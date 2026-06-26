#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
SALT_VERSION="${SALT_VERSION:-3008.1}"
SALT_KEYRING="${SALT_KEYRING:-/etc/apt/keyrings/salt-archive-keyring.pgp}"
SALT_SOURCES="${SALT_SOURCES:-/etc/apt/sources.list.d/salt.sources}"
SALT_PIN="${SALT_PIN:-/etc/apt/preferences.d/proxyfleet-salt-pin}"
MINION_CONF="${MINION_CONF:-/etc/salt/minion.d/proxyfleet.conf}"
MINION_CONF_DIR="${MINION_CONF_DIR:-/etc/salt/minion.d}"
MINION_PKI_DIR="${MINION_PKI_DIR:-/etc/salt/pki/minion}"
PROXYFLEET_ETC_ROOT="${PROXYFLEET_ETC_ROOT:-/etc/proxyfleet}"
MIHOMO_BINARY="${MIHOMO_BINARY:-/usr/local/bin/mihomo}"
MIHOMO_UNIT_PATH="${MIHOMO_UNIT_PATH:-/etc/systemd/system/mihomo.service}"
MIHOMO_SERVICE="${MIHOMO_SERVICE:-mihomo.service}"
MIHOMO_CONFIG_PATH="${MIHOMO_CONFIG_PATH:-${PROXYFLEET_ETC_ROOT}/current/config.yaml}"
COMPONENT_LOCKS="${COMPONENT_LOCKS:-${PROXYFLEET_ETC_ROOT}/component-locks.json}"
MIHOMO_RECEIPT="${MIHOMO_RECEIPT:-${MIHOMO_BINARY}.proxyfleet-install.json}"
LOCAL_OPTIONS_PATH="${LOCAL_OPTIONS_PATH:-${PROXYFLEET_ETC_ROOT}/local/options.json}"
PROXYFLEET_VERSION="${PROXYFLEET_VERSION:-v0.1.0}"
UPDATE_MANIFEST_URL="${UPDATE_MANIFEST_URL:-https://raw.githubusercontent.com/Flashyuan/ProxyFleet/main/update-manifest.json}"
UPDATE_STATE_PATH="${UPDATE_STATE_PATH:-${PROXYFLEET_ETC_ROOT}/local/update-state.json}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"

die() {
  echo "错误：$*" >&2
  exit 1
}

need_root() {
  if [[ "${EUID}" -ne 0 && "${PROXYFLEET_TEST_ALLOW_NON_ROOT:-}" != "1" ]]; then
    die "此命令需要 root 权限，请使用 sudo 执行"
  fi
}

check_os() {
  . /etc/os-release
  [[ "${ID}" == "ubuntu" ]] || die "仅支持 Ubuntu，当前 ID=${ID}"
  case "${VERSION_ID}" in
    22.04|24.04) ;;
    *) die "仅支持 Ubuntu 22.04/24.04，当前 VERSION_ID=${VERSION_ID}" ;;
  esac
}

install_salt_repo() {
  install -d -m 0755 /etc/apt/keyrings
  if [[ ! -f "${SALT_KEYRING}" ]]; then
    curl -fsSL "https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public" \
      | gpg --dearmor -o "${SALT_KEYRING}"
  fi
  cat > "${SALT_SOURCES}" <<SOURCES
Types: deb
URIs: https://packages.broadcom.com/artifactory/saltproject-deb
Suites: stable
Components: main
Signed-By: ${SALT_KEYRING}
SOURCES
  cat > "${SALT_PIN}" <<PIN
Package: salt-master salt-minion salt-common salt-ssh salt-syndic salt-cloud salt-api
Pin: version ${SALT_VERSION}*
Pin-Priority: 1001
PIN
}

usage() {
  cat <<'USAGE'
用法：scripts/proxyfleet-minion.sh <command> [options]

命令：
  preflight
  bootstrap --master <master-host-or-ip> --id <minion-id>
          [--environment production] [--driver native-mihomo]
          [--release-channel stable]
  install --master <master-host-or-ip> --id <minion-id>
          [--environment production] [--driver native-mihomo]
          [--release-channel stable]
  start
  start --with-mihomo
  stop
  stop --with-mihomo
  restart
  restart --with-mihomo
  status
  check-update
  update [--yes]
  uninstall [--yes]
  uninstall --purge-data [--yes]
  mihomo-start
  mihomo-stop
  mihomo-restart
  mihomo-status
  mihomo-uninstall [--yes]

说明：
  --master-ip 是 --master 的兼容别名。
  start/stop/restart 默认只控制 salt-minion。
  uninstall 默认会停止并完整清理 salt-minion、ProxyFleet 受管 Mihomo 和 /etc/proxyfleet。
  脚本只删除 ProxyFleet 明确受管路径，不重置系统路由、DNS 或防火墙。
  install 不会自动接受 key。安装后必须在 Master 上人工核验 fingerprint：
    sudo salt-key -F
    sudo salt-key -a <minion-id>
USAGE
}

