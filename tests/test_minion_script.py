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

    def _systemctl_log(self, root: Path) -> list[str]:
        log = root / "systemctl.log"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def test_default_start_does_not_touch_mihomo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._run(root, ["start"])

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["start salt-minion"], self._systemctl_log(root))

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

    def test_mihomo_uninstall_default_preserves_proxyfleet_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            result = self._run(root, ["mihomo-uninstall"], tree)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(tree["unit"].exists())
            self.assertTrue(tree["binary"].exists())
            self.assertTrue((tree["etc"] / "local").exists())
            self.assertTrue((tree["etc"] / "managed").exists())
            self.assertTrue((tree["etc"] / "effective").exists())
            self.assertTrue((tree["etc"] / "releases").exists())

    def test_mihomo_uninstall_purge_managed_preserves_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            result = self._run(root, ["mihomo-uninstall", "--purge-managed"], tree)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse((tree["etc"] / "managed").exists())
            self.assertFalse((tree["etc"] / "effective").exists())
            self.assertTrue((tree["etc"] / "local").exists())
            self.assertTrue(tree["binary"].exists())

    def test_mihomo_uninstall_purge_all_requires_yes_and_preserves_local_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            result = self._run(root, ["mihomo-uninstall", "--purge-all"], tree)

            self.assertNotEqual(0, result.returncode)
            self.assertTrue(tree["binary"].exists())

            result = self._run(root, ["mihomo-uninstall", "--purge-all", "--yes"], tree)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(tree["binary"].exists())
            self.assertFalse((tree["etc"] / "releases").exists())
            self.assertFalse((tree["etc"] / "current").exists())
            self.assertTrue((tree["etc"] / "local").exists())

    def test_purge_local_override_requires_purge_all_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = self._mihomo_tree(root)
            result = self._run(root, ["mihomo-uninstall", "--purge-local-override"], tree)

            self.assertNotEqual(0, result.returncode)
            self.assertTrue((tree["etc"] / "local").exists())

            result = self._run(root, ["mihomo-uninstall", "--purge-all", "--yes", "--purge-local-override"], tree)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse((tree["etc"] / "local").exists())


if __name__ == "__main__":
    unittest.main()
