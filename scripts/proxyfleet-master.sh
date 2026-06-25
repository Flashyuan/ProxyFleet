#!/usr/bin/env bash
set -Eeuo pipefail

SALT_VERSION="${SALT_VERSION:-3008.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
SALT_KEYRING="/etc/apt/keyrings/salt-archive-keyring.pgp"
SALT_SOURCES="/etc/apt/sources.list.d/salt.sources"
SALT_PIN="/etc/apt/preferences.d/proxyfleet-salt-pin"
MASTER_CONF="/etc/salt/master.d/proxyfleet.conf"
SALT_STATES_ROOT="/srv/proxyfleet/salt/states"
SALT_PILLAR_ROOT="/srv/proxyfleet/salt/pillar"

die() {
  echo "错误：$*" >&2
  exit 1
}

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "此命令需要 root 权限，请使用 sudo 执行"
  fi
}

check_os() {
  # 只支持项目基线 Ubuntu 22.04/24.04。
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

install_master() {
  need_root
  check_os
  install_salt_repo
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    "salt-common=${SALT_VERSION}*" \
    "salt-master=${SALT_VERSION}*"
  apt-mark hold salt-common salt-master

  install -d -m 0755 /etc/salt/master.d
  install -d -m 0755 "${SALT_STATES_ROOT}/poc"
  install -d -m 0755 "${SALT_PILLAR_ROOT}"
  install -d -m 0755 "${PROJECT_ROOT}"

  cat > "${MASTER_CONF}" <<CONF
# ProxyFleet Salt Master POC 配置。
# 不启用 salt-api；Minion key 必须人工核验后接受。
interface: 0.0.0.0
publish_port: 4505
ret_port: 4506
auto_accept: False
open_mode: False
file_roots:
  base:
    - ${SALT_STATES_ROOT}
pillar_roots:
  base:
    - ${SALT_PILLAR_ROOT}
CONF

  cat > "${SALT_STATES_ROOT}/poc/init.sls" <<'SLS'
proxyfleet_poc_marker:
  file.managed:
    - name: /tmp/proxyfleet-salt-poc
    - contents: "ProxyFleet Salt POC\n"
    - mode: "0644"
SLS
  sync_assets

  systemctl enable --now salt-master
  echo "Master 安装完成。请在防火墙/云安全组仅向受管 Minion 开放 TCP 4505/4506。"
}

sync_assets() {
  need_root
  [[ -f "${PROJECT_ROOT}/salt/modules/proxyfleet_mihomo.py" ]] || die "缺少 ${PROJECT_ROOT}/salt/modules/proxyfleet_mihomo.py"
  [[ -d "${PROJECT_ROOT}/salt/states/proxyfleet" ]] || die "缺少 ${PROJECT_ROOT}/salt/states/proxyfleet"
  install -d -m 0755 "${SALT_STATES_ROOT}/_modules"
  install -m 0644 "${PROJECT_ROOT}/salt/modules/proxyfleet_mihomo.py" "${SALT_STATES_ROOT}/_modules/proxyfleet_mihomo.py"
  install -d -m 0755 "${SALT_STATES_ROOT}/proxyfleet"

  local source_dir="${PROJECT_ROOT}/salt/states/proxyfleet"
  local target_dir="${SALT_STATES_ROOT}/proxyfleet"
  local path rel
  while IFS= read -r path; do
    rel="${path#${source_dir}/}"
    install -d -m 0755 "${target_dir}/${rel}"
  done < <(find "${source_dir}" -type d)
  while IFS= read -r path; do
    rel="${path#${source_dir}/}"
    install -D -m 0644 "${path}" "${target_dir}/${rel}"
  done < <(find "${source_dir}" -type f)
  echo "ProxyFleet Salt assets 已同步到 ${SALT_STATES_ROOT}"
}

start_master() {
  need_root
  systemctl start salt-master
}

stop_master() {
  need_root
  systemctl stop salt-master
}

restart_master() {
  need_root
  systemctl restart salt-master
}

status_master() {
  systemctl status salt-master --no-pager || true
  echo
  echo "Salt key 列表："
  salt-key -L || true
}

latest_release_dir() {
  if [[ -d "${PROJECT_ROOT}/releases" ]]; then
    find "${PROJECT_ROOT}/releases" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
      | sort -n \
      | tail -n 1 \
      | sed "s#^#${PROJECT_ROOT}/releases/#"
  fi
}

proxyfleet_python() {
  PYTHONPATH="${PROJECT_ROOT}/src" python3 -m proxyfleet.cli "$@"
}

health_cache_has_useful_result() {
  local health_cache="$1"
  [[ -f "${health_cache}" ]] || return 1
  python3 - "${health_cache}" <<'PY'
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit(1)
nodes = payload.get("nodes", {})
if not isinstance(nodes, dict) or not nodes:
    raise SystemExit(1)
for item in nodes.values():
    if not isinstance(item, dict):
        continue
    if item.get("health_status") == "ok" and isinstance(item.get("last_delay_ms"), int):
        raise SystemExit(0)
    if item.get("measured_at"):
        raise SystemExit(0)
raise SystemExit(1)
PY
}

refresh_health() {
  local release_dir="${PROJECT_ROOT}/releases/000001"
  local health_cache="${PROJECT_ROOT}/runtime/health.json"
  local mihomo_api="http://127.0.0.1:9090"
  local timeout_ms="2000"
  local concurrency="16"
  local url="https://www.gstatic.com/generate_204"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --release-dir) release_dir="$2"; shift 2 ;;
      --health-cache) health_cache="$2"; shift 2 ;;
      --mihomo-api) mihomo_api="$2"; shift 2 ;;
      --timeout-ms) timeout_ms="$2"; shift 2 ;;
      --concurrency) concurrency="$2"; shift 2 ;;
      --url) url="$2"; shift 2 ;;
      *) die "未知 refresh-health 参数：$1" ;;
    esac
  done

  if [[ ! -d "${release_dir}" ]]; then
    local latest
    latest="$(latest_release_dir || true)"
    [[ -n "${latest}" ]] || die "找不到 release 目录，请先构建 release"
    release_dir="${latest}"
  fi

  echo "刷新节点测速缓存：${health_cache}"
  proxyfleet_python health-check "${release_dir}" "${health_cache}" \
    --mihomo-api "${mihomo_api}" \
    --all \
    --url "${url}" \
    --timeout-ms "${timeout_ms}" \
    --concurrency "${concurrency}" \
    --progress >/dev/null
}