tui_available() {
  [[ -t 0 && -t 1 ]] || [[ "${PROXYFLEET_TEST_ALLOW_NON_TTY:-}" == "1" ]]
}

tui_clear() {
  if [[ -t 1 && -n "${TERM:-}" && "${TERM:-}" != "dumb" ]]; then
    clear
  fi
}

tui_pause() {
  if tui_available; then
    read -r -p "按 Enter 返回菜单..." _
  fi
}

tui_unavailable() {
  cat >&2 <<'EOF'
E_TUI_UNAVAILABLE: 当前不是交互式终端，无法进入 Minion TUI。

等价非交互命令示例：
  sudo scripts/proxyfleet-minion.sh preflight
  sudo scripts/proxyfleet-minion.sh install --master <master-ip> --id <minion-id>
  sudo scripts/proxyfleet-minion.sh status
  sudo scripts/proxyfleet-minion.sh mihomo-status
  sudo scripts/proxyfleet-minion.sh stop --with-mihomo
EOF
}

confirm_phrase() {
  local phrase="$1"
  local message="$2"
  local answer
  echo "${message}"
  read -r -p "请输入 ${phrase} 确认：" answer
  [[ "${answer}" == "${phrase}" ]]
}

preview_write() {
  local level="$1"
  shift
  echo "将执行的操作（危险等级：${level}）："
  printf '  - %s\n' "$@"
}

current_commit() {
  git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || echo "unknown"
}

proxyfleet_python() {
  if [[ ! -f "${PROJECT_ROOT}/src/proxyfleet/cli.py" ]]; then
    case "${1:-}" in
      check-update|update|suppress-update)
        python3 - "$@" <<'PY'
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

def die(code, msg):
    print(f"{code}: {msg}", file=sys.stderr)
    raise SystemExit(2)

def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def read_bytes(src):
    p = urlparse(src)
    if p.scheme in ("http", "https"):
        if p.username or p.password or p.scheme != "https":
            die("E_UPDATE_UNTRUSTED_SOURCE", "更新 URL 不可信")
        with urlopen(src, timeout=10) as r:
            return r.read()
    if p.scheme == "file":
        return Path(p.path).read_bytes()
    if p.scheme:
        die("E_UPDATE_UNTRUSTED_SOURCE", f"不支持的 URL 协议：{p.scheme}")
    return Path(src).read_bytes()

def load_state(path, version, commit):
    p = Path(path)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            die("E_UPDATE_MANIFEST", f"update-state 无效：{exc}")
    else:
        data = {"schema_version": "1.0"}
    data.setdefault("installed_version", version)
    data.setdefault("installed_commit", commit)
    data.setdefault("suppressed_versions", [])
    return data

def write_state(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)

def load_manifest(src):
    raw = read_bytes(src)
    try:
        m = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        die("E_UPDATE_MANIFEST", f"更新清单 JSON 无效：{exc}")
    if str(m.get("schema_version", "")).split(".", 1)[0] != "1" or m.get("product") != "proxyfleet":
        die("E_UPDATE_MANIFEST", "更新清单 schema/product 无效")
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", str(m.get("commit", ""))):
        die("E_UPDATE_MANIFEST", "更新清单 commit 必须是 Git SHA")
    assets = []
    for a in m.get("assets", []):
        if a.get("role") not in ("minion", "common"):
            continue
        if a.get("path") != "scripts/proxyfleet-minion.sh":
            die("E_UPDATE_SCOPE", f"Minion 单脚本更新只允许 scripts/proxyfleet-minion.sh：{a.get('path')}")
        u = urlparse(str(a.get("url", "")))
        if u.scheme not in ("https", "file") or u.username or u.password:
            die("E_UPDATE_UNTRUSTED_SOURCE", "asset URL 不可信")
        if u.netloc == "raw.githubusercontent.com":
            parts = [x for x in u.path.split("/") if x]
            if len(parts) >= 4 and parts[2] in {"main", "master"}:
                die("E_UPDATE_UNTRUSTED_SOURCE", "asset URL 不得使用 GitHub raw 浮动分支")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(a.get("sha256", ""))):
            die("E_UPDATE_MANIFEST", "asset sha256 无效")
        assets.append(a)
    if not assets:
        die("E_UPDATE_MANIFEST", "更新清单没有适用于 Minion 的资产")
    return m, hashlib.sha256(raw).hexdigest(), assets

