"""节点健康监控、告警和延迟自动切换。"""

from __future__ import annotations

import json
import os
import smtplib
import socket
import ssl
import tempfile
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from .fleet import (
    FleetError,
    MANAGED_POLICY_GROUP,
    MihomoClient,
    build_node_catalog,
    load_desired_state,
    prepare_salt_publish,
    run_salt_sync,
    select_node,
)


MONITOR_SCHEMA_VERSION = "1.0"
DEFAULT_CHECK_INTERVAL_SECONDS = 600
DEFAULT_ADMIN_GRACE_SECONDS = 600
DEFAULT_BLACKLIST_KEYWORDS = ["香港", "港", "HK", "Hong Kong", "台湾", "台", "TW", "Taiwan"]
DEFAULT_PROBE_ALLOWLIST = {
    "exit_ip": ["https://ipdata.co", "https://ipinfo.io/json"],
    "google": ["https://www.google.com/generate_204"],
    "chatgpt": ["https://chatgpt.com", "https://api.openai.com"],
}


class HealthMonitorError(FleetError):
    """健康监控失败。"""


@dataclass(frozen=True)
class MonitorPaths:
    policy_path: Path
    state_path: Path
    email_config_path: Path | None = None


def default_policy() -> dict[str, Any]:
    """返回保守默认策略。"""

    return {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "enabled": True,
        "auto_switch_enabled": False,
        "check_interval_seconds": DEFAULT_CHECK_INTERVAL_SECONDS,
        "consecutive_bad_rounds": 3,
        "min_success_score": 2,
        "admin_grace_period_seconds": DEFAULT_ADMIN_GRACE_SECONDS,
        "switch_cooldown_seconds": 1800,
        "max_auto_switches_per_hour": 1,
        "max_auto_switches_per_day": 3,
        "failed_candidate_ttl_seconds": 3600,
        "proxy_url": "http://127.0.0.1:7890",
        "probes": {"mihomo_delay": True, "exit_ip": True, "google": True, "chatgpt": True},
        "probe_allowlist": DEFAULT_PROBE_ALLOWLIST,
        "blacklist_name_keywords": DEFAULT_BLACKLIST_KEYWORDS,
        "unknown_region_auto_switch": False,
        "notify": {"email_profile": "default"},
    }


def load_policy(path: Path | None) -> dict[str, Any]:
    """读取策略；不存在时使用默认策略。"""

    policy = default_policy()
    if path is not None and path.exists():
        data = _read_json(path)
        if data.get("schema_version") != MONITOR_SCHEMA_VERSION:
            raise HealthMonitorError("E_SCHEMA_UNSUPPORTED", "monitor policy schema_version 不受支持")
        policy = _deep_merge(policy, data)
    _validate_policy(policy)
    return policy


def write_default_policy(path: Path) -> dict[str, Any]:
    """写入默认策略，便于 TUI 首次配置。"""

    policy = default_policy()
    _atomic_write_json(path, policy, mode=0o600)
    return policy


def set_auto_switch(path: Path, enabled: bool) -> dict[str, Any]:
    """显式启用或关闭自动切换。"""

    policy = load_policy(path if path.exists() else None)
    policy["auto_switch_enabled"] = bool(enabled)
    _atomic_write_json(path, policy, mode=0o600)
    return _redact_obj(policy)


def configure_email_profile(
    email_config_path: Path,
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_tls: bool,
    username: str,
    password_file: Path,
    sender: str,
    recipients: list[str],
    profile: str = "default",
) -> dict[str, Any]:
    """写入邮件告警配置；密码只引用 password_file。"""

    if not smtp_host:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP host 不能为空")
    if smtp_port < 1 or smtp_port > 65535:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP port 无效")
    if not username:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP username 不能为空")
    if not sender:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "发件人不能为空")
    cleaned = _clean_recipients(recipients)
    if not cleaned:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "至少需要一个收件人")
    payload = {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "profiles": {
            profile: {
                "smtp_host": smtp_host,
                "smtp_port": smtp_port,
                "smtp_tls": bool(smtp_tls),
                "username": username,
                "password_file": str(password_file),
                "from": sender,
                "recipients": cleaned,
            }
        },
    }
    _atomic_write_json(email_config_path, payload, mode=0o600)
    return _redact_obj(payload)


