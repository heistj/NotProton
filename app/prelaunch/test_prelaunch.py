# make prelaunch-tests runs these. Not installed into the app.

import tempfile
import unittest
from pathlib import Path

import crossover_reset as cr
import crossover_update as cu
import ed25519
import prelaunch

FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <item>
      <title>CrossOver Mac 26.4.0</title>
      <enclosure url="https://example.invalid/crossover-26.4.0.zip" sparkle:version="26.4.0.39900"
        sparkle:shortVersionString="26.4.0" sparkle:edSignature="c2ln" length="100" />
      <sparkle:minimumSystemVersion>10.15</sparkle:minimumSystemVersion>
    </item>
    <item>
      <title>CrossOver Mac 26.3.0</title>
      <enclosure url="https://example.invalid/crossover-26.3.0.zip" sparkle:version="26.3.0.39832"
        sparkle:shortVersionString="26.3.0" sparkle:edSignature="c2ln" length="100" />
    </item>
    <item><title>No enclosure</title></item>
  </channel>
</rss>
"""


def release(version, minimum="10.15"):
    return cu.Release(version, version, f"https://example.invalid/{version}.zip", "c2ln", 1, minimum)


class FeedTests(unittest.TestCase):
    def test_parses_enclosures_and_skips_items_without_one(self):
        releases = cu.parse_feed(FEED)
        self.assertEqual([r.version for r in releases], ["26.4.0.39900", "26.3.0.39832"])
        self.assertEqual(releases[0].display, "26.4.0")
        self.assertEqual(releases[0].minimum_macos, "10.15")
        self.assertEqual(releases[1].minimum_macos, "0")

    def test_versions_order_numerically(self):
        self.assertLess(cu.version_key("26.3.0.39832"), cu.version_key("26.10.0.1"))
        self.assertLess(cu.version_key("26.3.0.39832"), cu.version_key("27.0.0.40921"))


class PlanTests(unittest.TestCase):
    installed = "26.3.0.39832"

    def test_nothing_newer_does_nothing(self):
        self.assertIsNone(cu.plan(self.installed, [release(self.installed)], {self.installed}, {}, "26.6"))

    def test_newer_supported_build_is_offered(self):
        d = cu.plan(self.installed, [release("27.0.0.41069")], {"27.0.0.41069"}, {}, "26.6")
        self.assertEqual((d.action, d.release.version), ("update", "27.0.0.41069"))

    def test_newer_unsupported_build_is_warned_about(self):
        d = cu.plan(self.installed, [release("26.4.0.39900")], {self.installed}, {}, "26.6")
        self.assertEqual((d.action, d.release.version), ("warn", "26.4.0.39900"))

    def test_warning_is_shown_once_per_version(self):
        state = {"warned": "26.4.0.39900"}
        self.assertIsNone(cu.plan(self.installed, [release("26.4.0.39900")], {self.installed}, state, "26.6"))

    def test_newest_supported_wins_over_an_unsupported_newer_one(self):
        releases = [release("27.0.0.40921"), release("27.0.0.41069"), release("27.1.0.1")]
        d = cu.plan(self.installed, releases, {"27.0.0.40921", "27.0.0.41069"}, {}, "26.6")
        self.assertEqual((d.action, d.release.version), ("update", "27.0.0.41069"))

    def test_declined_update_is_not_offered_again_but_unsupported_newer_still_warns(self):
        releases = [release("27.0.0.41069"), release("27.1.0.1")]
        state = {"declined": "27.0.0.41069"}
        d = cu.plan(self.installed, releases, {"27.0.0.41069"}, state, "26.6")
        self.assertEqual((d.action, d.release.version), ("warn", "27.1.0.1"))

    def test_release_needing_newer_macos_is_ignored(self):
        d = cu.plan(self.installed, [release("27.0.0.41069", minimum="27.0")], {"27.0.0.41069"}, {}, "26.6")
        self.assertIsNone(d)


class FreshInstallPlanTests(unittest.TestCase):
    def test_newest_supported_build_is_offered(self):
        releases = [release("26.3.0.39832"), release("26.4.0.39900")]
        d = cu.plan(None, releases, {"26.3.0.39832"}, {}, "26.6")
        self.assertEqual((d.action, d.release.version), ("install", "26.3.0.39832"))

    def test_nothing_supported_offers_nothing(self):
        self.assertIsNone(cu.plan(None, [release("26.4.0.39900")], {"26.3.0.39832"}, {}, "26.6"))

    def test_declined_install_is_not_offered_again(self):
        state = {"declined_install": "26.3.0.39832"}
        self.assertIsNone(cu.plan(None, [release("26.3.0.39832")], {"26.3.0.39832"}, state, "26.6"))

    def test_newer_supported_build_is_offered_after_a_decline(self):
        state = {"declined_install": "26.3.0.39832"}
        releases = [release("26.3.0.39832"), release("27.0.0.41069")]
        d = cu.plan(None, releases, {"26.3.0.39832", "27.0.0.41069"}, state, "26.6")
        self.assertEqual((d.action, d.release.version), ("install", "27.0.0.41069"))


class ReplaceTests(unittest.TestCase):
    def test_places_the_app_where_none_was(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dest = root / "Applications" / "CrossOver.app"
            dest.parent.mkdir()
            new = root / "new" / "CrossOver.app"
            (new / "Contents").mkdir(parents=True)
            (new / "Contents" / "new").write_text("new")

            cu.replace_app(new, dest)

            self.assertTrue((dest / "Contents" / "new").exists())
            self.assertEqual(sorted(p.name for p in dest.parent.iterdir()), ["CrossOver.app"])

    def test_swaps_the_app_and_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dest = root / "Applications" / "CrossOver.app"
            (dest / "Contents").mkdir(parents=True)
            (dest / "Contents" / "old").write_text("old")
            new = root / "new" / "CrossOver.app"
            (new / "Contents").mkdir(parents=True)
            (new / "Contents" / "new").write_text("new")

            cu.replace_app(new, dest)

            self.assertTrue((dest / "Contents" / "new").exists())
            self.assertFalse((dest / "Contents" / "old").exists())
            self.assertEqual(sorted(p.name for p in dest.parent.iterdir()), ["CrossOver.app"])


class Ed25519Tests(unittest.TestCase):
    # RFC 8032, section 7.1, tests 1 to 3.
    vectors = [
        ("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
        ("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
         "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
    ]

    def test_rfc_vectors_verify(self):
        for pk, msg, sig in self.vectors:
            self.assertTrue(ed25519.verify(bytes.fromhex(pk), bytes.fromhex(msg), bytes.fromhex(sig)))

    def test_tampered_message_and_signature_fail(self):
        pk, msg, sig = (bytes.fromhex(x) for x in self.vectors[2])
        self.assertFalse(ed25519.verify(pk, msg + b"x", sig))
        self.assertFalse(ed25519.verify(pk, msg, bytes([sig[0] ^ 1]) + sig[1:]))
        self.assertFalse(ed25519.verify(pk, msg, sig[:63]))

    def test_file_verification_matches_in_memory(self):
        pk, msg, sig = (bytes.fromhex(x) for x in self.vectors[2])
        with tempfile.NamedTemporaryFile() as f:
            f.write(msg)
            f.flush()
            self.assertTrue(ed25519.verify_file(pk, f.name, sig, chunk_size=1))


class CrossoverResetTests(unittest.TestCase):
    def test_remove_reg_section_removes_section_and_preserves_others(self):
        with tempfile.TemporaryDirectory() as d:
            reg_path = Path(d) / "system.reg"
            initial = (
                "WINE REGISTRY Version 2\n\n"
                "[Software\\\\CodeWeavers\\\\CrossOver\\\\cxoffice] 1234567890\n"
                '"FirstRunDate"="2026/01/01"\n'
                '"SomeOtherKey"=dword:00000001\n\n'
                "[Software\\\\Wine] 1234567890\n"
                '"Version"="wine-9.0"\n'
            )
            reg_path.write_text(initial)

            result = cr.remove_reg_section(reg_path, cr.TARGET_SECTION)
            self.assertTrue(result)

            content = reg_path.read_text()
            self.assertNotIn("CodeWeavers", content)
            self.assertNotIn("FirstRunDate", content)
            self.assertIn("[Software\\\\Wine]", content)
            self.assertIn('"Version"="wine-9.0"', content)

    def test_remove_reg_section_returns_false_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            reg_path = Path(d) / "system.reg"
            initial = "[Software\\\\Wine]\n\"Version\"=\"wine-9.0\"\n"
            reg_path.write_text(initial)

            result = cr.remove_reg_section(reg_path, cr.TARGET_SECTION)
            self.assertFalse(result)
            self.assertEqual(reg_path.read_text(), initial)

    def test_prelaunch_main_calls_reset_and_update(self):
        called = []
        orig_reset = cr.run
        orig_update = cu.run
        try:
            cr.run = lambda: called.append("reset")
            cu.run = lambda: called.append("update")
            ret = prelaunch.main()
            self.assertEqual(ret, 0)
            self.assertEqual(called, ["reset", "update"])
        finally:
            cr.run = orig_reset
            cu.run = orig_update


if __name__ == "__main__":
    unittest.main()

