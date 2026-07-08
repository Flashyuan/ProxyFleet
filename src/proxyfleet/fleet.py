"""代理节点目录、选择状态与同步计划。"""

from __future__ import annotations

import hashlib
import json
import re
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
from .subscription import SubscriptionError, parse_provider_snapshot


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
    proxy_mode: str = "tproxy"

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
            "proxy_mode": self.proxy_mode,
        }


@dataclass(frozen=True)
class SaltSyncResult:
    returncode: int
    log_path: Path | None
    failed_minions: list[str]
    error_summary: str
    route_plan: dict[str, Any] | None = None
    fallback_used: bool = False
    warning: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "returncode": self.returncode,
            "log_path": str(self.log_path) if self.log_path else None,
            "failed_minions": self.failed_minions,
            "error_summary": self.error_summary,
        }
        if self.route_plan is not None:
            payload["route_plan"] = self.route_plan
        if self.fallback_used:
            payload["fallback_used"] = True
        if self.warning:
            payload["warning"] = self.warning
        return payload


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
    release = load_release_info(root)
    manifest = _read_json(root / "manifest.json")
    health_cache = load_health_cache(health_cache_path, release) if health_cache_path else {}
    entries: list[NodeEntry] = []
    seen_ids: set[str] = set()

    for item in manifest.get("files", []):
        relative = _require_str(item, "path")
        if not relative.startswith("providers/"):
            continue
        provider_id = Path(relative).stem
        provider_data = _read_provider_snapshot(root / relative)
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


def load_health_cache(path: Path | None, release: ReleaseInfo | None = None) -> dict[str, dict[str, Any]]:
    """读取节点健康缓存；缺失文件表示没有缓存。"""

    if path is None or not path.exists():
        return {}
    data = _read_json(path)
    if release is not None:
        if data.get("release_revision") != release.release_revision or data.get("provider_revision") != release.provider_revision:
            return {}
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
    proxy_mode: str = "tproxy",
    full_converge: bool = True,
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
    assets_target = salt_root / "proxyfleet" / "assets"
    release_target.parent.mkdir(parents=True, exist_ok=True)
    if full_converge:
        _copytree_if_changed(release.release_dir, release_target)
    else:
        _assert_lightweight_publish_ready(release.release_dir, release_target, component_locks_path, locks_target, assets_target)
    desired_target.parent.mkdir(parents=True, exist_ok=True)
    _copyfile_if_changed(desired_path, desired_target, mode=0o644)
    if full_converge and component_locks_path is not None:
        try:
            _copyfile_if_changed(component_locks_path, locks_target, mode=0o644)
            _publish_component_assets_if_changed(component_locks_path, assets_target)
        except OSError as exc:
            raise FleetError("E_COMPONENT_INTEGRITY_MISSING", f"组件锁定清单不可用: {component_locks_path}") from exc
    elif not locks_target.exists():
        raise FleetError("E_SYNC_NEEDS_FULL_CONVERGE", "Salt file_roots 缺少 component-locks.json，请先执行 --full-converge")
    if port_policy_path is not None:
        try:
            port_policy_target = salt_root / "proxyfleet" / "port-policy.yaml"
            _copyfile_if_changed(port_policy_path, port_policy_target, mode=0o644)
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
        proxy_mode=proxy_mode,
    )


def build_sync_plan(
    release_dir: Path,
    desired_path: Path,
    salt_root: Path,
    target: str,
    *,
    port_policy_enabled: bool = False,
    port_policy_mode: str = "merge",
    proxy_mode: str = "tproxy",
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
        proxy_mode=proxy_mode,
    )


def run_salt_sync_result(
    plan: SyncPlan,
    salt_bin: str = "salt",
    *,
    batch: str | None = None,
    log_dir: Path | None = None,
    full_converge: bool = False,
    concurrency: int = 5,
    plan_only: bool = False,
) -> SaltSyncResult:
    """同步 release 并应用节点选择。

    默认路径先对 Minion 做轻量分类，已收敛旧节点只执行 Mihomo API 切换；
    新节点或漂移节点才走完整 state.apply。显式 batch/full_converge 保留旧
    state.apply 路径，用于修复和兼容。
    """

    _validate_batch(batch)
    if concurrency < 1:
        raise FleetError("E_CONFIG_VALIDATE", "concurrency 必须大于 0")
    if not full_converge and not batch:
        return _run_smart_sync_result(plan, salt_bin, log_dir=log_dir, concurrency=concurrency, plan_only=plan_only)
    if plan_only:
        return SaltSyncResult(
            0,
            None,
            [],
            "",
            route_plan={
                "mode": "full-converge" if full_converge else "state-apply",
                "target": plan.target,
                "batch": batch,
            },
        )
    return _run_state_apply_result(plan, salt_bin, batch=batch, log_dir=log_dir)


