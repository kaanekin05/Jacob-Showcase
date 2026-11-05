import contextlib
import io
import os
import plistlib
import subprocess
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from ub import drive, ios, minio, preflight, stages, unitybuild
from ub import record as rec
from ub.config import load_game
from ub.record import Record
from ub.runner import FakeRunner, Result, Runner
from ub.unitybuild import StepFailed
from ub.versions import Numbers, apply_numbers, read_numbers

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ProjectSettings.asset"
PS = "ProjectSettings/ProjectSettings.asset"
ADDR = "Assets/AddressableAssetsData/AddressableAssetSettings.asset"
SRD = "Assets/StompyRobot/SRDebugger/usr/Resources/SRDebugger/Settings.asset"
MANIFEST = "Assets/Plugins/Android/AndroidManifest.xml"
CODE = "Assets/a.cs"
DEFINES = "  scriptingDefineSymbols:\n    Android: DOTWEEN\n    iPhone: DOTWEEN\n"
TEST_APK = "Builds/v0.1.8/Android/Amber_v.0.1.8_T.apk"
CHANGELOG = ["UA Team Feedbacks", "GDPR Güncellemeleri"]


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


class World:
    """Real git in the temp repo. Every other tool goes to a FakeRunner. Records every call."""

    def __init__(self, phone=True):
        self.real = Runner()
        self.fake = FakeRunner()
        self.phone = phone
        self.adb_install = Result(0, "Success\n")
        self.calls = []

    def run(self, cmd, cwd=None, env=None, input=None):
        self.calls.append(list(cmd))
        if cmd[0] == "git":
            return self.real.run(cmd, cwd, env, input)
        self.fake.run(cmd, cwd, env, input)
        if cmd[:3] == ["adb", "devices", "-l"]:
            return Result(0, "List of devices attached\n"
                             + ("R5CT device usb:1-1 product:x model:SM\n" if self.phone else ""))
        if cmd[:1] == ["adb"] and "install" in cmd:
            return self.adb_install
        return Result(0)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        genv = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
        genv.start()
        self.addCleanup(genv.stop)
        self.repo = r = Path(tmp.name) / "game"
        r.mkdir()
        git(r, "init", "-q", "-b", "dev")
        git(r, "config", "user.email", "t@t")
        git(r, "config", "user.name", "t")
        git(r, "config", "core.autocrlf", "false")
        self.write(".gitignore", "Builds/\n")
        self.write(PS, FIXTURE.read_text() + DEFINES)
        self.write(ADDR, "MonoBehaviour:\n  m_ActiveProfileId: 067be015d747d4b95b1c258e6206febd\n")
        self.write(SRD, "MonoBehaviour:\n  _isEnabled: 0\n")
        self.write(MANIFEST, '<manifest>\n  <application android:label="x">\n  </application>\n</manifest>\n')
        self.write(CODE, "class A {\n    int x = 1;\n}\n")
        self.write(".memsearch/notes.md", "n\n")
        self.write("crashlytics_build_id.xml", "old\n")
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "init")
        git(r, "branch", "release")
        # The guard baseline. The tool never fetches, so a plain ref stands in for the remote.
        git(r, "update-ref", "refs/remotes/origin/release", "release")
        self.game = replace(load_game("amber"), project_path=r)
        self.record = Record.load("amber", state_dir=Path(tmp.name) / "state")
        self.runner = World()
        self.events = []
        self.uploads = []
        self.upload_fails = 0
        self.testflight_fails = 0
        self.remote_apk = None
        self.build_fails = False
        self.crlf_paths = []
        self.iphone = True
        self.versions_seen = []

        orig_install, orig_commit, orig_fp = unitybuild.install_apk, unitybuild.commit_outputs, rec.fingerprint
        self.fingerprint = orig_fp
        patches = [
            mock.patch.object(preflight, "check", side_effect=self.fake_preflight),
            mock.patch.object(unitybuild, "build", side_effect=self.fake_build),
            mock.patch.object(unitybuild, "install_apk",
                              side_effect=lambda p, rn: self.ev("install_apk") or orig_install(p, rn)),
            mock.patch.object(unitybuild, "commit_outputs",
                              side_effect=lambda g, label, rn: self.ev("commit") or orig_commit(g, label, rn)),
            mock.patch.object(rec, "fingerprint",
                              side_effect=lambda g, ref, rn: self.ev("fingerprint") or orig_fp(g, ref, rn)),
            mock.patch.object(drive, "ensure_version_folder",
                              side_effect=lambda g, ver, rn: self.ev("folder") or "FOLDER"),
            mock.patch.object(drive, "upload", side_effect=self.fake_upload),
            mock.patch.object(ios, "archive", side_effect=self.fake_archive),
            mock.patch.object(ios, "upload_testflight", side_effect=self.fake_testflight),
            mock.patch.object(ios, "iphone_present", side_effect=lambda g, rn: self.ev("probe_ios") or self.iphone),
            mock.patch.object(drive, "remote_file", side_effect=lambda g, folder, name, rn: self.remote_apk),
            mock.patch.object(ios, "install_on_iphone",
                              side_effect=lambda g, app, rn: self.ev("install_ios") or self.iphone),
            mock.patch.object(stages, "_is_terminal", return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # ---- fakes ----

    def ev(self, name):
        self.events.append(name)

    def fake_preflight(self, game, stage, platform, runner):
        self.ev("preflight")
        return []

    def fake_build(self, game, profile, out_path, log_path, runner):
        self.ev(f"build:{profile}")
        if self.build_fails:
            raise StepFailed(f"Unity exited 1 building {profile}. Log: {log_path}")
        self.versions_seen.append(read_numbers(self.read(PS)).version)
        start = time.time() - 1
        out = Path(out_path)
        rel = out.relative_to(self.repo).parts
        ver, plat = rel[1][1:], rel[2]
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix == ".apk":
            out.write_bytes(b"apk " + profile.encode())
        elif out.suffix == ".aab":
            out.write_bytes(b"aab")
            (out.parent / "unity-output.symbols.zip").write_bytes(b"sym")
        else:
            (out / "Unity-iPhone.xcodeproj").mkdir(parents=True, exist_ok=True)
            (out / "Unity-iPhone.xcodeproj/project.pbxproj").write_text("p\n")
            (out / "Unity-iPhone.xcworkspace").mkdir(exist_ok=True)
        self.write(f"VersionTracker/Amber_{ver}_{plat}_BuildInfo.json", "{}\n")
        self.write("crashlytics_build_id.xml", f"{profile}\n")
        for rel in self.crlf_paths:
            self.to_crlf(rel)
        return start

    def fake_upload(self, game, folder, files, runner):
        self.ev("upload")
        if self.upload_fails:
            self.upload_fails -= 1
            raise StepFailed("Upload of 'x' failed: network")
        for f in files:
            self.assertTrue(Path(f).is_file(), f)
        self.uploads.append([Path(f).name for f in files])
        return {Path(f).name: drive.file_url("id-" + Path(f).name) for f in files}

    def fake_archive(self, game, ver, runner):
        self.ev("archive")
        arc = self.repo / f"Builds/v{ver}/iOS/Amber.xcarchive"
        app = arc / "Products/Applications/Amber.app"
        app.mkdir(parents=True, exist_ok=True)
        build = read_numbers(self.read(PS)).ios_build
        (app / "Info.plist").write_bytes(plistlib.dumps({"DTSDKName": "iphoneos26.5", "CFBundleVersion": str(build)}))
        (arc / "dSYMs/Amber.app.dSYM/Contents").mkdir(parents=True, exist_ok=True)
        (arc / "dSYMs/Amber.app.dSYM/Contents/Info.plist").write_text("x\n")
        return arc

    def fake_testflight(self, game, archive_path, ios_build, record, runner, version=""):
        self.ev("testflight")
        record.uploaded_ios_builds.append(ios.upload_key(version, ios_build))
        if self.testflight_fails:
            self.testflight_fails -= 1
            raise StepFailed(f"Upload succeeded for build {ios_build}, but the record could not be saved")

    # ---- helpers ----

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def to_crlf(self, rel):
        p = self.repo / rel
        p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    def read(self, rel):
        return (self.repo / rel).read_text()

    def commit_on(self, branch, edit, msg="c"):
        git(self.repo, "switch", "-q", branch)
        edit()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", msg)

    def numbers(self, version, android, ios_build):
        return lambda: self.write(PS, apply_numbers(self.read(PS), Numbers(version, android, ios_build)))

    def call(self, fn, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fn(*args)
        self.out = buf.getvalue()
        return code

    def builds(self):
        return [e for e in self.events if e.startswith("build:")]

    def release_ready(self, dev_edit=None, apk=True):
        """dev at 0.1.8 and tested, release at 0.1.7, the test APK on disk. Leaves dev checked out."""
        def edit():
            self.numbers("0.1.8", 18, 18)()
            if dev_edit:
                dev_edit()
        self.commit_on("dev", edit, "bump")
        self.record.tested["0.1.8"] = self.fingerprint(self.game, "dev", Runner())
        if apk:
            self.write(TEST_APK, "test apk\n")

    def release(self, platform="both", changelog=CHANGELOG, allow=False):
        return self.call(stages.run_release, self.game, platform, changelog, allow, self.runner, self.record)

    def head(self, ref="HEAD"):
        return git(self.repo, "rev-parse", ref)

    def merge_head(self):
        return (self.repo / ".git/MERGE_HEAD").exists()


class TestStage(Base):
    def test_test_stage_order(self):
        self.record.released.append("0.1.7")
        code = self.call(stages.run_test, self.game, "both", "0.1.8", self.runner, self.record)
        self.assertEqual(code, 0, self.out)
        self.assertEqual([e for e in self.events if e != "folder"],
                         ["preflight", "preflight", "build:0-And_Test", "build:0-iOS_Test",
                          "install_apk", "upload", "probe_ios", "archive", "install_ios", "commit",
                          "fingerprint"])
        self.assertEqual(self.versions_seen, ["0.1.8", "0.1.8"], "the bump lands before any build")
        log = git(self.repo, "log", "--format=%s", "dev").splitlines()
        self.assertEqual(log[:2], ["chore(build): record v0.1.8 test outputs", "chore(version): bump to v0.1.8"])
        self.assertEqual(read_numbers(git(self.repo, "show", f"dev:{PS}")), Numbers("0.1.8", 18, 18))
        self.assertEqual(self.record.tested["0.1.8"], self.fingerprint(self.game, "dev", Runner()))
        self.assertIsNone(self.record.run)
        self.assertEqual(self.uploads, [["Amber_v.0.1.8_T.apk"]], "the test APK goes to Drive even after an install")

    def test_ios_only_test_stage_uploads_nothing(self):
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        self.assertEqual(self.call(stages.run_test, self.game, "ios", None, self.runner, self.record), 0, self.out)
        self.assertEqual(self.uploads, [])

    def test_resume_after_failed_test_apk_upload_does_not_reinstall(self):
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        self.upload_fails = 1
        self.assertEqual(self.call(stages.run_test, self.game, "android", None, self.runner, self.record), 1)
        self.assertEqual(self.events.count("install_apk"), 1)
        self.assertEqual(self.call(stages.resume, self.game, self.runner, self.record), 0, self.out)
        self.assertEqual(self.events.count("install_apk"), 1, "resume starts at the upload step")
        self.assertEqual(self.uploads, [["Amber_v.0.1.8_T.apk"]])

    def test_retest_does_not_bump(self):
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        code = self.call(stages.run_test, self.game, "android", None, self.runner, self.record)
        self.assertEqual(code, 0, self.out)
        self.assertNotIn("chore(version)", git(self.repo, "log", "--format=%s", "dev"))
        self.assertEqual(read_numbers(self.read(PS)), Numbers("0.1.8", 18, 18))
        self.assertIn("0.1.8", self.record.tested)

    def test_no_phone_uploads_test_apk_to_drive(self):
        self.runner.phone = False
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        code = self.call(stages.run_test, self.game, "android", None, self.runner, self.record)
        self.assertEqual(code, 0, self.out)
        self.assertEqual(self.uploads, [["Amber_v.0.1.8_T.apk"]])

    def test_bump_without_version_or_terminal_exits_2(self):
        self.record.released.append("0.1.7")
        code = self.call(stages.run_test, self.game, "both", None, self.runner, self.record)
        self.assertEqual(code, 2)
        self.assertIn("0.1.8", self.out)
        self.assertEqual(self.builds(), [])
        self.assertEqual(read_numbers(self.read(PS)).version, "0.1.7")
        self.assertIsNone(self.record.run)


class ReleaseStage(Base):
    def test_release_asks_changelog_before_any_build(self):
        self.release_ready()
        # No changelog file and no terminal: stop before anything runs.
        self.assertEqual(self.release(changelog=None), 2)
        self.assertEqual(self.events, [])
        answers = iter(["UA Team Feedbacks", "GDPR Güncellemeleri", ""])
        with mock.patch.object(stages, "_is_terminal", return_value=True), \
                mock.patch.object(stages, "_ask", side_effect=lambda p: self.ev("ask") or next(answers)):
            code = self.release(changelog=None)
        self.assertEqual(code, 0, self.out)
        self.assertEqual(self.events[:4], ["ask", "ask", "ask", "preflight"])
        msg_dir = self.repo / "Builds/v0.1.8/messages"
        android = (msg_dir / "Android.txt").read_text(encoding="utf-8")
        self.assertTrue(android.startswith("Amber Android v0.1.8 Drive'a yüklendi hocam @Build Owner\n"))
        self.assertIn("Test APK: Amber_v.0.1.8_T.apk\n", android)
        self.assertIn("AAB: Amber-0.1.8-v18.aab\n", android)
        self.assertTrue(android.endswith("Changelog;\n-UA Team Feedbacks\n-GDPR Güncellemeleri"))
        self.assertIn("TFye yüklendi", (msg_dir / "iOS.txt").read_text(encoding="utf-8"))
        pb = [c for c in self.runner.fake.calls if c.cmd == ["pbcopy"]]
        self.assertEqual(len(pb), 1)
        self.assertEqual(pb[0].input.decode("utf-8"), android)
        self.assertIn("pbcopy < ", self.out)
        self.assertIn(str(msg_dir / "iOS.txt"), self.out)

    def test_release_stops_when_game_files_moved(self):
        self.release_ready()
        self.commit_on("dev", lambda: self.write(CODE, "class A {\n    int x = 5;\n}\n"))
        release_tip = self.head("release")
        self.assertEqual(self.release(), 2)
        self.assertIn("moved", self.out)
        self.assertEqual(self.head("release"), release_tip)
        self.assertFalse(self.merge_head())
        self.assertEqual(self.builds(), [])

    def test_release_passes_after_session_only_commit(self):
        self.release_ready()
        self.commit_on("dev", lambda: self.write(".memsearch/notes.md", "more notes\n"))
        self.assertEqual(self.release(), 0, self.out)

    def test_allow_moved_dev_overrides(self):
        self.release_ready()
        self.commit_on("dev", lambda: self.write(CODE, "class A {\n    int x = 5;\n}\n"))
        self.assertEqual(self.release(allow=True), 0, self.out)
        self.assertIn("x = 5", git(self.repo, "show", f"release:{CODE}"))

    def test_guard_violation_stops_before_builds(self):
        self.release_ready(lambda: self.write(SRD, "MonoBehaviour:\n  _isEnabled: 1\n"))
        release_tip = self.head("release")
        self.assertEqual(self.release(), 1)
        self.assertIn("_isEnabled", self.out)
        self.assertEqual(self.builds(), [])
        self.assertTrue(self.merge_head(), "the staged merge stays for the user")
        self.assertEqual(self.head(), release_tip, "nothing was committed")
        self.assertEqual(git(self.repo, "symbolic-ref", "--short", "HEAD"), "release")
        self.assertIn(SRD, git(self.repo, "diff", "--cached", "--name-only"))

    def conflict(self):
        self.release_ready(lambda: self.write(CODE, "class A {\n    int x = 2;\n}\n"))
        self.commit_on("release", lambda: self.write(CODE, "class A {\n    int x = 3;\n}\n"))
        git(self.repo, "switch", "-q", "dev")
        self.release_tip = self.head("release")
        return self.release()

    def test_conflict_exits_3_and_lists_both_sides(self):
        self.assertEqual(self.conflict(), 3)
        self.assertIn(CODE, self.out)
        self.assertIn("int x = 3;", self.out)
        self.assertIn("int x = 2;", self.out)
        self.assertTrue(self.merge_head())
        self.assertEqual(self.head(), self.release_tip)
        self.assertIn("merge", self.record.run.done)
        self.assertEqual(self.builds(), [])
        saved = Record.load("amber", state_dir=self.record.path.parent)
        self.assertEqual(saved.run.stage, "release")

    def test_resume_finishes_merge_and_skips_done_steps(self):
        self.assertEqual(self.conflict(), 3)
        self.write(CODE, "class A {\n    int x = 2;\n}\n")
        git(self.repo, "add", "--", CODE)
        self.events.clear()
        code = self.call(stages.resume, self.game, self.runner, self.record)
        self.assertEqual(code, 0, self.out)
        self.assertNotIn("preflight", self.events)
        self.assertEqual(self.builds(), ["build:2-APK_Release", "build:3-AAB_Release", "build:1-iOS_Release"])
        self.assertFalse(self.merge_head())
        merge = git(self.repo, "log", "--merges", "-1", "--format=%P", "release").split()
        self.assertEqual(merge[0], self.release_tip)
        self.assertIsNone(self.record.run)
        self.assertEqual(self.record.released, ["0.1.8"])

    def failed_build_run(self):
        self.release_ready()
        self.build_fails = True
        self.assertEqual(self.release(), 1)
        self.build_fails = False
        self.events.clear()

    def test_resume_refuses_on_other_branch(self):
        self.failed_build_run()
        git(self.repo, "switch", "-q", "dev")
        self.assertEqual(self.call(stages.resume, self.game, self.runner, self.record), 2)
        self.assertIn("release", self.out)
        self.assertEqual(self.builds(), [])

    def test_resume_refuses_on_changed_version(self):
        self.failed_build_run()
        self.numbers("0.1.9", 19, 19)()
        self.assertEqual(self.call(stages.resume, self.game, self.runner, self.record), 2)
        self.assertIn("0.1.9", self.out)
        self.assertEqual(self.builds(), [])

    def test_resume_refuses_with_unmerged_paths(self):
        self.assertEqual(self.conflict(), 3)
        self.events.clear()
        self.assertEqual(self.call(stages.resume, self.game, self.runner, self.record), 2)
        self.assertIn(CODE, self.out)
        self.assertTrue(self.merge_head())
        self.assertEqual(self.builds(), [])

    def test_ios_only_uploads_no_android_files(self):
        self.release_ready(apk=False)
        self.assertEqual(self.release("ios"), 0, self.out)
        self.assertEqual(self.uploads, [["dSYMs.zip", "Amber_0.1.8_iOS_BuildInfo.json"]])
        self.assertEqual(self.builds(), ["build:1-iOS_Release"])
        self.assertIn("testflight", self.events)
        self.assertEqual(self.record.uploaded_ios_builds, [18])
        self.assertFalse((self.repo / "Builds/v0.1.8/messages/Android.txt").exists())

    def test_second_platform_skips_merge(self):
        self.release_ready()
        self.assertEqual(self.release("android"), 0, self.out)
        self.assertEqual(self.record.released, ["0.1.8"])
        self.assertEqual(self.release("ios"), 0, self.out)
        self.assertIn("Nothing to merge", self.out)
        self.assertEqual(len(git(self.repo, "rev-list", "--merges", "release").splitlines()), 1)
        self.assertEqual(self.record.released, ["0.1.8"])

    def test_failed_upload_rerun_skips_builds(self):
        self.release_ready()
        self.upload_fails = 1
        self.assertEqual(self.release(), 1)
        self.assertIn("network", self.out)
        built = self.builds()
        self.assertEqual(len(built), 3)
        self.assertEqual(self.record.released, [])
        self.assertEqual(self.call(stages.resume, self.game, self.runner, self.record), 0, self.out)
        self.assertEqual(self.builds(), built, "no rebuild on resume")
        self.assertEqual(len(self.uploads), 2)
        self.assertEqual(sorted(self.uploads[0]), sorted([
            "Amber_v.0.1.8_T.apk", "Amber_v.0.1.8_R.apk", "Amber-0.1.8-v18.aab",
            "Amber-0.1.8-v18-IL2CPP.symbols.zip", "Amber_0.1.8_Android_BuildInfo.json"]))

    def test_release_never_pushes(self):
        self.record.released.append("0.1.7")
        self.assertEqual(self.call(stages.run_test, self.game, "both", "0.1.8", self.runner, self.record), 0)
        self.write(TEST_APK, "test apk\n")
        self.assertEqual(self.release(), 0, self.out)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        for c in self.runner.calls:
            self.assertNotIn("push", c)
            self.assertNotEqual(c[:2], ["rclone", "link"])
            if c[:2] == ["git", "add"] or c[:3] == ["git", "--literal-pathspecs", "add"]:
                self.assertFalse({"-A", "-a", ".", "--all"} & set(c), c)
            if "commit" in c:
                self.assertFalse({"-a", "--all"} & set(c), c)

    def test_missing_test_apk_stops_release(self):
        self.release_ready(apk=False)
        release_tip = self.head("release")
        self.assertEqual(self.release("android"), 2)
        self.assertIn("Amber_v.0.1.8_T.apk", self.out)
        self.assertEqual(self.head("release"), release_tip)
        self.assertFalse(self.merge_head())
        self.assertEqual(self.builds(), [])
        self.assertIsNone(self.record.run)



class FixRound1(Base):
    """Review findings C1, C2, I1-I3, M1, M3."""

    def profile_and_conflict(self):
        """dev changes the protected Addressables profile and conflicts on CODE with release."""
        def dev_edit():
            self.write(CODE, "class A {\n    int x = 2;\n}\n")
            self.write(ADDR, "MonoBehaviour:\n  m_ActiveProfileId: devprofile\n")
        self.release_ready(dev_edit)
        self.commit_on("release", lambda: self.write(CODE, "class A {\n    int x = 3;\n}\n"))
        git(self.repo, "switch", "-q", "dev")

    def resume(self):
        return self.call(stages.resume, self.game, self.runner, self.record)

    def test_path_a_hand_committed_merge_blocks_new_run_and_resume_catches_profile(self):
        self.profile_and_conflict()
        self.assertEqual(self.release(), 3, self.out)
        self.write(CODE, "class A {\n    int x = 2;\n}\n")
        git(self.repo, "add", "--", CODE)
        git(self.repo, "commit", "-q", "--no-edit")  # the user commits the merge by hand
        self.events.clear()
        self.assertEqual(self.release(), 2, self.out)
        self.assertIn("--discard-run", self.out)
        self.assertEqual(self.events, [])
        self.assertEqual(self.resume(), 1, self.out)
        self.assertIn("m_ActiveProfileId", self.out)
        self.assertIn("committed by hand", self.out)
        self.assertEqual(self.builds(), [])
        # The user restores the value and stages it; the run commits the fix and finishes.
        self.write(ADDR, "MonoBehaviour:\n  m_ActiveProfileId: 067be015d747d4b95b1c258e6206febd\n")
        git(self.repo, "add", "--", ADDR)
        self.assertEqual(self.resume(), 0, self.out)
        self.assertIn("067be015d747d4b95b1c258e6206febd", git(self.repo, "show", f"release:{ADDR}"))
        self.assertIn("fix(release): restore release-only settings after merge",
                      git(self.repo, "log", "--format=%s", "release"))

    def test_path_b_merge_failed_partway_then_hand_commit_resume_catches_profile(self):
        self.release_ready(lambda: self.write(ADDR, "MonoBehaviour:\n  m_ActiveProfileId: devprofile\n"))
        real = stages.mergeflow.merge_dev

        def broken(game, runner):
            real(game, runner)
            raise stages.MergeError("git add failed: index.lock exists")
        with mock.patch.object(stages.mergeflow, "merge_dev", side_effect=broken):
            self.assertEqual(self.release(), 1, self.out)
        self.assertIn("Do not commit the merge by hand", self.out)
        self.assertIn("resume", self.out)
        git(self.repo, "commit", "-q", "--no-edit")  # the user commits anyway
        self.assertEqual(self.resume(), 1, self.out)
        self.assertIn("m_ActiveProfileId", self.out)
        self.assertEqual(self.builds(), [])
        self.assertIn("devprofile", self.read(ADDR))

    def test_path_b_merge_failed_partway_resume_without_commit_catches_profile(self):
        self.release_ready(lambda: self.write(ADDR, "MonoBehaviour:\n  m_ActiveProfileId: devprofile\n"))
        real = stages.mergeflow.merge_dev

        def broken(game, runner):
            real(game, runner)
            raise stages.MergeError("boom")
        with mock.patch.object(stages.mergeflow, "merge_dev", side_effect=broken):
            self.assertEqual(self.release(), 1, self.out)
        self.assertEqual(self.resume(), 1, self.out)
        self.assertIn("m_ActiveProfileId", self.out)
        self.assertIn("staged and not committed", self.out)
        self.assertEqual(self.builds(), [])

    def test_discard_run_names_the_loss_and_foreign_merge_is_refused(self):
        self.profile_and_conflict()
        self.assertEqual(self.release(), 3, self.out)
        self.write(CODE, "class A {\n    int x = 2;\n}\n")
        git(self.repo, "add", "--", CODE)
        code = self.call(stages.run_release, self.game, "both", CHANGELOG, False, self.runner, self.record, True)
        self.assertEqual(code, 1, self.out)
        self.assertIn("DISCARDING", self.out)
        self.assertIn("A merge is still staged", self.out)
        self.assertIn("did not start", self.out)
        self.assertEqual(self.builds(), [])

    def failed_test_run(self):
        self.record.released.append("0.1.7")
        with mock.patch.object(ios, "archive", side_effect=StepFailed("signing")):
            self.assertEqual(self.call(stages.run_test, self.game, "both", "0.1.8", self.runner, self.record), 1)
        self.events.clear()

    def test_resume_refuses_after_dev_moved(self):
        self.failed_test_run()
        built = self.head()
        self.write(CODE, "class A {\n    int x = 99;\n}\n")
        git(self.repo, "commit", "-q", "-am", "untested")
        self.assertEqual(self.resume(), 2, self.out)
        self.assertIn(built, self.out)
        self.assertIn(self.head(), self.out)
        self.assertNotIn("0.1.8", self.record.tested)
        self.assertEqual(self.events, [])

    def test_user_edit_before_resume_is_not_committed(self):
        self.failed_test_run()
        self.write(CODE, "class A {\n    int x = 99;\n}\n")
        self.assertEqual(self.resume(), 2, self.out)
        self.assertIn(CODE, self.out)
        self.assertNotIn("x = 99", git(self.repo, "show", f"HEAD:{CODE}"))
        self.assertNotIn("commit", self.events)
        # Once the edit is moved aside, the run finishes and records the built commit plus its outputs.
        git(self.repo, "checkout", "--", CODE)
        self.assertEqual(self.resume(), 0, self.out)
        self.assertEqual(self.record.tested["0.1.8"], self.fingerprint(self.game, "dev", Runner()))

    def test_testflight_already_uploaded_is_skipped_on_resume(self):
        self.release_ready()
        self.testflight_fails = 1
        self.assertEqual(self.release("ios"), 1, self.out)
        self.assertEqual(self.record.uploaded_ios_builds, [18])
        self.assertEqual(self.resume(), 0, self.out)
        self.assertEqual(self.events.count("testflight"), 1)
        self.assertIn("This run already uploaded", self.out)
        self.assertEqual(self.record.released, ["0.1.8"])

    def test_release_ios_builds_into_a_clean_folder_and_keeps_the_old_one(self):
        self.release_ready()
        old = self.repo / "Builds/v0.1.8/iOS"
        old.mkdir(parents=True, exist_ok=True)
        (old / "from-test.txt").write_text("test project\n")
        self.assertEqual(self.release("ios"), 0, self.out)
        self.assertFalse((old / "from-test.txt").exists(), "Unity must not append to the test project")
        self.assertEqual((self.repo / "Builds/v0.1.8/iOS-before-release/from-test.txt").read_text(), "test project\n")
        self.assertIn("iOS-before-release", self.out)

    def test_test_stage_drive_name_clash_says_delete_then_resume(self):
        self.runner.phone = False
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        with mock.patch.object(drive, "upload", side_effect=drive.DriveNameClash("Drive already has 'x' with a different size")):
            code = self.call(stages.run_test, self.game, "android", None, self.runner, self.record)
        self.assertEqual(code, 1)
        self.assertIn("Delete or rename", self.out)
        self.assertIn("resume", self.out)

    def test_release_stops_before_merge_when_drive_test_apk_differs(self):
        self.release_ready()
        self.remote_apk = {"Name": "Amber_v.0.1.8_T.apk", "ID": "X", "Size": 1, "Hashes": {"md5": "0" * 32}}
        tip = self.head("release")
        self.assertEqual(self.release("android"), 2, self.out)
        self.assertIn("Amber_v.0.1.8_T.apk", self.out)
        self.assertEqual(self.head("release"), tip)
        self.assertFalse(self.merge_head())
        self.assertIsNone(self.record.run)

    def test_release_passes_when_drive_test_apk_matches(self):
        self.release_ready()
        apk = self.repo / TEST_APK
        import hashlib
        self.remote_apk = {"Name": apk.name, "ID": "X", "Size": apk.stat().st_size,
                           "Hashes": {"md5": hashlib.md5(apk.read_bytes()).hexdigest()}}
        self.assertEqual(self.release("android"), 0, self.out)

    def test_failed_apk_install_is_a_step_failure_not_an_upload(self):
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        self.runner.adb_install = Result(1, "adb: failed to install: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]\n")
        code = self.call(stages.run_test, self.game, "android", None, self.runner, self.record)
        self.assertEqual(code, 1)
        self.assertIn("INSTALL_FAILED_INSUFFICIENT_STORAGE", self.out)
        self.assertEqual(self.uploads, [])

    def test_no_iphone_skips_the_archive(self):
        self.iphone = False
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        self.assertEqual(self.call(stages.run_test, self.game, "ios", None, self.runner, self.record), 0, self.out)
        self.assertIn("probe_ios", self.events)
        self.assertNotIn("archive", self.events)

    def test_check_release_stops_on_missing_test_apk(self):
        self.release_ready(apk=False)
        code = self.call(stages.check, self.game, "release", "android", self.runner, self.record)
        self.assertEqual(code, 2)
        self.assertIn("Amber_v.0.1.8_T.apk", self.out)
        self.assertNotIn("Preflight passed", self.out)



class FixRound2(Base):
    """Guard baseline from origin/release (P1, P2), index-checked guards (P3), merge ownership (P4), M1-M3."""

    def resume(self):
        return self.call(stages.resume, self.game, self.runner, self.record)

    def profile_and_conflict(self, profile="devprofile"):
        def dev_edit():
            self.write(CODE, "class A {\n    int x = 2;\n}\n")
            self.write(ADDR, f"MonoBehaviour:\n  m_ActiveProfileId: {profile}\n")
        self.release_ready(dev_edit)
        self.commit_on("release", lambda: self.write(CODE, "class A {\n    int x = 3;\n}\n"))
        git(self.repo, "switch", "-q", "dev")

    def test_p1_hand_merge_before_any_run_is_caught(self):
        self.profile_and_conflict()
        git(self.repo, "switch", "-q", "release")
        subprocess.run(["git", "merge", "--no-ff", "--no-edit", "dev"], cwd=self.repo, capture_output=True)
        self.write(CODE, "class A {\n    int x = 2;\n}\n")
        git(self.repo, "add", "--", CODE)
        git(self.repo, "commit", "-q", "--no-edit")
        git(self.repo, "switch", "-q", "dev")
        self.assertEqual(self.release(), 1, self.out)
        self.assertIn("m_ActiveProfileId", self.out)
        self.assertIn("devprofile", self.out)
        self.assertEqual(self.builds(), [])

    def test_p2_path_a_then_discard_run_is_caught(self):
        self.profile_and_conflict()
        self.assertEqual(self.release(), 3, self.out)
        self.write(CODE, "class A {\n    int x = 2;\n}\n")
        git(self.repo, "add", "--", CODE)
        git(self.repo, "commit", "-q", "--no-edit")
        code = self.call(stages.run_release, self.game, "both", CHANGELOG, False, self.runner, self.record, True)
        self.assertEqual(code, 1, self.out)
        self.assertIn("DISCARDING", self.out)
        self.assertIn("devprofile", self.out)
        self.assertEqual(self.builds(), [])

    def test_p3_unstaged_fix_is_not_trusted_and_nothing_builds(self):
        self.profile_and_conflict()
        self.assertEqual(self.release(), 3, self.out)
        self.write(CODE, "class A {\n    int x = 2;\n}\n")
        git(self.repo, "add", "--", CODE)
        self.assertEqual(self.resume(), 1, self.out)
        self.write(ADDR, "MonoBehaviour:\n  m_ActiveProfileId: 067be015d747d4b95b1c258e6206febd\n")  # fixed, not staged
        self.assertEqual(self.resume(), 1, self.out)
        self.assertIn("devprofile", self.out)
        self.assertIn("stage it by path", self.out)
        self.assertEqual(self.builds(), [])
        self.assertTrue(self.merge_head())
        git(self.repo, "add", "--", ADDR)
        self.assertEqual(self.resume(), 0, self.out)
        self.assertIn("067be015d747d4b95b1c258e6206febd", git(self.repo, "show", f"release:{ADDR}"))

    def test_p3_worktree_edit_after_conclude_blocks_builds(self):
        self.release_ready()
        real = stages._r_conclude

        def conclude_then_edit(ctx):
            real(ctx)
            self.write(ADDR, "MonoBehaviour:\n  m_ActiveProfileId: devprofile\n")
        with mock.patch.dict(stages._STEPS, {"conclude": conclude_then_edit}):
            self.assertEqual(self.release(), 1, self.out)
        self.assertEqual(self.builds(), [])
        self.assertIn(ADDR, self.out)
        self.assertIn("Move your change aside", self.out)
        self.assertNotIn("git restore", self.out)
        self.assertNotIn("--worktree", self.out)
        self.assertNotIn("stash", self.out)

    def test_p4_remerge_after_abort_is_refused(self):
        self.profile_and_conflict(profile="067be015d747d4b95b1c258e6206febd")
        self.assertEqual(self.release(), 3, self.out)
        git(self.repo, "merge", "--abort")
        self.commit_on("dev", lambda: self.write("Assets/untested.cs", "class U {}\n"), "untested")
        git(self.repo, "switch", "-q", "release")
        subprocess.run(["git", "merge", "--no-ff", "--no-commit", "dev"], cwd=self.repo, capture_output=True)
        self.write(CODE, "class A {\n    int x = 2;\n}\n")
        git(self.repo, "add", "--", CODE)
        self.assertEqual(self.resume(), 2, self.out)
        self.assertIn("not started by this run", self.out)
        self.assertIn(self.head("dev"), self.out)
        self.assertEqual(self.builds(), [])
        self.assertTrue(self.merge_head())

    def test_missing_baseline_ref_stops_with_2(self):
        self.release_ready()
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/release")
        tip = self.head("release")
        self.assertEqual(self.release(), 2, self.out)
        self.assertIn("refs/remotes/origin/release", self.out)
        self.assertEqual(self.head("release"), tip)
        self.assertNotIn(["git", "fetch"], [c[:2] for c in self.runner.calls])

    def test_m1_other_drive_failures_pass_through(self):
        self.runner.phone = False
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        self.upload_fails = 1
        self.assertEqual(self.call(stages.run_test, self.game, "android", None, self.runner, self.record), 1)
        self.assertIn("network", self.out)
        self.assertNotIn("Delete or rename", self.out)

    def test_m2_discard_waits_for_preflight(self):
        self.profile_and_conflict()
        self.assertEqual(self.release(), 3, self.out)
        with mock.patch.object(preflight, "check", return_value=["A merge is in progress."]):
            code = self.call(stages.run_release, self.game, "both", CHANGELOG, False, self.runner, self.record, True)
        self.assertEqual(code, 2)
        self.assertNotIn("DISCARDING", self.out)
        self.assertIsNotNone(self.record.run)

    def test_m3_build_number_uploaded_by_another_run_is_not_skipped(self):
        self.release_ready()
        self.record.uploaded_ios_builds.append(18)
        self.assertEqual(self.release("ios"), 0, self.out)
        self.assertIn("testflight", self.events)  # the real function's reused-number stop decides



PROD = "067be015d747d4b95b1c258e6206febd"


class FixRound3(Base):
    """Retried merges stay on the tested commit (C1), required profile (I1), aborted merge (M1)."""

    def resume(self):
        return self.call(stages.resume, self.game, self.runner, self.record)

    def conflict(self):
        self.release_ready(lambda: self.write(CODE, "class A {\n    int x = 2;\n}\n"))
        self.commit_on("release", lambda: self.write(CODE, "class A {\n    int x = 3;\n}\n"))
        git(self.repo, "switch", "-q", "dev")

    def test_c1_retry_after_dev_moved_is_refused(self):
        """Probe A: merge_dev fails before merging, dev gains an untested commit, resume."""
        self.conflict()
        tested_dev = self.head("dev")
        real = stages.mergeflow.merge_dev
        calls = []

        def flaky(game, runner):
            calls.append(1)
            if len(calls) == 1:
                raise stages.MergeError("git merge dev failed: index.lock exists")
            return real(game, runner)
        with mock.patch.object(stages.mergeflow, "merge_dev", side_effect=flaky):
            self.assertEqual(self.release(), 1, self.out)
            self.commit_on("dev", lambda: self.write("Assets/untested.cs", "class U {}\n"), "untested")
            git(self.repo, "switch", "-q", "release")
            self.assertEqual(self.resume(), 2, self.out)
        self.assertIn("moved after the test", self.out)
        self.assertIn(tested_dev, self.out)
        self.assertIn(self.head("dev"), self.out)
        self.assertEqual(len(calls), 1, "no second merge attempt")
        self.assertFalse(self.merge_head())
        self.assertNotIn("Assets/untested.cs", git(self.repo, "ls-tree", "-r", "--name-only", "release"))
        self.assertEqual(self.record.run.data["merge_dev_head"], tested_dev)

    def test_c1_retry_reruns_tested_gate(self):
        """dev's tip is unchanged but its tested fingerprint no longer matches (record changed): stop."""
        self.conflict()
        with mock.patch.object(stages.mergeflow, "merge_dev", side_effect=stages.MergeError("boom")):
            self.assertEqual(self.release(), 1, self.out)
        self.record.tested["0.1.8"] = "something-else"
        self.assertEqual(self.resume(), 2, self.out)
        self.assertIn("moved since v0.1.8 was tested", self.out)
        self.assertFalse(self.merge_head())

    def test_c1_retry_keeps_allow_moved_dev(self):
        self.conflict()
        self.record.tested["0.1.8"] = "stale"
        with mock.patch.object(stages.mergeflow, "merge_dev", side_effect=stages.MergeError("boom")):
            code = self.call(stages.run_release, self.game, "both", CHANGELOG, True, self.runner, self.record)
        self.assertEqual(code, 1, self.out)
        self.assertTrue(self.record.run.data["allow_moved_dev"])
        self.assertEqual(self.resume(), 3, self.out)  # the override carries over to the retry

    def test_m1_abort_after_exit_3_then_resume_merges_again(self):
        """Probe B: exit 3, the user aborts the merge, resume re-runs the merge on the same dev commit."""
        self.conflict()
        self.assertEqual(self.release(), 3, self.out)
        git(self.repo, "merge", "--abort")
        self.assertEqual(self.resume(), 3, self.out)
        self.assertIn("aborted by hand", self.out)
        self.assertIn("Resume runs the merge again", self.out)
        self.assertTrue(self.merge_head())
        self.write(CODE, "class A {\n    int x = 2;\n}\n")
        git(self.repo, "add", "--", CODE)
        self.assertEqual(self.resume(), 0, self.out)

    def test_i1_tainted_pushed_baseline_still_fails_required_profile(self):
        """Probe F: origin/release already holds the dev profile; the required value still stops it."""
        self.release_ready(lambda: self.write(ADDR, "MonoBehaviour:\n  m_ActiveProfileId: devprofile\n"))
        git(self.repo, "switch", "-q", "release")
        subprocess.run(["git", "merge", "--no-ff", "--no-edit", "dev"], cwd=self.repo, capture_output=True)
        git(self.repo, "update-ref", "refs/remotes/origin/release", "release")  # "pushed"
        git(self.repo, "switch", "-q", "dev")
        self.assertEqual(self.release(), 1, self.out)
        self.assertIn(PROD, self.out)
        self.assertIn("devprofile", self.out)
        self.assertEqual(self.builds(), [])


class FinalFixRound(Base):
    def test_cr_only_manifest_is_restored_after_outputs_commit(self):
        self.crlf_paths = [MANIFEST]
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        self.assertEqual(self.call(stages.run_test, self.game, "android", None, self.runner, self.record), 0, self.out)
        self.assertIn("Restored " + MANIFEST, self.out)
        self.assertNotIn(b"\r", (self.repo / MANIFEST).read_bytes())
        self.assertEqual(git(self.repo, "diff", "--name-only"), "")
        git(self.repo, "switch", "-q", "release")  # the next switch no longer refuses

    def test_cr_only_dirty_before_the_run_is_left_alone(self):
        self.to_crlf(MANIFEST)
        self.crlf_paths = []
        self.assertEqual(self.call(stages.run_test, self.game, "android", None, self.runner, self.record), 0, self.out)
        self.assertIn(b"\r\n", (self.repo / MANIFEST).read_bytes())

    def _ctx(self, dirty):
        from types import SimpleNamespace
        return SimpleNamespace(game=self.game, runner=self.runner, data={"dirty_at_start": dirty})

    def test_content_change_is_never_restored(self):
        self.write(MANIFEST, '<manifest>\r\n  <application android:label="CHANGED">\r\n  </application>\r\n</manifest>\r\n')
        stages._restore_cr_only(self._ctx([]))
        self.assertIn("CHANGED", self.read(MANIFEST))
        self.assertIn(b"\r\n", (self.repo / MANIFEST).read_bytes())

    def test_path_dirty_at_start_is_not_restored(self):
        self.to_crlf(MANIFEST)
        stages._restore_cr_only(self._ctx([MANIFEST]))
        self.assertIn(b"\r\n", (self.repo / MANIFEST).read_bytes())

    def test_rclone_failure_in_release_gates_exits_2_and_saves_no_run(self):
        self.release_ready()
        with mock.patch.object(drive, "remote_file", side_effect=StepFailed("rclone lsjson of '' failed: boom")):
            self.assertEqual(self.release(), 2, self.out)
        self.assertIn("Stopped before the run started:", self.out)
        self.assertNotIn("FAILED", self.out)
        self.assertIsNone(self.record.run)
        self.assertEqual(self.builds(), [])

    def test_failure_after_run_starts_still_exits_1(self):
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        self.build_fails = True
        self.assertEqual(self.call(stages.run_test, self.game, "android", None, self.runner, self.record), 1, self.out)
        self.assertIsNotNone(self.record.run)


class OtaStage(Base):
    """A Amber-shaped test game with Beryl's `ota` block."""

    def setUp(self):
        super().setUp()
        self.game = replace(self.game, ota=load_game("beryl").ota)
        self.ota_calls = []
        self.ota_fail_once = None
        patches = [
            mock.patch.object(minio, "ota_outputs", side_effect=lambda g, prof, plat, ver, since: []),
            mock.patch.object(minio, "upload", side_effect=self.fake_ota_upload),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def resume(self):
        return self.call(stages.resume, self.game, self.runner, self.record)

    def fake_ota_upload(self, game, profile, platform, ver, files, runner, may_replace, hook=None):
        self.ev(f"ota:{profile}/{platform}")
        self.ota_calls.append((profile, platform, may_replace))
        if self.ota_fail_once == "frozen":
            self.ota_fail_once = None
            raise minio.ProductionFrozen("frozen")
        if hook:
            hook()
        if self.ota_fail_once == "after_hook":
            self.ota_fail_once = None
            raise StepFailed("Upload of 'catalog_0.1.8.bin' failed: connection reset")
        return 3

    def test_amber_steps_unchanged(self):
        run = rec.RunState(stage="test", platform="both", branch="dev", version="0.1.8")
        self.assertEqual(stages._step_names(run, load_game("amber")),
                         ["preflight", "bump", "build_android", "build_ios", "install_android",
                          "upload_test_apk", "install_ios", "commit", "record"])
        run = rec.RunState(stage="release", platform="both", branch="release", version="0.1.8")
        self.assertEqual(stages._step_names(run, load_game("amber")),
                         ["preflight", "merge", "guards", "conclude", "build_android", "build_ios",
                          "upload_android", "archive_ios", "upload_ios", "testflight", "commit", "messages"])

    def test_ota_test_stage_order(self):
        self.record.released.append("0.1.7")
        code = self.call(stages.run_test, self.game, "both", "0.1.8", self.runner, self.record)
        self.assertEqual(code, 0, self.out)
        ev = [e for e in self.events if e.startswith(("build:", "ota:", "install", "probe"))]
        self.assertEqual(ev, ["build:0-And_Test", "ota:development/Android", "build:0-iOS_Test",
                              "ota:development/iOS", "install_apk", "probe_ios", "install_ios"])
        self.assertEqual(self.ota_calls, [("development", "Android", True), ("development", "iOS", True)])
        self.assertIn("https://ota.example.com/beryl/development/Android/v0.1.8/", self.out)

    def test_ota_release_uses_production_and_freezes(self):
        self.release_ready()
        self.assertEqual(self.release(), 0, self.out)
        self.assertEqual(self.ota_calls, [("production", "Android", False), ("production", "iOS", False)])
        ev = [e for e in self.events if e.startswith(("ota:", "upload", "testflight"))]
        self.assertEqual(ev[:2], ["ota:production/Android", "ota:production/iOS"])

    def test_resume_after_failed_ota_release_upload_may_replace(self):
        self.release_ready()
        self.ota_fail_once = "after_hook"
        self.assertEqual(self.release(), 1, self.out)
        self.assertEqual(self.resume(), 0, self.out)
        self.assertEqual(self.ota_calls[:2], [("production", "Android", False), ("production", "Android", True)])

    def test_hand_released_version_stops_release(self):
        self.release_ready()
        self.ota_fail_once = "frozen"
        self.assertEqual(self.release(), 1, self.out)
        self.assertEqual(self.uploads, [])
        self.assertNotIn("testflight", self.events)
        self.assertEqual(self.record.run.data.get("ota_uploaded", []), [])


if __name__ == "__main__":
    unittest.main()
