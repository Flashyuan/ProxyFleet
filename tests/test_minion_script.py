import os
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "proxyfleet-minion.sh"


class MinionScriptMihomoLifecycleTests(unittest.TestCase):
    def _fakebin(self, root: Path) -> Path:
        fakebin = root / "fakebin"
        fakebin.mkdir(exist_ok=True)
        log = root / "systemctl.log"
        (fakebin / "systemctl").write_text(
            f"""#!/usr/bin/env bash
echo "$*" >> {log}
if [[ "$1" == "cat" ]]; then
  cat "${{MIHOMO_UNIT_PATH}}"
  exit 0
fi
if [[ "$1" == "is-active" ]]; then
  exit 0
fi
exit 0
""",
            encoding="utf-8",
        )
        (fakebin / "systemctl").chmod(0o755)
        for name in ["apt-mark", "apt-get"]:
            (fakebin / name).write_text(
                f"#!/usr/bin/env bash\necho '{name} $*' >> {log}\nexit 0\n",
                encoding="utf-8",
            )
            (fakebin / name).chmod(0o755)
        return fakebin

    def _mihomo_tree(self, root: Path) -> dict[str, Path]:
        etc = root / "etc" / "proxyfleet"
        current = etc / "current"
        managed = etc / "managed"
        effective = etc / "effective"
        local = etc / "local"
        releases = etc / "releases"
        for path in [current, managed, effective, local, releases]:
            path.mkdir(parents=True)
        config = current / "config.yaml"
        config.write_text("mixed-port: 7890\n", encoding="utf-8")
        (local / "port-policy.yaml").write_text('{"owner":"local","allow":[],"deny":[]}\n', encoding="utf-8")
        (managed / "port-policy.yaml").write_text('{"owner":"master","allow":[],"deny":[]}\n', encoding="utf-8")
        (effective / "port-policy.yaml").write_text('{"owner":"effective","allow":[],"deny":[]}\n', encoding="utf-8")
        binary = root / "bin" / "mihomo"
        binary.parent.mkdir()
        binary.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$1\" == \"-t\" ]]; then exit 0; fi\n"
            "echo 'Mihomo Meta v1.19.27'\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        artifact_sha = "a" * 64
        binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
        receipt = binary.with_name(binary.name + ".proxyfleet-install.json")
        receipt.write_text(
            json.dumps(
                {
                    "component": "mihomo",
                    "version": "v1.19.27",
                    "artifact_sha256": artifact_sha,
                    "binary_sha256": binary_sha,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        locks = root / "component-locks.json"
        locks.write_text(
            '{"components":[{"name":"mihomo","version":"v1.19.27","artifacts":{"linux-amd64":{"target_path":"'
            + str(binary)
            + '","sha256":"'
            + artifact_sha
            + '","compression":"gzip"}}}]}\n',
            encoding="utf-8",
        )
        unit = root / "mihomo.service"
        unit.write_text(
            "[Unit]\n"
            "Description=ProxyFleet managed Mihomo\n"
            "[Service]\n"
            f"ExecStart={binary} -d {current} -f {config}\n",
            encoding="utf-8",
        )
        return {"etc": etc, "config": config, "binary": binary, "receipt": receipt, "locks": locks, "unit": unit}

    def _run(self, root: Path, args: list[str], tree: dict[str, Path] | None = None) -> subprocess.CompletedProcess:
        fakebin = self._fakebin(root)
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fakebin}:{env['PATH']}",
                "PROXYFLEET_TEST_ALLOW_NON_ROOT": "1",
                "MINION_CONF_DIR": str(root / "etc" / "salt" / "minion.d"),
                "MINION_PKI_DIR": str(root / "etc" / "salt" / "pki" / "minion"),
                "SALT_SOURCES": str(root / "salt.sources"),
                "SALT_PIN": str(root / "salt.pin"),
                "SALT_KEYRING": str(root / "salt.keyring"),
            }
        )
        if tree is not None:
            env.update(
                {
                    "PROXYFLEET_ETC_ROOT": str(tree["etc"]),
                    "MIHOMO_BINARY": str(tree["binary"]),
                    "MIHOMO_UNIT_PATH": str(tree["unit"]),
                    "MIHOMO_RECEIPT": str(tree["receipt"]),
                    "MIHOMO_CONFIG_PATH": str(tree["config"]),
                    "COMPONENT_LOCKS": str(tree["locks"]),
                    "SYSTEMD_UNIT_DIR": str(tree["unit"].parent),
                }
            )
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def _run_with_input(
        self,
        root: Path,
        args: list[str],
        user_input: str,
        tree: dict[str, Path] | None = None,
        allow_tui: bool = True,
    ) -> subprocess.CompletedProcess:
        fakebin = self._fakebin(root)
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fakebin}:{env['PATH']}",
                "PROXYFLEET_TEST_ALLOW_NON_ROOT": "1",
                "PROXYFLEET_ETC_ROOT": str(root / "etc" / "proxyfleet"),
                "MINION_CONF_DIR": str(root / "etc" / "salt" / "minion.d"),
                "MINION_PKI_DIR": str(root / "etc" / "salt" / "pki" / "minion"),
                "SALT_SOURCES": str(root / "salt.sources"),
                "SALT_PIN": str(root / "salt.pin"),
                "SALT_KEYRING": str(root / "salt.keyring"),
            }
        )
        if allow_tui:
            env["PROXYFLEET_TEST_ALLOW_NON_TTY"] = "1"
        if tree is not None:
            env.update(
                {
                    "MIHOMO_BINARY": str(tree["binary"]),
                    "MIHOMO_UNIT_PATH": str(tree["unit"]),
                    "MIHOMO_RECEIPT": str(tree["receipt"]),
                    "MIHOMO_CONFIG_PATH": str(tree["config"]),
                    "COMPONENT_LOCKS": str(tree["locks"]),
                }
            )
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

    def _systemctl_log(self, root: Path) -> list[str]:
        log = root / "systemctl.log"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def test_default_start_does_not_touch_mihomo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._run(root, ["start"])

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["start salt-minion"], self._systemctl_log(root))

    def test_minion_install_defaults_to_master_asset_mirror(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('ASSET_MIRROR_PORT="${ASSET_MIRROR_PORT:-48080}"', text)
        self.assertIn('local base_url="http://${master}:${ASSET_MIRROR_PORT}/proxyfleet"', text)
        self.assertIn('if install_salt_from_master_assets "${MASTER}"; then', text)
        self.assertIn("bootstrap-manifest.json", text)

    def test_no_args_enters_minion_tui(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._run_with_input(root, [], "q\n")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("ProxyFleet Minion 主控台", result.stdout)
            self.assertIn("检测并更新 ProxyFleet Minion", result.stdout)
            self.assertNotIn("用法：scripts/proxyfleet-minion.sh <command>", result.stdout)

    def test_no_tty_minion_fallback_shows_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._run_with_input(root, [], "", allow_tui=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("E_TUI_UNAVAILABLE", result.stderr)
            self.assertIn("install --master <master-ip> --id <minion-id>", result.stderr)

    def test_tui_writes_local_port_policy_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._run_with_input(root, [], "8\n3\nWRITE\n\nq\n")

            self.assertEqual(0, result.returncode, result.stderr)
            options = root / "etc" / "proxyfleet" / "local" / "options.json"
            self.assertTrue(options.exists())
            self.assertEqual("local-only", json.loads(options.read_text(encoding="utf-8"))["port_policy_mode"])

    def test_uninstall_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._run_with_input(root, ["uninstall"], "NO\n")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("已取消卸载", result.stderr)
            self.assertFalse((root / "systemctl.log").exists())

    def test_start_with_mihomo_starts_minion_then_mihomo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            result = self._run(root, ["start", "--with-mihomo"], tree)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                ["start salt-minion", "cat mihomo.service", "daemon-reload", "start mihomo.service", "is-active --quiet mihomo.service"],
                self._systemctl_log(root),
            )

    def test_non_proxyfleet_unit_fails_closed_before_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            tree["unit"].write_text("[Service]\nExecStart=/usr/bin/mihomo -f /tmp/config.yaml\n", encoding="utf-8")

            result = self._run(root, ["mihomo-stop"], tree)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(["cat mihomo.service"], self._systemctl_log(root))

    def test_mihomo_uninstall_default_removes_proxyfleet_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            result = self._run(root, ["mihomo-uninstall", "--yes"], tree)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(tree["unit"].exists())
            self.assertFalse(tree["binary"].exists())
            self.assertFalse(tree["receipt"].exists())
            self.assertFalse(tree["etc"].exists())

    def test_uninstall_default_removes_mihomo_and_minion_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            minion_conf = root / "etc" / "salt" / "minion.d"
            minion_pki = root / "etc" / "salt" / "pki" / "minion"
            minion_conf.mkdir(parents=True)
            minion_pki.mkdir(parents=True)
            result = self._run(root, ["uninstall", "--yes"], tree)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(tree["unit"].exists())
            self.assertFalse(tree["binary"].exists())
            self.assertFalse(tree["etc"].exists())
            self.assertFalse(minion_conf.exists())
            self.assertFalse(minion_pki.exists())

    def test_mihomo_uninstall_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            result = self._run_with_input(root, ["mihomo-uninstall"], "NO\n", tree=tree)

            self.assertNotEqual(0, result.returncode)
            self.assertTrue(tree["binary"].exists())

    def test_mihomo_uninstall_skips_non_proxyfleet_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            tree["unit"].write_text("[Service]\nExecStart=/usr/bin/mihomo -f /tmp/config.yaml\n", encoding="utf-8")
            result = self._run(root, ["mihomo-uninstall", "--yes"], tree)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(tree["unit"].exists())
            self.assertIn("跳过 Mihomo 服务删除", result.stdout)

    def test_takeover_mihomo_backs_up_and_stops_existing_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            tree["unit"].write_text("[Service]\nExecStart=/opt/shellcrash/mihomo -f /etc/ShellCrash/config.yaml\n", encoding="utf-8")
            backup = root / "backup"

            result = self._run(root, ["takeover-mihomo", "--yes", "--backup-dir", str(backup)], tree)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((backup / "mihomo.service.cat").exists())
            self.assertTrue((tree["etc"] / "local" / "takeover.json").exists())
            self.assertTrue(tree["unit"].with_name("mihomo.service.proxyfleet-taken-over").exists())
            log = self._systemctl_log(root)
            self.assertIn("stop mihomo.service", log)
            self.assertIn("disable mihomo.service", log)
            self.assertIn("daemon-reload", log)

    def test_single_script_minion_update_fallback_replaces_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "minion"
            script_dir = project / "scripts"
            script_dir.mkdir(parents=True)
            target = script_dir / "proxyfleet-minion.sh"
            target.write_text("#!/usr/bin/env bash\necho old-minion\n", encoding="utf-8")
            target.chmod(0o755)
            asset = root / "new-minion.sh"
            asset.write_text("#!/usr/bin/env bash\necho new-minion\n", encoding="utf-8")
            asset.chmod(0o755)
            manifest = root / "update-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "product": "proxyfleet",
                        "channel": "stable",
                        "version": "v0.2.0",
                        "commit": "d" * 40,
                        "published_at": "2026-06-26T00:00:00Z",
                        "minimum_supported_version": "v0.1.0",
                        "summary": ["minion script"],
                        "assets": [
                            {
                                "role": "minion",
                                "path": "scripts/proxyfleet-minion.sh",
                                "url": asset.as_uri(),
                                "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                                "mode": "0755",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "PROJECT_ROOT": str(project),
                    "PROXYFLEET_TEST_ALLOW_NON_ROOT": "1",
                    "PROXYFLEET_ETC_ROOT": str(root / "etc" / "proxyfleet"),
                    "UPDATE_MANIFEST_URL": str(manifest),
                }
            )

            result = subprocess.run(
                ["bash", str(SCRIPT), "update", "--yes"],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("new-minion", target.read_text(encoding="utf-8"))
            state = root / "etc" / "proxyfleet" / "local" / "update-state.json"
            self.assertTrue(state.exists())
            self.assertEqual("success", json.loads(state.read_text(encoding="utf-8"))["last_update_status"])

    def test_minion_update_manifest_defaults_to_release_latest(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'UPDATE_MANIFEST_URL="${UPDATE_MANIFEST_URL:-https://github.com/Flashyuan/ProxyFleet/releases/latest/download/update-manifest.json}"',
            text,
        )
        self.assertNotIn("raw.githubusercontent.com/Flashyuan/ProxyFleet/main/update-manifest.json", text)


if __name__ == "__main__":
    unittest.main()
