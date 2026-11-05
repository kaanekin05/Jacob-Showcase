import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ub.config import load_game
from ub.guards import snapshot, snapshot_ref, violations
from ub.runner import FakeRunner

ADDR = "Assets/AddressableAssetsData/AddressableAssetSettings.asset"
SRD = "Assets/StompyRobot/SRDebugger/usr/Resources/SRDebugger/Settings.asset"
PS = "ProjectSettings/ProjectSettings.asset"
MANIFEST = "Assets/Plugins/Android/AndroidManifest.xml"

DEFINES = """PlayerSettings:
  bundleVersion: 0.1.7
  scriptingDefineSymbols:
    Android: DOTWEEN;ODIN_INSPECTOR
    Nintendo Switch: DOTWEEN;CF_DEV
    iPhone: DOTWEEN;ODIN_INSPECTOR
    tvOS: DOTWEEN
  additionalCompilerArguments: {}
"""

MANIFEST_RELEASE = ('<manifest>\n  <application android:theme="@style/UnityThemeSelector" '
                    'android:label="@string/app_name">\n  </application>\n</manifest>\n')


class Guards(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.write(ADDR, "MonoBehaviour:\n  m_ActiveProfileId: 067be015d747d4b95b1c258e6206febd\n  m_BuildRemoteCatalog: 0\n")
        self.write(SRD, "MonoBehaviour:\n  _isEnabled: 0\n  _autoLoad: 1\n")
        self.write(PS, DEFINES)
        self.write(MANIFEST, MANIFEST_RELEASE)
        self.game = replace(load_game("amber"), project_path=self.root)
        self.runner = FakeRunner()
        self.before = snapshot(self.game, self.runner)

    def write(self, rel, text, crlf=False):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.replace("\n", "\r\n" if crlf else "\n").encode())

    def edit(self, rel, old, new):
        p = self.root / rel
        text = p.read_bytes().decode()
        self.assertIn(old, text)
        p.write_bytes(text.replace(old, new).encode())

    def check(self):
        return violations(self.game, self.before, self.runner)

    def test_unchanged_passes(self):
        self.assertEqual(self.check(), [])

    def test_guard_active_profile_changed(self):
        self.edit(ADDR, "067be015d747d4b95b1c258e6206febd", "dev456")
        out = self.check()
        self.assertEqual(len(out), 1)
        for part in (ADDR, "m_ActiveProfileId", "067be015d747d4b95b1c258e6206febd", "dev456"):
            self.assertIn(part, out[0])

    def test_guard_srdebugger_on(self):
        self.edit(SRD, "_isEnabled: 0", "_isEnabled: 1")
        out = self.check()
        self.assertEqual(len(out), 1)
        for part in (SRD, "_isEnabled", "'0'", "'1'"):
            self.assertIn(part, out[0])

    def test_guard_srdebugger_on_before_merge_is_still_a_violation(self):
        self.edit(SRD, "_isEnabled: 0", "_isEnabled: 1")
        self.before = snapshot(self.game, self.runner)
        out = self.check()
        self.assertEqual(len(out), 1)
        self.assertIn("_isEnabled", out[0])

    def test_guard_forbidden_define(self):
        self.edit(PS, "iPhone: DOTWEEN;ODIN_INSPECTOR", "iPhone: DOTWEEN;CF_DEV;ODIN_INSPECTOR")
        out = self.check()
        self.assertEqual(len(out), 1)
        for part in (PS, "iPhone", "CF_DEV", "absent", "present"):
            self.assertIn(part, out[0])

    def test_guard_sr_enabled_on_android(self):
        self.edit(PS, "Android: DOTWEEN;ODIN_INSPECTOR", "Android: DOTWEEN;ODIN_INSPECTOR;SR_ENABLED")
        out = self.check()
        self.assertEqual(len(out), 1)
        self.assertIn("Android", out[0])
        self.assertIn("SR_ENABLED", out[0])

    def test_guard_new_harmless_define_passes(self):
        self.edit(PS, "iPhone: DOTWEEN;ODIN_INSPECTOR", "iPhone: DOTWEEN;ODIN_INSPECTOR;NEW_FEATURE")
        self.assertEqual(self.check(), [])

    def test_define_on_unguarded_platform_and_substring_pass(self):
        # CF_DEV on Switch is not checked; CF_DEVTOOLS is a different symbol
        self.edit(PS, "Android: DOTWEEN;ODIN_INSPECTOR", "Android: DOTWEEN;CF_DEVTOOLS")
        self.assertEqual(self.check(), [])

    def test_guard_forbidden_define_crlf(self):
        self.write(PS, DEFINES.replace("iPhone: DOTWEEN", "iPhone: CF_DEV;DOTWEEN"), crlf=True)
        out = self.check()
        self.assertEqual(len(out), 1)
        self.assertIn("CF_DEV", out[0])

    def test_guard_debuggable(self):
        self.edit(MANIFEST, 'android:label="@string/app_name"',
                  'android:label="@string/app_name" android:debuggable="true"')
        out = self.check()
        self.assertEqual(len(out), 1)
        for part in (MANIFEST, "android:debuggable", "'true'", "absent"):
            self.assertIn(part, out[0])

    def test_guard_debuggable_crlf(self):
        self.write(MANIFEST, MANIFEST_RELEASE.replace("<application", '<application android:debuggable="true"'),
                   crlf=True)
        self.assertIn("android:debuggable", "\n".join(self.check()))

    def test_crlf_only_rewrite_passes(self):
        for rel in (ADDR, SRD, PS, MANIFEST):
            p = self.root / rel
            p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.check(), [])

    def test_missing_guarded_file_is_reported(self):
        (self.root / ADDR).unlink()
        out = self.check()
        self.assertEqual(len(out), 1)
        for part in (ADDR, "missing", "m_ActiveProfileId", "067be015d747d4b95b1c258e6206febd"):
            self.assertIn(part, out[0])

    def test_missing_manifest_is_reported(self):
        (self.root / MANIFEST).unlink()
        out = self.check()
        self.assertEqual(len(out), 1)
        self.assertIn(MANIFEST, out[0])
        self.assertIn("android:debuggable", out[0])

    def test_missing_project_settings_is_reported(self):
        (self.root / PS).unlink()
        out = self.check()
        self.assertEqual(len(out), 1)
        self.assertIn(PS, out[0])
        self.assertIn("missing", out[0])

    def test_defines_block_not_found_is_reported(self):
        self.write(PS, "PlayerSettings:\n  bundleVersion: 0.1.7\n")
        out = self.check()
        self.assertEqual(len(out), 1)
        self.assertIn("scriptingDefineSymbols", out[0])
        self.assertIn("CF_DEV", out[0])

    def test_defines_block_unparseable_is_reported(self):
        self.write(PS, DEFINES.replace("    tvOS: DOTWEEN\n", "    garbage line without colon\n"))
        self.assertIn("scriptingDefineSymbols", "\n".join(self.check()))

    def test_empty_defines_block_passes(self):
        self.write(PS, "PlayerSettings:\n  scriptingDefineSymbols: {}\n")
        self.assertEqual(self.check(), [])

    def test_keep_value_absent_before_merge_is_reported(self):
        self.write(ADDR, "MonoBehaviour:\n  m_BuildRemoteCatalog: 0\n")
        self.before = snapshot(self.game, self.runner)
        out = self.check()
        self.assertEqual(len(out), 1)
        for part in (ADDR, "m_ActiveProfileId", "not found before the merge"):
            self.assertIn(part, out[0])

    def test_guard_debuggable_single_quotes(self):
        self.edit(MANIFEST, 'android:label="@string/app_name"',
                  "android:label=\"@string/app_name\" android:debuggable='true'")
        out = self.check()
        self.assertEqual(len(out), 1)
        self.assertIn("'true'", out[0])


