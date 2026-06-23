import json
import shutil
import tempfile
import unittest
from pathlib import Path

from proxyfleet.config_build import BuildOptions, ConfigBuildError, build_release, verify_release


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "config-src"
LOCKS = ROOT / "component-locks.json"


class ConfigBuildTests(unittest.TestCase):
    def test_build_release_writes_manifest_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = build_release(
                BuildOptions(
                    source_dir=FIXTURE,
                    output_dir=Path(tmp),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )
            manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(1, manifest["release_revision"])
            self.assertEqual("abc123", manifest["source_git_commit"])
            self.assertEqual("v1.19.27", manifest["mihomo_version"])
            paths = {item["path"] for item in manifest["files"]}
            self.assertIn("config.yaml", paths)
            self.assertIn("providers/self-hosted.yaml", paths)
            self.assertIn("rules/force-proxy.yaml", paths)
            self.assertTrue((release / "manifest.sha256").exists())
            verify_release(release)

    def test_verify_release_detects_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = build_release(
                BuildOptions(
                    source_dir=FIXTURE,
                    output_dir=Path(tmp),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )
            (release / "config.yaml").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigBuildError, "哈希不符"):
                verify_release(release)

    def test_verify_release_detects_manifest_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = build_release(
                BuildOptions(
                    source_dir=FIXTURE,
                    output_dir=Path(tmp),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )
            manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
            manifest["release_revision"] = 2
            (release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ConfigBuildError, "manifest.sha256"):
                verify_release(release)

    def test_verify_release_detects_size_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = build_release(
                BuildOptions(
                    source_dir=FIXTURE,
                    output_dir=Path(tmp),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )
            manifest_path = release / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in manifest["files"]:
                if item["path"] == "config.yaml":
                    item["size"] = item["size"] + 1
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            digest = __import__("hashlib").sha256(manifest_path.read_bytes()).hexdigest()
            (release / "manifest.sha256").write_text(f"{digest}  manifest.json\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigBuildError, "size 不符"):
                verify_release(release)

    def test_missing_fleet_proxy_fails(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
            groups = json.loads((Path(src) / "groups.json").read_text(encoding="utf-8"))
            groups["groups"][0]["name"] = "OTHER"
            (Path(src) / "groups.json").write_text(json.dumps(groups), encoding="utf-8")
            with self.assertRaisesRegex(ConfigBuildError, "FLEET_PROXY"):
                build_release(BuildOptions(Path(src), Path(out), 1, "abc123", LOCKS))

    def test_unknown_provider_reference_fails(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
            groups = json.loads((Path(src) / "groups.json").read_text(encoding="utf-8"))
            groups["groups"][0]["use"] = ["missing"]
            (Path(src) / "groups.json").write_text(json.dumps(groups), encoding="utf-8")
            with self.assertRaisesRegex(ConfigBuildError, "未知 Provider"):
                build_release(BuildOptions(Path(src), Path(out), 1, "abc123", LOCKS))

    def test_provider_path_escape_fails(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
            providers = json.loads((Path(src) / "providers.json").read_text(encoding="utf-8"))
            providers["providers"][0]["output"] = "../escape.yaml"
            (Path(src) / "providers.json").write_text(json.dumps(providers), encoding="utf-8")
            with self.assertRaisesRegex(ConfigBuildError, "逃逸"):
                build_release(BuildOptions(Path(src), Path(out), 1, "abc123", LOCKS))

    def test_existing_release_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "000001").mkdir()
            with self.assertRaisesRegex(ConfigBuildError, "已存在"):
                build_release(BuildOptions(FIXTURE, output, 1, "abc123", LOCKS))


if __name__ == "__main__":
    unittest.main()