cmd = sys.argv[1]
ap = argparse.ArgumentParser()
ap.add_argument("--role", required=True)
ap.add_argument("--install-root", required=True)
ap.add_argument("--state-path", required=True)
ap.add_argument("--manifest-url", required=True)
ap.add_argument("--current-version", default="unknown")
ap.add_argument("--current-commit", default="unknown")
ap.add_argument("--respect-suppressed", action="store_true")
ap.add_argument("--version")
ap.add_argument("--yes", action="store_true")
ns = ap.parse_args(sys.argv[2:])
if ns.role != "minion":
    die("E_UPDATE_SCOPE", "单脚本 fallback 只支持 Minion 更新")

manifest, manifest_sha, assets = load_manifest(ns.manifest_url)
state = load_state(ns.state_path, ns.current_version, ns.current_commit)
remote_version = str(manifest.get("version", "unknown"))
remote_commit = str(manifest.get("commit", "unknown"))

if cmd == "suppress-update":
    if not ns.version:
        die("E_UPDATE_MANIFEST", "缺少 --version")
    state["suppressed_versions"] = list(dict.fromkeys([*state.get("suppressed_versions", []), ns.version]))
    state["last_prompted_version"] = ns.version
    state["last_update_status"] = "skipped"
    write_state(ns.state_path, state)
    print(json.dumps({"schema_version":"1.0","role":"minion","status":"skipped","remote_version":ns.version}, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0)

status = "available"
if remote_commit == state.get("installed_commit") or remote_version == state.get("installed_version"):
    status = "not_available"
elif ns.respect_suppressed and remote_version in set(state.get("suppressed_versions") or []):
    status = "skipped"
state["last_checked_at"] = now()
write_state(ns.state_path, state)
if cmd == "check-update":
    print(json.dumps({"schema_version":"1.0","role":"minion","status":status,"current_version":state.get("installed_version"),"current_commit":state.get("installed_commit"),"remote_version":remote_version,"remote_commit":remote_commit,"manifest_sha256":manifest_sha,"summary":manifest.get("summary", []),"assets":[{"path":a["path"],"role":a["role"],"sha256":a["sha256"]} for a in assets]}, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0)

if cmd != "update":
    die("E_UPDATE_MANIFEST", f"未知 fallback 命令：{cmd}")
if status == "not_available":
    print(json.dumps({"schema_version":"1.0","role":"minion","status":"not_available","remote_version":remote_version,"remote_commit":remote_commit}, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0)
if not ns.yes:
    die("E_UPDATE_CONFIRMATION", "应用更新需要用户确认")

asset = assets[0]
data = read_bytes(asset["url"])
if hashlib.sha256(data).hexdigest().lower() != asset["sha256"].lower():
    die("E_UPDATE_HASH", "资产 SHA-256 不匹配")
root = Path(ns.install_root)
target = root / "scripts" / "proxyfleet-minion.sh"
backup_root = root / ".proxyfleet-update-backups" / f"update-op-{int(time.time())}"
backup = backup_root / "scripts" / "proxyfleet-minion.sh"
backup.parent.mkdir(parents=True, exist_ok=True)
if target.exists():
    shutil.copy2(target, backup)
else:
    backup.write_text("__PROXYFLEET_MISSING__\n", encoding="utf-8")
fd, tmp = tempfile.mkstemp(prefix=".proxyfleet-minion.sh.", dir=str(target.parent))
try:
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, int(str(asset.get("mode", "0755")), 8))
    os.replace(tmp, target)
    result = subprocess.run(["bash", "-n", str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
except Exception as exc:
    if backup.exists() and backup.read_text(encoding="utf-8", errors="ignore") == "__PROXYFLEET_MISSING__\n":
        target.unlink(missing_ok=True)
    elif backup.exists():
        shutil.copy2(backup, target)
    Path(tmp).unlink(missing_ok=True)
    die("E_UPDATE_VERIFY", f"更新失败，已尝试回滚：{exc}")
state["installed_version"] = remote_version
state["installed_commit"] = remote_commit
state["last_update_status"] = "success"
write_state(ns.state_path, state)
print(json.dumps({"schema_version":"1.0","role":"minion","status":"success","remote_version":remote_version,"remote_commit":remote_commit,"evidence":{"manifest_sha256":manifest_sha,"backup_path":str(backup_root),"updated_files":["scripts/proxyfleet-minion.sh"]}}, ensure_ascii=False, indent=2, sort_keys=True))
PY
        return
        ;;
      *) die "E_UPDATE_MANIFEST: 当前目录缺少 src/proxyfleet/cli.py，无法执行 proxyfleet CLI" ;;
    esac
  fi
  PYTHONPATH="${PROJECT_ROOT}/src" python3 -m proxyfleet.cli "$@"
}

check_update_minion() {
  proxyfleet_python check-update \
    --role minion \
    --install-root "${PROJECT_ROOT}" \
    --state-path "${UPDATE_STATE_PATH}" \
    --manifest-url "${UPDATE_MANIFEST_URL}" \
    --current-version "${PROXYFLEET_VERSION}" \
    --current-commit "$(current_commit)"
}

apply_update_minion() {
  need_root
  proxyfleet_python update \
    --role minion \
    --install-root "${PROJECT_ROOT}" \
    --state-path "${UPDATE_STATE_PATH}" \
    --manifest-url "${UPDATE_MANIFEST_URL}" \
    --current-version "${PROXYFLEET_VERSION}" \
    --current-commit "$(current_commit)" \
    --yes
}

suppress_update_minion() {
  local version="$1"
  proxyfleet_python suppress-update \
    --role minion \
    --install-root "${PROJECT_ROOT}" \
    --state-path "${UPDATE_STATE_PATH}" \
    --manifest-url "${UPDATE_MANIFEST_URL}" \
    --current-version "${PROXYFLEET_VERSION}" \
    --current-commit "$(current_commit)" \
    --version "${version}"
}

update_minion_tui() {
  local payload status version choice
  payload="$(check_update_minion)" || return $?
  echo "${payload}"
  status="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' <<<"${payload}")"
  version="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("remote_version","unknown"))' <<<"${payload}")"
  if [[ "${status}" != "available" ]]; then
    echo "当前没有需要应用的更新。"
    return 0
  fi
  echo
  echo "发现新版本：${version}"
  echo "1) 是，应用更新"
  echo "2) 否，本次跳过"
  echo "3) 否，并不再提醒此版本"
  read -r -p "请选择: " choice
  case "${choice}" in
    1)
      preview_write "high" \
        "下载并校验 update manifest 中的 Minion 资产" \
        "备份并原子替换 scripts/proxyfleet-minion.sh" \
        "不会覆盖 /etc/salt、/etc/proxyfleet、Mihomo、release 或 local override" \
        "更新不会自动启动、停止、重启或卸载 Mihomo"
      confirm_phrase "UPDATE" "确认应用 ProxyFleet Minion 更新？" || return 0
      apply_update_minion
      ;;
    3) suppress_update_minion "${version}" ;;
    *) echo "已跳过更新" ;;
  esac
}

