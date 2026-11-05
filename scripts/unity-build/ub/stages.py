"""The test and release stages, the resumable run state, and `check`.

Each stage is a named list of steps. `record.run` holds the stage, game, version, branch, platform and
the finished steps, and is saved after every step, so `resume` skips what is done. `run.data["head"]`
is the commit the run expects HEAD at; `resume` refuses when the world moved under it.

Exit codes: 0 success, 1 failed step, 2 stop before anything changed, 3 merge needs a decision.
Nothing here pushes, stages broadly, or calls `rclone link`.
"""
import re
import shlex
import sys
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from . import drive, guards, ios, mergeflow, messages, minio, names, preflight, unitybuild, versions
from . import record as rec
from .mergeflow import MergeError
from .record import RunState
from .unitybuild import StepFailed
from .versions import Numbers

PS = mergeflow.PROJECT_SETTINGS
OK, FAILED, STOP, DECIDE = 0, 1, 2, 3
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
# Paths a Unity build may change besides the session paths and Game.regenerated_names (matched by basename).
BUILD_WRITTEN = ("Assets/AddressableAssetsData/link.xml", "Assets/AddressableAssetsData/link.xml.meta")
BUILD_WRITTEN_DIRS = (unitybuild.BUILDINFO_DIR + "/",)


class _Decide(Exception):
    """The merge left conflicts that need the user."""


class _Stop(Exception):
    """A step found the world changed under the run. Exit 2; nothing was changed."""


# ---- small seams (tests replace these) ----

def _is_terminal() -> bool:
    return sys.stdin.isatty()


def _ask(prompt: str) -> str:
    return input(prompt)


# ---- helpers ----

def _platforms(platform: str) -> list[str]:
    return ["android", "ios"] if platform == "both" else [platform]


def _git(game, runner, *args):
    return runner.run(["git", *args], cwd=game.project_path)


def _current_branch(game, runner) -> str:
    return _git(game, runner, "symbolic-ref", "--short", "HEAD").out.strip()


