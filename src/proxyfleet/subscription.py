"""订阅状态解析和 Last Known Good 缓存。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
