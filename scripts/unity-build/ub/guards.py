"""Release-only settings that a dev merge must not change.

A snapshot holds the guarded values from one source. `snapshot` reads the working tree, and
`snapshot_ref` reads a git ref (`git show <ref>:<path>`) or the index (ref ""). `violations` compares a
baseline snapshot with an after snapshot, which defaults to the working tree. The stages compare
`baseline_ref(game)`, the remote-tracking release branch, with the index the merge commit is made from:
the tool never pushes, so nothing it or a local hand merge does can move that baseline. The game's
`guards` settings name the files and values. A `required` value is checked on the after side, so a
baseline that already holds a wrong value still fails.

The guards fail closed: a missing file, an unreadable defines block, or a protected key with no
baseline value is a violation, never a pass.
"""
import re
from pathlib import Path

_DEFINES_HEAD = re.compile(r"^([ \t]*)scriptingDefineSymbols:[ \t]*(\{\})?[ \t]*\r?$", re.M)


BASELINE_REMOTE = "origin"


def baseline_ref(game) -> str:
    """The remote-tracking release branch, e.g. refs/remotes/origin/release. Never fetched by the tool."""
    return f"refs/remotes/{BASELINE_REMOTE}/{game.release_branch}"


def _guarded_files(game) -> list[str]:
    g = game.guards
    files = [i["file"] for k in ("keep_value", "forbidden_defines", "forbidden_attributes") for i in g.get(k, [])]
    return list(dict.fromkeys(files))


def _read(root: Path, rel: str) -> str | None:
    p = root / rel
    return p.read_bytes().decode("utf-8", "replace") if p.is_file() else None


def _value(text: str | None, key: str) -> str | None:
    if text is None:
        return None
    m = re.search(rf"^[ \t]*{re.escape(key)}:[ \t]*([^\r\n]*?)[ \t]*\r?$", text, re.M)
    return m.group(1) if m else None


def _defines(text: str | None) -> dict | None:
    """Platform name to its list of define symbols. None when the block is missing or unreadable."""
    if text is None:
        return None
    head = _DEFINES_HEAD.search(text)
    if head is None:
        return None
    if head.group(2):
        return {}  # "scriptingDefineSymbols: {}" means no defines on any platform
    out, indent = {}, len(head.group(1))
    # head.end() sits just before the newline, so element 0 is the empty rest of the head line.
    for line in text[head.end():].splitlines()[1:]:
        if not line.strip():
            continue
        if len(line) - len(line.lstrip(" \t")) <= indent:
            break
        name, sep, value = line.strip().partition(":")
        if not sep:
            return None
        out[name.strip()] = [s for s in (x.strip() for x in value.split(";")) if s]
    return out or None  # a header with no entries under it is not a shape Unity writes


def _attr(text: str | None, attr: str) -> str | None:
    if text is None:
        return None
    m = re.search(rf"""{re.escape(attr)}\s*=\s*(["'])(.*?)\1""", text, re.S)
    return m.group(2) if m else None


def _snapshot(game, read) -> dict:
    g = game.guards
    texts = {f: read(f) for f in _guarded_files(game)}
    snap = {"values": {}, "defines": {}, "attributes": {},
            "missing": sorted(f for f, t in texts.items() if t is None)}
    for item in g.get("keep_value", []):
        snap["values"][(item["file"], item["key"])] = _value(texts[item["file"]], item["key"])
    for item in g.get("forbidden_defines", []):
        snap["defines"][item["file"]] = _defines(texts[item["file"]])
    for item in g.get("forbidden_attributes", []):
        snap["attributes"][(item["file"], item["attribute"])] = _attr(texts[item["file"]], item["attribute"])
    return snap


def snapshot(game, runner=None) -> dict:
    """The guarded values as they are now. `runner` is unused; files are read from disk."""
    return _snapshot(game, lambda rel: _read(game.project_path, rel))


def snapshot_ref(game, ref: str, runner) -> dict:
    """The guarded values at a git ref, or in the index when `ref` is "".

    A missing ref or a missing file reads as absent, so `violations` reports it (fail closed).
    """
    def read(rel):
        r = runner.run(["git", "show", f"{ref}:{rel}"], cwd=game.project_path)
        return r.out if r.code == 0 else None
    return _snapshot(game, read)


def _show(v) -> str:
    return "absent" if v is None else repr(v)


