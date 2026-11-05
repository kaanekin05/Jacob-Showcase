import difflib
import tempfile
import unittest
from pathlib import Path

from ub.record import Record, RunState
from ub.versions import Numbers, apply_numbers, needs_bump, next_numbers, read_numbers

FIXTURE = (Path(__file__).parent / "fixtures" / "ProjectSettings.asset").read_text(encoding="utf-8")


class VersionRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rec = Record.load("amber", state_dir=Path(self.tmp.name))

    def test_next_uses_higher_branch(self):
        dev = Numbers("0.1.7", 17, 17)
        rel = Numbers("0.1.8", 17, 18)
        self.assertEqual(next_numbers(dev, rel), Numbers("0.1.9", 18, 19))

    def test_ios_build_zero_never_increments(self):
        self.assertEqual(next_numbers(Numbers("1.1.0", 30, 0), Numbers("1.1.0", 30, 0)), Numbers("1.1.1", 31, 0))

    def test_ios_build_moves_when_either_branch_is_nonzero(self):
        self.assertEqual(next_numbers(Numbers("1.1.0", 30, 0), Numbers("1.1.0", 30, 4)).ios_build, 5)

    def test_compares_numerically(self):
        dev = Numbers("0.1.10", 5, 5)
        rel = Numbers("0.1.9", 4, 4)
        self.assertEqual(next_numbers(dev, rel).version, "0.1.11")
        self.assertFalse(needs_bump(dev, rel, self.rec))

    def test_retest_keeps_version_when_dev_ahead(self):
        self.rec.released.append("0.1.7")
        self.assertFalse(needs_bump(Numbers("0.1.8", 18, 18), Numbers("0.1.7", 17, 17), self.rec))

    def test_failed_release_after_merge_keeps_version(self):
        n = Numbers("0.1.8", 18, 19)
        self.assertFalse(needs_bump(n, n, self.rec))

    def test_released_version_bumps(self):
        n = Numbers("0.1.8", 18, 19)
        self.rec.released.append("0.1.8")
        self.assertTrue(needs_bump(n, n, self.rec))

    def test_release_ahead_of_dev_bumps(self):
        # Today's Amber: release got 0.1.8 directly, dev never held it.
        self.assertTrue(needs_bump(Numbers("0.1.7", 17, 17), Numbers("0.1.8", 17, 18), self.rec))

    def test_read_numbers(self):
        self.assertEqual(read_numbers(FIXTURE), Numbers("0.1.7", 17, 17))

    def test_read_numbers_missing_field(self):
        with self.assertRaises(ValueError):
            read_numbers("bundleVersion: 1.0.0\n")

    def test_apply_changes_three_lines_only(self):
        out = apply_numbers(FIXTURE, Numbers("0.1.9", 18, 19))
        diff = [l for l in difflib.unified_diff(FIXTURE.splitlines(), out.splitlines(), lineterm="", n=0)
                if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        self.assertEqual(len(diff), 6)  # three removed, three added
        self.assertEqual(read_numbers(out), Numbers("0.1.9", 18, 19))
        # the iPhone applicationIdentifier line must not be touched
        self.assertIn("    iPhone: com.example.amber\n", out)

    def test_apply_keeps_crlf(self):
        crlf = FIXTURE.replace("\n", "\r\n")
        out = apply_numbers(crlf, Numbers("0.1.9", 18, 19))
        self.assertEqual(out.count("\r\n"), crlf.count("\r\n"))
        self.assertNotIn("\n", out.replace("\r\n", ""))


class RecordFile(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            r = Record.load("amber", state_dir=Path(d))
            self.assertEqual((r.released, r.tested, r.uploaded_ios_builds, r.run), ([], {}, [], None))
            r.released.append("0.1.8")
            r.tested["0.1.9"] = "abc"
            r.uploaded_ios_builds.append(18)
            r.run = RunState(stage="release", platform="ios", branch="release", version="0.1.9", step="merge")
            r.save()
            r2 = Record.load("amber", state_dir=Path(d))
            self.assertEqual(r2.released, ["0.1.8"])
            self.assertEqual(r2.tested, {"0.1.9": "abc"})
            self.assertEqual(r2.uploaded_ios_builds, [18])
            self.assertEqual(r2.run, r.run)

    def test_env_var_overrides_location(self):
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"UB_STATE_DIR": d}):
            Record.load("amber").save()
            self.assertTrue((Path(d) / "amber.json").exists())


if __name__ == "__main__":
    unittest.main()
