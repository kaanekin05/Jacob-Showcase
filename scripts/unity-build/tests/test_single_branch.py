"""Single-branch games (test and release from one branch) and -executeMethod builds, as g-coral uses."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ub import stages, unitybuild
from ub import record as rec
from ub.config import load_game
from ub.guards import release_violations, snapshot
from ub.runner import FakeRunner
from tests.test_stages import Base as StageBase, PS, SRD, git
from tests.test_unitybuild import Base as BuildBase, LogWriter

FARM = load_game("coral")


class FarmSettings(unittest.TestCase):
    def test_farm_is_single_branch_with_build_method(self):
        self.assertTrue(FARM.single_branch)
        self.assertEqual(FARM.dev_branch, "development")
        self.assertEqual(FARM.build_method, "Coral.BuildTools.CoralBuildPipeline.Build")
        self.assertEqual(FARM.drive_folder_id, "1EXAMPLEdriveFoldercoralxxxxxxxxx")
        self.assertEqual(FARM.keystore_env, ("FARM_KEYSTORE_PASS", "FARM_KEYALIAS_PASS"))

    def test_other_games_unchanged(self):
        for game in ("amber", "beryl"):
            g = load_game(game)
            self.assertFalse(g.single_branch, game)
            self.assertIsNone(g.build_method, game)
            self.assertIsNone(g.apk_names, game)

    def test_farm_release_steps_have_no_merge(self):
        run = rec.RunState(stage="release", platform="both", branch="development", version="1.2.7")
        self.assertEqual(stages._step_names(run, FARM),
                         ["preflight", "head_guards", "build_android", "build_ios", "upload_android",
                          "archive_ios", "upload_ios", "testflight", "commit", "messages"])
        run = rec.RunState(stage="test", platform="android", branch="development", version="1.2.7")
        self.assertEqual(stages._step_names(run, FARM),
                         ["preflight", "bump", "build_android", "install_android", "upload_test_apk",
                          "commit", "record"])


class ExecuteMethodBuild(BuildBase):
    def setUp(self):
        super().setUp()
        self.game = replace(FARM, project_path=self.repo)

    def cmd_for(self, profile, out):
        fake = LogWriter()
        unitybuild.build(self.game, profile, out, self.repo / "b.log", fake)
        return fake.calls[0].cmd

    def test_android_profile_uses_execute_method(self):
        out = self.repo / "Builds/v1.2.7/Android/CoralTest.apk"
        cmd = self.cmd_for("0-And_Test", out)
        self.assertEqual(cmd[cmd.index("-buildTarget") + 1], "Android")
        self.assertEqual(cmd[cmd.index("-executeMethod") + 1], FARM.build_method)
        self.assertEqual(cmd[cmd.index("-ubProfile") + 1], "0-And_Test")
        self.assertEqual(cmd[cmd.index("-ubOut") + 1], str(out))
        self.assertEqual(cmd[cmd.index("-logFile") + 1], str(self.repo / "b.log"))
        self.assertNotIn("-activeBuildProfile", cmd)
        self.assertNotIn("-build", cmd)

    def test_ios_profile_gets_ios_target(self):
        cmd = self.cmd_for("1-iOS_Release", self.repo / "Builds/v1.2.7/iOS")
        self.assertEqual(cmd[cmd.index("-buildTarget") + 1], "iOS")


class HeadGuards(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.write(SRD, "MonoBehaviour:\n  _isEnabled: 0\n")
        self.write(PS, "PlayerSettings:\n  scriptingDefineSymbols:\n    Android: DOTWEEN\n    iPhone: DOTWEEN\n")
        self.write("Assets/Plugins/Android/AndroidManifest.xml", '<manifest>\n  <application android:label="x" />\n</manifest>\n')
        self.game = replace(FARM, project_path=self.root)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def check(self):
        return release_violations(self.game, snapshot(self.game))

    def test_release_values_pass(self):
        self.assertEqual(self.check(), [])

    def test_sr_enabled_fails(self):
        self.write(SRD, "MonoBehaviour:\n  _isEnabled: 1\n")
        self.assertEqual(len(self.check()), 1)
        self.assertIn("_isEnabled is '1'", self.check()[0])

    def test_sr_defines_fail(self):
        self.write(PS, "PlayerSettings:\n  scriptingDefineSymbols:\n    Android: DOTWEEN;SR_ENABLED\n"
                       "    iPhone: DISABLE_SRDEBUGGER\n")
        out = self.check()
        self.assertEqual(len(out), 2, out)
        self.assertIn("Android scripting defines contain SR_ENABLED", out[0])
        self.assertIn("iPhone scripting defines contain DISABLE_SRDEBUGGER", out[1])

    def test_debuggable_fails(self):
        self.write("Assets/Plugins/Android/AndroidManifest.xml",
                   '<manifest>\n  <application android:debuggable="true" />\n</manifest>\n')
        self.assertIn("android:debuggable", self.check()[0])

    def test_missing_file_fails_closed(self):
        (self.root / SRD).unlink()
        self.assertIn("the file is missing", self.check()[0])


class SingleBranchStages(StageBase):
    """The stage harness with Amber's settings, but test and release both on 'dev'."""

    def setUp(self):
        super().setUp()
        profiles = {s: {**p, "branch": "dev"} for s, p in self.game.profiles.items()}
        self.game = replace(self.game, release_branch="dev", profiles=profiles)

    def test_release_builds_tested_commit_without_merge(self):
        self.release_ready()
        tested = self.head("dev")
        code = self.release()
        self.assertEqual(code, 0, self.out)
        self.assertEqual(self.builds(), ["build:2-APK_Release", "build:3-AAB_Release", "build:1-iOS_Release"])
        self.assertEqual(git(self.repo, "symbolic-ref", "--short", "HEAD"), "dev")
        self.assertFalse(self.merge_head())
        log = git(self.repo, "log", "--format=%s", "dev").splitlines()
        self.assertEqual(log[0], "chore(build): record v0.1.8 release outputs")
        self.assertEqual(git(self.repo, "rev-parse", "dev~1"), tested, "only the outputs commit sits on top")
        self.assertIn("0.1.8", self.record.released)
        self.assertIsNone(self.record.run)

    def test_release_needs_no_origin_baseline(self):
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/release")
        self.release_ready()
        self.assertEqual(self.release(), 0, self.out)

    def test_guard_violation_at_head_stops_before_builds(self):
        self.release_ready(lambda: self.write(SRD, "MonoBehaviour:\n  _isEnabled: 1\n"))
        tip = self.head()
        self.assertEqual(self.release(), 1)
        self.assertIn("GUARD:", self.out)
        self.assertIn("_isEnabled", self.out)
        self.assertEqual(self.builds(), [])
        self.assertEqual(self.head(), tip, "nothing was committed")

    def test_untested_commit_stops(self):
        self.release_ready()
        self.commit_on("dev", lambda: self.write("Assets/a.cs", "class A {\n    int x = 9;\n}\n"))
        self.assertEqual(self.release(), 2)
        self.assertIn("moved", self.out)
        self.assertEqual(self.builds(), [])

    def test_resume_after_failed_build(self):
        self.release_ready()
        self.build_fails = True
        self.assertEqual(self.release(), 1)
        self.build_fails = False
        self.assertEqual(self.call(stages.resume, self.game, self.runner, self.record), 0, self.out)
        self.assertIn("0.1.8", self.record.released)

    def test_bump_only_after_release(self):
        self.commit_on("dev", self.numbers("0.1.8", 18, 18))
        self.assertEqual(self.call(stages.check, self.game, "test", "android", self.runner, self.record), 0, self.out)
        self.assertIn("Retest: the version stays v0.1.8.", self.out)
        self.record.released.append("0.1.8")
        self.call(stages.check, self.game, "test", "android", self.runner, self.record)
        self.assertIn("Proposed version: 0.1.9", self.out)

    def test_test_then_release_on_one_branch(self):
        self.record.released.append("0.1.7")
        code = self.call(stages.run_test, self.game, "android", "0.1.8", self.runner, self.record)
        self.assertEqual(code, 0, self.out)
        self.assertIn("0.1.8", self.record.tested)
        self.assertEqual(self.release(platform="android"), 0, self.out)
        self.assertEqual(self.builds(), ["build:0-And_Test", "build:2-APK_Release", "build:3-AAB_Release"])


if __name__ == "__main__":
    unittest.main()
