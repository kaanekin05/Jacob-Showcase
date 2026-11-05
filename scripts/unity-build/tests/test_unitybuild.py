import os
import shutil
import subprocess
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from ub import unitybuild
from ub.config import load_game
from ub.runner import FakeRunner, Result, Runner
from ub.unitybuild import StepFailed

PROFILE = "Assets/Settings/Build Profiles/{}.asset"
OK_LOG = "stuff\nBuild Finished, Result: Success.\n"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


class Recording:
    """Real commands, with every call recorded."""

    def __init__(self):
        self.real = Runner()
        self.calls = []

    def run(self, cmd, cwd=None, env=None, input=None):
        self.calls.append(list(cmd))
        return self.real.run(cmd, cwd, env, input)


class LogWriter:
    """Fake Unity: writes the log the way a real run would, then returns exit 0 (or `code`)."""

    def __init__(self, log_text=OK_LOG, code=0):
        self.fake = FakeRunner([Result(code)])
        self.calls = self.fake.calls
        self.log_text = log_text

    def run(self, cmd, cwd=None, env=None, input=None):
        if "-logFile" in cmd and self.log_text is not None:
            Path(cmd[cmd.index("-logFile") + 1]).write_text(self.log_text)
        return self.fake.run(cmd, cwd, env, input)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        genv = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
        genv.start()
        self.addCleanup(genv.stop)
        self.repo = r = Path(tmp.name)
        git(r, "init", "-q", "-b", "dev")
        git(r, "config", "user.email", "t@t")
        git(r, "config", "user.name", "t")
        git(r, "config", "core.autocrlf", "false")
        (r / ".gitignore").write_text("Builds/\n")
        (r / "ProjectSettings").mkdir()
        (r / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.67f1\n")
        (r / "Assets/Plugins/Android").mkdir(parents=True)
        (r / "Assets/Plugins/Android/AndroidManifest.xml").write_bytes(b"a\nb\n")
        (r / "crashlytics_build_id.xml").write_text("old\n")
        (r / "VersionTracker").mkdir()
        (r / "VersionTracker/Amber_0.1.6_Android_BuildInfo.json").write_text("{}\n")
        (r / ".memsearch").mkdir()
        (r / ".memsearch/notes.md").write_text("n\n")
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "init")
        self.game = replace(load_game("amber"), project_path=r)
        self.unity = Path(tmp.name + "-unity/6000.0.67f1/Unity")
        self.unity.parent.mkdir(parents=True)
        self.unity.write_text("")
        self.addCleanup(shutil.rmtree, tmp.name + "-unity", True)
        patch = mock.patch.object(unitybuild, "UNITY_BIN", tmp.name + "-unity/{}/Unity")
        patch.start()
        self.addCleanup(patch.stop)
        self.since = time.time() - 60

    def stale(self, path):
        old = self.since - 100
        os.utime(path, (old, old))

    def out(self, platform="Android"):
        d = self.repo / "Builds/v0.1.7" / platform
        d.mkdir(parents=True, exist_ok=True)
        return d

    def info(self, platform="Android", ver="0.1.7"):
        p = self.repo / "VersionTracker" / f"Amber_{ver}_{platform}_BuildInfo.json"
        p.write_text("{}\n")
        return p


