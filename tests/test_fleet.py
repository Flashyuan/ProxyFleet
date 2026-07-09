import json
import gzip
import hashlib
import importlib.util
import io
import shutil
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import error
from unittest import mock

from proxyfleet.cli import main
from proxyfleet.config_build import BuildOptions, build_release
from proxyfleet.fleet import (
    FleetError,
    MihomoClient,
    build_node_catalog,
    build_sync_plan,
    load_desired_state,
    prepare_salt_publish,
    run_salt_sync,
    run_salt_sync_result,
    salt_envelope,
    select_node,
    SaltSyncResult,
    _summarize_salt_output,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "config-src"
LOCKS = ROOT / "component-locks.json"
SALT_MODULE = ROOT / "salt" / "modules" / "proxyfleet_mihomo.py"


def _release(tmp: Path):
    return build_release(BuildOptions(FIXTURE, tmp, 1, "abc123", LOCKS))


def _installed_mihomo_fixture(root: Path):
    binary = root / "mihomo"
    binary.write_text("#!/bin/sh\necho mihomo\n", encoding="utf-8")
    binary.chmod(0o755)
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    artifact_sha = "1" * 64
    receipt = binary.with_name(binary.name + ".proxyfleet-install.json")
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "component": "mihomo",
                "version": "v1.19.27",
                "arch": "linux-amd64-compatible",
                "source": "file:///fixture",
                "artifact_sha256": artifact_sha,
                "compression": "gzip",
                "binary_sha256": binary_sha,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    locks = root / "component-locks.json"
    locks.write_text(
        json.dumps(
            {
                "components": [
                    {
                        "name": "mihomo",
                        "version": "v1.19.27",
                        "artifacts": {
                            "linux-amd64-compatible": {
                                "url": "file:///fixture",
                                "sha256": artifact_sha,
                                "compression": "gzip",
                            }
                        },
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return locks, binary


class FleetTests(unittest.TestCase):
    def test_build_node_catalog_from_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = _release(Path(tmp))
            catalog = build_node_catalog(release)
            self.assertEqual(1, len(catalog))
            self.assertTrue(catalog[0].node_id.startswith("node-"))
            self.assertEqual("[SELF] test-node", catalog[0].mihomo_name)
            self.assertEqual("self-hosted", catalog[0].provider_id)

    def test_build_node_catalog_accepts_yaml_provider_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "config-src"
            shutil.copytree(FIXTURE, source)
            (source / "provider-self-hosted.json").write_text(
                """
proxies:
  - name: yaml-node
    type: socks5
    server: 127.0.0.1
    port: 1080
""",
                encoding="utf-8",
            )
            release = build_release(BuildOptions(source, root / "releases", 1, "abc123", LOCKS))

            catalog = build_node_catalog(release)

            self.assertEqual("yaml-node", catalog[0].mihomo_name)
            self.assertEqual("self-hosted", catalog[0].provider_id)

    def test_build_node_catalog_merges_health_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            cache = root / "health-cache.json"
            cache.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "release_revision": 1,
                        "provider_revision": 1,
                        "nodes": {
                            node.node_id: {
                                "last_delay_ms": 123,
                                "health_status": "ok",
                                "measured_at": "2026-06-24T00:00:00Z",
                                "freshness": "fresh",
                                "selected": True,
                                "selectable": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            merged = build_node_catalog(release, cache)[0].to_dict()
            self.assertEqual(123, merged["last_delay_ms"])
            self.assertEqual("ok", merged["health_status"])
            self.assertEqual("fresh", merged["freshness"])
            self.assertTrue(merged["selected"])

    def test_build_node_catalog_ignores_stale_health_cache_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            cache = root / "health-cache.json"
            cache.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "release_revision": 999,
                        "provider_revision": 999,
                        "nodes": {node.node_id: {"last_delay_ms": 123, "health_status": "ok"}},
                    }
                ),
                encoding="utf-8",
            )

            merged = build_node_catalog(release, cache)[0].to_dict()

            self.assertNotIn("last_delay_ms", merged)
            self.assertEqual("unknown", merged["health_status"])

    def test_select_node_writes_desired_and_increments_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            desired = select_node(release, root / "runtime", node.node_id, "production")
            self.assertEqual(1, desired["desired_revision"])
            self.assertEqual(node.node_id, desired["selected_node_id"])
            self.assertEqual("[SELF] test-node", desired["selected_mihomo_name"])
            desired2 = select_node(release, root / "runtime", node.node_id, "production")
            self.assertEqual(2, desired2["desired_revision"])
            loaded = load_desired_state(root / "runtime" / "desired.yaml")
            self.assertEqual(2, loaded["desired_revision"])

    def test_select_unknown_node_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = _release(Path(tmp) / "releases")
            with self.assertRaisesRegex(FleetError, "未知 node_id"):
                select_node(release, Path(tmp) / "runtime", "node-missing", "production")

    def test_publish_salt_copies_release_and_desired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            port_policy = root / "port-policy.json"
            port_policy.write_text(json.dumps({"owner": "master", "allow": [], "deny": []}), encoding="utf-8")
            asset = root / "component-assets" / "mihomo.gz"
            asset.parent.mkdir()
            asset.write_bytes(b"offline")
            mirror_asset = root / "runtime" / "asset-mirror" / "public" / "proxyfleet" / "mihomo" / "mirror.gz"
            mirror_asset.parent.mkdir(parents=True)
            mirror_asset.write_bytes(b"mirror")
            asset_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
            locks = root / "component-locks.json"
            locks.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "mihomo",
                                "version": "v1.19.27",
                                "artifacts": {
                                    "linux-amd64": {
                                        "local_path": "component-assets/mihomo.gz",
                                        "url": "https://example.invalid/mihomo.gz",
                                        "sha256": asset_sha,
                                        "compression": "gzip",
                                        "target_path": "/usr/local/bin/mihomo",
                                    }
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            plan = prepare_salt_publish(
                release,
                root / "runtime" / "desired.yaml",
                root / "srv-salt",
                locks,
                port_policy,
                "merge",
            )
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "releases" / "000001" / "config.yaml").exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "desired.yaml").exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "component-locks.json").exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "assets" / "mihomo.gz").exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "assets" / "mirror.gz").exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "assets" / asset_sha).exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "port-policy.yaml").exists())
            self.assertEqual(0o755, (root / "srv-salt" / "proxyfleet" / "releases" / "000001").stat().st_mode & 0o777)
            self.assertEqual(0o644, (root / "srv-salt" / "proxyfleet" / "releases" / "000001" / "config.yaml").stat().st_mode & 0o777)
            self.assertEqual(0o644, (root / "srv-salt" / "proxyfleet" / "desired.yaml").stat().st_mode & 0o777)
            self.assertEqual(1, plan.release_revision)
            self.assertEqual(1, plan.desired_revision)
            self.assertTrue(plan.port_policy_enabled)
            self.assertEqual("tproxy", plan.proxy_mode)

    def test_lightweight_publish_only_updates_desired_and_keeps_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(
                release,
                root / "runtime" / "desired.yaml",
                salt_root,
                LOCKS,
                None,
                full_converge=True,
            )
            asset_marker = salt_root / "proxyfleet" / "assets" / "marker.txt"
            asset_marker.write_text("keep-assets\n", encoding="utf-8")
            select_node(release, root / "runtime", node.node_id, "production")

            prepare_salt_publish(
                release,
                root / "runtime" / "desired.yaml",
                salt_root,
                LOCKS,
                None,
                full_converge=False,
            )

            self.assertEqual("keep-assets\n", asset_marker.read_text(encoding="utf-8"))
            desired = json.loads((salt_root / "proxyfleet" / "desired.yaml").read_text(encoding="utf-8"))
            self.assertEqual(2, desired["desired_revision"])

    def test_lightweight_publish_requires_existing_release_and_locks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")

            with self.assertRaises(FleetError) as ctx:
                prepare_salt_publish(
                    release,
                    root / "runtime" / "desired.yaml",
                    root / "empty-salt",
                    LOCKS,
                    None,
                    full_converge=False,
                )

            self.assertEqual("E_SYNC_NEEDS_FULL_CONVERGE", ctx.exception.error_code)

    def test_sync_plan_rejects_provider_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            desired_path = root / "runtime" / "desired.yaml"
            desired = json.loads(desired_path.read_text(encoding="utf-8"))
            desired["provider_revision"] = 99
            desired_path.write_text(json.dumps(desired), encoding="utf-8")
            with self.assertRaisesRegex(FleetError, "provider_revision"):
                build_sync_plan(release, desired_path, root / "srv-salt", "*")

    def test_run_salt_sync_passes_selected_salt_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            plan = build_sync_plan(
                release,
                root / "runtime" / "desired.yaml",
                root / "custom-salt",
                "minion-1",
                port_policy_enabled=True,
                port_policy_mode="merge",
            )
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.return_value.returncode = 0
                self.assertEqual(0, run_salt_sync(plan, "salt"))
            cmd = run.call_args.args[0]
            self.assertIn("minion-1", cmd)
            pillar = next(item for item in cmd if item.startswith("pillar="))
            self.assertIn(str(root / "custom-salt" / "proxyfleet" / "releases"), pillar)
            self.assertIn(str(root / "custom-salt" / "proxyfleet" / "desired.yaml"), pillar)
            self.assertIn(str(root / "custom-salt" / "proxyfleet" / "component-locks.json"), pillar)
            self.assertIn('"proxyfleet_port_policy_enabled":true', pillar)
            self.assertIn('"proxyfleet_port_policy_mode":"merge"', pillar)
            self.assertIn('"proxyfleet_proxy_mode":"tproxy"', pillar)

    def test_run_salt_sync_supports_batch_and_log_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", root / "srv-salt", "*")
            salt_output = "minion-a:\n  Result: False\n  Comment: E_LOCAL_API failed\nminion-b:\n  Result: True\n"
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.return_value = mock.Mock(returncode=2, stdout=salt_output, stderr="")
                result = run_salt_sync_result(plan, "salt", batch="20%", log_dir=root / "logs")

            cmd = run.call_args.args[0]
            self.assertIn("--batch", cmd)
            self.assertIn("20%", cmd)
            self.assertIn("--state-output=terse", cmd)
            self.assertEqual(2, result.returncode)
            self.assertIn("minion-a", result.failed_minions)
            self.assertIn("E_LOCAL_API", result.error_summary)
            self.assertIsNotNone(result.log_path)
            self.assertTrue(result.log_path.exists())
            self.assertIn("E_LOCAL_API failed", result.log_path.read_text(encoding="utf-8"))
            self.assertEqual(0o700, (root / "logs").stat().st_mode & 0o777)
            self.assertEqual(0o600, result.log_path.stat().st_mode & 0o777)

    def test_run_salt_sync_falls_back_when_batch_publish_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", root / "srv-salt", "*")
            batch_error = "salt.exceptions.SaltClientError: Some exception handling minion payload\n"
            success = "minion-a:\n  Result: True\n"
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=1, stdout="", stderr=batch_error),
                    mock.Mock(returncode=0, stdout=success, stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", batch="20%", log_dir=root / "logs")

            first_cmd = run.call_args_list[0].args[0]
            second_cmd = run.call_args_list[1].args[0]
            self.assertIn("--batch", first_cmd)
            self.assertNotIn("--batch", second_cmd)
            self.assertEqual(0, result.returncode)
            log_text = result.log_path.read_text(encoding="utf-8")
            self.assertIn("retried without --batch", log_text)

    def test_salt_log_redacts_proxy_uri_and_secret_like_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", root / "srv-salt", "*")
            salt_output = "minion-a:\n  Comment: password=abc vless://00000000-0000-0000-0000-000000000000@example\n"
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.return_value = mock.Mock(returncode=1, stdout=salt_output, stderr="")
                result = run_salt_sync_result(plan, "salt", log_dir=root / "logs")

            log_text = result.log_path.read_text(encoding="utf-8")
            self.assertIn("redacted", log_text)
            self.assertNotIn("password=abc", log_text)
            self.assertNotIn("vless://", log_text)

    def test_salt_log_redacts_yaml_and_json_secret_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", root / "srv-salt", "*")
            salt_output = (
                "minion-a:\n"
                "  Result: False\n"
                "  Comment: password: abc\n"
                "  Error: {\"api_secret\": \"def\", \"token\": \"ghi\"}\n"
            )
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.return_value = mock.Mock(returncode=1, stdout=salt_output, stderr="")
                result = run_salt_sync_result(plan, "salt", log_dir=root / "logs")

            log_text = result.log_path.read_text(encoding="utf-8")
            self.assertIn("redacted", log_text)
            self.assertIn("redacted", result.error_summary)
            for leaked in ("password: abc", '"api_secret": "def"', '"token": "ghi"', "def", "ghi"):
                self.assertNotIn(leaked, log_text)
                self.assertNotIn(leaked, result.error_summary)

    def test_run_salt_sync_rejects_invalid_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", root / "srv-salt", "*")

            with self.assertRaises(FleetError):
                run_salt_sync_result(plan, "salt", batch="0%")

    def test_smart_sync_routes_old_minions_to_switch_and_new_to_converge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            status = json.dumps(
                {
                    "drift": {"classification": "drifted", "reason": "component locks hash mismatch"},
                    "old": {"classification": "ready-old", "reason": "ready"},
                    "new": {"classification": "new-minion", "reason": "missing receipt"},
                    "off": {"classification": "offline", "reason": "not returned"},
                }
            )
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["drift", "old", "new", "off"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"drift": True, "old": True, "new": True}), stderr=""),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps(
                            {
                                "drift": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"],
                                "old": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"],
                                "new": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"],
                            }
                        ),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=status, stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"old": {"status": "success"}}), stderr=""),
                    mock.Mock(returncode=0, stdout="new:\n  Result: True\n", stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2, log_dir=root / "logs")

            self.assertEqual(0, result.returncode)
            self.assertNotIn("off", result.failed_minions)
            self.assertEqual("Some Minions were offline and deferred", result.warning)
            self.assertEqual(1, result.route_plan["summary"]["ready-old"])
            self.assertEqual(1, result.route_plan["summary"]["new-minion"])
            self.assertEqual(1, result.route_plan["summary"]["drifted"])
            self.assertEqual(1, result.route_plan["summary"]["offline"])
            switch_cmd = run.call_args_list[4].args[0]
            converge_cmd = run.call_args_list[5].args[0]
            self.assertIn("proxyfleet_mihomo.apply_switch", switch_cmd)
            self.assertIn("fail_on_error=true", switch_cmd)
            self.assertIn("-L", switch_cmd)
            self.assertIn("old", switch_cmd)
            self.assertIn("state.apply", converge_cmd)
            self.assertIn("-L", converge_cmd)
            self.assertIn("new", ",".join(converge_cmd))
            self.assertIn("drift", ",".join(converge_cmd))

    def test_smart_sync_switch_failed_envelope_marks_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            status = json.dumps({"old": {"classification": "ready-old", "reason": "ready"}})
            failed = json.dumps({"old": {"status": "failed", "error_code": "E_NODE_NOT_FOUND", "message": "target node is not selectable"}})
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["old"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"old": True}), stderr=""),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps({"old": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"]}),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=status, stderr=""),
                    mock.Mock(returncode=0, stdout=failed, stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(1, result.returncode)
            self.assertEqual(["old"], result.failed_minions)
            self.assertEqual("failed", result.minion_results[0]["status"])
            self.assertEqual("E_NODE_NOT_FOUND", result.minion_results[0]["reason"])

    def test_smart_sync_switch_already_applied_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            status = json.dumps({"old": {"classification": "ready-old", "reason": "ready"}})
            applied = json.dumps({"old": {"status": "success", "message": "already-applied"}})
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["old"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"old": True}), stderr=""),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps({"old": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"]}),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=status, stderr=""),
                    mock.Mock(returncode=0, stdout=applied, stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(0, result.returncode)
            self.assertEqual([], result.failed_minions)
            self.assertEqual("already-applied", result.minion_results[0]["status"])
            self.assertEqual("already-applied", result.minion_results[0]["reason"])

    def test_smart_sync_empty_classification_falls_back_to_state_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=1, stdout="", stderr="salt-key failed"),
                    mock.Mock(returncode=0, stdout="{}", stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(0, result.returncode)
            self.assertTrue(result.fallback_used)
            self.assertTrue(result.route_plan["classification_unavailable"])
            fallback_cmd = run.call_args_list[1].args[0]
            self.assertIn("state.apply", fallback_cmd)
            self.assertNotIn("-L", fallback_cmd)

    def test_smart_sync_status_failure_fallback_success_does_not_report_failed_minions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            fallback_output = "minion-a:\n----------\nSummary for minion-a\n------------\nFailed:     0\n"
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["minion-a"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"minion-a": True}), stderr=""),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps({"minion-a": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"]}),
                        stderr="",
                    ),
                    mock.Mock(returncode=1, stdout="", stderr="sync_status unavailable"),
                    mock.Mock(returncode=0, stdout=fallback_output, stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(0, result.returncode)
            self.assertTrue(result.fallback_used)
            self.assertTrue(result.route_plan["classification_unavailable"])
            self.assertEqual([], result.failed_minions)
            self.assertEqual("", result.error_summary)

    def test_salt_summary_failed_zero_is_not_a_failure(self):
        output = "minion-a:\n----------\nSummary for minion-a\n------------\nFailed:     0\n"

        failed, summary = _summarize_salt_output(output, 0)

        self.assertEqual([], failed)
        self.assertEqual("", summary)

    def test_smart_sync_plan_only_only_classifies_minions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            status = json.dumps({"old": {"classification": "ready-old", "reason": "ready"}})
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["old"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"old": True}), stderr=""),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps({"old": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"]}),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=status, stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", plan_only=True)

            self.assertEqual(0, result.returncode)
            self.assertEqual(4, run.call_count)
            for call in run.call_args_list[1:]:
                self.assertNotIn("--static", call.args[0])
            self.assertEqual("switch-only", result.route_plan["minions"][0]["action"])
            self.assertIn("route_plan", result.to_dict())

    def test_smart_sync_missing_module_routes_to_full_converge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["new"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"new": True}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"new": ["test.ping"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"new": ["proxyfleet_mihomo"]}), stderr=""),
                    mock.Mock(returncode=0, stdout="new:\n  Result: True\n", stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(0, result.returncode)
            self.assertEqual("full-converge", result.route_plan["minions"][0]["action"])
            self.assertEqual("new-minion", result.route_plan["minions"][0]["classification"])
            sync_modules_cmd = run.call_args_list[3].args[0]
            converge_cmd = run.call_args_list[4].args[0]
            self.assertIn("saltutil.sync_modules", sync_modules_cmd)
            self.assertIn("-L", sync_modules_cmd)
            self.assertIn("new", ",".join(sync_modules_cmd))
            self.assertIn("state.apply", converge_cmd)

    def test_smart_sync_stale_module_hash_routes_to_full_converge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            module_path = salt_root / "_modules" / "proxyfleet_mihomo.py"
            module_path.parent.mkdir(parents=True)
            module_path.write_text("current module\n", encoding="utf-8")
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["stale"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"stale": True}), stderr=""),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps({"stale": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch", "proxyfleet_mihomo.module_sha256"]}),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=json.dumps({"stale": {"sha256": "0" * 64}}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"stale": ["proxyfleet_mihomo"]}), stderr=""),
                    mock.Mock(returncode=0, stdout="stale:\n  Result: True\n", stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(0, result.returncode)
            self.assertEqual("full-converge", result.route_plan["minions"][0]["action"])
            self.assertEqual("stale", result.route_plan["minions"][0]["module_status"])
            sync_modules_cmd = run.call_args_list[4].args[0]
            converge_cmd = run.call_args_list[5].args[0]
            self.assertIn("saltutil.sync_modules", sync_modules_cmd)
            self.assertIn("stale", ",".join(sync_modules_cmd))
            self.assertIn("state.apply", converge_cmd)

    def test_smart_sync_module_refresh_is_per_minion_not_global(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            module_path = salt_root / "_modules" / "proxyfleet_mihomo.py"
            module_path.parent.mkdir(parents=True, exist_ok=True)
            module_path.write_text("current module\n", encoding="utf-8")
            expected_hash = module_path.read_bytes()
            current_hash = hashlib.sha256(expected_hash).hexdigest()
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            status = json.dumps({"old": {"classification": "ready-old", "reason": "ready"}})
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["old", "stale", "missing", "offline"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"old": True, "stale": True, "missing": True}), stderr=""),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps(
                            {
                                "old": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch", "proxyfleet_mihomo.module_sha256"],
                                "stale": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch", "proxyfleet_mihomo.module_sha256"],
                                "missing": ["test.ping"],
                            }
                        ),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=json.dumps({"old": {"sha256": current_hash}, "stale": {"sha256": "0" * 64}}), stderr=""),
                    mock.Mock(returncode=0, stdout=status, stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"missing": ["proxyfleet_mihomo"], "stale": ["proxyfleet_mihomo"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"old": {"status": "success"}}), stderr=""),
                    mock.Mock(returncode=0, stdout="missing:\n  Result: True\nstale:\n  Result: True\n", stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=4)

            self.assertEqual(0, result.returncode)
            by_id = {item["minion_id"]: item for item in result.route_plan["minions"]}
            self.assertEqual("switch-only", by_id["old"]["action"])
            self.assertEqual("defer", by_id["offline"]["action"])
            self.assertEqual("full-converge", by_id["missing"]["action"])
            self.assertEqual("full-converge", by_id["stale"]["action"])
            sync_modules_cmd = run.call_args_list[5].args[0]
            switch_cmd = run.call_args_list[6].args[0]
            converge_cmd = run.call_args_list[7].args[0]
            self.assertIn("saltutil.sync_modules", sync_modules_cmd)
            self.assertIn("missing", ",".join(sync_modules_cmd))
            self.assertIn("stale", ",".join(sync_modules_cmd))
            self.assertNotIn("old", ",".join(sync_modules_cmd))
            self.assertIn("proxyfleet_mihomo.apply_switch", switch_cmd)
            self.assertIn("old", ",".join(switch_cmd))
            self.assertNotIn("--static", switch_cmd)
            self.assertIn("state.apply", converge_cmd)
            self.assertIn("missing", ",".join(converge_cmd))
            self.assertIn("stale", ",".join(converge_cmd))
            self.assertNotIn("old", ",".join(converge_cmd))

    def test_smart_sync_accepted_key_without_ping_is_deferred_not_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            status = json.dumps({"online": {"classification": "ready-old", "reason": "ready"}})
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["online", "offline"]}), stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"online": True}), stderr=""),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps({"online": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"]}),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=status, stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"online": {"status": "success"}}), stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(0, result.returncode)
            self.assertEqual([], result.failed_minions)
            self.assertEqual("Some Minions were offline and deferred", result.warning)
            self.assertEqual(1, result.route_plan["summary"]["offline"])

    def test_smart_sync_ping_nonzero_with_json_result_still_classifies_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            status = json.dumps({"online": {"classification": "ready-old", "reason": "ready"}})
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["online", "offline"]}), stderr=""),
                    mock.Mock(returncode=1, stdout=json.dumps({"online": True}), stderr="one minion did not return"),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps({"online": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"]}),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=status, stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"online": {"status": "success"}}), stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(0, result.returncode)
            self.assertFalse(result.fallback_used)
            self.assertEqual([], result.failed_minions)
            self.assertEqual(1, result.route_plan["summary"]["ready-old"])
            self.assertEqual(1, result.route_plan["summary"]["offline"])

    def test_smart_sync_ping_nonzero_with_text_result_still_classifies_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", salt_root, "*")
            status = json.dumps({"online": {"classification": "ready-old", "reason": "ready"}})
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"minions": ["online", "offline"]}), stderr=""),
                    mock.Mock(returncode=1, stdout="online:\n    True\n", stderr="offline did not return"),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps({"online": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"]}),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=status, stderr=""),
                    mock.Mock(returncode=0, stdout=json.dumps({"online": {"status": "success"}}), stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(0, result.returncode)
            self.assertFalse(result.fallback_used)
            self.assertEqual([], result.failed_minions)
            self.assertEqual(1, result.route_plan["summary"]["ready-old"])
            self.assertEqual(1, result.route_plan["summary"]["offline"])

    def test_smart_sync_port_policy_forces_ready_old_to_converge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", salt_root, LOCKS, None, full_converge=True)
            plan = build_sync_plan(
                release,
                root / "runtime" / "desired.yaml",
                salt_root,
                "old",
                port_policy_enabled=True,
            )
            status = json.dumps({"old": {"classification": "ready-old", "reason": "ready"}})
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.side_effect = [
                    mock.Mock(returncode=0, stdout=json.dumps({"old": True}), stderr=""),
                    mock.Mock(
                        returncode=0,
                        stdout=json.dumps({"old": ["proxyfleet_mihomo.sync_status", "proxyfleet_mihomo.apply_switch"]}),
                        stderr="",
                    ),
                    mock.Mock(returncode=0, stdout=status, stderr=""),
                    mock.Mock(returncode=0, stdout="old:\n  Result: True\n", stderr=""),
                ]
                result = run_salt_sync_result(plan, "salt", concurrency=2)

            self.assertEqual(0, result.returncode)
            self.assertEqual("full-converge", result.route_plan["minions"][0]["action"])
            converge_cmd = run.call_args_list[3].args[0]
            self.assertIn("state.apply", converge_cmd)
            self.assertIn("-L", converge_cmd)

    def test_cli_sync_plan_only_json_outputs_route_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            route_plan = {"summary": {"ready-old": 1}, "minions": [{"minion_id": "old", "action": "switch-only"}]}
            stdout = io.StringIO()

            with mock.patch("proxyfleet.cli.run_salt_sync_result", return_value=SaltSyncResult(0, None, [], "", route_plan=route_plan)), mock.patch("sys.stdout", new=stdout):
                rc = main(
                    [
                        "sync",
                        str(release),
                        str(root / "runtime" / "desired.yaml"),
                        str(salt_root),
                        "--plan-only",
                        "--json",
                    ]
                )

            self.assertEqual(0, rc)
            payload = json.loads(stdout.getvalue())
            self.assertEqual("planned", payload["status"])
            self.assertEqual({"ready-old": 1}, payload["salt"]["route_plan"]["summary"])

    def test_cli_sync_warning_outputs_partial_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            route_plan = {"summary": {"offline": 1}, "minions": [{"minion_id": "off", "action": "defer", "classification": "offline"}]}
            stdout = io.StringIO()

            with mock.patch(
                "proxyfleet.cli.run_salt_sync_result",
                return_value=SaltSyncResult(0, None, [], "", route_plan=route_plan, warning="No reachable Minions; sync deferred"),
            ), mock.patch("sys.stdout", new=stdout):
                rc = main(
                    [
                        "sync",
                        str(release),
                        str(root / "runtime" / "desired.yaml"),
                        str(salt_root),
                    ]
                )

            self.assertEqual(0, rc)
            output = stdout.getvalue()
            self.assertIn("同步目标：*", output)
            self.assertIn("提示：No reachable Minions; sync deferred", output)
            self.assertIn("off", output)
            self.assertIn("离线", output)
            self.assertIn("结果：部分成功", output)
            self.assertNotIn('"route_plan"', output)

    def test_cli_sync_json_preserves_machine_readable_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            salt_root = root / "srv-salt"
            route_plan = {"summary": {"offline": 1}, "minions": [{"minion_id": "off", "action": "defer", "classification": "offline"}]}
            stdout = io.StringIO()

            with mock.patch(
                "proxyfleet.cli.run_salt_sync_result",
                return_value=SaltSyncResult(0, None, [], "", route_plan=route_plan, warning="No reachable Minions; sync deferred"),
            ), mock.patch("sys.stdout", new=stdout):
                rc = main(
                    [
                        "sync",
                        str(release),
                        str(root / "runtime" / "desired.yaml"),
                        str(salt_root),
                        "--json",
                    ]
                )

            self.assertEqual(0, rc)
            payload = json.loads(stdout.getvalue())
            self.assertEqual("partial", payload["status"])
            self.assertEqual("No reachable Minions; sync deferred", payload["salt"]["warning"])
            self.assertIn("route_plan", payload["salt"])

    def test_salt_summary_zero_failure_variants_are_not_failures(self):
        variants = [
            "minion-a:\n----------\nSummary for minion-a\n------------\nFailed: 0\n",
            "minion-a:\n----------\nSummary for minion-a\n------------\nFailed:     0\n",
            "minion-a:\n----------\n# of minions with errors: 0\n",
            "minion-a:\n----------\nSummary for minion-a\n------------\nFailed: 0 (changed=1)\n",
        ]
        for output in variants:
            with self.subTest(output=output):
                failed, summary = _summarize_salt_output(output, 0)
                self.assertEqual([], failed)
                self.assertEqual("", summary)

    def test_salt_envelope_redacts_secret_fields(self):
        envelope = salt_envelope(
            "op-test",
            "minion-1",
            "apply",
            "failed",
            1,
            1,
            "E_LOCAL_API",
            "secret=abc",
            {"api_secret": "abc", "selected_node_id": "node-a"},
        )
        self.assertEqual("redacted", envelope["message"])
        self.assertEqual("redacted", envelope["evidence"]["api_secret"])
        self.assertEqual("node-a", envelope["evidence"]["selected_node_id"])


class MihomoHandler(BaseHTTPRequestHandler):
    selected = ""
    inconsistent = False
    delay_mode = "ok"
    calls = []

    def do_GET(self):
        self.__class__.calls.append(("GET", self.path))
        if self.path.startswith("/proxies/%5BSELF%5D%20test-node/delay"):
            if self.__class__.delay_mode == "timeout":
                time.sleep(0.2)
                return
            self._json({"delay": 123})
            return
        if self.path.startswith("/proxies/missing-node/delay"):
            self.send_response(404)
            self.end_headers()
            return
        body = {"name": "FLEET_PROXY", "now": self.__class__.selected, "all": ["[SELF] test-node"]}
        self._json(body)

    def do_PUT(self):
        self.__class__.calls.append(("PUT", self.path))
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not self.__class__.inconsistent:
            self.__class__.selected = payload["name"]
        self._json({})

    def log_message(self, fmt, *args):
        return

    def _json(self, body):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class MihomoClientTests(unittest.TestCase):
    def setUp(self):
        MihomoHandler.selected = ""
        MihomoHandler.inconsistent = False
        MihomoHandler.delay_mode = "ok"
        MihomoHandler.calls = []
        self.server = HTTPServer(("127.0.0.1", 0), MihomoHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self._server_closed = False

    def tearDown(self):
        if self._server_closed:
            return
        self._close_server()

    def _close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self._server_closed = True

    def test_select_node_puts_then_gets_to_verify(self):
        result = MihomoClient(self.base_url).select_node("FLEET_PROXY", "[SELF] test-node")
        self.assertEqual("success", result["status"])
        self.assertEqual([("GET", "/proxies/FLEET_PROXY"), ("PUT", "/proxies/FLEET_PROXY"), ("GET", "/proxies/FLEET_PROXY")], MihomoHandler.calls)

    def test_select_node_detects_verify_mismatch(self):
        MihomoHandler.inconsistent = True
        with self.assertRaisesRegex(FleetError, "回读结果不一致"):
            MihomoClient(self.base_url).select_node("FLEET_PROXY", "[SELF] test-node")

    def test_health_check_uses_single_node_delay_without_changing_selection(self):
        MihomoHandler.selected = "[SELF] previous"
        result = MihomoClient(self.base_url).health_check("[SELF] test-node", "https://www.gstatic.com/generate_204")
        self.assertEqual("ok", result["health_status"])
        self.assertEqual(123, result["last_delay_ms"])
        self.assertEqual("[SELF] previous", MihomoHandler.selected)
        self.assertEqual(1, len(MihomoHandler.calls))
        method, path = MihomoHandler.calls[0]
        self.assertEqual("GET", method)
        self.assertIn("/proxies/%5BSELF%5D%20test-node/delay", path)
        self.assertNotIn("FLEET_PROXY", path)

    def test_health_check_timeout_maps_error_code(self):
        self._close_server()
        with mock.patch("proxyfleet.fleet.request.urlopen", side_effect=socket.timeout):
            with self.assertRaises(FleetError) as ctx:
                MihomoClient(self.base_url, timeout=0.05).health_check("[SELF] test-node", "https://www.gstatic.com/generate_204")
        self.assertEqual("E_HEALTHCHECK_TIMEOUT", ctx.exception.error_code)

    def test_health_check_api_unavailable_is_not_node_timeout(self):
        self._close_server()
        with mock.patch("proxyfleet.fleet.request.urlopen", side_effect=error.URLError(ConnectionRefusedError())):
            with self.assertRaises(FleetError) as ctx:
                MihomoClient(self.base_url, timeout=0.05).health_check("[SELF] test-node", "https://www.gstatic.com/generate_204")
        self.assertEqual("E_LOCAL_API", ctx.exception.error_code)

    def test_health_check_http_timeout_exceeds_delay_timeout(self):
        self._close_server()
        response = mock.Mock()
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=None)
        response.read.return_value = b'{"delay":123}'

        with mock.patch("proxyfleet.fleet.request.urlopen", return_value=response) as urlopen:
            MihomoClient(self.base_url, timeout=0.05).health_check(
                "[SELF] test-node",
                "https://www.gstatic.com/generate_204",
                timeout_ms=3000,
            )

        self.assertEqual(5.0, urlopen.call_args.kwargs["timeout"])

    def test_health_check_missing_node_maps_error_code(self):
        with self.assertRaises(FleetError) as ctx:
            MihomoClient(self.base_url).health_check("missing-node", "https://www.gstatic.com/generate_204")
        self.assertEqual("E_NODE_NOT_FOUND", ctx.exception.error_code)

    def test_health_check_blocks_non_allowlisted_url(self):
        with self.assertRaises(FleetError) as ctx:
            MihomoClient(self.base_url).health_check("[SELF] test-node", "https://www.gstatic.com/generate_204?debug=1")
        self.assertEqual("E_HEALTHCHECK_TARGET_BLOCKED", ctx.exception.error_code)

    def test_mihomo_client_rejects_non_loopback_api(self):
        with self.assertRaises(FleetError) as ctx:
            MihomoClient("http://192.168.1.1:9090")
        self.assertEqual("E_LOCAL_API", ctx.exception.error_code)

    def test_cli_health_check_writes_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            cache = root / "health.json"
            with mock.patch("sys.stdout", new=io.StringIO()):
                rc = main(
                    [
                        "health-check",
                        str(release),
                        str(cache),
                        "--mihomo-api",
                        self.base_url,
                        "--all",
                        "--url",
                        "https://www.gstatic.com/generate_204",
                    ]
                )
            self.assertEqual(0, rc)
            data = json.loads(cache.read_text(encoding="utf-8"))
            node_id = build_node_catalog(release)[0].node_id
            self.assertEqual(123, data["nodes"][node_id]["last_delay_ms"])
            self.assertEqual(1, data["release_revision"])
            self.assertEqual(1, data["provider_revision"])
            self.assertEqual("master-local", data["source_scope"])

    def test_cli_health_check_progress_stays_on_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            cache = root / "health.json"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with mock.patch("sys.stdout", new=stdout), mock.patch("sys.stderr", new=stderr):
                rc = main(
                    [
                        "health-check",
                        str(release),
                        str(cache),
                        "--mihomo-api",
                        self.base_url,
                        "--all",
                        "--progress",
                        "--concurrency",
                        "4",
                    ]
                )

            self.assertEqual(0, rc)
            self.assertIn("测速中", stderr.getvalue())
            self.assertIn('"schema_version"', stdout.getvalue())

    def test_cli_apply_dry_run_does_not_write_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("sys.stdout", new=io.StringIO()):
                rc = main(
                    [
                        "apply",
                        str(FIXTURE),
                        str(root / "releases"),
                        str(root / "runtime"),
                        str(root / "srv-salt"),
                        "--revision",
                        "1",
                        "--source-git-commit",
                        "abc123",
                        "--dry-run",
                    ]
                )
            self.assertEqual(0, rc)
            self.assertFalse((root / "releases").exists())
            self.assertFalse((root / "runtime").exists())
            self.assertFalse((root / "srv-salt").exists())

    def test_cli_mihomo_failure_does_not_write_desired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            MihomoHandler.inconsistent = True
            with mock.patch("sys.stderr", new=io.StringIO()):
                rc = main(
                    [
                        "select-node",
                        str(release),
                        str(root / "runtime"),
                        "--node-id",
                        node.node_id,
                        "--mihomo-api",
                        self.base_url,
                    ]
                )
            self.assertEqual(2, rc)
            self.assertFalse((root / "runtime" / "desired.yaml").exists())


class SaltModuleTests(unittest.TestCase):
    def _module(self):
        spec = importlib.util.spec_from_file_location("proxyfleet_mihomo_test", SALT_MODULE)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_module_sha256_reports_current_execution_module_hash(self):
        module = self._module()

        payload = module.module_sha256()

        self.assertEqual("1.0", payload["schema_version"])
        self.assertEqual("proxyfleet_mihomo", payload["module"])
        self.assertEqual(hashlib.sha256(SALT_MODULE.read_bytes()).hexdigest(), payload["sha256"])

    def test_verify_release_detects_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = _release(Path(tmp) / "releases")
            (release / "config.yaml").write_text("tampered\n", encoding="utf-8")
            module = self._module()
            with self.assertRaisesRegex(Exception, "manifest file hash mismatch"):
                module._verify_release(release)

    def test_apply_desired_failure_does_not_switch_current_or_desired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            node = build_node_catalog(release)[0]
            desired = select_node(release, root / "runtime", node.node_id, "production")
            install_root = root / "install"
            previous_release = install_root / "releases" / "000000"
            previous_release.mkdir(parents=True)
            current = install_root / "current"
            current.symlink_to(previous_release)
            (install_root / "desired.yaml").write_text("{\"schema_version\":\"1.0\"}\n", encoding="utf-8")

            module = self._module()
            module._reload_or_restart = lambda service_name: None
            result = module.apply_desired(
                release_root=str(root / "salt" / "releases"),
                desired_path=str(root / "runtime" / "desired.yaml"),
                install_root=str(install_root),
                mihomo_api="http://127.0.0.1:1",
                operation_id="op-test",
            )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_LOCAL_API", result["error_code"])
            self.assertEqual(previous_release, current.resolve())
            self.assertEqual("{\"schema_version\":\"1.0\"}\n", (install_root / "desired.yaml").read_text(encoding="utf-8"))

    def test_apply_desired_reloads_before_selecting_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            install_root = root / "install"
            order = []

            module = self._module()
            module._reload_or_restart = lambda service_name: order.append("reload")
            module._wait_mihomo_node = lambda api, secret, group, name: order.append("wait")
            module._select_mihomo = lambda api, secret, group, name: order.append("select")
            result = module.apply_desired(
                release_root=str(root / "salt" / "releases"),
                desired_path=str(root / "runtime" / "desired.yaml"),
                install_root=str(install_root),
                operation_id="op-test",
            )

            self.assertEqual("success", result["status"])
            self.assertEqual(["reload", "wait", "select"], order)
            self.assertEqual(install_root / "releases" / "000001", (install_root / "current").resolve())
            self.assertTrue((install_root / "desired.yaml").exists())

    def test_apply_desired_waits_for_mihomo_api_before_selecting_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            order = []

            module = self._module()
            module._reload_or_restart = lambda service_name: order.append("reload")
            module._wait_mihomo_node = lambda api, secret, group, name: order.append("wait")
            module._select_mihomo = lambda api, secret, group, name: order.append("select")

            result = module.apply_desired(
                release_root=str(root / "salt" / "releases"),
                desired_path=str(root / "runtime" / "desired.yaml"),
                install_root=str(root / "install"),
                operation_id="op-test",
            )

            self.assertEqual("success", result["status"])
            self.assertEqual(["reload", "wait", "select"], order)

    def test_apply_desired_reload_failure_rolls_back_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            install_root = root / "install"
            previous_release = install_root / "releases" / "000000"
            previous_release.mkdir(parents=True)
            current = install_root / "current"
            current.symlink_to(previous_release)

            module = self._module()

            def fail_reload(service_name):
                raise module._ApplyError("E_SERVICE_SYSTEMD", "mihomo reload-or-restart failed")

            module._reload_or_restart = fail_reload
            result = module.apply_desired(
                release_root=str(root / "salt" / "releases"),
                desired_path=str(root / "runtime" / "desired.yaml"),
                install_root=str(install_root),
                operation_id="op-test",
            )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_SERVICE_SYSTEMD", result["error_code"])
            self.assertEqual(previous_release, current.resolve())
            self.assertFalse((install_root / "desired.yaml").exists())

    def test_apply_desired_already_applied_does_not_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            node = build_node_catalog(release)[0]
            desired = select_node(release, root / "runtime", node.node_id, "production")
            install_root = root / "install"
            target_release = install_root / "releases" / "000001"
            shutil.copytree(release, target_release)
            (install_root / "current").symlink_to(target_release)
            (install_root / "desired.yaml").write_text(json.dumps(desired), encoding="utf-8")

            module = self._module()
            module._api = lambda api, secret, method, path, body, **kwargs: {"all": [node.mihomo_name], "now": node.mihomo_name}
            with mock.patch.object(module, "_reload_or_restart") as reload_or_restart:
                result = module.apply_desired(
                    release_root=str(root / "salt" / "releases"),
                    desired_path=str(root / "runtime" / "desired.yaml"),
                    install_root=str(install_root),
                    operation_id="op-test",
                )

            self.assertEqual("success", result["status"])
            self.assertEqual("already-applied", result["message"])
            reload_or_restart.assert_not_called()

    def test_apply_desired_same_release_switch_only_does_not_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            node = build_node_catalog(release)[0]
            desired = select_node(release, root / "runtime", node.node_id, "production")
            install_root = root / "install"
            target_release = install_root / "releases" / "000001"
            shutil.copytree(release, target_release)
            (install_root / "current").symlink_to(target_release)
            (install_root / "desired.yaml").write_text('{"selected_node_id":"old"}\n', encoding="utf-8")
            calls = []

            module = self._module()
            module._wait_mihomo_node = lambda api, secret, group, name: calls.append(("wait", name))
            module._select_mihomo = lambda api, secret, group, name: calls.append(("select", name)) or True
            with mock.patch.object(module, "_reload_or_restart") as reload_or_restart:
                result = module.apply_desired(
                    release_root=str(root / "salt" / "releases"),
                    desired_path=str(root / "runtime" / "desired.yaml"),
                    install_root=str(install_root),
                    operation_id="op-test",
                )

            self.assertEqual("success", result["status"])
            self.assertEqual("switched", result["message"])
            self.assertTrue(result["evidence"]["switch_only"])
            self.assertEqual([("wait", node.mihomo_name), ("select", node.mihomo_name)], calls)
            reload_or_restart.assert_not_called()
            self.assertEqual(desired["selected_node_id"], json.loads((install_root / "desired.yaml").read_text(encoding="utf-8"))["selected_node_id"])

    def test_apply_switch_changes_selection_without_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            node = build_node_catalog(release)[0]
            desired = select_node(release, root / "runtime", node.node_id, "production")
            install_root = root / "install"
            managed_release = install_root / "managed" / "releases" / "000001"
            active_release = install_root / "releases" / "000001"
            shutil.copytree(release, managed_release)
            shutil.copytree(release, active_release)
            (install_root / "current").symlink_to(active_release)
            locks, binary = _installed_mihomo_fixture(root)
            calls = []

            module = self._module()
            module._api = lambda api, secret, method, path, body, **kwargs: {"all": [node.mihomo_name], "now": "DIRECT"}
            module._select_mihomo = lambda api, secret, group, name: calls.append(("select", name)) or True
            with mock.patch.object(module, "_reload_or_restart") as reload_or_restart:
                result = module.apply_switch(
                    desired_json=json.dumps(desired),
                    install_root=str(install_root),
                    component_locks_path=str(locks),
                    binary_path=str(binary),
                    operation_id="op-test",
                )

            self.assertEqual("success", result["status"])
            self.assertEqual([("select", node.mihomo_name)], calls)
            reload_or_restart.assert_not_called()
            self.assertTrue((install_root / "managed" / "desired.yaml").exists())
            self.assertTrue((install_root / "desired.yaml").exists())

    def test_apply_switch_fails_when_component_receipt_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            node = build_node_catalog(release)[0]
            desired = select_node(release, root / "runtime", node.node_id, "production")
            install_root = root / "install"
            shutil.copytree(release, install_root / "managed" / "releases" / "000001")
            shutil.copytree(release, install_root / "releases" / "000001")
            (install_root / "current").symlink_to(install_root / "releases" / "000001")
            locks, binary = _installed_mihomo_fixture(root)
            binary.with_name(binary.name + ".proxyfleet-install.json").write_text("{}", encoding="utf-8")

            module = self._module()
            module._api = lambda api, secret, method, path, body, **kwargs: {"all": [node.mihomo_name], "now": "DIRECT"}
            result = module.apply_switch(
                desired_json=json.dumps(desired),
                install_root=str(install_root),
                component_locks_path=str(locks),
                binary_path=str(binary),
                operation_id="op-test",
            )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_SWITCH_NEEDS_CONVERGE", result["error_code"])

    def test_sync_status_classifies_ready_old_and_new_minion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            install_root = root / "install"
            install_root.mkdir()
            locks, binary = _installed_mihomo_fixture(root)
            service = root / "mihomo.service"
            service.write_text("[Service]\n", encoding="utf-8")
            shutil.copy2(locks, install_root / "component-locks.json")
            managed_release = install_root / "managed" / "releases" / "000001"
            active_release = install_root / "releases" / "000001"
            shutil.copytree(release, managed_release)
            shutil.copytree(release, active_release)
            (install_root / "current").symlink_to(active_release)

            module = self._module()
            ready = module.sync_status(
                expected_release_revision=1,
                expected_component_locks_sha256=hashlib.sha256(locks.read_bytes()).hexdigest(),
                install_root=str(install_root),
                component_locks_path=str(locks),
                binary_path=str(binary),
                service_path=str(service),
            )
            new = module.sync_status(install_root=str(root / "missing"))

            self.assertEqual("ready-old", ready["classification"])
            self.assertEqual("new-minion", new["classification"])

    def test_sync_status_rejects_bad_component_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "salt" / "releases")
            install_root = root / "install"
            install_root.mkdir()
            locks, binary = _installed_mihomo_fixture(root)
            binary.with_name(binary.name + ".proxyfleet-install.json").write_text("{}", encoding="utf-8")
            service = root / "mihomo.service"
            service.write_text("[Service]\n", encoding="utf-8")
            shutil.copy2(locks, install_root / "component-locks.json")
            shutil.copytree(release, install_root / "managed" / "releases" / "000001")
            shutil.copytree(release, install_root / "releases" / "000001")
            (install_root / "current").symlink_to(install_root / "releases" / "000001")

            module = self._module()
            status = module.sync_status(
                expected_release_revision=1,
                expected_component_locks_sha256=hashlib.sha256(locks.read_bytes()).hexdigest(),
                install_root=str(install_root),
                component_locks_path=str(locks),
                binary_path=str(binary),
                service_path=str(service),
            )

            self.assertEqual("drifted", status["classification"])
            self.assertIn("E_COMPONENT_HASH", status["reasons"])

    def test_install_mihomo_missing_sha_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            locks = root / "component-locks.json"
            locks.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "mihomo",
                                "version": "v1.19.27",
                                "source": "https://example.invalid/mihomo",
                                "integrity": {"sha256": None},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            module = self._module()
            result = module.install_mihomo(
                component_locks_path=str(locks),
                binary_path=str(root / "mihomo"),
                service_path=str(root / "mihomo.service"),
                operation_id="op-test",
            )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_COMPONENT_INTEGRITY_MISSING", result["error_code"])
            self.assertFalse((root / "mihomo").exists())

    def test_install_mihomo_fail_on_error_raises_for_salt_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            locks = root / "component-locks.json"
            locks.write_text(json.dumps({"components": [{"name": "mihomo", "version": "v1.19.27", "integrity": {"sha256": None}}]}), encoding="utf-8")
            module = self._module()

            with self.assertRaises(module.CommandExecutionError) as ctx:
                module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    operation_id="op-test",
                    fail_on_error=True,
                )

            self.assertIn("E_COMPONENT_INTEGRITY_MISSING", str(ctx.exception))

    def test_apply_desired_fail_on_error_raises_on_early_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            desired = root / "desired.yaml"
            desired.write_text(
                json.dumps(
                    {
                        "release_revision": 1,
                        "desired_revision": 1,
                        "selected_mihomo_name": "[SELF] test-node",
                        "managed_policy_group": "OTHER",
                    }
                ),
                encoding="utf-8",
            )
            module = self._module()

            with self.assertRaises(module.CommandExecutionError) as ctx:
                module.apply_desired(
                    release_root=str(root / "missing-releases"),
                    desired_path=str(desired),
                    install_root=str(root / "install"),
                    operation_id="op-test",
                    fail_on_error=True,
                )

            self.assertIn("E_SCHEMA_UNSUPPORTED", str(ctx.exception))

    def test_apply_port_policy_preserves_local_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed" / "port-policy.yaml"
            local = root / "local" / "port-policy.yaml"
            effective = root / "effective" / "port-policy.yaml"
            managed.parent.mkdir()
            local.parent.mkdir()
            managed.write_text(
                json.dumps({"owner": "master", "allow": [{"protocol": "tcp", "port": 22, "source": "192.168.1.0/24"}], "deny": []}),
                encoding="utf-8",
            )
            local_payload = json.dumps({"owner": "local", "allow": [{"protocol": "tcp", "port": 8080, "source": "any"}], "deny": []})
            local.write_text(local_payload, encoding="utf-8")
            module = self._module()

            result = module.apply_port_policy(
                managed_path=str(managed),
                local_path=str(local),
                effective_path=str(effective),
                mode="merge",
                operation_id="op-test",
            )

            self.assertEqual("success", result["status"])
            self.assertEqual(local_payload, local.read_text(encoding="utf-8"))
            data = json.loads(effective.read_text(encoding="utf-8"))
            self.assertEqual(["master", "local"], [rule["owner"] for rule in data["allow"]])

    def test_apply_port_policy_local_options_override_master_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed" / "port-policy.yaml"
            local = root / "local" / "port-policy.yaml"
            options = root / "local" / "options.json"
            effective = root / "effective" / "port-policy.yaml"
            managed.parent.mkdir()
            local.parent.mkdir()
            managed.write_text(
                json.dumps({"owner": "master", "allow": [{"protocol": "tcp", "port": 22, "source": "192.168.1.0/24"}], "deny": []}),
                encoding="utf-8",
            )
            local.write_text(
                json.dumps({"owner": "local", "allow": [{"protocol": "tcp", "port": 8080, "source": "any"}], "deny": []}),
                encoding="utf-8",
            )
            options.write_text(json.dumps({"schema_version": "1.0", "port_policy_mode": "local-only"}), encoding="utf-8")
            module = self._module()

            result = module.apply_port_policy(
                managed_path=str(managed),
                local_path=str(local),
                options_path=str(options),
                effective_path=str(effective),
                mode="master-only",
                operation_id="op-test",
            )

            self.assertEqual("success", result["status"])
            self.assertEqual("local-only", result["evidence"]["mode"])
            self.assertEqual("master-only", result["evidence"]["master_mode"])
            data = json.loads(effective.read_text(encoding="utf-8"))
            self.assertEqual([8080], [rule["port"] for rule in data["allow"]])

    def test_apply_port_policy_rejects_bad_local_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed" / "port-policy.yaml"
            local = root / "local" / "port-policy.yaml"
            options = root / "local" / "options.json"
            effective = root / "effective" / "port-policy.yaml"
            managed.parent.mkdir()
            local.parent.mkdir()
            managed.write_text(json.dumps({"owner": "master", "allow": [], "deny": []}), encoding="utf-8")
            local.write_text(json.dumps({"owner": "local", "allow": [], "deny": []}), encoding="utf-8")
            options.write_text(json.dumps({"schema_version": "1.0", "port_policy_mode": "bad"}), encoding="utf-8")
            module = self._module()

            result = module.apply_port_policy(
                managed_path=str(managed),
                local_path=str(local),
                options_path=str(options),
                effective_path=str(effective),
                mode="merge",
                operation_id="op-test",
            )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_PORT_POLICY_SCHEMA", result["error_code"])
            self.assertFalse(effective.exists())

    def test_apply_port_policy_rejects_bad_schema_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed = root / "managed" / "port-policy.yaml"
            local = root / "local" / "port-policy.yaml"
            effective = root / "effective" / "port-policy.yaml"
            managed.parent.mkdir()
            local.parent.mkdir()
            managed.write_text(
                json.dumps({"schema_version": "2.0", "owner": "master", "allow": [{"protocol": "tcp", "port": 22, "source": "office"}], "deny": []}),
                encoding="utf-8",
            )
            local.write_text(json.dumps({"owner": "local", "allow": [], "deny": []}), encoding="utf-8")
            module = self._module()

            result = module.apply_port_policy(
                managed_path=str(managed),
                local_path=str(local),
                effective_path=str(effective),
                mode="merge",
                operation_id="op-test",
            )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_PORT_POLICY_SCHEMA", result["error_code"])
            self.assertFalse(effective.exists())

    def test_mihomo_artifact_selects_highest_supported_amd64_variant(self):
        module = self._module()
        component = {
            "artifacts": {
                "linux-amd64-compatible": {"url": "file:///compatible", "sha256": "0" * 64},
                "linux-amd64-v1": {"url": "file:///v1", "sha256": "1" * 64},
                "linux-amd64-v2": {"url": "file:///v2", "sha256": "2" * 64},
                "linux-amd64-v3": {"url": "file:///v3", "sha256": "3" * 64},
            }
        }
        v3_flags = {
            "avx",
            "avx2",
            "bmi1",
            "bmi2",
            "f16c",
            "fma",
            "abm",
            "movbe",
            "xsave",
            "cx16",
            "lahf_lm",
            "popcnt",
            "sse3",
            "ssse3",
            "sse4_1",
            "sse4_2",
        }

        with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(module, "_cpu_flags", return_value=v3_flags):
            artifact = module._component_artifact(component)

        self.assertEqual("file:///v3", artifact["url"])

    def test_mihomo_artifact_selects_v2_or_v1_or_compatible(self):
        module = self._module()
        v2_flags = {"cx16", "lahf_lm", "popcnt", "sse3", "ssse3", "sse4_1", "sse4_2"}
        component = {
            "artifacts": {
                "linux-amd64-compatible": {"url": "file:///compatible", "sha256": "0" * 64},
                "linux-amd64-v1": {"url": "file:///v1", "sha256": "1" * 64},
                "linux-amd64-v2": {"url": "file:///v2", "sha256": "2" * 64},
            }
        }

        with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(module, "_cpu_flags", return_value=v2_flags):
            self.assertEqual("file:///v2", module._component_artifact(component)["url"])
        with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(module, "_cpu_flags", return_value=set()):
            self.assertEqual("file:///v1", module._component_artifact(component)["url"])

        component = {"artifacts": {"linux-amd64-compatible": {"url": "file:///compatible", "sha256": "0" * 64}}}
        with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(module, "_cpu_flags", return_value=set()):
            self.assertEqual("file:///compatible", module._component_artifact(component)["url"])

    def test_install_mihomo_gzip_artifact_with_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "mihomo.gz"
            with gzip.open(asset, "wb") as fh:
                fh.write(b"#!/bin/sh\necho 'Mihomo Meta v1.19.27'\n")
            asset_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
            locks = root / "component-locks.json"
            locks.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "mihomo",
                                "version": "v1.19.27",
                                "artifacts": {
                                    "linux-amd64": {
                                        "url": asset.as_uri(),
                                        "sha256": asset_sha,
                                        "compression": "gzip",
                                        "target_path": str(root / "mihomo"),
                                    }
                                },
                                "integrity": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            module = self._module()
            with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(module, "_systemctl") as systemctl:
                result = module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    operation_id="op-test",
                )

            self.assertEqual("success", result["status"])
            systemctl.assert_called_once_with(["daemon-reload"])
            self.assertTrue((root / "mihomo").exists())
            self.assertTrue((root / "mihomo").stat().st_mode & 0o111)
            unit_text = (root / "mihomo.service").read_text(encoding="utf-8")
            self.assertIn("WorkingDirectory=/etc/proxyfleet/current", unit_text)
            self.assertIn(f"ExecStart={root / 'mihomo'} -d /etc/proxyfleet/current -f /etc/proxyfleet/current/config.yaml", unit_text)

    def test_install_mihomo_skips_daemon_reload_when_unit_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "mihomo.gz"
            with gzip.open(asset, "wb") as fh:
                fh.write(b"#!/bin/sh\necho 'Mihomo Meta v1.19.27'\n")
            asset_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
            locks = root / "component-locks.json"
            locks.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "mihomo",
                                "version": "v1.19.27",
                                "artifacts": {
                                    "linux-amd64": {
                                        "url": asset.as_uri(),
                                        "sha256": asset_sha,
                                        "compression": "gzip",
                                        "target_path": str(root / "mihomo"),
                                    }
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            module = self._module()
            with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(module, "_systemctl") as systemctl:
                first = module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    operation_id="op-test",
                )
                second = module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    operation_id="op-test",
                )

            self.assertEqual("success", first["status"])
            self.assertEqual("success", second["status"])
            self.assertTrue(first["evidence"]["unit_changed"])
            self.assertFalse(second["evidence"]["unit_changed"])
            systemctl.assert_called_once_with(["daemon-reload"])

    def test_install_mihomo_uses_offline_local_asset_before_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "offline-mihomo.gz"
            with gzip.open(asset, "wb") as fh:
                fh.write(b"#!/bin/sh\necho 'Mihomo Meta v1.19.27'\n")
            asset_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
            locks = root / "component-locks.json"
            locks.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "mihomo",
                                "version": "v1.19.27",
                                "artifacts": {
                                    "linux-amd64": {
                                        "local_path": str(asset),
                                        "url": "https://example.invalid/mihomo.gz",
                                        "sha256": asset_sha,
                                        "compression": "gzip",
                                        "target_path": str(root / "mihomo"),
                                    }
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            module = self._module()
            with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(module, "_systemctl"):
                result = module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    operation_id="op-test",
                )

            self.assertEqual("success", result["status"])
            receipt = json.loads((root / "mihomo.proxyfleet-install.json").read_text(encoding="utf-8"))
            self.assertTrue(receipt["source"].startswith("file://"))
            receipt = json.loads((root / "mihomo.proxyfleet-install.json").read_text(encoding="utf-8"))
            self.assertEqual(asset_sha, receipt["artifact_sha256"])
            self.assertEqual("gzip", receipt["compression"])

    def test_install_mihomo_daemon_reload_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "mihomo.gz"
            with gzip.open(asset, "wb") as fh:
                fh.write(b"#!/bin/sh\necho 'Mihomo Meta v1.19.27'\n")
            asset_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
            locks = root / "component-locks.json"
            locks.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "mihomo",
                                "version": "v1.19.27",
                                "artifacts": {
                                    "linux-amd64": {
                                        "url": asset.as_uri(),
                                        "sha256": asset_sha,
                                        "compression": "gzip",
                                        "target_path": str(root / "mihomo"),
                                    }
                                },
                                "integrity": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            module = self._module()
            with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(
                module,
                "_systemctl",
                side_effect=module._ApplyError("E_SERVICE_SYSTEMD", "daemon reload failed"),
            ):
                result = module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    operation_id="op-test",
                )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_SERVICE_SYSTEMD", result["error_code"])

    def test_install_mihomo_target_path_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "mihomo.gz"
            with gzip.open(asset, "wb") as fh:
                fh.write(b"#!/bin/sh\necho 'Mihomo Meta v1.19.27'\n")
            asset_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
            locks = root / "component-locks.json"
            locks.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "mihomo",
                                "version": "v1.19.27",
                                "artifacts": {
                                    "linux-amd64": {
                                        "url": asset.as_uri(),
                                        "sha256": asset_sha,
                                        "compression": "gzip",
                                        "target_path": str(root / "locked-mihomo"),
                                    }
                                },
                                "integrity": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            module = self._module()
            with mock.patch.object(module.platform, "machine", return_value="x86_64"):
                result = module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    operation_id="op-test",
                )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_COMPONENT_TARGET", result["error_code"])

    def test_install_mihomo_version_probe_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "mihomo.gz"
            with gzip.open(asset, "wb") as fh:
                fh.write(b"#!/bin/sh\necho 'wrong version'\n")
            asset_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
            locks = root / "component-locks.json"
            locks.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "mihomo",
                                "version": "v1.19.27",
                                "artifacts": {
                                    "linux-amd64": {
                                        "url": asset.as_uri(),
                                        "sha256": asset_sha,
                                        "compression": "gzip",
                                    }
                                },
                                "integrity": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            module = self._module()
            with mock.patch.object(module.platform, "machine", return_value="x86_64"):
                result = module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    operation_id="op-test",
                )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_MIHOMO_VERSION", result["error_code"])
            self.assertFalse((root / "mihomo").exists())

    def test_select_mihomo_rolls_back_previous_on_verify_mismatch(self):
        module = self._module()
        calls = []
        states = [
            {"now": "[SELF] previous", "all": ["[SELF] previous", "[SELF] test-node"]},
            {"now": "[SELF] previous", "all": ["[SELF] previous", "[SELF] test-node"]},
            {"now": "[SELF] previous", "all": ["[SELF] previous", "[SELF] test-node"]},
        ]

        def fake_api(base_url, api_secret, method, path, body, timeout_error_code="E_LOCAL_API", request_timeout=3):
            calls.append((method, body))
            if method == "GET":
                return states.pop(0)
            return {}

        module._api = fake_api
        with self.assertRaises(module._ApplyError) as ctx:
            module._select_mihomo("http://127.0.0.1:9090", None, "FLEET_PROXY", "[SELF] test-node")

        self.assertEqual("E_SELECT_VERIFY", ctx.exception.error_code)
        self.assertEqual(("PUT", {"name": "[SELF] previous"}), calls[-2])

    def test_select_mihomo_skips_put_when_already_selected(self):
        module = self._module()
        calls = []

        def fake_api(base_url, api_secret, method, path, body, timeout_error_code="E_LOCAL_API", request_timeout=3):
            calls.append((method, body))
            return {"now": "[SELF] test-node", "all": ["[SELF] test-node"]}

        module._api = fake_api
        changed = module._select_mihomo("http://127.0.0.1:9090", None, "FLEET_PROXY", "[SELF] test-node")

        self.assertFalse(changed)
        self.assertEqual([("GET", None)], calls)

    def test_select_mihomo_reports_rollback_failure(self):
        module = self._module()
        calls = []
        states = [
            {"now": "[SELF] previous", "all": ["[SELF] previous", "[SELF] test-node"]},
            {"now": "[SELF] previous", "all": ["[SELF] previous", "[SELF] test-node"]},
            {"now": "[SELF] other", "all": ["[SELF] previous", "[SELF] test-node"]},
        ]

        def fake_api(base_url, api_secret, method, path, body, timeout_error_code="E_LOCAL_API", request_timeout=3):
            calls.append((method, body))
            if method == "GET":
                return states.pop(0)
            return {}

        module._api = fake_api
        with self.assertRaises(module._ApplyError) as ctx:
            module._select_mihomo("http://127.0.0.1:9090", None, "FLEET_PROXY", "[SELF] test-node")

        self.assertEqual("E_ROLLBACK_FAILED", ctx.exception.error_code)
        self.assertEqual(("PUT", {"name": "[SELF] previous"}), calls[-2])

    def test_salt_health_check_http_timeout_exceeds_delay_timeout(self):
        module = self._module()
        response = mock.Mock()
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=None)
        response.read.return_value = b'{"delay":123}'

        with mock.patch.object(module.request, "urlopen", return_value=response) as urlopen:
            result = module.health_check(
                "http://127.0.0.1:9090",
                mihomo_name="[SELF] test-node",
                timeout_ms=5000,
            )

        self.assertEqual("success", result["status"])
        self.assertEqual(7.0, urlopen.call_args.kwargs["timeout"])

    def test_salt_api_rejects_non_loopback_base_url(self):
        module = self._module()
        with self.assertRaises(module._ApplyError) as ctx:
            module._api("http://192.168.1.1:9090", None, "GET", "/proxies/FLEET_PROXY", None)
        self.assertEqual("E_LOCAL_API", ctx.exception.error_code)

    def test_native_mihomo_local_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _release(root / "releases")
            node = build_node_catalog(release)[0]
            desired = select_node(release, root / "runtime", node.node_id, "production")
            prepare_salt_publish(release, root / "runtime" / "desired.yaml", root / "srv-salt", LOCKS)

            asset = root / "mihomo.gz"
            with gzip.open(asset, "wb") as fh:
                fh.write(b"#!/bin/sh\necho 'Mihomo Meta v1.19.27'\n")
            asset_sha = hashlib.sha256(asset.read_bytes()).hexdigest()
            locks = root / "component-locks.json"
            locks.write_text(
                json.dumps(
                    {
                        "components": [
                            {
                                "name": "mihomo",
                                "version": "v1.19.27",
                                "artifacts": {
                                    "linux-amd64": {
                                        "url": asset.as_uri(),
                                        "sha256": asset_sha,
                                        "compression": "gzip",
                                    }
                                },
                                "integrity": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            module = self._module()
            order = []

            def fake_reload(service_name):
                order.append(("reload", service_name))

            def fake_select(api, secret, group, selected_name):
                order.append(("select", group, selected_name))

            def fake_wait(api, secret, group, selected_name):
                order.append(("wait", group, selected_name))

            with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(module, "_systemctl"):
                install = module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    config_path=str(root / "install" / "current" / "config.yaml"),
                    operation_id="op-install",
                )
            module._reload_or_restart = fake_reload
            module._wait_mihomo_node = fake_wait
            module._select_mihomo = fake_select
            apply = module.apply_desired(
                release_root=str(root / "srv-salt" / "proxyfleet" / "releases"),
                desired_path=str(root / "srv-salt" / "proxyfleet" / "desired.yaml"),
                install_root=str(root / "install"),
                operation_id="op-apply",
            )

            self.assertEqual("success", install["status"])
            self.assertEqual("success", apply["status"])
            self.assertTrue((root / "install" / "current" / "config.yaml").exists())
            self.assertEqual(("select", "FLEET_PROXY", desired["selected_mihomo_name"]), order[-1])


if __name__ == "__main__":
    unittest.main()