write_local_options() {
  local mode="$1"
  case "${mode}" in
    merge|master-only|local-only|disabled) ;;
    *) die "端口策略模式无效：${mode}" ;;
  esac
  install -d -m 0755 "$(dirname "${LOCAL_OPTIONS_PATH}")"
  python3 - "${LOCAL_OPTIONS_PATH}" "${mode}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
mode = sys.argv[2]
payload = {"schema_version": "1.0", "port_policy_mode": mode}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

show_local_options() {
  if [[ -f "${LOCAL_OPTIONS_PATH}" ]]; then
    cat "${LOCAL_OPTIONS_PATH}"
  else
    echo "未配置本机端口策略模式；默认跟随 Master 下发 mode，缺省为 merge。"
  fi
}

minion_install_tui() {
  local master minion_id environment driver release_channel
  read -r -p "Master IP/Host: " master
  read -r -p "Minion ID [$(hostname)-machine]: " minion_id
  minion_id="${minion_id:-$(hostname)-machine}"
  read -r -p "environment [production]: " environment
  environment="${environment:-production}"
  read -r -p "driver [native-mihomo]: " driver
  driver="${driver:-native-mihomo}"
  read -r -p "release channel [stable]: " release_channel
  release_channel="${release_channel:-stable}"
  [[ -n "${master}" ]] || die "Master 地址不能为空"
  preview_write "medium" \
    "安装/修复 Salt Minion ${SALT_VERSION}" \
    "写入 ${MINION_CONF}" \
    "Master=${master}" \
    "Minion ID=${minion_id}" \
    "driver=${driver}"
  confirm_phrase "INSTALL" "确认安装/修复 Minion？" || return 0
  install_minion \
    --master "${master}" \
    --id "${minion_id}" \
    --environment "${environment}" \
    --driver "${driver}" \
    --release-channel "${release_channel}"
}

