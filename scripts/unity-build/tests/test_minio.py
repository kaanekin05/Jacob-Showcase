import hashlib
import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from ub import minio
from ub.config import load_game
from ub.runner import Result
from ub.unitybuild import StepFailed

ALLOWED = {"lsjson", "copyto", "check"}
BUNDLE = "defaultlocalgroup_assets_all_0123abcd.bundle"
CATALOG = "catalog_0.0.64.bin"
HASH = "catalog_0.0.64.hash"


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class SimRemote:
    """A fake rclone over an in-memory bucket folder. Files are {rel: (bytes, list_md5)}."""

    def __init__(self, missing_prefix_exit3=False):
        self.files = {}
        self.calls = []
        self.missing_prefix_exit3 = missing_prefix_exit3
        self.corrupt = set()      # rel names stored with different bytes on copy
        self.no_md5 = set()       # rel names listed without an md5
        self.fail = {}            # cmd[1] -> Result to return once
        self.lsjson_count = 0

    def put(self, rel, data, list_md5=True):
        self.files[rel] = data
        if not list_md5:
            self.no_md5.add(rel)

    def run(self, cmd, cwd=None, env=None, input=None):
        self.calls.append(list(cmd))
        if cmd[1] in self.fail:
            return self.fail.pop(cmd[1])
        if cmd[1] == "lsjson":
            self.lsjson_count += 1
            if not self.files and self.missing_prefix_exit3:
                return Result(3, "", "ERROR : : error listing: directory not found\n")
            out = []
            for rel, data in self.files.items():
                e = {"Path": rel, "Name": rel.rsplit("/", 1)[-1], "IsDir": False, "Size": len(data)}
                if rel not in self.no_md5:
                    e["Hashes"] = {"md5": md5(data)}
                out.append(e)
            return Result(0, json.dumps(out))
        if cmd[1] == "copyto":
            rel = cmd[3].split("/v0.0.64/", 1)[1]
            data = Path(cmd[2]).read_bytes()
            self.files[rel] = data + b"!" if rel in self.corrupt else data
            return Result(0)
        if cmd[1] == "check":
            rel = cmd[cmd.index("--include") + 1].lstrip("/")
            local = Path(cmd[2]) / rel
            same = rel in self.files and self.files[rel] == local.read_bytes()
            return Result(0) if same else Result(1, "", "1 differences found\n")
        raise AssertionError(cmd)

    def copies(self):
        return [c[3].rsplit("/", 1)[1] for c in self.calls if c[1] == "copyto"]


class MinioTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.game = replace(load_game("beryl"), project_path=Path(tmp.name))
        self.data = {BUNDLE: b"bundle bytes", HASH: b"hash", CATALOG: b"catalog bytes"}
        self.dir = self.make_dir("development")
        self.sims = []

    def tearDown(self):
        for s in self.sims:
            for c in s.calls:
                self.assertEqual(c[0], "rclone")
                self.assertIn(c[1], ALLOWED, c)

    def make_dir(self, profile):
        d = minio.local_dir(self.game, profile, "Android", "0.0.64")
        d.mkdir(parents=True, exist_ok=True)
        for n, data in self.data.items():
            (d / n).write_bytes(data)
        return d

    def sim(self, **kw):
        s = SimRemote(**kw)
        self.sims.append(s)
        return s

    def files(self, profile="development", since=0.0):
        return minio.ota_outputs(self.game, profile, "Android", "0.0.64", since)

    def upload(self, s, may_replace=True, profile="development", hook=None):
        if profile != "development":
            self.make_dir(profile)
        return minio.upload(self.game, profile, "Android", "0.0.64", self.files(profile), s, may_replace, hook)

    # ---- local outputs ----

    def test_local_dir_and_remote_url(self):
        self.assertEqual(self.dir, self.game.project_path / "Builds/ServerData/development/Android/v0.0.64")
        self.assertEqual(minio.remote_url(self.game, "production", "iOS", "0.0.64"),
                         "https://ota.example.com/beryl/production/iOS/v0.0.64/")

    def test_missing_folder_stops(self):
        with self.assertRaises(StepFailed) as cm:
            self.files("production")
        self.assertIn("ServerData", str(cm.exception))

    def test_folder_without_catalog_stops(self):
        (self.dir / CATALOG).unlink()
        with self.assertRaises(StepFailed):
            self.files()

    def test_folder_without_bundle_stops(self):
        (self.dir / BUNDLE).unlink()
        with self.assertRaises(StepFailed):
            self.files()

    def test_stale_catalog_only_stops(self):
        old = time.time() - 3600
        os.utime(self.dir / CATALOG, (old, old))
        with self.assertRaises(StepFailed) as cm:
            self.files(since=time.time() - 60)
        self.assertIn("no catalog newer", str(cm.exception))

    def test_stale_catalog_from_earlier_build_is_left_out(self):
        old = time.time() - 3600
        (self.dir / "catalog_2026.11.01.bin").write_bytes(b"old catalog")
        (self.dir / "catalog_2026.11.01.hash").write_bytes(b"old hash")
        for n in ("catalog_2026.11.01.bin", "catalog_2026.11.01.hash"):
            os.utime(self.dir / n, (old, old))
        names = [p.name for p in self.files(since=time.time() - 60)]
        self.assertEqual(names, [BUNDLE, HASH, CATALOG])

    def test_dotfiles_are_ignored(self):
        (self.dir / ".DS_Store").write_bytes(b"x")
        self.assertNotIn(".DS_Store", [p.name for p in self.files()])

    # ---- upload ----

    def test_order_is_bundles_then_hash_then_catalog(self):
        s = self.sim()
        self.assertEqual(self.upload(s), 3)
        self.assertEqual(s.copies(), [BUNDLE, HASH, CATALOG])
        first = [c for c in s.calls if c[1] == "copyto"][0][3]
        self.assertTrue(first.startswith("studio-minio:beryl/development/Android/v0.0.64/"))

    def test_missing_prefix_exit3_counts_as_empty(self):
        s = self.sim(missing_prefix_exit3=True)
        self.assertEqual(self.upload(s), 3)

    def test_other_listing_failure_stops(self):
        s = self.sim()
        s.fail["lsjson"] = Result(1, "", "connection refused\n")
        with self.assertRaises(StepFailed) as cm:
            self.upload(s)
        self.assertIn("connection refused", str(cm.exception))

    def test_same_bundle_is_skipped(self):
        s = self.sim()
        s.put(BUNDLE, self.data[BUNDLE])
        self.assertEqual(self.upload(s), 2)
        self.assertNotIn(BUNDLE, s.copies())

    def test_bundle_clash_stops_before_any_copy(self):
        s = self.sim()
        s.put(BUNDLE, b"other bytes!")
        with self.assertRaises(minio.MinioNameClash) as cm:
            self.upload(s)
        self.assertIn(BUNDLE, str(cm.exception))
        self.assertEqual(s.copies(), [])

    def test_no_md5_same_size_different_bundle_is_a_clash(self):
        s = self.sim()
        s.put(BUNDLE, b"bundle bytez", list_md5=False)  # same length, different bytes, no md5 listed
        with self.assertRaises(minio.MinioNameClash):
            self.upload(s)
        self.assertEqual(s.copies(), [])

    def test_no_md5_identical_bundle_is_skipped(self):
        s = self.sim()
        s.put(BUNDLE, self.data[BUNDLE], list_md5=False)
        self.assertEqual(self.upload(s), 2)

    def test_development_catalog_is_replaced(self):
        s = self.sim()
        s.put(CATALOG, b"older")
        s.put(HASH, b"old")
        self.assertEqual(self.upload(s), 3)
        self.assertEqual(s.files[CATALOG], self.data[CATALOG])

    def test_frozen_catalog_stops_before_any_copy(self):
        s = self.sim()
        s.put(CATALOG, b"live catalog")
        with self.assertRaises(minio.ProductionFrozen):
            self.upload(s, may_replace=False, profile="production")
        self.assertEqual(s.copies(), [])

    def test_frozen_no_md5_equal_size_catalog_stops(self):
        s = self.sim()
        s.put(CATALOG, b"catalog bytez", list_md5=False)
        with self.assertRaises(minio.ProductionFrozen):
            self.upload(s, may_replace=False, profile="production")
        self.assertEqual(s.copies(), [])

    def test_frozen_folder_with_other_catalog_name_stops(self):
        s = self.sim()
        s.put("catalog_2026.10.26.bin", b"live")
        with self.assertRaises(minio.ProductionFrozen):
            self.upload(s, may_replace=False, profile="production")
        self.assertEqual(s.copies(), [])

    def test_hook_runs_after_checks_before_first_copy(self):
        seen = []
        s = self.sim()
        self.upload(s, hook=lambda: seen.append(len(s.copies())))
        self.assertEqual(seen, [0])
        s2 = self.sim()
        s2.put(BUNDLE, b"other bytes!")
        with self.assertRaises(minio.MinioNameClash):
            self.upload(s2, hook=lambda: seen.append("ran"))
        self.assertEqual(seen, [0])

    def test_bad_bundle_stops_before_hash_and_catalog(self):
        s = self.sim()
        s.corrupt.add(BUNDLE)
        with self.assertRaises(StepFailed) as cm:
            self.upload(s)
        self.assertIn(BUNDLE, str(cm.exception))
        self.assertEqual(s.copies(), [BUNDLE])

    def test_bad_hash_stops_before_catalog(self):
        s = self.sim()
        s.corrupt.add(HASH)
        with self.assertRaises(StepFailed):
            self.upload(s)
        self.assertEqual(s.copies(), [BUNDLE, HASH])

    def test_missing_md5_after_upload_falls_back_to_check_download(self):
        s = self.sim()
        s.no_md5.add(BUNDLE)
        self.upload(s)
        checks = [c for c in s.calls if c[1] == "check"]
        self.assertEqual(len(checks), 1)
        self.assertIn("--download", checks[0])
        self.assertIn("/" + BUNDLE, checks[0])

    def test_missing_md5_mismatch_after_upload_stops(self):
        s = self.sim()
        s.no_md5.add(BUNDLE)
        s.corrupt.add(BUNDLE)
        with self.assertRaises(StepFailed) as cm:
            self.upload(s)
        self.assertIn(BUNDLE, str(cm.exception))
        self.assertEqual(s.copies(), [BUNDLE])

    def test_copy_failure_stops(self):
        s = self.sim()
        s.fail["copyto"] = Result(1, "", "connection reset\n")
        with self.assertRaises(StepFailed) as cm:
            self.upload(s)
        self.assertIn("connection reset", str(cm.exception))

    def test_sign_in_error_gives_remote_recreate_steps(self):
        s = self.sim()
        s.fail["lsjson"] = Result(1, "", "Failed to lsjson: SignatureDoesNotMatch: access_key_id=AKIAXYZ\n")
        with self.assertRaises(StepFailed) as cm:
            self.upload(s)
        msg = str(cm.exception)
        self.assertIn("`rclone config`", msg)
        self.assertIn("studio-minio", msg)
        self.assertIn("own Terminal", msg)
        self.assertIn("Paste nothing back", msg)
        # The S3 API sits behind Cloudflare, which rewrites Accept-Encoding and breaks the signature.
        self.assertIn("https://ota.example.com", msg)
        self.assertIn("sign_accept_encoding", msg)
        self.assertNotIn("AKIAXYZ", msg)
        # The secret must never sit on a command line: chat and shell history would both keep it.
        self.assertNotIn("secret_access_key=", msg)
        self.assertNotIn("`! rclone", msg)

    def test_unreadable_listing_stops(self):
        s = self.sim()
        s.fail["lsjson"] = Result(0, "not json")
        with self.assertRaises(StepFailed):
            self.upload(s)


if __name__ == "__main__":
    unittest.main()
