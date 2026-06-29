import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "proxyfleet-master.sh"


class MasterScriptTuiTests(unittest.TestCase):
    def _fakebin(self, root: Path) -> Path:
        fakebin = root / "fakebin"
        fakebin.mkdir(exist_ok=True)
        log = root / "commands.log"
        for name in ["systemctl", "apt-mark", "apt-get", "salt-key", "salt"]:
            (fakebin / name).write_text(
                f"#!/usr/bin/env bash\necho '{name} $*' >> {log}\nexit 0\n",
                encoding="utf-8",
            )
            (fakebin / name).chmod(0o755)
        return fakebin

    def _run(
        self,
        root: Path,
        args: list[str],
        user_input: str = "",
        allow_tui: bool = True,
        project_root: Path | None = None,
    ) -> subprocess.CompletedProcess:
        fakebin = self._fakebin(root)
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fakebin}:{env['PATH']}",
                "PROXYFLEET_TEST_ALLOW_NON_ROOT": "1",
                "PROJECT_ROOT": str(project_root or ROOT),
                "MASTER_CONF_DIR": str(root / "etc" / "salt" / "master.d"),
                "MASTER_PKI_DIR": str(root / "etc" / "salt" / "pki" / "master"),
                "SALT_STATES_ROOT": str(root / "srv" / "proxyfleet" / "salt" / "states"),
                "SALT_PILLAR_ROOT": str(root / "srv" / "proxyfleet" / "salt" / "pillar"),
                "SALT_SOURCES": str(root / "salt.sources"),
                "SALT_PIN": str(root / "salt.pin"),
                "SALT_KEYRING": str(root / "salt.keyring"),
                "MONITOR_POLICY_PATH": str(root / "runtime" / "health-monitor-policy.json"),
                "MONITOR_STATE_PATH": str(root / "runtime" / "health-monitor-state.json"),
                "MONITOR_EMAIL_CONFIG": str(root / "etc" / "proxyfleet" / "notify" / "email.json"),
                "SMTP_PASSWORD_FILE": str(root / "etc" / "proxyfleet" / "secrets" / "smtp-password"),
            }
        )
        if allow_tui:
            env["PROXYFLEET_TEST_ALLOW_NON_TTY"] = "1"
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=ROOT,
            env=env,
            input=user_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_no_args_enters_master_tui(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(Path(tmp), [], "q\n")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("ProxyFleet Master 主控台", result.stdout)
            self.assertIn("1) 安装相关", result.stdout)
            self.assertIn("2) Master 节点相关", result.stdout)
            self.assertIn("3) 节点配置相关", result.stdout)
            self.assertIn("4) 服务相关", result.stdout)
            self.assertNotIn("10) 配置端口白名单", result.stdout)
            self.assertNotIn("用法：scripts/proxyfleet-master.sh <command>", result.stdout)

    def test_master_install_menu_contains_update_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(Path(tmp), [], "1\nb\nq\n")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("检测并更新 ProxyFleet Master", result.stdout)

    def test_no_tty_master_fallback_shows_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(Path(tmp), [], allow_tui=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("E_TUI_UNAVAILABLE", result.stderr)
            self.assertIn("sudo scripts/proxyfleet-master.sh select-sync", result.stderr)

    def test_uninstall_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._run(root, ["uninstall"], "NO\n")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("已取消卸载", result.stderr)
            self.assertFalse((root / "commands.log").exists())

    def test_uninstall_removes_master_data_and_project_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            for path in [
                root / "etc" / "salt" / "master.d",
                root / "etc" / "salt" / "pki" / "master",
                root / "srv" / "proxyfleet" / "salt" / "states",
                root / "srv" / "proxyfleet" / "salt" / "pillar",
                project / "runtime",
                project / "releases",
                project / "config-src",
            ]:
                path.mkdir(parents=True, exist_ok=True)
            (project / ".env.proxyfleet").parent.mkdir(parents=True, exist_ok=True)
            (project / ".env.proxyfleet").write_text("export X=y\n", encoding="utf-8")

            result = self._run(root, ["uninstall", "--yes"], project_root=project)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse((root / "etc" / "salt" / "master.d").exists())
            self.assertFalse((root / "etc" / "salt" / "pki" / "master").exists())
            self.assertFalse((root / "srv" / "proxyfleet" / "salt" / "states").exists())
            self.assertFalse((root / "srv" / "proxyfleet" / "salt" / "pillar").exists())
            self.assertFalse((project / "runtime").exists())
            self.assertFalse((project / "releases").exists())
            self.assertFalse((project / "config-src").exists())
            self.assertFalse((project / ".env.proxyfleet").exists())
            self.assertIn("未修改系统路由、DNS、防火墙", result.stdout)

    def test_port_policy_tui_writes_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            result = self._run(
                root,
                [],
                "3\n6\n7890, 9090 7891\n192.168.1.0/24\nWRITE\n\nb\nq\n",
                project_root=project,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            policy = project / "config-src" / "port-policy.yaml"
            self.assertTrue(policy.exists())
            text = policy.read_text(encoding="utf-8")
            self.assertIn('"port": 7890', text)
            self.assertIn('"port": 7891', text)
            self.assertIn('"port": 9090', text)
            self.assertIn('"source": "192.168.1.0/24"', text)
            self.assertIn("Salt Master 自身需要对 Minion 开放 TCP 4505/4506", result.stdout)

    def test_master_config_menu_contains_health_monitor_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(Path(tmp), [], "3\nb\nq\n")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("配置节点健康监控和邮件告警", result.stdout)

    def test_monitor_email_tui_writes_config_and_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (project / "src").symlink_to(ROOT / "src", target_is_directory=True)
            result = self._run(
                root,
                [],
                "3\n8\n2\nsmtp.example.com\n465\nY\nalert@example.com\nProxyFleet Alert <alert@example.com>\nadmin1@example.com,admin2@example.com\nsecret-token\nWRITE\n\nb\nb\nq\n",
                project_root=project,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            email_config = root / "etc" / "proxyfleet" / "notify" / "email.json"
            password_file = root / "etc" / "proxyfleet" / "secrets" / "smtp-password"
            self.assertTrue(email_config.exists())
            self.assertTrue(password_file.exists())
            config = json.loads(email_config.read_text(encoding="utf-8"))
            self.assertEqual(["admin1@example.com", "admin2@example.com"], config["profiles"]["default"]["recipients"])
            self.assertEqual(0o600, password_file.stat().st_mode & 0o777)
            self.assertIn("配置邮件告警发件人和收件人", result.stdout)

    def test_monitor_email_tui_does_not_pass_password_as_argument(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("--password-stdin", text)
        self.assertNotIn("--password \"${password}\"", text)

    def test_monitor_tui_contains_auto_switch_toggle(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(Path(tmp), [], "3\n8\nb\nb\nq\n")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("启用自动切换", result.stdout)
            self.assertIn("关闭自动切换", result.stdout)

    def test_select_sync_calls_manual_switch_notification_after_success(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("manual_switch_notify()", text)
        self.assertIn('manual_switch_notify "${selected_node_id}" "${selected_name}" "${target}"', text)
        self.assertIn("monitor notify-manual-switch", text)

    def test_quick_subscription_tui_generates_config_and_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (project / "src").symlink_to(ROOT / "src", target_is_directory=True)
            (project / "component-locks.json").write_text((ROOT / "component-locks.json").read_text(encoding="utf-8"), encoding="utf-8")
            subscription = root / "subscription.json"
            subscription.write_text(
                json.dumps(
                    {
                        "proxies": [
                            {
                                "name": "A01",
                                "type": "socks5",
                                "server": "127.0.0.1",
                                "port": 1080,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = self._run(
                root,
                [],
                f"3\n1\nairport-main\n{subscription.as_uri()}\nWRITE\n\nb\nq\n",
                project_root=project,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((project / ".env.proxyfleet").exists())
            providers = json.loads((project / "config-src" / "providers.json").read_text(encoding="utf-8"))
            groups = json.loads((project / "config-src" / "groups.json").read_text(encoding="utf-8"))
            rules = json.loads((project / "config-src" / "rules.json").read_text(encoding="utf-8"))
            self.assertEqual("airport-main", providers["providers"][0]["id"])
            self.assertEqual(["airport-main"], groups["groups"][0]["use"])
            self.assertEqual("FLEET_PROXY", rules["order"][0]["target"])
            release_provider = project / "releases" / "000001" / "providers" / "airport-main.yaml"
            self.assertTrue(release_provider.exists())
            self.assertIn("[airport-main] A01", release_provider.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
