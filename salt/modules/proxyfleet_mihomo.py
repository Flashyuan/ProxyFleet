"""ProxyFleet Minion 执行模块。

该模块只处理 Minion 本机的 release 安装和 Mihomo 策略组选择。
Salt Master 负责分发文件；本模块不接触订阅 URL 或节点密钥。
"""

from __future__ import annotations

import json
import gzip
import hashlib
import ipaddress
import platform
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib import error, parse, request

try:
    from salt.exceptions import CommandExecutionError
except ImportError:  # 单元测试环境不加载 Salt 包。
    class CommandExecutionError(RuntimeError):
        pass


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
    fail_on_error=False,
):
    """按组件锁安装 Mihomo；缺少架构级 SHA 时 fail-closed。"""

    try:
        component = _load_component_lock(Path(component_locks_path), "mihomo")
        version = str(component.get("version"))
        artifact = _component_artifact(component)
        sha256 = artifact.get("sha256")
        source = artifact.get("url")
        compression = artifact.get("compression", "none")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise _ApplyError("E_COMPONENT_INTEGRITY_MISSING", "mihomo sha256 missing")
        if not isinstance(source, str) or not source.startswith(("https://", "file://")):
            raise _ApplyError("E_COMPONENT_SOURCE", "mihomo source is not installable")

        artifact_target = artifact.get("target_path")
        if artifact_target is not None and Path(str(artifact_target)) != Path(str(binary_path)):
            raise _ApplyError("E_COMPONENT_TARGET", "mihomo target_path does not match Salt target")
        binary = Path(binary_path)
        receipt = binary.with_name(binary.name + ".proxyfleet-install.json")
        if binary.exists() and _installed_receipt_matches(receipt, binary, sha256):
            changed = False
        else:
            binary.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="proxyfleet-mihomo-", dir=str(binary.parent)) as tmpdir:
                tmp = Path(tmpdir)
                downloaded = tmp / "mihomo.asset"
                unpacked = tmp / "mihomo"
                _download(source, downloaded)
                if _sha256(downloaded) != sha256:
                    raise _ApplyError("E_COMPONENT_HASH", "mihomo asset hash mismatch")
                _unpack_artifact(downloaded, unpacked, compression)
                unpacked.chmod(0o755)
                _verify_mihomo_version(unpacked, version)
                binary_sha256 = _sha256(unpacked)
                unpacked.replace(binary)
            _write_install_receipt(receipt, version, _arch_key(), source, sha256, compression, binary_sha256)
            changed = True

        _write_systemd_unit(Path(service_path), binary, Path(config_path), user, group)
        _systemctl(["daemon-reload"])
        return _envelope(
            operation_id,
            "prepare",
            "success",
            0,
            0,
            None,
            "mihomo installed",
            {"mihomo_version": version, "binary_path": str(binary), "artifact_sha256": sha256, "changed": changed},
        )
    except _ApplyError as exc:
        return _failure(operation_id, "prepare", 0, 0, exc.error_code, str(exc), fail_on_error)
    except CommandExecutionError:
        raise
    except Exception as exc:
        return _failure(operation_id, "prepare", 0, 0, "E_COMPONENT_INSTALL", str(exc), fail_on_error)


def apply_desired(
    release_root="/srv/proxyfleet/salt/states/proxyfleet/releases",
    desired_path="/srv/proxyfleet/salt/states/proxyfleet/desired.yaml",
    install_root="/etc/proxyfleet",
    mihomo_api="http://127.0.0.1:9090",
    api_secret=None,
    service_name="mihomo.service",
    operation_id="op-unknown",
    fail_on_error=False,
):
    """安装当前 release 并应用 desired state。"""

    try:
        desired = _read_json(Path(desired_path))
        release_revision = int(desired["release_revision"])
        desired_revision = int(desired["desired_revision"])
        selected_name = str(desired["selected_mihomo_name"])
        group = str(desired.get("managed_policy_group", MANAGED_POLICY_GROUP))
        if group != MANAGED_POLICY_GROUP:
            return _failure(operation_id, "apply", release_revision, desired_revision, "E_SCHEMA_UNSUPPORTED", "unsupported managed group", fail_on_error)

        source_release = Path(release_root) / f"{release_revision:06d}"
        if not source_release.exists():
            return _failure(operation_id, "apply", release_revision, desired_revision, "E_RELEASE_HASH", "release not found", fail_on_error)
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
            _wait_mihomo_node(mihomo_api, api_secret, group, selected_name)
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
        return _failure(operation_id, "apply", 0, 0, exc.error_code, str(exc), fail_on_error)
    except CommandExecutionError:
        raise
    except Exception as exc:  # Salt execution modules should return structured failure.
        return _failure(operation_id, "apply", 0, 0, "E_LOCAL_API", str(exc), fail_on_error)


