import json
import os
import tempfile
import unittest
from pathlib import Path

from sumika_core.agent import dsh_release


ROOT = Path(__file__).resolve().parents[2]


class DshReleaseDescriptionTests(unittest.TestCase):
    def setUp(self):
        self.release_root = ROOT / "dsh-release"

    def test_channel_default_is_a_described_active_release(self):
        channel = dsh_release.load_channel(ROOT)
        default = channel["default_release"]
        self.assertTrue((self.release_root / "releases" / default / "release.json").is_file())
        release = dsh_release.load_release(default, ROOT)
        self.assertEqual(release["id"], default)
        self.assertEqual(release["status"], "verified-active")
        self.assertEqual(release["adapter_contract"], dsh_release.ADAPTER_CONTRACT)

    def test_active_release_pins_a_frozen_lockfile_for_its_own_version(self):
        release = dsh_release.load_release(None, ROOT)
        directory = self.release_root / "releases" / release["id"]
        lockfile = directory / release["toolchain"]["lockfile"]
        self.assertTrue(lockfile.is_file())
        digest = dsh_release._sha256_file(lockfile)
        self.assertEqual(digest, release["toolchain"]["lockfile_sha256"].lower())
        self.assertIn(f"{release['harness']['package']}@{release['harness']['version']}",
                      lockfile.read_text(encoding="utf-8"))

    def test_own_plugin_content_matches_the_description(self):
        release = dsh_release.load_release(None, ROOT)
        self.assertEqual(dsh_release.verify_plugins(release, ROOT), [])
        self.assertGreaterEqual(len(release["plugins"]), 4)
        for plugin in release["plugins"]:
            self.assertIn(plugin["install"], dsh_release.PLUGIN_INSTALL_MODES)
            manifest = json.loads((ROOT / plugin["path"] / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["name"], plugin["name"])
            self.assertEqual(manifest["version"], plugin["version"])

    def test_community_catalog_does_not_drift_from_the_release(self):
        catalog = json.loads((ROOT / "plugins" / "community-defaults.json").read_text(encoding="utf-8"))
        release = dsh_release.load_release(None, ROOT)
        described = {plugin["name"]: plugin for plugin in release["plugins"]}
        for package in catalog["packages"]:
            self.assertIn(package["name"], described,
                          "a community default must be described by the active release")
            plugin = described[package["name"]]
            self.assertEqual(plugin["version"], package["version"])
            self.assertEqual(sorted(plugin.get("groups") or []), sorted(package["groups"]))
            self.assertFalse(plugin["default_enabled"])

    def test_the_candidate_is_described_and_blocked(self):
        candidate = dsh_release.load_release("0.1.5-rc.1", ROOT)
        self.assertEqual(candidate["status"], "blocked")
        self.assertEqual(candidate["harness"]["version"], "0.1.5-rc.1")
        self.assertNotEqual(candidate["adapter_contract"], dsh_release.ADAPTER_CONTRACT)
        blockers = " ".join(candidate["verification"]["blockers"])
        for expected in ("Token authentication", "Endpoint naming", "Payload envelope"):
            self.assertIn(expected, blockers)
        # The frozen lockfile of the candidate must be real even though the
        # release is not launchable yet.
        lockfile = self.release_root / "releases" / "0.1.5-rc.1" / candidate["toolchain"]["lockfile"]
        self.assertEqual(dsh_release._sha256_file(lockfile),
                         candidate["toolchain"]["lockfile_sha256"].lower())

    def test_distribution_identity_is_path_independent_and_content_bound(self):
        release = dsh_release.load_release(None, ROOT)
        baseline = dsh_release.distribution_id(release)
        self.assertEqual(baseline, dsh_release.distribution_id(json.loads(json.dumps(release))))
        changed = json.loads(json.dumps(release))
        changed["plugins"][0]["content_digest"] = "f" * 64
        self.assertNotEqual(baseline, dsh_release.distribution_id(changed))
        moved = json.loads(json.dumps(release))
        moved["harness"]["install"]["root"] = r"E:\Elsewhere"
        self.assertEqual(baseline, dsh_release.distribution_id(moved))

    def test_install_policy_installs_from_the_lockfile_without_scripts(self):
        for release_id in (None, "0.1.5-rc.1"):
            release = dsh_release.load_release(release_id, ROOT)
            self.assertTrue(release["install_policy"]["lockfile_only"])
            self.assertTrue(release["install_policy"]["ignore_scripts"])
            self.assertEqual(release["install_policy"]["scripts_allowed"], [])

    def test_release_id_selection_fails_closed(self):
        with self.assertRaises(dsh_release.DshReleaseError):
            dsh_release.load_release("no-such-release", ROOT)
        with self.assertRaises(dsh_release.DshReleaseError):
            dsh_release.load_release("../escape", ROOT)
        self.assertEqual(dsh_release.resolve_release_id(None, ROOT),
                         dsh_release.load_channel(ROOT)["default_release"])

    def test_environment_override_selects_another_described_release(self):
        previous = os.environ.get("SUMIKA_DSH_RELEASE")
        os.environ["SUMIKA_DSH_RELEASE"] = "0.1.5-rc.1"
        try:
            self.assertEqual(dsh_release.resolve_release_id(None, ROOT), "0.1.5-rc.1")
            self.assertEqual(dsh_release.load_release(None, ROOT)["id"], "0.1.5-rc.1")
        finally:
            if previous is None:
                os.environ.pop("SUMIKA_DSH_RELEASE", None)
            else:
                os.environ["SUMIKA_DSH_RELEASE"] = previous

    def test_layout_matching_binds_a_launch_to_the_described_install(self):
        release = dsh_release.load_release(None, ROOT)
        described = dsh_release.executable_path(release)
        self.assertTrue(dsh_release.matches_described_layout(release, described))
        relocated = Path(r"E:\Other\Harness") / release["harness"]["install"]["directory"] / \
            release["harness"]["install"]["executable"]
        self.assertTrue(dsh_release.matches_described_layout(release, relocated))
        self.assertFalse(dsh_release.matches_described_layout(release, r"E:\Other\Harness\dsh.cmd"))

    def test_installed_evidence_levels_are_reported_honestly(self):
        release = dsh_release.load_release(None, ROOT)
        with tempfile.TemporaryDirectory() as directory:
            absent = dsh_release.installed_lockfile_evidence(release, directory)
            self.assertEqual(absent["level"], "declared-unverified")
            install_dir = dsh_release.install_directory(release, directory)
            virtual = install_dir / "node_modules" / ".pnpm"
            virtual.mkdir(parents=True)
            (virtual / "lock.yaml").write_text("different", encoding="utf-8")
            mismatched = dsh_release.installed_lockfile_evidence(release, directory)
            self.assertEqual(mismatched["level"], "mismatch")
            source = self.release_root / "releases" / release["id"] / release["toolchain"]["lockfile"]
            (virtual / "lock.yaml").write_bytes(source.read_bytes())
            verified = dsh_release.installed_lockfile_evidence(release, directory)
            self.assertEqual(verified["level"], "frozen-lockfile-verified")

    def test_no_consumer_keeps_its_own_copy_of_the_dsh_version(self):
        """Duplicated version knowledge is the regression H02 removes."""

        consumers = (
            ROOT / "tools" / "dsh-launch.ps1",
            ROOT / "tools" / "setup-dsh.ps1",
            ROOT / "tools" / "setup-sumika-dsh-bridges.ps1",
        )
        versions = {dsh_release.load_release(release_id, ROOT)["harness"]["version"]
                    for release_id in (None, "0.1.5-rc.1")}
        for consumer in consumers:
            text = consumer.read_text(encoding="utf-8")
            for version in versions:
                self.assertNotIn(version, text,
                                 f"{consumer.name} must read the release description instead of {version}")
            self.assertNotIn("legacy-unlocked", text)
        # Rust keeps version literals only inside its own unit tests; the
        # production half must resolve the release at run time.
        rust = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        production = rust.split("#[cfg(test)]")[0]
        for version in versions:
            self.assertNotIn(version, production,
                             f"main.rs must read the release description instead of {version}")
        self.assertNotIn("legacy-unlocked", production)

    def test_managed_identity_derives_its_distribution_from_the_description(self):
        source = (ROOT / "backend" / "src" / "sumika_core" / "agent" / "managed_identity.py").read_text(
            encoding="utf-8")
        self.assertIn("dsh_release.distribution_id", source)
        self.assertIn("matches_described_layout", source)
        self.assertNotIn("legacy-unlocked", source)


if __name__ == "__main__":
    unittest.main()
