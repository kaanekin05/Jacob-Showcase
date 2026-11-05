import os
import unittest
from unittest import mock

from ub import names
from ub.config import load_game
from ub.messages import android_message, copy_to_clipboard, ios_message
from ub.runner import FakeRunner, Result

G = load_game("amber")
FW = load_game("beryl")

ANDROID_EXPECTED = """Amber Android v0.1.7 Drive'a yüklendi hocam @Build Owner

Drive Folder: drive.google.com/drive/folders/1EXAMPLEdriveFolderMessageSamplex?usp=drive_link
Test APK: Amber_v.0.1.7_T.apk
Release APK: Amber_v.0.1.7_R.apk
AAB: Amber-0.1.7-v17.aab
Symbols: Amber-0.1.7-v17-IL2CPP.symbols.zip
BuildInfo: drive.google.com/file/d/…/view?usp=drive_link

Changelog;
-UA Team Feedbacks
-Phone language used as starting language bugfix
-GDPR Güncellemeleri"""

IOS_EXPECTED = """Amber iOS v0.1.8 TFye yüklendi hocam @Build Owner

Changelog;
-iOS 27 Crash fix

Drive Folder: drive.google.com/drive/folders/…?usp=drive_link
dSYMs: dSYMs.zip
BuildInfo: Amber_0.1.8_iOS_BuildInfo.json"""


class NamesTests(unittest.TestCase):
    def test_names_match_real_amber_files(self):
        self.assertEqual(names.test_apk(G, "0.1.7"), "Amber_v.0.1.7_T.apk")
        self.assertEqual(names.release_apk(G, "0.1.7"), "Amber_v.0.1.7_R.apk")
        self.assertEqual(names.aab(G, "0.1.7", 17), "Amber-0.1.7-v17.aab")
        self.assertEqual(names.symbols(G, "0.1.7", 17), "Amber-0.1.7-v17-IL2CPP.symbols.zip")
        self.assertEqual(names.buildinfo(G, "0.1.8", "iOS"), "Amber_0.1.8_iOS_BuildInfo.json")
        self.assertEqual(names.buildinfo(G, "0.1.7", "Android"), "Amber_0.1.7_Android_BuildInfo.json")


class GameTests(unittest.TestCase):
    def test_amber_settings(self):
        self.assertEqual(G.product_name, "Amber")
        self.assertEqual((G.dev_branch, G.release_branch), ("dev", "release"))
        self.assertEqual(G.drive_folder_id, "1EXAMPLEdriveFolderamberxxxxxxxxx")
        self.assertEqual(G.mention, "@Build Owner")
        self.assertEqual(G.xcode_major, 26)
        self.assertEqual(G.sdk_prefix, "iphoneos26.")
        self.assertEqual(G.team_id, "ABCDEFGHIJ")
        self.assertEqual(G.iphone_id, "00000000-000000000AA0000A")
        self.assertEqual(G.project_path.name, "g-sample-game")
        self.assertTrue(G.project_path.is_absolute())
        self.assertEqual(G.session_paths, (".memsearch/", ".claude/autoharness/", ".claude/skills/"))
        self.assertEqual(G.merge_drivers, ("keep-active-profile", "keep-srdebugger-enabled"))

    def test_profiles_tie_to_branches(self):
        self.assertEqual(G.profiles["test"]["branch"], "dev")
        self.assertEqual(G.profiles["test"]["android"], ["0-And_Test"])
        self.assertEqual(G.profiles["test"]["ios"], ["0-iOS_Test"])
        self.assertEqual(G.profiles["release"]["branch"], "release")
        self.assertEqual(G.profiles["release"]["android"], ["2-APK_Release", "3-AAB_Release"])
        self.assertEqual(G.profiles["release"]["ios"], ["1-iOS_Release"])

    def test_beryl_settings(self):
        self.assertEqual(FW.product_name, "Beryl!")
        self.assertEqual(FW.project_path.name, "g-beryl")
        self.assertEqual(FW.drive_folder_id, "1EXAMPLEdriveFolderberylxxxxxxxxx")
        self.assertEqual(FW.mention, "@Build Owner")
        self.assertEqual(FW.merge_drivers, ())
        self.assertEqual(FW.keystore_env, ("BERYL_KEYSTORE_PASS", "BERYL_KEYALIAS_PASS"))
        self.assertEqual(FW.ota, {"remote": "studio-minio", "bucket": "beryl",
                                  "endpoint": "https://ota.example.com",
                                  "cdn_base": "https://ota.example.com/beryl",
                                  "profiles": {"test": "development", "release": "production"}})
        fd = FW.guards["forbidden_defines"][0]
        self.assertEqual(set(fd["symbols"]), {"SR_ENABLED", "BERYL_DEV"})
        self.assertEqual(set(fd["platforms"]), {"Android", "iPhone"})
        keep = {k["key"]: k["required"] for k in FW.guards["keep_value"]}
        self.assertEqual(keep, {"m_ActiveProfileId": "067be015d747d4b95b1c258e6206febd", "_isEnabled": "0"})

    def test_beryl_buildinfo_has_no_space(self):
        self.assertEqual(names.buildinfo(FW, "0.0.64", "Android"), "Beryl!_0.0.64_Android_BuildInfo.json")
        self.assertEqual(names.test_apk(FW, "0.0.64"), "Beryl!_v.0.0.64_T.apk")

    def test_amber_defaults_unchanged(self):
        self.assertEqual(G.buildinfo_prefix, "Amber")
        self.assertEqual(G.keystore_env, ("AMBER_KEYSTORE_PASS", "AMBER_KEYALIAS_PASS"))
        self.assertIsNone(G.ota)

    def test_unknown_game_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_game("nope")