def _sha(game, runner, ref="HEAD") -> str:
    r = _git(game, runner, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if r.code != 0:
        raise StepFailed(f"git rev-parse {ref} failed: {(r.err or r.out).strip() or 'exit ' + str(r.code)}")
    return r.out.strip()


def _parents(game, runner, sha) -> list[str]:
    r = _git(game, runner, "rev-list", "--parents", "-n", "1", sha)
    if r.code != 0:
        raise StepFailed(f"git rev-list {sha} failed: {r.err.strip()}")
    return r.out.split()[1:]


def _merge_in_progress(game, runner) -> bool:
    return _git(game, runner, "rev-parse", "-q", "--verify", "MERGE_HEAD").code == 0


def _switch(game, branch, runner) -> None:
    if _current_branch(game, runner) == branch:
        return
    r = _git(game, runner, "switch", "-q", branch)
    if r.code != 0:
        raise StepFailed(f"git switch {branch} failed: {(r.err or r.out).strip()}")


def _unmerged(game, runner) -> list[str]:
    r = _git(game, runner, "ls-files", "-u", "-z")
    if r.code != 0:
        raise StepFailed(f"git ls-files -u failed: {r.err.strip()}")
    return sorted({entry.split("\t", 1)[1] for entry in r.out.split("\0") if "\t" in entry})


def _foreign_dirty(game, runner) -> list[str]:
    """Changed or untracked paths that no build writes: the user's own edits.

    Session paths, regenerated files (by basename), the Addressables link.xml pair, BuildInfo files and
    line-ending-only changes are the builds' and are left out.
    """
    _, real, errors = preflight._dirty(runner, game)
    if errors:
        raise StepFailed("; ".join(errors))
    out = []
    for p in sorted(set(real)):
        if (p.startswith(tuple(game.session_paths)) or PurePosixPath(p).name in game.regenerated_names
                or p in BUILD_WRITTEN or p.startswith(BUILD_WRITTEN_DIRS)):
            continue
        out.append(p)
    return out


def _dirty_advice(game, paths, run) -> str:
    """What to do about foreign edits. Never suggests stashing a guarded file."""
    guarded = set(guards._guarded_files(game))
    g = [p for p in paths if p in guarded]
    other = [p for p in paths if p not in guarded]
    parts = []
    if other:
        parts.append("These files changed, but no build writes them: " + ", ".join(other) + ". The run commits "
                     "only build outputs. Move those edits aside (for example `git stash push -- <path>`).")
    if g:
        parts.append("These release-only settings files differ from the committed release version, which passed "
                     "the release-only checks: " + ", ".join(g) + ". Builds use the working tree. Move your change "
                     "aside, for example copy the file elsewhere, then restore it with your git client. "
                     "If the change is wanted, commit it on "
                     f"'{game.release_branch}' yourself and start a new run with --discard-run.")
    return " ".join(parts) + f" Then run {_resume_hint(run)}."


def _require_clean(ctx) -> None:
    """Builds and the outputs commit must see only the commit plus build-written files."""
    foreign = _foreign_dirty(ctx.game, ctx.runner)
    if foreign:
        raise StepFailed(_dirty_advice(ctx.game, foreign, ctx.run))


def _parse_numbers(text: str, where: str) -> Numbers:
    try:
        return versions.read_numbers(text)
    except ValueError as e:
        raise StepFailed(f"{where}: {e}")


def _branch_numbers(game, branch, runner) -> Numbers:
    r = _git(game, runner, "show", f"{branch}:{PS}")
    if r.code != 0:
        raise StepFailed(f"Cannot read {PS} on '{branch}': {r.err.strip()}")
    return _parse_numbers(r.out, f"{PS} on '{branch}'")


def _tree_numbers(game) -> Numbers:
    p = game.project_path / PS
    try:
        text = p.read_bytes().decode("utf-8", "replace")
    except OSError as e:
        raise StepFailed(f"Cannot read {p}: {e.strerror or e}")
    return _parse_numbers(text, str(p))


def _builds(game, ver: str, platform: str) -> Path:
    return game.project_path / "Builds" / f"v{ver}" / platform


def _test_apk(game, ver) -> Path:
    return _builds(game, ver, "Android") / names.test_apk(game, ver)


def _say_stop(lines) -> int:
    for line in lines:
        print(f"STOP: {line}")
    return STOP


def _baseline_missing(game, runner) -> str | None:
    ref = guards.baseline_ref(game)
    if _git(game, runner, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").code != 0:
        return (f"{ref} does not exist. The release-only checks compare against it, and this tool never "
                f"fetches. Run `git fetch {guards.BASELINE_REMOTE}` in the game repo yourself, then start again.")
    return None


def _merge_owner_problem(game, runner, run) -> str | None:
    """A merge in progress must be the one this run started: same dev commit, same release base."""
    if not _merge_in_progress(game, runner):
        return None
    d = run.data
    merge_head = _sha(game, runner, "MERGE_HEAD")
    head = _sha(game, runner)
    if "pre_merge_head" not in d:
        return (f"A merge is in progress (MERGE_HEAD {merge_head}) that this run did not start. Nothing was "
                "changed. Finish or abort it yourself.")
    if merge_head != d["merge_dev_head"] or head != d["pre_merge_head"]:
        return (f"The merge in progress was not started by this run. This run merged "
                f"'{game.dev_branch}' {d['merge_dev_head']} into '{run.branch}' {d['pre_merge_head']}; the merge "
                f"in progress merges {merge_head} into {head}. Nothing was changed. Abort it with "
                "`git merge --abort`, then resume to let the run merge again.")
    return None


def _mark_released(ctx) -> None:
    if ctx.run.version not in ctx.record.released:
        ctx.record.released.append(ctx.run.version)
        ctx.record.save()


def _is_hand_merge(game, runner, run, sha, until="guards") -> bool:
    """True when `sha` is the run's own merge, committed outside the run before step `until` finished."""
    d = run.data
    if run.stage != "release" or "pre_merge_head" not in d or until in run.done:
        return False
    return _parents(game, runner, sha) == [d["pre_merge_head"], d["merge_dev_head"]]


def _merge_was_aborted(game, runner, run) -> bool:
    """The run's merge step finished (conflicts or a staged merge), then the user ran `git merge --abort`."""
    d = run.data
    return (run.stage == "release" and "merge" in run.done and "guards" not in run.done
            and d.get("merge_status") in ("needs_decision", "clean", "resolved")
            and not _merge_in_progress(game, runner) and _sha(game, runner) == d.get("pre_merge_head"))


def _resume_hint(run) -> str:
    return f"`python3 scripts/unity-build/unity_build.py resume {run.game}`"


class _Ctx:
    def __init__(self, game, runner, record):
        self.game, self.runner, self.record = game, runner, record
        self.run: RunState = record.run

    @property
    def ver(self) -> str:
        return self.run.version

    @property
    def data(self) -> dict:
        return self.run.data

    @property
    def numbers(self) -> Numbers:
        return Numbers(**self.data["numbers"])


# ---- test stage steps ----

def _t_bump(ctx):
    if not ctx.data["bump"]:
        print(f"Retest: keeping v{ctx.ver}.")
        return
    target = ctx.numbers
    p = ctx.game.project_path / PS
    text = p.read_bytes().decode("utf-8", "surrogateescape")
    if _parse_numbers(text, str(p)) != target:
        p.write_bytes(versions.apply_numbers(text, target).encode("utf-8", "surrogateescape"))
    if _git(ctx.game, ctx.runner, "diff", "--quiet", "HEAD", "--", PS).code == 0:
        return  # already committed by an earlier attempt
    for args in (("add", "--", PS), ("commit", "-q", "-m", f"chore(version): bump to v{ctx.ver}", "--", PS)):
        r = _git(ctx.game, ctx.runner, *args)
        if r.code != 0:
            raise StepFailed(f"git {args[0]} of the version bump failed: {(r.err or r.out).strip()}")
    print(f"Bumped to v{ctx.ver} (Android {target.android_code}, iOS {target.ios_build}) on {ctx.run.branch}.")


def _note_built_head(ctx):
    """The commit the test builds ran on. Every test build must come from the same one."""
    head = _sha(ctx.game, ctx.runner)
    built = ctx.data.setdefault("built_head", head)
    if built != head:
        raise StepFailed(f"This build ran on {head[:12]}, but the run's other builds ran on {built[:12]}.")


def _t_build_android(ctx):
    _note_built_head(ctx)
    profile = ctx.game.profiles["test"]["android"][0]
    out = _builds(ctx.game, ctx.ver, "Android")
    out.mkdir(parents=True, exist_ok=True)
    since = unitybuild.build(ctx.game, profile, out / names.test_apk(ctx.game, ctx.ver),
                             out / f"{profile}.log", ctx.runner)
    ctx.data["since"]["android"] = since
    unitybuild.outputs_android(ctx.game, ctx.ver, ctx.numbers.android_code, "test", since)


def _build_ios(ctx, stage):
    if stage == "test":
        _note_built_head(ctx)
    else:
        _require_clean(ctx)
    profile = ctx.game.profiles[stage]["ios"][0]
    out = _builds(ctx.game, ctx.ver, "iOS")
    if stage == "release" and out.is_dir() and any(out.iterdir()):
        # Unity appends to an existing Xcode project, and CocoaPods then embeds the SPM ad SDKs a second
        # time ("Multiple commands produce ...framework"). Build into a clean folder; keep the old one.
        aside, n = out.with_name("iOS-before-release"), 2
        while aside.exists():
            aside, n = out.with_name(f"iOS-before-release-{n}"), n + 1
        out.rename(aside)
        print(f"Moved the existing iOS project aside to {aside.name}, so the release builds a clean one.")
    out.mkdir(parents=True, exist_ok=True)
    since = unitybuild.build(ctx.game, profile, out, out.parent / f"{profile}.log", ctx.runner)
    ctx.data["since"]["ios"] = since
    unitybuild.outputs_ios(ctx.game, ctx.ver, since)


def _t_install_android(ctx):
    apk = unitybuild.outputs_android(ctx.game, ctx.ver, ctx.numbers.android_code, "test",
                                     ctx.data["since"]["android"])[0]
    if unitybuild.install_apk(apk, ctx.runner):
        print(f"Installed {apk.name} on the Android phone.")
    else:
        print("Android install skipped: no Android phone is connected.")


def _t_upload_test_apk(ctx):
    """Every Android test build goes to Drive. The release stage uploads it again only if it is gone."""
    apk = _test_apk(ctx.game, ctx.ver)
    drive.ensure_version_folder(ctx.game, ctx.ver, ctx.runner)
    try:
        links = drive.upload(ctx.game, f"v{ctx.ver}", [apk], ctx.runner)
    except drive.DriveNameClash as e:
        raise StepFailed(f"{e}\nDrive folder v{ctx.ver} holds a different {apk.name}, from an earlier test build. "
                         f"Delete or rename that old file in Drive, then run {_resume_hint(ctx.run)}.")
    print(f"Test APK on Drive: {links[apk.name]}")


def _app_in(archive: Path) -> Path:
    apps = sorted((archive / "Products" / "Applications").glob("*.app"))
    if len(apps) != 1:
        raise StepFailed(f"Expected exactly one .app in {archive}/Products/Applications, found {len(apps)}")
    return apps[0]


def _t_install_ios(ctx):
    if not ios.iphone_present(ctx.game, ctx.runner):
        print("iPhone install skipped: the phone is not connected. No archive was made.")
        return
    archive = ios.archive(ctx.game, ctx.ver, ctx.runner)
    if ios.install_on_iphone(ctx.game, _app_in(archive), ctx.runner):
        print("Installed the iOS test build on the iPhone.")
    else:
        print("iPhone install skipped: the phone disconnected during the archive.")


def _restore_cr_only(ctx) -> None:
    """Undo line-ending-only rewrites a build left (AndroidManifest.xml), or the next branch switch refuses.

    Only paths that were clean at run start and differ in line endings alone. No content is lost.
    """
    before = ctx.data.get("dirty_at_start")
    if before is None:  # a run saved by an older version: do not guess
        return
    skip = set(before)
    names = unitybuild._paths(ctx.runner, ctx.game, "diff", "-z", "--name-only")
    for p in names:
        if p in skip:
            continue
        same = unitybuild._git(ctx.runner, ctx.game, "diff", "--ignore-cr-at-eol", "--quiet", "--", p)
        differs = unitybuild._git(ctx.runner, ctx.game, "diff", "--quiet", "--", p)
        if same.code == 0 and differs.code == 1:
            r = unitybuild._git(ctx.runner, ctx.game, "checkout", "--", p)
            if r.code != 0:
                raise StepFailed(f"git checkout failed on {p}: {r.err.strip() or 'exit ' + str(r.code)}")
            print(f"Restored {p}: only its line endings had changed.")


def _commit(ctx):
    _require_clean(ctx)
    sha = unitybuild.commit_outputs(ctx.game, f"v{ctx.ver} {ctx.run.stage}", ctx.runner)
    ctx.data["outputs_commit"] = sha
    _restore_cr_only(ctx)
    print(f"Committed build outputs on {ctx.run.branch}: {sha}" if sha else "No tracked build outputs to commit.")


def _t_record(ctx):
    """Record the built commit, plus the run's own outputs commit on top of it, as tested."""
    tip = _sha(ctx.game, ctx.runner, ctx.game.dev_branch)
    built, outputs = ctx.data["built_head"], ctx.data.get("outputs_commit")
    if outputs:
        ok = tip == outputs and _parents(ctx.game, ctx.runner, tip) == [built]
    else:
        ok = tip == built
    if not ok:
        raise StepFailed(f"'{ctx.game.dev_branch}' is at {tip[:12]}, which is not the commit the builds ran on "
                         f"({built[:12]}) plus this run's outputs commit. Not recording it as tested. "
                         "Run the test stage again.")
    ctx.record.tested[ctx.ver] = rec.fingerprint(ctx.game, tip, ctx.runner)
    print(f"Recorded {tip[:12]} as the tested commit for v{ctx.ver}.")


# ---- release stage steps ----

def _foreign_merge_message(game) -> str:
    return (f"A merge is in progress on '{game.release_branch}' that this run did not start. Nothing was "
            "changed. Finish or abort it yourself (`git merge --abort`). Do not commit it to start a new "
            "release; then start the release again.")


def _print_conflicts(ctx, pending):
    print(f"The merge needs a decision on {len(pending)} file(s). The merge is left in progress.")
    for c in pending:
        print(f"\nCONFLICT: {c.path}")
        print(f"--- {ctx.game.release_branch} (ours) ---")
        print(c.ours.rstrip("\n"))
        print(f"--- {ctx.game.dev_branch} (theirs) ---")
        print(c.theirs.rstrip("\n"))
    print(f"\nResolve each file and stage it by path (git add -- <path>). Do not commit. Then run "
          f"{_resume_hint(ctx.run)}.")


def _merge_dev(ctx):
    try:
        return mergeflow.merge_dev(ctx.game, ctx.runner)
    except MergeError as e:
        raise StepFailed(
            f"The merge of '{ctx.game.dev_branch}' into '{ctx.game.release_branch}' stopped partway: {e}\n"
            f"Nothing was committed. Do not commit the merge by hand. Resolve any conflicted files, stage each "
            f"one by path, then run {_resume_hint(ctx.run)}. The run checks the merge against the release-only "
            "settings it saved before merging.")


def _r_merge(ctx):
    g, r, d = ctx.game, ctx.runner, ctx.data
    head = _sha(g, r)
    if "pre_merge_head" not in d:
        if _merge_in_progress(g, r):
            raise StepFailed(_foreign_merge_message(g))
        _tested_gate_or_stop(ctx)
        # Saved once, before the run's own merge, and never overwritten.
        d["pre_merge_head"] = head
        d["merge_dev_head"] = _sha(g, r, g.dev_branch)
        ctx.record.save()
        result = _merge_dev(ctx)
    elif _merge_in_progress(g, r):
        problem = _merge_owner_problem(g, r, ctx.run)
        if problem:
            raise _Stop(problem)
        # This run's merge, left by an earlier attempt that stopped partway.
        left = _unmerged(g, r)
        if left:
            print("These files still need a decision: " + ", ".join(left))
            print(f"Resolve each one and stage it by path. Do not commit. Then run {_resume_hint(ctx.run)}.")
            ctx.run.done.append("merge")
            raise _Decide()
        print("Continuing this run's merge, which is staged and not committed.")
        return
    elif head == d["pre_merge_head"]:
        # The earlier attempt never started the merge, or it was aborted. Merge the same dev commit again.
        now = _sha(g, r, g.dev_branch)
        if now != d["merge_dev_head"]:
            raise _Stop(f"'{g.dev_branch}' moved after the test: this run merges {d['merge_dev_head']}, but "
                        f"'{g.dev_branch}' is now at {now}. Nothing was changed. Run the test stage on the new "
                        f"commit, then start the release again with --discard-run.")
        _tested_gate_or_stop(ctx)
        result = _merge_dev(ctx)
    elif _is_hand_merge(g, r, ctx.run, head):
        print(f"This run's merge was committed outside the run as {head[:12]}. Checking it against "
              f"{guards.baseline_ref(g)}.")
        return
    else:
        raise StepFailed(f"'{g.release_branch}' moved from {d['pre_merge_head'][:12]} to {head[:12]} since this "
                         "run started its merge. Nothing was changed.")
    d["merge_status"] = result.status
    if result.status == "up_to_date":
        print(f"Nothing to merge: '{g.release_branch}' already has '{g.dev_branch}'.")
    elif result.status == "needs_decision":
        _print_conflicts(ctx, result.pending)
        ctx.run.done.append("merge")
        raise _Decide()
    else:
        print(f"Merged '{g.dev_branch}' into '{g.release_branch}' ({result.status}); not committed yet.")


def _merge_state(ctx) -> str:
    """How the merge stands, for messages: staged, or already committed by hand."""
    if _merge_in_progress(ctx.game, ctx.runner):
        return ("The merge is staged and not committed. The check reads the staged version, so fix each file "
                "and stage it by path (git add -- <path>). Do not commit.")
    head = _sha(ctx.game, ctx.runner)
    if _is_hand_merge(ctx.game, ctx.runner, ctx.run, head):
        return (f"The merge was already committed by hand as {head[:12]}. Fix each file and stage it by path. "
                "Do not commit; the run commits the staged fixes when it concludes.")
    return ("Fix each file and stage it by path (git add -- <path>). Do not commit; the run commits the "
            "staged fixes when it concludes.")


def _r_guards(ctx):
    left = _unmerged(ctx.game, ctx.runner)
    if left:
        raise StepFailed("These paths still have unresolved conflicts: " + ", ".join(left))
    problem = _merge_owner_problem(ctx.game, ctx.runner, ctx.run)
    if problem:
        raise _Stop(problem)
    missing = _baseline_missing(ctx.game, ctx.runner)
    if missing:
        raise _Stop(missing)
    base = guards.baseline_ref(ctx.game)
    # The index is what conclude commits; the working tree is checked separately before any build.
    bad = guards.violations(ctx.game, guards.snapshot_ref(ctx.game, base, ctx.runner), ctx.runner,
                            after=guards.snapshot_ref(ctx.game, "", ctx.runner))
    for v in bad:
        print(f"GUARD: {v}")
    hint = f"{_merge_state(ctx)} Then run {_resume_hint(ctx.run)}."
    if bad:
        raise StepFailed(f"The merge broke {len(bad)} release-only setting(s), compared with {base}. {hint}")
    before, merged = _branch_numbers(ctx.game, base, ctx.runner), _branch_numbers(ctx.game, "", ctx.runner)
    if (versions.version_key(merged.version) < versions.version_key(before.version)
            or merged.android_code < before.android_code or merged.ios_build < before.ios_build):
        raise StepFailed(f"The merge lowered the version numbers: {base} has {before}, "
                         f"the merge has {merged}. {hint}")
    if merged.version != ctx.ver:
        raise StepFailed(f"The merge holds v{merged.version}, but this run releases v{ctx.ver}. {hint}")
    ctx.data["numbers"] = asdict(merged)


def _r_head_guards(ctx):
    """Single-branch release: no merge, so check the tested commit itself against the release rules."""
    _tested_gate_or_stop(ctx)
    bad = guards.release_violations(ctx.game, guards.snapshot_ref(ctx.game, "HEAD", ctx.runner))
    for v in bad:
        print(f"GUARD: {v}")
    if bad:
        raise StepFailed(f"HEAD breaks {len(bad)} release-only setting(s). Fix them in a commit, test that "
                         f"commit, then start the release again with --discard-run.")
    head = _branch_numbers(ctx.game, "HEAD", ctx.runner)
    if head.version != ctx.ver:
        raise StepFailed(f"HEAD holds v{head.version}, but this run releases v{ctx.ver}.")
    ctx.data["numbers"] = asdict(head)


def _r_conclude(ctx):
    g, r = ctx.game, ctx.runner
    if _merge_in_progress(g, r):
        mergeflow.conclude_merge(g, r)
    else:
        staged = [x for x in _git(g, r, "diff", "--cached", "--name-only", "-z").out.split("\0") if x]
        if staged:
            # Fixes the user staged after a merge that was already committed broke a guard.
            other = sorted(set(staged) - set(guards._guarded_files(g)))
            if other:
                raise StepFailed("Staged changes outside the release-only settings files: " + ", ".join(other)
                                 + f". Unstage them (git restore --staged -- <path>), then run {_resume_hint(ctx.run)}.")
            c = _git(g, r, "commit", "-q", "-m", "fix(release): restore release-only settings after merge",
                     "--", *staged)
            if c.code != 0:
                raise StepFailed(f"git commit of the staged guard fixes failed: {(c.err or c.out).strip()}")
            print("Committed the staged release-only setting fixes.")
    base = guards.baseline_ref(g)
    bad = guards.violations(g, guards.snapshot_ref(g, base, r), r, after=guards.snapshot_ref(g, "HEAD", r))
    if bad:  # defensive: HEAD is what was checked in the index
        raise StepFailed("The committed release breaks release-only settings: " + " ".join(bad))


def _r_build_android(ctx):
    _require_clean(ctx)
    apk_profile, aab_profile = ctx.game.profiles["release"]["android"]
    out = _builds(ctx.game, ctx.ver, "Android")
    out.mkdir(parents=True, exist_ok=True)
    code = ctx.numbers.android_code
    # The release APK's start time covers both outputs; the AAB's would make the APK look stale.
    since = unitybuild.build(ctx.game, apk_profile, out / names.release_apk(ctx.game, ctx.ver),
                             out / f"{apk_profile}.log", ctx.runner)
    ctx.data["since"]["android"] = since
    ctx.record.save()
    unitybuild.build(ctx.game, aab_profile, out / names.aab(ctx.game, ctx.ver, code),
                     out / f"{aab_profile}.log", ctx.runner)
    unitybuild.outputs_android(ctx.game, ctx.ver, code, "release", since)


def _r_upload_android(ctx):
    test_apk = _test_apk(ctx.game, ctx.ver)
    if not test_apk.is_file():
        raise StepFailed(f"The test APK is missing: {test_apk}")
    files = [test_apk] + unitybuild.outputs_android(ctx.game, ctx.ver, ctx.numbers.android_code, "release",
                                                    ctx.data["since"]["android"])
    ctx.data["folder_id"] = drive.ensure_version_folder(ctx.game, ctx.ver, ctx.runner)
    ctx.data["links_android"] = drive.upload(ctx.game, f"v{ctx.ver}", files, ctx.runner)
    print(f"Uploaded {len(files)} Android files to Drive folder v{ctx.ver}.")
    _mark_released(ctx)


def _r_archive_ios(ctx):
    archive = ios.archive(ctx.game, ctx.ver, ctx.runner)
    ios.check_sdk(ctx.game, archive)  # stop before Drive gets dSYMs of a build that must not ship
    ios.zip_dsyms(archive, archive.parent)
    ctx.data["archive"] = str(archive)


def _r_upload_ios(ctx):
    out = _builds(ctx.game, ctx.ver, "iOS")
    buildinfo = unitybuild.outputs_ios(ctx.game, ctx.ver, ctx.data["since"]["ios"])[2]
    files = [out / "dSYMs.zip", buildinfo]
    ctx.data["folder_id"] = drive.ensure_version_folder(ctx.game, ctx.ver, ctx.runner)
    ctx.data["links_ios"] = drive.upload(ctx.game, f"v{ctx.ver}", files, ctx.runner)
    print(f"Uploaded dSYMs.zip and {buildinfo.name} to Drive folder v{ctx.ver}.")


def _r_testflight(ctx):
    build = ctx.numbers.ios_build
    if ctx.data.get("testflight_uploaded") == build:
        print(f"This run already uploaded iOS build {build} to TestFlight; skipping the upload.")
    else:
        key = ios.upload_key(ctx.ver, build)
        had = key in ctx.record.uploaded_ios_builds
        try:
            ios.upload_testflight(ctx.game, Path(ctx.data["archive"]), build, ctx.record, ctx.runner,
                                  version=ctx.ver)
        finally:
            if not had and key in ctx.record.uploaded_ios_builds:
                ctx.data["testflight_uploaded"] = build  # the upload went through, even if saving failed
        print(f"Uploaded iOS build {build} to TestFlight.")
    _mark_released(ctx)


def _r_messages(ctx):
    g, ver, plats = ctx.game, ctx.ver, _platforms(ctx.run.platform)
    out = g.project_path / "Builds" / f"v{ver}" / "messages"
    out.mkdir(parents=True, exist_ok=True)
    folder = drive.folder_url(ctx.data["folder_id"])
    changelog = ctx.data["changelog"]
    texts = {}
    if "android" in plats:
        code, info = ctx.numbers.android_code, names.buildinfo(g, ver, "Android")
        texts["Android"] = messages.android_message(
            g, ver, {"folder": folder, "buildinfo": ctx.data["links_android"][info]},
            {"test_apk": names.test_apk(g, ver), "release_apk": names.release_apk(g, ver),
             "aab": names.aab(g, ver, code), "symbols": names.symbols(g, ver, code)}, changelog)
    if "ios" in plats:
        texts["iOS"] = messages.ios_message(g, ver, {"folder": folder},
                                            {"buildinfo": names.buildinfo(g, ver, "iOS")}, changelog)
    paths = {}
    for plat, text in texts.items():
        paths[plat] = out / f"{plat}.txt"
        paths[plat].write_text(text, encoding="utf-8")
        print(f"\n===== {plat} message ({paths[plat]}) =====\n{text}\n")
    first = "Android" if "Android" in texts else "iOS"
    messages.copy_to_clipboard(texts[first], ctx.runner)
    print(f"The {first} message is on the clipboard.")
    if "iOS" in paths:
        print(f"Copy the iOS message with: LC_CTYPE=UTF-8 pbcopy < {shlex.quote(str(paths['iOS']))}")


def _upload_ota(ctx, platform_key: str):
    """Upload the build's Addressables folder to MinIO. Production is replaceable only by the run that wrote it."""
    g, ver = ctx.game, ctx.ver
    plat = "Android" if platform_key == "android" else "iOS"
    profile = g.ota["profiles"][ctx.run.stage]
    tag = f"{profile}/{plat}"
    mine = ctx.data.setdefault("ota_uploaded", [])
    may_replace = ctx.run.stage == "test" or tag in mine

    def claim():
        if tag not in mine:
            mine.append(tag)
            ctx.record.save()

    files = minio.ota_outputs(g, profile, plat, ver, ctx.data["since"][platform_key])
    copied = minio.upload(g, profile, plat, ver, files, ctx.runner, may_replace, claim)
    print(f"Uploaded {copied} of {len(files)} Addressables files to {minio.remote_url(g, profile, plat, ver)}")


_STEPS = {
    "bump": _t_bump, "install_android": _t_install_android, "upload_test_apk": _t_upload_test_apk,
    "install_ios": _t_install_ios, "commit": _commit, "record": _t_record,
    "merge": _r_merge, "guards": _r_guards, "conclude": _r_conclude, "head_guards": _r_head_guards, "upload_android": _r_upload_android,
    "archive_ios": _r_archive_ios, "upload_ios": _r_upload_ios, "testflight": _r_testflight,
    "messages": _r_messages,
    "upload_ota_android": lambda ctx: _upload_ota(ctx, "android"),
    "upload_ota_ios": lambda ctx: _upload_ota(ctx, "ios"),
}


def _step_names(run: RunState, game) -> list[str]:
    p = _platforms(run.platform)
    a, i = "android" in p, "ios" in p
    o = game.ota is not None
    build_a = ["build_android"] + ["upload_ota_android"] * o
    build_i = ["build_ios"] + ["upload_ota_ios"] * o
    if run.stage == "test":
        return (["preflight", "bump"] + build_a * a + build_i * i
                + ["install_android", "upload_test_apk"] * a + ["install_ios"] * i + ["commit", "record"])
    start = ["preflight", "head_guards"] if game.single_branch else ["preflight", "merge", "guards", "conclude"]
    return (start + build_a * a + build_i * i
            + ["upload_android"] * a + ["archive_ios", "upload_ios", "testflight"] * i + ["commit", "messages"])


def _step_fn(run: RunState, name: str):
    if name == "build_android":
        return _t_build_android if run.stage == "test" else _r_build_android
    if name == "build_ios":
        return lambda ctx: _build_ios(ctx, run.stage)
    return _STEPS[name]


def _execute(game, runner, record) -> int:
    ctx = _Ctx(game, runner, record)
    run = ctx.run
    for name in _step_names(run, game):
        if name in run.done:
            continue
        run.step = name
        record.save()
        print(f"== {run.stage} v{run.version}: {name}")
        try:
            _step_fn(run, name)(ctx)
            run.data["head"] = _sha(game, runner)
        except _Decide:
            record.save()
            return DECIDE
        except _Stop as e:
            print(f"STOP at step '{name}': {e}")
            record.save()
            return STOP
        except (StepFailed, MergeError, RuntimeError, OSError, KeyError, ValueError, TypeError) as e:
            print(f"FAILED at step '{name}': {type(e).__name__ + ': ' if not isinstance(e, StepFailed) else ''}{e}")
            print(f"Fix the cause, then run {_resume_hint(run)}.")
            record.save()
            return FAILED
        run.done.append(name)
        record.save()
    record.run = None
    record.save()
    print(f"{run.stage.capitalize()} v{run.version} ({run.platform}) finished.")
    return OK


def _dirty_now(game, runner) -> list[str]:
    raw, _, errors = preflight._dirty(runner, game)
    if errors:
        raise StepFailed("; ".join(errors))
    return sorted(set(raw))


def _start(game, runner, record, stage, platform, branch, version, data) -> None:
    record.run = RunState(stage=stage, platform=platform, branch=branch, version=version,
                          done=["preflight"], game=record.path.stem,
                          data={"since": {}, "head": _sha(game, runner),
                                "dirty_at_start": _dirty_now(game, runner), **data})
    record.save()


def _preflight(game, stage, platform, runner) -> list[str]:
    reasons = []
    for p in _platforms(platform):
        for r in preflight.check(game, stage, p, runner):
            if r not in reasons:
                reasons.append(r)
    return reasons


def _version_plan(game, version, runner, record):
    """(Numbers to build, bump?) or a list of stop reasons."""
    dev = _branch_numbers(game, game.dev_branch, runner)
    rel = _branch_numbers(game, game.release_branch, runner)
    if not versions.needs_bump(dev, rel, record):
        if version and version != dev.version:
            return [f"v{dev.version} has not been released, so this is a retest and keeps v{dev.version}. "
                    f"--version {version} was not applied."]
        return dev, False
    proposed = versions.next_numbers(dev, rel)
    if not version:
        if not _is_terminal():
            return [f"A version bump is needed. Proposed version: {proposed.version} "
                    f"(dev {dev.version}, release {rel.version}). Rerun with --version {proposed.version} "
                    "or another version to confirm it."]
        try:
            version = _ask(f"New version [{proposed.version}]: ").strip() or proposed.version
        except EOFError:
            return ["No version was entered."]
    if not _SEMVER.match(version):
        return [f"'{version}' is not a version like 0.1.9."]
    top = max(versions.version_key(dev.version), versions.version_key(rel.version))
    if versions.version_key(version) <= top:
        return [f"v{version} is not above dev ({dev.version}) and release ({rel.version})."]
    return Numbers(version, proposed.android_code, proposed.ios_build), True


def _unfinished_gate(record, discard_run) -> list[str]:
    """Stop reasons from an unfinished run. Empty means a new run may start."""
    run = record.run
    if run is None:
        return []
    merging = run.stage == "release" and "pre_merge_head" in run.data and "guards" not in run.done
    if merging and not discard_run:
        return [f"An unfinished release run for v{run.version} has started its merge into '{run.branch}' but has "
                "not yet checked the release-only settings. A new run would abandon that merge halfway. "
                f"Finish it with {_resume_hint(run)}. To throw it away instead, rerun with --discard-run."]
    if not discard_run:
        print(f"NOTE: an unfinished {run.stage} run for v{run.version} stopped at '{run.step}'. "
              f"{_resume_hint(run)} continues it. A new run replaces it once preflight passes.")
    return []


def _discard(game, runner, record, discard_run) -> None:
    """Called once preflight passed: say what the replaced run leaves behind, then drop it."""
    run = record.run
    if run is None or not discard_run:
        return
    merging = _merge_in_progress(game, runner)
    _, real, _ = preflight._dirty(runner, game)
    outputs = [p for p in real if not p.startswith(tuple(game.session_paths))]
    print(f"DISCARDING the unfinished {run.stage} run for v{run.version} (stopped at '{run.step}'). "
          f"Lost: its finished steps ({', '.join(run.done)}). "
          f"A merge is {'still staged' if merging else 'not staged'}. "
          + (f"Uncommitted changes, such as build outputs: {', '.join(outputs)}." if outputs
             else "No build outputs are left uncommitted.")
          + f" The release-only checks always compare with {guards.baseline_ref(game)}, so nothing about them is lost.")
    record.run = None
    record.save()


def _tested_problem(game, ver, allow_moved_dev, runner, record) -> str | None:
    """dev must still hold the tested files (session paths aside), unless --allow-moved-dev."""
    tested = record.tested.get(ver)
    if tested is None:
        return f"v{ver} on '{game.dev_branch}' has no tested commit. Run the test stage first."
    if rec.fingerprint(game, game.dev_branch, runner) != tested:
        if not allow_moved_dev:
            return (f"'{game.dev_branch}' moved since v{ver} was tested: files outside the session paths "
                    "changed. Test again, or pass --allow-moved-dev to release anyway.")
        print(f"WARNING: '{game.dev_branch}' moved since v{ver} was tested. Releasing anyway (--allow-moved-dev).")
    return None


def _tested_gate_or_stop(ctx) -> None:
    """The same tested-commit gate as the release start, before every merge attempt."""
    problem = _tested_problem(ctx.game, ctx.ver, ctx.data.get("allow_moved_dev", False), ctx.runner, ctx.record)
    if problem:
        raise _Stop(problem + " Nothing was merged.")


def _release_gates(game, platform, ver, allow_moved_dev, runner, record) -> list[str]:
    """Release stop reasons that need no change: tested commit, and the test APK locally and on Drive."""
    missing = None if game.single_branch else _baseline_missing(game, runner)
    if missing:
        return [missing]
    if record.tested.get(ver) is None:
        return [_tested_problem(game, ver, allow_moved_dev, runner, record)]
    reasons = []
    problem = _tested_problem(game, ver, allow_moved_dev, runner, record)
    if problem:
        reasons.append(problem)
    if "android" in _platforms(platform):
        apk = _test_apk(game, ver)
        if not apk.is_file():
            reasons.append(f"The test APK is missing: {apk}. The Android release uploads the build the user "
                           "played. Run the test stage for Android first.")
        else:
            entry = drive.remote_file(game, f"v{ver}", apk.name, runner)
            if entry is not None and not drive.same_content(entry, apk):
                reasons.append(f"Drive folder v{ver} already holds a different {apk.name} (size or MD5 differs "
                               f"from {apk}). Delete or rename the old file in Drive, then start the release again.")
    return reasons


# ---- public API ----

def run_test(game, platform, version, runner, record, discard_run=False) -> int:
    if platform not in ("android", "ios", "both"):
        return _say_stop([f"Unknown platform '{platform}'. Use android, ios or both."])
    blocked = _unfinished_gate(record, discard_run)
    if blocked:
        return _say_stop(blocked)
    try:
        reasons = _preflight(game, "test", platform, runner)
        if reasons:
            return _say_stop(reasons)
        plan = _version_plan(game, version, runner, record)
        if isinstance(plan, list):
            return _say_stop(plan)
        target, bump = plan
        _discard(game, runner, record, discard_run)
        _switch(game, game.dev_branch, runner)
        _start(game, runner, record, "test", platform, game.dev_branch, target.version,
               {"bump": bump, "numbers": asdict(target)})
    except (StepFailed, MergeError, RuntimeError) as e:
        # No run state is saved yet, so there is nothing to resume.
        print(f"Stopped before the run started: {e}")
        return STOP
    return _execute(game, runner, record)


def _read_changelog(changelog):
    if changelog is None:
        if not _is_terminal():
            print("STOP: No changelog. Pass --changelog-file PATH, or run in a terminal to type it.")
            return None
        print("Changelog lines, one per line. Finish with an empty line.")
        lines = []
        while True:
            try:
                line = _ask("> ")
            except EOFError:
                break
            if not line.strip():
                break
            lines.append(line)
        changelog = lines
    if isinstance(changelog, str):
        changelog = changelog.splitlines()
    lines = [ln.strip() for ln in changelog if ln.strip()]
    if not lines:
        print("STOP: The changelog is empty.")
        return None
    return lines


def run_release(game, platform, changelog, allow_moved_dev, runner, record, discard_run=False) -> int:
    if platform not in ("android", "ios", "both"):
        return _say_stop([f"Unknown platform '{platform}'. Use android, ios or both."])
    blocked = _unfinished_gate(record, discard_run)
    if blocked:
        return _say_stop(blocked)
    lines = _read_changelog(changelog)
    if lines is None:
        return STOP
    try:
        reasons = _preflight(game, "release", platform, runner)
        if reasons:
            return _say_stop(reasons)
        ver = _branch_numbers(game, game.dev_branch, runner).version
        reasons = _release_gates(game, platform, ver, allow_moved_dev, runner, record)
        if reasons:
            return _say_stop(reasons)
        _discard(game, runner, record, discard_run)
        _switch(game, game.release_branch, runner)
        _start(game, runner, record, "release", platform, game.release_branch, ver, {"changelog": lines, "allow_moved_dev": bool(allow_moved_dev)})
    except (StepFailed, MergeError, RuntimeError) as e:
        # No run state is saved yet, so there is nothing to resume.
        print(f"Stopped before the run started: {e}")
        return STOP
    return _execute(game, runner, record)


def resume(game, runner, record) -> int:
    run = record.run
    if run is None:
        return _say_stop(["There is no unfinished run to resume."])
    try:
        branch = _current_branch(game, runner)
        if branch != run.branch:
            return _say_stop([f"The run was on '{run.branch}', but '{branch}' is checked out. "
                              f"Switch back to '{run.branch}' first. Nothing was changed."])
        problem = _merge_owner_problem(game, runner, run)
        if problem:
            return _say_stop([problem])
        left = _unmerged(game, runner)
        if left:
            return _say_stop(["These paths still have unresolved conflicts: " + ", ".join(left)
                              + ". Resolve each one and stage it by path, then resume."])
        if _merge_was_aborted(game, runner, run):
            print(f"The merge this run started was aborted by hand: '{run.branch}' is back at "
                  f"{run.data['pre_merge_head'][:12]} and no merge is in progress. Resume runs the merge again, "
                  f"from the same tested '{game.dev_branch}' commit {run.data['merge_dev_head'][:12]}.")
            run.done.remove("merge")
            record.save()
        expected, head = run.data.get("head"), _sha(game, runner)
        if expected and head != expected and not _is_hand_merge(game, runner, run, head):
            return _say_stop([f"The run expected '{run.branch}' at {expected}, but HEAD is now {head}. Something "
                              "was committed, reset or checked out since the run stopped, and the run cannot vouch "
                              f"for it. Nothing was changed. Put '{run.branch}' back at {expected[:12]} and resume, "
                              "or start a new run with --discard-run."])
        # Before the bump (test) or the merge (release), the tree still holds the old version.
        version_step = "bump" if run.stage == "test" else ("head_guards" if game.single_branch else "merge")
        if version_step in run.done:
            now = _tree_numbers(game).version
            if now != run.version:
                return _say_stop([f"The run is for v{run.version}, but {PS} now holds v{now}. "
                                  "Nothing was changed."])
        # Once the merge is concluded (release) or from the start (test), every change is a build's.
        if run.stage == "test" or game.single_branch or "conclude" in run.done:
            foreign = _foreign_dirty(game, runner)
            if run.stage == "test" and "bump" not in run.done:
                foreign = [p for p in foreign if p != PS]
            if foreign:
                return _say_stop(["Nothing was changed. " + _dirty_advice(game, foreign, run)])
    except (StepFailed, RuntimeError) as e:
        return _say_stop([f"Cannot check the run: {e}"])
    print(f"Resuming {run.stage} v{run.version} ({run.platform}); done: {', '.join(run.done)}.")
    return _execute(game, runner, record)


def check(game, stage, platform, runner, record) -> int:
    """Read-only: preflight, plus the version a test run would use or the release's own stop checks."""
    try:
        reasons = _preflight(game, stage, platform, runner)
        dev = _branch_numbers(game, game.dev_branch, runner)
        if stage == "test":
            rel = _branch_numbers(game, game.release_branch, runner)
            if versions.needs_bump(dev, rel, record):
                print(f"A version bump is needed. Proposed version: {versions.next_numbers(dev, rel).version}")
            else:
                print(f"Retest: the version stays v{dev.version}.")
        else:
            reasons += _release_gates(game, platform, dev.version, False, runner, record)
            if dev.version in record.tested and not reasons:
                print(f"'{game.dev_branch}' is at the tested commit for v{dev.version}.")
    except (StepFailed, RuntimeError) as e:
        print(f"STOP: {e}")
        return STOP
    for r in reasons:
        print(f"STOP: {r}")
    if record.run:
        print(f"An unfinished {record.run.stage} run for v{record.run.version} is waiting at "
              f"'{record.run.step}'. Use resume.")
    if not reasons:
        print("Preflight passed.")
    return STOP if reasons else OK
