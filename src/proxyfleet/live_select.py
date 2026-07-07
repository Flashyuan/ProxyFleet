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
DEFAULT_CONCURRENCY = 8
MAX_CONCURRENCY = 8
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
    provider_id: str = ""
    selected: bool = False
    freshness: str = "unknown"

    @classmethod
    def from_catalog_item(cls, index: int, item: dict[str, Any]) -> "LiveNode":
        return cls(
            index=index,
            node_id=str(item.get("node_id") or ""),
            mihomo_name=str(item.get("mihomo_name") or ""),
            health_status=str(item.get("health_status") or "pending"),
            last_delay_ms=item.get("last_delay_ms") if isinstance(item.get("last_delay_ms"), int) else None,
            last_error_code=item.get("last_error_code") if isinstance(item.get("last_error_code"), str) else None,
            provider_id=str(item.get("provider_id") or ""),
            selected=bool(item.get("selected") is True),
            freshness=str(item.get("freshness") or "unknown"),
        )

    def has_fresh_health(self) -> bool:
        """fresh 缓存不在进入 TUI 时立刻重复探测，包含成功和失败状态。"""

        return self.freshness == "fresh" and self.health_status in {"ok", "timeout", "failed"}

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
    concurrency: int = DEFAULT_CONCURRENCY,
    test_url: str = DEFAULT_TEST_URL,
    desired_path: Path | None = None,
    release_label: str = "-",
    target_label: str = "-",
    port_policy_status: str = "端口白名单：未配置",
) -> LiveNode | None:
    """运行 curses TUI，返回用户确认选择的节点；退出返回 None。"""

    if timeout_ms < 300 or timeout_ms > 10000:
        raise FleetError("E_HEALTHCHECK_FAILED", "timeout-ms 必须在 300..10000 之间")
    if concurrency < 1 or concurrency > 64:
        raise FleetError("E_HEALTHCHECK_FAILED", "concurrency 必须在 1..64 之间")
    nodes = load_catalog(catalog_path)
    client = MihomoClient(mihomo_api, mihomo_secret)
    model = LiveSelectModel(nodes)
    current_selection = _current_selection_summary(desired_path, client)
    runner = _LiveSelectRunner(
        model,
        client,
        timeout_ms,
        min(concurrency, MAX_CONCURRENCY),
        test_url,
        current_selection=current_selection,
        release_label=release_label,
        target_label=target_label,
        port_policy_status=port_policy_status,
    )
    return runner.run()