connectivity_tui() {
  local master
  read -r -p "Master IP/Host: " master
  [[ -n "${master}" ]] || die "Master 地址不能为空"
  for port in 4505 4506; do
    if timeout 3 bash -c "</dev/tcp/${master}/${port}" 2>/dev/null; then
      echo "${port}-ok"
    else
      echo "${port}-failed"
    fi
  done
}

local_port_policy_tui() {
  local choice source_path
  echo "当前本机选项："
  show_local_options
  echo
  echo "1) 设置模式 merge"
  echo "2) 设置模式 master-only"
  echo "3) 设置模式 local-only"
  echo "4) 设置模式 disabled"
  echo "5) 导入本机端口白名单 YAML"
  read -r -p "请选择: " choice
  case "${choice}" in
    1) preview_write "medium" "写入 ${LOCAL_OPTIONS_PATH}" "port_policy_mode=merge"; confirm_phrase "WRITE" "确认写入？" && write_local_options "merge" ;;
    2) preview_write "medium" "写入 ${LOCAL_OPTIONS_PATH}" "port_policy_mode=master-only"; confirm_phrase "WRITE" "确认写入？" && write_local_options "master-only" ;;
    3) preview_write "medium" "写入 ${LOCAL_OPTIONS_PATH}" "port_policy_mode=local-only"; confirm_phrase "WRITE" "确认写入？" && write_local_options "local-only" ;;
    4) preview_write "medium" "写入 ${LOCAL_OPTIONS_PATH}" "port_policy_mode=disabled"; confirm_phrase "WRITE" "确认写入？" && write_local_options "disabled" ;;
    5)
      read -r -p "源 YAML 路径: " source_path
      [[ -n "${source_path}" && -f "${source_path}" ]] || die "源文件不存在：${source_path}"
      preview_write "medium" "复制 ${source_path}" "覆盖 ${PROXYFLEET_ETC_ROOT}/local/port-policy.yaml"
      confirm_phrase "WRITE" "确认导入本机端口白名单？" || return 0
      install -D -m 0644 "${source_path}" "${PROXYFLEET_ETC_ROOT}/local/port-policy.yaml"
      ;;
    *) echo "已取消" ;;
  esac
}

minion_services_tui() {
  local choice
  echo "1) start salt-minion"
  echo "2) stop salt-minion"
  echo "3) restart salt-minion"
  echo "4) start salt-minion + Mihomo"
  echo "5) stop Mihomo + salt-minion"
  echo "6) restart salt-minion + Mihomo"
  read -r -p "请选择服务操作: " choice
  case "${choice}" in
    1) start_command ;;
    2) preview_write "high" "停止 salt-minion" "Master 将无法同步本机"; confirm_phrase "STOP" "确认停止？" && stop_command ;;
    3) restart_command ;;
    4) start_command --with-mihomo ;;
    5) preview_write "high" "停止 Mihomo 和 salt-minion" "本机代理将中断"; confirm_phrase "STOP" "确认停止？" && stop_command --with-mihomo ;;
    6) restart_command --with-mihomo ;;
    *) echo "已取消" ;;
  esac
}

minion_tui() {
  if ! tui_available; then
    tui_unavailable
    return 2
  fi
  local choice
  while true; do
    tui_clear
    cat <<'MENU'
ProxyFleet Minion 主控台

1) 只读预检
2) 安装/修复 Salt Minion
3) 检测并更新 ProxyFleet Minion
4) 测试 Master 4505/4506 连通性
5) 查看 Salt Minion 状态
6) 查看 Mihomo 状态
7) 启动/停止/重启服务
8) 配置本机端口白名单和同步模式
9) 卸载 Minion
10) 卸载 Mihomo
q) 退出
MENU
    read -r -p "请选择: " choice
    case "${choice}" in
      1) preflight; tui_pause ;;
      2) minion_install_tui; tui_pause ;;
      3) update_minion_tui; tui_pause ;;
      4) connectivity_tui; tui_pause ;;
      5) status_minion; tui_pause ;;
      6) mihomo_status; tui_pause ;;
      7) minion_services_tui; tui_pause ;;
      8) local_port_policy_tui; tui_pause ;;
      9) preview_write "critical" "停止 salt-minion 和 ProxyFleet 受管 Mihomo" "卸载 salt-minion" "删除 ${PROXYFLEET_ETC_ROOT}、Minion PKI 和配置"; confirm_phrase "UNINSTALL" "确认完整卸载 Minion？" && uninstall_command --yes; tui_pause ;;
      10) preview_write "critical" "停止并卸载 ProxyFleet 受管 Mihomo" "删除 ${PROXYFLEET_ETC_ROOT}、受管二进制和 systemd unit"; confirm_phrase "UNINSTALL MIHOMO" "确认卸载 Mihomo？" && mihomo_uninstall --yes; tui_pause ;;
      q|Q) return 0 ;;
      *) echo "未知选项"; tui_pause ;;
    esac
  done
}

