"""Stop checks before a run. `check` only reports; it never changes a file or a branch."""
import os
import re

from .drive import REMOTE, SIGN_IN_STEPS

PROFILE_DIR = "Assets/Settings/Build Profiles"
KEYSTORE_FILE = "Tools/keystore.local.json"


def _git(runner, game, *args):
    return runner.run(["git", *args], cwd=game.project_path)


def _names(out: str) -> list[str]:
    return [p for p in out.split("\0") if p]


def _in_session(game, path: str) -> bool:
    return path.startswith(tuple(game.session_paths))


def _dirty(runner, game):
    """Return (raw, real, errors): changed or untracked paths. Line-ending-only changes drop out of `real`."""
    errors = []

    def names(*args):
        r = _git(runner, game, *args)
        if r.code != 0:
            errors.append(f"`git {' '.join(args)}` failed: {r.err.strip() or 'exit ' + str(r.code)}")
        return _names(r.out)

    untracked = names("ls-files", "-z", "--others", "--exclude-standard")
    raw = names("diff", "-z", "--name-only", "HEAD") + untracked
    # --name-only still lists a CR-only change, so ask per file with --quiet.
    real = list(untracked)
    for p in names("diff", "-z", "--name-only", "--ignore-cr-at-eol", "HEAD"):
        q = _git(runner, game, "diff", "--quiet", "--ignore-cr-at-eol", "HEAD", "--", p)
        if q.code == 1:
            real.append(p)
        elif q.code != 0:
            errors.append(f"`git diff --quiet {p}` failed: {q.err.strip() or 'exit ' + str(q.code)}")
    return raw, real, errors


def check(game, stage: str, platform: str, runner) -> list[str]:
    reasons: list[str] = []
    root = game.project_path
    profile = game.profiles[stage]
    branch = profile["branch"]

    if (root / "Temp" / "UnityLockfile").exists():
        reasons.append("Unity has this project open. Close it, because command-line builds cannot run on an open project, or delete Temp/UnityLockfile if Unity crashed.")

    if _git(runner, game, "rev-parse", "--git-dir").code != 0:
        return reasons + [f"{root} is not a git repository."]

    merging = _git(runner, game, "rev-parse", "-q", "--verify", "MERGE_HEAD").code == 0
    if merging:
        reasons.append("A merge is in progress. If this tool started it, run `resume`. Otherwise finish or "
                       "abort it yourself. Do not commit it to start a new release.")
    raw, real, errors = _dirty(runner, game)
    if errors:
        return reasons + errors
    game_dirty = sorted({p for p in real if not _in_session(game, p)})
    if game_dirty and not merging:
        shown = ", ".join(game_dirty[:5]) + (f" and {len(game_dirty) - 5} more" if len(game_dirty) > 5 else "")
        reasons.append(f"Uncommitted changes outside the session paths: {shown}. Commit or stash them yourself.")

    if platform not in ("android", "ios"):
        reasons.append(f"Unknown platform '{platform}'. Use android or ios.")
    if stage == "release" and game.dev_branch != branch and \
            _git(runner, game, "rev-parse", "--verify", "--quiet", f"refs/heads/{game.dev_branch}").code != 0:
        reasons.append(f"Branch '{game.dev_branch}' does not exist, and the release merges from it.")

    branch_ok = _git(runner, game, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").code == 0
    if not branch_ok:
        reasons.append(f"Branch '{branch}' does not exist.")
    else:
        lt = _git(runner, game, "ls-tree", "-r", "--name-only", "-z", branch)
        if lt.code != 0:
            return reasons + [f"`git ls-tree {branch}` failed: {lt.err.strip() or 'exit ' + str(lt.code)}"]
        on_branch = set(_names(lt.out))
        # A build_method game keeps its profiles in its build script, not as Build Profile assets.
        for name in ([] if game.build_method else profile.get(platform, [])):
            path = f"{PROFILE_DIR}/{name}.asset"
            if path not in on_branch:
                reasons.append(f"Build profile '{name}' is not on branch '{branch}' ({path}).")
        # Any dirty file, even a line-ending-only one, blocks git switch when the target branch differs from it.
        blocking = []
        for p in sorted(set(raw)):
            tracked = _git(runner, game, "ls-files", "-z", "--", p)
            if tracked.code != 0:
                return reasons + [f"`git ls-files {p}` failed: {tracked.err.strip() or 'exit ' + str(tracked.code)}"]
            if p in on_branch and p not in _names(tracked.out):
                blocking.append(p)  # untracked here, tracked there: switch would overwrite it
                continue
            d = _git(runner, game, "diff", "--quiet", "HEAD", branch, "--", p)
            if d.code == 1:
                blocking.append(p)
            elif d.code != 0:
                return reasons + [f"`git diff HEAD {branch} -- {p}` failed: {d.err.strip() or 'exit ' + str(d.code)}"]
        if blocking:
            reasons.append("git switch to '" + branch + "' would be blocked by local edits to files that "
                           "differ on that branch: " + ", ".join(blocking) +
                           ". Nothing was discarded. Commit or move those files, then rerun.")

    if _git(runner, game, "lfs", "version").code != 0:
        reasons.append("Git LFS is not available. The repo uses LFS rules.")

    for d in game.merge_drivers:
        if _git(runner, game, "config", "--get", f"merge.{d}.driver").code != 0:
            reasons.append(f"Merge driver '{d}' is not registered in this clone's git config.")

    if _git(runner, game, "check-ignore", "-q", "Builds/").code != 0:
        reasons.append("Builds/ is not ignored by git. Build output would show up as changes.")

    if platform == "ios":
        r = runner.run(["xcodebuild", "-version"])
        m = re.search(r"Xcode (\d+)", r.out) if r.code == 0 else None
        if not m:
            reasons.append("Xcode is not installed or `xcodebuild -version` failed.")
        elif int(m.group(1)) != game.xcode_major:
            reasons.append(f"Xcode {m.group(1)} is installed but this game needs Xcode {game.xcode_major}. "
                           "Xcode 27 builds for iOS 27 crash at launch." if int(m.group(1)) == 27 else
                           f"Xcode {m.group(1)} is installed but this game needs Xcode {game.xcode_major}.")

    if platform == "android":
        # Existence only. Never open the file or print a value.
        if not (root / KEYSTORE_FILE).exists() and not all(os.environ.get(v) for v in game.keystore_env):
            reasons.append(f"Android signing passwords not found. Add {KEYSTORE_FILE} to the game repo, "
                           f"or set {' and '.join(game.keystore_env)}.")

    r = runner.run(["rclone", "lsjson", f"{REMOTE}:", "--drive-root-folder-id", game.drive_folder_id,
                    "--max-depth", "1"])
    if r.code != 0:
        reasons.append(f"rclone cannot list the Drive folder (remote '{REMOTE}'). " + SIGN_IN_STEPS)

    return reasons
