import json
import importlib.util
import io
import tempfile
import threading
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
            plan = prepare_salt_publish(release, root / "runtime" / "desired.yaml", root / "srv-salt")
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "releases" / "000001" / "config.yaml").exists())
            self.assertTrue((root / "srv-salt" / "proxyfleet" / "desired.yaml").exists())
            self.assertEqual(1, plan.release_revision)
            self.assertEqual(1, plan.desired_revision)

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
            plan = build_sync_plan(release, root / "runtime" / "desired.yaml", root / "custom-salt", "minion-1")
            with mock.patch("proxyfleet.fleet.subprocess.run") as run:
                run.return_value.returncode = 0
                self.assertEqual(0, run_salt_sync(plan, "salt"))
            cmd = run.call_args.args[0]
            self.assertIn("minion-1", cmd)
            pillar = next(item for item in cmd if item.startswith("pillar="))
            self.assertIn(str(root / "custom-salt" / "proxyfleet" / "releases"), pillar)
            self.assertIn(str(root / "custom-salt" / "proxyfleet" / "desired.yaml"), pillar)

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
    calls = []

    def do_GET(self):
        self.__class__.calls.append(("GET", self.path))
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
        MihomoHandler.calls = []
        self.server = HTTPServer(("127.0.0.1", 0), MihomoHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def test_select_node_puts_then_gets_to_verify(self):
        result = MihomoClient(self.base_url).select_node("FLEET_PROXY", "[SELF] test-node")
        self.assertEqual("success", result["status"])
        self.assertEqual([("GET", "/proxies/FLEET_PROXY"), ("PUT", "/proxies/FLEET_PROXY"), ("GET", "/proxies/FLEET_PROXY")], MihomoHandler.calls)

    def test_select_node_detects_verify_mismatch(self):
        MihomoHandler.inconsistent = True
        with self.assertRaisesRegex(FleetError, "回读结果不一致"):
            MihomoClient(self.base_url).select_node("FLEET_PROXY", "[SELF] test-node")

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
                raise module._ApplyError("E_LOCAL_API", "mihomo reload-or-restart failed")

            module._reload_or_restart = fail_reload
            result = module.apply_desired(
                release_root=str(root / "salt" / "releases"),
                desired_path=str(root / "runtime" / "desired.yaml"),
                install_root=str(install_root),
                operation_id="op-test",
            )

            self.assertEqual("failed", result["status"])
            self.assertEqual("E_LOCAL_API", result["error_code"])
            self.assertEqual(previous_release, current.resolve())
            self.assertFalse((install_root / "desired.yaml").exists())


if __name__ == "__main__":
    unittest.main()