def write_smtp_password(password_file: Path, password: str) -> None:
    """写入 SMTP 授权码，权限限制为 0600。"""

    if not password:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP 密码或授权码不能为空")
    password_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=password_file.parent, delete=False) as fh:
        fh.write(password.strip() + "\n")
        temp_name = fh.name
    os.chmod(temp_name, 0o600)
    Path(temp_name).replace(password_file)
    try:
        password_file.chmod(0o600)
    except OSError:
        pass


def monitor_status(policy_path: Path, state_path: Path, email_config_path: Path | None = None) -> dict[str, Any]:
    """输出健康监控状态。"""

    policy = load_policy(policy_path)
    state = _load_state(state_path)
    email_configured = bool(email_config_path and email_config_path.exists())
    return {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "policy": _redact_obj(policy),
        "state": _redact_obj(state),
        "email_configured": email_configured,
    }


def notify_manual_switch(
    *,
    policy_path: Path | None,
    email_config_path: Path | None,
    selected_node_id: str,
    selected_mihomo_name: str,
    target: str,
    actor: str,
    operation_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """手动切换节点成功后发送邮件通知。"""

    now = now or datetime.now(timezone.utc)
    if email_config_path is None or not email_config_path.exists():
        return {
            "schema_version": MONITOR_SCHEMA_VERSION,
            "status": "skipped",
            "reason": "email_config_missing",
        }
    policy = load_policy(policy_path if policy_path and policy_path.exists() else None)
    profile = str(policy.get("notify", {}).get("email_profile", "default"))
    event = {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "event_type": "manual_switch_success",
        "created_at": _fmt_time(now),
        "node_id": selected_node_id,
        "mihomo_name": selected_mihomo_name,
        "target": target,
        "actor": actor,
        "operation_id": operation_id,
    }
    send_email_event(email_config_path, profile, "ProxyFleet 手动切换节点成功", event)
    return {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "status": "sent",
        "event": _redact_obj(event),
    }


def monitor_once(
    *,
    release_dir: Path,
    runtime_dir: Path,
    paths: MonitorPaths,
    mihomo_api: str,
    mihomo_secret: str | None = None,
    salt_root: Path | None = None,
    component_locks: Path | None = None,
    target: str = "*",
    salt_bin: str = "salt",
    dry_run: bool = False,
    send_email: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """执行一轮健康监控和状态推进。"""

    now = now or datetime.now(timezone.utc)
    policy = load_policy(paths.policy_path)
    if not bool(policy.get("enabled", True)):
        return {"schema_version": MONITOR_SCHEMA_VERSION, "status": "disabled"}

    desired_path = runtime_dir / "desired.yaml"
    desired = load_desired_state(desired_path)
    selected_node_id = str(desired["selected_node_id"])
    selected_name = str(desired["selected_mihomo_name"])
    nodes = build_node_catalog(release_dir)
    current_node = next((node for node in nodes if node.node_id == selected_node_id), None)
    if current_node is None:
        raise HealthMonitorError("E_NODE_NOT_FOUND", f"当前 desired 节点不在 release 中: {selected_node_id}")

    state = _load_state(paths.state_path)
    if state.get("selected_node_id") != selected_node_id:
        state = _fresh_state(selected_node_id, selected_name, now)

    round_result = evaluate_current_node(
        selected_name,
        policy,
        mihomo_api=mihomo_api,
        mihomo_secret=mihomo_secret,
        now=now,
    )
    ok = int(round_result["score"]) >= int(policy["min_success_score"])
    events: list[dict[str, Any]] = []
    action: dict[str, Any] = {"type": "none"}

    if ok:
        if state.get("status") in {"WAITING_ADMIN", "DEGRADED", "FAILED_NEED_MANUAL"}:
            events.append(_event("node_recovered", selected_node_id, selected_name, now, round_result))
            _send_policy_email(paths.email_config_path, policy, "ProxyFleet 节点恢复", events[-1], send_email)
        state = _fresh_state(selected_node_id, selected_name, now)
        state["status"] = "HEALTHY"
    else:
        state["bad_rounds"] = int(state.get("bad_rounds", 0)) + 1
        threshold = int(policy["consecutive_bad_rounds"])
        if state["bad_rounds"] < threshold:
            state["status"] = "DEGRADED"
            action = {"type": "observe", "bad_rounds": state["bad_rounds"], "threshold": threshold}
        else:
            action = _advance_failure_state(
                state=state,
                policy=policy,
                paths=paths,
                release_dir=release_dir,
                runtime_dir=runtime_dir,
                desired_path=desired_path,
                nodes=nodes,
                current_node=current_node,
                round_result=round_result,
                now=now,
                salt_root=salt_root,
                component_locks=component_locks,
                target=target,
                salt_bin=salt_bin,
                dry_run=dry_run,
                send_email=send_email,
            )
            events.extend(action.get("events", []))

    state["updated_at"] = _fmt_time(now)
    state["last_round"] = round_result
    _atomic_write_json(paths.state_path, _redact_obj(state), mode=0o600)
    return {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "status": state.get("status"),
        "selected_node_id": selected_node_id,
        "selected_mihomo_name": selected_name,
        "round": round_result,
        "action": _redact_obj(action),
        "state": _redact_obj(state),
        "events": _redact_obj(events),
        "dry_run": dry_run,
    }


def evaluate_current_node(
    mihomo_name: str,
    policy: dict[str, Any],
    *,
    mihomo_api: str,
    mihomo_secret: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """执行当前节点综合探测。"""

    now = now or datetime.now(timezone.utc)
    probes = policy.get("probes", {})
    result: dict[str, Any] = {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "measured_at": _fmt_time(now),
        "selected_mihomo_name": mihomo_name,
        "scope": "master-local",
        "score": 0,
        "status": "unknown",
        "probes": {},
        "minions": {"online": 0, "failed": 0, "offline": 0, "failed_ratio": 0.0},
        "last_error_code": None,
    }
    score = 0
    if probes.get("mihomo_delay", True):
        probe = _probe_mihomo_delay(mihomo_name, policy, mihomo_api, mihomo_secret)
        result["probes"]["mihomo_delay"] = probe
        score += 1 if probe["ok"] else 0
    if probes.get("exit_ip", True):
        probe = _probe_http_category("exit_ip", policy)
        result["probes"]["exit_ip"] = probe
        score += 1 if probe["ok"] else 0
    if probes.get("google", True):
        probe = _probe_http_category("google", policy)
        result["probes"]["google"] = probe
        score += 1 if probe["ok"] else 0
    if probes.get("chatgpt", True):
        probe = _probe_http_category("chatgpt", policy)
        result["probes"]["chatgpt"] = probe
        score += 1 if probe["ok"] else 0

    result["score"] = score
    min_success = int(policy["min_success_score"])
    if score >= 4:
        result["status"] = "healthy"
    elif score >= min_success:
        result["status"] = "degraded"
    elif score <= 1:
        result["status"] = "suspect_failed"
    else:
        result["status"] = "degraded"
    errors = [str(item.get("error_code")) for item in result["probes"].values() if isinstance(item, dict) and item.get("error_code")]
    result["last_error_code"] = errors[0] if errors else None
    return result


def choose_auto_switch_candidate(
    nodes: list[Any],
    current_node: Any,
    policy: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按黑名单、同地域优先和失败候选 TTL 选择备用节点。"""

    state = state or {}
    now = datetime.now(timezone.utc)
    current_region = infer_region(current_node.mihomo_name)
    failed_candidates = _active_failed_candidates(state, policy, now)
    candidates = []
    rejected = []
    for node in nodes:
        reason = None
        if node.node_id == current_node.node_id:
            reason = "current"
        elif _is_blacklisted(node.mihomo_name, policy):
            reason = "blacklisted"
        elif node.node_id in failed_candidates:
            reason = "recent_failed_candidate"
        else:
            region = infer_region(node.mihomo_name)
            if not region and not bool(policy.get("unknown_region_auto_switch", False)):
                reason = "unknown_region"
        if reason:
            rejected.append({"node_id": node.node_id, "mihomo_name": node.mihomo_name, "reason": reason})
            continue
        candidates.append(node)

    same_region = [node for node in candidates if infer_region(node.mihomo_name) == current_region and current_region]
    selected_pool = same_region or candidates
    if not selected_pool:
        return {"selected": None, "reason": "no_candidate", "rejected": rejected}
    selected = selected_pool[0]
    return {
        "selected": selected.to_dict(),
        "reason": "same_region" if selected in same_region else "fallback_region",
        "current_region": current_region,
        "selected_region": infer_region(selected.mihomo_name),
        "rejected": rejected,
    }


def infer_region(name: str) -> str | None:
    """根据节点名称推断粗粒度地域。未知时返回 None。"""

    lowered = name.lower()
    mapping = [
        ("香港", ["香港", "港", "hk", "hong kong"]),
        ("台湾", ["台湾", "台", "tw", "taiwan"]),
        ("日本", ["日本", "东京", "大阪", "jp", "japan", "tokyo", "osaka"]),
        ("新加坡", ["新加坡", "sg", "singapore"]),
        ("美国", ["美国", "美", "us", "usa", "united states", "los angeles", "la"]),
        ("韩国", ["韩国", "韩", "kr", "korea", "seoul"]),
        ("英国", ["英国", "uk", "britain", "london"]),
        ("德国", ["德国", "de", "germany", "frankfurt"]),
    ]
    for region, keywords in mapping:
        if any(keyword in lowered for keyword in keywords):
            return region
    return None


def _advance_failure_state(
    *,
    state: dict[str, Any],
    policy: dict[str, Any],
    paths: MonitorPaths,
    release_dir: Path,
    runtime_dir: Path,
    desired_path: Path,
    nodes: list[Any],
    current_node: Any,
    round_result: dict[str, Any],
    now: datetime,
    salt_root: Path | None,
    component_locks: Path | None,
    target: str,
    salt_bin: str,
    dry_run: bool,
    send_email: bool,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if state.get("status") != "WAITING_ADMIN":
        state["status"] = "WAITING_ADMIN"
        state["alert_sent_at"] = _fmt_time(now)
        state["auto_switch_after"] = _fmt_time(now + timedelta(seconds=int(policy["admin_grace_period_seconds"])))
        event = _event("node_suspect_failed", current_node.node_id, current_node.mihomo_name, now, round_result)
        events.append(event)
        _send_policy_email(paths.email_config_path, policy, "ProxyFleet 节点疑似失效", event, send_email)
        return {"type": "alert_waiting_admin", "events": events, "auto_switch_after": state["auto_switch_after"]}

    auto_switch_after = _parse_time(str(state.get("auto_switch_after")))
    if auto_switch_after and now < auto_switch_after:
        return {"type": "waiting_admin", "events": events, "auto_switch_after": state.get("auto_switch_after")}

    if not bool(policy.get("auto_switch_enabled", False)):
        state["status"] = "FAILED_NEED_MANUAL"
        event = _event("auto_switch_disabled", current_node.node_id, current_node.mihomo_name, now, round_result)
        events.append(event)
        _send_policy_email(paths.email_config_path, policy, "ProxyFleet 节点仍失效，需要人工处理", event, send_email)
        return {"type": "blocked_auto_switch_disabled", "events": events}

    limit_error = _switch_limit_error(state, policy, now)
    if limit_error:
        state["status"] = "FAILED_NEED_MANUAL"
        event = _event(limit_error, current_node.node_id, current_node.mihomo_name, now, round_result)
        events.append(event)
        _send_policy_email(paths.email_config_path, policy, "ProxyFleet 自动切换被限制", event, send_email)
        return {"type": "blocked_by_limit", "reason": limit_error, "events": events}

    decision = choose_auto_switch_candidate(nodes, current_node, policy, state)
    if not decision.get("selected"):
        state["status"] = "FAILED_NEED_MANUAL"
        event = _event("auto_switch_no_candidate", current_node.node_id, current_node.mihomo_name, now, round_result)
        event["decision"] = decision
        events.append(event)
        _send_policy_email(paths.email_config_path, policy, "ProxyFleet 自动切换失败", event, send_email)
        return {"type": "no_candidate", "decision": decision, "events": events}

    selected = decision["selected"]
    state["status"] = "AUTO_SWITCHING"
    if not dry_run:
        try:
            select_node(release_dir, runtime_dir, str(selected["node_id"]), "production")
            if salt_root is not None and component_locks is not None:
                prepare_salt_publish(release_dir, desired_path, salt_root, component_locks)
                rc = run_salt_sync(
                    _build_sync_plan_after_select(release_dir, desired_path, salt_root, target),
                    salt_bin,
                )
                if rc != 0:
                    raise HealthMonitorError("E_SYNC_FAILED", f"Salt 同步失败，退出码: {rc}")
        except Exception as exc:
            _mark_failed_candidate(state, str(selected["node_id"]), now)
            state["status"] = "FAILED_NEED_MANUAL"
            event = _event("auto_switch_failed", current_node.node_id, current_node.mihomo_name, now, round_result)
            event["error"] = _redact(str(exc))
            event["decision"] = decision
            events.append(event)
            _send_policy_email(paths.email_config_path, policy, "ProxyFleet 自动切换失败", event, send_email)
            return {"type": "auto_switch_failed", "decision": decision, "events": events}

    state["status"] = "RESOLVED_AUTO"
    state["selected_node_id"] = str(selected["node_id"])
    state["selected_mihomo_name"] = str(selected["mihomo_name"])
    state.setdefault("switch_history", []).append({"at": _fmt_time(now), "node_id": selected["node_id"], "dry_run": dry_run})
    event = _event("auto_switch_success", str(selected["node_id"]), str(selected["mihomo_name"]), now, round_result)
    event["decision"] = decision
    events.append(event)
    _send_policy_email(paths.email_config_path, policy, "ProxyFleet 自动切换成功", event, send_email)
    return {"type": "auto_switch_success", "decision": decision, "events": events}


def _build_sync_plan_after_select(release_dir: Path, desired_path: Path, salt_root: Path, target: str):
    from .fleet import build_sync_plan

    return build_sync_plan(release_dir, desired_path, salt_root, target)


def _probe_mihomo_delay(mihomo_name: str, policy: dict[str, Any], mihomo_api: str, mihomo_secret: str | None) -> dict[str, Any]:
    try:
        url = str(policy["probe_allowlist"]["google"][0])
        health = MihomoClient(mihomo_api, mihomo_secret).health_check(mihomo_name, url, timeout_ms=3000)
        return {"ok": True, "delay_ms": health["last_delay_ms"], "error_code": None}
    except FleetError as exc:
        return {"ok": False, "delay_ms": None, "error_code": exc.error_code}


def _probe_http_category(category: str, policy: dict[str, Any]) -> dict[str, Any]:
    urls = policy.get("probe_allowlist", {}).get(category, [])
    if not isinstance(urls, list) or not urls:
        return {"ok": False, "http_status": None, "error_code": "E_HEALTHCHECK_TARGET_BLOCKED"}
    last_error = "E_HEALTHCHECK_FAILED"
    for url in urls:
        try:
            _assert_probe_url_allowed(category, str(url), policy)
            return _probe_via_proxy(str(url), str(policy["proxy_url"]))
        except HealthMonitorError as exc:
            last_error = exc.error_code
    return {"ok": False, "http_status": None, "error_code": last_error}


def _probe_via_proxy(url: str, proxy_url: str) -> dict[str, Any]:
    _assert_loopback_proxy(proxy_url)
    opener = request.build_opener(request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    req = request.Request(url, headers={"User-Agent": "ProxyFleetHealth/1.0"})
    try:
        with opener.open(req, timeout=10) as resp:
            raw = resp.read(4096)
            payload: dict[str, Any] = {"ok": True, "http_status": int(resp.status), "error_code": None}
            if "ipdata.co" in url or "ipinfo.io" in url:
                payload["body_preview"] = _redact(raw.decode("utf-8", "ignore")[:256])
            return payload
    except error.HTTPError as exc:
        # ChatGPT/OpenAI 可能返回 403/404/429；能收到 HTTP 响应仍代表服务可达。
        return {"ok": True, "http_status": int(exc.code), "error_code": None}
    except (socket.timeout, TimeoutError) as exc:
        raise HealthMonitorError("E_PROBE_TIMEOUT", "代理探测超时") from exc
    except error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise HealthMonitorError("E_PROBE_TIMEOUT", "代理探测超时") from exc
        raise HealthMonitorError("E_PROBE_FAILED", "代理探测失败") from exc


def _send_policy_email(email_config_path: Path | None, policy: dict[str, Any], subject: str, event: dict[str, Any], send_email: bool) -> None:
    if not send_email:
        return
    if email_config_path is None or not email_config_path.exists():
        return
    profile = str(policy.get("notify", {}).get("email_profile", "default"))
    send_email_event(email_config_path, profile, subject, event)


def send_email_event(email_config_path: Path, profile: str, subject: str, event: dict[str, Any]) -> None:
    """发送邮件告警。"""

    config = _read_json(email_config_path)
    profile_data = config.get("profiles", {}).get(profile)
    if not isinstance(profile_data, dict):
        raise HealthMonitorError("E_NOTIFY_CONFIG", f"邮件 profile 不存在: {profile}")
    password_path = Path(_require_str(profile_data, "password_file"))
    _assert_password_file_safe(password_path)
    try:
        password = password_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP password_file 不可读") from exc
    recipients = _clean_recipients(profile_data.get("recipients", []))
    if not recipients:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "邮件收件人为空")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _require_str(profile_data, "from")
    msg["To"] = ", ".join(recipients)
    msg.set_content(json.dumps(_redact_obj(event), ensure_ascii=False, indent=2, sort_keys=True))
    host = _require_str(profile_data, "smtp_host")
    port = int(profile_data.get("smtp_port", 465))
    username = _require_str(profile_data, "username")
    if bool(profile_data.get("smtp_tls", True)):
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as smtp:
            smtp.login(username, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(username, password)
            smtp.send_message(msg)


def _switch_limit_error(state: dict[str, Any], policy: dict[str, Any], now: datetime) -> str | None:
    history = [_parse_time(str(item.get("at"))) for item in state.get("switch_history", []) if isinstance(item, dict)]
    history = [item for item in history if item is not None]
    if history:
        last = max(history)
        if (now - last).total_seconds() < int(policy["switch_cooldown_seconds"]):
            return "auto_switch_cooldown"
    last_hour = [item for item in history if (now - item).total_seconds() <= 3600]
    if len(last_hour) >= int(policy["max_auto_switches_per_hour"]):
        return "auto_switch_hourly_limit"
    last_day = [item for item in history if (now - item).total_seconds() <= 86400]
    if len(last_day) >= int(policy["max_auto_switches_per_day"]):
        return "auto_switch_daily_limit"
    return None


def _assert_password_file_safe(path: Path) -> None:
    if not path.is_absolute():
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP password_file 必须是绝对路径")
    try:
        st = path.lstat()
    except OSError as exc:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP password_file 不存在") from exc
    if stat.S_ISLNK(st.st_mode):
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP password_file 不得是符号链接")
    if not stat.S_ISREG(st.st_mode):
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP password_file 必须是普通文件")
    if st.st_uid not in {0, os.geteuid()}:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP password_file owner 不可信")
    if st.st_mode & 0o077:
        raise HealthMonitorError("E_NOTIFY_CONFIG", "SMTP password_file 不能允许 group/world 读取")


def _active_failed_candidates(state: dict[str, Any], policy: dict[str, Any], now: datetime) -> set[str]:
    ttl = int(policy["failed_candidate_ttl_seconds"])
    active = set()
    for item in state.get("failed_candidates", []):
        if not isinstance(item, dict):
            continue
        at = _parse_time(str(item.get("at")))
        node_id = item.get("node_id")
        if at and isinstance(node_id, str) and (now - at).total_seconds() <= ttl:
            active.add(node_id)
    return active


def _mark_failed_candidate(state: dict[str, Any], node_id: str, now: datetime) -> None:
    state.setdefault("failed_candidates", []).append({"node_id": node_id, "at": _fmt_time(now)})


def _is_blacklisted(name: str, policy: dict[str, Any]) -> bool:
    lowered = name.lower()
    for keyword in policy.get("blacklist_name_keywords", DEFAULT_BLACKLIST_KEYWORDS):
        if str(keyword).lower() in lowered:
            return True
    return False


def _assert_probe_url_allowed(category: str, url: str, policy: dict[str, Any]) -> None:
    allowed = [str(item) for item in policy.get("probe_allowlist", {}).get(category, [])]
    if url not in allowed:
        raise HealthMonitorError("E_HEALTHCHECK_TARGET_BLOCKED", "探测 URL 不在 allowlist")
    parsed = parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise HealthMonitorError("E_HEALTHCHECK_TARGET_BLOCKED", "探测 URL 不安全")


def _assert_loopback_proxy(proxy_url: str) -> None:
    parsed = parse.urlparse(proxy_url)
    if parsed.scheme not in {"http", "https"}:
        raise HealthMonitorError("E_LOCAL_API", "代理 URL 仅支持 HTTP(S)")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HealthMonitorError("E_LOCAL_API", "代理 URL 必须是 loopback 地址")


def _fresh_state(node_id: str, mihomo_name: str, now: datetime) -> dict[str, Any]:
    return {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "status": "HEALTHY",
        "selected_node_id": node_id,
        "selected_mihomo_name": mihomo_name,
        "bad_rounds": 0,
        "switch_history": [],
        "failed_candidates": [],
        "updated_at": _fmt_time(now),
    }


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": MONITOR_SCHEMA_VERSION, "status": "UNKNOWN", "bad_rounds": 0}
    data = _read_json(path)
    if data.get("schema_version") != MONITOR_SCHEMA_VERSION:
        raise HealthMonitorError("E_SCHEMA_UNSUPPORTED", "monitor state schema_version 不受支持")
    return data


def _event(event_type: str, node_id: str, mihomo_name: str, now: datetime, round_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "event_type": event_type,
        "created_at": _fmt_time(now),
        "node_id": node_id,
        "mihomo_name": mihomo_name,
        "score": round_result.get("score"),
        "health_status": round_result.get("status"),
        "last_error_code": round_result.get("last_error_code"),
    }


def _validate_policy(policy: dict[str, Any]) -> None:
    if int(policy.get("check_interval_seconds", 0)) < 300:
        raise HealthMonitorError("E_CONFIG_VALIDATE", "check_interval_seconds 生产默认不得低于 300")
    if int(policy.get("admin_grace_period_seconds", 0)) < 60:
        raise HealthMonitorError("E_CONFIG_VALIDATE", "admin_grace_period_seconds 不得低于 60")
    _assert_loopback_proxy(str(policy.get("proxy_url", "")))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HealthMonitorError("E_CONFIG_VALIDATE", f"文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HealthMonitorError("E_CONFIG_VALIDATE", f"JSON 无效: {path.name}") from exc
    if not isinstance(data, dict):
        raise HealthMonitorError("E_CONFIG_VALIDATE", f"JSON 顶层必须是对象: {path.name}")
    return data


def _atomic_write_json(path: Path, payload: dict[str, Any], *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
        temp_name = fh.name
    os.chmod(temp_name, mode)
    Path(temp_name).replace(path)
    try:
        path.chmod(mode)
    except OSError:
        pass


def _clean_recipients(recipients: Any) -> list[str]:
    if isinstance(recipients, str):
        raw = recipients.replace(";", ",").split(",")
    elif isinstance(recipients, list):
        raw = []
        for item in recipients:
            raw.extend(str(item).replace(";", ",").split(","))
    else:
        raw = []
    cleaned = []
    for item in raw:
        value = str(item).strip()
        if value and "@" in value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _require_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise HealthMonitorError("E_CONFIG_VALIDATE", f"缺少字段: {key}")
    return value


def _fmt_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime | None:
    if not value or value == "None":
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _redact(value: str) -> str:
    redacted = value
    for marker in ["password", "token", "secret", "uuid", "订阅"]:
        redacted = redacted.replace(marker, "<redacted>")
    return redacted


def _redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lower = str(key).lower()
            if any(marker in lower for marker in ["password", "token", "secret"]):
                result[key] = "<redacted>"
            else:
                result[key] = _redact_obj(item)
        return result
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value