parse_install_args() {
  MASTER=""
  MINION_ID=""
  ENVIRONMENT="production"
  DRIVER="native-mihomo"
  RELEASE_CHANNEL="stable"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --master|--master-ip) MASTER="${2:-}"; shift 2 ;;
      --id) MINION_ID="${2:-}"; shift 2 ;;
      --environment) ENVIRONMENT="${2:-}"; shift 2 ;;
      --driver) DRIVER="${2:-}"; shift 2 ;;
      --release-channel) RELEASE_CHANNEL="${2:-}"; shift 2 ;;
      *) die "未知参数：$1" ;;
    esac
  done
  [[ -n "${MASTER}" ]] || die "缺少 --master"
  [[ -n "${MINION_ID}" ]] || die "缺少 --id"
}

install_minion() {
  need_root
  check_os
  parse_install_args "$@"
  install_salt_repo
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    "salt-common=${SALT_VERSION}*" \
    "salt-minion=${SALT_VERSION}*"
  apt-mark hold salt-common salt-minion

  systemctl stop salt-minion || true
  install -d -m 0755 /etc/salt/minion.d
  cat > "${MINION_CONF}" <<CONF
# ProxyFleet Salt Minion POC 配置。
master: ${MASTER}
id: ${MINION_ID}
grains:
  environment: ${ENVIRONMENT}
  driver: ${DRIVER}
  os_baseline: ubuntu-$(. /etc/os-release && echo "${VERSION_ID}")
  release_channel: ${RELEASE_CHANNEL}
CONF

  systemctl enable salt-minion
  systemctl restart salt-minion
  echo "Minion 安装完成。请回到 Master 人工核验并接受 key：${MINION_ID}"
  echo "本机 Minion fingerprint："
  salt-call --local key.finger || true
  echo "Master 端下一步：sudo salt-key -F && sudo salt-key -a ${MINION_ID}"
}

start_minion() {
  need_root
  systemctl start salt-minion
}

stop_minion() {
  need_root
  systemctl stop salt-minion
}

restart_minion() {
  need_root
  systemctl restart salt-minion
}

status_minion() {
  systemctl status salt-minion --no-pager || true
}

uninstall_minion() {
  need_root
  local yes="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --purge-data) shift ;; # 兼容旧参数；当前 uninstall 默认完整清理。
      --yes) yes="1"; shift ;;
      "") shift ;;
      *) die "未知 salt-minion 卸载参数：$1" ;;
    esac
  done
  if [[ "${yes}" != "1" ]]; then
    if ! confirm_phrase "UNINSTALL PROXYFLEET MINION" "危险操作：将停止并完整删除 ProxyFleet Minion 受管数据和组件"; then
      die "已取消卸载"
    fi
  fi
  systemctl disable --now salt-minion || true
  apt-mark unhold salt-minion salt-common || true
  DEBIAN_FRONTEND=noninteractive apt-get purge -y salt-minion || true
  echo "删除 Minion PKI 和 ProxyFleet Minion 配置。"
  rm -rf "${MINION_PKI_DIR}" "${MINION_CONF_DIR}"
  rm -f "${SALT_SOURCES}" "${SALT_PIN}" "${SALT_KEYRING}"
}

with_mihomo_arg() {
  for arg in "$@"; do
    if [[ "${arg}" == "--with-mihomo" ]]; then
      return 0
    fi
  done
  return 1
}