class BuildTests(Base):
    def test_build_passes_profile_and_output(self):
        log = self.repo / "b.log"
        fake = LogWriter()
        out = self.repo / "Builds/v0.1.7/Android/Amber_v.0.1.7_T.apk"
        start = unitybuild.build(self.game, "0-And_Test", out, log, fake)
        self.assertIsInstance(start, float)
        cmd = fake.calls[0].cmd
        self.assertEqual(cmd[0], str(self.unity))
        for flag in ("-batchmode", "-quit"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("-projectPath") + 1], str(self.repo))
        self.assertEqual(cmd[cmd.index("-activeBuildProfile") + 1], PROFILE.format("0-And_Test"))
        self.assertEqual(cmd[cmd.index("-build") + 1], str(out))
        self.assertEqual(cmd[cmd.index("-logFile") + 1], str(log))

    def test_nonzero_exit_fails_and_names_log(self):
        log = self.repo / "b.log"
        with self.assertRaises(StepFailed) as cm:
            unitybuild.build(self.game, "0-And_Test", self.repo / "o", log, LogWriter(code=1))
        self.assertIn(str(log), str(cm.exception))

    def test_exit_zero_without_success_line_fails_and_names_log(self):
        log = self.repo / "b.log"
        with self.assertRaises(StepFailed) as cm:
            unitybuild.build(self.game, "0-And_Test", self.repo / "o", log,
                             LogWriter("Build Finished, Result: Failure.\n"))
        self.assertIn(str(log), str(cm.exception))

    def test_exit_zero_with_no_log_file_fails(self):
        log = self.repo / "none.log"
        with self.assertRaises(StepFailed) as cm:
            unitybuild.build(self.game, "0-And_Test", self.repo / "o", log, LogWriter(None))
        self.assertIn(str(log), str(cm.exception))

    def test_stale_log_with_success_line_does_not_pass(self):
        log = self.repo / "b.log"
        log.write_text(OK_LOG)
        with self.assertRaises(StepFailed):
            unitybuild.build(self.game, "0-And_Test", self.repo / "o", log, LogWriter(None))

    def test_preclean_removes_old_output_and_symbols_only(self):
        d = self.out()
        aab, sym = d / "Amber-0.1.7-v17.aab", d / "Amber-0.1.7-v17.symbols.zip"
        keep = d / "Amber_v.0.1.7_T.apk"
        for f in (aab, sym, keep):
            f.write_text("old")
        (d / "dir.symbols.zip").mkdir()
        unitybuild.build(self.game, "3-AAB_Release", aab, self.repo / "b.log", LogWriter())
        self.assertFalse(aab.exists())
        self.assertFalse(sym.exists())
        self.assertTrue(keep.exists())
        self.assertTrue((d / "dir.symbols.zip").is_dir())

    def test_missing_unity_binary_is_step_failed(self):
        self.unity.unlink()
        with self.assertRaises(StepFailed) as cm:
            unitybuild.build(self.game, "0-And_Test", self.repo / "o", self.repo / "b.log", LogWriter())
        self.assertIn("6000.0.67f1", str(cm.exception))

    def test_missing_project_version_is_step_failed(self):
        (self.repo / "ProjectSettings/ProjectVersion.txt").unlink()
        with self.assertRaises(StepFailed):
            unitybuild.build(self.game, "0-And_Test", self.repo / "o", self.repo / "b.log", LogWriter())


