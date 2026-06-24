"""代理节点目录、选择状态与同步计划。"""

from __future__ import annotations

import hashlib
import json
import socket
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from .config_build import ConfigBuildError, verify_release


MANAGED_POLICY_GROUP = "FLEET_PROXY"
DESIRED_SCHEMA_VERSION = "1.0"


class FleetError(ValueError):
    """ProxyFleet 运行态操作失败。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class NodeEntry:
    node_id: str
    mihomo_name: str
    provider_id: str
    protocol: str
    fingerprint: str
    availability: str = "unknown"
    selectable: bool | None = None
    selected: bool | None = None
    last_delay_ms: int | None = None
    health_status: str = "unknown"
    measured_at: str | None = None
    last_error_code: str | None = None
    freshness: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "node_id": self.node_id,
            "mihomo_name": self.mihomo_name,
            "provider_id": self.provider_id,
            "protocol": self.protocol,
            "fingerprint": self.fingerprint,
            "availability": self.availability,
            "health_status": self.health_status,
            "freshness": self.freshness,
        }
        if self.selectable is not None:
            payload["selectable"] = self.selectable
        if self.selected is not None:
            payload["selected"] = self.selected
        if self.last_delay_ms is not None:
            payload["last_delay_ms"] = self.last_delay_ms
        if self.measured_at is not None:
            payload["measured_at"] = self.measured_at
        if self.last_error_code is not None:
            payload["last_error_code"] = self.last_error_code
        return payload


@dataclass(frozen=True)
class ReleaseInfo:
    release_dir: Path
    release_revision: int
    provider_revision: int
    mihomo_version: str


@dataclass(frozen=True)
class SyncPlan:
    operation_id: str
    target: str
    release_revision: int
    desired_revision: int
    release_source: Path
    salt_release_dir: Path
    salt_desired_path: Path
    port_policy_enabled: bool = False
    port_policy_mode: str = "merge"

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "target": self.target,
            "release_revision": self.release_revision,
            "desired_revision": self.desired_revision,
            "release_source": str(self.release_source),
            "salt_release_dir": str(self.salt_release_dir),
            "salt_desired_path": str(self.salt_desired_path),
            "port_policy_enabled": self.port_policy_enabled,
            "port_policy_mode": self.port_policy_mode,
        }


def load_release_info(release_dir: Path) -> ReleaseInfo:
    """读取并校验 release 元数据。"""

    root = release_dir.resolve()
    verify_release(root)
    manifest = _read_json(root / "manifest.json")
    return ReleaseInfo(
        release_dir=root,
        release_revision=_require_int(manifest, "release_revision"),
        provider_revision=_require_int(manifest, "provider_revision"),
        mihomo_version=_require_str(manifest, "mihomo_version"),
    )


def build_node_catalog(release_dir: Path, health_cache_path: Path | None = None) -> list[NodeEntry]:
    """从 release Provider 快照生成稳定节点目录。"""

    root = release_dir.resolve()
    load_release_info(root)
    manifest = _read_json(root / "manifest.json")
    health_cache = load_health_cache(health_cache_path) if health_cache_path else {}
    entries: list[NodeEntry] = []
    seen_ids: set[str] = set()

    for item in manifest.get("files", []):
        relative = _require_str(item, "path")
        if not relative.startswith("providers/"):
            continue
        provider_id = Path(relative).stem
        provider_data = _read_json(root / relative)
        proxies = provider_data.get("proxies")
        if not isinstance(proxies, list):
            raise FleetError("E_CONFIG_VALIDATE", f"Provider 缺少 proxies 数组: {relative}")
        for proxy in proxies:
            if not isinstance(proxy, dict):
                raise FleetError("E_CONFIG_VALIDATE", f"Provider 节点必须是对象: {relative}")
            entry = _merge_health(_node_entry(provider_id, proxy), health_cache)
            if entry.node_id in seen_ids:
                raise FleetError("E_CONFIG_VALIDATE", f"node_id 重复: {entry.node_id}")
            seen_ids.add(entry.node_id)
            entries.append(entry)

    if not entries:
        raise FleetError("E_NODE_NOT_FOUND", "release 中没有可选代理节点")
    return entries


def load_health_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    """读取节点健康缓存；缺失文件表示没有缓存。"""

    if path is None or not path.exists():
        return {}
    data = _read_json(path)
    nodes = data.get("nodes", {})
    if isinstance(nodes, dict):
        return {str(key): value for key, value in nodes.items() if isinstance(value, dict)}
    if isinstance(nodes, list):
        cache: dict[str, dict[str, Any]] = {}
        for item in nodes:
            if isinstance(item, dict) and isinstance(item.get("node_id"), str):
                cache[str(item["node_id"])] = item
        return cache
    raise FleetError("E_CONFIG_VALIDATE", "health cache nodes 必须是对象或数组")


def write_node_catalog(release_dir: Path) -> Path:
    """把节点目录写入 release，便于审计和后续选择。"""

    root = release_dir.resolve()
    catalog_path = root / "node-catalog.json"
    entries = [entry.to_dict() for entry in build_node_catalog(root)]
    catalog_path.write_text(json.dumps({"schema_version": "1.0", "nodes": entries}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return catalog_path


def select_node(release_dir: Path, runtime_dir: Path, node_id: str, target_group: str, connection_policy: str = "preserve") -> dict[str, Any]:
    """选择稳定节点 ID 并写入 desired state。"""

    desired = build_desired_state(release_dir, runtime_dir, node_id, target_group, connection_policy)
    write_desired_state(runtime_dir / "desired.yaml", desired)
    return desired


def build_desired_state(release_dir: Path, runtime_dir: Path, node_id: str, target_group: str, connection_policy: str = "preserve") -> dict[str, Any]:
    """生成 desired state，但不写磁盘。"""

    release = load_release_info(release_dir)
    node = _find_node(build_node_catalog(release.release_dir), node_id)
    desired_path = runtime_dir / "desired.yaml"
    previous = load_desired_state(desired_path) if desired_path.exists() else None
    desired_revision = int(previous.get("desired_revision", 0)) + 1 if previous else 1
    return {
        "schema_version": DESIRED_SCHEMA_VERSION,
        "desired_revision": desired_revision,
        "release_revision": release.release_revision,
        "provider_revision": release.provider_revision,
        "target_group": target_group,
        "managed_policy_group": MANAGED_POLICY_GROUP,
        "selected_node_id": node.node_id,
        "selected_mihomo_name": node.mihomo_name,
        "connection_policy": connection_policy,
        "activate_at": None,
        "failure_policy": "fail-closed",
        "updated_at": _now_utc(),
    }


def write_desired_state(desired_path: Path, desired: dict[str, Any]) -> None:
    """原子写入 desired state。"""

    desired_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=desired_path.parent, delete=False) as fh:
        json.dump(desired, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
        temp_name = fh.name
    Path(temp_name).replace(desired_path)


def load_desired_state(path: Path) -> dict[str, Any]:
    """读取 desired state；当前写入 JSON/YAML 子集。"""

    data = _read_json(path)
    if data.get("schema_version") != DESIRED_SCHEMA_VERSION:
        raise FleetError("E_SCHEMA_UNSUPPORTED", "desired state schema_version 不受支持")
    if data.get("managed_policy_group") != MANAGED_POLICY_GROUP:
        raise FleetError("E_SCHEMA_UNSUPPORTED", "desired state managed_policy_group 不受支持")
    _require_int(data, "desired_revision")
    _require_int(data, "release_revision")
    _require_int(data, "provider_revision")
    _require_str(data, "selected_node_id")
    _require_str(data, "selected_mihomo_name")
    return data


def prepare_salt_publish(
    release_dir: Path,
    desired_path: Path,
    salt_root: Path,
    component_locks_path: Path | None = None,
    port_policy_path: Path | None = None,
    port_policy_mode: str = "merge",
) -> SyncPlan:
    """准备 Salt file_roots 中的 release 和 desired state。"""

    release = load_release_info(release_dir)
    desired = load_desired_state(desired_path)
    if desired["release_revision"] != release.release_revision:
        raise FleetError("E_PROVIDER_MISMATCH", "desired release_revision 与 release 不一致")
    if desired["provider_revision"] != release.provider_revision:
        raise FleetError("E_PROVIDER_MISMATCH", "desired provider_revision 与 release 不一致")

    salt_root = salt_root.resolve()
    release_target = salt_root / "proxyfleet" / "releases" / f"{release.release_revision:06d}"
    desired_target = salt_root / "proxyfleet" / "desired.yaml"
    locks_target = salt_root / "proxyfleet" / "component-locks.json"
    release_target.parent.mkdir(parents=True, exist_ok=True)
    if release_target.exists():
        shutil.rmtree(release_target)
    shutil.copytree(release.release_dir, release_target)
    desired_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(desired_path, desired_target)
    if component_locks_path is not None:
        try:
            shutil.copyfile(component_locks_path, locks_target)
        except OSError as exc:
            raise FleetError("E_COMPONENT_INTEGRITY_MISSING", f"组件锁定清单不可用: {component_locks_path}") from exc
    if port_policy_path is not None:
        try:
            shutil.copyfile(port_policy_path, salt_root / "proxyfleet" / "port-policy.yaml")
        except OSError as exc:
            raise FleetError("E_CONFIG_VALIDATE", f"端口白名单不可用: {port_policy_path}") from exc
    return _sync_plan(
        release,
        desired,
        release.release_dir,
        release_target,
        desired_target,
        target="*",
        port_policy_enabled=port_policy_path is not None,
        port_policy_mode=port_policy_mode,
    )


def build_sync_plan(
    release_dir: Path,
    desired_path: Path,
    salt_root: Path,
    target: str,
    *,
    port_policy_enabled: bool = False,
    port_policy_mode: str = "merge",
) -> SyncPlan:
    """生成同步计划，不写入 Salt 目录。"""

    release = load_release_info(release_dir)
    desired = load_desired_state(desired_path)
    if desired["release_revision"] != release.release_revision:
        raise FleetError("E_PROVIDER_MISMATCH", "desired release_revision 与 release 不一致")
    if desired["provider_revision"] != release.provider_revision:
        raise FleetError("E_PROVIDER_MISMATCH", "desired provider_revision 与 release 不一致")
    salt_release_dir = salt_root.resolve() / "proxyfleet" / "releases" / f"{release.release_revision:06d}"
    salt_desired_path = salt_root.resolve() / "proxyfleet" / "desired.yaml"
    return _sync_plan(
        release,
        desired,
        release.release_dir,
        salt_release_dir,
        salt_desired_path,
        target,
        port_policy_enabled=port_policy_enabled,
        port_policy_mode=port_policy_mode,
    )


def run_salt_sync(plan: SyncPlan, salt_bin: str = "salt") -> int:
    """调用 Salt state.apply，同步 release 并应用节点选择。"""

    cmd = [
        salt_bin,
        plan.target,
        "state.apply",
        "proxyfleet.sync",
        f"pillar={json.dumps({'proxyfleet_operation_id': plan.operation_id, 'proxyfleet_release_root': str(plan.salt_release_dir.parent), 'proxyfleet_desired_path': str(plan.salt_desired_path), 'proxyfleet_component_locks_path': str(plan.salt_desired_path.parent / 'component-locks.json'), 'proxyfleet_port_policy_enabled': plan.port_policy_enabled, 'proxyfleet_port_policy_mode': plan.port_policy_mode}, separators=(',', ':'))}",
    ]
    completed = subprocess.run(cmd, check=False)
    return int(completed.returncode)


class MihomoClient:
    """Mihomo 最小 API 客户端，PUT 后必须 GET 验证。"""

    def __init__(self, base_url: str, secret: str | None = None, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.timeout = timeout

    def select_node(self, group: str, mihomo_name: str) -> dict[str, Any]:
        before = self.get_group(group)
        all_names = _group_all_names(before)
        if mihomo_name not in all_names:
            raise FleetError("E_NODE_NOT_FOUND", "目标节点不在 Mihomo 策略组中")
        self._request("PUT", f"/proxies/{parse.quote(group, safe='')}", {"name": mihomo_name})
        after = self.get_group(group)
        if after.get("now") != mihomo_name:
            raise FleetError("E_SELECT_VERIFY", "Mihomo 选择后回读结果不一致")
        return {
            "schema_version": "1.0",
            "phase": "apply",
            "status": "success",
            "evidence": {
                "group": group,
                "selected_mihomo_name": mihomo_name,
            },
        }

    def get_group(self, group: str) -> dict[str, Any]:
        response = self._request("GET", f"/proxies/{parse.quote(group, safe='')}", None)
        if not isinstance(response, dict):
            raise FleetError("E_LOCAL_API", "Mihomo API 返回非对象")
        return response

    def health_check(self, mihomo_name: str, test_url: str, timeout_ms: int = 3000) -> dict[str, Any]:
        """执行单节点 delay 探测，不读取或修改 FLEET_PROXY 选择。"""

        if not mihomo_name:
            raise FleetError("E_NODE_NOT_FOUND", "Mihomo 节点名称不能为空")
        if not _is_allowed_healthcheck_url(test_url):
            raise FleetError("E_HEALTHCHECK_TARGET_BLOCKED", "健康检查 URL 不在允许列表中")
        query = parse.urlencode({"timeout": int(timeout_ms), "url": test_url})
        response = self._request(
            "GET",
            f"/proxies/{parse.quote(mihomo_name, safe='')}/delay?{query}",
            None,
            timeout_error_code="E_HEALTHCHECK_TIMEOUT",
            not_found_error_code="E_NODE_NOT_FOUND",
        )
        if not isinstance(response, dict):
            raise FleetError("E_HEALTHCHECK_FAILED", "Mihomo delay API 返回非对象")
        delay = response.get("delay")
        if not isinstance(delay, int):
            raise FleetError("E_HEALTHCHECK_FAILED", "Mihomo delay API 缺少 delay")
        return {
            "schema_version": "1.0",
            "mihomo_name": mihomo_name,
            "health_status": "ok",
            "last_delay_ms": delay,
            "measured_at": _now_utc(),
        }

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        timeout_error_code: str = "E_LOCAL_API",
        not_found_error_code: str = "E_NODE_NOT_FOUND",
    ) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"
        req = request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except error.HTTPError as exc:
            if exc.code == 404:
                raise FleetError(not_found_error_code, "Mihomo API 目标不存在") from exc
            raise FleetError("E_LOCAL_API", "Mihomo 本地 API 返回错误状态") from exc
        except socket.timeout as exc:
            raise FleetError(timeout_error_code, "Mihomo 本地 API 超时") from exc
        except (error.URLError, TimeoutError, socket.timeout) as exc:
            raise FleetError(timeout_error_code, "Mihomo 本地 API 不可用") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise FleetError("E_LOCAL_API", "Mihomo API 返回非 JSON") from exc


def salt_envelope(
    operation_id: str,
    minion_id: str,
    phase: str,
    status: str,
    release_revision: int,
    desired_revision: int,
    error_code: str | None = None,
    message: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成脱敏 Salt 作业结果 envelope。"""

    return {
        "schema_version": "1.0",
        "operation_id": operation_id,
        "minion_id": minion_id,
        "phase": phase,
        "status": status,
        "error_code": error_code,
        "message": _redact(message),
        "release_revision": release_revision,
        "desired_revision": desired_revision,
        "evidence": _redact_obj(evidence or {}),
    }


