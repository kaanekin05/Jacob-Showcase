import contextlib
import io
import json
import plistlib
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from ub import ios
from ub.config import load_game
from ub.record import Record
from ub.runner import FakeRunner, Result
from ub.unitybuild import StepFailed


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.game = replace(load_game("amber"), project_path=self.root / "proj")
        self.ios_dir = self.game.project_path / "Builds" / "v0.1.7" / "iOS"
        self.ios_dir.mkdir(parents=True)
        self.rec = Record.load("amber", state_dir=self.root / "state")

    def make_archive(self, sdk="iphoneos26.5", apps=("Amber.app",)):
        a = self.root / "Amber.xcarchive"
        for app in apps:
            d = a / "Products" / "Applications" / app
            d.mkdir(parents=True, exist_ok=True)
            (d / "Info.plist").write_bytes(plistlib.dumps({"DTSDKName": sdk, "CFBundleVersion": "18"}))
        ds = a / "dSYMs" / "Amber.app.dSYM" / "Contents"
        ds.mkdir(parents=True)
        (ds / "Info.plist").write_text("x")
        return a


class Archive(Base):
    def test_uses_workspace_when_present(self):
        (self.ios_dir / "Unity-iPhone.xcworkspace").mkdir()
        (self.ios_dir / "Unity-iPhone.xcodeproj").mkdir()
        r = FakeRunner()
        out = ios.archive(self.game, "0.1.7", r)
        cmd = r.calls[0].cmd
        self.assertEqual(cmd[0:2], ["xcodebuild", "-workspace"])
        self.assertEqual(cmd[2], str(self.ios_dir / "Unity-iPhone.xcworkspace"))
        self.assertNotIn("-project", cmd)
        self.assertIn("generic/platform=iOS", cmd)
        self.assertEqual(cmd[cmd.index("-configuration") + 1], "Release")
        self.assertEqual(cmd[cmd.index("-scheme") + 1], "Unity-iPhone")
        self.assertIn("-allowProvisioningUpdates", cmd)
        self.assertEqual(cmd[cmd.index("-archivePath") + 1], str(out))
        self.assertEqual(out.suffix, ".xcarchive")

    def test_uses_project_otherwise(self):
        (self.ios_dir / "Unity-iPhone.xcodeproj").mkdir()
        r = FakeRunner()
        ios.archive(self.game, "0.1.7", r)
        cmd = r.calls[0].cmd
        self.assertEqual(cmd[1], "-project")
        self.assertEqual(cmd[2], str(self.ios_dir / "Unity-iPhone.xcodeproj"))

    def test_failure_names_log_and_first_error(self):
        (self.ios_dir / "Unity-iPhone.xcodeproj").mkdir()
        r = FakeRunner([Result(65, "noise\nfoo.m:1: error: boom\nerror: later\n", "")])
        with self.assertRaises(StepFailed) as cm:
            ios.archive(self.game, "0.1.7", r)
        msg = str(cm.exception)
        self.assertIn("error: boom", msg)
        self.assertNotIn("later", msg)
        log = next(self.ios_dir.glob("*.log"))
        self.assertIn(str(log), msg)
        self.assertIn("boom", log.read_text())

    def test_no_xcode_project_fails(self):
        with self.assertRaises(StepFailed):
            ios.archive(self.game, "0.1.7", FakeRunner())


class Sdk(Base):
    def test_sdk_26_passes(self):
        ios.check_sdk(self.game, self.make_archive("iphoneos26.5"))

    def test_sdk_27_stops_before_upload(self):
        a = self.make_archive("iphoneos27.0")
        r = FakeRunner()
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 18, self.rec, r)
        self.assertEqual(r.calls, [])
        self.assertIn("iphoneos27.0", str(cm.exception))
        self.assertIn("UIScene", str(cm.exception))
        self.assertEqual(self.rec.uploaded_ios_builds, [])

    def test_sdk_check_runs_before_build_number_check(self):
        a = self.make_archive("iphoneos27.0")
        self.rec.uploaded_ios_builds.append(18)
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 18, self.rec, FakeRunner())
        self.assertIn("iphoneos27.0", str(cm.exception))

    def test_no_app_fails_clearly(self):
        a = self.make_archive(apps=())
        (a / "Products" / "Applications").mkdir(parents=True)
        with self.assertRaises(StepFailed) as cm:
            ios.check_sdk(self.game, a)
        self.assertIn(".app", str(cm.exception))

    def test_two_apps_fail(self):
        a = self.make_archive(apps=("A.app", "B.app"))
        with self.assertRaises(StepFailed):
            ios.check_sdk(self.game, a)


