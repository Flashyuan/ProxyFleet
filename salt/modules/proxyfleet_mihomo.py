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
import urllib.request
from pathlib import Path
from urllib import error, parse, request


MANAGED_POLICY_GROUP = "FLEET_PROXY"


class _ApplyError(ValueError):
    def __init__(self, error_code, message):
        super().__init__(message)
        self.error_code = error_code


def __virtual__():
    return "proxyfleet_mihomo"


def install_mihomo(
    component_locks_path="/etc/proxyfleet/component-locks.json",
    binary_path="/usr/local/bin/mihomo",
    service_path="/etc/systemd/system/mihomo.service",
    config_path="/etc/proxyfleet/current/config.yaml",
    user="root",
    group="root",
    operation_id="op-unknown",
):
    """按组件锁安装 Mihomo；缺少 SHA 时 fail-closed。"""

    try:
        component = _load_component_lock(Path(component_locks_path), "mihomo")
        version = str(component.get("version"))
        sha256 = _component_sha256(component)
        source = str(component.get("source", ""))
        if not sha256:
            raise _ApplyError("E_COMPONENT_INTEGRITY_MISSING", "mihomo sha256 missing")
        if not source.startswith(("http://", "https://", "file://")):
            raise _ApplyError("E_COMPONENT_SOURCE", "mihomo source is not installable")

        binary = Path(binary_path)
        if binary.exists() and _sha256(binary) == sha256:
            changed = False
        else:
            temp = binary.parent / (binary.name + ".download")
            binary.parent.mkdir(parents=True, exist_ok=True)
            _download(source, temp)
            if _sha256(temp) != sha256:
                temp.unlink(missing_ok=True)
                raise _ApplyError("E_COMPONENT_HASH", "mihomo binary hash mismatch")
            temp.chmod(0o755)
            temp.replace(binary)
            changed = True

        _write_systemd_unit(Path(service_path), binary, Path(config_path), user, group)
        subprocess.run(["systemctl", "daemon-reload"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return _envelope(
            operation_id,
            "prepare",
            "success",
            0,
            0,
            None,
            "mihomo installed",
            {"mihomo_version": version, "binary_path": str(binary), "changed": changed},
        )
    except _ApplyError as exc:
        return _envelope(operation_id, "prepare", "failed", 0, 0, exc.error_code, str(exc))
    except Exception as exc:
        return _envelope(operation_id, "prepare", "failed", 0, 0, "E_COMPONENT_INSTALL", str(exc))


def apply_desired(
    release_root="/srv/proxyfleet/salt/states/proxyfleet/releases",
    desired_path="/srv/proxyfleet/salt/states/proxyfleet/desired.yaml",
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


def health_check(base_url, api_secret=None, mihomo_name=None, test_url="https://www.gstatic.com/generate_204", timeout_ms=3000, operation_id="op-unknown"):
    """执行单节点 delay 检查，不读取或修改 FLEET_PROXY 选择。"""

    try:
        if not mihomo_name:
            raise _ApplyError("E_NODE_NOT_FOUND", "mihomo_name is required")
        if not _health_url_allowed(str(test_url)):
            raise _ApplyError("E_HEALTHCHECK_TARGET_BLOCKED", "healthcheck url is not allowed")
        query = parse.urlencode({"timeout": int(timeout_ms), "url": str(test_url)})
        result = _api(
            base_url,
            api_secret,
            "GET",
            "/proxies/" + parse.quote(str(mihomo_name), safe="") + "/delay?" + query,
            None,
            timeout_error_code="E_HEALTHCHECK_TIMEOUT",
        )
        delay = result.get("delay")
        if not isinstance(delay, int):
            raise _ApplyError("E_HEALTHCHECK_FAILED", "delay response invalid")
        return _envelope(
            operation_id,
            "status",
            "success",
            0,
            0,
            None,
            "health ok",
            {"mihomo_name": mihomo_name, "health_status": "ok", "last_delay_ms": delay},
        )
    except _ApplyError as exc:
        return _envelope(operation_id, "status", "failed", 0, 0, exc.error_code, str(exc))


def _api(base_url, api_secret, method, path, body, timeout_error_code="E_LOCAL_API"):
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_secret:
        headers["Authorization"] = "Bearer " + str(api_secret)
    req = request.Request(base_url.rstrip("/") + path, data=payload, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=3) as resp:
            raw = resp.read()
    except error.HTTPError as exc:
        if exc.code == 404:
            raise _ApplyError("E_NODE_NOT_FOUND", "mihomo api target not found") from exc
        raise _ApplyError("E_LOCAL_API", "mihomo api error status") from exc
    except (error.URLError, TimeoutError, socket.timeout) as exc:
        raise _ApplyError(timeout_error_code, "mihomo api unavailable") from exc
    return json.loads(raw.decode("utf-8")) if raw else {}


def _health_url_allowed(test_url):
    parsed = parse.urlparse(str(test_url))
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


def _load_component_lock(path, name):
    try:
        data = _read_json(path)
    except FileNotFoundError as exc:
        raise _ApplyError("E_COMPONENT_INTEGRITY_MISSING", "component locks missing") from exc
    components = data.get("components")
    if not isinstance(components, list):
        raise _ApplyError("E_SCHEMA_UNSUPPORTED", "component locks invalid")
    for component in components:
        if isinstance(component, dict) and component.get("name") == name:
            return component
    raise _ApplyError("E_COMPONENT_INTEGRITY_MISSING", "mihomo lock missing")


def _component_sha256(component):
    integrity = component.get("integrity")
    if not isinstance(integrity, dict):
        return None
    sha256 = integrity.get("sha256")
    if not isinstance(sha256, str) or len(sha256) != 64:
        return None
    return sha256.lower()


def _download(source, target):
    if source.startswith("file://"):
        shutil.copyfile(source.removeprefix("file://"), target)
        return
    with urllib.request.urlopen(source, timeout=30) as resp:
        with target.open("wb") as fh:
            shutil.copyfileobj(resp, fh)


def _write_systemd_unit(path, binary, config, user, group):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""[Unit]
Description=ProxyFleet managed Mihomo
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={group}
ExecStart={binary} -f {config}
Restart=on-failure
RestartSec=3s
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
"""
    path.write_text(content, encoding="utf-8")


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