def _sync_plan(
    release: ReleaseInfo,
    desired: dict[str, Any],
    release_source: Path,
    salt_release_dir: Path,
    salt_desired_path: Path,
    target: str,
    *,
    port_policy_enabled: bool = False,
    port_policy_mode: str = "merge",
) -> SyncPlan:
    operation_id = f"op-{_now_utc().replace(':', '').replace('-', '')}-{desired['desired_revision']}"
    return SyncPlan(
        operation_id=operation_id,
        target=target,
        release_revision=release.release_revision,
        desired_revision=int(desired["desired_revision"]),
        release_source=release_source,
        salt_release_dir=salt_release_dir,
        salt_desired_path=salt_desired_path,
        port_policy_enabled=port_policy_enabled,
        port_policy_mode=port_policy_mode,
    )


def _node_entry(provider_id: str, proxy: dict[str, Any]) -> NodeEntry:
    name = _require_str(proxy, "name")
    protocol = _require_str(proxy, "type")
    stable = {
        "provider_id": provider_id,
        "name": name,
        "type": protocol,
        "server": proxy.get("server"),
        "port": proxy.get("port"),
    }
    fingerprint = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return NodeEntry(
        node_id=f"node-{fingerprint[:12]}",
        mihomo_name=name,
        provider_id=provider_id,
        protocol=protocol,
        fingerprint=fingerprint,
    )