live_health_menu() {
  local catalog_file="$1"
  local mihomo_api="$2"
  local timeout_ms="$3"
  local concurrency="$4"
  local desired_path="$5"
  local release_label="$6"
  local target_label="$7"
  local port_policy_status="$8"
  local selection_file
  selection_file="$(mktemp)"
  if proxyfleet_python live-select "${catalog_file}" \
    --mihomo-api "${mihomo_api}" \
    --timeout-ms "${timeout_ms}" \
    --concurrency "${concurrency}" \
    --desired-path "${desired_path}" \
    --release-label "${release_label}" \
    --target-label "${target_label}" \
    --port-policy-status "${port_policy_status}" \
    --selection-output "${selection_file}" \
    </dev/tty >/dev/tty; then
    cat "${selection_file}"
    rm -f "${selection_file}"
  else
    local rc=$?
    rm -f "${selection_file}"
    return "${rc}"
  fi
}
select_sync() {
  need_root

  local release_dir="${PROJECT_ROOT}/releases/000001"
  local runtime_dir="${PROJECT_ROOT}/runtime"
  local salt_root="${SALT_STATES_ROOT}"
  local target="*"
  local target_group="production"
  local health_cache="${PROJECT_ROOT}/runtime/health.json"
  local port_policy=""
  local port_policy_explicit="false"
  local port_policy_mode="merge"
  local refresh_health_first="false"
  local use_health_cache="true"
  local mihomo_api="http://127.0.0.1:9090"
  local health_timeout_ms="2000"
  local health_concurrency="16"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --release-dir) release_dir="$2"; shift 2 ;;
      --runtime-dir) runtime_dir="$2"; shift 2 ;;
      --salt-root) salt_root="$2"; shift 2 ;;
      --target) target="$2"; shift 2 ;;
      --target-group) target_group="$2"; shift 2 ;;
      --health-cache) health_cache="$2"; shift 2 ;;
      --refresh-health) refresh_health_first="true"; shift ;;
      --live-health) shift ;; # 兼容别名：select-sync 默认已进入 TUI。
      --no-health-cache) use_health_cache="false"; shift ;;
      --mihomo-api) mihomo_api="$2"; shift 2 ;;
      --health-timeout-ms) health_timeout_ms="$2"; shift 2 ;;
      --health-concurrency) health_concurrency="$2"; shift 2 ;;
      --port-policy) port_policy="$2"; port_policy_explicit="true"; shift 2 ;;
      --port-policy-mode) port_policy_mode="$2"; shift 2 ;;
      *) die "未知 select-sync 参数：$1" ;;
    esac
  done

  if [[ ! -d "${release_dir}" ]]; then
    local latest
    latest="$(latest_release_dir || true)"
    [[ -n "${latest}" ]] || die "找不到 release 目录，请先构建 release"
    release_dir="${latest}"
  fi

  [[ -f "${PROJECT_ROOT}/component-locks.json" ]] || die "缺少 ${PROJECT_ROOT}/component-locks.json"
  [[ -d "${release_dir}" ]] || die "release 目录不存在：${release_dir}"

  local default_port_policy="${PROJECT_ROOT}/config-src/port-policy.yaml"
  local port_policy_status="端口白名单：未配置"
  if [[ "${port_policy_explicit}" == "false" && -f "${default_port_policy}" ]]; then
    port_policy="${default_port_policy}"
  fi
  if [[ -n "${port_policy}" ]]; then
    [[ -f "${port_policy}" ]] || die "端口白名单文件不存在：${port_policy}"
    port_policy_status="端口白名单：$(basename "${port_policy}") mode=${port_policy_mode}"
  fi

  if [[ "${refresh_health_first}" == "true" ]]; then
    if ! refresh_health \
      --release-dir "${release_dir}" \
      --health-cache "${health_cache}" \
      --mihomo-api "${mihomo_api}" \
      --timeout-ms "${health_timeout_ms}" \
      --concurrency "${health_concurrency}"; then
      echo "警告：测速刷新失败，将继续显示未测速状态" >&2
      use_health_cache="false"
    fi
  fi

  local catalog_file
  catalog_file="$(mktemp)"
  if [[ "${use_health_cache}" == "true" ]] && health_cache_has_useful_result "${health_cache}"; then
    proxyfleet_python nodes "${release_dir}" --health-cache "${health_cache}" > "${catalog_file}"
  else
    proxyfleet_python nodes "${release_dir}" > "${catalog_file}"
  fi

  local selected_line selected_node_id selected_name
  if ! selected_line="$(live_health_menu \
    "${catalog_file}" \
    "${mihomo_api}" \
    "${health_timeout_ms}" \
    "${health_concurrency}" \
    "${runtime_dir}/desired.yaml" \
    "$(basename "${release_dir}")" \
    "${target}" \
    "${port_policy_status}")"; then
    die "未选择有效节点序号"
  fi
  [[ -n "${selected_line}" ]] || die "未选择有效节点序号"
  selected_node_id="$(printf '%s\n' "${selected_line}" | awk -F '\t' '{print $2}')"
  selected_name="$(printf '%s\n' "${selected_line}" | awk -F '\t' '{print $3}')"

  echo "已选择：${selected_name}"
  proxyfleet_python select-node "${release_dir}" "${runtime_dir}" \
    --node-id "${selected_node_id}" \
    --target-group "${target_group}" >/dev/null

  local publish_args=(
    publish-salt
    "${release_dir}"
    "${runtime_dir}/desired.yaml"
    "${salt_root}"
    --component-locks "${PROJECT_ROOT}/component-locks.json"
    --port-policy-mode "${port_policy_mode}"
  )
  if [[ -n "${port_policy}" ]]; then
    publish_args+=(--port-policy "${port_policy}")
  fi
  proxyfleet_python "${publish_args[@]}" >/dev/null

  sync_assets
  salt "${target}" saltutil.sync_modules

  local sync_args=(
    sync
    "${release_dir}"
    "${runtime_dir}/desired.yaml"
    "${salt_root}"
    --target "${target}"
    --salt-bin salt
    --port-policy-mode "${port_policy_mode}"
  )
  if [[ -n "${port_policy}" ]]; then
    sync_args+=(--port-policy-enabled)
  fi
  proxyfleet_python "${sync_args[@]}"
}

