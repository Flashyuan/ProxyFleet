"""组件版本锁定清单校验。

本模块只使用 Python 标准库，避免在供应链基线阶段引入新的第三方依赖。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FLOATING_VERSION_WORDS = {"latest", "stable", "current", "master", "main", "dev"}
HASH_RE = re.compile(r"^[a-fA-F0-9]{64}$")
DIGEST_RE = re.compile(r"^sha256:[a-fA-F0-9]{64}$")


class ComponentLockError(ValueError):
    """组件锁定清单不满足 fail-closed 约束。"""


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


def load_lock_file(path: str | Path) -> dict[str, Any]:
    """读取 JSON 格式的组件锁定清单。"""

    lock_path = Path(path)
    with lock_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ComponentLockError("组件锁定清单根节点必须是对象")
    return data


def validate_lock_file(path: str | Path) -> list[ValidationIssue]:
    """校验组件锁定清单，返回所有问题。"""

    return validate_lock_data(load_lock_file(path))


def validate_lock_data(data: dict[str, Any]) -> list[ValidationIssue]:
    """校验已解析的组件锁定清单。"""

    issues: list[ValidationIssue] = []
    _require(data, "schema_version", "root", issues)

    policy = data.get("policy")
    if not isinstance(policy, dict):
        issues.append(ValidationIssue("policy", "policy 必须是对象"))
    else:
        if policy.get("no_floating_versions") is not True:
            issues.append(ValidationIssue("policy.no_floating_versions", "必须禁止浮动版本"))
        if policy.get("no_automatic_updates") is not True:
            issues.append(ValidationIssue("policy.no_automatic_updates", "必须禁止自动更新"))
        if policy.get("fail_closed_on_missing_integrity") is not True:
            issues.append(ValidationIssue("policy.fail_closed_on_missing_integrity", "缺失完整性信息时必须 fail-closed"))

    components = data.get("components")
    if not isinstance(components, list) or not components:
        issues.append(ValidationIssue("components", "components 必须是非空数组"))
        return issues

    seen_names: set[str] = set()
    for index, component in enumerate(components):
        path = f"components[{index}]"
        if not isinstance(component, dict):
            issues.append(ValidationIssue(path, "组件条目必须是对象"))
            continue
        _validate_component(component, path, seen_names, issues)
    return issues


def assert_valid_lock_file(path: str | Path) -> None:
    """校验失败时抛出异常，供 CLI 和 release gate 使用。"""

    issues = validate_lock_file(path)
    if issues:
        details = "\n".join(f"- {issue.path}: {issue.message}" for issue in issues)
        raise ComponentLockError(f"组件锁定清单校验失败:\n{details}")


def _validate_component(
    component: dict[str, Any],
    path: str,
    seen_names: set[str],
    issues: list[ValidationIssue],
) -> None:
    name = _require(component, "name", path, issues)
    kind = _require(component, "kind", path, issues)
    version = _require(component, "version", path, issues)
    status = component.get("status", "candidate")

    if isinstance(name, str):
        if name in seen_names:
            issues.append(ValidationIssue(f"{path}.name", "组件 name 必须唯一"))
        seen_names.add(name)

    if isinstance(version, str):
        normalized = version.strip().lower()
        if not normalized:
            issues.append(ValidationIssue(f"{path}.version", "version 不能为空"))
        if normalized in FLOATING_VERSION_WORDS or normalized.endswith("-snapshot"):
            issues.append(ValidationIssue(f"{path}.version", "禁止使用浮动版本"))

    install_policy = component.get("install_policy")
    if not isinstance(install_policy, dict):
        issues.append(ValidationIssue(f"{path}.install_policy", "install_policy 必须是对象"))
    else:
        if install_policy.get("allow_auto_update") is not False:
            issues.append(ValidationIssue(f"{path}.install_policy.allow_auto_update", "安装后不得自动更新"))
        if install_policy.get("require_exact_version") is not True:
            issues.append(ValidationIssue(f"{path}.install_policy.require_exact_version", "必须要求精确版本"))
        if install_policy.get("hold_after_install") is not True:
            issues.append(ValidationIssue(f"{path}.install_policy.hold_after_install", "安装后必须 hold/pin"))

    architectures = component.get("architectures", component.get("architecture"))
    if not architectures:
        issues.append(ValidationIssue(f"{path}.architecture", "必须声明目标架构"))

    if status == "installable":
        _validate_installable_integrity(component, str(kind), path, issues)


def _validate_installable_integrity(
    component: dict[str, Any],
    kind: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    integrity = component.get("integrity")
    if not isinstance(integrity, dict):
        issues.append(ValidationIssue(f"{path}.integrity", "installable 组件必须声明完整性信息"))
        return

    normalized_kind = kind.replace("_", "-")

    if normalized_kind in {"container-image", "base-image"}:
        digest = integrity.get("digest")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            issues.append(ValidationIssue(f"{path}.integrity.digest", "installable 镜像必须固定 sha256 digest"))
        return

    if normalized_kind in {"binary", "archive", "ruleset", "data-file"}:
        sha256 = integrity.get("sha256")
        if not isinstance(sha256, str) or not HASH_RE.fullmatch(sha256):
            issues.append(ValidationIssue(f"{path}.integrity.sha256", "installable 二进制/归档必须固定 SHA-256"))
        return

    if normalized_kind in {"apt-package", "package"}:
        if integrity.get("package_version_exact") is not True:
            issues.append(ValidationIssue(f"{path}.integrity.package_version_exact", "apt 包必须固定精确版本"))
        if not integrity.get("repository_signature"):
            issues.append(ValidationIssue(f"{path}.integrity.repository_signature", "apt 仓库必须有签名校验"))


def _require(
    obj: dict[str, Any],
    key: str,
    path: str,
    issues: list[ValidationIssue],
) -> Any:
    value = obj.get(key)
    if value in (None, ""):
        issues.append(ValidationIssue(f"{path}.{key}", "必填字段缺失"))
    return value