class Upload(Base):
    def test_export_options_have_upload_destination(self):
        a = self.make_archive()
        r = FakeRunner()
        ios.upload_testflight(self.game, a, 18, self.rec, r)
        cmd = r.calls[0].cmd
        self.assertEqual(cmd[:2], ["xcodebuild", "-exportArchive"])
        self.assertEqual(cmd[cmd.index("-archivePath") + 1], str(a))
        self.assertIn("-allowProvisioningUpdates", cmd)
        opts = plistlib.loads(Path(cmd[cmd.index("-exportOptionsPlist") + 1]).read_bytes())
        self.assertEqual(opts["method"], "app-store-connect")
        self.assertEqual(opts["destination"], "upload")
        self.assertEqual(opts["teamID"], "ABCDEFGHIJ")
        self.assertEqual(opts["signingStyle"], "automatic")
        self.assertIs(opts["manageAppVersionAndBuildNumber"], False)
        self.assertIs(opts["uploadSymbols"], True)

    def test_used_build_number_stops(self):
        a = self.make_archive()
        self.rec.uploaded_ios_builds.append(18)
        r = FakeRunner()
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 18, self.rec, r)
        self.assertEqual(r.calls, [])
        self.assertIn("18", str(cm.exception))

    def test_upload_failure_keeps_archive_and_names_organizer(self):
        a = self.make_archive()
        r = FakeRunner([Result(70, "", "export failed")])
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 18, self.rec, r)
        self.assertTrue(a.is_dir())
        self.assertIn(str(a), str(cm.exception))
        self.assertIn("Organizer", str(cm.exception))
        self.assertEqual(self.rec.uploaded_ios_builds, [])

    def test_account_error_mentions_settings_accounts(self):
        a = self.make_archive()
        r = FakeRunner([Result(70, "", "error: Authentication failed, no account for team")])
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 18, self.rec, r)
        self.assertIn("Settings > Accounts", str(cm.exception))

    def test_archive_number_mismatch_makes_no_call(self):
        a = self.make_archive()
        r = FakeRunner()
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 19, self.rec, r)
        self.assertEqual(r.calls, [])
        self.assertIn("18", str(cm.exception))
        self.assertIn("19", str(cm.exception))

    def test_failure_message_mentions_app_store_connect_and_keeps_record(self):
        a = self.make_archive()
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 18, self.rec, FakeRunner([Result(70, "", "x")]))
        self.assertIn("App Store Connect already shows build 18", str(cm.exception))
        self.assertNotIn("Possible cause", str(cm.exception))
        self.assertEqual(self.rec.uploaded_ios_builds, [])

    def test_account_error_says_possible_cause(self):
        a = self.make_archive()
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 18, self.rec, FakeRunner([Result(70, "", "no account")]))
        self.assertIn("Possible cause", str(cm.exception))

    def test_record_save_failure_names_build_and_record(self):
        a = self.make_archive()

        def boom():
            raise OSError(28, "No space left")
        self.rec.save = boom
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 18, self.rec, FakeRunner())
        msg = str(cm.exception)
        self.assertIn("Upload succeeded for build 18", msg)
        self.assertIn(str(self.rec.path), msg)

    def test_success_records_build_number(self):
        a = self.make_archive()
        ios.upload_testflight(self.game, a, 18, self.rec, FakeRunner())
        self.assertEqual(self.rec.uploaded_ios_builds, [18])
        self.assertEqual(Record.load("amber", state_dir=self.root / "state").uploaded_ios_builds, [18])

    def _build_zero_archive(self):
        a = self.make_archive()
        plist = a / "Products/Applications/Amber.app/Info.plist"
        plist.write_bytes(plistlib.dumps({"DTSDKName": "iphoneos26.5", "CFBundleVersion": "0"}))
        return a

    def test_build_zero_is_keyed_by_version(self):
        a = self._build_zero_archive()
        ios.upload_testflight(self.game, a, 0, self.rec, FakeRunner(), version="1.1.1")
        ios.upload_testflight(self.game, a, 0, self.rec, FakeRunner(), version="1.1.2")
        self.assertEqual(self.rec.uploaded_ios_builds, ["1.1.1/0", "1.1.2/0"])

    def test_build_zero_same_version_is_blocked(self):
        a = self._build_zero_archive()
        self.rec.uploaded_ios_builds.append("1.1.1/0")
        r = FakeRunner()
        with self.assertRaises(StepFailed) as cm:
            ios.upload_testflight(self.game, a, 0, self.rec, r, version="1.1.1")
        self.assertEqual(r.calls, [])
        self.assertIn("for v1.1.1", str(cm.exception))

    def test_build_zero_without_version_refuses(self):
        r = FakeRunner()
        with self.assertRaises(StepFailed):
            ios.upload_testflight(self.game, self._build_zero_archive(), 0, self.rec, r)
        self.assertEqual(r.calls, [])

    def test_nonzero_build_still_blocked_across_versions(self):
        self.rec.uploaded_ios_builds.append(18)
        with self.assertRaises(StepFailed):
            ios.upload_testflight(self.game, self.make_archive(), 18, self.rec, FakeRunner(), version="9.9.9")


