"""ProxyFleet 受控自更新实现。

本模块只使用标准库，负责 update manifest 校验、路径范围校验、下载、SHA-256
校验、备份、原子替换和失败回滚。脚本层只做 TUI/命令封装。
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen


class UpdateError(Exception):
    """自更新错误，携带稳定错误码。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


MASTER_ALLOWLIST = [
    "README.md",
    "component-locks.json",
    "update-manifest.json",
    "scripts/proxyfleet-master.sh",
    "scripts/proxyfleet-minion.sh",
    "src/**",
    "salt/**",
    "docs/**",
]

MASTER_DENYLIST = [
    ".env.proxyfleet",
    "config-src/**",
    "runtime/**",
    "releases/**",
    "cache/**",
    "providers-cache/**",
    "subscriptions-cache/**",
]

MINION_ALLOWLIST = [
    "scripts/proxyfleet-minion.sh",
]

MINION_DENYLIST = [
    "runtime/**",
    "releases/**",
    "config-src/**",
]

ABSOLUTE_DENYLIST = [
    "/etc/salt/**",
    "/etc/proxyfleet/current/**",
    "/etc/proxyfleet/managed/**",
    "/etc/proxyfleet/effective/**",
    "/etc/proxyfleet/local/port-policy.yaml",
    "/etc/proxyfleet/local/options.json",
    "/usr/local/bin/mihomo",
    "/etc/systemd/system/mihomo.service",
    "/etc/apt/**",
    "/etc/systemd/**",
    "/srv/proxyfleet/salt/pillar/**",
]


