import json
import gzip
import hashlib
import importlib.util
import io
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
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
    salt_envelope,
    select_node,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "config-src"
LOCKS = ROOT / "component-locks.json"
SALT_MODULE = ROOT / "salt" / "modules" / "proxyfleet_mihomo.py"


def _release(tmp: Path):
    return build_release(BuildOptions(FIXTURE, tmp, 1, "abc123", LOCKS))


class FleetTests(unittest.TestCase):
    def test_build_node_catalog_from_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = _release(Path(tmp))
            catalog = build_node_catalog(release)
            self.assertEqual(1, len(catalog))
            self.assertTrue(catalog[0].node_id.startswith("node-"))
            self.assertEqual("[SELF] test-node", catalog[0].mihomo_name)
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
            plan = prepare_salt_publish(
                release,
                root / "runtime" / "desired.yaml",
                root / "srv-salt",
                LOCKS,
                port_policy,
                "merge",
            )
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "releases" / "000001" / "config.yaml").exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "desired.yaml").exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "component-locks.json").exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "port-policy.yaml").exists())
            self.assertEqual(1, plan.release_revision)
            self.assertEqual(1, plan.desired_revision)
            self.assertTrue(plan.port_policy_enabled)

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

    def test_health_check_missing_node_maps_error_code(self):
        with self.assertRaises(FleetError) as ctx:
            MihomoClient(self.base_url).health_check("missing-node", "https://www.gstatic.com/generate_204")
        self.assertEqual("E_NODE_NOT_FOUND", ctx.exception.error_code)

    def test_health_check_blocks_non_allowlisted_url(self):
        with self.assertRaises(FleetError) as ctx:
            MihomoClient(self.base_url).health_check("[SELF] test-node", "https://www.gstatic.com/generate_204?debug=1")
        self.assertEqual("E_HEALTHCHECK_TARGET_BLOCKED", ctx.exception.error_code)

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
            module._select_mihomo = lambda api, secret, group, name: order.append("select")
            result = module.apply_desired(
                release_root=str(root / "salt" / "releases"),
                desired_path=str(root / "runtime" / "desired.yaml"),
                install_root=str(install_root),
                operation_id="op-test",
            )

            self.assertEqual("success", result["status"])
            self.assertEqual(["reload", "select"], order)
            self.assertEqual(install_root / "releases" / "000001", (install_root / "current").resolve())
            self.assertTrue((install_root / "desired.yaml").exists())

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

        def fake_api(base_url, api_secret, method, path, body, timeout_error_code="E_LOCAL_API"):
            calls.append((method, body))
            if method == "GET":
                return states.pop(0)
            return {}

        module._api = fake_api
        with self.assertRaises(module._ApplyError) as ctx:
            module._select_mihomo("http://127.0.0.1:9090", None, "FLEET_PROXY", "[SELF] test-node")

        self.assertEqual("E_SELECT_VERIFY", ctx.exception.error_code)
        self.assertEqual(("PUT", {"name": "[SELF] previous"}), calls[-2])

    def test_select_mihomo_reports_rollback_failure(self):
        module = self._module()
        calls = []
        states = [
            {"now": "[SELF] previous", "all": ["[SELF] previous", "[SELF] test-node"]},
            {"now": "[SELF] previous", "all": ["[SELF] previous", "[SELF] test-node"]},
            {"now": "[SELF] other", "all": ["[SELF] previous", "[SELF] test-node"]},
        ]

        def fake_api(base_url, api_secret, method, path, body, timeout_error_code="E_LOCAL_API"):
            calls.append((method, body))
            if method == "GET":
                return states.pop(0)
            return {}

        module._api = fake_api
        with self.assertRaises(module._ApplyError) as ctx:
            module._select_mihomo("http://127.0.0.1:9090", None, "FLEET_PROXY", "[SELF] test-node")

        self.assertEqual("E_ROLLBACK_FAILED", ctx.exception.error_code)
        self.assertEqual(("PUT", {"name": "[SELF] previous"}), calls[-2])

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

            with mock.patch.object(module.platform, "machine", return_value="x86_64"), mock.patch.object(module, "_systemctl"):
                install = module.install_mihomo(
                    component_locks_path=str(locks),
                    binary_path=str(root / "mihomo"),
                    service_path=str(root / "mihomo.service"),
                    config_path=str(root / "install" / "current" / "config.yaml"),
                    operation_id="op-install",
                )
            module._reload_or_restart = fake_reload
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
