"""Addressables upload to MinIO through an rclone S3 remote.

Bundles are add-only. Catalog and hash files may be replaced, except in a frozen production folder.
Never syncs, moves, links or deletes.
"""
import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from .config import Game
from .runner import Runner
from .unitybuild import StepFailed

_CATALOG = re.compile(r"^catalog_.*\.(bin|json)$")
_HASH = re.compile(r"^catalog_.*\.hash$")
_AUTH = ("signaturedoesnotmatch", "invalidaccesskeyid", "accessdenied", "nocredentialproviders",
         "didn't find section in config file", "credential")


class MinioNameClash(StepFailed):
    """MinIO holds a bundle of the same name with different content. Nothing was uploaded."""


class ProductionFrozen(StepFailed):
    """A production folder already holds a catalog this run did not upload. Nothing was uploaded."""


def _sign_in_steps(ota: dict) -> str:
    # Never put the key on a command line: a `!` command's text reaches the chat, and shells keep history.
    # The S3 API sits behind Cloudflare, which rewrites Accept-Encoding, so that header must stay unsigned.
    return (f"Recreate the MinIO sign-in. Create a new access key in the MinIO console. Then, in your own "
            f"Terminal app and not through Claude, run `rclone config`, and edit or add the remote "
            f"'{ota['remote']}': type s3, provider Minio, endpoint {ota['endpoint']}, then type the access key "
            "and secret at the prompts. In the advanced options, set sign_accept_encoding to false. "
            "Paste nothing back; the tool checks the sign-in itself.")


def _err(game: Game, res) -> str:
    lines = [ln for ln in res.err.strip().splitlines()
             if not re.search(r"access_key|secret|AKIA[0-9A-Z]+", ln, re.I)]
    text = "\n".join(lines).strip()
    if any(w in res.err.lower() for w in _AUTH):
        text = (text + " " if text else "") + _sign_in_steps(game.ota)
    return text or f"exit {res.code}"


def _kind(name: str) -> int:
    """0 bundle, 1 hash, 2 catalog: the upload order."""
    return 2 if _CATALOG.match(name) else 1 if _HASH.match(name) else 0


def _is_catalog_file(name: str) -> bool:
    return _kind(name) > 0


def local_dir(game: Game, profile: str, platform: str, ver: str) -> Path:
    return game.project_path / "Builds/ServerData" / profile / platform / f"v{ver}"


def remote_url(game: Game, profile: str, platform: str, ver: str) -> str:
    return f"{game.ota['cdn_base']}/{profile}/{platform}/v{ver}/"


def _remote_base(game: Game, profile: str, platform: str, ver: str) -> str:
    return f"{game.ota['remote']}:{game.ota['bucket']}/{profile}/{platform}/v{ver}"


