import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from ub.config import load_game
from ub.preflight import check
from ub.runner import FakeRunner, Result, Runner
from ub.record import fingerprint

PROFILE = "Assets/Settings/Build Profiles/{}.asset"


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


class Router:
    """Real git, scripted everything else. Records the non-git commands."""

    def __init__(self, xcode="Xcode 26.6\nBuild version 17A1", lfs=0, rclone=0, drivers=True):
        self.real = Runner()
        self.fake = FakeRunner()
        self.xcode, self.lfs, self.rclone, self.drivers = xcode, lfs, rclone, drivers

    def run(self, cmd, cwd=None, env=None, input=None):
        if cmd[:2] == ["git", "lfs"]:
            return Result(self.lfs)
        if cmd[0] == "git":
            if cmd[1:3] == ["config", "--get"] and cmd[3].startswith("merge."):
                return Result(0 if self.drivers else 1, "sh x\n" if self.drivers else "")
            return self.real.run(cmd, cwd, env, input)
        self.fake.run(cmd, cwd, env, input)
        if cmd[0] == "xcodebuild":
            return Result(0, self.xcode)
        if cmd[0] == "rclone":
            return Result(self.rclone, "[]", "NOTICE: Config file not found")
        return Result(0)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        genv = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
        genv.start()
        self.addCleanup(genv.stop)
        self.repo = Path(tmp.name)
        r = self.repo
        git(r, "init", "-q", "-b", "dev")
        git(r, "config", "user.email", "t@t")
        git(r, "config", "user.name", "t")
        git(r, "config", "core.autocrlf", "false")
        (r / ".gitignore").write_text("Builds/\nTemp/\n")
        (r / "Assets/Settings/Build Profiles").mkdir(parents=True)
        for p in ("0-And_Test", "0-iOS_Test", "2-APK_Release", "3-AAB_Release", "1-iOS_Release"):
            (r / PROFILE.format(p)).write_text("x\n")
        (r / "Assets/Plugins/Android").mkdir(parents=True)
        (r / "Assets/Plugins/Android/AndroidManifest.xml").write_text("a\nb\n")
        (r / "Assets/a.cs").write_text("class A {}\n")
        (r / ".memsearch").mkdir()
        (r / ".memsearch/notes.md").write_text("n1\n")
        (r / ".claude/agents").mkdir(parents=True)
        (r / ".claude/agents/s.md").write_text("s\n")
        (r / "Tools").mkdir()
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "init")
        git(r, "branch", "release")
        self.game = replace(load_game("amber"), project_path=r)
        self.env = mock.patch.dict(os.environ, {"AMBER_KEYSTORE_PASS": "x", "AMBER_KEYALIAS_PASS": "y"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def check(self, stage="test", platform="android", **kw):
        return check(self.game, stage, platform, Router(**kw))

    def joined(self, reasons):
        return "\n".join(reasons)


class Preflight(Base):
    def test_clean_repo_goes(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(self.check("release", "ios"), [])

    def test_stops_when_unity_open(self):
        (self.repo / "Temp").mkdir()
        (self.repo / "Temp/UnityLockfile").write_text("")
        self.assertIn("Unity", self.joined(self.check()))

    def test_stops_on_dirty_game_file(self):
        (self.repo / "Assets/a.cs").write_text("changed\n")
        out = self.joined(self.check())
        self.assertIn("Assets/a.cs", out)

    def test_merge_in_progress_is_its_own_stop_without_commit_advice(self):
        git(self.repo, "switch", "-q", "release")
        (self.repo / "Assets/a.cs").write_text("release\n")
        git(self.repo, "commit", "-qam", "r")
        git(self.repo, "switch", "-q", "dev")
        (self.repo / "Assets/a.cs").write_text("dev\n")
        git(self.repo, "commit", "-qam", "d")
        git(self.repo, "switch", "-q", "release")
        subprocess.run(["git", "merge", "--no-ff", "--no-commit", "dev"], cwd=self.repo, capture_output=True)
        reasons = self.check("release", "android")
        self.assertIn("A merge is in progress", reasons[0])
        self.assertIn("Do not commit it", reasons[0])
        self.assertNotIn("Commit or stash", self.joined(reasons))

    def test_stops_on_untracked_game_file(self):
        (self.repo / "Assets/new.cs").write_text("x\n")
        self.assertIn("Assets/new.cs", self.joined(self.check()))

    def test_crlf_only_change_counts_as_clean(self):
        (self.repo / "Assets/Plugins/Android/AndroidManifest.xml").write_bytes(b"a\r\nb\r\n")
        self.assertEqual(self.check(), [])

    def test_crlf_only_file_that_differs_on_target_blocks_switch(self):
        manifest = "Assets/Plugins/Android/AndroidManifest.xml"
        git(self.repo, "switch", "-q", "release")
        (self.repo / manifest).write_text("changed on release\n")
        git(self.repo, "commit", "-qam", "release manifest")
        git(self.repo, "switch", "-q", "dev")
        (self.repo / manifest).write_bytes(b"a\r\nb\r\n")
        out = self.joined(self.check("release"))
        self.assertIn(manifest, out)
        self.assertIn("Nothing was discarded", out)
        self.assertEqual((self.repo / manifest).read_bytes(), b"a\r\nb\r\n")

    def test_git_failure_is_a_stop_not_a_clean_tree(self):
        class Broken(Router):
            def run(self, cmd, cwd=None, env=None, input=None):
                if cmd[:2] == ["git", "diff"]:
                    return Result(128, "", "fatal: boom")
                return super().run(cmd, cwd, env, input)
        out = self.joined(check(self.game, "test", "android", Broken()))
        self.assertIn("boom", out)

    def test_unknown_platform_stops(self):
        self.assertIn("Unknown platform", self.joined(self.check(platform="windows")))

    def test_release_stops_when_dev_branch_missing(self):
        git(self.repo, "switch", "-q", "release")
        git(self.repo, "branch", "-D", "dev")
        self.assertIn("'dev' does not exist", self.joined(self.check("release")))

    def test_allows_dirty_session_file(self):
        (self.repo / ".memsearch/notes.md").write_text("n2\n")
        (self.repo / ".claude").joinpath("autoharness").mkdir()
        (self.repo / ".claude/autoharness/req").write_text("r\n")
        self.assertEqual(self.check(), [])

    def test_other_claude_paths_are_game_files(self):
        (self.repo / ".claude/agents/s.md").write_text("changed\n")
        self.assertIn(".claude/agents/s.md", self.joined(self.check()))

    def test_stops_when_session_file_blocks_switch(self):
        git(self.repo, "switch", "-q", "release")
        (self.repo / ".memsearch/notes.md").write_text("n-release\n")
        git(self.repo, "commit", "-qam", "release notes")
        git(self.repo, "switch", "-q", "dev")
        (self.repo / ".memsearch/notes.md").write_text("local edit\n")
        out = self.joined(self.check("release"))
        self.assertIn(".memsearch/notes.md", out)
        self.assertIn("switch", out)
        # nothing discarded
        self.assertEqual((self.repo / ".memsearch/notes.md").read_text(), "local edit\n")
        self.assertEqual(self.check("test"), [])  # same branch, no block

    def test_untracked_session_file_that_exists_on_target_blocks_switch(self):
        git(self.repo, "switch", "-q", "release")
        (self.repo / ".memsearch/only-release.md").write_text("r\n")
        git(self.repo, "add", ".memsearch/only-release.md")
        git(self.repo, "commit", "-qm", "r")
        git(self.repo, "switch", "-q", "dev")
        (self.repo / ".memsearch/only-release.md").write_text("mine\n")
        self.assertIn(".memsearch/only-release.md", self.joined(self.check("release")))

    def test_stops_on_missing_profile_on_branch(self):
        # dev (and the working tree) has the profile, the release branch does not
        git(self.repo, "switch", "-q", "release")
        git(self.repo, "rm", "-q", PROFILE.format("1-iOS_Release"))
        git(self.repo, "commit", "-qm", "drop")
        git(self.repo, "switch", "-q", "dev")
        out = self.joined(self.check("release", "ios"))
        self.assertIn("1-iOS_Release", out)
        self.assertIn("release", out)

    def test_stops_when_branch_missing(self):
        git(self.repo, "branch", "-m", "release", "rel2")
        self.assertIn("release", self.joined(self.check("release")))

    def test_stops_on_unregistered_merge_driver(self):
        out = self.joined(self.check(drivers=False))
        self.assertIn("keep-active-profile", out)

    def test_stops_on_wrong_xcode_major(self):
        out = self.joined(self.check(platform="ios", xcode="Xcode 27.0\nBuild version 1"))
        self.assertIn("27", out)
        self.assertIn("iOS 27", out)

    def test_xcode_ignored_for_android(self):
        self.assertEqual(self.check(platform="android", xcode="Xcode 27.0"), [])

    def test_stops_when_rclone_cannot_list_folder(self):
        r = Router(rclone=1)
        out = self.joined(check(self.game, "test", "android", r))
        self.assertIn("rclone", out)
        call = [c for c in r.fake.calls if c.cmd[0] == "rclone"][0]
        self.assertEqual(call.cmd, ["rclone", "lsjson", "studio-drive:", "--drive-root-folder-id",
                                    self.game.drive_folder_id, "--max-depth", "1"])

    def test_rclone_advice_is_the_safe_two_step_form(self):
        out = self.joined(check(self.game, "test", "android", Router(rclone=1)))
        self.assertIn("config delete", out)
        self.assertIn("> /dev/null", out)
        self.assertNotIn("reconnect", out)

    def test_rclone_notice_on_stderr_is_not_a_failure(self):
        self.assertEqual(self.check(rclone=0), [])

    def test_stops_when_lfs_missing(self):
        self.assertIn("LFS", self.joined(self.check(lfs=1)))

    def test_stops_when_builds_not_ignored(self):
        (self.repo / ".gitignore").write_text("Temp/\n")
        git(self.repo, "commit", "-qam", "unignore")
        self.assertIn("Builds/", self.joined(self.check()))

    def test_stops_without_signing_passwords(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("AMBER_KEYSTORE_PASS")
            self.assertIn("signing", self.joined(self.check()))

    def test_keystore_file_satisfies_signing(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("AMBER_KEYSTORE_PASS")
            os.environ.pop("AMBER_KEYALIAS_PASS")
            (self.repo / "Tools/keystore.local.json").write_text("{}")
            # file is untracked: it must not show up as a dirty game file either
            git(self.repo, "add", "-f", "Tools/keystore.local.json")
            git(self.repo, "commit", "-qm", "ks")
            self.assertEqual(self.check(), [])

    def test_signing_uses_the_game_own_env_names(self):
        self.game = replace(self.game, keystore_env=("BERYL_KEYSTORE_PASS", "BERYL_KEYALIAS_PASS"))
        with mock.patch.dict(os.environ, {"BERYL_KEYSTORE_PASS": "x", "BERYL_KEYALIAS_PASS": "y"}):
            os.environ.pop("AMBER_KEYSTORE_PASS")
            os.environ.pop("AMBER_KEYALIAS_PASS")
            self.assertEqual(self.check(), [])
        with mock.patch.dict(os.environ):
            msg = self.joined(self.check())
        self.assertIn("BERYL_KEYSTORE_PASS", msg)
        self.assertNotIn("AMBER", msg)

    def test_signing_not_required_for_ios(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("AMBER_KEYSTORE_PASS")
            self.assertEqual(self.check(platform="ios"), [])

    def test_check_never_mutates(self):
        (self.repo / "Assets/a.cs").write_text("changed\n")
        (self.repo / ".memsearch/notes.md").write_text("local\n")
        before = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True).stdout
        self.check("release")
        after = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True).stdout
        self.assertEqual(before, after)


class Fingerprint(Base):
    def fp(self, ref="dev"):
        return fingerprint(self.game, ref, Router())

    def test_fingerprint_ignores_session_paths(self):
        a = self.fp()
        (self.repo / ".memsearch/notes.md").write_text("more notes\n")
        (self.repo / ".memsearch/new.md").write_text("x\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "notes")
        self.assertEqual(a, self.fp())

    def test_fingerprint_ignores_autoharness_but_not_other_claude_paths(self):
        a = self.fp()
        (self.repo / ".claude/autoharness").mkdir()
        (self.repo / ".claude/autoharness/req").write_text("r\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "ah")
        self.assertEqual(a, self.fp())
        (self.repo / ".claude/agents/s.md").write_text("changed\n")
        git(self.repo, "commit", "-qam", "skill")
        self.assertNotEqual(a, self.fp())

    def test_fingerprint_filters_non_ascii_session_names(self):
        a = self.fp()
        (self.repo / ".memsearch/günlük.md").write_text("x\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tr")
        self.assertEqual(a, self.fp())

    def test_fingerprint_changes_on_game_file(self):
        a = self.fp()
        (self.repo / "Assets/a.cs").write_text("class B {}\n")
        git(self.repo, "commit", "-qam", "code")
        self.assertNotEqual(a, self.fp())

    def test_fingerprint_equal_across_branches_with_same_content(self):
        self.assertEqual(self.fp("dev"), self.fp("release"))


if __name__ == "__main__":
    unittest.main()
