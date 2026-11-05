"""iOS archive, SDK check, dSYMs, phone install and TestFlight upload."""
import json
import plistlib
import tempfile
import zipfile
from pathlib import Path

from .config import Game
from .unitybuild import XCODE_PROJECT, XCODE_WORKSPACE, StepFailed

SCHEME = "Unity-iPhone"
AUTH_HINTS = ("account", "authenticat", "session", "sign in", "signed in", "credential")


def _run(runner, cmd, what):
    try:
        return runner.run(cmd)
    except OSError as e:
        raise StepFailed(f"Could not run {what}: {e.strerror or e}")


def _first_error(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if "error:" in ln), "")


def archive(game: Game, ver: str, runner) -> Path:
    """Archive Unity's Xcode project. The workspace wins when it exists (CocoaPods needs it)."""
    out_dir = game.project_path / "Builds" / f"v{ver}" / "iOS"
    ws, proj = out_dir / XCODE_WORKSPACE, out_dir / XCODE_PROJECT
    if ws.exists():
        target = ["-workspace", str(ws)]
    elif proj.exists():
        target = ["-project", str(proj)]
    else:
        raise StepFailed(f"No Xcode workspace or project in {out_dir}")
    arc = out_dir / f"{game.product_name}.xcarchive"
    log = out_dir / "xcodebuild-archive.log"
    cmd = ["xcodebuild", *target, "-scheme", SCHEME, "-configuration", "Release",
           "-destination", "generic/platform=iOS", "-archivePath", str(arc), "archive",
           "-allowProvisioningUpdates"]
    r = _run(runner, cmd, "xcodebuild")
    log.write_text(r.out + ("\n" + r.err if r.err else ""), encoding="utf-8")
    if r.code != 0:
        err = _first_error(r.out + "\n" + r.err)
        raise StepFailed(f"xcodebuild archive exited {r.code}. Log: {log}" + (f"\nFirst error: {err}" if err else ""))
    return arc


def _app(archive_path: Path) -> Path:
    apps = sorted((Path(archive_path) / "Products" / "Applications").glob("*.app"))
    if len(apps) != 1:
        raise StepFailed(f"Expected exactly one .app in {archive_path}/Products/Applications, found {len(apps)}")
    return apps[0]


def _app_plist(archive_path: Path) -> dict:
    plist = _app(archive_path) / "Info.plist"
    try:
        return plistlib.loads(plist.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError) as e:
        raise StepFailed(f"Cannot read {plist}: {e}")


def check_sdk(game: Game, archive_path: Path) -> str:
    """Stop unless the archive was built with the pinned iOS SDK. Returns the SDK name."""
    sdk = _app_plist(archive_path).get("DTSDKName", "")
    if not sdk.startswith(game.sdk_prefix):
        raise StepFailed(
            f"The archive was built with SDK '{sdk or 'unknown'}', not '{game.sdk_prefix}x'. Unity 6000.0.67f1 has no "
            f"UIScene support, so builds made with the iOS 27 SDK crash on launch on iOS 27. "
            f"Xcode must stay on {game.xcode_major}.x. Archive: {archive_path}")
    return sdk