@dataclass(frozen=True)
class UpdateContext:
    role: str
    install_root: Path
    state_path: Path
    manifest_source: str
    current_version: str = "unknown"
    current_commit: str = "unknown"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(source: str, timeout: float = 10.0) -> bytes:
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        if parsed.username or parsed.password:
            raise UpdateError("E_UPDATE_UNTRUSTED_SOURCE", "更新 URL 不得包含凭据")
        if parsed.scheme != "https":
            raise UpdateError("E_UPDATE_UNTRUSTED_SOURCE", "远程更新 URL 必须使用 https")
        with urlopen(source, timeout=timeout) as response:  # noqa: S310 - URL 已限制为 https/file。
            return response.read()
    if parsed.scheme == "file":
        return Path(parsed.path).read_bytes()
    if parsed.scheme:
        raise UpdateError("E_UPDATE_UNTRUSTED_SOURCE", f"不支持的更新 URL 协议：{parsed.scheme}")
    return Path(source).read_bytes()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UpdateError("E_UPDATE_MANIFEST", f"JSON 无效：{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise UpdateError("E_UPDATE_MANIFEST", f"JSON 顶层必须是对象：{path}")
    return payload


def load_update_state(path: Path, current_version: str = "unknown", current_commit: str = "unknown") -> dict[str, Any]:
    payload = _load_json(path)
    if not payload:
        payload = {"schema_version": "1.0"}
    payload.setdefault("installed_version", current_version)
    payload.setdefault("installed_commit", current_commit)
    payload.setdefault("suppressed_versions", [])
    return payload


def write_update_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def load_manifest(source: str) -> tuple[dict[str, Any], str]:
    try:
        raw = _read_bytes(source)
    except OSError as exc:
        raise UpdateError("E_UPDATE_DOWNLOAD", f"无法读取更新清单：{exc}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("E_UPDATE_MANIFEST", f"更新清单 JSON 无效：{exc}") from exc
    if not isinstance(manifest, dict):
        raise UpdateError("E_UPDATE_MANIFEST", "更新清单顶层必须是对象")
    validate_manifest(manifest)
    return manifest, _sha256_bytes(raw)


def validate_manifest(manifest: dict[str, Any]) -> None:
    schema = str(manifest.get("schema_version", ""))
    if schema.split(".", 1)[0] != "1":
        raise UpdateError("E_UPDATE_MANIFEST", f"不支持的更新清单 schema：{schema}")
    if manifest.get("product") != "proxyfleet":
        raise UpdateError("E_UPDATE_MANIFEST", "更新清单 product 必须是 proxyfleet")
    commit = str(manifest.get("commit", ""))
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        raise UpdateError("E_UPDATE_MANIFEST", "更新清单 commit 必须是可追溯 Git SHA")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise UpdateError("E_UPDATE_MANIFEST", "更新清单 assets 不能为空")
    for item in assets:
        if not isinstance(item, dict):
            raise UpdateError("E_UPDATE_MANIFEST", "asset 必须是对象")
        role = item.get("role")
        if role not in ("master", "minion", "common"):
            raise UpdateError("E_UPDATE_MANIFEST", f"asset role 无效：{role}")
        path = item.get("path")
        if not isinstance(path, str) or not path:
            raise UpdateError("E_UPDATE_MANIFEST", "asset path 不能为空")
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise UpdateError("E_UPDATE_SCOPE", f"asset path 必须是安装根内相对路径：{path}")
        url = str(item.get("url", ""))
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "file"):
            raise UpdateError("E_UPDATE_UNTRUSTED_SOURCE", f"asset URL 协议无效：{parsed.scheme}")
        if parsed.username or parsed.password:
            raise UpdateError("E_UPDATE_UNTRUSTED_SOURCE", "asset URL 不得包含凭据")
        if parsed.netloc == "raw.githubusercontent.com":
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 4 and parts[2] in {"main", "master"}:
                raise UpdateError("E_UPDATE_UNTRUSTED_SOURCE", "asset URL 不得使用 GitHub raw 浮动分支")
        sha = item.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            raise UpdateError("E_UPDATE_MANIFEST", f"asset sha256 无效：{path}")


def _normalize_relative(path: str) -> str:
    posix = Path(path).as_posix().strip("/")
    if not posix or Path(posix).is_absolute() or ".." in Path(posix).parts:
        raise UpdateError("E_UPDATE_SCOPE", f"更新路径非法：{path}")
    return posix


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def assert_asset_scope(role: str, asset_path: str) -> str:
    rel = _normalize_relative(asset_path)
    if role == "master":
        allowlist = MASTER_ALLOWLIST
        denylist = MASTER_DENYLIST
    elif role == "minion":
        allowlist = MINION_ALLOWLIST
        denylist = MINION_DENYLIST
    else:
        raise UpdateError("E_UPDATE_SCOPE", f"未知更新角色：{role}")
    if _matches_any(rel, denylist):
        raise UpdateError("E_UPDATE_SCOPE", f"更新路径命中 denylist：{rel}")
    if not _matches_any(rel, allowlist):
        raise UpdateError("E_UPDATE_SCOPE", f"更新路径未命中 allowlist：{rel}")
    return rel


def assets_for_role(manifest: dict[str, Any], role: str) -> list[dict[str, Any]]:
    selected = []
    for item in manifest.get("assets", []):
        if item.get("role") in (role, "common"):
            assert_asset_scope(role, str(item["path"]))
            selected.append(item)
    if not selected:
        raise UpdateError("E_UPDATE_MANIFEST", f"更新清单没有适用于 {role} 的资产")
    return selected


def check_update(context: UpdateContext, *, respect_suppressed: bool = False) -> dict[str, Any]:
    manifest, manifest_sha = load_manifest(context.manifest_source)
    state = load_update_state(context.state_path, context.current_version, context.current_commit)
    remote_version = str(manifest.get("version", "unknown"))
    remote_commit = str(manifest.get("commit", "unknown"))
    current_version = str(state.get("installed_version", context.current_version))
    current_commit = str(state.get("installed_commit", context.current_commit))
    suppressed = set(state.get("suppressed_versions") or [])
    status = "available"
    if remote_version == current_version or remote_commit == current_commit:
        status = "not_available"
    elif respect_suppressed and remote_version in suppressed:
        status = "skipped"
    assets_for_role(manifest, context.role)
    state["last_checked_at"] = _utc_now()
    write_update_state(context.state_path, state)
    return {
        "schema_version": "1.0",
        "operation_id": f"update-check-{int(time.time())}",
        "role": context.role,
        "status": status,
        "current_version": current_version,
        "current_commit": current_commit,
        "remote_version": remote_version,
        "remote_commit": remote_commit,
        "summary": manifest.get("summary", []),
        "manifest_sha256": manifest_sha,
        "assets": [
            {"path": item["path"], "role": item["role"], "sha256": item["sha256"]}
            for item in assets_for_role(manifest, context.role)
        ],
    }


def suppress_update(context: UpdateContext, version: str) -> dict[str, Any]:
    state = load_update_state(context.state_path, context.current_version, context.current_commit)
    suppressed = list(dict.fromkeys([*state.get("suppressed_versions", []), version]))
    state["suppressed_versions"] = suppressed
    state["last_prompted_version"] = version
    state["last_update_status"] = "skipped"
    write_update_state(context.state_path, state)
    return {
        "schema_version": "1.0",
        "operation_id": f"update-suppress-{int(time.time())}",
        "role": context.role,
        "status": "skipped",
        "remote_version": version,
    }


def _download_asset(asset: dict[str, Any]) -> bytes:
    try:
        data = _read_bytes(str(asset["url"]))
    except OSError as exc:
        raise UpdateError("E_UPDATE_DOWNLOAD", f"资产下载失败：{asset['path']}: {exc}") from exc
    actual = _sha256_bytes(data)
    expected = str(asset["sha256"]).lower()
    if actual.lower() != expected:
        raise UpdateError("E_UPDATE_HASH", f"资产 SHA-256 不匹配：{asset['path']}")
    return data


def _copy_or_mark_missing(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dest)
    else:
        dest.write_text("__PROXYFLEET_MISSING__\n", encoding="utf-8")


def _restore_backup(install_root: Path, backup_root: Path, updated: list[str]) -> None:
    for rel in reversed(updated):
        target = install_root / rel
        backup = backup_root / rel
        if backup.exists() and backup.read_text(encoding="utf-8", errors="ignore") == "__PROXYFLEET_MISSING__\n":
            target.unlink(missing_ok=True)
            continue
        if backup.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)