def _select_mihomo(base_url, api_secret, group, selected_name):
    before = _api(base_url, api_secret, "GET", "/proxies/" + parse.quote(group, safe=""), None)
    all_names = set(before.get("all", []))
    if selected_name not in all_names:
        raise _ApplyError("E_NODE_NOT_FOUND", "target node is not selectable")
    previous_name = before.get("now")
    _api(base_url, api_secret, "PUT", "/proxies/" + parse.quote(group, safe=""), {"name": selected_name})
    after = _api(base_url, api_secret, "GET", "/proxies/" + parse.quote(group, safe=""), None)
    if after.get("now") != selected_name:
        if isinstance(previous_name, str) and previous_name in all_names:
            try:
                _api(base_url, api_secret, "PUT", "/proxies/" + parse.quote(group, safe=""), {"name": previous_name})
                restored = _api(base_url, api_secret, "GET", "/proxies/" + parse.quote(group, safe=""), None)
                if restored.get("now") != previous_name:
                    raise _ApplyError("E_ROLLBACK_FAILED", "select rollback verification failed")
            except _ApplyError:
                raise _ApplyError("E_ROLLBACK_FAILED", "select rollback failed")
        raise _ApplyError("E_SELECT_VERIFY", "select verification failed")


def _wait_mihomo_api(base_url, api_secret, group, timeout_seconds=20):
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            _api(base_url, api_secret, "GET", "/proxies/" + parse.quote(group, safe=""), None)
            return
        except _ApplyError as exc:
            last_error = exc
            time.sleep(0.5)
    if last_error is not None:
        raise last_error
    raise _ApplyError("E_LOCAL_API", "mihomo api unavailable")


def _wait_mihomo_node(base_url, api_secret, group, selected_name, timeout_seconds=30):
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            state = _api(base_url, api_secret, "GET", "/proxies/" + parse.quote(group, safe=""), None)
            if selected_name in set(state.get("all", [])):
                return
            last_error = _ApplyError("E_NODE_NOT_FOUND", "target node is not selectable")
        except _ApplyError as exc:
            last_error = exc
        time.sleep(0.5)
    if last_error is not None:
        raise last_error
    raise _ApplyError("E_NODE_NOT_FOUND", "target node is not selectable")


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
            request_timeout=max(3, int(timeout_ms) / 1000 + 2),
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


