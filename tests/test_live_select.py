import json
import contextlib
import io
import os
import pty
import select
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from proxyfleet.fleet import FleetError
from proxyfleet.live_select import LiveNode, LiveSelectModel, load_catalog
from proxyfleet.cli import main


class LiveSelectModelTests(unittest.TestCase):
    def _nodes(self):
        return [
            LiveNode(1, "node-a", "Alpha", "pending"),
            LiveNode(2, "node-b", "Beta", "pending"),
            LiveNode(3, "node-c", "Gamma", "pending"),
        ]

    def test_model_keeps_stable_indices_by_default(self):
        model = LiveSelectModel(self._nodes())
        model.update_health("node-b", "ok", 20, None)
        model.update_health("node-a", "ok", 10, None)

        self.assertEqual([1, 2, 3], [node.index for node in model.visible_nodes()])

    def test_search_filters_without_changing_node_identity(self):
        model = LiveSelectModel(self._nodes())
        model.set_search("bet", viewport_height=10)

        visible = model.visible_nodes()
        self.assertEqual(1, len(visible))
        self.assertEqual("node-b", visible[0].node_id)
        self.assertEqual(2, visible[0].index)

    def test_delay_sort_is_explicit_and_keeps_original_index(self):
        model = LiveSelectModel(self._nodes())
        model.update_health("node-a", "ok", 30, None)
        model.update_health("node-b", "ok", 10, None)
        model.sort_by_delay = True

        visible = model.visible_nodes()
        self.assertEqual(["node-b", "node-a", "node-c"], [node.node_id for node in visible])
        self.assertEqual([2, 1, 3], [node.index for node in visible])

    def test_health_update_only_changes_target_node(self):
        model = LiveSelectModel(self._nodes())
        model.update_health("node-b", "failed", None, "E_LOCAL_API")

        by_id = {node.node_id: node for node in model.nodes}
        self.assertEqual("pending", by_id["node-a"].health_status)
        self.assertEqual("failed", by_id["node-b"].health_status)
        self.assertEqual("E_LOCAL_API", by_id["node-b"].last_error_code)

    def test_load_catalog_rejects_empty_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            path.write_text(json.dumps({"nodes": []}), encoding="utf-8")

            with self.assertRaises(FleetError):
                LiveSelectModel(load_catalog(path))

    def test_live_select_rejects_non_loopback_before_tui(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            path.write_text(
                json.dumps({"nodes": [{"node_id": "node-a", "mihomo_name": "Alpha"}]}),
                encoding="utf-8",
            )

            with contextlib.redirect_stderr(io.StringIO()):
                code = main(["live-select", str(path), "--mihomo-api", "http://192.0.2.1:9090"])

        self.assertEqual(2, code)


class LiveSelectPtyTests(unittest.TestCase):
    def _catalog(self, tmp: str, count: int = 20) -> Path:
        path = Path(tmp) / "catalog.json"
        nodes = [{"node_id": f"node-{idx}", "mihomo_name": f"Node {idx:02d}"} for idx in range(1, count + 1)]
        path.write_text(json.dumps({"nodes": nodes}), encoding="utf-8")
        return path

    def _run_pty(self, catalog: Path, keys: bytes, timeout: float = 8.0) -> tuple[int, str]:
        cmd = [
            "env",
            "TERM=xterm",
            "PYTHONPATH=src",
            "python3",
            "-m",
            "proxyfleet.cli",
            "live-select",
            str(catalog),
            "--mihomo-api",
            "http://127.0.0.1:65535",
            "--timeout-ms",
            "300",
            "--concurrency",
            "2",
        ]
        pid, fd = pty.fork()
        if pid == 0:
            os.execvp(cmd[0], cmd)
        output = bytearray()
        sent = False
        deadline = time.time() + timeout
        status = None
        try:
            while time.time() < deadline:
                readable, _, _ = select.select([fd], [], [], 0.1)
                if readable:
                    try:
                        data = os.read(fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    output.extend(data)
                    if not sent and b"ProxyFleet Live Select" in output:
                        os.write(fd, keys)
                        sent = True
                waited, status_candidate = os.waitpid(pid, os.WNOHANG)
                if waited:
                    status = status_candidate
                    break
            else:
                os.kill(pid, 2)
                _, status = os.waitpid(pid, 0)
            if status is None:
                try:
                    _, status = os.waitpid(pid, 0)
                except ChildProcessError:
                    status = 1
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        return int(status), output.decode("utf-8", errors="replace")

    def test_tui_enter_selects_highlighted_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, output = self._run_pty(self._catalog(tmp), b"\n")

        self.assertTrue(os.WIFEXITED(status), output)
        self.assertEqual(0, os.WEXITSTATUS(status), output)
        self.assertIn("1\tnode-1\tNode 01", output)

    def test_tui_supports_search_and_select(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, output = self._run_pty(self._catalog(tmp), b"/15\n\n")

        self.assertTrue(os.WIFEXITED(status), output)
        self.assertEqual(0, os.WEXITSTATUS(status), output)
        self.assertIn("15\tnode-15\tNode 15", output)

    def test_tui_supports_keyboard_scroll_and_select(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, output = self._run_pty(self._catalog(tmp), b"jjjjjjjjj\n")

        self.assertTrue(os.WIFEXITED(status), output)
        self.assertEqual(0, os.WEXITSTATUS(status), output)
        self.assertIn("10\tnode-10\tNode 10", output)

    def test_tui_q_exits_without_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, output = self._run_pty(self._catalog(tmp), b"q")

        self.assertTrue(os.WIFEXITED(status), output)
        self.assertEqual(130, os.WEXITSTATUS(status), output)
        self.assertIn("\x1b[?1049l", output)

    def test_tui_ctrl_c_restores_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, output = self._run_pty(self._catalog(tmp), b"\x03")

        self.assertNotEqual(0, os.WEXITSTATUS(status) if os.WIFEXITED(status) else 130, output)
        self.assertIn("\x1b[?1049l", output)


if __name__ == "__main__":
    unittest.main()