assert_mihomo_unit_owned() {
  local unit_text
  if unit_text="$("${SYSTEMCTL}" cat "${MIHOMO_SERVICE}" 2>/dev/null)"; then
    :
  elif [[ -f "${MIHOMO_UNIT_PATH}" ]]; then
    unit_text="$(cat "${MIHOMO_UNIT_PATH}")"
  else
    die "E_SERVICE_SYSTEMD: mihomo.service 不存在：${MIHOMO_UNIT_PATH}"
  fi
  grep -q "ProxyFleet managed Mihomo" <<<"${unit_text}" || die "E_SERVICE_OWNERSHIP: mihomo.service 非 ProxyFleet 所有"
  grep -q "ExecStart=${MIHOMO_BINARY} " <<<"${unit_text}" || die "E_SERVICE_OWNERSHIP: mihomo.service ExecStart 未指向受管二进制"
  grep -q -- "-f ${MIHOMO_CONFIG_PATH}" <<<"${unit_text}" || die "E_SERVICE_OWNERSHIP: mihomo.service ExecStart 未指向受管配置"
}

assert_mihomo_binary_owned() {
  [[ -x "${MIHOMO_BINARY}" ]] || die "受管 Mihomo 二进制不存在或不可执行：${MIHOMO_BINARY}"
  [[ -f "${COMPONENT_LOCKS}" ]] || die "E_COMPONENT_INTEGRITY_MISSING: 缺少组件锁：${COMPONENT_LOCKS}"
  [[ -f "${MIHOMO_RECEIPT}" ]] || die "E_COMPONENT_INTEGRITY_MISSING: 缺少 Mihomo 安装 receipt：${MIHOMO_RECEIPT}"
  python3 - "${COMPONENT_LOCKS}" "${MIHOMO_BINARY}" "${MIHOMO_RECEIPT}" <<'PY'
import hashlib
import json
import sys

locks = json.load(open(sys.argv[1], encoding="utf-8"))
target = sys.argv[2]
receipt = json.load(open(sys.argv[3], encoding="utf-8"))
artifact_sha = receipt.get("artifact_sha256")
binary_sha = receipt.get("binary_sha256")
with open(target, "rb") as fh:
    actual_binary_sha = hashlib.sha256(fh.read()).hexdigest()
if not binary_sha or binary_sha != actual_binary_sha:
    raise SystemExit("E_COMPONENT_INTEGRITY_MISSING: Mihomo 二进制 SHA 与 receipt 不匹配")
for component in locks.get("components", []):
    if component.get("name") != "mihomo":
        continue
    if receipt.get("version") and component.get("version") != receipt.get("version"):
        continue
    artifacts = component.get("artifacts", {})
    for artifact in artifacts.values():
        if not isinstance(artifact, dict):
            continue
        if artifact.get("target_path") == target and artifact.get("sha256") == artifact_sha and artifact.get("compression") == "gzip":
            raise SystemExit(0)
raise SystemExit("E_COMPONENT_INTEGRITY_MISSING: 组件锁与 Mihomo receipt 不匹配")
PY
}

assert_mihomo_config_ready() {
  [[ -r "${MIHOMO_CONFIG_PATH}" ]] || die "受管 Mihomo 配置不可读：${MIHOMO_CONFIG_PATH}"
  "${MIHOMO_BINARY}" -t -d "$(dirname "${MIHOMO_CONFIG_PATH}")" -f "${MIHOMO_CONFIG_PATH}" >/dev/null \
    || die "E_CONFIG_VALIDATE: Mihomo 配置校验失败"
}

assert_mihomo_owned() {
  assert_mihomo_unit_owned
  assert_mihomo_binary_owned
}

mihomo_start() {
  need_root
  assert_mihomo_owned
  assert_mihomo_config_ready
  "${SYSTEMCTL}" daemon-reload
  "${SYSTEMCTL}" start "${MIHOMO_SERVICE}" || die "E_SERVICE_SYSTEMD: Mihomo 启动失败"
  "${SYSTEMCTL}" is-active --quiet "${MIHOMO_SERVICE}" || die "Mihomo 启动后未处于 active 状态"
}

mihomo_stop() {
  need_root
  assert_mihomo_unit_owned
  "${SYSTEMCTL}" stop "${MIHOMO_SERVICE}" || die "E_SERVICE_SYSTEMD: Mihomo 停止失败"
}

mihomo_restart() {
  need_root
  assert_mihomo_owned
  assert_mihomo_config_ready
  "${SYSTEMCTL}" daemon-reload
  "${SYSTEMCTL}" restart "${MIHOMO_SERVICE}" || die "E_SERVICE_SYSTEMD: Mihomo 重启失败"
  "${SYSTEMCTL}" is-active --quiet "${MIHOMO_SERVICE}" || die "Mihomo 重启后未处于 active 状态"
}