def apply_port_policy(
    managed_path="/etc/proxyfleet/managed/port-policy.yaml",
    local_path="/etc/proxyfleet/local/port-policy.yaml",
    effective_path="/etc/proxyfleet/effective/port-policy.yaml",
    mode="merge",
    operation_id="op-unknown",
    fail_on_error=False,
):
    """合并端口白名单，不覆盖 Minion 本地 local override。"""

    try:
        managed = _load_port_policy(Path(managed_path), "master")
        local = _load_port_policy(Path(local_path), "local")
        effective = _merge_port_policy(managed, local, str(mode))
        target = Path(effective_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(effective, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp = target.with_name(target.name + ".next")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(target)
        return _envelope(
            operation_id,
            "apply",
            "success",
            0,
            0,
            None,
            "port policy applied",
            {
                "mode": mode,
                "managed_sha256": _optional_sha256(Path(managed_path)),
                "local_sha256": _optional_sha256(Path(local_path)),
                "effective_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            },
        )
    except _ApplyError as exc:
        return _failure(operation_id, "apply", 0, 0, exc.error_code, str(exc), fail_on_error)


def _api(base_url, api_secret, method, path, body, timeout_error_code="E_LOCAL_API", request_timeout=3):
    _assert_loopback_api(base_url)
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_secret:
        headers["Authorization"] = "Bearer " + str(api_secret)
    req = request.Request(base_url.rstrip("/") + path, data=payload, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=request_timeout) as resp:
            raw = resp.read()
    except error.HTTPError as exc:
        if exc.code == 404:
            raise _ApplyError("E_NODE_NOT_FOUND", "mihomo api target not found") from exc
        raise _ApplyError("E_LOCAL_API", "mihomo api error status") from exc
    except (error.URLError, TimeoutError, socket.timeout) as exc:
        raise _ApplyError(timeout_error_code, "mihomo api unavailable") from exc
    return json.loads(raw.decode("utf-8")) if raw else {}


def _assert_loopback_api(base_url):
    parsed = parse.urlparse(str(base_url))
    if parsed.scheme not in ("http", "https"):
        raise _ApplyError("E_LOCAL_API", "mihomo api must use local HTTP(S)")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return
    raise _ApplyError("E_LOCAL_API", "mihomo api must be loopback")


def _load_port_policy(path, expected_owner):
    if not path.exists():
        return {"schema_version": "1.0", "owner": expected_owner, "allow": [], "deny": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _ApplyError("E_PORT_POLICY_SCHEMA", "port policy is not valid JSON/YAML subset") from exc
    if not isinstance(data, dict):
        raise _ApplyError("E_PORT_POLICY_SCHEMA", "port policy root must be object")
    if data.get("schema_version", "1.0") != "1.0":
        raise _ApplyError("E_PORT_POLICY_SCHEMA", "port policy schema_version must be 1.0")
    if data.get("owner") != expected_owner:
        raise _ApplyError("E_PORT_POLICY_SCHEMA", "port policy owner mismatch")
    for key in ("allow", "deny"):
        if key not in data:
            data[key] = []
        if not isinstance(data[key], list):
            raise _ApplyError("E_PORT_POLICY_SCHEMA", "port policy allow/deny must be list")
    return data


def _merge_port_policy(managed, local, mode):
    if mode not in {"merge", "master-only", "local-only", "disabled"}:
        raise _ApplyError("E_PORT_POLICY_SCHEMA", "port policy mode invalid")
    selected = []
    if mode == "merge":
        selected = [managed, local]
    elif mode == "master-only":
        selected = [managed]
    elif mode == "local-only":
        selected = [local]
    allow = []
    deny = []
    seen = {}
    conflicts = []
    for policy in selected:
        for action in ("allow", "deny"):
            for rule in policy.get(action, []):
                normalized = _normalize_port_rule(rule, str(policy.get("owner", "unknown")), action)
                key = (normalized["protocol"], normalized["port"], normalized["source"])
                previous = seen.get(key)
                if previous and previous != action:
                    conflicts.append(f"{normalized['protocol']}/{normalized['port']} from {normalized['source']}")
                seen[key] = action
                (allow if action == "allow" else deny).append(normalized)
    if conflicts:
        raise _ApplyError("E_PORT_POLICY_CONFLICT", "port policy conflict: " + ", ".join(conflicts))
    return {"schema_version": "1.0", "owner": "effective", "mode": mode, "allow": allow, "deny": deny}


def _normalize_port_rule(rule, owner, action):
    if not isinstance(rule, dict):
        raise _ApplyError("E_PORT_POLICY_SCHEMA", "port rule must be object")
    protocol = str(rule.get("protocol", "")).lower()
    if protocol not in {"tcp", "udp"}:
        raise _ApplyError("E_PORT_POLICY_SCHEMA", "port rule protocol invalid")
    port = rule.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise _ApplyError("E_PORT_POLICY_SCHEMA", "port rule port invalid")
    source = str(rule.get("source", "")).strip()
    if not _valid_port_source(source):
        raise _ApplyError("E_PORT_POLICY_SCHEMA", "port rule source invalid")
    return {
        "action": action,
        "protocol": protocol,
        "port": port,
        "source": source,
        "comment": str(rule.get("comment", "")),
        "owner": owner,
    }


def _optional_sha256(path):
    return _sha256(path) if path.exists() else None


def _valid_port_source(source):
    if source == "any":
        return True
    try:
        ipaddress.ip_network(source, strict=False)
    except ValueError:
        return False
    return True


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
    _systemctl(["reload-or-restart", str(service_name)])


def _systemctl(args):
    completed = subprocess.run(["systemctl", *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise _ApplyError("E_SERVICE_SYSTEMD", "systemd operation failed: " + " ".join(args))


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


def _component_artifact(component):
    artifacts = component.get("artifacts")
    if isinstance(artifacts, dict):
        arch = _select_artifact_key(artifacts)
        artifact = artifacts.get(arch)
        if not isinstance(artifact, dict):
            raise _ApplyError("E_COMPONENT_ARCH_UNSUPPORTED", "mihomo artifact for current architecture missing")
        return artifact

    integrity = component.get("integrity")
    if not isinstance(integrity, dict):
        return {}
    return {
        "url": component.get("source"),
        "sha256": integrity.get("sha256"),
        "compression": "none",
    }


def _arch_key():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return _amd64_level_key()
    if machine in ("aarch64", "arm64"):
        return "linux-arm64"
    raise _ApplyError("E_COMPONENT_ARCH_UNSUPPORTED", "unsupported architecture")


def _select_artifact_key(artifacts):
    preferred = _arch_key()
    if preferred in artifacts:
        return preferred
    if preferred.startswith("linux-amd64"):
        for fallback in ("linux-amd64-compatible", "linux-amd64"):
            if fallback in artifacts:
                return fallback
    raise _ApplyError("E_COMPONENT_ARCH_UNSUPPORTED", "mihomo artifact for current architecture missing")


def _amd64_level_key():
    flags = _cpu_flags()
    # x86-64-v3 roughly matches the common baseline expected by upstream v3 builds.
    v3 = {
        "avx",
        "avx2",
        "bmi1",
        "bmi2",
        "f16c",
        "fma",
        "abm",
        "movbe",
        "xsave",
    }
    v2 = {
        "cx16",
        "lahf_lm",
        "popcnt",
        "sse3",
        "ssse3",
        "sse4_1",
        "sse4_2",
    }
    if v3.issubset(flags):
        return "linux-amd64-v3"
    if v2.issubset(flags):
        return "linux-amd64-v2"
    return "linux-amd64-v1"


def _cpu_flags():
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    flags = set()
    for line in text.splitlines():
        if line.lower().startswith(("flags", "features")) and ":" in line:
            flags.update(line.split(":", 1)[1].strip().split())
    if "pni" in flags:
        flags.add("sse3")
    if "lzcnt" in flags:
        flags.add("abm")
    return flags


def _download(source, target):
    if source.startswith("file://"):
        shutil.copyfile(source.removeprefix("file://"), target)
        return
    with urllib.request.urlopen(source, timeout=30) as resp:
        with target.open("wb") as fh:
            shutil.copyfileobj(resp, fh)


def _unpack_artifact(source, target, compression):
    if compression in (None, "", "none"):
        shutil.copyfile(source, target)
        return
    if compression == "gzip":
        try:
            with gzip.open(source, "rb") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        except OSError as exc:
            raise _ApplyError("E_COMPONENT_UNPACK", "mihomo gzip unpack failed") from exc
        return
    raise _ApplyError("E_COMPONENT_UNPACK", "mihomo compression unsupported")


def _installed_receipt_matches(receipt, binary, artifact_sha256):
    try:
        data = _read_json(receipt)
    except Exception:
        return False
    if data.get("artifact_sha256") != artifact_sha256:
        return False
    binary_sha256 = data.get("binary_sha256")
    return isinstance(binary_sha256, str) and _sha256(binary) == binary_sha256


def _write_install_receipt(path, version, arch, source, artifact_sha256, compression, binary_sha256):
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "component": "mihomo",
                "version": version,
                "arch": arch,
                "source": source,
                "artifact_sha256": artifact_sha256,
                "compression": compression,
                "binary_sha256": binary_sha256,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _verify_mihomo_version(binary, expected_version):
    completed = subprocess.run([str(binary), "-v"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output = (completed.stdout or "") + (completed.stderr or "")
    expected = str(expected_version).lstrip("v")
    if completed.returncode != 0 or expected not in output:
        raise _ApplyError("E_MIHOMO_VERSION", "mihomo version probe failed")


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
WorkingDirectory={config.parent}
ExecStart={binary} -d {config.parent} -f {config}
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


def _failure(operation_id, phase, release_revision, desired_revision, error_code, message, fail_on_error):
    envelope = _envelope(operation_id, phase, "failed", release_revision, desired_revision, error_code, message)
    if fail_on_error:
        raise CommandExecutionError(json.dumps(envelope, ensure_ascii=False, sort_keys=True))
    return envelope


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