def _find_node(nodes: list[NodeEntry], node_id: str) -> NodeEntry:
    matches = [node for node in nodes if node.node_id == node_id]
    if not matches:
        raise FleetError("E_NODE_NOT_FOUND", f"未知 node_id: {node_id}")
    if len(matches) > 1:
        raise FleetError("E_CONFIG_VALIDATE", f"node_id 重复: {node_id}")
    return matches[0]


def _merge_health(node: NodeEntry, cache: dict[str, dict[str, Any]]) -> NodeEntry:
    item = cache.get(node.node_id) or cache.get(node.mihomo_name)
    if not item:
        return node
    return NodeEntry(
        node_id=node.node_id,
        mihomo_name=node.mihomo_name,
        provider_id=node.provider_id,
        protocol=node.protocol,
        fingerprint=node.fingerprint,
        availability=str(item.get("availability", node.availability)),
        selectable=_optional_bool(item.get("selectable")),
        selected=_optional_bool(item.get("selected")),
        last_delay_ms=_optional_int(item.get("last_delay_ms")),
        health_status=str(item.get("health_status", node.health_status)),
        measured_at=str(item["measured_at"]) if item.get("measured_at") else None,
        last_error_code=str(item["last_error_code"]) if item.get("last_error_code") else None,
        freshness=str(item.get("freshness", node.freshness)),
    )


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _is_allowed_healthcheck_url(test_url: str) -> bool:
    """限制测速目标，避免把节点测速变成任意外联探测。"""

    parsed = parse.urlparse(test_url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "www.gstatic.com"
        and parsed.path == "/generate_204"
        and not parsed.query
        and not parsed.params
        and not parsed.fragment
        and not parsed.username
        and not parsed.password
    )