uninstall_master() {
  need_root
  systemctl disable --now salt-master || true
  apt-mark unhold salt-master salt-common || true
  DEBIAN_FRONTEND=noninteractive apt-get purge -y salt-master || true
  if [[ "${1:-}" == "--purge-data" ]]; then
    echo "危险操作：删除 /etc/salt/pki/master、/etc/salt/master.d 和 /srv/proxyfleet/salt"
    rm -rf /etc/salt/pki/master /etc/salt/master.d /srv/proxyfleet/salt
  else
    echo "已卸载 salt-master 包；默认保留 Salt PKI 和 /srv/proxyfleet/salt。"
  fi
}

preflight() {
  check_os
  echo "OS: $(. /etc/os-release && echo "${PRETTY_NAME}")"
  echo "Salt target version: ${SALT_VERSION}"
  echo "Project root: ${PROJECT_ROOT}"
  echo "systemd: $(systemctl --version | head -n 1)"
  echo "sudo: $(command -v sudo || true)"
}

usage() {
  cat <<'USAGE'
用法：scripts/proxyfleet-master.sh <command>

命令：
  preflight        只读预检当前机器是否符合 Master 测试机基线
  install          安装并配置 Salt Master 3008.1
  start            启动 salt-master
  stop             停止 salt-master
  restart          重启 salt-master
  status           查看 salt-master 和 salt-key 状态
  sync-assets      同步 ProxyFleet Salt module/state 到 file_roots
  refresh-health   刷新本机 Mihomo API 节点测速缓存
  select-sync      进入实时 TUI 选择节点，并同步到所有 Minion
  uninstall        卸载 salt-master，默认保留 PKI 和状态目录
  uninstall --purge-data
                   危险：卸载并删除 Master PKI/配置/POC states

select-sync 常用参数：
  --release-dir PATH       默认 releases/000001；不存在时自动使用 releases 下最大编号
  --runtime-dir PATH       默认 runtime
  --target '*'             默认同步全部 Minion
  --health-cache PATH      默认 runtime/health.json，存在时展示测速状态
  --live-health            兼容别名：行为与默认入口一致
  --mihomo-api URL         默认 http://127.0.0.1:9090
  --health-timeout-ms N    默认 2000
  --health-concurrency N   默认 16
  --port-policy PATH       可选：同步 Master managed 端口白名单；默认检测 config-src/port-policy.yaml
  --refresh-health         deprecated：进入 TUI 前先刷新测速缓存
  --no-health-cache        deprecated：不读取测速缓存，只显示 unknown
USAGE
}

command="${1:-}"
case "${command}" in
  preflight) preflight ;;
  install) install_master ;;
  start) start_master ;;
  stop) stop_master ;;
  restart) restart_master ;;
  status) status_master ;;
  sync-assets) sync_assets ;;
  refresh-health) shift; refresh_health "$@" ;;
  select-sync) shift; select_sync "$@" ;;
  uninstall) shift; uninstall_master "${1:-}" ;;
  *) usage; exit 2 ;;
esac