class MessageTests(unittest.TestCase):
    def test_android_message_matches_pasted_message(self):
        links = {
            "folder": "drive.google.com/drive/folders/1EXAMPLEdriveFolderMessageSamplex?usp=drive_link",
            "buildinfo": "drive.google.com/file/d/…/view?usp=drive_link",
        }
        n = {
            "test_apk": names.test_apk(G, "0.1.7"),
            "release_apk": names.release_apk(G, "0.1.7"),
            "aab": names.aab(G, "0.1.7", 17),
            "symbols": names.symbols(G, "0.1.7", 17),
        }
        changelog = ["UA Team Feedbacks", "Phone language used as starting language bugfix", "GDPR Güncellemeleri"]
        self.assertEqual(android_message(G, "0.1.7", links, n, changelog), ANDROID_EXPECTED)

    def test_ios_message_matches_pasted_message(self):
        links = {"folder": "drive.google.com/drive/folders/…?usp=drive_link"}
        n = {"buildinfo": names.buildinfo(G, "0.1.8", "iOS")}
        self.assertEqual(ios_message(G, "0.1.8", links, n, ["iOS 27 Crash fix"]), IOS_EXPECTED)

    def test_changelog_lines_get_one_dash(self):
        links = {"folder": "f"}
        n = {"buildinfo": "b"}
        for lines in (["x"], ["-x"], ["", "x", "  "], ["x\n\n"]):
            msg = ios_message(G, "1.0.0", links, n, lines)
            self.assertIn("Changelog;\n-x\n\nDrive Folder", msg)
        self.assertEqual(ios_message(G, "1.0.0", links, n, "a\n-b\n\nc").split("\n\n")[1],
                         "Changelog;\n-a\n-b\n-c")

    def test_clipboard_sends_utf8_with_utf8_locale(self):
        fake = FakeRunner()
        copy_to_clipboard("GDPR Güncellemeleri", fake)
        self.assertEqual(fake.calls[0].cmd, ["pbcopy"])
        self.assertEqual(fake.calls[0].input, "GDPR Güncellemeleri".encode("utf-8"))
        self.assertEqual(fake.calls[0].env["LC_CTYPE"], "UTF-8")

    def test_clipboard_drops_lc_all(self):
        fake = FakeRunner()
        with mock.patch.dict(os.environ, {"LC_ALL": "C"}):
            copy_to_clipboard("x", fake)
        self.assertNotIn("LC_ALL", fake.calls[0].env)
        self.assertEqual(fake.calls[0].env["LC_CTYPE"], "UTF-8")

    def test_clipboard_failure_raises(self):
        fake = FakeRunner([Result(1, "", "no pasteboard\n")])
        with self.assertRaises(RuntimeError) as cm:
            copy_to_clipboard("x", fake)
        self.assertIn("pbcopy", str(cm.exception))
        self.assertIn("no pasteboard", str(cm.exception))


class FakeRunnerTests(unittest.TestCase):
    def test_scripted_results_in_order_then_default(self):
        from ub.runner import Result
        fake = FakeRunner([Result(1, "o", "e")])
        self.assertEqual(fake.run(["a"]).code, 1)
        self.assertEqual(fake.run(["b"]).code, 0)
        self.assertEqual([c.cmd for c in fake.calls], [["a"], ["b"]])


if __name__ == "__main__":
    unittest.main()
