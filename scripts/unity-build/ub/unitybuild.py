"""Unity builds, output collection, phone install and the outputs commit."""
import re
import shutil
import time
from pathlib import Path

from . import names
from .config import Game

UNITY_BIN = "/Applications/Unity/Hub/Editor/{}/Unity.app/Contents/MacOS/Unity"
PROFILE_DIR = "Assets/Settings/Build Profiles"
SUCCESS_LINE = "Build Finished, Result: Success."
BUILDINFO_DIR = "VersionTracker"
XCODE_PROJECT = "Unity-iPhone.xcodeproj"
XCODE_WORKSPACE = "Unity-iPhone.xcworkspace"


class StepFailed(Exception):
    """A pipeline step failed. The message says what and where."""


def unity_path(game: Game) -> str:
    pv = game.project_path / "ProjectSettings/ProjectVersion.txt"
    try:
        text = pv.read_text(encoding="utf-8")
    except OSError as e:
        raise StepFailed(f"Cannot read {pv}: {e.strerror or e}")
    m = re.search(r"^m_EditorVersion:\s*(\S+)", text, re.M)
    if not m:
        raise StepFailed(f"No m_EditorVersion in {pv}")
    unity = UNITY_BIN.format(m.group(1))
    if not Path(unity).is_file():
        raise StepFailed(f"Unity {m.group(1)} is not installed: {unity} does not exist")
    return unity


def build_target(game: Game, profile_key: str) -> str:
    """The -buildTarget for a profile: iOS when a stage lists it under "ios", else Android."""
    is_ios = any(profile_key in stage.get("ios", []) for stage in game.profiles.values())
    return "iOS" if is_ios else "Android"


