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


PROXY_MODE_TPROXY = "tproxy"
PROXY_MODE_EXPLICIT = "explicit-proxy"
VALID_PROXY_MODES = {PROXY_MODE_TPROXY, PROXY_MODE_EXPLICIT}

DEFAULT_TPROXY_ROUTE_EXCLUDES = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "224.0.0.0/4",
    "240.0.0.0/4",
]
TUN_ROUTE_EXCLUDES = DEFAULT_TPROXY_ROUTE_EXCLUDES
DEFAULT_TPROXY_DIRECT_RULES = [
    "IP-CIDR,0.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,114.114.114.114/32,DIRECT,no-resolve",
    "IP-CIDR,119.29.29.29/32,DIRECT,no-resolve",
    "IP-CIDR,180.76.76.76/32,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,223.5.5.5/32,DIRECT,no-resolve",
    "IP-CIDR,223.6.6.6/32,DIRECT,no-resolve",
    "IP-CIDR,224.0.0.0/4,DIRECT,no-resolve",
    "IP-CIDR,240.0.0.0/4,DIRECT,no-resolve",
]
DEFAULT_TPROXY_DIRECT_DOMAINS = [
    "126.com",
    "163.com",
    "alicdn.com",
    "aliyun.com",
    "aliyuncs.com",
    "alipay.com",
    "baidu.com",
    "bdimg.com",
    "bdstatic.com",
    "bilibili.com",
    "bytedance.com",
    "byteimg.com",
    "cdn.bcebos.com",
    "chinaunicom.cn",
    "cluster.local",
    "cn",
    "cnblogs.com",
    "csdn.net",
    "douyin.com",
    "gitee.com",
    "gitee.io",
    "gitcode.com",
    "gtimg.com",
    "huawei.com",
    "huaweicloud.com",
    "jd.com",
    "local",
    "localhost",
    "mi.com",
    "mmstat.com",
    "netease.com",
    "npmmirror.com",
    "oschina.net",
    "qcloud.com",
    "qq.com",
    "sina.com.cn",
    "sogou.com",
    "sohu.com",
    "svc",
    "taobao.com",
    "tencent.com",
    "tencent-cloud.com",
    "tmall.com",
    "tsinghua.edu.cn",
    "ustc.edu.cn",
    "weibo.com",
    "weixin.qq.com",
    "zhihu.com",
]


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
    tproxy_excludes = _load_tproxy_excludes(source_dir)

    _assert_schema(providers, "providers.json")
    _assert_schema(groups, "groups.json")
    _assert_schema(rules, "rules.json")
    _assert_schema(base, "base.json")
    if tproxy_excludes:
        _assert_schema(tproxy_excludes, "tproxy-excludes")
    _validate_providers(providers, source_dir)
    _validate_groups(groups, providers)
    _validate_rules(rules, groups)
    _validate_tproxy_excludes(tproxy_excludes)

    return {
        "providers": providers,
        "groups": groups,
        "rules": rules,
        "base": base,
        "tproxy_excludes": tproxy_excludes,
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
    proxy_mode = _base_proxy_mode(source["base"])
    tproxy_excludes = source.get("tproxy_excludes", {})
    _apply_proxy_mode(base, proxy_mode, tproxy_excludes)
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

    rules = _tproxy_direct_rules(proxy_mode, tproxy_excludes)
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
    base["rules"] = _dedupe_str(rules)
    return base


def _base_proxy_mode(base_source: dict[str, Any]) -> str:
    mode = str(base_source.get("proxy_mode", PROXY_MODE_TPROXY)).strip()
    if mode == "mixed":
        mode = PROXY_MODE_EXPLICIT
    if mode not in VALID_PROXY_MODES:
        raise ConfigBuildError(f"proxy_mode 只支持: {', '.join(sorted(VALID_PROXY_MODES))}")
    return mode


def _apply_proxy_mode(config: dict[str, Any], proxy_mode: str, tproxy_excludes: dict[str, Any] | None = None) -> None:
    """为 release 注入运行模式；tproxy 是强制透明代理模式。"""

    config.setdefault("mixed-port", 7890)
    config.setdefault("external-controller", "127.0.0.1:9090")
    config.setdefault("mode", "rule")
    if proxy_mode != PROXY_MODE_TPROXY:
        return

    # tproxy 是 Master 的显式运行模式选择，必须覆盖订阅源中关闭 TUN/TProxy 的字段。
    config["tproxy-port"] = 7893
    excludes = _dedupe_str(DEFAULT_TPROXY_ROUTE_EXCLUDES + _string_list((tproxy_excludes or {}).get("route_exclude_address")))

    tun = dict(config.get("tun", {})) if isinstance(config.get("tun"), dict) else {}
    tun["enable"] = True
    tun["stack"] = "system"
    tun["auto-route"] = True
    tun["auto-redirect"] = False
    tun["auto-detect-interface"] = True
    tun["strict-route"] = False
    tun["dns-hijack"] = ["any:53"]
    tun["route-exclude-address"] = excludes
    config["tun"] = tun

    dns = dict(config.get("dns", {})) if isinstance(config.get("dns"), dict) else {}
    dns["enable"] = True
    dns.setdefault("listen", "127.0.0.1:1053")
    dns.setdefault("enhanced-mode", "fake-ip")
    dns.setdefault("fake-ip-range", "198.18.0.1/16")
    dns.setdefault("nameserver", ["https://223.5.5.5/dns-query", "https://1.1.1.1/dns-query"])
    # TProxy 首次收敛不能依赖启动时在线下载 MMDB；fallback-filter.geoip 会触发
    # GeoIP 初始化，网络不佳时会让 Mihomo fatal，导致 Minion 无法进入可控状态。
    dns["fallback"] = []
    dns["fallback-filter"] = {
        "geoip": False,
        "ipcidr": [],
        "domain": [],
    }
    config["dns"] = dns
    _assert_tproxy_config(config)


def _assert_tproxy_config(config: dict[str, Any]) -> None:
    tun = config.get("tun")
    dns = config.get("dns")
    if config.get("tproxy-port") != 7893:
        raise ConfigBuildError("tproxy release 必须启用 tproxy-port=7893")
    if not isinstance(tun, dict) or tun.get("enable") is not True or tun.get("auto-route") is not True:
        raise ConfigBuildError("tproxy release 必须启用 tun.enable 和 tun.auto-route")
    if not isinstance(dns, dict):
        raise ConfigBuildError("tproxy release 必须包含 dns 配置")
    fallback_filter = dns.get("fallback-filter")
    if dns.get("fallback") != [] or not isinstance(fallback_filter, dict) or fallback_filter.get("geoip") is not False:
        raise ConfigBuildError("tproxy release 必须关闭 DNS fallback GeoIP/MMDB 启动依赖")


def _tproxy_direct_rules(proxy_mode: str, tproxy_excludes: dict[str, Any] | None) -> list[str]:
    excludes = tproxy_excludes or {}
    rules: list[str] = []
    if proxy_mode == PROXY_MODE_TPROXY:
        rules.extend(DEFAULT_TPROXY_DIRECT_RULES)
        rules.extend(f"DOMAIN-SUFFIX,{domain},DIRECT" for domain in DEFAULT_TPROXY_DIRECT_DOMAINS)
    rules.extend(_string_list(excludes.get("direct_rules")))
    rules.extend(f"DOMAIN-SUFFIX,{domain},DIRECT" for domain in _string_list(excludes.get("direct_domains")))
    return _dedupe_str(rules)


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


def _validate_tproxy_excludes(data: dict[str, Any]) -> None:
    for field in ("route_exclude_address", "direct_rules", "direct_domains"):
        value = data.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ConfigBuildError(f"tproxy-excludes {field} 必须是字符串数组")


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


def _load_tproxy_excludes(source_dir: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {"schema_version": "1.0"}
    for name in ("tproxy-excludes.json", "tproxy-excludes.yaml", "tproxy-excludes.yml"):
        path = source_dir / name
        if not path.exists():
            continue
        data = _read_json(path) if path.suffix == ".json" else _read_simple_yaml(path)
        _assert_schema(data, name)
        for field in ("route_exclude_address", "direct_rules", "direct_domains"):
            merged[field] = _dedupe_str(_string_list(merged.get(field)) + _string_list(data.get(field)))
    return merged


def _read_simple_yaml(path: Path) -> dict[str, Any]:
    """读取 tproxy-excludes 使用的简单 YAML 子集，避免为三组数组引入新依赖。"""

    result: dict[str, Any] = {}
    current_key: str | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ConfigBuildError(f"缺少配置源文件: {path.name}") from exc
    for line in lines:
        raw = line.split("#", 1)[0].rstrip()
        if not raw.strip():
            continue
        if not raw.startswith((" ", "\t")) and ":" in raw:
            key, value = raw.split(":", 1)
            key = key.strip()
            value = _strip_yaml_scalar(value.strip())
            if value:
                result[key] = value
                current_key = None
            else:
                result[key] = []
                current_key = key
            continue
        if current_key and raw.lstrip().startswith("- "):
            result[current_key].append(_strip_yaml_scalar(raw.lstrip()[2:].strip()))
            continue
        raise ConfigBuildError(f"tproxy-excludes YAML 仅支持顶层字段和字符串数组: {path.name}")
    if not isinstance(result, dict):
        raise ConfigBuildError(f"配置源必须是对象: {path.name}")
    return result


def _strip_yaml_scalar(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]


def _dedupe_str(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


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
