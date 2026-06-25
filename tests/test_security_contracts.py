"""安全与发布契约的静态回归测试。"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SecurityContractTests(unittest.TestCase):
    def test_install_scripts_do_not_fetch_floating_salt_sources(self):
        for script in [
            ROOT / "scripts" / "proxyfleet-master.sh",
            ROOT / "scripts" / "proxyfleet-minion.sh",
        ]:
            text = script.read_text(encoding="utf-8")
            self.assertNotIn("releases/latest/download/salt.sources", text)
            self.assertIn("https://packages.broadcom.com/artifactory/saltproject-deb", text)

    def test_minion_install_restarts_after_writing_proxyfleet_config(self):
        text = (ROOT / "scripts" / "proxyfleet-minion.sh").read_text(encoding="utf-8")
        self.assertIn("systemctl stop salt-minion || true", text)
        self.assertIn("systemctl restart salt-minion", text)
        self.assertNotIn("systemctl enable --now salt-minion", text)

    def test_master_script_can_refresh_health_before_select_sync(self):
        text = (ROOT / "scripts" / "proxyfleet-master.sh").read_text(encoding="utf-8")
        self.assertIn("refresh_health()", text)
        self.assertIn("--refresh-health", text)
        self.assertIn("health_cache_has_useful_result", text)
        self.assertIn("--progress", text)
        self.assertIn("--concurrency", text)
        self.assertIn('local health_timeout_ms="2000"', text)

    def test_proxyfleet_sync_sls_has_unique_state_ids(self):
        text = (ROOT / "salt" / "states" / "proxyfleet" / "sync.sls").read_text(encoding="utf-8")
        state_ids = []
        for line in text.splitlines():
            if line and not line.startswith((" ", "#")) and line.endswith(":"):
                state_ids.append(line[:-1])
        self.assertEqual(len(state_ids), len(set(state_ids)))
        self.assertEqual(1, state_ids.count("proxyfleet-install-mihomo"))

    def test_healthcheck_url_allowlist_is_exact(self):
        fleet_text = (ROOT / "src" / "proxyfleet" / "fleet.py").read_text(encoding="utf-8")
        salt_text = (ROOT / "salt" / "modules" / "proxyfleet_mihomo.py").read_text(encoding="utf-8")
        for text in [fleet_text, salt_text]:
            self.assertIn('parsed.netloc == "www.gstatic.com"', text)
            self.assertIn('parsed.path == "/generate_204"', text)
            self.assertIn("not parsed.query", text)

    def test_apply_desired_is_gated_by_port_policy_when_enabled(self):
        text = (ROOT / "salt" / "states" / "proxyfleet" / "sync.sls").read_text(encoding="utf-8")
        self.assertIn("proxyfleet-effective-port-policy:", text)
        self.assertIn("- module: proxyfleet-effective-port-policy", text)
        self.assertEqual(3, text.count("- fail_on_error: true"))

    def test_sync_state_uses_minion_local_managed_release_paths(self):
        text = (ROOT / "salt" / "states" / "proxyfleet" / "sync.sls").read_text(encoding="utf-8")
        self.assertIn("proxyfleet-managed-releases:", text)
        self.assertIn("source: salt://proxyfleet/releases", text)
        self.assertIn("name: /etc/proxyfleet/managed/desired.yaml", text)
        self.assertIn("release_root: /etc/proxyfleet/managed/releases", text)
        self.assertIn("desired_path: /etc/proxyfleet/managed/desired.yaml", text)
        self.assertNotIn("pillar.get('proxyfleet_release_root'", text)
        self.assertNotIn("pillar.get('proxyfleet_desired_path'", text)


if __name__ == "__main__":
    unittest.main()
