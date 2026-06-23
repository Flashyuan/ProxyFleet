#!/usr/bin/env bash
set -Eeuo pipefail

SALT_VERSION="${SALT_VERSION:-3008.1}"
SALT_KEYRING="/etc/apt/keyrings/salt-archive-keyring.pgp"
SALT_SOURCES="/etc/apt/sources.list.d/salt.sources"
SALT_PIN="/etc/apt/preferences.d/proxyfleet-salt-pin"
MINION_CONF="/etc/salt/minion.d/proxyfleet.conf"

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
  curl -fsSL "https://github.com/saltstack/salt-install-guide/releases/latest/download/salt.sources" \
    -o "${SALT_SOURCES}"
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
  install --master <master-host-or-ip> --id <minion-id>
          [--environment production] [--driver native-mihomo]
          [--release-channel stable]
  start
  stop
  restart
  status
  uninstall
  uninstall --purge-data

说明：
  install 不会自动接受 key。安装后必须在 Master 上人工核验 fingerprint：
    sudo salt-key -F
    sudo salt-key -a <minion-id>
USAGE
}

parse_install_args() {
  MASTER=""
  MINION_ID=""
  ENVIRONMENT="production"
  DRIVER="native-mihomo"
  RELEASE_CHANNEL="stable"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --master) MASTER="${2:-}"; shift 2 ;;
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

  systemctl enable --now salt-minion
  echo "Minion 安装完成。请回到 Master 人工核验并接受 key：${MINION_ID}"
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
  systemctl disable --now salt-minion || true
  apt-mark unhold salt-minion salt-common || true
  DEBIAN_FRONTEND=noninteractive apt-get purge -y salt-minion || true
  if [[ "${1:-}" == "--purge-data" ]]; then
    echo "危险操作：删除 /etc/salt/pki/minion 和 /etc/salt/minion.d"
    rm -rf /etc/salt/pki/minion /etc/salt/minion.d
  else
    echo "已卸载 salt-minion 包；默认保留 Minion PKI 和配置。"
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
  preflight) preflight ;;
  install) shift; install_minion "$@" ;;
  start) start_minion ;;
  stop) stop_minion ;;
  restart) restart_minion ;;
  status) status_minion ;;
  uninstall) shift; uninstall_minion "${1:-}" ;;
  *) usage; exit 2 ;;
esac