def _regular_symbols(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.symbols.zip") if p.is_file()) if directory.is_dir() else []


def build(game: Game, profile_key: str, out_path: Path, log_path: Path, runner) -> float:
    """Run one Unity build profile and return its start time (for the output freshness check).

    Exit code 0 is not enough: the log must say it succeeded. Before the run, this build's own expected
    output file (and the symbols zips beside an AAB) are deleted, so an older file cannot pass for new.
    """
    out_path, log_path = Path(out_path), Path(log_path)
    cmd = [unity_path(game), "-batchmode", "-quit", "-projectPath", str(game.project_path)]
    if game.build_method:
        cmd += ["-buildTarget", build_target(game, profile_key), "-executeMethod", game.build_method,
                "-ubProfile", profile_key, "-ubOut", str(out_path)]
    else:
        cmd += ["-activeBuildProfile", f"{PROFILE_DIR}/{profile_key}.asset", "-build", str(out_path)]
    cmd += ["-logFile", str(log_path)]
    if out_path.is_file():
        out_path.unlink()
    if out_path.suffix == ".aab":
        for z in _regular_symbols(out_path.parent):
            z.unlink()
    log_path.unlink(missing_ok=True)
    start = time.time()
    try:
        r = runner.run(cmd, cwd=game.project_path)
    except OSError as e:
        raise StepFailed(f"Could not start Unity ({cmd[0]}): {e.strerror or e}")
    if r.code != 0:
        raise StepFailed(f"Unity exited {r.code} building {profile_key}. Log: {log_path}")
    try:
        log = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise StepFailed(f"Unity exited 0 building {profile_key} but wrote no log. Log: {log_path}")
    if SUCCESS_LINE not in log:
        raise StepFailed(f"Unity exited 0 but the log has no '{SUCCESS_LINE}' for {profile_key}. Log: {log_path}")
    return start


def _need(path: Path, since: float) -> Path:
    """A regular file that exists and was written since `since`."""
    if not path.is_file():
        raise StepFailed(f"Build reported success but this file is missing: {path}")
    if path.stat().st_mtime < since:
        raise StepFailed(f"Stale output, older than this build's start: {path}")
    return path


def _buildinfo(game: Game, ver: str, platform: str, out_dir: Path, since: float) -> Path:
    name = names.buildinfo(game, ver, platform)
    src = _need(game.project_path / BUILDINFO_DIR / name, since)
    dst = out_dir / name
    shutil.copyfile(src, dst)
    return dst


def _symbols(game: Game, ver: str, code: int, out_dir: Path, since: float) -> Path:
    """Unity writes the symbols zip beside the AAB under its own name. Collect it under the spec name."""
    want = out_dir / names.symbols(game, ver, code)
    if want.is_file():
        return _need(want, since)
    found = [p for p in _regular_symbols(out_dir) if p.stat().st_mtime >= since]
    if len(found) != 1:
        raise StepFailed(f"Build reported success but this file is missing: {want}"
                         + (f" ({len(found)} fresh symbols zips in {out_dir}, none chosen)" if found else ""))
    shutil.copyfile(found[0], want)  # copyfile, not copy2: the copy must not inherit an old mtime
    return want


def outputs_android(game: Game, ver: str, code: int, stage: str, since: float) -> list[Path]:
    """`since` is the start time `build()` returned; any output older than it is stale."""
    out = game.project_path / "Builds" / f"v{ver}" / "Android"
    if stage == "test":
        return [_need(out / names.test_apk(game, ver), since)]
    return [_need(out / names.release_apk(game, ver), since),
            _need(out / names.aab(game, ver, code), since),
            _symbols(game, ver, code, out, since),
            _buildinfo(game, ver, "Android", out, since)]


def outputs_ios(game: Game, ver: str, since: float) -> list[Path]:
    out = game.project_path / "Builds" / f"v{ver}" / "iOS"
    # The workspace comes from CocoaPods; Task 7 archives from it. Existence only: Unity may leave it untouched.
    ws = out / XCODE_WORKSPACE
    if not ws.exists():
        raise StepFailed(f"Build reported success but this file is missing: {ws}")
    proj = out / XCODE_PROJECT
    # A directory's mtime does not move when Unity rewrites a file in it, so judge freshness by the pbxproj.
    if not proj.is_dir():
        raise StepFailed(f"Build reported success but this folder is missing: {proj}")
    _need(proj / "project.pbxproj", since)
    return [proj, ws, _buildinfo(game, ver, "iOS", out, since)]


def install_apk(path: Path, runner) -> bool:
    """`-r` keeps the app's data. False when no phone is in the `device` state.
    A failed install on a present phone raises StepFailed quoting adb's error line.

    One phone can be listed twice (USB and wireless), so the install always names a serial:
    the first `device` entry with a `usb:` field, else the first `device` entry.
    """
    try:
        r = runner.run(["adb", "devices", "-l"])
    except OSError as e:
        raise StepFailed(f"adb could not run: {e.strerror or e}")
    ready = []  # (serial, is_usb)
    for ln in r.out.splitlines()[1:]:
        parts = ln.split()
        if len(parts) >= 2 and parts[1] == "device":
            ready.append((parts[0], any(f.startswith("usb:") for f in parts[2:])))
    if not ready:
        return False
    serial = next((sr for sr, usb in ready if usb), ready[0][0])
    try:
        r = runner.run(["adb", "-s", serial, "install", "-r", str(path)])
    except OSError as e:
        raise StepFailed(f"adb could not run: {e.strerror or e}")
    if r.code != 0:
        raise StepFailed(f"adb install on {serial} failed (exit {r.code}): {_error_line(r.out + chr(10) + r.err)}")
    return True


def _error_line(text: str) -> str:
    """The tool's own error line: the first line naming a failure or error, else the last non-empty line."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hit = next((ln for ln in lines if "failure" in ln.lower() or "error" in ln.lower()), None)
    return hit or (lines[-1] if lines else "no output")


def _git(runner, game, *args):
    return runner.run(["git", "--literal-pathspecs", *args], cwd=game.project_path)


def _paths(runner, game, *args) -> list[str]:
    r = _git(runner, game, *args)
    if r.code != 0:
        raise StepFailed(f"`git {' '.join(args)}` failed: {r.err.strip() or 'exit ' + str(r.code)}")
    return [p for p in r.out.split("\0") if p]


def commit_outputs(game: Game, label: str, runner) -> str | None:
    """Commit what a build changed, by explicit path. `label` is like 'v0.1.7 test'. Returns the sha, or None."""
    skip = tuple(game.session_paths)
    keep = []
    for p in _paths(runner, game, "diff", "-z", "--name-only", "HEAD"):
        if p.startswith(skip):
            continue
        # A CRLF-only rewrite (AndroidManifest.xml) is not a change worth committing.
        q = _git(runner, game, "diff", "--ignore-cr-at-eol", "--quiet", "HEAD", "--", p)
        if q.code == 1:
            keep.append(p)
        elif q.code != 0:
            raise StepFailed(f"`git diff --quiet` failed on {p}: {q.err.strip() or 'exit ' + str(q.code)}")
    for p in _paths(runner, game, "ls-files", "-z", "--others", "--exclude-standard", "--", f"{BUILDINFO_DIR}/"):
        if not p.startswith(skip):
            keep.append(p)
    if not keep:
        return None
    r = _git(runner, game, "add", "--", *keep)
    if r.code != 0:
        raise StepFailed(f"git add failed: {r.err.strip()}")
    r = _git(runner, game, "commit", "-m", f"chore(build): record {label} outputs", "--", *keep)
    if r.code != 0:
        raise StepFailed(f"git commit failed: {r.err.strip() or r.out.strip()}")
    return _git(runner, game, "rev-parse", "HEAD").out.strip()