def zip_dsyms(archive_path: Path, out: Path) -> Path:
    """Zip the archive's dSYMs folder contents to `<out>/dSYMs.zip`, keeping the .dSYM bundles."""
    src = Path(archive_path) / "dSYMs"
    if not src.is_dir():
        raise StepFailed(f"No dSYMs folder in {archive_path}")
    if not any(p.is_dir() and p.suffix == ".dSYM" for p in src.iterdir()):
        raise StepFailed(f"No .dSYM bundle in {src}")
    if not Path(out).is_dir():
        raise StepFailed(f"Output folder does not exist: {out}")
    dst = Path(out) / "dSYMs.zip"
    dst.unlink(missing_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            z.write(p, p.relative_to(src).as_posix())
    return dst


def upload_key(version: str, ios_build: int):
    """The uploaded_ios_builds entry for one upload. Build 0 never moves, so it is keyed by version too:
    "1.1.1/0" and "1.1.2/0" are different uploads. Any other build stays a bare number, blocked for every version."""
    return f"{version}/0" if ios_build == 0 else ios_build


def upload_testflight(game: Game, archive_path: Path, ios_build: int, record, runner, version: str = "") -> None:
    """SDK check, then build-number check, then upload. The archive is never deleted."""
    if ios_build == 0 and not version:
        raise StepFailed("iOS build 0 needs the version to check for a reused upload. Nothing was uploaded.")
    key = upload_key(version, ios_build)
    check_sdk(game, archive_path)
    actual = _app_plist(archive_path).get("CFBundleVersion")
    if str(actual) != str(ios_build):
        raise StepFailed(f"The archive holds build number {actual}, but build {ios_build} was asked for. "
                         f"Archive: {archive_path}")
    if key in record.uploaded_ios_builds:
        raise StepFailed(f"iOS build number {ios_build} was already uploaded{f' for v{version}' if ios_build == 0 else ''}; TestFlight rejects a reused number. "
                         f"Bump the build number and archive again.")
    archive_path = Path(archive_path)
    opts = archive_path.parent / "ExportOptions.plist"
    opts.write_bytes(plistlib.dumps({"method": "app-store-connect", "destination": "upload",
                                     "teamID": game.team_id, "signingStyle": "automatic",
                                     # Xcode must not renumber the build: the record and Slack assume the archive's number.
                                     "manageAppVersionAndBuildNumber": False, "uploadSymbols": True}))
    export = archive_path.parent / "export"
    r = _run(runner, ["xcodebuild", "-exportArchive", "-archivePath", str(archive_path),
                      "-exportOptionsPlist", str(opts), "-exportPath", str(export),
                      "-allowProvisioningUpdates"], "xcodebuild")
    if r.code != 0:
        text = r.out + "\n" + r.err
        msg = (f"TestFlight upload failed (exit {r.code}). The archive is kept: {archive_path}\n"
               f"Finish from Xcode Organizer (Window > Organizer > Distribute App), or rerun this step.\n"
               f"If App Store Connect already shows build {ios_build}, add it to the record instead of rerunning.")
        if any(h in text.lower() for h in AUTH_HINTS):
            msg += "\nPossible cause: the Apple session expired. Sign in again in Xcode > Settings > Accounts."
        err = _first_error(text)
        if err:
            msg += f"\nFirst error: {err}"
        raise StepFailed(msg)
    record.uploaded_ios_builds.append(key)
    try:
        record.save()
    except OSError as e:
        raise StepFailed(f"Upload succeeded for build {ios_build}, but the record could not be saved: "
                         f"{e.strerror or e}. Add {json.dumps(key)} to uploaded_ios_builds in {record.path}.")


def iphone_present(game: Game, runner) -> bool:
    """True when the game's iPhone is listed by devicectl and paired. False, with a printed line, otherwise."""
    with tempfile.TemporaryDirectory() as tmp:
        js = Path(tmp) / "devices.json"
        try:
            r = runner.run(["xcrun", "devicectl", "list", "devices", "--json-output", str(js)])
            devices = (json.loads(js.read_text(encoding="utf-8"))["result"]["devices"] or []) if r.code == 0 else []
        except (OSError, ValueError, KeyError, TypeError):
            devices = []
            r = None
    if r is not None and r.code != 0:
        print(f"devicectl list devices exited {r.code}; skipping install.")
        return False
    ready = False
    for d in devices:
        ids = {d.get("identifier"), (d.get("hardwareProperties") or {}).get("udid")}
        pairing = (d.get("connectionProperties") or {}).get("pairingState")
        if game.iphone_id in ids and pairing in (None, "paired"):
            ready = True
    if not ready:
        print(f"iPhone {game.iphone_id} not found or not paired; skipping install.")
    return ready


def install_on_iphone(game: Game, app_path: Path, runner) -> bool:
    """Install over devicectl. False when the phone is not available.
    A failed install on a present phone raises StepFailed quoting devicectl's error line."""
    if not iphone_present(game, runner):
        return False
    r = _run(runner, ["xcrun", "devicectl", "device", "install", "app", "--device", game.iphone_id,
                      str(app_path)], "devicectl")
    if r.code != 0:
        text = r.out + "\n" + r.err
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        line = next((ln for ln in lines if "error" in ln.lower()), lines[-1] if lines else "no output")
        raise StepFailed(f"devicectl install on iPhone {game.iphone_id} failed (exit {r.code}): {line}")
    return True
