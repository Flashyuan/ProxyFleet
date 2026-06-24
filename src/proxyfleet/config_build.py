"""配置源校验与 release 构建 POC。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .component_locks import assert_valid_lock_file, load_lock_file
from .subscription import SubscriptionError, refresh_subscription_provider


class ConfigBuildError(ValueError):
    """配置源或 release 构建失败。"""


@dataclass(frozen=True)
class BuildOptions:
    source_dir: Path
    output_dir: Path
    revision: int
    source_git_commit: str
    component_locks: Path
    cache_dir: Path | None = None
    subscription_timeout: float = 10.0


def build_release(options: BuildOptions) -> Path:
    """构建不可变 release 目录并返回 release 路径。"""

    assert_valid_lock_file(options.component_locks)
    source_dir = options.source_dir.resolve()
    output_dir = options.output_dir.resolve()
    release_dir = output_dir / f"{options.revision:06d}"
    if release_dir.exists():
        raise ConfigBuildError(f"release 已存在: {release_dir}")

    source = load_config_source(source_dir)
    mihomo_version = _component_version(options.component_locks, "mihomo")

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=output_dir) as tmp_name:
        staging = Path(tmp_name)
        _write_release_files(
            staging,
            source_dir,
            source,
            options.cache_dir or (output_dir / ".subscription-cache"),
            options.subscription_timeout,
        )
        manifest = _build_manifest(
            staging,
            revision=options.revision,
            source_git_commit=options.source_git_commit,
            mihomo_version=mihomo_version,
            provider_revision=options.revision,
        )
        _write_json(staging / "manifest.json", manifest)
        manifest_hash = _sha256_file(staging / "manifest.json")
        (staging / "manifest.sha256").write_text(f"{manifest_hash}  manifest.json\n", encoding="utf-8")
        staging.rename(release_dir)
    return release_dir


def load_config_source(source_dir: Path) -> dict[str, Any]:
    """读取并校验配置源。"""

    providers = _read_json(source_dir / "providers.json")
    groups = _read_json(source_dir / "groups.json")
    rules = _read_json(source_dir / "rules.json")
    base = _read_json(source_dir / "base.json")

    _assert_schema(providers, "providers.json")
    _assert_schema(groups, "groups.json")
    _assert_schema(rules, "rules.json")
    _assert_schema(base, "base.json")
    _validate_providers(providers, source_dir)
    _validate_groups(groups, providers)
    _validate_rules(rules, groups)

    return {
        "providers": providers,
        "groups": groups,
        "rules": rules,
        "base": base,
    }


def verify_release(release_dir: Path) -> None:
    """验证 release manifest 中记录的文件哈希。"""

    root = release_dir.resolve()
    manifest_path = root / "manifest.json"
    manifest_sha_path = root / "manifest.sha256"
    if not manifest_sha_path.exists():
        raise ConfigBuildError("manifest.sha256 缺失")
    expected_manifest_hash = manifest_sha_path.read_text(encoding="utf-8").split()[0]
    actual_manifest_hash = _sha256_file(manifest_path)
    if actual_manifest_hash != expected_manifest_hash:
        raise ConfigBuildError("manifest.sha256 与 manifest.json 不匹配")

    manifest = _read_json(manifest_path)
    _assert_schema(manifest, "manifest.json")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ConfigBuildError("manifest.files 必须是非空数组")
    for item in files:
        relative = _safe_relative_path(_require_str(item, "path"))
        path = root / relative
        if not path.exists() or not path.is_file():
            raise ConfigBuildError(f"manifest 文件缺失: {relative.as_posix()}")
        expected = _require_str(item, "sha256")
        actual = _sha256_file(path)
        if actual != expected:
            raise ConfigBuildError(f"manifest 哈希不符: {relative.as_posix()}")
        expected_size = item.get("size")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise ConfigBuildError(f"manifest size 无效: {relative.as_posix()}")
        if path.stat().st_size != expected_size:
            raise ConfigBuildError(f"manifest size 不符: {relative.as_posix()}")


def _write_release_files(staging: Path, source_dir: Path, source: dict[str, Any], cache_dir: Path, subscription_timeout: float) -> None:
    providers_dir = staging / "providers"
    rules_dir = staging / "rules"
    providers_dir.mkdir(parents=True)
    rules_dir.mkdir(parents=True)

    for provider in source["providers"]["providers"]:
        output = _safe_relative_path(provider["output"])
        if output.parts[0] != "providers":
            raise ConfigBuildError("Provider 输出必须位于 providers/ 下")
        target_path = staging / output
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if provider["kind"] == "local_file":
            source_path = _safe_join(source_dir, provider["source"])
            shutil.copyfile(source_path, target_path)
        elif provider["kind"] == "subscription":
            url = _subscription_url(provider)
            try:
                provider_data, status = refresh_subscription_provider(
                    cache_dir,
                    provider["id"],
                    url,
                    name_prefix=provider.get("name_prefix", ""),
                    timeout=subscription_timeout,
                )
            except SubscriptionError as exc:
                raise ConfigBuildError(str(exc)) from exc
            _write_json(target_path, provider_data)
            status_path = staging / "subscription-status" / f"{provider['id']}.json"
            _write_json(status_path, status.to_dict())
        else:
            raise ConfigBuildError(f"不支持的 Provider 类型: {provider['kind']}")

    for rule in source["rules"].get("rule_providers", []):
        output = _safe_relative_path(rule["output"])
        if output.parts[0] != "rules":
            raise ConfigBuildError("Rule 输出必须位于 rules/ 下")
        source_path = _safe_join(source_dir, rule["source"])
        target_path = staging / output
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)

    config = _compile_config(source)
    _write_json(staging / "config.yaml", config)


def _compile_config(source: dict[str, Any]) -> dict[str, Any]:
    base = dict(source["base"].get("config", {}))
    providers = {
        item["id"]: {
            "type": "file",
            "path": item["output"],
            "health-check": item.get("health_check", {"enable": False}),
        }
        for item in source["providers"]["providers"]
        if item.get("enabled", True)
    }
    groups = []
    for group in source["groups"]["groups"]:
        compiled = {
            "name": group["name"],
            "type": group["type"],
            "use": list(group.get("use", [])),
        }
        groups.append(compiled)

    rules = []
    for item in source["rules"]["order"]:
        if "rule_provider" in item:
            rules.append(f"RULE-SET,{item['rule_provider']},{item['target']}")
        elif "match" in item:
            rules.append(f"{item['match']},{item['target']}")
        else:
            raise ConfigBuildError("规则条目必须包含 rule_provider 或 match")

    rule_providers = {
        item["id"]: {
            "type": "file",
            "behavior": item.get("behavior", "classical"),
            "path": item["output"],
        }
        for item in source["rules"].get("rule_providers", [])
    }

    base["proxy-providers"] = providers
    base["proxy-groups"] = groups
    base["rule-providers"] = rule_providers
    base["rules"] = rules
    return base


def _build_manifest(
    staging: Path,
    revision: int,
    source_git_commit: str,
    mihomo_version: str,
    provider_revision: int,
) -> dict[str, Any]:
    files = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(staging).as_posix()
        if relative == "manifest.json":
            continue
        files.append({"path": relative, "sha256": _sha256_file(path), "size": path.stat().st_size})

    return {
        "schema_version": "1.0",
        "release_revision": revision,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_git_commit": source_git_commit,
        "mihomo_version": mihomo_version,
        "provider_revision": provider_revision,
        "files": files,
    }


def _validate_providers(data: dict[str, Any], source_dir: Path) -> None:
    providers = data.get("providers")
    if not isinstance(providers, list) or not providers:
        raise ConfigBuildError("providers 必须是非空数组")
    seen: set[str] = set()
    for provider in providers:
        provider_id = _require_str(provider, "id")
        if provider_id in seen:
            raise ConfigBuildError(f"Provider id 重复: {provider_id}")
        seen.add(provider_id)
        kind = provider.get("kind")
        if kind not in {"local_file", "subscription"}:
            raise ConfigBuildError(f"不支持的 Provider 类型: {kind}")
        _safe_relative_path(_require_str(provider, "output"))
        if kind == "local_file":
            _safe_join(source_dir, _require_str(provider, "source"))
        else:
            _require_subscription_secret_ref(provider)


def _validate_groups(data: dict[str, Any], providers: dict[str, Any]) -> None:
    provider_ids = {item["id"] for item in providers["providers"]}
    groups = data.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ConfigBuildError("groups 必须是非空数组")
    fleet = None
    for group in groups:
        name = _require_str(group, "name")
        if name == "FLEET_PROXY":
            fleet = group
        for provider_id in group.get("use", []):
            if provider_id not in provider_ids:
                raise ConfigBuildError(f"策略组引用未知 Provider: {provider_id}")
    if not fleet:
        raise ConfigBuildError("必须定义 FLEET_PROXY 策略组")
    if fleet.get("type") != "select":
        raise ConfigBuildError("FLEET_PROXY 必须是 select 类型")


def _validate_rules(data: dict[str, Any], groups: dict[str, Any]) -> None:
    group_names = {item["name"] for item in groups["groups"]}
    rule_provider_ids = {item["id"] for item in data.get("rule_providers", [])}
    order = data.get("order")
    if not isinstance(order, list) or not order:
        raise ConfigBuildError("rules.order 必须是非空数组")
    for item in data.get("rule_providers", []):
        _safe_relative_path(_require_str(item, "output"))
    for item in order:
        target = _require_str(item, "target")
        if target not in group_names and target not in {"DIRECT", "REJECT"}:
            raise ConfigBuildError(f"规则目标未知: {target}")
        if "rule_provider" in item and item["rule_provider"] not in rule_provider_ids:
            raise ConfigBuildError(f"规则引用未知 rule_provider: {item['rule_provider']}")


def _component_version(component_locks: Path, name: str) -> str:
    data = load_lock_file(component_locks)
    for component in data.get("components", []):
        if component.get("name") == name:
            return str(component["version"])
    raise ConfigBuildError(f"组件锁缺少 {name}")


def _subscription_url(provider: dict[str, Any]) -> str:
    secret_ref = _require_subscription_secret_ref(provider)
    value = os.environ.get(secret_ref)
    if not value:
        raise ConfigBuildError(f"订阅 URL 环境变量未设置: {secret_ref}")
    if "://" not in value:
        raise ConfigBuildError(f"订阅 URL 无效: {secret_ref}")
    return value


def _require_subscription_secret_ref(provider: dict[str, Any]) -> str:
    value = provider.get("secret_ref", provider.get("env"))
    if not isinstance(value, str) or not value:
        raise ConfigBuildError("subscription Provider 必须设置 secret_ref 或 env")
    return value


def _assert_schema(data: dict[str, Any], filename: str) -> None:
    if data.get("schema_version") != "1.0":
        raise ConfigBuildError(f"{filename} schema_version 不受支持")


def _require_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigBuildError(f"缺少字段: {key}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise ConfigBuildError(f"缺少配置源文件: {path.name}") from exc
    if not isinstance(data, dict):
        raise ConfigBuildError(f"配置源必须是对象: {path.name}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_relative_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigBuildError(f"路径不得逃逸 release/source 目录: {raw}")
    return path


def _safe_join(root: Path, raw: str) -> Path:
    relative = _safe_relative_path(raw)
    path = (root / relative).resolve()
    if root.resolve() not in path.parents and path != root.resolve():
        raise ConfigBuildError(f"路径不得逃逸 source 目录: {raw}")
    if not path.exists():
        raise ConfigBuildError(f"源文件不存在: {raw}")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
