import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from ub.config import load_game
from ub.guards import snapshot, violations
from ub.mergeflow import MergeError, _parse, conclude_merge, merge_dev
from ub.runner import Runner
from ub.versions import Numbers, apply_numbers, read_numbers

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ProjectSettings.asset"
PS = "ProjectSettings/ProjectSettings.asset"
CODE = "Assets/a.cs"
SESSION = ".claude/autoharness/requests"
BIN = "Assets/AddressableAssetsData/addressables_content_state.bin"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        genv = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
        genv.start()
        self.addCleanup(genv.stop)
        r = self.repo = Path(tmp.name)
        git(r, "init", "-q", "-b", "dev")
        git(r, "config", "user.email", "t@t")
        git(r, "config", "user.name", "t")
        git(r, "config", "core.autocrlf", "false")
        self.write(PS, FIXTURE.read_text())
        self.write(CODE, "class A {\n    int x = 1;\n}\n")
        self.write(SESSION, "req-base\n")
        self.write(".memsearch/notes.md", "n\n")
        (r / BIN).parent.mkdir(parents=True)
        (r / BIN).write_bytes(b"\x00\x01base\x00")
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "init")
        git(r, "branch", "release")
        self.game = replace(load_game("amber"), project_path=r)
        self.runner = Runner()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def read(self, rel):
        return (self.repo / rel).read_text()

    def numbers(self, version, android, ios):
        self.write(PS, apply_numbers(self.read(PS), Numbers(version, android, ios)))

    def commit(self, branch, msg="c"):
        git(self.repo, "switch", "-q", branch)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", msg)

    def on(self, branch, edit):
        git(self.repo, "switch", "-q", branch)
        edit()
        self.commit(branch)

    def merge(self):
        git(self.repo, "switch", "-q", "release")
        self.dev_tip = git(self.repo, "rev-parse", "dev")
        self.release_tip = git(self.repo, "rev-parse", "release")
        result = merge_dev(self.game, self.runner)
        self.assertEqual(git(self.repo, "rev-parse", "dev"), self.dev_tip, "dev must never move")
        self.assertEqual(git(self.repo, "symbolic-ref", "--short", "HEAD"), "release")
        return result

    def merge_head(self):
        return (self.repo / ".git" / "MERGE_HEAD").exists()

    def assert_staged_not_committed(self):
        """merge_dev never commits: MERGE_HEAD is kept and HEAD is still release's tip."""
        self.assertTrue(self.merge_head())
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.release_tip)
        self.assertEqual(git(self.repo, "diff", "--name-only", "--diff-filter=U"), "")

    def assert_committed(self):
        self.assert_staged_not_committed()
        conclude_merge(self.game, self.runner)
        self.assertFalse(self.merge_head())
        parents = git(self.repo, "log", "-1", "--format=%P").split()
        self.assertEqual(len(parents), 2)
        self.assertEqual(parents[1], self.dev_tip)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")


