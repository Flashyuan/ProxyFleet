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
from proxyfleet.live_select import DEFAULT_CONCURRENCY, MAX_CONCURRENCY, LiveNode, LiveSelectModel, _LiveSelectRunner, _current_selection_summary, load_catalog
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

    def test_current_selection_shows_none_when_desired_and_api_empty(self):
        class Client:
            def get_group(self, group):
                return {"now": ""}

        self.assertEqual("当前选择：无", _current_selection_summary(None, Client()))

    def test_current_selection_shows_drift(self):
        class Client:
            def get_group(self, group):
                return {"now": "Actual"}

        with tempfile.TemporaryDirectory() as tmp:
            desired = Path(tmp) / "desired.yaml"
            desired.write_text(json.dumps({"selected_mihomo_name": "Desired"}), encoding="utf-8")
            summary = _current_selection_summary(desired, Client())

        self.assertEqual("当前选择漂移：desired=Desired actual=Actual", summary)

    def test_current_selection_handles_api_unavailable(self):
        class Client:
            def get_group(self, group):
                raise FleetError("E_LOCAL_API", "down")

        with tempfile.TemporaryDirectory() as tmp:
            desired = Path(tmp) / "desired.yaml"
            desired.write_text(json.dumps({"selected_mihomo_name": "Desired"}), encoding="utf-8")
            summary = _current_selection_summary(desired, Client())

        self.assertEqual("当前选择：未知（API 不可达，desired=Desired）", summary)

    def test_master_script_defaults_select_sync_to_tui(self):
        script = Path("scripts/proxyfleet-master.sh").read_text(encoding="utf-8")

        self.assertIn("--live-health) shift ;; # 兼容别名", script)
        self.assertIn('selected_line="$(live_health_menu', script)
        self.assertNotIn('read -r -p "请输入要同步到所有 Minion 的节点序号', script)
        self.assertIn("config-src/port-policy.yaml", script)

    def test_default_concurrency_is_resource_bounded(self):
        self.assertLessEqual(DEFAULT_CONCURRENCY, 8)
        self.assertLessEqual(MAX_CONCURRENCY, 8)
        runner = _LiveSelectRunner(
            LiveSelectModel(self._nodes()),
            object(),
            300,
            64,
            "https://www.gstatic.com/generate_204",
            current_selection="当前选择：无",
            release_label="1",
            target_label="*",
            port_policy_status="端口白名单：未配置",
        )

        self.assertLessEqual(runner.concurrency, MAX_CONCURRENCY)
        self.assertEqual(len(self._nodes()), runner.concurrency)

    def test_initial_probe_order_prioritizes_selected_then_viewport_then_background(self):
        nodes = [
            LiveNode(1, "node-a", "Alpha"),
            LiveNode(2, "node-b", "Beta", selected=True),
            LiveNode(3, "node-c", "Gamma"),
            LiveNode(4, "node-d", "Delta"),
        ]
        runner = _LiveSelectRunner(
            LiveSelectModel(nodes),
            object(),
            300,
            2,
            "https://www.gstatic.com/generate_204",
            current_selection="当前选择：Beta",
            release_label="1",
            target_label="*",
            port_policy_status="端口白名单：未配置",
        )

        runner._reset_nodes_for_probe(current_page_first=False, viewport_height=2)
        runner._enqueue_initial_probe_order(viewport_height=2)
        ordered = [runner.tasks.get_nowait()[3].node_id for _ in range(4)]

        self.assertEqual("node-b", ordered[0])
        self.assertEqual("node-a", ordered[1])
        self.assertEqual("node-c", ordered[2])
        self.assertEqual("node-d", ordered[3])

    def test_fresh_cache_nodes_are_not_immediately_reprobed_on_entry(self):
        nodes = [
            LiveNode(1, "node-a", "Alpha", "ok", 12, freshness="fresh"),
            LiveNode(2, "node-b", "Beta"),
        ]
        runner = _LiveSelectRunner(
            LiveSelectModel(nodes),
            object(),
            300,
            2,
            "https://www.gstatic.com/generate_204",
            current_selection="当前选择：无",
            release_label="1",
            target_label="*",
            port_policy_status="端口白名单：未配置",
        )

        runner._reset_nodes_for_probe(current_page_first=False, viewport_height=1)
        runner._enqueue_initial_probe_order(viewport_height=1)
        queued = []
        while not runner.tasks.empty():
            queued.append(runner.tasks.get_nowait()[3].node_id)

        self.assertIn("node-a", runner.completed)
        self.assertEqual(1, runner.counts["ok"])
        self.assertNotIn("node-a", queued)

    def test_refresh_requeues_current_page_even_when_cached(self):
        nodes = [
            LiveNode(1, "node-a", "Alpha", "ok", 12, freshness="fresh"),
            LiveNode(2, "node-b", "Beta", "ok", 15, freshness="fresh"),
            LiveNode(3, "node-c", "Gamma", "ok", 20, freshness="fresh"),
        ]
        runner = _LiveSelectRunner(
            LiveSelectModel(nodes),
            object(),
            300,
            2,
            "https://www.gstatic.com/generate_204",
            current_selection="当前选择：无",
            release_label="1",
            target_label="*",
            port_policy_status="端口白名单：未配置",
        )

        runner._reset_nodes_for_probe(current_page_first=True, viewport_height=2)
        runner._enqueue_initial_probe_order(viewport_height=2)
        queued = [runner.tasks.get_nowait()[3].node_id for _ in range(2)]

        self.assertEqual(["node-a", "node-b"], queued)


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
                    if not sent and b"ProxyFleet Select" in output:
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

    def test_tui_180_nodes_can_select_without_waiting_for_full_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, output = self._run_pty(self._catalog(tmp, count=180), b"\n")

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