mihomo_status() {
  assert_mihomo_unit_owned
  "${SYSTEMCTL}" status "${MIHOMO_SERVICE}" --no-pager || true
}

mihomo_uninstall() {
  need_root
  local yes="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --purge-managed|--purge-all|--purge-local-override) shift ;; # 兼容旧参数；当前默认完整清理。
      --yes) yes="1"; shift ;;
      *) die "未知 Mihomo 卸载参数：$1" ;;
    esac
  done

  if [[ "${yes}" != "1" ]]; then
    if ! confirm_phrase "UNINSTALL PROXYFLEET MIHOMO" "危险操作：将删除 ProxyFleet 受管 Mihomo、${PROXYFLEET_ETC_ROOT} 和相关 unit"; then
      die "已取消 Mihomo 卸载"
    fi
  fi
  if ! ( assert_mihomo_unit_owned ); then
    echo "未发现 ProxyFleet 受管 Mihomo unit，跳过 Mihomo 服务删除。"
  else
    "${SYSTEMCTL}" stop "${MIHOMO_SERVICE}" || true
    "${SYSTEMCTL}" disable "${MIHOMO_SERVICE}" || true
    rm -f "${MIHOMO_UNIT_PATH}"
    "${SYSTEMCTL}" daemon-reload || true
  fi

  if [[ -f "${MIHOMO_RECEIPT}" ]]; then
    if ( assert_mihomo_binary_owned ); then
      rm -f "${MIHOMO_BINARY}" "${MIHOMO_RECEIPT}"
    else
      echo "Mihomo 二进制 ownership 校验失败，已保守跳过二进制删除。" >&2
    fi
  fi
  rm -rf "${PROXYFLEET_ETC_ROOT}"
  echo "Mihomo 卸载完成。未修改系统路由、DNS、防火墙或其它网络配置。"
}

cleanup_project_runtime() {
  rm -rf "${PROXYFLEET_ETC_ROOT}"
}

uninstall_command() {
  local yes="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --with-mihomo|--purge-data|--purge-managed|--purge-all|--purge-local-override) shift ;; # 兼容旧参数；当前默认完整清理。
      --yes) yes="1"; shift ;;
      *) die "未知卸载参数：$1" ;;
    esac
  done
  if [[ "${yes}" != "1" ]]; then
    if ! confirm_phrase "UNINSTALL PROXYFLEET MINION" "危险操作：将停止并完整删除 ProxyFleet Minion、受管 Mihomo 和本项目数据"; then
      die "已取消卸载"
    fi
  fi
  mihomo_uninstall --yes || true
  cleanup_project_runtime
  uninstall_minion --yes
  echo "Minion 卸载完成。未修改系统路由、DNS、防火墙或其它网络配置。"
}

start_command() {
  start_minion
  if with_mihomo_arg "$@"; then
    mihomo_start
  fi
}

stop_command() {
  if with_mihomo_arg "$@"; then
    mihomo_stop
  fi
  stop_minion
}

restart_command() {
  restart_minion
  if with_mihomo_arg "$@"; then
    mihomo_restart
  fi
}

preflight() {
  check_os
  echo "OS: $(. /etc/os-release && echo "${PRETTY_NAME}")"
  echo "Salt target version: ${SALT_VERSION}"
  echo "systemd: $(systemctl --version | head -n 1)"
  echo "sudo: $(command -v sudo || true)"
}

command="${1:-}"
case "${command}" in
  "") minion_tui ;;
  preflight) preflight ;;
  bootstrap) shift; install_minion "$@" ;;
  install) shift; install_minion "$@" ;;
  start) shift; start_command "$@" ;;
  stop) shift; stop_command "$@" ;;
  restart) shift; restart_command "$@" ;;
  status) status_minion ;;
  check-update) shift; check_update_minion "$@" ;;
  update) shift; need_root; if [[ "${1:-}" == "--yes" ]]; then apply_update_minion; else update_minion_tui; fi ;;
  uninstall) shift; uninstall_command "$@" ;;
  mihomo-start) shift; mihomo_start "$@" ;;
  mihomo-stop) shift; mihomo_stop "$@" ;;
  mihomo-restart) shift; mihomo_restart "$@" ;;
  mihomo-status) shift; mihomo_status "$@" ;;
  mihomo-uninstall) shift; mihomo_uninstall "$@" ;;
  *) usage; exit 2 ;;
esac