def violations(game, before: dict, runner=None, after: dict | None = None) -> list[str]:
    """One message per broken guard, naming the file, the setting, and the before and after values.

    `after` defaults to the working tree; pass `snapshot_ref(...)` to check a commit or the index.
    Run it only once no unmerged paths remain. A file that still holds conflict markers would be
    read as release's side and could pass when it should not.
    """
    g, out = game.guards, []
    after = snapshot(game, runner) if after is None else after
    gone = set(after["missing"])
    out += [f"{f}: the file is missing from the baseline (before the merge), so its release values "
            "cannot be checked." for f in before.get("missing", [])]

    def _missing(_game, rel):
        return rel in gone
    for item in g.get("keep_value", []):
        f, key = item["file"], item["key"]
        was, now = before["values"].get((f, key)), after["values"][(f, key)]
        if _missing(game, f):
            out.append(f"{f}: the file is missing after the merge, so {key} cannot be checked "
                       f"(before the merge: {_show(was)}).")
        elif was is None:
            out.append(f"{f}: {key} was not found before the merge (after: {_show(now)}), so there is "
                       f"no release value to protect. Check the file and this game's guard settings.")
        elif now != was:
            out.append(f"{f}: {key} changed from {_show(was)} to {_show(now)}. Restore {_show(was)}.")
        elif "required" in item and now != item["required"]:
            out.append(f"{f}: {key} is {_show(now)} (before the merge: {_show(was)}), "
                       f"but release needs {item['required']!r}.")
    for item in g.get("forbidden_defines", []):
        f, syms = item["file"], ", ".join(item["symbols"])
        was_all, now_all = before["defines"].get(item["file"]), after["defines"][item["file"]]
        if _missing(game, f):
            out.append(f"{f}: the file is missing after the merge, so {syms} cannot be checked.")
            continue
        if now_all is None:
            out.append(f"{f}: the scriptingDefineSymbols block was not found or could not be read, "
                       f"so {syms} cannot be checked.")
            continue
        for platform in item["platforms"]:
            was, now = (was_all or {}).get(platform, []), now_all.get(platform, [])
            for sym in item["symbols"]:
                if sym in now:
                    state = "present" if sym in was else "absent"
                    out.append(f"{f}: {platform} scripting defines contain {sym} "
                               f"(before the merge: {state}, after: present). Remove {sym}.")
    for item in g.get("forbidden_attributes", []):
        f, attr = item["file"], item["attribute"]
        was, now = before["attributes"].get((f, attr)), after["attributes"][(f, attr)]
        if _missing(game, f):
            out.append(f"{f}: the file is missing after the merge, so {attr} cannot be checked.")
        elif now is not None:
            out.append(f"{f}: {attr} is {_show(now)} (before the merge: {_show(was)}). Remove the attribute.")
    return out


def release_violations(game, snap: dict) -> list[str]:
    """Check one snapshot against the release rules alone, with no baseline. For a single-branch game,
    where the release builds the tested commit as it is and no merge can move a value.

    A `keep_value` item is checked only when it names a `required` value. Fails closed like `violations`.
    """
    g, out = game.guards, []
    gone = set(snap["missing"])
    out += [f"{f}: the file is missing, so its release values cannot be checked." for f in snap["missing"]]
    for item in g.get("keep_value", []):
        f, key = item["file"], item["key"]
        if f in gone or "required" not in item:
            continue
        now = snap["values"][(f, key)]
        if now != item["required"]:
            out.append(f"{f}: {key} is {_show(now)}, but release needs {item['required']!r}.")
    for item in g.get("forbidden_defines", []):
        f, syms = item["file"], ", ".join(item["symbols"])
        if f in gone:
            continue
        now_all = snap["defines"][f]
        if now_all is None:
            out.append(f"{f}: the scriptingDefineSymbols block was not found or could not be read, "
                       f"so {syms} cannot be checked.")
            continue
        for platform in item["platforms"]:
            for sym in item["symbols"]:
                if sym in now_all.get(platform, []):
                    out.append(f"{f}: {platform} scripting defines contain {sym}. Remove {sym}.")
    for item in g.get("forbidden_attributes", []):
        f, attr = item["file"], item["attribute"]
        now = snap["attributes"][(f, attr)]
        if f not in gone and now is not None:
            out.append(f"{f}: {attr} is {_show(now)}. Remove the attribute.")
    return out