def _run_state_apply_result(plan: SyncPlan, salt_bin: str, *, batch: str | None = None, log_dir: Path | None = None) -> SaltSyncResult:
    """调用 Salt state.apply，同步 release 并应用节点选择。"""

    pillar = f"pillar={json.dumps({'proxyfleet_operation_id': plan.operation_id, 'proxyfleet_release_root': str(plan.salt_release_dir.parent), 'proxyfleet_desired_path': str(plan.salt_desired_path), 'proxyfleet_component_locks_path': str(plan.salt_desired_path.parent / 'component-locks.json'), 'proxyfleet_port_policy_enabled': plan.port_policy_enabled, 'proxyfleet_port_policy_mode': plan.port_policy_mode, 'proxyfleet_proxy_mode': plan.proxy_mode}, separators=(',', ':'))}"
    cmd = _salt_sync_cmd(plan, salt_bin, batch, pillar)
    completed = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output = _completed_output(completed)
    final_cmd = cmd
    final_returncode = int(completed.returncode)
    fallback_used = False
    fallback_warning = None

    if batch and final_returncode != 0 and _is_salt_batch_publish_error(output):
        fallback_cmd = _salt_sync_cmd(plan, salt_bin, None, pillar)
        fallback = subprocess.run(fallback_cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        fallback_output = _completed_output(fallback)
        fallback_used = True
        fallback_warning = "Salt batch publish failed; retried without --batch"
        if int(fallback.returncode) == 0:
            output = "# ProxyFleet fallback: Salt batch publish failed; retried without --batch.\n" + fallback_output
        else:
            output = output + "\n\n# ProxyFleet fallback: Salt batch publish failed; retried without --batch.\n" + fallback_output
        final_cmd = fallback_cmd
        final_returncode = int(fallback.returncode)

    log_path = _write_salt_log(plan, final_cmd, output, log_dir) if log_dir is not None else None
    failed_minions, error_summary = _summarize_salt_output(output, final_returncode)
    return SaltSyncResult(final_returncode, log_path, failed_minions, error_summary, fallback_used=fallback_used, warning=fallback_warning)


def _run_smart_sync_result(
    plan: SyncPlan,
    salt_bin: str,
    *,
    log_dir: Path | None,
    concurrency: int,
    plan_only: bool,
) -> SaltSyncResult:
    if not plan.salt_desired_path.exists() or not (plan.salt_desired_path.parent / "component-locks.json").exists():
        return _run_state_apply_result(plan, salt_bin, batch=None, log_dir=log_dir)
    desired = _read_json(plan.salt_desired_path)
    route_plan, status_output, status_rc = _build_minion_route_plan(plan, salt_bin)
    if plan_only:
        log_path = _write_salt_log(plan, [salt_bin, plan.target, "proxyfleet_mihomo.sync_status"], status_output, log_dir) if log_dir is not None else None
        return SaltSyncResult(0, log_path, [], "", route_plan=route_plan, warning=_route_plan_warning(route_plan))
    if status_rc != 0 or route_plan.get("classification_unavailable"):
        fallback = _run_state_apply_result(plan, salt_bin, batch=None, log_dir=log_dir)
        warning = "Minion classification failed; fell back to state.apply"
        if route_plan.get("classification_unavailable"):
            warning = "Minion classification unavailable; fell back to state.apply"
        return SaltSyncResult(
            fallback.returncode,
            fallback.log_path,
            fallback.failed_minions,
            fallback.error_summary,
            route_plan=route_plan,
            fallback_used=True,
            warning=warning,
        )

    outputs = [status_output] if status_output else []
    returncode = 0
    failed_minions: list[str] = []
    switch_minions = [item["minion_id"] for item in route_plan["minions"] if item["action"] == "switch-only"]
    converge_minions = [item["minion_id"] for item in route_plan["minions"] if item["action"] == "full-converge"]
    route_warning = _route_plan_warning(route_plan)

    for chunk in _chunks(switch_minions, concurrency):
        cmd = _salt_apply_switch_cmd(plan, salt_bin, chunk, desired)
        completed = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output = _completed_output(completed)
        outputs.append(output)
        if int(completed.returncode) != 0:
            returncode = int(completed.returncode)
            failed_minions.extend(chunk)

    for chunk in _chunks(converge_minions, concurrency):
        chunk_plan = _replace_plan_target(plan, ",".join(chunk))
        pillar = f"pillar={json.dumps({'proxyfleet_operation_id': plan.operation_id, 'proxyfleet_release_root': str(plan.salt_release_dir.parent), 'proxyfleet_desired_path': str(plan.salt_desired_path), 'proxyfleet_component_locks_path': str(plan.salt_desired_path.parent / 'component-locks.json'), 'proxyfleet_port_policy_enabled': plan.port_policy_enabled, 'proxyfleet_port_policy_mode': plan.port_policy_mode, 'proxyfleet_proxy_mode': plan.proxy_mode}, separators=(',', ':'))}"
        cmd = _salt_sync_cmd(chunk_plan, salt_bin, None, pillar, target_type="list")
        completed = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output = _completed_output(completed)
        outputs.append(output)
        if int(completed.returncode) != 0:
            returncode = int(completed.returncode)
            failed_minions.extend(chunk)

    combined = "\n".join(item for item in outputs if item)
    log_path = _write_salt_log(plan, [salt_bin, plan.target, "proxyfleet smart sync"], combined, log_dir) if log_dir is not None else None
    parsed_failed, error_summary = _summarize_salt_output(combined, returncode)
    merged_failed = sorted(set(failed_minions + parsed_failed))
    return SaltSyncResult(returncode, log_path, merged_failed, error_summary, route_plan=route_plan, warning=route_warning)


def _build_minion_route_plan(plan: SyncPlan, salt_bin: str) -> tuple[dict[str, Any], str, int]:
    expected_locks = _sha256_file(plan.salt_desired_path.parent / "component-locks.json")
    desired = _read_json(plan.salt_desired_path)
    expected_targets = _expected_target_ids(plan.target, salt_bin)
    if expected_targets is None and plan.target == "*":
        return _route_plan_unavailable(plan, "accepted key list unavailable"), "", 1

    ping_cmd = [
        salt_bin,
        plan.target,
        "test.ping",
        "--out=json",
        "--static",
    ]
    ping = subprocess.run(ping_cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ping_output = _completed_output(ping)
    if int(ping.returncode) != 0:
        return _route_plan_unavailable(plan, "test.ping command failed"), ping_output, int(ping.returncode)

    ping_data = _json_object(ping.stdout)
    if ping_data is None:
        return _route_plan_unavailable(plan, "test.ping returned invalid JSON"), ping_output, 1

    minions: list[dict[str, Any]] = []
    reachable = _reachable_minions(ping_data, expected_targets)
    if expected_targets is not None:
        for minion_id in sorted(set(expected_targets) - set(reachable)):
            minions.append(
                {
                    "minion_id": minion_id,
                    "classification": "offline",
                    "action": "defer",
                    "reason": "test.ping did not return true",
                    "reachability": "offline",
                }
            )
    if not reachable:
        return _route_plan(plan, minions, classification_unavailable=False), ping_output, 0

    functions_cmd = [
        salt_bin,
        "-L",
        ",".join(reachable),
        "sys.list_functions",
        "proxyfleet_mihomo",
        "--out=json",
        "--static",
    ]
    functions = subprocess.run(functions_cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    functions_output = _completed_output(functions)
    if int(functions.returncode) != 0:
        return _route_plan_unavailable(plan, "sys.list_functions command failed"), "\n".join([ping_output, functions_output]), int(functions.returncode)

    functions_data = _json_object(functions.stdout)
    if functions_data is None:
        return _route_plan_unavailable(plan, "sys.list_functions returned invalid JSON"), "\n".join([ping_output, functions_output]), 1

    module_ready: list[str] = []
    for minion_id in reachable:
        functions_value = functions_data.get(minion_id)
        if _has_proxyfleet_sync_functions(functions_value):
            module_ready.append(minion_id)
        else:
            minions.append(
                {
                    "minion_id": minion_id,
                    "classification": "new-minion",
                    "action": "full-converge",
                    "reason": "proxyfleet execution module missing or stale",
                    "reachability": "online",
                    "module_status": "missing",
                }
            )

    status_output = ""
    if module_ready:
        status_cmd = [
            salt_bin,
            "-L",
            ",".join(module_ready),
            "proxyfleet_mihomo.sync_status",
            f"expected_release_revision={plan.release_revision}",
            f"expected_component_locks_sha256={expected_locks}",
            f"expected_selected_node_id={desired['selected_node_id']}",
            "--out=json",
            "--static",
        ]
        completed = subprocess.run(status_cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        status_output = _completed_output(completed)
        if int(completed.returncode) != 0:
            return _route_plan_unavailable(plan, "sync_status command failed"), "\n".join([ping_output, functions_output, status_output]), int(completed.returncode)
        status_data = _json_object(completed.stdout)
        if status_data is None:
            return _route_plan_unavailable(plan, "sync_status returned invalid JSON"), "\n".join([ping_output, functions_output, status_output]), 1
        for minion_id in module_ready:
            value = status_data.get(minion_id)
            if not isinstance(value, dict):
                minions.append(
                    {
                        "minion_id": minion_id,
                        "classification": "drifted",
                        "action": "full-converge",
                        "reason": "missing status return",
                        "reachability": "online",
                        "module_status": "ready",
                    }
                )
                continue
            classification = str(value.get("classification", "drifted"))
            reason = str(value.get("reason", ""))
            if classification == "ready-old":
                action = "switch-only"
                if plan.port_policy_enabled:
                    action = "full-converge"
                    reason = "port policy enabled requires converge"
            elif classification in {"new-minion", "drifted"}:
                action = "full-converge"
            else:
                classification = "drifted"
                action = "full-converge"
                reason = reason or "unexpected sync_status classification"
            minions.append(
                {
                    "minion_id": minion_id,
                    "classification": classification,
                    "action": action,
                    "reason": reason,
                    "reachability": "online",
                    "module_status": "ready",
                }
            )

    return _route_plan(plan, sorted(minions, key=lambda item: item["minion_id"]), classification_unavailable=False), "\n".join(
        item for item in (ping_output, functions_output, status_output) if item
    ), 0


def _route_plan_unavailable(plan: SyncPlan, reason: str) -> dict[str, Any]:
    return {
        "mode": "smart",
        "target": plan.target,
        "classification_unavailable": True,
        "summary": {"ready-old": 0, "new-minion": 0, "drifted": 0, "offline": 0, "unknown": 0},
        "minions": [],
        "reason": reason,
    }


def _route_plan(plan: SyncPlan, minions: list[dict[str, Any]], *, classification_unavailable: bool) -> dict[str, Any]:
    return {
        "mode": "smart",
        "target": plan.target,
        "classification_unavailable": classification_unavailable,
        "summary": _route_summary(minions),
        "minions": minions,
    }


def _json_object(raw: str | None) -> dict[str, Any] | None:
    try:
        data = json.loads(raw if isinstance(raw, str) else "{}")
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _reachable_minions(ping_data: dict[str, Any], expected_targets: list[str] | None) -> list[str]:
    candidates = expected_targets if expected_targets is not None else sorted(str(key) for key in ping_data)
    reachable: list[str] = []
    for minion_id in candidates:
        value = ping_data.get(minion_id)
        if value is True or str(value).lower() == "true":
            reachable.append(str(minion_id))
    return sorted(set(reachable))


def _has_proxyfleet_sync_functions(functions_value: Any) -> bool:
    if not isinstance(functions_value, list):
        return False
    functions = {str(item) for item in functions_value}
    return "proxyfleet_mihomo.sync_status" in functions and "proxyfleet_mihomo.apply_switch" in functions


def _route_plan_warning(route_plan: dict[str, Any]) -> str | None:
    minions = route_plan.get("minions", [])
    if not isinstance(minions, list):
        return None
    offline = [item for item in minions if isinstance(item, dict) and item.get("classification") == "offline"]
    active = [item for item in minions if isinstance(item, dict) and item.get("action") in {"switch-only", "full-converge"}]
    if offline and active:
        return "Some Minions were offline and deferred"
    if offline and not active:
        return "No reachable Minions; sync deferred"
    return None


def _expected_target_ids(target: str, salt_bin: str) -> list[str] | None:
    if target == "*":
        salt_key = str(Path(salt_bin).with_name("salt-key")) if "/" in salt_bin else "salt-key"
        completed = subprocess.run([salt_key, "--out=json", "-l", "acc"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if int(completed.returncode) != 0:
            return None
        try:
            data = json.loads(completed.stdout if isinstance(completed.stdout, str) else "{}")
        except Exception:
            return None
        if isinstance(data, dict):
            for field in ("minions", "accepted", "Accepted Keys"):
                value = data.get(field)
                if isinstance(value, list) and value:
                    return sorted(set(str(item) for item in value))
        return None
    if not any(char in target for char in "*?[]{},"):
        return [target]
    return None


def _route_summary(minions: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"ready-old": 0, "new-minion": 0, "drifted": 0, "offline": 0}
    for item in minions:
        key = str(item.get("classification", "offline"))
        summary[key] = summary.get(key, 0) + 1
    return summary


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _replace_plan_target(plan: SyncPlan, target: str) -> SyncPlan:
    return SyncPlan(
        operation_id=plan.operation_id,
        target=target,
        release_revision=plan.release_revision,
        desired_revision=plan.desired_revision,
        release_source=plan.release_source,
        salt_release_dir=plan.salt_release_dir,
        salt_desired_path=plan.salt_desired_path,
        port_policy_enabled=plan.port_policy_enabled,
        port_policy_mode=plan.port_policy_mode,
        proxy_mode=plan.proxy_mode,
    )


def _salt_sync_cmd(plan: SyncPlan, salt_bin: str, batch: str | None, pillar: str, *, target_type: str = "glob") -> list[str]:
    cmd = [salt_bin, "--state-output=terse", "--state-verbose=False", "--summary"]
    if batch:
        cmd.extend(["--batch", batch])
    if target_type == "list":
        cmd.extend(["-L", plan.target])
    else:
        cmd.append(plan.target)
    cmd.extend(
        [
            "state.apply",
            "proxyfleet.sync",
            pillar,
        ]
    )
    return cmd


def _salt_apply_switch_cmd(plan: SyncPlan, salt_bin: str, minions: list[str], desired: dict[str, Any]) -> list[str]:
    return [
        salt_bin,
        "-L",
        ",".join(minions),
        "proxyfleet_mihomo.apply_switch",
        f"desired_json={json.dumps(desired, ensure_ascii=False, separators=(',', ':'))}",
        f"operation_id={plan.operation_id}",
        "--out=json",
        "--static",
    ]


def _completed_output(completed: subprocess.CompletedProcess[str] | Any) -> str:
    stdout = completed.stdout if isinstance(getattr(completed, "stdout", None), str) else ""
    stderr = completed.stderr if isinstance(getattr(completed, "stderr", None), str) else ""
    return stdout + (("\n" + stderr) if stderr else "")


def _is_salt_batch_publish_error(output: str) -> bool:
    return (
        "Some exception handling minion payload" in output
        or "salt.exceptions.PublishError" in output
        or "salt.exceptions.SaltClientError" in output
    )


def run_salt_sync(plan: SyncPlan, salt_bin: str = "salt", *, batch: str | None = None, log_dir: Path | None = None) -> int:
    return run_salt_sync_result(plan, salt_bin, batch=batch, log_dir=log_dir).returncode


class MihomoClient:
    """Mihomo 最小 API 客户端，PUT 后必须 GET 验证。"""

    def __init__(self, base_url: str, secret: str | None = None, timeout: float = 3.0):
        _assert_loopback_api(base_url)
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
            request_timeout=max(self.timeout, int(timeout_ms) / 1000 + 2),
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
        request_timeout: float | None = None,
    ) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"
        req = request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)
        try:
            with request.urlopen(req, timeout=self.timeout if request_timeout is None else request_timeout) as resp:
                raw = resp.read()
        except error.HTTPError as exc:
            if exc.code == 404:
                raise FleetError(not_found_error_code, "Mihomo API 目标不存在") from exc
            raise FleetError("E_LOCAL_API", "Mihomo 本地 API 返回错误状态") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise FleetError(timeout_error_code, "Mihomo 本地 API 超时") from exc
        except error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise FleetError(timeout_error_code, "Mihomo 本地 API 超时") from exc
            raise FleetError("E_LOCAL_API", "Mihomo 本地 API 不可用") from exc
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
    proxy_mode: str = "tproxy",
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
        proxy_mode=proxy_mode,
    )


def _chmod_tree(root: Path, *, dir_mode: int, file_mode: int) -> None:
    root.chmod(dir_mode)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(dir_mode)
        elif path.is_file():
            path.chmod(file_mode)


def _copyfile_if_changed(source: Path, target: Path, *, mode: int | None = None) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_file() and _sha256_file(source) == _sha256_file(target):
        if mode is not None:
            target.chmod(mode)
        return False
    shutil.copy2(source, target)
    if mode is not None:
        target.chmod(mode)
    return True


def _copytree_if_changed(source: Path, target: Path) -> bool:
    digest = _tree_digest(source)
    marker = target.parent / f".{target.name}.sha256"
    if target.exists() and marker.exists() and marker.read_text(encoding="utf-8").strip() == digest:
        _chmod_tree(target, dir_mode=0o755, file_mode=0o644)
        return False
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    _chmod_tree(target, dir_mode=0o755, file_mode=0o644)
    marker.write_text(digest + "\n", encoding="utf-8")
    return True


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_component_assets(component_locks_path: Path, assets_target: Path) -> None:
    """把 Master 本地离线组件资产发布到 Salt file_roots，供 Minion 无外网安装。"""

    if assets_target.exists():
        shutil.rmtree(assets_target)
    assets_target.mkdir(parents=True, exist_ok=True)

    root = component_locks_path.resolve().parent
    asset_directories = [
        root / "component-assets",
        root / "assets",
        root / "offline-assets",
        root / "runtime" / "asset-mirror" / "public" / "proxyfleet" / "mihomo",
    ]
    for directory in asset_directories:
        if directory.is_dir():
            for path in directory.iterdir():
                if path.is_file():
                    shutil.copy2(path, assets_target / path.name)

    try:
        locks = _read_json(component_locks_path)
    except FleetError:
        return
    for component in locks.get("components", []):
        artifacts = component.get("artifacts", {})
        if not isinstance(artifacts, dict):
            continue
        for artifact in artifacts.values():
            if not isinstance(artifact, dict):
                continue
            local_path = artifact.get("local_path") or artifact.get("file")
            if not isinstance(local_path, str) or not local_path:
                continue
            source = Path(local_path)
            if not source.is_absolute():
                source = root / source
            if not source.is_file():
                continue
            target = assets_target / source.name
            shutil.copy2(source, target)
            sha256 = artifact.get("sha256")
            if isinstance(sha256, str) and len(sha256) == 64:
                shutil.copy2(source, assets_target / sha256)
    _chmod_tree(assets_target, dir_mode=0o755, file_mode=0o644)


def _publish_component_assets_if_changed(component_locks_path: Path, assets_target: Path) -> bool:
    digest = _component_assets_digest(component_locks_path)
    marker = assets_target.parent / ".assets.sha256"
    if assets_target.exists() and marker.exists() and marker.read_text(encoding="utf-8").strip() == digest:
        _chmod_tree(assets_target, dir_mode=0o755, file_mode=0o644)
        return False
    _publish_component_assets(component_locks_path, assets_target)
    marker.write_text(digest + "\n", encoding="utf-8")
    return True


def _assert_lightweight_publish_ready(
    release_source: Path,
    release_target: Path,
    component_locks_path: Path | None,
    locks_target: Path,
    assets_target: Path,
) -> None:
    """轻量发布前校验 Salt file_roots 已有完整、安全的组件基线。"""

    if not release_target.exists():
        raise FleetError("E_SYNC_NEEDS_FULL_CONVERGE", "Salt file_roots 缺少 release，请先执行 --full-converge")
    try:
        verify_release(release_target)
    except ConfigBuildError as exc:
        raise FleetError("E_SYNC_NEEDS_FULL_CONVERGE", "Salt file_roots release 校验失败，请先执行 --full-converge") from exc
    if _tree_digest(release_source) != _tree_digest(release_target):
        raise FleetError("E_SYNC_NEEDS_FULL_CONVERGE", "Salt file_roots release 与当前 release 不一致，请先执行 --full-converge")
    if not locks_target.exists():
        raise FleetError("E_SYNC_NEEDS_FULL_CONVERGE", "Salt file_roots 缺少 component-locks.json，请先执行 --full-converge")
    if component_locks_path is not None and _sha256_file(component_locks_path) != _sha256_file(locks_target):
        raise FleetError("E_SYNC_NEEDS_FULL_CONVERGE", "Salt file_roots component-locks.json 与当前组件锁不一致，请先执行 --full-converge")
    if component_locks_path is not None:
        marker = assets_target.parent / ".assets.sha256"
        if not assets_target.exists() or not marker.exists() or marker.read_text(encoding="utf-8").strip() != _component_assets_digest(component_locks_path):
            raise FleetError("E_SYNC_NEEDS_FULL_CONVERGE", "Salt file_roots 组件资产缺失或过期，请先执行 --full-converge")


def _component_assets_digest(component_locks_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(_sha256_file(component_locks_path).encode("ascii"))
    root = component_locks_path.resolve().parent
    try:
        locks = _read_json(component_locks_path)
    except FleetError:
        return digest.hexdigest()
    for component in locks.get("components", []):
        artifacts = component.get("artifacts", {}) if isinstance(component, dict) else {}
        if not isinstance(artifacts, dict):
            continue
        for artifact in artifacts.values():
            if not isinstance(artifact, dict):
                continue
            local_path = artifact.get("local_path") or artifact.get("file")
            if not isinstance(local_path, str) or not local_path:
                continue
            source = Path(local_path)
            if not source.is_absolute():
                source = root / source
            if source.is_file():
                digest.update(str(source).encode("utf-8"))
                digest.update(_sha256_file(source).encode("ascii"))
    return digest.hexdigest()


def _validate_batch(batch: str | None) -> None:
    if batch is None or batch == "":
        return
    raw = str(batch)
    if raw.endswith("%"):
        number = raw[:-1]
        if number.isdigit() and 1 <= int(number) <= 100:
            return
    elif raw.isdigit() and int(raw) > 0:
        return
    raise FleetError("E_SCHEMA_UNSUPPORTED", "Salt batch 必须是正整数或 1..100%")


def _write_salt_log(plan: SyncPlan, cmd: list[str], output: str, log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_dir.chmod(0o700)
    log_path = log_dir / f"{plan.operation_id}.salt.log"
    payload = [
        "# ProxyFleet Salt sync log",
        "operation_id=" + plan.operation_id,
        "target=" + plan.target,
        "command=" + " ".join(_redact(item) for item in cmd),
        "",
        _redact(output),
    ]
    log_path.write_text("\n".join(payload), encoding="utf-8")
    log_path.chmod(0o600)
    return log_path


def _summarize_salt_output(output: str, returncode: int) -> tuple[list[str], str]:
    failed: list[str] = []
    current_minion: str | None = None
    summary: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not line.startswith((" ", "\t", "-", "{", "[", '"')) and stripped.endswith(":"):
            current_minion = stripped[:-1]
        lowered = stripped.lower()
        if re.fullmatch(r"failed:\s+0", lowered):
            continue
        if "result: false" in lowered or '"result": false' in lowered or "failed" in lowered or "error" in lowered or "e_" in lowered:
            if current_minion and current_minion not in failed:
                failed.append(current_minion)
            if len(summary) < 5:
                summary.append(_redact(stripped))
    if returncode != 0 and not summary:
        summary.append(f"salt exited with {returncode}")
    return failed[:20], "; ".join(summary[:5])


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


def _assert_loopback_api(base_url: str) -> None:
    parsed = parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise FleetError("E_LOCAL_API", "Mihomo API 仅支持本机 HTTP(S) 地址")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return
    raise FleetError("E_LOCAL_API", "Mihomo API 必须是 loopback 地址")


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


def _read_provider_snapshot(path: Path) -> dict[str, Any]:
    try:
        return parse_provider_snapshot(path.read_bytes())
    except FileNotFoundError as exc:
        raise FleetError("E_CONFIG_VALIDATE", f"文件不存在: {path}") from exc
    except SubscriptionError as exc:
        raise FleetError("E_CONFIG_VALIDATE", f"Provider 无效: {path.name}: {exc}") from exc


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
    lowered = redacted.lower()
    if re.search(r'["\']?(password|passwd|secret|api_secret|token|uuid)["\']?\s*[:=]\s*["\']?[^"\'\s,;}]+', lowered):
        return "redacted"
    for marker in (
        "secret=",
        "password=",
        "passwd=",
        "uuid=",
        "token=",
        "url=",
        "http://",
        "https://",
        "vmess://",
        "vless://",
        "trojan://",
        "ss://",
        "ssr://",
        "hysteria2://",
        "tuic://",
        "socks5://",
    ):
        if marker in lowered:
            return "redacted"
    if re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", lowered):
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