class MergeFlow(Base):
    def test_clean_merge(self):
        self.on("dev", lambda: self.write(CODE, "class A {\n    int x = 2;\n}\n"))
        self.on("release", lambda: self.write("Assets/b.cs", "class B {}\n"))
        result = self.merge()
        self.assertEqual(result.status, "clean")
        self.assertEqual(result.pending, [])
        self.assert_committed()
        self.assertIn("x = 2", self.read(CODE))

    def test_already_up_to_date(self):
        result = self.merge()
        self.assertEqual(result.status, "up_to_date")
        self.assertFalse(self.merge_head())
        conclude_merge(self.game, self.runner)  # a no-op
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.release_tip)

    def test_version_hunk_takes_dev(self):
        self.on("dev", lambda: self.numbers("0.1.9", 19, 19))
        self.on("release", lambda: self.numbers("0.1.8", 18, 18))
        result = self.merge()
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.pending, [])
        self.assert_committed()
        self.assertEqual(read_numbers(self.read(PS)), Numbers("0.1.9", 19, 19))
        self.assertNotIn("<<<<<<<", self.read(PS))

    def test_version_compare_is_numeric(self):
        self.on("dev", lambda: self.numbers("0.1.10", 19, 19))
        self.on("release", lambda: self.numbers("0.1.9", 18, 18))
        self.assertEqual(self.merge().status, "resolved")
        self.assertEqual(read_numbers(self.read(PS)).version, "0.1.10")

    def test_refuses_version_hunk_when_dev_lower(self):
        self.on("dev", lambda: self.numbers("0.1.8", 19, 19))
        self.on("release", lambda: self.numbers("0.1.9", 18, 18))
        result = self.merge()
        self.assertEqual(result.status, "needs_decision")
        self.assertEqual([c.path for c in result.pending], [PS])
        self.assertIn("0.1.9", result.pending[0].ours)
        self.assertIn("0.1.8", result.pending[0].theirs)
        self.assertTrue(self.merge_head())
        self.assertIn("bundleVersion: 0.1.9", self.read(PS))  # release's line is still there

    def test_refuses_when_one_build_number_is_lower(self):
        self.on("dev", lambda: self.numbers("0.1.9", 19, 16))  # base is 17, so both sides change it
        self.on("release", lambda: self.numbers("0.1.8", 18, 18))
        result = self.merge()
        self.assertEqual(result.status, "needs_decision")
        self.assertIn("iPhone: 18", result.pending[0].ours)

    def test_mixed_hunk_goes_to_pending(self):
        def dev():
            self.numbers("0.1.9", 18, 18)
            self.write(PS, self.read(PS).replace("AndroidMinSdkVersion: 25", "AndroidMinSdkVersion: 26"))

        def rel():
            self.numbers("0.1.8", 17, 17)
            self.write(PS, self.read(PS).replace("AndroidMinSdkVersion: 25", "AndroidMinSdkVersion: 24"))
        self.on("dev", dev)
        self.on("release", rel)
        result = self.merge()
        self.assertEqual(result.status, "needs_decision")
        self.assertEqual([c.path for c in result.pending], [PS])
        text = self.read(PS)
        # The version-only hunk is already resolved to dev's number.
        self.assertIn("  bundleVersion: 0.1.9\n", text)
        self.assertNotIn("bundleVersion: 0.1.8", text)
        self.assertEqual(text.count("<<<<<<<"), 1)
        self.assertIn("AndroidMinSdkVersion: 24", result.pending[0].ours)
        self.assertIn("AndroidMinSdkVersion: 26", result.pending[0].theirs)
        self.assertNotIn("bundleVersion", result.pending[0].ours)
        self.assertTrue(self.merge_head())

    def test_numeric_iphone_line_outside_build_number_is_not_a_version_line(self):
        def edit(v):
            return lambda: self.write(PS, self.read(PS).replace(
                "  ForceInternetPermission: 0\n", f"  ForceInternetPermission: 0\n  scriptingBackend:\n    iPhone: {v}\n"))
        self.on("dev", edit(2))
        self.on("release", edit(1))
        self.assertEqual(self.merge().status, "needs_decision")

    def test_session_path_keeps_release_copy(self):
        self.on("dev", lambda: self.write(SESSION, "req-dev\n"))
        self.on("release", lambda: self.write(SESSION, "req-release\n"))
        result = self.merge()
        self.assertEqual(result.status, "resolved")
        self.assert_committed()
        self.assertEqual(self.read(SESSION), "req-release\n")

    def test_session_path_deleted_on_release_stays_deleted(self):
        self.on("dev", lambda: self.write(SESSION, "req-dev\n"))
        self.on("release", lambda: (self.repo / SESSION).unlink())
        self.assertEqual(self.merge().status, "resolved")
        self.assert_committed()
        self.assertFalse((self.repo / SESSION).exists())

    def test_regenerated_binary_resolves(self):
        self.on("dev", lambda: (self.repo / BIN).write_bytes(b"\x00dev\x00"))
        self.on("release", lambda: (self.repo / BIN).write_bytes(b"\x00release\x00"))
        result = self.merge()
        self.assertEqual(result.status, "resolved")
        self.assert_committed()
        self.assertIn((self.repo / BIN).read_bytes(), (b"\x00dev\x00", b"\x00release\x00"))

    def test_game_code_conflict_needs_decision(self):
        self.on("dev", lambda: (self.write(CODE, "class A {\n    int x = 2;\n}\n"), self.write(SESSION, "d\n")))
        self.on("release", lambda: (self.write(CODE, "class A {\n    int x = 3;\n}\n"), self.write(SESSION, "r\n")))
        result = self.merge()
        self.assertEqual(result.status, "needs_decision")
        self.assertEqual([c.path for c in result.pending], [CODE])
        self.assertIn("x = 3", result.pending[0].ours)
        self.assertIn("x = 2", result.pending[0].theirs)
        text = self.read(CODE)
        self.assertIn("x = 2", text)
        self.assertIn("x = 3", text)
        self.assertTrue(self.merge_head())
        # The session conflict was still auto-resolved and staged.
        self.assertEqual(self.read(SESSION), "r\n")
        self.assertEqual(git(self.repo, "diff", "--name-only", "--diff-filter=U"), CODE)

    def test_conclude_refuses_with_unmerged_paths(self):
        self.on("dev", lambda: self.write(CODE, "dev\n"))
        self.on("release", lambda: self.write(CODE, "release\n"))
        self.assertEqual(self.merge().status, "needs_decision")
        with self.assertRaises(MergeError) as cm:
            conclude_merge(self.game, self.runner)
        self.assertIn(CODE, str(cm.exception))
        self.assertTrue(self.merge_head())
        # The user decides; the agent applies it and concludes.
        self.write(CODE, "dev\n")
        git(self.repo, "add", "--", CODE)
        self.assert_committed()

    def test_conclude_without_merge_in_progress_is_a_no_op(self):
        git(self.repo, "switch", "-q", "release")
        head = git(self.repo, "rev-parse", "HEAD")
        conclude_merge(self.game, self.runner)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)

    def driver(self, command):
        git(self.repo, "config", "merge.failer.driver", command)
        self.write(".gitattributes", "*.asset merge=failer\n")
        self.commit("dev")
        git(self.repo, "switch", "-q", "release")
        git(self.repo, "merge", "-q", "dev")  # fast-forward: both branches get .gitattributes

    def test_project_settings_without_markers_goes_to_pending(self):
        # A merge driver that fails without writing markers, like a YAML merge tool that gives up.
        self.driver("false")
        self.on("dev", lambda: (self.numbers("0.1.5", 5, 5), self.write(PS, self.read(PS).replace(
            "AndroidMinSdkVersion: 25", "AndroidMinSdkVersion: 30"))))
        self.on("release", lambda: self.numbers("0.1.9", 19, 19))
        before = self.read(PS)
        result = self.merge()
        self.assertEqual(result.status, "needs_decision")
        self.assertEqual([c.path for c in result.pending], [PS])
        self.assertIn("AndroidMinSdkVersion: 30", result.pending[0].theirs)
        self.assertIn("bundleVersion: 0.1.9", result.pending[0].ours)
        self.assertEqual(self.read(PS), before)  # untouched
        self.assertIn(PS, git(self.repo, "diff", "--name-only", "--diff-filter=U"))
        self.assertTrue(self.merge_head())
        with self.assertRaises(MergeError):
            conclude_merge(self.game, self.runner)

    def test_project_settings_with_unterminated_hunk_goes_to_pending(self):
        self.driver("printf '<<<<<<< a\\n  bundleVersion: 0.1.8\\n=======\\n  bundleVersion: 0.1.9\\n' > %A; exit 1")
        self.on("dev", lambda: self.numbers("0.1.9", 19, 19))
        self.on("release", lambda: self.numbers("0.1.8", 18, 18))
        result = self.merge()
        self.assertEqual(result.status, "needs_decision")
        self.assertEqual([c.path for c in result.pending], [PS])
        self.assertIn(PS, git(self.repo, "diff", "--name-only", "--diff-filter=U"))

    def test_parse_rejects_malformed_markers(self):
        self.assertIsNone(_parse(["<<<<<<< a\n", "x\n", "=======\n", "y\n"]))
        self.assertIsNone(_parse(["<<<<<<< a\n", "x\n", ">>>>>>> b\n"]))
        self.assertIsNone(_parse(["x\n", ">>>>>>> b\n"]))
        self.assertEqual(len(_parse(["<<<<<<< a\n", "x\n", "=======\n", "y\n", ">>>>>>> b\n"])), 1)

    def test_guards_run_before_the_merge_commit(self):
        manifest = "Assets/Plugins/Android/AndroidManifest.xml"
        self.write(manifest, '<manifest>\n  <application android:label="x">\n  </application>\n</manifest>\n')
        # The other guarded files, in a passing state; a missing one is a violation by design.
        self.write("Assets/AddressableAssetsData/AddressableAssetSettings.asset", "  m_ActiveProfileId: 067be015d747d4b95b1c258e6206febd\n")
        self.write("Assets/StompyRobot/SRDebugger/usr/Resources/SRDebugger/Settings.asset", "  _isEnabled: 0\n")
        self.write(PS, self.read(PS) + "  scriptingDefineSymbols:\n    Android: DOTWEEN\n    iPhone: DOTWEEN\n")
        self.commit("dev")
        git(self.repo, "branch", "-f", "release", "dev")
        self.on("dev", lambda: self.write(manifest, self.read(manifest).replace(
            'android:label="x"', 'android:label="x" android:debuggable="true"')))
        self.on("release", lambda: self.write("Assets/b.cs", "b\n"))
        git(self.repo, "switch", "-q", "release")
        before = snapshot(self.game, self.runner)
        result = self.merge()
        self.assertEqual(result.status, "clean")
        out = violations(self.game, before, self.runner)
        self.assertEqual(len(out), 1)
        self.assertIn("android:debuggable", out[0])
        self.assertIn(manifest, out[0])
        self.assertTrue(self.merge_head())
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.release_tip)  # no merge commit

    def test_no_merge_back(self):
        # merge() asserts dev never moves; here also refuse to run with dev checked out.
        self.on("dev", lambda: self.write(CODE, "dev\n"))
        self.on("release", lambda: self.write("Assets/b.cs", "b\n"))
        dev_tip = git(self.repo, "rev-parse", "dev")
        git(self.repo, "switch", "-q", "dev")
        with self.assertRaises(MergeError):
            merge_dev(self.game, self.runner)
        self.assertEqual(git(self.repo, "rev-parse", "dev"), dev_tip)
        self.assertFalse(self.merge_head())
        self.merge()
        self.assertEqual(git(self.repo, "rev-parse", "dev"), dev_tip)
        self.assertNotIn("b.cs", git(self.repo, "ls-tree", "-r", "--name-only", "dev"))

    def test_refuses_when_merge_already_in_progress(self):
        self.on("dev", lambda: self.write(CODE, "dev\n"))
        self.on("release", lambda: self.write(CODE, "release\n"))
        self.merge()
        with self.assertRaises(MergeError):
            merge_dev(self.game, self.runner)
        self.assertTrue(self.merge_head())


if __name__ == "__main__":
    unittest.main()
