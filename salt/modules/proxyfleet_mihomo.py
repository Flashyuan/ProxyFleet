"""ProxyFleet Minion 执行模块。

该模块只处理 Minion 本机的 release 安装和 Mihomo 策略组选择。
Salt Master 负责分发文件；本模块不接触订阅 URL 或节点密钥。
"""

from __future__ import annotations

import json
import hashlib
import shutil
import socket
import subprocess
from pathlib import Path
from urllib import error, parse, request


MANAGED_POLICY_GROUP = "FLEET_PROXY"


class _ApplyError(ValueError):
    def __init__(self, error_code, message):
        super().__init__(message)
        self.error_code = error_code


def __virtual__():
    return "proxyfleet_mihomo"


def apply_desired(
    release_root="/srv/salt/proxyfleet/releases",
    desired_path="/srv/salt/proxyfleet/desired.yaml",
    install_root="/etc/proxyfleet",
    mihomo_api="http://127.0.0.1:9090",
    api_secret=None,
    service_name="mihomo.service",
    operation_id="op-unknown",
):
    """安装当前 release 并应用 desired state。"""

    try:
        desired = _read_json(Path(desired_path))
        release_revision = int(desired["release_revision"])
        desired_revision = int(desired["desired_revision"])
        selected_name = str(desired["selected_mihomo_name"])
        group = str(desired.get("managed_policy_group", MANAGED_POLICY_GROUP))
        if group != MANAGED_POLICY_GROUP:
            return _envelope(operation_id, "apply", "failed", release_revision, desired_revision, "E_SCHEMA_UNSUPPORTED", "unsupported managed group")

        source_release = Path(release_root) / f"{release_revision:06d}"
        if not source_release.exists():
            return _envelope(operation_id, "apply", "failed", release_revision, desired_revision, "E_RELEASE_HASH", "release not found")
        _verify_release(source_release)

        target_release = Path(install_root) / "releases" / f"{release_revision:06d}"
        staging_release = Path(install_root) / "releases" / f".staging-{release_revision:06d}-{operation_id}"
        target_release.parent.mkdir(parents=True, exist_ok=True)
        if not target_release.exists():
            if staging_release.exists():
                shutil.rmtree(staging_release)
            shutil.copytree(source_release, staging_release)
            _verify_release(staging_release)
            staging_release.replace(target_release)
        _verify_release(target_release)

        current = Path(install_root) / "current"
        previous_current = _current_target(current)
        _point_current(current, target_release)
        try:
            _reload_or_restart(service_name)
            _select_mihomo(mihomo_api, api_secret, group, selected_name)
        except _ApplyError:
            _restore_current(current, previous_current)
            if previous_current:
                try:
                    _reload_or_restart(service_name)
                except _ApplyError:
                    pass
            raise
        _atomic_copy(Path(desired_path), Path(install_root) / "desired.yaml")
        return _envelope(
            operation_id,
            "apply",
            "success",
            release_revision,
            desired_revision,
            None,
            "applied",
            {"selected_node_id": desired["selected_node_id"], "selected_mihomo_name": selected_name},
        )
    except _ApplyError as exc:
        return _envelope(operation_id, "apply", "failed", 0, 0, exc.error_code, str(exc))
    except Exception as exc:  # Salt execution modules should return structured failure.
        return _envelope(operation_id, "apply", "failed", 0, 0, "E_LOCAL_API", str(exc))


def _select_mihomo(base_url, api_secret, group, selected_name):
    before = _api(base_url, api_secret, "GET", "/proxies/" + parse.quote(group, safe=""), None)
    all_names = set(before.get("all", []))
    if selected_name not in all_names:
        raise _ApplyError("E_NODE_NOT_FOUND", "target node is not selectable")
    _api(base_url, api_secret, "PUT", "/proxies/" + parse.quote(group, safe=""), {"name": selected_name})
    after = _api(base_url, api_secret, "GET", "/proxies/" + parse.quote(group, safe=""), None)
    if after.get("now") != selected_name:
        raise _ApplyError("E_SELECT_VERIFY", "select verification failed")


def _api(base_url, api_secret, method, path, body):
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_secret:
        headers["Authorization"] = "Bearer " + str(api_secret)
    req = request.Request(base_url.rstrip("/") + path, data=payload, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=3) as resp:
            raw = resp.read()
    except (error.URLError, TimeoutError) as exc:
        raise _ApplyError("E_LOCAL_API", "mihomo api unavailable") from exc
    return json.loads(raw.decode("utf-8")) if raw else {}


def _reload_or_restart(service_name):
    completed = subprocess.run(["systemctl", "reload-or-restart", str(service_name)], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise _ApplyError("E_LOCAL_API", "mihomo reload-or-restart failed")


def _current_target(current):
    if current.is_symlink():
        return current.resolve()
    if current.exists():
        return current.resolve()
    return None


def _point_current(current, target):
    current.parent.mkdir(parents=True, exist_ok=True)
    next_link = current.parent / ".current.next"
    if next_link.exists() or next_link.is_symlink():
        next_link.unlink()
    next_link.symlink_to(target)
    next_link.replace(current)


def _restore_current(current, previous):
    if previous is None:
        if current.exists() or current.is_symlink():
            current.unlink()
        return
    _point_current(current, previous)


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_release(root):
    manifest_sha = root / "manifest.sha256"
    manifest_path = root / "manifest.json"
    if not manifest_sha.exists() or not manifest_path.exists():
        raise _ApplyError("E_RELEASE_HASH", "release manifest missing")
    expected_manifest = manifest_sha.read_text(encoding="utf-8").split()[0]
    if _sha256(manifest_path) != expected_manifest:
        raise _ApplyError("E_RELEASE_HASH", "manifest hash mismatch")
    manifest = _read_json(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise _ApplyError("E_RELEASE_HASH", "manifest files invalid")
    for item in files:
        rel = item.get("path")
        if not isinstance(rel, str) or rel.startswith("/") or ".." in Path(rel).parts:
            raise _ApplyError("E_RELEASE_HASH", "manifest path invalid")
        path = root / rel
        if not path.is_file():
            raise _ApplyError("E_RELEASE_HASH", "manifest file missing")
        if _sha256(path) != item.get("sha256"):
            raise _ApplyError("E_RELEASE_HASH", "manifest file hash mismatch")
        if path.stat().st_size != item.get("size"):
            raise _ApplyError("E_RELEASE_HASH", "manifest file size mismatch")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / (target.name + ".next")
    shutil.copyfile(source, temp)
    temp.replace(target)


def _envelope(operation_id, phase, status, release_revision, desired_revision, error_code, message, evidence=None):
    return {
        "schema_version": "1.0",
        "operation_id": operation_id,
        "minion_id": socket.gethostname(),
        "phase": phase,
        "status": status,
        "error_code": error_code,
        "message": _redact(message),
        "release_revision": release_revision,
        "desired_revision": desired_revision,
        "evidence": _redact_obj(evidence or {}),
    }


def _redact(message):
    raw = str(message)
    lowered = raw.lower()
    if any(marker in lowered for marker in ("secret=", "password=", "uuid=", "token=", "url=")):
        return "redacted"
    return raw


def _redact_obj(value):
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in ("secret", "password", "uuid", "token", "url")):
                safe[key] = "redacted"
            else:
                safe[key] = _redact_obj(item)
        return safe
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value
