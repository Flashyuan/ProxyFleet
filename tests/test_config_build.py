import json
import os
import shutil
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest import mock

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
            config = json.loads((release / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(7893, config["tproxy-port"])
            self.assertTrue(config["tun"]["enable"])
            self.assertTrue(config["tun"]["auto-route"])
            self.assertFalse(config["tun"]["auto-redirect"])
            self.assertIn("any:53", config["tun"]["dns-hijack"])
            self.assertIn("192.168.0.0/16", config["tun"]["route-exclude-address"])
            self.assertEqual([], config["dns"]["fallback"])
            self.assertFalse(config["dns"]["fallback-filter"]["geoip"])
            self.assertIn("IP-CIDR,10.0.0.0/8,DIRECT,no-resolve", config["rules"])
            self.assertIn("DOMAIN-SUFFIX,cluster.local,DIRECT", config["rules"])
            self.assertLess(config["rules"].index("IP-CIDR,10.0.0.0/8,DIRECT,no-resolve"), config["rules"].index("RULE-SET,force-proxy,FLEET_PROXY"))
            self.assertTrue((release / "manifest.sha256").exists())
            verify_release(release)

    def test_explicit_proxy_mode_does_not_inject_tun(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
            base_path = Path(src) / "base.json"
            base = json.loads(base_path.read_text(encoding="utf-8"))
            base["proxy_mode"] = "explicit-proxy"
            base_path.write_text(json.dumps(base, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

            release = build_release(
                BuildOptions(
                    source_dir=Path(src),
                    output_dir=Path(out),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )

            config = json.loads((release / "config.yaml").read_text(encoding="utf-8"))
            self.assertNotIn("tun", config)
            self.assertNotIn("tproxy-port", config)

    def test_tproxy_mode_overrides_disabled_tun_from_source(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
            base_path = Path(src) / "base.json"
            base = json.loads(base_path.read_text(encoding="utf-8"))
            base["tproxy-port"] = 0
            base["tun"] = {
                "enable": False,
                "stack": "gVisor",
                "auto-route": False,
                "auto-redirect": False,
                "auto-detect-interface": False,
                "strict-route": False,
                "dns-hijack": ["0.0.0.0:53"],
            }
            base_path.write_text(json.dumps(base, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

            release = build_release(
                BuildOptions(
                    source_dir=Path(src),
                    output_dir=Path(out),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )

            config = json.loads((release / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(7893, config["tproxy-port"])
            self.assertTrue(config["tun"]["enable"])
            self.assertEqual("system", config["tun"]["stack"])
            self.assertTrue(config["tun"]["auto-route"])
            self.assertFalse(config["tun"]["auto-redirect"])
            self.assertTrue(config["tun"]["auto-detect-interface"])
            self.assertFalse(config["tun"]["strict-route"])
            self.assertEqual(["any:53"], config["tun"]["dns-hijack"])
            self.assertIn("10.0.0.0/8", config["tun"]["route-exclude-address"])
            self.assertEqual([], config["dns"]["fallback"])
            self.assertEqual({"domain": [], "geoip": False, "ipcidr": []}, config["dns"]["fallback-filter"])

    def test_tproxy_custom_excludes_json_are_merged_and_deduped(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
            (Path(src) / "tproxy-excludes.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "route_exclude_address": ["10.96.0.0/12", "10.96.0.0/12"],
                        "direct_rules": ["IP-CIDR,10.96.0.0/12,DIRECT,no-resolve"],
                        "direct_domains": ["cluster.local", "svc.custom"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            release = build_release(
                BuildOptions(
                    source_dir=Path(src),
                    output_dir=Path(out),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )

            config = json.loads((release / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(1, config["tun"]["route-exclude-address"].count("10.96.0.0/12"))
            self.assertIn("IP-CIDR,10.96.0.0/12,DIRECT,no-resolve", config["rules"])
            self.assertIn("DOMAIN-SUFFIX,svc.custom,DIRECT", config["rules"])
            self.assertEqual(1, config["rules"].count("DOMAIN-SUFFIX,cluster.local,DIRECT"))

    def test_tproxy_custom_excludes_yaml_are_merged_and_deduped(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
            (Path(src) / "tproxy-excludes.yaml").write_text(
                """
schema_version: "1.0"
route_exclude_address:
  - 10.244.0.0/16
direct_rules:
  - IP-CIDR,10.244.0.0/16,DIRECT,no-resolve
direct_domains:
  - pod.cluster.local
""".strip()
                + "\n",
                encoding="utf-8",
            )

            release = build_release(
                BuildOptions(
                    source_dir=Path(src),
                    output_dir=Path(out),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )

            config = json.loads((release / "config.yaml").read_text(encoding="utf-8"))
            self.assertIn("10.244.0.0/16", config["tun"]["route-exclude-address"])
            self.assertIn("IP-CIDR,10.244.0.0/16,DIRECT,no-resolve", config["rules"])
            self.assertIn("DOMAIN-SUFFIX,pod.cluster.local,DIRECT", config["rules"])

    def test_explicit_proxy_mode_preserves_source_tun_settings(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
            base_path = Path(src) / "base.json"
            base = json.loads(base_path.read_text(encoding="utf-8"))
            base["proxy_mode"] = "explicit-proxy"
            base["tproxy-port"] = 0
            base["tun"] = {"enable": False, "auto-route": False}
            base_path.write_text(json.dumps(base, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

            release = build_release(
                BuildOptions(
                    source_dir=Path(src),
                    output_dir=Path(out),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )

            config = json.loads((release / "config.yaml").read_text(encoding="utf-8"))
            self.assertNotEqual(7893, config.get("tproxy-port"))
            self.assertNotEqual(True, config.get("tun", {}).get("enable") if isinstance(config.get("tun"), dict) else None)

    def test_explicit_proxy_preserves_custom_direct_rules_without_forcing_tun(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
            base_path = Path(src) / "base.json"
            base = json.loads(base_path.read_text(encoding="utf-8"))
            base["proxy_mode"] = "explicit-proxy"
            base_path.write_text(json.dumps(base, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            (Path(src) / "tproxy-excludes.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "direct_rules": ["IP-CIDR,10.96.0.0/12,DIRECT,no-resolve"],
                        "direct_domains": ["cluster.local"],
                    }
                ),
                encoding="utf-8",
            )

            release = build_release(
                BuildOptions(
                    source_dir=Path(src),
                    output_dir=Path(out),
                    revision=1,
                    source_git_commit="abc123",
                    component_locks=LOCKS,
                )
            )

            config = json.loads((release / "config.yaml").read_text(encoding="utf-8"))
            self.assertNotIn("tun", config)
            self.assertNotIn("tproxy-port", config)
            self.assertIn("IP-CIDR,10.96.0.0/12,DIRECT,no-resolve", config["rules"])
            self.assertIn("DOMAIN-SUFFIX,cluster.local,DIRECT", config["rules"])

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

    def test_build_release_with_subscription_local_file_and_rules(self):
        body = json.dumps(
            {
                "proxies": [
                    {"name": "jp-01", "type": "socks5", "server": "127.0.0.1", "port": 1080}
                ]
            }
        ).encode("utf-8")
        with _subscription_server([(200, body, "upload=1; download=2; total=10")]) as url:
            with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
                shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
                source_dir = Path(src)
                providers = json.loads((source_dir / "providers.json").read_text(encoding="utf-8"))
                providers["providers"].append(
                    {
                        "enabled": True,
                        "id": "airport-main",
                        "kind": "subscription",
                        "name_prefix": "[A] ",
                        "output": "providers/airport-main.yaml",
                        "secret_ref": "AIRPORT_MAIN_URL",
                    }
                )
                (source_dir / "providers.json").write_text(json.dumps(providers), encoding="utf-8")
                groups = json.loads((source_dir / "groups.json").read_text(encoding="utf-8"))
                groups["groups"][0]["use"] = ["self-hosted", "airport-main"]
                (source_dir / "groups.json").write_text(json.dumps(groups), encoding="utf-8")

                with mock.patch.dict(os.environ, {"AIRPORT_MAIN_URL": url}):
                    release = build_release(
                        BuildOptions(
                            source_dir=source_dir,
                            output_dir=Path(out) / "releases",
                            revision=1,
                            source_git_commit="abc123",
                            component_locks=LOCKS,
                            cache_dir=Path(out) / "cache",
                        )
                    )

                config = json.loads((release / "config.yaml").read_text(encoding="utf-8"))
                self.assertEqual({"self-hosted", "airport-main"}, set(config["proxy-providers"].keys()))
                self.assertTrue((release / "providers" / "self-hosted.yaml").exists())
                provider = json.loads((release / "providers" / "airport-main.yaml").read_text(encoding="utf-8"))
                self.assertEqual("[A] jp-01", provider["proxies"][0]["name"])
                self.assertTrue((release / "rules" / "force-proxy.yaml").exists())
                status = json.loads((release / "subscription-status" / "airport-main.json").read_text(encoding="utf-8"))
                self.assertEqual("fresh", status["freshness"])

    def test_build_release_extracts_proxies_from_full_subscription_config(self):
        body = b"""
proxy-groups:
  - name: manual
    type: select
    proxies:
      - jp-01
rules:
  - MATCH,DIRECT
proxies:
  - name: jp-01
    type: socks5
    server: 127.0.0.1
    port: 1080
"""
        with _subscription_server([(200, body, "upload=1; download=2; total=10")]) as url:
            with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
                shutil.copytree(FIXTURE, src, dirs_exist_ok=True)
                source_dir = Path(src)
                providers = json.loads((source_dir / "providers.json").read_text(encoding="utf-8"))
                providers["providers"].append(
                    {
                        "enabled": True,
                        "id": "airport-main",
                        "kind": "subscription",
                        "name_prefix": "[A] ",
                        "output": "providers/airport-main.yaml",
                        "secret_ref": "AIRPORT_MAIN_URL",
                    }
                )
                (source_dir / "providers.json").write_text(json.dumps(providers), encoding="utf-8")
                groups = json.loads((source_dir / "groups.json").read_text(encoding="utf-8"))
                groups["groups"][0]["use"] = ["self-hosted", "airport-main"]
                (source_dir / "groups.json").write_text(json.dumps(groups), encoding="utf-8")

                with mock.patch.dict(os.environ, {"AIRPORT_MAIN_URL": url}):
                    release = build_release(
                        BuildOptions(
                            source_dir=source_dir,
                            output_dir=Path(out) / "releases",
                            revision=1,
                            source_git_commit="abc123",
                            component_locks=LOCKS,
                            cache_dir=Path(out) / "cache",
                        )
                    )

                provider = json.loads((release / "providers" / "airport-main.yaml").read_text(encoding="utf-8"))
                self.assertEqual("[A] jp-01", provider["proxies"][0]["name"])
                self.assertNotIn("proxy-groups", provider)

class _SubscriptionServer:
    def __init__(self, responses):
        self._responses = list(responses)
        responses_ref = self._responses

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if responses_ref:
                    status, body, userinfo = responses_ref.pop(0)
                else:
                    status, body, userinfo = 500, b"exhausted", None
                self.send_response(status)
                if userinfo is not None:
                    self.send_header("Subscription-Userinfo", userinfo)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A003
                return

        class Server(ThreadingHTTPServer):
            daemon_threads = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self._server.server_port}/sub"

    def __enter__(self):
        self._thread.start()
        return self.url

    def __exit__(self, exc_type, exc, tb):
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()


def _subscription_server(responses):
    return _SubscriptionServer(responses)


if __name__ == "__main__":
    unittest.main()
