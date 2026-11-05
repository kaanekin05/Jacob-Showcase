"""Google Drive upload through rclone. Never shares, links, overwrites or deletes."""
import hashlib
import json
from pathlib import Path

from .config import Game
from .runner import Runner
from .unitybuild import StepFailed

REMOTE = "studio-drive"
# Never `rclone config reconnect`: its fallback has the user paste the OAuth token, which would reach the chat.
SIGN_IN_STEPS = (f"Sign in again in two steps. Run `! rclone config delete {REMOTE}`, then "
                 f"`! rclone config create {REMOTE} drive scope=drive > /dev/null`. "
                 "Paste nothing back; the tool checks the sign-in itself.")
_AUTH_WORDS = ("token", "oauth", "auth")


def _rclone_err(res) -> str:
    """rclone's stderr for a message. Lines that suggest `config reconnect` are dropped, and sign-in steps added."""
    lines = res.err.strip().splitlines()
    kept = [ln for ln in lines if "config reconnect" not in ln]
    text = "\n".join(kept).strip()
    if len(kept) < len(lines) or any(w in text.lower() for w in _AUTH_WORDS):
        text = (text + " " if text else "") + SIGN_IN_STEPS
    return text


class DriveNameClash(StepFailed):
    """Drive already holds a file of the same name with different content. Nothing was overwritten."""


def folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}?usp=drive_link"


def file_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view?usp=drive_link"


def _root(game: Game) -> list[str]:
    if not game.drive_folder_id.strip():
        # Without the flag value rclone would fall back to the My Drive root.
        raise StepFailed("This game has no Drive folder ID in its settings. Refusing to touch Drive.")
    return ["--drive-root-folder-id", game.drive_folder_id]


def _lsjson(game: Game, path: str, runner: Runner, hashes: bool = False) -> list[dict]:
    # Judge success by exit code only. rclone prints a NOTICE on stderr every call.
    cmd = ["rclone", "lsjson", f"{REMOTE}:{path}", *_root(game)]
    if hashes:
        cmd.append("--hash")
    res = runner.run(cmd)
    if res.code != 0:
        raise StepFailed(f"rclone lsjson of '{path or 'the root folder'}' failed: {_rclone_err(res)}")
    where = path or "the root folder"
    if not res.out.strip():
        raise StepFailed(f"rclone lsjson of '{where}' exited 0 but printed nothing")
    try:
        entries = json.loads(res.out)
    except json.JSONDecodeError as e:
        raise StepFailed(f"rclone lsjson of '{where}' gave unreadable output: {e}")
    if not isinstance(entries, list):
        raise StepFailed(f"rclone lsjson of '{where}' did not give a list")
    return entries


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_folder(entries: list[dict], name: str) -> str | None:
    found = [e for e in entries if e.get("IsDir") and e["Name"] == name]
    if len(found) > 1:
        raise StepFailed(f"Drive holds {len(found)} folders named '{name}'. "
                         "Merge them by hand, then rerun.")
    return found[0]["ID"] if found else None


def ensure_version_folder(game: Game, ver: str, runner: Runner) -> str:
    name = f"v{ver}"
    existing = _find_folder(_lsjson(game, "", runner), name)
    if existing:
        return existing
    res = runner.run(["rclone", "mkdir", f"{REMOTE}:{name}", *_root(game)])
    if res.code != 0:
        raise StepFailed(f"Could not create Drive folder '{name}': {_rclone_err(res)}")
    created = _find_folder(_lsjson(game, "", runner), name)
    if not created:
        raise StepFailed(f"Drive folder '{name}' is not listed after creating it")
    return created


def _index(entries: list[dict], wanted: set[str], folder: str) -> dict[str, dict]:
    by_name: dict[str, dict] = {}
    for e in entries:
        if e.get("IsDir") or e["Name"] not in wanted:
            continue
        if e["Name"] in by_name:
            raise StepFailed(f"Drive folder '{folder}' holds two files named '{e['Name']}'. "
                             "Merge them by hand, then rerun.")
        by_name[e["Name"]] = e
    return by_name


def remote_file(game: Game, folder_name: str, name: str, runner: Runner) -> dict | None:
    """Read-only: the lsjson entry (with hashes) for `name` in the version folder, or None if either is missing."""
    if not _find_folder(_lsjson(game, "", runner), folder_name):
        return None
    return _index(_lsjson(game, folder_name, runner, hashes=True), {name}, folder_name).get(name)


def same_content(entry: dict, path: Path) -> bool:
    """The same test `upload` uses to skip a file: equal size, and equal MD5 when Drive lists one."""
    if entry.get("Size") != path.stat().st_size:
        return False
    remote_md5 = (entry.get("Hashes") or {}).get("md5")
    return not remote_md5 or remote_md5.lower() == _md5(path)


def upload(game: Game, folder_name: str, files: list[Path], runner: Runner) -> dict[str, str]:
    """Upload files into the existing version folder. Returns {file name: link}."""
    names = [f.name for f in files]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise StepFailed(f"Two files to upload share the name '{dupes[0]}'. Nothing was uploaded.")
    sizes = {}
    for f in files:
        try:
            sizes[f.name] = f.stat().st_size
        except OSError as e:
            raise StepFailed(f"Cannot read local file {f}: {e.strerror or e}. Nothing was uploaded.")
    if not _find_folder(_lsjson(game, "", runner), folder_name):
        raise StepFailed(f"Drive folder '{folder_name}' does not exist")
    wanted = set(names)
    present = _index(_lsjson(game, folder_name, runner, hashes=True), wanted, folder_name)
    uploaded = False
    for f in files:
        size = sizes[f.name]
        have = present.get(f.name)
        if have is not None:
            fix = "Delete or rename the old file in Drive, then rerun."
            if have.get("Size") != size:
                raise DriveNameClash(f"Drive already has '{f.name}' in '{folder_name}' with a different "
                                 f"size ({have.get('Size')} bytes, local {size}). "
                                 f"Not overwriting. {fix}")
            remote_md5 = (have.get("Hashes") or {}).get("md5")
            # If Drive lists no MD5, fall back to the size-only skip.
            if remote_md5 and remote_md5.lower() != _md5(f):
                raise DriveNameClash(f"Drive already has '{f.name}' in '{folder_name}' with the same "
                                 f"size but different content (MD5 differs). Not overwriting. {fix}")
            continue
        # No timeout: APKs and AABs are about 220 MB each.
        res = runner.run(["rclone", "copyto", str(f), f"{REMOTE}:{folder_name}/{f.name}", *_root(game)])
        if res.code != 0:
            raise StepFailed(f"Upload of '{f.name}' failed: {_rclone_err(res)}")
        uploaded = True
    final = _index(_lsjson(game, folder_name, runner), wanted, folder_name) if uploaded else present
    urls = {}
    for f in files:
        if f.name not in final:
            raise StepFailed(f"'{f.name}' is not in Drive folder '{folder_name}' after upload")
        urls[f.name] = file_url(final[f.name]["ID"])
    return urls