class _LiveSelectRunner:
    def __init__(
        self,
        model: LiveSelectModel,
        client: MihomoClient,
        timeout_ms: int,
        concurrency: int,
        test_url: str,
        *,
        current_selection: str,
        release_label: str,
        target_label: str,
        port_policy_status: str,
    ):
        self.model = model
        self.client = client
        self.timeout_ms = timeout_ms
        self.concurrency = min(max(1, concurrency), MAX_CONCURRENCY, len(model.nodes))
        self.test_url = test_url
        self.current_selection = current_selection
        self.release_label = release_label
        self.target_label = target_label
        self.port_policy_status = port_policy_status
        self.updates: queue.Queue[tuple[str, str, int | None, str | None]] = queue.Queue()
        self.tasks: queue.PriorityQueue[tuple[int, int, str, LiveNode]] = queue.PriorityQueue()
        self.stop_event = threading.Event()
        self.started = time.monotonic()
        self.counts = {"ok": 0, "timeout": 0, "failed": 0}
        self.completed: set[str] = set()
        self.inflight: set[str] = set()
        self.scheduled_priority: dict[str, int] = {}
        self.sequence = 0
        self.search_mode = False

    def run(self) -> LiveNode | None:
        return curses.wrapper(self._main)

    def _start_probe_round(self, viewport_height: int, *, current_page_first: bool = False) -> None:
        self.stop_event.set()
        self.stop_event = threading.Event()
        self.tasks = queue.PriorityQueue()
        self.updates = queue.Queue()
        self.completed = set()
        self.inflight = set()
        self.scheduled_priority = {}
        self.sequence = 0
        self.counts = {"ok": 0, "timeout": 0, "failed": 0}
        self.started = time.monotonic()
        self._reset_nodes_for_probe(current_page_first=current_page_first, viewport_height=viewport_height)
        self._enqueue_initial_probe_order(viewport_height)
        round_stop_event = self.stop_event
        for _ in range(self.concurrency):
            threading.Thread(target=self._worker, args=(round_stop_event,), daemon=True).start()

    def _reset_nodes_for_probe(self, *, current_page_first: bool, viewport_height: int) -> None:
        page_ids = {node.node_id for node in self.model.page(viewport_height)} if current_page_first else set()
        for node in self.model.nodes:
            if node.has_fresh_health() and node.node_id not in page_ids:
                self.completed.add(node.node_id)
                self.counts[node.health_status if node.health_status in self.counts else "failed"] += 1
                continue
            node.health_status = "pending"
            node.last_delay_ms = None
            node.last_error_code = None
            node.freshness = "unknown"

    def _enqueue_initial_probe_order(self, viewport_height: int) -> None:
        page = self.model.page(viewport_height)
        visible = self.model.visible_nodes()
        selected = [node for node in self.model.nodes if node.selected]
        self._enqueue_nodes(selected, priority=0)
        self._enqueue_nodes(page, priority=1)
        self._enqueue_nodes(visible, priority=2)
        self._enqueue_nodes(self.model.nodes, priority=5)

    def _enqueue_current_page(self, viewport_height: int, *, force: bool = False) -> None:
        if force:
            for node in self.model.page(viewport_height):
                self.completed.discard(node.node_id)
                node.health_status = "pending"
                node.last_delay_ms = None
                node.last_error_code = None
                node.freshness = "unknown"
        self._enqueue_nodes(self.model.page(viewport_height), priority=0, force=force)

    def _enqueue_nodes(self, nodes: list[LiveNode], *, priority: int, force: bool = False) -> None:
        for node in nodes:
            if not force and (node.node_id in self.completed or node.node_id in self.inflight):
                continue
            previous = self.scheduled_priority.get(node.node_id)
            if not force and previous is not None and previous <= priority:
                continue
            self.scheduled_priority[node.node_id] = priority
            self.sequence += 1
            self.tasks.put((priority, self.sequence, node.node_id, node))

    def _worker(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                priority, _, node_id, node = self.tasks.get_nowait()
            except queue.Empty:
                return
            if self.scheduled_priority.get(node_id) != priority:
                self.tasks.task_done()
                continue
            if node.node_id in self.completed or node.node_id in self.inflight:
                self.tasks.task_done()
                continue
            self.inflight.add(node.node_id)
            self.scheduled_priority.pop(node.node_id, None)
            try:
                health = self.client.health_check(node.mihomo_name, self.test_url, self.timeout_ms)
                self.updates.put((node.node_id, "ok", int(health["last_delay_ms"]), None))
            except FleetError as exc:
                status = "timeout" if exc.error_code == "E_HEALTHCHECK_TIMEOUT" else "failed"
                self.updates.put((node.node_id, status, None, exc.error_code))
            finally:
                self.inflight.discard(node.node_id)
                self.tasks.task_done()

    def _main(self, screen) -> LiveNode | None:
        curses.curs_set(0)
        screen.nodelay(True)
        screen.keypad(True)
        selected: LiveNode | None = None
        try:
            self._draw(screen)
            self._start_probe_round(max(1, screen.getmaxyx()[0] - 7))
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
        viewport_height = max(1, height - 7)
        total = len(self.model.nodes)
        done = len(self.completed)
        elapsed = int(time.monotonic() - self.started)
        sort_label = "delay" if self.model.sort_by_delay else "index"
        title = f"ProxyFleet Select | release={self.release_label} | target={self.target_label} | {self.current_selection}"
        status = (
            f"进度 {done}/{total} "
            f"ok={self.counts['ok']} timeout={self.counts['timeout']} failed={self.counts['failed']} "
            f"耗时={elapsed}s 并发={self.concurrency} source=master-local sort={sort_label} | {self.port_policy_status}"
        )
        help_text = "↑/↓ j/k 移动  Enter 选择  / 搜索  r 重测  s 延迟排序  n 原序  q 退出"
        self._addstr(screen, 0, 0, title, width, curses.A_BOLD)
        self._addstr(screen, 1, 0, status, width)
        if self.search_mode:
            self._addstr(screen, 2, 0, f"search: {self.model.search}", width, curses.A_REVERSE)
        else:
            self._addstr(screen, 2, 0, f"filter: {self.model.search or '-'}", width)
        self._addstr(screen, 3, 0, "序号  状态        延迟      当前  Provider        Mihomo 节点", width, curses.A_BOLD)
        page = self.model.page(viewport_height)
        visible = self.model.visible_nodes()
        start = self.model.offset + 1 if visible else 0
        end = min(self.model.offset + len(page), len(visible))
        self._addstr(screen, height - 2, 0, f"visible {start}-{end}/{len(visible)}  图例：*当前选择 pending/ok/timeout/failed/stale/unknown", width)
        self._addstr(screen, height - 1, 0, help_text, width, curses.A_DIM if hasattr(curses, "A_DIM") else curses.A_NORMAL)
        for row, node in enumerate(page, start=4):
            if row >= height - 2:
                break
            cursor_index = self.model.offset + row - 4
            attr = curses.A_REVERSE if cursor_index == self.model.cursor else curses.A_NORMAL
            marker = ">" if cursor_index == self.model.cursor else " "
            current_marker = "*" if node.selected else " "
            status = node.health_status[:10]
            delay = f"{node.last_delay_ms}ms" if isinstance(node.last_delay_ms, int) else "-"
            provider = node.provider_id[:14]
            name_width = max(16, width - 48)
            line = f"{marker} {node.index:4d}  {status:<10} {delay:>8}   {current_marker}   {provider:<14.14} {node.mihomo_name:<{name_width}.{name_width}}"
            self._addstr(screen, row, 0, line, width, attr)
        screen.refresh()

    def _handle_key(self, key: int, screen) -> LiveNode | object | None:
        viewport_height = max(1, screen.getmaxyx()[0] - 7)
        if self.search_mode:
            if key in (27, curses.KEY_EXIT):
                self.search_mode = False
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                self.model.set_search(self.model.search[:-1], viewport_height)
                self._enqueue_current_page(viewport_height)
            elif key in (10, 13):
                self.search_mode = False
            elif 32 <= key <= 126:
                self.model.set_search(self.model.search + chr(key), viewport_height)
                self._enqueue_current_page(viewport_height)
            return None

        if key in (ord("q"), 27):
            return _QUIT
        if key in (curses.KEY_DOWN, ord("j")):
            self.model.move(1, viewport_height)
            self._enqueue_current_page(viewport_height)
        elif key in (curses.KEY_UP, ord("k")):
            self.model.move(-1, viewport_height)
            self._enqueue_current_page(viewport_height)
        elif key == curses.KEY_NPAGE:
            self.model.move(viewport_height, viewport_height)
            self._enqueue_current_page(viewport_height)
        elif key == curses.KEY_PPAGE:
            self.model.move(-viewport_height, viewport_height)
            self._enqueue_current_page(viewport_height)
        elif key in (10, 13):
            return self.model.current()
        elif key == ord("/"):
            self.search_mode = True
            self.model.set_search("", viewport_height)
            self._enqueue_current_page(viewport_height)
        elif key == ord("r"):
            self._start_probe_round(viewport_height, current_page_first=True)
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


def _current_selection_summary(desired_path: Path | None, client: MihomoClient) -> str:
    desired_name: str | None = None
    if desired_path and desired_path.exists():
        try:
            desired = json.loads(desired_path.read_text(encoding="utf-8"))
            value = desired.get("selected_mihomo_name")
            if isinstance(value, str) and value:
                desired_name = value
        except (OSError, json.JSONDecodeError):
            desired_name = None

    try:
        group = client.get_group("FLEET_PROXY")
        actual = group.get("now")
        actual_name = actual if isinstance(actual, str) and actual else None
    except FleetError:
        if desired_name:
            return f"当前选择：未知（API 不可达，desired={desired_name}）"
        return "当前选择：未知（API 不可达）"

    if not desired_name and not actual_name:
        return "当前选择：无"
    if desired_name and actual_name and desired_name != actual_name:
        return f"当前选择漂移：desired={desired_name} actual={actual_name}"
    return f"当前选择：{desired_name or actual_name}"
