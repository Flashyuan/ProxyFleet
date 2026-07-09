import json
import tempfile
import unittest
from pathlib import Path

from proxyfleet.self_update import (
    UpdateContext,
    UpdateError,
    apply_update,
    check_update,
    generate_manifest,
    suppress_update,
)


class SelfUpdateTests(unittest.TestCase):
    def _root(self, base: Path) -> Path:
        root = base / "install"
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "proxyfleet-minion.sh").write_text("#!/usr/bin/env bash\necho old\n", encoding="utf-8")
        (root / "scripts" / "proxyfleet-master.sh").write_text("#!/usr/bin/env bash\necho master\n", encoding="utf-8")
        (root / "README.md").write_text("old\n", encoding="utf-8")
        return root

    def _manifest(self, base: Path, *, role: str = "minion", path: str = "scripts/proxyfleet-minion.sh", data: bytes = b"#!/usr/bin/env bash\necho new\n") -> Path:
        asset = base / "asset"
        asset.write_bytes(data)
        manifest = {
            "schema_version": "1.0",
            "product": "proxyfleet",
            "channel": "stable",
            "version": "v0.1.1",
            "commit": "a" * 40,
            "published_at": "2026-06-26T00:00:00Z",
            "minimum_supported_version": "v0.1.0",
            "summary": ["update"],
            "assets": [
                {
                    "role": role,
                    "path": path,
                    "url": asset.as_uri(),
                    "sha256": __import__("hashlib").sha256(data).hexdigest(),
                    "mode": "0755",
                }
            ],
        }
        path_out = base / "update-manifest.json"
        path_out.write_text(json.dumps(manifest), encoding="utf-8")
        return path_out

    def _context(self, root: Path, manifest: Path, role: str = "minion") -> UpdateContext:
        return UpdateContext(
            role=role,
            install_root=root,
            state_path=root / "state" / "update-state.json",
            manifest_source=str(manifest),
            current_version="v0.1.0",
            current_commit="b" * 40,
        )

    def test_check_update_reports_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            manifest = self._manifest(base)

            payload = check_update(self._context(root, manifest))

            self.assertEqual("available", payload["status"])
            self.assertEqual("v0.1.1", payload["remote_version"])
            self.assertEqual("scripts/proxyfleet-minion.sh", payload["assets"][0]["path"])

    def test_apply_update_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            manifest = self._manifest(base)

            with self.assertRaises(UpdateError) as ctx:
                apply_update(self._context(root, manifest))

            self.assertEqual("E_UPDATE_CONFIRMATION", ctx.exception.error_code)
            self.assertIn("echo old", (root / "scripts" / "proxyfleet-minion.sh").read_text(encoding="utf-8"))

    def test_apply_update_replaces_allowlisted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            manifest = self._manifest(base)

            payload = apply_update(self._context(root, manifest), assume_yes=True)

            self.assertEqual("success", payload["status"])
            self.assertIn("echo new", (root / "scripts" / "proxyfleet-minion.sh").read_text(encoding="utf-8"))
            state = json.loads((root / "state" / "update-state.json").read_text(encoding="utf-8"))
            self.assertEqual("success", state["last_update_status"])

    def test_denylisted_path_is_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            manifest = self._manifest(base, role="master", path="config-src/providers.json")

            with self.assertRaises(UpdateError) as ctx:
                check_update(self._context(root, manifest, role="master"))

            self.assertEqual("E_UPDATE_SCOPE", ctx.exception.error_code)

    def test_sha_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            manifest = self._manifest(base)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["assets"][0]["sha256"] = "0" * 64
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(UpdateError) as ctx:
                apply_update(self._context(root, manifest), assume_yes=True)

            self.assertEqual("E_UPDATE_HASH", ctx.exception.error_code)
            self.assertIn("echo old", (root / "scripts" / "proxyfleet-minion.sh").read_text(encoding="utf-8"))

    def test_raw_github_floating_asset_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            manifest = self._manifest(base)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["assets"][0]["url"] = "https://raw.githubusercontent.com/Flashyuan/ProxyFleet/main/scripts/proxyfleet-minion.sh"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(UpdateError) as ctx:
                check_update(self._context(root, manifest))

            self.assertEqual("E_UPDATE_UNTRUSTED_SOURCE", ctx.exception.error_code)

    def test_verify_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            manifest = self._manifest(base, data=b"#!/usr/bin/env bash\nif then\n")

            with self.assertRaises(UpdateError) as ctx:
                apply_update(self._context(root, manifest), assume_yes=True)

            self.assertEqual("E_UPDATE_VERIFY", ctx.exception.error_code)
            self.assertIn("echo old", (root / "scripts" / "proxyfleet-minion.sh").read_text(encoding="utf-8"))

    def test_suppress_update_records_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            manifest = self._manifest(base)
            context = self._context(root, manifest)

            suppress_update(context, "v0.1.1")
            payload = check_update(context, respect_suppressed=True)

            self.assertEqual("skipped", payload["status"])

    def test_generate_manifest_uses_allowlist_and_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            output = base / "manifest.json"

            payload = generate_manifest(
                install_root=root,
                output=output,
                version="v0.1.1",
                commit="c" * 40,
                base_url="https://example.invalid/releases/v0.1.1",
                role="master",
                assets=["README.md"],
                summary=["docs"],
            )

            self.assertTrue(output.exists())
            self.assertEqual("README.md", payload["assets"][0]["path"])

    def test_master_manifest_marks_minion_script_as_common(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            output = base / "manifest.json"

            payload = generate_manifest(
                install_root=root,
                output=output,
                version="v0.1.1",
                commit="c" * 40,
                base_url="https://example.invalid/releases/v0.1.1",
                role="master",
                assets=["scripts/proxyfleet-master.sh", "scripts/proxyfleet-minion.sh"],
                summary=["scripts"],
            )

            by_path = {asset["path"]: asset for asset in payload["assets"]}
            self.assertEqual("master", by_path["scripts/proxyfleet-master.sh"]["role"])
            self.assertEqual("common", by_path["scripts/proxyfleet-minion.sh"]["role"])

    def test_minion_can_check_common_minion_script_from_master_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            manifest = base / "manifest.json"
            generate_manifest(
                install_root=root,
                output=manifest,
                version="v0.1.1",
                commit="c" * 40,
                base_url="file://" + str(root),
                role="master",
                assets=["scripts/proxyfleet-master.sh", "scripts/proxyfleet-minion.sh"],
                summary=["scripts"],
            )

            payload = check_update(self._context(root, manifest, role="minion"))

            self.assertEqual("available", payload["status"])
            self.assertEqual("scripts/proxyfleet-minion.sh", payload["assets"][0]["path"])
            self.assertEqual("common", payload["assets"][0]["role"])


if __name__ == "__main__":
    unittest.main()