def _atomic_write(path: Path, data: bytes, mode: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        if mode:
            os.chmod(temp_name, int(mode, 8))
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _verify_after_update(role: str, install_root: Path) -> None:
    scripts = []
    if role == "master":
        scripts = [install_root / "scripts" / "proxyfleet-master.sh", install_root / "scripts" / "proxyfleet-minion.sh"]
    elif role == "minion":
        scripts = [install_root / "scripts" / "proxyfleet-minion.sh"]
    for script in scripts:
        if script.exists():
            result = subprocess.run(["bash", "-n", str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if result.returncode != 0:
                raise UpdateError("E_UPDATE_VERIFY", f"脚本语法检查失败：{script.name}: {result.stderr.strip()}")
    src = install_root / "src" / "proxyfleet"
    if role == "master" and src.exists():
        py_files = [str(path) for path in src.glob("*.py")]
        if py_files:
            result = subprocess.run([sys.executable, "-m", "py_compile", *py_files], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if result.returncode != 0:
                raise UpdateError("E_UPDATE_VERIFY", f"Python 编译检查失败：{result.stderr.strip()}")


def apply_update(context: UpdateContext, *, assume_yes: bool = False) -> dict[str, Any]:
    check = check_update(context)
    if check["status"] == "not_available":
        state = load_update_state(context.state_path, context.current_version, context.current_commit)
        state["last_update_status"] = "skipped"
        write_update_state(context.state_path, state)
        return check
    if not assume_yes:
        raise UpdateError("E_UPDATE_CONFIRMATION", "应用更新需要用户确认")
    manifest, manifest_sha = load_manifest(context.manifest_source)
    assets = assets_for_role(manifest, context.role)
    operation_id = f"update-op-{int(time.time())}"
    backup_root = context.install_root / ".proxyfleet-update-backups" / operation_id
    downloaded: list[tuple[str, dict[str, Any], bytes]] = []
    updated: list[str] = []
    for asset in assets:
        rel = assert_asset_scope(context.role, str(asset["path"]))
        downloaded.append((rel, asset, _download_asset(asset)))
    try:
        for rel, asset, data in downloaded:
            target = context.install_root / rel
            resolved_parent = target.parent.resolve() if target.parent.exists() else target.parent
            root_resolved = context.install_root.resolve()
            if not str(resolved_parent).startswith(str(root_resolved)):
                raise UpdateError("E_UPDATE_SCOPE", f"更新路径逃逸安装根目录：{rel}")
            _copy_or_mark_missing(target, backup_root / rel)
            _atomic_write(target, data, str(asset.get("mode", "")) or None)
            updated.append(rel)
        _verify_after_update(context.role, context.install_root)
    except UpdateError:
        _restore_backup(context.install_root, backup_root, updated)
        raise
    except OSError as exc:
        _restore_backup(context.install_root, backup_root, updated)
        raise UpdateError("E_UPDATE_APPLY", f"更新写入失败：{exc}") from exc

    state = load_update_state(context.state_path, context.current_version, context.current_commit)
    state.update(
        {
            "installed_version": manifest.get("version", "unknown"),
            "installed_commit": manifest.get("commit", "unknown"),
            "last_checked_at": _utc_now(),
            "last_prompted_version": manifest.get("version", "unknown"),
            "last_update_status": "success",
        }
    )
    write_update_state(context.state_path, state)
    return {
        "schema_version": "1.0",
        "operation_id": operation_id,
        "role": context.role,
        "status": "success",
        "current_version": check["current_version"],
        "remote_version": manifest.get("version", "unknown"),
        "remote_commit": manifest.get("commit", "unknown"),
        "error_code": None,
        "message": "updated",
        "evidence": {
            "manifest_sha256": manifest_sha,
            "backup_path": str(backup_root),
            "updated_files": updated,
        },
    }


def generate_manifest(
    *,
    install_root: Path,
    output: Path,
    version: str,
    commit: str,
    base_url: str,
    role: str,
    assets: list[str],
    summary: list[str],
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        raise UpdateError("E_UPDATE_MANIFEST", "commit 必须是 Git SHA")
    manifest_assets = []
    for raw in assets:
        rel = assert_asset_scope(role, raw)
        path = install_root / rel
        if not path.is_file():
            raise UpdateError("E_UPDATE_MANIFEST", f"asset 不存在：{rel}")
        url = base_url.rstrip("/") + "/" + rel
        manifest_assets.append(
            {
                "role": role,
                "path": rel,
                "url": url,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "mode": f"{path.stat().st_mode & 0o777:04o}",
            }
        )
    manifest = {
        "schema_version": "1.0",
        "product": "proxyfleet",
        "channel": "stable",
        "version": version,
        "commit": commit,
        "published_at": _utc_now(),
        "minimum_supported_version": "v0.0.0",
        "summary": summary,
        "assets": manifest_assets,
    }
    validate_manifest(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