def ota_outputs(game: Game, profile: str, platform: str, ver: str, since: float) -> list[Path]:
    """The build's ServerData files to upload, in upload order. Stops on a missing or stale folder.

    Addressables never empties the folder, so a retest of the same version finds older catalogs beside the
    new one. Only catalog and hash files written by this build are returned; every bundle is returned, and
    the add-only upload skips the ones already on MinIO.
    """
    root = local_dir(game, profile, platform, ver)
    if not root.is_dir():
        raise StepFailed(f"The build wrote no Addressables ServerData folder: {root}")
    files = [p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")]
    bundles = [p for p in files if _kind(p.name) == 0]
    fresh = [p for p in files if _kind(p.name) > 0 and p.stat().st_mtime >= since]
    catalogs = [p for p in fresh if _kind(p.name) == 2]
    hashes = [p for p in fresh if _kind(p.name) == 1]
    if not bundles:
        raise StepFailed(f"{root} holds no bundles.")
    if not catalogs or not hashes:
        raise StepFailed(f"{root} has no catalog newer than this build start (found {len(catalogs)} new catalog "
                         f"and {len(hashes)} new hash files). The build did not write its Addressables output, "
                         "so nothing is uploaded.")
    return sorted(bundles + fresh, key=lambda p: (_kind(p.name), p.relative_to(root).as_posix()))


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _list(game: Game, base: str, runner: Runner) -> dict[str, dict]:
    res = runner.run(["rclone", "lsjson", base, "--hash", "--recursive", "--files-only"])
    if res.code == 3 or (res.code != 0 and "directory not found" in res.err.lower()):
        return {}  # some rclone versions report a prefix with no objects yet this way
    if res.code != 0:
        raise StepFailed(f"rclone lsjson of '{base}' failed: {_err(game, res)}")
    try:
        entries = json.loads(res.out)
    except json.JSONDecodeError as e:
        raise StepFailed(f"rclone lsjson of '{base}' gave unreadable output: {e}")
    if not isinstance(entries, list):
        raise StepFailed(f"rclone lsjson of '{base}' did not give a list")
    return {e["Path"]: e for e in entries if not e.get("IsDir")}


def _matches(game: Game, entry: dict, path: Path, root: Path, base: str, rel: str, runner: Runner) -> bool:
    """Byte-equal: size, then the listed MD5, or a one-file `check --download` when MinIO lists none."""
    if entry.get("Size") != path.stat().st_size:
        return False
    remote = (entry.get("Hashes") or {}).get("md5")
    if remote:
        return remote.lower() == _md5(path)
    res = runner.run(["rclone", "check", str(root), base, "--download", "--one-way",
                      "--include", "/" + _glob_escape(rel)])
    return res.code == 0


def _glob_escape(name: str) -> str:
    return re.sub(r"([\[\]{}*?\\])", r"\\\1", name)


def upload(game: Game, profile: str, platform: str, ver: str, files: list[Path], runner: Runner,
           may_replace_catalog: bool, before_first_copy: Callable[[], None] | None = None) -> int:
    """Upload `files` (from `ota_outputs`) and verify them. Returns how many files were copied.

    Every clash is decided from one listing before the first copy, so a stop changes nothing on MinIO.
    `before_first_copy` runs after those checks pass and before the first copy. Bundles, then hash, then
    catalog are each copied and verified before the next kind starts, so a catalog never goes live
    pointing at a bad bundle.
    """
    root = local_dir(game, profile, platform, ver)
    base = _remote_base(game, profile, platform, ver)
    ordered = sorted(files, key=lambda p: (_kind(p.name), p.relative_to(root).as_posix()))
    rel = {p: p.relative_to(root).as_posix() for p in ordered}
    present = _list(game, base, runner)
    same = {p for p in ordered if rel[p] in present
            and _matches(game, present[rel[p]], p, root, base, rel[p], runner)}

    if not may_replace_catalog:
        ours = {rel[p] for p in same}
        frozen = sorted(n for n in present if _is_catalog_file(Path(n).name) and n not in ours)
        if frozen:
            raise ProductionFrozen(f"{base} already holds {frozen[0]}, which this run did not upload. A live "
                                   "version's production folder is never changed. Nothing was uploaded.")
    todo = []
    for p in ordered:
        if p in same:
            continue
        if rel[p] in present and not _is_catalog_file(p.name):
            raise MinioNameClash(f"{base}/{rel[p]} already exists with different content. Bundle names carry "
                                 "a content hash, so this should not happen. Nothing was uploaded.")
        todo.append(p)

    if todo and before_first_copy:
        before_first_copy()
    for kind in (0, 1, 2):
        batch = [p for p in todo if _kind(p.name) == kind]
        if not batch:
            continue
        for p in batch:
            res = runner.run(["rclone", "copyto", str(p), f"{base}/{rel[p]}"])
            if res.code != 0:
                raise StepFailed(f"Upload of '{rel[p]}' to {base} failed: {_err(game, res)}")
        after = _list(game, base, runner)
        for p in batch:
            entry = after.get(rel[p])
            if entry is None or not _matches(game, entry, p, root, base, rel[p], runner):
                raise StepFailed(f"'{rel[p]}' in {base} is missing or differs from the local file after upload. "
                                 "Later files were not uploaded.")
    return len(todo)
