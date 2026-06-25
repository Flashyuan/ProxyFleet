"""实时测速节点选择 TUI。"""

from __future__ import annotations

import curses
import json
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fleet import FleetError, MihomoClient


DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"
_QUIT = object()


@dataclass
class LiveNode:
    """TUI 内部使用的节点视图模型。"""

    index: int
    node_id: str
    mihomo_name: str
    health_status: str = "pending"
    last_delay_ms: int | None = None
    last_error_code: str | None = None

    @classmethod
    def from_catalog_item(cls, index: int, item: dict[str, Any]) -> "LiveNode":
        return cls(
            index=index,
            node_id=str(item.get("node_id") or ""),
            mihomo_name=str(item.get("mihomo_name") or ""),
            health_status=str(item.get("health_status") or "pending"),
            last_delay_ms=item.get("last_delay_ms") if isinstance(item.get("last_delay_ms"), int) else None,
            last_error_code=item.get("last_error_code") if isinstance(item.get("last_error_code"), str) else None,
        )

    def status_text(self) -> str:
        delay = f"{self.last_delay_ms}ms" if isinstance(self.last_delay_ms, int) else "-"
        return f"{self.health_status} {delay}"

    def to_tsv(self) -> str:
        delay = self.last_delay_ms if isinstance(self.last_delay_ms, int) else "-"
        return f"{self.index}\t{self.node_id}\t{self.mihomo_name}\t{self.health_status}\t{delay}"


class LiveSelectModel:
    """无 curses 依赖的选择状态，便于测试。"""

    def __init__(self, nodes: list[LiveNode]):
        if not nodes:
            raise FleetError("E_NODE_NOT_FOUND", "没有可选择节点")
        self.nodes = nodes
        self.cursor = 0
        self.offset = 0
        self.search = ""
        self.sort_by_delay = False

    def visible_nodes(self) -> list[LiveNode]:
        items = self.nodes
        if self.search:
            needle = self.search.lower()
            items = [node for node in items if needle in node.mihomo_name.lower() or needle in str(node.index)]
        if self.sort_by_delay:
            items = sorted(items, key=lambda node: (node.last_delay_ms is None, node.last_delay_ms or 10**9, node.index))
        else:
            items = sorted(items, key=lambda node: node.index)
        if not items:
            self.cursor = 0
            self.offset = 0
            return []
        self.cursor = max(0, min(self.cursor, len(items) - 1))
        return items

    def move(self, delta: int, viewport_height: int) -> None:
        items = self.visible_nodes()
        if not items:
            return
        self.cursor = max(0, min(self.cursor + delta, len(items) - 1))
        self._clamp_offset(len(items), viewport_height)

    def current(self) -> LiveNode | None:
        items = self.visible_nodes()
        return items[self.cursor] if items else None

    def update_health(self, node_id: str, status: str, delay: int | None, error_code: str | None) -> None:
        for node in self.nodes:
            if node.node_id == node_id:
                node.health_status = status
                node.last_delay_ms = delay
                node.last_error_code = error_code
                return

    def set_search(self, text: str, viewport_height: int) -> None:
        self.search = text
        self.cursor = 0
        self.offset = 0
        self._clamp_offset(len(self.visible_nodes()), viewport_height)

    def page(self, viewport_height: int) -> list[LiveNode]:
        items = self.visible_nodes()
        self._clamp_offset(len(items), viewport_height)
        return items[self.offset : self.offset + viewport_height]

    def _clamp_offset(self, item_count: int, viewport_height: int) -> None:
        viewport_height = max(1, viewport_height)
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + viewport_height:
            self.offset = self.cursor - viewport_height + 1
        self.offset = max(0, min(self.offset, max(0, item_count - viewport_height)))


def load_catalog(path: Path) -> list[LiveNode]:
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        raise FleetError("E_CONFIG_VALIDATE", "catalog nodes 必须是数组")
    return [LiveNode.from_catalog_item(index, item) for index, item in enumerate(nodes, start=1) if isinstance(item, dict)]


def run_live_select(
    catalog_path: Path,
    *,
    mihomo_api: str,
    mihomo_secret: str | None = None,
    timeout_ms: int = 2000,
    concurrency: int = 16,
    test_url: str = DEFAULT_TEST_URL,
) -> LiveNode | None:
    """运行 curses TUI，返回用户确认选择的节点；退出返回 None。"""

    if timeout_ms < 300 or timeout_ms > 10000:
        raise FleetError("E_HEALTHCHECK_FAILED", "timeout-ms 必须在 300..10000 之间")
    if concurrency < 1 or concurrency > 64:
        raise FleetError("E_HEALTHCHECK_FAILED", "concurrency 必须在 1..64 之间")
    nodes = load_catalog(catalog_path)
    client = MihomoClient(mihomo_api, mihomo_secret)
    model = LiveSelectModel(nodes)
    runner = _LiveSelectRunner(model, client, timeout_ms, concurrency, test_url)
    return runner.run()


