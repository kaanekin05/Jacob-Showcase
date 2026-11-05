import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ub import drive
from ub.config import load_game
from ub.runner import FakeRunner, Result
from ub.unitybuild import StepFailed

NOTICE = "NOTICE: Google drive root '': Using shared client_id\n"
FORBIDDEN = {"link", "delete", "deletefile", "purge", "rmdir", "move", "moveto", "sync",
             "backend", "cleanup", "dedupe", "rmdirs", "touch", "settier", "genautocomplete"}


def ls(*entries):
    return Result(0, json.dumps([
        {"Name": n, "ID": i, "IsDir": d, "Size": s, "ModTime": "2026-11-02T10:00:00Z"}
        for n, i, d, s in entries]), NOTICE)


def ls_hash(*entries):
    return Result(0, json.dumps([
        {"Name": n, "ID": i, "IsDir": d, "Size": s, "Hashes": {"md5": h}}
        for n, i, d, s, h in entries]), NOTICE)


class DriveTest(unittest.TestCase):
    def setUp(self):
        self.game = load_game("amber")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runners = []

    def tearDown(self):
        for r in self.runners:
            self.assert_calls_safe(r)

    def assert_calls_safe(self, r):
        for c in r.calls:
            self.assertEqual(c.cmd[0], "rclone")
            self.assertNotIn(c.cmd[1], FORBIDDEN)
            self.assertIn(c.cmd[1], {"lsjson", "mkdir", "copyto"})
            i = c.cmd.index("--drive-root-folder-id")
            self.assertEqual(c.cmd[i + 1], self.game.drive_folder_id)

    def runner(self, results):
        r = FakeRunner(results)
        self.runners.append(r)
        return r

    def file(self, name, size):
        p = Path(self.tmp.name) / name
        p.write_bytes(b"x" * size)
        return p

    def subcmds(self, r):
        return [c.cmd[1] for c in r.calls]

    def test_url_shapes(self):
        self.assertEqual(drive.folder_url("abc"), "https://drive.google.com/drive/folders/abc?usp=drive_link")
        self.assertEqual(drive.file_url("xyz"), "https://drive.google.com/file/d/xyz/view?usp=drive_link")

    def test_reuses_existing_folder(self):
        r = self.runner([ls(("v0.1.9", "F1", True, -1), ("AlphaTests", "A", True, -1))])
        self.assertEqual(drive.ensure_version_folder(self.game, "0.1.9", r), "F1")
        self.assertEqual(self.subcmds(r), ["lsjson"])
        cmd = r.calls[0].cmd
        self.assertIn("studio-drive:", cmd)
        self.assertEqual(cmd[cmd.index("--drive-root-folder-id") + 1], self.game.drive_folder_id)

    def test_creates_missing_folder_and_reads_id(self):
        r = self.runner([ls(("AlphaTests", "A", True, -1)), Result(0, "", NOTICE),
                         ls(("AlphaTests", "A", True, -1), ("v0.1.9", "F2", True, -1))])
        self.assertEqual(drive.ensure_version_folder(self.game, "0.1.9", r), "F2")
        self.assertEqual(self.subcmds(r), ["lsjson", "mkdir", "lsjson"])
        self.assertIn("studio-drive:v0.1.9", r.calls[1].cmd)

    def test_duplicate_folder_stops(self):
        r = self.runner([ls(("v0.1.9", "F1", True, -1), ("v0.1.9", "F2", True, -1))])
        with self.assertRaises(StepFailed) as cm:
            drive.ensure_version_folder(self.game, "0.1.9", r)
        self.assertIn("v0.1.9", str(cm.exception))
        self.assertEqual(self.subcmds(r), ["lsjson"])

    def test_upload_returns_urls(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls(), Result(0, "", NOTICE),
                         ls(("a.apk", "ID1", False, 5))])
        urls = drive.upload(self.game, "v0.1.9", [a], r)
        self.assertEqual(urls, {"a.apk": drive.file_url("ID1")})
        copy = [c.cmd for c in r.calls if c.cmd[1] == "copyto"][0]
        self.assertEqual(copy[2:4], [str(a), "studio-drive:v0.1.9/a.apk"])

    def test_rerun_uploads_no_duplicate(self):
        a, b = self.file("a.apk", 5), self.file("b.aab", 7)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)),
                         ls(("a.apk", "ID1", False, 5)), Result(0, "", NOTICE),
                         ls(("a.apk", "ID1", False, 5), ("b.aab", "ID2", False, 7))])
        urls = drive.upload(self.game, "v0.1.9", [a, b], r)
        copies = [c.cmd for c in r.calls if c.cmd[1] == "copyto"]
        self.assertEqual(len(copies), 1)
        self.assertIn("studio-drive:v0.1.9/b.aab", copies[0])
        self.assertEqual(set(urls), {"a.apk", "b.aab"})
        self.assertEqual(urls["a.apk"], drive.file_url("ID1"))

    def test_rerun_all_present_uploads_nothing(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls(("a.apk", "ID1", False, 5))])
        self.assertEqual(drive.upload(self.game, "v0.1.9", [a], r), {"a.apk": drive.file_url("ID1")})
        self.assertNotIn("copyto", self.subcmds(r))

    def test_same_name_different_size_stops(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls(("a.apk", "ID1", False, 99))])
        with self.assertRaises(StepFailed) as cm:
            drive.upload(self.game, "v0.1.9", [a], r)
        self.assertIn("a.apk", str(cm.exception))
        self.assertNotIn("copyto", self.subcmds(r))

    def test_duplicate_file_stops(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)),
                         ls(("a.apk", "I1", False, 5), ("a.apk", "I2", False, 5))])
        with self.assertRaises(StepFailed) as cm:
            drive.upload(self.game, "v0.1.9", [a], r)
        self.assertIn("a.apk", str(cm.exception))
        self.assertNotIn("copyto", self.subcmds(r))

    def test_expired_token_stderr_never_suggests_reconnect(self):
        err = ("Failed to create file system: couldn't login: token expired. "
               "Run `rclone config reconnect studio-drive:` to fix.\n")
        for fn in (lambda r: drive.ensure_version_folder(self.game, "0.1.9", r),
                   lambda r: drive.upload(self.game, "v0.1.9", [self.file("a.apk", 3)], r)):
            r = self.runner([Result(1, "", err)])
            with self.assertRaises(StepFailed) as cm:
                fn(r)
            msg = str(cm.exception)
            self.assertNotIn("reconnect", msg)
            self.assertIn("config delete studio-drive", msg)
            self.assertIn("> /dev/null", msg)
            self.assertIn("Paste nothing back", msg)

    def test_plain_failure_stderr_is_quoted_without_sign_in_steps(self):
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls(), Result(1, "", "boom quota")])
        with self.assertRaises(StepFailed) as cm:
            drive.upload(self.game, "v0.1.9", [self.file("a.apk", 3)], r)
        self.assertIn("boom quota", str(cm.exception))
        self.assertNotIn("config delete", str(cm.exception))

    def test_upload_failure_raises_with_file_name(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls(), Result(1, "", "boom quota")])
        with self.assertRaises(StepFailed) as cm:
            drive.upload(self.game, "v0.1.9", [a], r)
        self.assertIn("a.apk", str(cm.exception))
        self.assertIn("boom quota", str(cm.exception))

    def test_notice_on_stderr_with_exit_zero_succeeds(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls(), Result(0, "", NOTICE),
                         ls(("a.apk", "ID1", False, 5))])
        self.assertEqual(drive.upload(self.game, "v0.1.9", [a], r), {"a.apk": drive.file_url("ID1")})

    def test_missing_folder_stops(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls()])
        with self.assertRaises(StepFailed):
            drive.upload(self.game, "v0.1.9", [a], r)

    def test_never_calls_rclone_link(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("AlphaTests", "A", True, -1)), Result(0, "", NOTICE),
                         ls(("v0.1.9", "F1", True, -1)),
                         ls(("v0.1.9", "F1", True, -1)), ls(), Result(0, "", NOTICE),
                         ls(("a.apk", "ID1", False, 5))])
        drive.ensure_version_folder(self.game, "0.1.9", r)
        drive.upload(self.game, "v0.1.9", [a], r)
        self.assertEqual(self.subcmds(r), ["lsjson", "mkdir", "lsjson", "lsjson", "lsjson", "copyto", "lsjson"])
        self.assert_calls_safe(r)

    def test_empty_folder_id_stops(self):
        game = replace(self.game, drive_folder_id="")
        r = self.runner([])
        with self.assertRaises(StepFailed):
            drive.ensure_version_folder(game, "0.1.9", r)
        self.assertEqual(r.calls, [])

    def test_duplicate_basenames_stop_before_upload(self):
        d = Path(self.tmp.name)
        (d / "x").mkdir()
        a, b = self.file("a.apk", 5), d / "x" / "a.apk"
        b.write_bytes(b"yy")
        r = self.runner([])
        with self.assertRaises(StepFailed) as cm:
            drive.upload(self.game, "v0.1.9", [a, b], r)
        self.assertIn("a.apk", str(cm.exception))
        self.assertEqual(r.calls, [])

    def test_missing_local_file_stops_before_any_call(self):
        a = self.file("a.apk", 5)
        gone = Path(self.tmp.name) / "gone.aab"
        r = self.runner([])
        with self.assertRaises(StepFailed) as cm:
            drive.upload(self.game, "v0.1.9", [a, gone], r)
        self.assertIn("gone.aab", str(cm.exception))
        self.assertEqual(r.calls, [])

    def test_lsjson_empty_stdout_stops(self):
        r = self.runner([Result(0, "", NOTICE)])
        with self.assertRaises(StepFailed):
            drive.ensure_version_folder(self.game, "0.1.9", r)

    def test_lsjson_non_list_stops(self):
        r = self.runner([Result(0, '{"Name": "v0.1.9"}', "")])
        with self.assertRaises(StepFailed):
            drive.ensure_version_folder(self.game, "0.1.9", r)

    def test_version_folder_listed_with_hash(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls(("a.apk", "ID1", False, 5))])
        drive.upload(self.game, "v0.1.9", [a], r)
        self.assertIn("--hash", r.calls[1].cmd)

    def test_same_size_different_md5_stops(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)),
                         ls_hash(("a.apk", "ID1", False, 5, "0" * 32))])
        with self.assertRaises(StepFailed) as cm:
            drive.upload(self.game, "v0.1.9", [a], r)
        self.assertIn("a.apk", str(cm.exception))
        self.assertIn("rename", str(cm.exception))
        self.assertNotIn("copyto", self.subcmds(r))

    def test_same_size_same_md5_skips(self):
        a = self.file("a.apk", 5)
        md5 = hashlib.md5(b"x" * 5).hexdigest()
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls_hash(("a.apk", "ID1", False, 5, md5))])
        self.assertEqual(drive.upload(self.game, "v0.1.9", [a], r), {"a.apk": drive.file_url("ID1")})
        self.assertNotIn("copyto", self.subcmds(r))

    def test_size_mismatch_message_names_action(self):
        a = self.file("a.apk", 5)
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls(("a.apk", "ID1", False, 99))])
        with self.assertRaises(StepFailed) as cm:
            drive.upload(self.game, "v0.1.9", [a], r)
        self.assertIn("Delete or rename", str(cm.exception))
        self.assertIsInstance(cm.exception, drive.DriveNameClash)

    def test_remote_file_reads_entry_without_writing(self):
        a = self.file("a.apk", 5)
        md5 = hashlib.md5(b"x" * 5).hexdigest()
        r = self.runner([ls(("v0.1.9", "F1", True, -1)), ls_hash(("a.apk", "ID1", False, 5, md5))])
        entry = drive.remote_file(self.game, "v0.1.9", "a.apk", r)
        self.assertEqual(entry["ID"], "ID1")
        self.assertTrue(drive.same_content(entry, a))
        self.assertFalse(drive.same_content({**entry, "Size": 6}, a))
        self.assertFalse(drive.same_content({**entry, "Hashes": {"md5": "0" * 32}}, a))
        self.assertEqual(self.subcmds(r), ["lsjson", "lsjson"])

    def test_remote_file_missing_folder_is_none(self):
        r = self.runner([ls(("v0.1.8", "F0", True, -1))])
        self.assertIsNone(drive.remote_file(self.game, "v0.1.9", "a.apk", r))
        self.assertEqual(len(r.calls), 1)


if __name__ == "__main__":
    unittest.main()