class OutputTests(Base):
    def test_test_stage_collects_apk(self):
        apk = self.out() / "Amber_v.0.1.7_T.apk"
        apk.write_text("apk")
        self.assertEqual(unitybuild.outputs_android(self.game, "0.1.7", 17, "test", self.since), [apk])

    def test_success_with_missing_apk_fails(self):
        self.out()
        with self.assertRaises(StepFailed) as cm:
            unitybuild.outputs_android(self.game, "0.1.7", 17, "test", self.since)
        self.assertEqual(str(cm.exception).count("Amber_v.0.1.7_T.apk"), 1)
        self.assertNotIn("\n", str(cm.exception))

    def release_files(self, symbols=None):
        d = self.out()
        for n in ("Amber_v.0.1.7_R.apk", "Amber-0.1.7-v17.aab"):
            (d / n).write_text("x")
        if symbols:
            (d / symbols).write_text("sym")
        self.info()
        return d

    def test_release_collects_all_four_and_copies_buildinfo(self):
        d = self.release_files("Amber-0.1.7-v17-IL2CPP.symbols.zip")
        got = unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertEqual([p.name for p in got], [
            "Amber_v.0.1.7_R.apk", "Amber-0.1.7-v17.aab",
            "Amber-0.1.7-v17-IL2CPP.symbols.zip", "Amber_0.1.7_Android_BuildInfo.json"])
        self.assertTrue((d / "Amber_0.1.7_Android_BuildInfo.json").exists())
        self.assertTrue(all(p.parent == d for p in got))

    def test_unity_named_symbols_are_collected_under_spec_name(self):
        d = self.release_files("Amber-0.1.7-v17.aab-0.1.7-v17.symbols.zip")
        got = unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertEqual(got[2], d / "Amber-0.1.7-v17-IL2CPP.symbols.zip")
        self.assertEqual(got[2].read_text(), "sym")

    def test_missing_symbols_fails(self):
        self.release_files()
        with self.assertRaises(StepFailed) as cm:
            unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertIn("Amber-0.1.7-v17-IL2CPP.symbols.zip", str(cm.exception))

    def test_burst_debug_folder_is_never_collected(self):
        d = self.release_files("Amber-0.1.7-v17-IL2CPP.symbols.zip")
        for where in (d, d.parent):
            (where / "Amber_BurstDebugInformation_DoNotShip").mkdir(exist_ok=True)
        got = unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertEqual(len(got), 4)
        self.assertFalse([p for p in got if "BurstDebug" in str(p)])

    def test_stale_apk_fails_as_stale(self):
        apk = self.out() / "Amber_v.0.1.7_T.apk"
        apk.write_text("apk")
        self.stale(apk)
        with self.assertRaises(StepFailed) as cm:
            unitybuild.outputs_android(self.game, "0.1.7", 17, "test", self.since)
        self.assertIn("Stale", str(cm.exception))
        self.assertIn(str(apk), str(cm.exception))

    def test_stale_spec_named_symbols_fail(self):
        d = self.release_files("Amber-0.1.7-v17-IL2CPP.symbols.zip")
        self.stale(d / "Amber-0.1.7-v17-IL2CPP.symbols.zip")
        with self.assertRaises(StepFailed) as cm:
            unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertIn("Stale", str(cm.exception))
        self.assertIn("IL2CPP.symbols.zip", str(cm.exception))

    def test_stale_unity_named_zip_never_fails_the_next_build(self):
        d = self.out()
        old = d / "Amber-0.1.7-v17.aab-0.1.7-v17.symbols.zip"
        old.write_text("old")
        self.stale(old)
        aab = d / "Amber-0.1.7-v17.aab"
        unitybuild.build(self.game, "3-AAB_Release", aab, self.repo / "b.log", LogWriter())
        self.assertFalse(old.exists())
        (d / "Amber_v.0.1.7_R.apk").write_text("x")
        aab.write_text("x")
        (d / "Amber-0.1.7-v17.aab-new.symbols.zip").write_text("fresh")
        self.info()
        got = unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertEqual(got[2].read_text(), "fresh")

    def test_stale_unity_named_zip_next_to_fresh_one_is_ignored(self):
        d = self.release_files()
        old = d / "old.symbols.zip"
        old.write_text("old")
        self.stale(old)
        (d / "new.symbols.zip").write_text("fresh")
        got = unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertEqual(got[2].read_text(), "fresh")

    def test_only_stale_unity_named_zip_fails(self):
        d = self.release_files()
        old = d / "old.symbols.zip"
        old.write_text("old")
        self.stale(old)
        with self.assertRaises(StepFailed):
            unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)

    def test_copied_symbols_get_a_fresh_mtime(self):
        d = self.release_files()
        src = d / "u.symbols.zip"
        src.write_text("fresh")
        got = unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertGreaterEqual(got[2].stat().st_mtime, self.since)

    def test_stale_buildinfo_fails(self):
        self.release_files("Amber-0.1.7-v17-IL2CPP.symbols.zip")
        self.stale(self.repo / "VersionTracker/Amber_0.1.7_Android_BuildInfo.json")
        with self.assertRaises(StepFailed) as cm:
            unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertIn("Stale", str(cm.exception))
        self.assertIn("BuildInfo.json", str(cm.exception))

    def test_missing_buildinfo_fails(self):
        d = self.release_files("Amber-0.1.7-v17-IL2CPP.symbols.zip")
        (self.repo / "VersionTracker/Amber_0.1.7_Android_BuildInfo.json").unlink()
        with self.assertRaises(StepFailed) as cm:
            unitybuild.outputs_android(self.game, "0.1.7", 17, "release", self.since)
        self.assertIn("Amber_0.1.7_Android_BuildInfo.json", str(cm.exception))

    def ios_dir(self, workspace=True):
        d = self.out("iOS")
        (d / "Unity-iPhone.xcodeproj").mkdir()
        (d / "Unity-iPhone.xcodeproj/project.pbxproj").write_text("p")
        if workspace:
            (d / "Unity-iPhone.xcworkspace").mkdir()
        self.info("iOS")
        return d

    def test_ios_outputs(self):
        self.ios_dir()
        got = unitybuild.outputs_ios(self.game, "0.1.7", self.since)
        self.assertEqual([p.name for p in got], ["Unity-iPhone.xcodeproj", "Unity-iPhone.xcworkspace",
                                                 "Amber_0.1.7_iOS_BuildInfo.json"])

    def test_ios_missing_project_fails(self):
        d = self.ios_dir()
        shutil.rmtree(d / "Unity-iPhone.xcodeproj")
        with self.assertRaises(StepFailed) as cm:
            unitybuild.outputs_ios(self.game, "0.1.7", self.since)
        self.assertIn("Unity-iPhone.xcodeproj", str(cm.exception))

    def test_ios_rebuild_into_old_folder_passes_when_pbxproj_is_fresh(self):
        d = self.ios_dir()
        self.stale(d / "Unity-iPhone.xcodeproj")
        self.stale(d / "Unity-iPhone.xcworkspace")
        got = unitybuild.outputs_ios(self.game, "0.1.7", self.since)
        self.assertEqual(len(got), 3)

    def test_ios_stale_pbxproj_fails(self):
        d = self.ios_dir()
        self.stale(d / "Unity-iPhone.xcodeproj/project.pbxproj")
        with self.assertRaises(StepFailed) as cm:
            unitybuild.outputs_ios(self.game, "0.1.7", self.since)
        self.assertIn("Stale", str(cm.exception))
        self.assertIn("project.pbxproj", str(cm.exception))

    def test_directory_named_like_an_output_is_not_a_file(self):
        (self.out() / "Amber_v.0.1.7_T.apk").mkdir()
        with self.assertRaises(StepFailed):
            unitybuild.outputs_android(self.game, "0.1.7", 17, "test", self.since)

    def test_ios_missing_workspace_fails(self):
        self.ios_dir(workspace=False)
        with self.assertRaises(StepFailed) as cm:
            unitybuild.outputs_ios(self.game, "0.1.7", self.since)
        self.assertIn("Unity-iPhone.xcworkspace", str(cm.exception))


