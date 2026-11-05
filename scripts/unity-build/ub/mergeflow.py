"""Merge dev into release, auto-resolving the conflicts that have a safe answer.

Direction is fixed: the release branch must be checked out, and dev is never written. A conflict
with no safe answer stays in the working tree with MERGE_HEAD in place, for the user to decide.
Staging is by explicit path only, and nothing is ever pushed.

`merge_dev` never commits. The merge stays staged with MERGE_HEAD kept, so the caller can run the
guards first. `conclude_merge` makes the merge commit.
"""
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ub.versions import version_key

PROJECT_SETTINGS = "ProjectSettings/ProjectSettings.asset"

_VERSION_LINE = re.compile(r"^[ \t]*bundleVersion:[ \t]*(\d+(?:\.\d+)*)[ \t]*$")
_ANDROID_LINE = re.compile(r"^[ \t]*AndroidBundleVersionCode:[ \t]*(\d+)[ \t]*$")
_IOS_LINE = re.compile(r"^([ \t]*)iPhone:[ \t]*(\d+)[ \t]*$")


class MergeError(Exception):
    pass


@dataclass(frozen=True)
class Conflict:
    path: str
    ours: str    # release's side
    theirs: str  # dev's side


@dataclass
class MergeResult:
    status: str  # "up_to_date", "clean", "resolved" or "needs_decision"
    pending: list = field(default_factory=list)


def _git(game, runner, *args, check=True):
    r = runner.run(["git", *args], cwd=game.project_path)
    if check and r.code != 0:
        raise MergeError(f"git {' '.join(args)} failed: {(r.err or r.out).strip()}")
    return r


def _merge_in_progress(game, runner) -> bool:
    return _git(game, runner, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).code == 0


def _unmerged(game, runner) -> dict:
    """Unmerged path to the set of index stages it has (1 base, 2 ours, 3 theirs)."""
    out = {}
    for rec in _git(game, runner, "ls-files", "-u", "-z").out.split("\0"):
        if rec:
            meta, path = rec.split("\t", 1)
            out.setdefault(path, set()).add(int(meta.split()[2]))
    return out


def _take(game, runner, path, stages, side):
    """Resolve `path` to one side. A side without a stage means that branch deleted the file."""
    if side in stages:
        _git(game, runner, "checkout", "--ours" if side == 2 else "--theirs", "--", path)
        _git(game, runner, "add", "--", path)
    else:
        _git(game, runner, "rm", "-q", "--", path)


# ---- per-hunk handling of conflict markers ----

def _parse(lines):
    """Split a conflicted file into text runs and (ours, theirs) hunks. Lines keep their endings.

    Returns None when the markers are malformed: a hunk with no `=======` or no closing `>>>>>>>`,
    or a stray `>>>>>>>` outside a hunk.
    """
    segs, i = [], 0
    while i < len(lines):
        if lines[i].startswith("<<<<<<<"):
            ours, theirs, part, j = [], [], "ours", i + 1
            while j < len(lines) and not lines[j].startswith(">>>>>>>"):
                tag = lines[j][:7]
                if tag == "<<<<<<<":
                    return None
                if tag == "|||||||":
                    part = "base"
                elif tag == "=======" and lines[j].rstrip("\r\n") == "=======":
                    part = "theirs"
                elif part == "ours":
                    ours.append(lines[j])
                elif part == "theirs":
                    theirs.append(lines[j])
                j += 1
            if j == len(lines) or part != "theirs":
                return None
            segs.append((ours, theirs, lines[i:j + 1]))
            i = j + 1
        elif lines[i].startswith(">>>>>>>"):
            return None
        else:
            segs.append(lines[i])
            i += 1
    return segs


def _parent_is_build_number(before, indent):
    for line in reversed(before):
        s = line.rstrip("\r\n")
        if not s.strip():
            continue
        if len(s) - len(s.lstrip(" \t")) < indent:
            return s.strip() == "buildNumber:"
    return False


def _version_kind(line, before):
    """('kind', comparable) for one of the three version lines, else None."""
    s = line.rstrip("\r\n")
    if m := _VERSION_LINE.match(s):
        return "bundleVersion", version_key(m.group(1))
    if m := _ANDROID_LINE.match(s):
        return "AndroidBundleVersionCode", int(m.group(1))
    if (m := _IOS_LINE.match(s)) and _parent_is_build_number(before, len(m.group(1))):
        return "buildNumber/iPhone", int(m.group(2))
    return None


