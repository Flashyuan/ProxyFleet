import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from proxyfleet.config_build import BuildOptions, build_release
from proxyfleet.fleet import build_node_catalog, select_node
from proxyfleet.health_monitor import (
    HealthMonitorError,
    MonitorPaths,
    choose_auto_switch_candidate,
    configure_email_profile,
    default_policy,
    evaluate_current_node,
    monitor_once,
    set_auto_switch,
    write_smtp_password,
)


ROOT = Path(__file__).resolve().parents[1]
LOCKS = ROOT / "component-locks.json"


def _multi_release(root: Path) -> Path:
    source = root / "config-src"
    source.mkdir()
    (source / "base.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "port": 7890,
                "socks-port": 7891,
                "external-controller": "127.0.0.1:9090",
                "mode": "rule",
            }
        ),
        encoding="utf-8",
    )
    (source / "providers.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "providers": [
                    {
                        "id": "self-hosted",
                        "kind": "local_file",
                        "source": "provider-self-hosted.json",
                        "output": "providers/self-hosted.yaml",
                        "name_prefix": "",
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (source / "groups.json").write_text(
        json.dumps({"schema_version": "1.0", "groups": [{"name": "FLEET_PROXY", "type": "select", "use": ["self-hosted"]}]}),
        encoding="utf-8",
    )
    (source / "rules.json").write_text(
        json.dumps({"schema_version": "1.0", "order": [{"match": "MATCH", "target": "FLEET_PROXY"}]}),
        encoding="utf-8",
    )
    (source / "provider-self-hosted.json").write_text(
        json.dumps(
            {
                "proxies": [
                    {"name": "日本 A01", "type": "socks5", "server": "127.0.0.1", "port": 1081},
                    {"name": "日本 A02", "type": "socks5", "server": "127.0.0.2", "port": 1082},
                    {"name": "香港 HK01", "type": "socks5", "server": "127.0.0.3", "port": 1083},
                    {"name": "新加坡 SG01", "type": "socks5", "server": "127.0.0.4", "port": 1084},
                ]
            }
        ),
        encoding="utf-8",
    )
    return build_release(BuildOptions(source, root / "releases", 1, "abc123", LOCKS))


class HealthMonitorTests(unittest.TestCase):
    def test_evaluate_scores_four_probe_dimensions(self):
        policy = default_policy()
        with mock.patch("proxyfleet.health_monitor._probe_mihomo_delay", return_value={"ok": True, "delay_ms": 100, "error_code": None}), \
            mock.patch("proxyfleet.health_monitor._probe_http_category", side_effect=[
                {"ok": True, "http_status": 200, "error_code": None},
                {"ok": True, "http_status": 204, "error_code": None},
                {"ok": False, "http_status": None, "error_code": "E_PROBE_TIMEOUT"},
            ]):
            result = evaluate_current_node("日本 A01", policy, mihomo_api="http://127.0.0.1:9090")

        self.assertEqual(3, result["score"])
        self.assertEqual("degraded", result["status"])

    def test_single_bad_round_only_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _multi_release(root)
            nodes = build_node_catalog(release)
            select_node(release, root / "runtime", nodes[0].node_id, "production")
            policy_path = root / "policy.json"
            state_path = root / "state.json"
            policy = default_policy()
            policy_path.write_text(json.dumps(policy), encoding="utf-8")

            with mock.patch("proxyfleet.health_monitor.evaluate_current_node", return_value={"score": 0, "status": "suspect_failed", "last_error_code": "E_PROBE_TIMEOUT"}):
                payload = monitor_once(
                    release_dir=release,
                    runtime_dir=root / "runtime",
                    paths=MonitorPaths(policy_path, state_path),
                    mihomo_api="http://127.0.0.1:9090",
                    dry_run=True,
                    send_email=False,
                )

            self.assertEqual("DEGRADED", payload["status"])
            self.assertEqual("observe", payload["action"]["type"])

    def test_three_bad_rounds_enters_waiting_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _multi_release(root)
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            policy_path = root / "policy.json"
            state_path = root / "state.json"
            policy_path.write_text(json.dumps(default_policy()), encoding="utf-8")
            bad = {"score": 0, "status": "suspect_failed", "last_error_code": "E_PROBE_TIMEOUT"}

            with mock.patch("proxyfleet.health_monitor.evaluate_current_node", return_value=bad):
                for _ in range(3):
                    payload = monitor_once(
                        release_dir=release,
                        runtime_dir=root / "runtime",
                        paths=MonitorPaths(policy_path, state_path),
                        mihomo_api="http://127.0.0.1:9090",
                        dry_run=True,
                        send_email=False,
                    )

            self.assertEqual("WAITING_ADMIN", payload["status"])
            self.assertEqual("alert_waiting_admin", payload["action"]["type"])
            self.assertIn("auto_switch_after", payload["state"])

    def test_waiting_window_blocks_auto_switch_until_600_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = _multi_release(root)
            node = build_node_catalog(release)[0]
            select_node(release, root / "runtime", node.node_id, "production")
            policy_path = root / "policy.json"
            state_path = root / "state.json"
            policy = default_policy()
            policy["auto_switch_enabled"] = True
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            start = datetime(2026, 6, 26, 0, 0, tzinfo=timezone.utc)
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "WAITING_ADMIN",
                        "selected_node_id": node.node_id,
                        "selected_mihomo_name": node.mihomo_name,
                        "bad_rounds": 3,
                        "alert_sent_at": start.isoformat().replace("+00:00", "Z"),
                        "auto_switch_after": (start + timedelta(seconds=600)).isoformat().replace("+00:00", "Z"),
                    }
                ),
                encoding="utf-8",
            )
            bad = {"score": 0, "status": "suspect_failed", "last_error_code": "E_PROBE_TIMEOUT"}

            with mock.patch("proxyfleet.health_monitor.evaluate_current_node", return_value=bad):
                payload = monitor_once(
                    release_dir=release,
                    runtime_dir=root / "runtime",
                    paths=MonitorPaths(policy_path, state_path),
                    mihomo_api="http://127.0.0.1:9090",
                    dry_run=True,
                    send_email=False,
                    now=start + timedelta(seconds=599),
                )

            self.assertEqual("waiting_admin", payload["action"]["type"])

    def test_blacklist_excludes_hong_kong_and_prefers_same_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = _multi_release(Path(tmp))
            nodes = build_node_catalog(release)
            current = next(node for node in nodes if node.mihomo_name == "日本 A01")

            decision = choose_auto_switch_candidate(nodes, current, default_policy())

            self.assertEqual("same_region", decision["reason"])
            self.assertEqual("日本 A02", decision["selected"]["mihomo_name"])
            rejected = {item["mihomo_name"]: item["reason"] for item in decision["rejected"]}
            self.assertEqual("blacklisted", rejected["香港 HK01"])

    def test_email_profile_writes_multiple_recipients_and_redacts_password_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            password_file = root / "smtp-password"
            write_smtp_password(password_file, "secret-token")
            payload = configure_email_profile(
                root / "email.json",
                smtp_host="smtp.example.com",
                smtp_port=465,
                smtp_tls=True,
                username="alert@example.com",
                password_file=password_file,
                sender="ProxyFleet Alert <alert@example.com>",
                recipients=["admin1@example.com,admin2@example.com"],
            )

            self.assertEqual(["admin1@example.com", "admin2@example.com"], payload["profiles"]["default"]["recipients"])
            self.assertEqual("<redacted>", payload["profiles"]["default"]["password_file"])
            self.assertEqual(0o600, os.stat(password_file).st_mode & 0o777)

    def test_auto_switch_is_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"

            disabled = set_auto_switch(path, False)
            enabled = set_auto_switch(path, True)

            self.assertFalse(disabled["auto_switch_enabled"])
            self.assertTrue(enabled["auto_switch_enabled"])

    def test_password_file_rejects_group_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            email = root / "email.json"
            password_file = root / "smtp-password"
            password_file.write_text("secret\n", encoding="utf-8")
            password_file.chmod(0o644)
            configure_email_profile(
                email,
                smtp_host="smtp.example.com",
                smtp_port=465,
                smtp_tls=True,
                username="alert@example.com",
                password_file=password_file,
                sender="ProxyFleet Alert <alert@example.com>",
                recipients=["admin@example.com"],
            )

            with self.assertRaises(HealthMonitorError) as ctx:
                from proxyfleet.health_monitor import send_email_event

                send_email_event(email, "default", "test", {"event_type": "x"})
            self.assertEqual("E_NOTIFY_CONFIG", ctx.exception.error_code)


if __name__ == "__main__":
    unittest.main()