HDR = "List of devices attached\n"
USB = "b5c31664               device usb:51642368X product:OnePlus6 model:ONEPLUS_A6003 device:OnePlus6 transport_id:1\n"
MDNS = "adb-b5c31664-AbCdEf._adb-tls-connect._tcp device product:OnePlus6 model:ONEPLUS_A6003 device:OnePlus6 transport_id:2\n"
WIFI = "192.168.1.20:5555       device product:OnePlus6 model:ONEPLUS_A6003 device:OnePlus6 transport_id:3\n"


class InstallTests(unittest.TestCase):
    def install(self, listing, code=0):
        fake = FakeRunner([Result(0, listing), Result(code, "Success")])
        ok = unitybuild.install_apk(Path("a.apk"), fake)
        return ok, fake

    def test_install_apk_without_phone_returns_false(self):
        for listing in (HDR + "\n", HDR + "ABC\toffline\nDEF\tunauthorized\n",
                        HDR + "ABC                    offline transport_id:1\n"):
            ok, fake = self.install(listing)
            self.assertFalse(ok)
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(fake.calls[0].cmd, ["adb", "devices", "-l"])

    def test_install_failure_on_present_phone_raises_with_adb_error(self):
        fake = FakeRunner([Result(0, HDR + USB),
                           Result(1, "Performing Streamed Install\nadb: failed to install a.apk: "
                                     "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]\n")])
        with self.assertRaises(StepFailed) as cm:
            unitybuild.install_apk(Path("a.apk"), fake)
        self.assertIn("INSTALL_FAILED_UPDATE_INCOMPATIBLE", str(cm.exception))

    def test_two_serials_picks_the_usb_one(self):
        ok, fake = self.install(HDR + WIFI + USB)
        self.assertTrue(ok)
        self.assertEqual(fake.calls[1].cmd, ["adb", "-s", "b5c31664", "install", "-r", "a.apk"])

    def test_mdns_serial_listed_first_still_picks_usb(self):
        ok, fake = self.install(HDR + MDNS + USB)
        self.assertEqual(fake.calls[1].cmd[2], "b5c31664")

    def test_wireless_only_uses_the_first_serial(self):
        ok, fake = self.install(HDR + MDNS + WIFI)
        self.assertTrue(ok)
        self.assertEqual(fake.calls[1].cmd, ["adb", "-s", "adb-b5c31664-AbCdEf._adb-tls-connect._tcp",
                                             "install", "-r", "a.apk"])

    def test_single_device_still_passes_dash_s(self):
        ok, fake = self.install(HDR + USB)
        self.assertEqual(fake.calls[1].cmd, ["adb", "-s", "b5c31664", "install", "-r", "a.apk"])

    def test_offline_usb_is_not_chosen(self):
        ok, fake = self.install(HDR + "USB1 offline usb:1 transport_id:1\n" + WIFI)
        self.assertEqual(fake.calls[1].cmd[2], "192.168.1.20:5555")

    def test_missing_adb_is_step_failed(self):
        class NoAdb:
            def run(self, *a, **k):
                raise FileNotFoundError(2, "No such file or directory")
        with self.assertRaises(StepFailed):
            unitybuild.install_apk(Path("a.apk"), NoAdb())