class Dsyms(Base):
    def test_dsyms_zip_is_named_dsyms_zip(self):
        a = self.make_archive()
        out = self.root / "out"
        out.mkdir()
        z = ios.zip_dsyms(a, out)
        self.assertEqual(z.name, "dSYMs.zip")
        self.assertEqual(z.parent, out)
        with zipfile.ZipFile(z) as f:
            self.assertIn("Amber.app.dSYM/Contents/Info.plist", f.namelist())

    def test_no_dsym_bundle_fails(self):
        a = self.root / "E.xcarchive"
        (a / "dSYMs").mkdir(parents=True)
        with self.assertRaises(StepFailed):
            ios.zip_dsyms(a, self.root)

    def test_missing_out_dir_fails(self):
        with self.assertRaises(StepFailed):
            ios.zip_dsyms(self.make_archive(), self.root / "nope")

    def test_missing_dsyms_fails(self):
        with self.assertRaises(StepFailed):
            ios.zip_dsyms(self.root / "nope.xcarchive", self.root)


class DeviceRunner:
    def __init__(self, devices, code=0, install=Result(0)):
        self.devices, self.code, self.install, self.calls = devices, code, install, []

    def run(self, cmd, cwd=None, env=None, input=None):
        self.calls.append(list(cmd))
        if "install" in cmd:
            return self.install
        if self.code == 0 and "--json-output" in cmd:
            Path(cmd[cmd.index("--json-output") + 1]).write_text(json.dumps({"result": {"devices": self.devices}}))
        return Result(self.code)


def dev(udid, pairing="paired"):
    return {"identifier": "uuid-" + udid, "hardwareProperties": {"udid": udid},
            "connectionProperties": {"pairingState": pairing}}


class Install(Base):
    def run_install(self, r):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = ios.install_on_iphone(self.game, self.root / "a.app", r)
        return ok, buf.getvalue()

    def test_no_device_returns_false(self):
        r = DeviceRunner([])
        ok, out = self.run_install(r)
        self.assertFalse(ok)
        self.assertIn("not found or not paired", out)
        self.assertEqual(len(r.calls), 1)

    def test_unpaired_returns_false(self):
        ok, out = self.run_install(DeviceRunner([dev(self.game.iphone_id, "unpaired")]))
        self.assertFalse(ok)
        self.assertIn("not found or not paired", out)

    def test_devicectl_failure_returns_false(self):
        ok, out = self.run_install(DeviceRunner([], code=1))
        self.assertFalse(ok)
        self.assertIn("exited 1", out)

    def test_null_devices_returns_false(self):
        ok, _ = self.run_install(DeviceRunner(None))
        self.assertFalse(ok)

    def test_installs_on_found_device(self):
        r = DeviceRunner([dev(self.game.iphone_id)])
        ok, _ = self.run_install(r)
        self.assertTrue(ok)
        cmd = r.calls[1]
        self.assertEqual(cmd[:5], ["xcrun", "devicectl", "device", "install", "app"])
        self.assertEqual(cmd[cmd.index("--device") + 1], self.game.iphone_id)
        self.assertEqual(cmd[-1], str(self.root / "a.app"))

    def test_install_failure_on_present_device_raises_with_error_line(self):
        r = DeviceRunner([dev(self.game.iphone_id)],
                         install=Result(1, "", "ERROR: The application could not be verified. (0xE8008018)\n"))
        with self.assertRaises(StepFailed) as cm:
            self.run_install(r)
        self.assertIn("could not be verified", str(cm.exception))

    def test_iphone_present_probe_does_not_install(self):
        r = DeviceRunner([dev(self.game.iphone_id)])
        self.assertTrue(ios.iphone_present(self.game, r))
        self.assertEqual(len(r.calls), 1)


if __name__ == "__main__":
    unittest.main()
