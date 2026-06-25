#!/usr/bin/env bash
set -Eeuo pipefail

SALT_VERSION="${SALT_VERSION:-3008.1}"
SALT_KEYRING="/etc/apt/keyrings/salt-archive-keyring.pgp"
SALT_SOURCES="/etc/apt/sources.list.d/salt.sources"
SALT_PIN="/etc/apt/preferences.d/proxyfleet-salt-pin"
MINION_CONF="/etc/salt/minion.d/proxyfleet.conf"
PROXYFLEET_ETC_ROOT="${PROXYFLEET_ETC_ROOT:-/etc/proxyfleet}"
MIHOMO_BINARY="${MIHOMO_BINARY:-/usr/local/bin/mihomo}"
MIHOMO_UNIT_PATH="${MIHOMO_UNIT_PATH:-/etc/systemd/system/mihomo.service}"
MIHOMO_SERVICE="${MIHOMO_SERVICE:-mihomo.service}"
MIHOMO_CONFIG_PATH="${MIHOMO_CONFIG_PATH:-${PROXYFLEET_ETC_ROOT}/current/config.yaml}"
COMPONENT_LOCKS="${COMPONENT_LOCKS:-${PROXYFLEET_ETC_ROOT}/component-locks.json}"
MIHOMO_RECEIPT="${MIHOMO_RECEIPT:-${MIHOMO_BINARY}.proxyfleet-install.json}"
LOCAL_OPTIONS_PATH="${LOCAL_OPTIONS_PATH:-${PROXYFLEET_ETC_ROOT}/local/options.json}"
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
  uninstall
  uninstall --with-mihomo [--purge-managed] [--purge-all --yes]
          [--purge-local-override] [--purge-data]
  uninstall --purge-data [--yes]
  mihomo-start
  mihomo-stop
  mihomo-restart
  mihomo-status
  mihomo-uninstall [--purge-managed] [--purge-all --yes]
          [--purge-local-override]

说明：
  --master-ip 是 --master 的兼容别名。
  start/stop/restart/uninstall 默认只控制 salt-minion。
  Mihomo 只通过 --with-mihomo 或 mihomo-* 专用子命令显式控制。
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
3) 测试 Master 4505/4506 连通性
4) 查看 Salt Minion 状态
5) 查看 Mihomo 状态
6) 启动/停止/重启服务
7) 配置本机端口白名单和同步模式
8) 卸载 Minion
9) 卸载 Mihomo
q) 退出
MENU
    read -r -p "请选择: " choice
    case "${choice}" in
      1) preflight; tui_pause ;;
      2) minion_install_tui; tui_pause ;;
      3) connectivity_tui; tui_pause ;;
      4) status_minion; tui_pause ;;
      5) mihomo_status; tui_pause ;;
      6) minion_services_tui; tui_pause ;;
      7) local_port_policy_tui; tui_pause ;;
      8) preview_write "critical" "卸载 salt-minion" "默认保留 Minion PKI 和配置"; confirm_phrase "UNINSTALL" "确认卸载 Minion？" && uninstall_command; tui_pause ;;
      9) preview_write "critical" "卸载 ProxyFleet 受管 Mihomo" "默认保留 ${PROXYFLEET_ETC_ROOT} 和 local override"; confirm_phrase "UNINSTALL MIHOMO" "确认卸载 Mihomo？" && mihomo_uninstall; tui_pause ;;
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
  local purge_data="0"
  local yes="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --purge-data) purge_data="1"; shift ;;
      --yes) yes="1"; shift ;;
      "") shift ;;
      *) die "未知 salt-minion 卸载参数：$1" ;;
    esac
  done
  if [[ "${purge_data}" == "1" && "${yes}" != "1" ]]; then
    if ! confirm_phrase "PURGE MINION DATA" "危险操作：将删除 /etc/salt/pki/minion 和 /etc/salt/minion.d"; then
      die "已取消 purge-data"
    fi
  fi
  systemctl disable --now salt-minion || true
  apt-mark unhold salt-minion salt-common || true
  DEBIAN_FRONTEND=noninteractive apt-get purge -y salt-minion || true
  if [[ "${purge_data}" == "1" ]]; then
    echo "危险操作：删除 /etc/salt/pki/minion 和 /etc/salt/minion.d"
    rm -rf /etc/salt/pki/minion /etc/salt/minion.d
  else
    echo "已卸载 salt-minion 包；默认保留 Minion PKI 和配置。"
  fi
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
  local purge_managed="0"
  local purge_all="0"
  local yes="0"
  local purge_local_override="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --purge-managed) purge_managed="1"; shift ;;
      --purge-all) purge_all="1"; shift ;;
      --yes) yes="1"; shift ;;
      --purge-local-override) purge_local_override="1"; shift ;;
      *) die "未知 Mihomo 卸载参数：$1" ;;
    esac
  done

  assert_mihomo_owned
  if [[ "${purge_all}" == "1" && "${yes}" != "1" ]]; then
    die "--purge-all 必须同时传入 --yes"
  fi
  if [[ "${purge_local_override}" == "1" && ! ( "${purge_all}" == "1" && "${yes}" == "1" ) ]]; then
    die "--purge-local-override 只能与 --purge-all --yes 同时使用"
  fi

  "${SYSTEMCTL}" stop "${MIHOMO_SERVICE}" || true
  "${SYSTEMCTL}" disable "${MIHOMO_SERVICE}" || true
  rm -f "${MIHOMO_UNIT_PATH}"
  "${SYSTEMCTL}" daemon-reload || true

  if [[ "${purge_managed}" == "1" || "${purge_all}" == "1" ]]; then
    rm -rf "${PROXYFLEET_ETC_ROOT}/managed" "${PROXYFLEET_ETC_ROOT}/effective"
  fi
  if [[ "${purge_all}" == "1" ]]; then
    rm -rf "${PROXYFLEET_ETC_ROOT}/releases" \
      "${PROXYFLEET_ETC_ROOT}/current" \
      "${PROXYFLEET_ETC_ROOT}/previous"
    rm -f "${MIHOMO_BINARY}" "${MIHOMO_RECEIPT}"
    if [[ "${purge_local_override}" == "1" ]]; then
      rm -rf "${PROXYFLEET_ETC_ROOT}/local"
    fi
  fi
  echo "Mihomo 卸载完成。默认保留 ${PROXYFLEET_ETC_ROOT}、release 和 local override。"
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

uninstall_command() {
  local salt_args=()
  local mihomo_args=()
  local with_mihomo="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --with-mihomo) with_mihomo="1"; shift ;;
      --purge-data)
        salt_args+=("$1")
        shift
        ;;
      --yes)
        salt_args+=("$1")
        mihomo_args+=("$1")
        shift
        ;;
      --purge-managed|--purge-all|--yes|--purge-local-override)
        mihomo_args+=("$1")
        shift
        ;;
      *) die "未知卸载参数：$1" ;;
    esac
  done
  if [[ "${with_mihomo}" == "1" ]]; then
    mihomo_uninstall "${mihomo_args[@]}"
  fi
  uninstall_minion "${salt_args[@]}"
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
  uninstall) shift; uninstall_command "$@" ;;
  mihomo-start) shift; mihomo_start "$@" ;;
  mihomo-stop) shift; mihomo_stop "$@" ;;
  mihomo-restart) shift; mihomo_restart "$@" ;;
  mihomo-status) shift; mihomo_status "$@" ;;
  mihomo-uninstall) shift; mihomo_uninstall "$@" ;;
  *) usage; exit 2 ;;
esac