def _group_all_names(group: dict[str, Any]) -> set[str]:
    names = group.get("all")
    if isinstance(names, list):
        return {str(item) for item in names}
    proxies = group.get("proxies")
    if isinstance(proxies, list):
        return {str(item.get("name")) for item in proxies if isinstance(item, dict) and item.get("name")}
    return set()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FleetError("E_CONFIG_VALIDATE", f"文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FleetError("E_CONFIG_VALIDATE", f"JSON 无效: {path.name}") from exc
    if not isinstance(data, dict):
        raise FleetError("E_CONFIG_VALIDATE", f"JSON 顶层必须是对象: {path.name}")
    return data


def _require_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise FleetError("E_SCHEMA_UNSUPPORTED", f"缺少字段: {key}")
    return value


def _require_int(obj: dict[str, Any], key: str) -> int:
    value = obj.get(key)
    if not isinstance(value, int):
        raise FleetError("E_SCHEMA_UNSUPPORTED", f"缺少整数字段: {key}")
    return value


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _redact(message: str) -> str:
    redacted = str(message)
    for marker in ("secret=", "password=", "uuid=", "token=", "url="):
        if marker in redacted.lower():
            return "redacted"
    return redacted


def _redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("secret", "password", "uuid", "token", "url")):
                safe[key] = "redacted"
            else:
                safe[key] = _redact_obj(item)
        return safe
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value
