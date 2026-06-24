"""端口白名单分层合并。

本模块只生成 ProxyFleet 的 effective port policy 文件；实际落地到 UFW/nftables
属于后续 OPS 实现。输入文件使用 JSON 语法，保存为 yaml 扩展名时仍是合法 YAML
子集，避免在 Minion 上引入额外解析依赖。
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PortPolicyError(ValueError):
    """端口策略无效或冲突。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class PortPolicyResult:
    mode: str
    managed_sha256: str | None
    local_sha256: str | None
    effective_sha256: str
    rule_count: int
    conflicts: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "mode": self.mode,
            "managed_sha256": self.managed_sha256,
            "local_sha256": self.local_sha256,
            "effective_sha256": self.effective_sha256,
            "rule_count": self.rule_count,
            "conflicts": self.conflicts,
        }


EMPTY_POLICY = {"schema_version": "1.0", "owner": "empty", "allow": [], "deny": []}
VALID_MODES = {"merge", "master-only", "local-only", "disabled"}
VALID_PROTOCOLS = {"tcp", "udp"}


def build_effective_policy(
    managed_path: Path,
    local_path: Path,
    effective_path: Path,
    *,
    mode: str = "merge",
    lkg_path: Path | None = None,
) -> PortPolicyResult:
    """合并 managed/local 策略并原子写入 effective。

    local 文件不存在不是错误；local 文件存在但语法错误时 fail-closed。
    """

    if mode not in VALID_MODES:
        raise PortPolicyError("E_PORT_POLICY_SCHEMA", f"未知端口策略模式: {mode}")

    managed = _load_optional_policy(managed_path, "master")
    local = _load_optional_policy(local_path, "local")
    effective = _merge(managed, local, mode)

    effective_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(effective, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temp = effective_path.with_name(effective_path.name + ".next")
    temp.write_text(payload, encoding="utf-8")
    temp.replace(effective_path)
    if lkg_path is not None:
        lkg_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(effective_path, lkg_path)

    return PortPolicyResult(
        mode=mode,
        managed_sha256=_file_sha256(managed_path),
        local_sha256=_file_sha256(local_path),
        effective_sha256=_sha256_bytes(payload.encode("utf-8")),
        rule_count=len(effective["allow"]) + len(effective["deny"]),
        conflicts=[],
    )


def status(managed_path: Path, local_path: Path, effective_path: Path, *, mode: str = "merge") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": mode,
        "managed_exists": managed_path.exists(),
        "local_exists": local_path.exists(),
        "effective_exists": effective_path.exists(),
        "managed_sha256": _file_sha256(managed_path),
        "local_sha256": _file_sha256(local_path),
        "effective_sha256": _file_sha256(effective_path),
    }


def _merge(managed: dict[str, Any], local: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode == "disabled":
        selected = []
    elif mode == "master-only":
        selected = [managed]
    elif mode == "local-only":
        selected = [local]
    else:
        selected = [managed, local]

    allow: list[dict[str, Any]] = []
    deny: list[dict[str, Any]] = []
    seen: dict[tuple[str, int, str], str] = {}
    conflicts: list[str] = []
    for policy in selected:
        for action in ("allow", "deny"):
            for rule in policy.get(action, []):
                normalized = _normalize_rule(rule, str(policy.get("owner", "unknown")), action)
                key = (normalized["protocol"], normalized["port"], normalized["source"])
                previous = seen.get(key)
                if previous and previous != action:
                    conflicts.append(f"{normalized['protocol']}/{normalized['port']} from {normalized['source']}")
                seen[key] = action
                (allow if action == "allow" else deny).append(normalized)
    if conflicts:
        raise PortPolicyError("E_PORT_POLICY_CONFLICT", "端口策略存在 allow/deny 冲突: " + ", ".join(conflicts))
    return {
        "schema_version": "1.0",
        "owner": "effective",
        "mode": mode,
        "allow": allow,
        "deny": deny,
    }


def _load_optional_policy(path: Path, expected_owner: str) -> dict[str, Any]:
    if not path.exists():
        return {**EMPTY_POLICY, "owner": expected_owner}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PortPolicyError("E_PORT_POLICY_SCHEMA", f"端口策略不是 JSON/YAML 子集: {path}") from exc
    if not isinstance(data, dict):
        raise PortPolicyError("E_PORT_POLICY_SCHEMA", "端口策略顶层必须是对象")
    if data.get("schema_version", "1.0") != "1.0":
        raise PortPolicyError("E_PORT_POLICY_SCHEMA", "端口策略 schema_version 必须是 1.0")
    owner = data.get("owner")
    if owner != expected_owner:
        raise PortPolicyError("E_PORT_POLICY_SCHEMA", f"端口策略 owner 必须是 {expected_owner}")
    for key in ("allow", "deny"):
        if key not in data:
            data[key] = []
        if not isinstance(data[key], list):
            raise PortPolicyError("E_PORT_POLICY_SCHEMA", f"{key} 必须是数组")
    return data


def _normalize_rule(rule: Any, owner: str, action: str) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise PortPolicyError("E_PORT_POLICY_SCHEMA", "端口规则必须是对象")
    protocol = str(rule.get("protocol", "")).lower()
    if protocol not in VALID_PROTOCOLS:
        raise PortPolicyError("E_PORT_POLICY_SCHEMA", "端口规则 protocol 必须是 tcp/udp")
    port = rule.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise PortPolicyError("E_PORT_POLICY_SCHEMA", "端口规则 port 必须是 1..65535")
    source = str(rule.get("source", "")).strip()
    if not _valid_source(source):
        raise PortPolicyError("E_PORT_POLICY_SCHEMA", "端口规则 source 必须是 any、IP 或 CIDR")
    return {
        "action": action,
        "protocol": protocol,
        "port": port,
        "source": source,
        "comment": str(rule.get("comment", "")),
        "owner": owner,
    }


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_source(source: str) -> bool:
    if source == "any":
        return True
    try:
        ipaddress.ip_network(source, strict=False)
    except ValueError:
        return False
    return True