class _LiveSelectRunner:
    def __init__(self, model: LiveSelectModel, client: MihomoClient, timeout_ms: int, concurrency: int, test_url: str):
        self.model = model
        self.client = client
        self.timeout_ms = timeout_ms
        self.concurrency = min(concurrency, len(model.nodes))
        self.test_url = test_url
        self.updates: queue.Queue[tuple[str, str, int | None, str | None]] = queue.Queue()
        self.tasks: queue.Queue[LiveNode] = queue.Queue()
        self.stop_event = threading.Event()
        self.started = time.monotonic()
        self.counts = {"ok": 0, "timeout": 0, "failed": 0}
        self.completed: set[str] = set()
        self.search_mode = False

    def run(self) -> LiveNode | None:
        self._start_probe_round()
        return curses.wrapper(self._main)

    def _start_probe_round(self) -> None:
        self.stop_event.set()
        self.stop_event = threading.Event()
        self.tasks = queue.Queue()
        self.updates = queue.Queue()
        self.completed = set()
        self.counts = {"ok": 0, "timeout": 0, "failed": 0}
        self.started = time.monotonic()
        for node in self.model.nodes:
            node.health_status = "pending"
            node.last_delay_ms = None
            node.last_error_code = None
            self.tasks.put(node)
        for _ in range(max(1, self.concurrency)):
            threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                node = self.tasks.get_nowait()
            except queue.Empty:
                return
            try:
                health = self.client.health_check(node.mihomo_name, self.test_url, self.timeout_ms)
                self.updates.put((node.node_id, "ok", int(health["last_delay_ms"]), None))
            except FleetError as exc:
                status = "timeout" if exc.error_code == "E_HEALTHCHECK_TIMEOUT" else "failed"
                self.updates.put((node.node_id, status, None, exc.error_code))
            finally:
                self.tasks.task_done()

    def _main(self, screen) -> LiveNode | None:
        curses.curs_set(0)
        screen.nodelay(True)
        screen.keypad(True)
        selected: LiveNode | None = None
        try:
            while selected is None:
                self._drain_updates()
                self._draw(screen)
                key = screen.getch()
                if key == -1:
                    curses.napms(100)
                    continue
                action = self._handle_key(key, screen)
                if action is _QUIT:
                    return None
                if isinstance(action, LiveNode):
                    selected = action
        finally:
            self.stop_event.set()
        return selected

    def _drain_updates(self) -> None:
        while True:
            try:
                node_id, status, delay, error_code = self.updates.get_nowait()
            except queue.Empty:
                return
            if node_id not in self.completed:
                self.completed.add(node_id)
                self.counts[status if status in self.counts else "failed"] += 1
            self.model.update_health(node_id, status, delay, error_code)

    def _draw(self, screen) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        viewport_height = max(1, height - 5)
        total = len(self.model.nodes)
        done = len(self.completed)
        elapsed = int(time.monotonic() - self.started)
        sort_label = "delay" if self.model.sort_by_delay else "index"
        header = (
            f"ProxyFleet Live Select  {done}/{total} "
            f"ok={self.counts['ok']} timeout={self.counts['timeout']} failed={self.counts['failed']} "
            f"elapsed={elapsed}s 并发={self.concurrency} source=master-local sort={sort_label}"
        )
        help_text = "↑/↓ j/k 移动  Enter 选择  / 搜索  r 重测  s 延迟排序  n 原序  q 退出"
        self._addstr(screen, 0, 0, header, width, curses.A_BOLD)
        self._addstr(screen, 1, 0, help_text, width)
        if self.search_mode:
            self._addstr(screen, 2, 0, f"search: {self.model.search}", width, curses.A_REVERSE)
        else:
            self._addstr(screen, 2, 0, f"filter: {self.model.search or '-'}", width)
        page = self.model.page(viewport_height)
        visible = self.model.visible_nodes()
        start = self.model.offset + 1 if visible else 0
        end = min(self.model.offset + len(page), len(visible))
        self._addstr(screen, 3, 0, f"visible {start}-{end}/{len(visible)}", width)
        for row, node in enumerate(page, start=4):
            cursor_index = self.model.offset + row - 4
            attr = curses.A_REVERSE if cursor_index == self.model.cursor else curses.A_NORMAL
            marker = ">" if cursor_index == self.model.cursor else " "
            line = f"{marker} {node.index:4d} {node.mihomo_name:<64.64} [{node.status_text():>12}]"
            self._addstr(screen, row, 0, line, width, attr)
        screen.refresh()

    def _handle_key(self, key: int, screen) -> LiveNode | object | None:
        viewport_height = max(1, screen.getmaxyx()[0] - 5)
        if self.search_mode:
            if key in (27, curses.KEY_EXIT):
                self.search_mode = False
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                self.model.set_search(self.model.search[:-1], viewport_height)
            elif key in (10, 13):
                self.search_mode = False
            elif 32 <= key <= 126:
                self.model.set_search(self.model.search + chr(key), viewport_height)
            return None

        if key in (ord("q"), 27):
            return _QUIT
        if key in (curses.KEY_DOWN, ord("j")):
            self.model.move(1, viewport_height)
        elif key in (curses.KEY_UP, ord("k")):
            self.model.move(-1, viewport_height)
        elif key == curses.KEY_NPAGE:
            self.model.move(viewport_height, viewport_height)
        elif key == curses.KEY_PPAGE:
            self.model.move(-viewport_height, viewport_height)
        elif key in (10, 13):
            return self.model.current()
        elif key == ord("/"):
            self.search_mode = True
            self.model.set_search("", viewport_height)
        elif key == ord("r"):
            self._start_probe_round()
        elif key == ord("s"):
            self.model.sort_by_delay = True
            self.model.cursor = 0
            self.model.offset = 0
        elif key == ord("n"):
            self.model.sort_by_delay = False
            self.model.cursor = 0
            self.model.offset = 0
        return None

    @staticmethod
    def _addstr(screen, y: int, x: int, text: str, width: int, attr: int = curses.A_NORMAL) -> None:
        try:
            screen.addstr(y, x, text[: max(0, width - 1)], attr)
        except curses.error:
            pass