class CommitTests(Base):
    def dirty(self):
        (self.repo / "crashlytics_build_id.xml").write_text("new\n")
        self.info("Android")
        (self.repo / ".memsearch/notes.md").write_text("changed\n")
        (self.repo / ".memsearch/new.md").write_text("x\n")
        (self.repo / "Assets/stray.txt").write_text("stray\n")

    def test_commit_skips_session_paths(self):
        self.dirty()
        sha = unitybuild.commit_outputs(self.game, "v0.1.7 test", Runner())
        self.assertEqual(sha, git(self.repo, "rev-parse", "HEAD").strip())
        files = set(git(self.repo, "show", "--name-only", "--format=", "HEAD").split())
        self.assertEqual(files, {"crashlytics_build_id.xml",
                                 "VersionTracker/Amber_0.1.7_Android_BuildInfo.json"})
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "chore(build): record v0.1.7 test outputs\n")
        status = git(self.repo, "status", "--porcelain")
        self.assertIn(".memsearch/notes.md", status)
        self.assertIn("Assets/stray.txt", status)

    def test_commit_never_uses_add_all(self):
        self.dirty()
        rec = Recording()
        unitybuild.commit_outputs(self.game, "v0.1.7 test", rec)
        for call in rec.calls:
            for bad in ("-A", "-a", ".", "--all", "-am"):
                self.assertNotIn(bad, call)

    def test_commit_with_no_changes_returns_none(self):
        before = git(self.repo, "rev-parse", "HEAD")
        self.assertIsNone(unitybuild.commit_outputs(self.game, "v0.1.7 test", Runner()))
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), before)

    def test_commit_with_only_session_changes_returns_none(self):
        (self.repo / ".memsearch/notes.md").write_text("changed\n")
        self.assertIsNone(unitybuild.commit_outputs(self.game, "v0.1.7 test", Runner()))

    def test_line_ending_only_change_is_left_out(self):
        (self.repo / "Assets/Plugins/Android/AndroidManifest.xml").write_bytes(b"a\r\nb\r\n")
        self.assertIsNone(unitybuild.commit_outputs(self.game, "v0.1.7 test", Runner()))
        (self.repo / "crashlytics_build_id.xml").write_text("new\n")
        unitybuild.commit_outputs(self.game, "v0.1.7 test", Runner())
        files = git(self.repo, "show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(files, ["crashlytics_build_id.xml"])

    def test_git_diff_quiet_failure_is_step_failed(self):
        (self.repo / "crashlytics_build_id.xml").write_text("new\n")

        class Broken(Recording):
            def run(self, cmd, cwd=None, env=None, input=None):
                if "--quiet" in cmd:
                    from ub.runner import Result as R
                    return R(128, "", "fatal: boom")
                return super().run(cmd, cwd, env, input)

        with self.assertRaises(StepFailed) as cm:
            unitybuild.commit_outputs(self.game, "v0.1.7 test", Broken())
        self.assertIn("boom", str(cm.exception))

    def test_pathspec_characters_are_literal(self):
        r = self.repo
        (r / "a*.txt").write_text("1\n")
        (r / "ab.txt").write_bytes(b"x\ny\n")
        git(r, "add", "--", "a*.txt", "ab.txt")
        git(r, "commit", "-q", "-m", "more")
        (r / "a*.txt").write_text("2\n")
        (r / "ab.txt").write_bytes(b"x\r\ny\r\n")  # line endings only
        rec = Recording()
        unitybuild.commit_outputs(self.game, "v0.1.7 test", rec)
        self.assertEqual(git(r, "show", "--name-only", "--format=", "HEAD").split(), ["a*.txt"])
        self.assertTrue(all("--literal-pathspecs" in c for c in rec.calls))


if __name__ == "__main__":
    unittest.main()