def _version_hunk(ours, theirs, before) -> bool:
    """True when every changed line is a version line and dev's number is not lower.

    Git folds unchanged lines between nearby changes into one hunk (the iPhone build number and
    AndroidBundleVersionCode sit three lines apart), so lines identical on both sides are allowed.
    """
    if len(ours) != len(theirs):
        return False
    changed = False
    for k, (o, t) in enumerate(zip(ours, theirs)):
        if o.rstrip("\r\n") == t.rstrip("\r\n"):
            continue
        ctx = before + ours[:k]
        ko, kt = _version_kind(o, ctx), _version_kind(t, ctx)
        if ko is None or kt is None or ko[0] != kt[0] or kt[1] < ko[1]:
            return False
        changed = True
    return changed


def _resolve_project_settings(game, path):
    """Resolve version-only hunks to dev's lines. Returns the hunks left for the user.

    Returns None, and leaves the file untouched, when it has no parseable conflict markers. A
    merge driver can fail without writing markers, and then nothing in the file is safe to stage.
    """
    p = game.project_path / path
    raw = p.read_bytes().decode("utf-8", "surrogateescape")
    segs = _parse(raw.splitlines(keepends=True))
    if not segs or all(isinstance(s, str) for s in segs):
        return None
    out, left = [], []
    for seg in segs:
        if isinstance(seg, str):
            out.append(seg)
        elif _version_hunk(seg[0], seg[1], out):
            out.extend(seg[1])
        else:
            out.extend(seg[2])
            left.append(seg)
    p.write_bytes("".join(out).encode("utf-8", "surrogateescape"))
    return left


# ---- presenting a conflict ----

def _side(game, runner, path, stage, stages):
    if stage not in stages:
        return "(deleted on this branch)"
    r = runner.run(["git", "show", f":{stage}:{path}"], cwd=game.project_path)
    return "(binary file)" if "\0" in r.out else r.out


def _conflict(game, runner, path, stages, hunks=None):
    if hunks is None:
        p = game.project_path / path
        if p.is_file() and b"\0" not in (data := p.read_bytes()):
            segs = _parse(data.decode("utf-8", "replace").splitlines(keepends=True)) or []
            hunks = [s for s in segs if not isinstance(s, str)]
    if hunks:
        sep = "\n...\n"
        return Conflict(path, sep.join("".join(h[0]) for h in hunks), sep.join("".join(h[1]) for h in hunks))
    return Conflict(path, _side(game, runner, path, 2, stages), _side(game, runner, path, 3, stages))


# ---- public API ----

def merge_dev(game, runner) -> MergeResult:
    branch = _git(game, runner, "symbolic-ref", "--short", "HEAD", check=False).out.strip()
    if branch != game.release_branch:
        raise MergeError(f"Check out '{game.release_branch}' before merging; '{branch}' is checked out. "
                         f"The merge only goes from '{game.dev_branch}' into '{game.release_branch}'.")
    if _merge_in_progress(game, runner):
        raise MergeError("A merge is already in progress. Decide its conflicts and conclude it first.")

    r = _git(game, runner, "merge", "--no-ff", "--no-commit", "--no-edit", game.dev_branch, check=False)
    conflicts = _unmerged(game, runner)
    if r.code != 0 and not conflicts:
        raise MergeError(f"git merge {game.dev_branch} failed: {(r.err or r.out).strip()}")
    if not _merge_in_progress(game, runner):
        return MergeResult("up_to_date")

    pending = []
    for path, stages in sorted(conflicts.items()):
        if any(path.startswith(s) for s in game.session_paths):
            _take(game, runner, path, stages, 2)
        elif PurePosixPath(path).name in game.regenerated_names:
            _take(game, runner, path, stages, 2 if 2 in stages else 3)
        elif path == PROJECT_SETTINGS and stages >= {2, 3}:
            left = _resolve_project_settings(game, path)
            if left is None:
                pending.append(_conflict(game, runner, path, stages))
            elif left:
                pending.append(_conflict(game, runner, path, stages, left))
            else:
                _git(game, runner, "add", "--", path)
        else:
            pending.append(_conflict(game, runner, path, stages))

    if pending:
        return MergeResult("needs_decision", pending)
    return MergeResult("resolved" if conflicts else "clean")


def conclude_merge(game, runner) -> None:
    """Commit the merge. Call it only after the guards pass and the user's decisions are staged.

    A no-op when no merge is in progress, which is the "up_to_date" case.
    """
    if not _merge_in_progress(game, runner):
        return
    left = sorted(_unmerged(game, runner))
    if left:
        raise MergeError("These paths still have unresolved conflicts: " + ", ".join(left)
                         + ". Resolve each one and stage it by path first.")
    _git(game, runner, "commit", "--no-edit", "-q")
