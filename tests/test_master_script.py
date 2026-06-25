import os
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
    ) -> subprocess.CompletedProcess:
        fakebin = self._fakebin(root)
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fakebin}:{env['PATH']}",
                "PROXYFLEET_TEST_ALLOW_NON_ROOT": "1",
                "PROJECT_ROOT": str(ROOT),
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
            self.assertNotIn("用法：scripts/proxyfleet-master.sh <command>", result.stdout)

    def test_no_tty_master_fallback_shows_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(Path(tmp), [], allow_tui=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("E_TUI_UNAVAILABLE", result.stderr)
            self.assertIn("sudo scripts/proxyfleet-master.sh select-sync", result.stderr)

    def test_purge_data_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._run(root, ["uninstall", "--purge-data"], "NO\n")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("已取消 purge-data", result.stderr)
            self.assertFalse((root / "commands.log").exists())


if __name__ == "__main__":
    unittest.main()
