#!/usr/bin/env bash
set -Eeuo pipefail

SALT_VERSION="${SALT_VERSION:-3008.1}"
PROJECT_ROOT="${PROJECT_ROOT:-/home/terence/project/ProxyFleet}"
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
  rm -rf "${SALT_STATES_ROOT}/proxyfleet"
  cp -R "${PROJECT_ROOT}/salt/states/proxyfleet" "${SALT_STATES_ROOT}/proxyfleet"
  find "${SALT_STATES_ROOT}/proxyfleet" -type d -exec chmod 0755 {} +
  find "${SALT_STATES_ROOT}/proxyfleet" -type f -exec chmod 0644 {} +
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
  uninstall        卸载 salt-master，默认保留 PKI 和状态目录
  uninstall --purge-data
                   危险：卸载并删除 Master PKI/配置/POC states
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
  uninstall) shift; uninstall_master "${1:-}" ;;
  *) usage; exit 2 ;;
esac
