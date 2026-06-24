"""订阅状态解析和 Last Known Good 缓存。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # PyYAML 是可选能力；缺失时使用内置简易解析器。
    yaml = None


class SubscriptionError(ValueError):
    """订阅响应不可用于更新 Provider。"""


@dataclass(frozen=True)
class SubscriptionStatus:
    provider_id: str
    freshness: str
    fetched_at: str | None
    upload_bytes: int | None
    download_bytes: int | None
    total_bytes: int | None
    remaining_bytes: int | None
    expire_at: str | None
    userinfo_source: str
    content_sha256: str | None
    last_error_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "provider_id": self.provider_id,
            "freshness": self.freshness,
            "fetched_at": self.fetched_at,
            "upload_bytes": self.upload_bytes,
            "download_bytes": self.download_bytes,
            "total_bytes": self.total_bytes,
            "remaining_bytes": self.remaining_bytes,
            "expire_at": self.expire_at,
            "userinfo_source": self.userinfo_source,
            "content_sha256": self.content_sha256,
            "last_error_code": self.last_error_code,
        }


@dataclass(frozen=True)
class SubscriptionFetchResult:
    """订阅刷新结果，body 为已校验可转换的原始 Provider 快照。"""

    body: bytes | None
    status: dict[str, Any]


def parse_subscription_userinfo(header: str | None) -> dict[str, int | None]:
    """解析 Subscription-Userinfo 头，缺失字段返回 None。"""

    values: dict[str, int | None] = {
        "upload": None,
        "download": None,
        "total": None,
        "expire": None,
    }
    if not header:
        return values

    for part in header.split(";"):
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        key = key.strip().lower()
        raw_value = raw_value.strip()
        if key not in values:
            continue
        if raw_value == "":
            values[key] = None
            continue
        try:
            parsed = int(raw_value)
        except ValueError as exc:
            raise SubscriptionError(f"Subscription-Userinfo 字段不是整数: {key}") from exc
        if parsed < 0:
            raise SubscriptionError(f"Subscription-Userinfo 字段不能为负数: {key}")
        values[key] = parsed
    return values


def validate_subscription_body(body: bytes) -> str:
    """校验订阅正文是否可作为 Provider 快照缓存。"""

    if not body or not body.strip():
        raise SubscriptionError("E_SUB_INVALID: 订阅正文为空")
    prefix = body.lstrip()[:128].lower()
    if prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html"):
        raise SubscriptionError("E_SUB_INVALID: 订阅正文疑似 HTML")
    return hashlib.sha256(body).hexdigest()


def parse_provider_snapshot(body: bytes) -> dict[str, Any]:
    """解析订阅正文并提取 Mihomo Provider 节点。

    订阅服务常见返回有两种：

    - 纯 provider 快照：顶层只有 `proxies`；
    - 完整 Clash/Mihomo 配置：顶层同时包含 `proxy-groups`、`rules` 等。

    ProxyFleet 只接收节点清单，订阅侧策略组和规则由 Master 本地配置统一管理，
    因此这里会提取顶层 `proxies` 并丢弃其它字段。
    """

    validate_subscription_body(body)
    text = body.decode("utf-8")
    data: Any
    data = _parse_structured_subscription(text)

    if not isinstance(data, dict):
        raise SubscriptionError("E_SUB_INVALID: 订阅配置必须是对象")
    proxies = data.get("proxies")
    if not isinstance(proxies, list) or not proxies:
        raise SubscriptionError("E_SUB_INVALID: 订阅配置缺少顶层 proxies")
    for proxy in proxies:
        if not isinstance(proxy, dict):
            raise SubscriptionError("E_SUB_INVALID: Provider 节点必须是对象")
        if not isinstance(proxy.get("name"), str) or not proxy["name"]:
            raise SubscriptionError("E_SUB_INVALID: Provider 节点缺少 name")
        if not isinstance(proxy.get("type"), str) or not proxy["type"]:
            raise SubscriptionError("E_SUB_INVALID: Provider 节点缺少 type")
        if not isinstance(proxy.get("server"), str) or not proxy["server"]:
            raise SubscriptionError("E_SUB_INVALID: Provider 节点缺少 server")
    return {"proxies": proxies}


def provider_snapshot_bytes(body: bytes, *, name_prefix: str = "") -> bytes:
    """将订阅正文转换为规范 JSON Provider 快照。"""

    snapshot = parse_provider_snapshot(body)
    normalized = dict(snapshot)
    proxies = []
    for proxy in snapshot["proxies"]:
        item = dict(proxy)
        if name_prefix and not item["name"].startswith(name_prefix):
            item["name"] = f"{name_prefix}{item['name']}"
        proxies.append(item)
    normalized["proxies"] = proxies
    return json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def fetch_subscription_url(url: str, *, timeout: float = 15.0) -> tuple[bytes, str | None]:
    """通过 HTTP 拉取订阅正文，返回 body 和 Subscription-Userinfo。"""

    request = urllib.request.Request(url, headers={"User-Agent": "ProxyFleet/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise SubscriptionError("E_SUB_FETCH: 订阅 HTTP 状态失败")
            header = response.headers.get("Subscription-Userinfo")
            return response.read(), header
    except urllib.error.HTTPError as exc:
        raise SubscriptionError("E_SUB_FETCH: 订阅 HTTP 状态失败") from exc
    except urllib.error.URLError as exc:
        raise SubscriptionError("E_SUB_FETCH: 订阅请求失败") from exc
    except TimeoutError as exc:
        raise SubscriptionError("E_SUB_FETCH: 订阅请求超时") from exc


def refresh_subscription_url(
    cache_dir: Path,
    provider_id: str,
    url: str,
    *,
    name_prefix: str = "",
    timeout: float = 15.0,
) -> SubscriptionFetchResult:
    """刷新订阅并维护 Last Known Good；失败时只标记 stale。"""

    try:
        body, header = fetch_subscription_url(url, timeout=timeout)
        snapshot = provider_snapshot_bytes(body, name_prefix=name_prefix)
        status = update_last_known_good(cache_dir, provider_id, header, snapshot).to_dict()
        return SubscriptionFetchResult(snapshot, status)
    except SubscriptionError as exc:
        error_code = _error_code(exc)
        status = mark_subscription_failure(cache_dir, provider_id, error_code)
        return SubscriptionFetchResult(None, status)


def build_subscription_status(
    provider_id: str,
    header: str | None,
    body: bytes | None,
    *,
    freshness: str = "fresh",
    fetched_at: str | None = None,
    last_error_code: str | None = None,
) -> SubscriptionStatus:
    """构造契约化订阅状态。"""

    info = parse_subscription_userinfo(header)
    content_sha256 = validate_subscription_body(body or b"") if body is not None else None
    upload = info["upload"]
    download = info["download"]
    total = info["total"]
    remaining = None
    if total is not None and upload is not None and download is not None:
        remaining = max(total - upload - download, 0)

    expire_at = None
    if info["expire"] is not None:
        expire_at = datetime.fromtimestamp(info["expire"], tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return SubscriptionStatus(
        provider_id=provider_id,
        freshness=freshness,
        fetched_at=fetched_at or _utc_now(),
        upload_bytes=upload,
        download_bytes=download,
        total_bytes=total,
        remaining_bytes=remaining,
        expire_at=expire_at,
        userinfo_source="header" if header else "absent",
        content_sha256=content_sha256,
        last_error_code=last_error_code,
    )


def update_last_known_good(cache_dir: Path, provider_id: str, header: str | None, body: bytes) -> SubscriptionStatus:
    """校验成功后原子写入 Provider 快照和状态。"""

    status = build_subscription_status(provider_id, header, body)
    provider_dir = cache_dir / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(provider_dir / "provider.snapshot", body)
    _atomic_write_json(provider_dir / "subscription-status.json", status.to_dict())
    return status


def fetch_subscription(url: str, timeout: float = 10.0) -> tuple[bytes, str | None]:
    """兼容旧调用名：从订阅 URL 拉取正文和用量头。"""

    return fetch_subscription_url(url, timeout=timeout)


def convert_subscription_to_provider(body: bytes) -> dict[str, Any]:
    """把已拉取订阅快照转换为 Mihomo file provider。

    当前实现支持两类 JSON/YAML 订阅正文：纯 provider 快照，或包含顶层
    `proxies` 的完整 Clash/Mihomo 配置。后者会丢弃订阅侧策略组和规则，
    仅保留节点清单。
    """

    return parse_provider_snapshot(body)


def refresh_subscription_provider(
    cache_dir: Path,
    provider_id: str,
    url: str,
    *,
    name_prefix: str = "",
    timeout: float = 10.0,
) -> tuple[dict[str, Any], SubscriptionStatus]:
    """拉取、校验并转换订阅 Provider；失败时使用 LKG。"""

    try:
        body, header = fetch_subscription_url(url, timeout=timeout)
        snapshot = provider_snapshot_bytes(body, name_prefix=name_prefix)
        provider = parse_provider_snapshot(snapshot)
        status = update_last_known_good(cache_dir, provider_id, header, snapshot)
        return provider, status
    except SubscriptionError as exc:
        status = mark_subscription_failure(cache_dir, provider_id, _error_code(exc))
        try:
            snapshot, _ = load_last_known_good(cache_dir, provider_id)
        except SubscriptionError:
            raise exc
        provider = parse_provider_snapshot(snapshot)
        return provider, SubscriptionStatus(
            provider_id=str(status["provider_id"]),
            freshness=str(status["freshness"]),
            fetched_at=status.get("fetched_at"),
            upload_bytes=status.get("upload_bytes"),
            download_bytes=status.get("download_bytes"),
            total_bytes=status.get("total_bytes"),
            remaining_bytes=status.get("remaining_bytes"),
            expire_at=status.get("expire_at"),
            userinfo_source=str(status.get("userinfo_source", "cache")),
            content_sha256=status.get("content_sha256"),
            last_error_code=status.get("last_error_code"),
        )


def load_last_known_good(cache_dir: Path, provider_id: str) -> tuple[bytes, dict[str, Any]]:
    """读取最后有效 Provider 快照和状态。"""

    provider_dir = cache_dir / provider_id
    snapshot = provider_dir / "provider.snapshot"
    status = provider_dir / "subscription-status.json"
    if not snapshot.exists() or not status.exists():
        raise SubscriptionError("E_SUB_FETCH: Last Known Good 不存在")
    return snapshot.read_bytes(), json.loads(status.read_text(encoding="utf-8"))


def mark_subscription_failure(cache_dir: Path, provider_id: str, error_code: str) -> dict[str, Any]:
    """订阅失败时返回 stale 状态，不覆盖 Provider 快照。"""

    provider_dir = cache_dir / provider_id
    try:
        _, status = load_last_known_good(cache_dir, provider_id)
    except SubscriptionError:
        status = {
            "schema_version": "1.0",
            "provider_id": provider_id,
            "freshness": "unknown",
            "fetched_at": None,
            "upload_bytes": None,
            "download_bytes": None,
            "total_bytes": None,
            "remaining_bytes": None,
            "expire_at": None,
            "userinfo_source": "absent",
            "content_sha256": None,
            "last_error_code": error_code,
        }
    else:
        status["freshness"] = "stale"
        status["last_error_code"] = error_code
    _atomic_write_json(provider_dir / "subscription-status.json", status)
    return status


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    _atomic_write(path, (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_structured_subscription(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if yaml is not None:
        try:
            return yaml.safe_load(text)
        except Exception as exc:
            raise SubscriptionError("E_SUB_INVALID: 订阅 YAML 解析失败") from exc
    return _parse_yaml(text)


def _parse_yaml(text: str) -> Any:
    """解析受限 Mihomo provider YAML 子集。

    这里故意不引入 PyYAML 依赖。复杂 YAML、锚点、多行字符串等都交给后续锁定
    subconverter；当前 fallback 只支持测试和手写 provider 常见的 `proxies:` 列表，
    并允许在 `proxies:` 前后存在其它顶层字段。
    """

    proxies: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_proxies = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if not line.startswith(" ") and stripped.endswith(":"):
            if stripped == "proxies:":
                in_proxies = True
                continue
            if in_proxies:
                break
            continue
        if stripped == "proxies:":
            in_proxies = True
            continue
        if not in_proxies:
            continue
        if stripped.startswith("- "):
            if current is not None:
                proxies.append(current)
            current = {}
            remainder = stripped[2:].strip()
            if remainder:
                key, value = _parse_yaml_pair(remainder)
                current[key] = value
            continue
        if current is None:
            raise SubscriptionError("E_SUB_INVALID: Provider YAML 节点格式无效")
        key, value = _parse_yaml_pair(stripped)
        current[key] = value
    if current is not None:
        proxies.append(current)
    return {"proxies": proxies}


def _parse_yaml_pair(raw: str) -> tuple[str, Any]:
    if ":" not in raw:
        raise SubscriptionError("E_SUB_INVALID: Provider YAML 字段格式无效")
    key, value = raw.split(":", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        raise SubscriptionError("E_SUB_INVALID: Provider YAML 字段名为空")
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return key, value[1:-1]
    if value.isdigit():
        return key, int(value)
    return key, value


def _error_code(exc: object) -> str:
    message = str(exc)
    if message.startswith("E_SUB_INVALID"):
        return "E_SUB_INVALID"
    if message.startswith("E_SUB_FETCH"):
        return "E_SUB_FETCH"
    return "E_SUB_INVALID"