class RefSnapshots(unittest.TestCase):
    """snapshot_ref reads committed or staged values; missing refs and files fail closed."""

    def setUp(self):
        import os
        import subprocess
        from unittest import mock
        from ub.runner import Runner
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
        env.start()
        self.addCleanup(env.stop)
        self.root = Path(tmp.name)
        self.git = lambda *a: subprocess.run(["git", *a], cwd=self.root, check=True, capture_output=True)
        self.git("init", "-q", "-b", "release")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        for rel, text in ((ADDR, "MonoBehaviour:\n  m_ActiveProfileId: 067be015d747d4b95b1c258e6206febd\n"),
                          (SRD, "MonoBehaviour:\n  _isEnabled: 0\n"), (PS, DEFINES), (MANIFEST, MANIFEST_RELEASE)):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.git("update-ref", "refs/remotes/origin/release", "HEAD")
        self.game = replace(load_game("amber"), project_path=self.root)
        self.runner = Runner()

    def test_baseline_ref_name(self):
        self.assertEqual(snapshot_ref.__module__, "ub.guards")
        from ub.guards import baseline_ref
        self.assertEqual(baseline_ref(self.game), "refs/remotes/origin/release")

    def test_index_change_is_caught_but_unstaged_fix_is_not_trusted(self):
        base = snapshot_ref(self.game, "refs/remotes/origin/release", self.runner)
        (self.root / ADDR).write_text("MonoBehaviour:\n  m_ActiveProfileId: devprofile\n")
        self.git("add", "--", ADDR)
        (self.root / ADDR).write_text("MonoBehaviour:\n  m_ActiveProfileId: 067be015d747d4b95b1c258e6206febd\n")  # unstaged fix
        out = violations(self.game, base, self.runner, after=snapshot_ref(self.game, "", self.runner))
        self.assertTrue(any("devprofile" in v for v in out), out)
        self.assertEqual(violations(self.game, base, self.runner), [])  # the working tree alone would pass

    def test_missing_ref_fails_closed(self):
        base = snapshot_ref(self.game, "refs/remotes/origin/nope", self.runner)
        out = violations(self.game, base, self.runner, after=snapshot_ref(self.game, "HEAD", self.runner))
        self.assertTrue(any("missing from the baseline" in v for v in out), out)

    def test_file_missing_at_ref_fails_closed(self):
        base = snapshot_ref(self.game, "refs/remotes/origin/release", self.runner)
        self.git("rm", "-q", "--", MANIFEST)
        self.git("commit", "-q", "-m", "rm")
        out = violations(self.game, base, self.runner, after=snapshot_ref(self.game, "HEAD", self.runner))
        self.assertTrue(any(MANIFEST in v and "missing" in v for v in out), out)


    def test_required_profile_fails_even_when_baseline_holds_dev_profile(self):
        dev = "MonoBehaviour:\n  m_ActiveProfileId: bd8e202c5c3834221a08f6ec1717286c\n"
        (self.root / ADDR).write_text(dev)
        self.git("commit", "-qam", "tainted")
        self.git("update-ref", "refs/remotes/origin/release", "HEAD")
        base = snapshot_ref(self.game, "refs/remotes/origin/release", self.runner)
        out = violations(self.game, base, self.runner, after=snapshot_ref(self.game, "HEAD", self.runner))
        self.assertTrue(any("067be015d747d4b95b1c258e6206febd" in v and "bd8e202c" in v for v in out), out)


if __name__ == "__main__":
    unittest.main()
