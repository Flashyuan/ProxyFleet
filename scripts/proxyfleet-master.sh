#!/usr/bin/env bash
set -Eeuo pipefail

SALT_VERSION="${SALT_VERSION:-3008.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
SALT_KEYRING="${SALT_KEYRING:-/etc/apt/keyrings/salt-archive-keyring.pgp}"
SALT_SOURCES="${SALT_SOURCES:-/etc/apt/sources.list.d/salt.sources}"
SALT_PIN="${SALT_PIN:-/etc/apt/preferences.d/proxyfleet-salt-pin}"
MASTER_CONF="${MASTER_CONF:-/etc/salt/master.d/proxyfleet.conf}"
MASTER_CONF_DIR="${MASTER_CONF_DIR:-/etc/salt/master.d}"
MASTER_PKI_DIR="${MASTER_PKI_DIR:-/etc/salt/pki/master}"
SALT_STATES_ROOT="${SALT_STATES_ROOT:-/srv/proxyfleet/salt/states}"
SALT_PILLAR_ROOT="${SALT_PILLAR_ROOT:-/srv/proxyfleet/salt/pillar}"
PROXYFLEET_VERSION="${PROXYFLEET_VERSION:-v.0.2.0}"
UPDATE_MANIFEST_URL="${UPDATE_MANIFEST_URL:-https://github.com/Flashyuan/ProxyFleet/releases/latest/download/update-manifest.json}"
UPDATE_STATE_PATH="${UPDATE_STATE_PATH:-${PROJECT_ROOT}/runtime/update-state.json}"
MONITOR_POLICY_PATH="${MONITOR_POLICY_PATH:-${PROJECT_ROOT}/runtime/health-monitor-policy.json}"
MONITOR_STATE_PATH="${MONITOR_STATE_PATH:-${PROJECT_ROOT}/runtime/health-monitor-state.json}"
MONITOR_EMAIL_CONFIG="${MONITOR_EMAIL_CONFIG:-/etc/proxyfleet/notify/email.json}"
SMTP_PASSWORD_FILE="${SMTP_PASSWORD_FILE:-/etc/proxyfleet/secrets/smtp-password}"
ASSET_MIRROR_PORT="${ASSET_MIRROR_PORT:-48080}"
ASSET_MIRROR_ROOT="${ASSET_MIRROR_ROOT:-${PROJECT_ROOT}/runtime/asset-mirror}"
ASSET_MIRROR_SERVICE="${ASSET_MIRROR_SERVICE:-proxyfleet-asset-mirror.service}"

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

file_sha256() {
  sha256sum "$1" | awk '{print $1}'
}

salt_remote_module_hash_matches() {
  local expected_hash="$1"
  local target="$2"
  local batch="$3"
  local output
  output="$(mktemp)"
  local expected_targets_json=""
  if [[ "${target}" == "*" ]]; then
    local keys_output
    keys_output="$(mktemp)"
    if ! salt-key --out=json -l acc >"${keys_output}" 2>/dev/null; then
      rm -f "${output}" "${keys_output}"
      return 1
    fi
    expected_targets_json="$(python3 - "${keys_output}" <<'PY'
import json
import sys

try:
    data = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    sys.exit(1)
keys = []
if isinstance(data, dict):
    for field in ("minions", "accepted", "Accepted Keys"):
        value = data.get(field)
        if isinstance(value, list):
            keys = [str(item) for item in value]
            break
if not keys:
    sys.exit(1)
print(json.dumps(sorted(set(keys)), ensure_ascii=True))
PY
)"
    local key_rc=$?
    rm -f "${keys_output}"
    if [[ "${key_rc}" -ne 0 || -z "${expected_targets_json}" ]]; then
      rm -f "${output}"
      return 1
    fi
  elif [[ "${target}" != *"*"* && "${target}" != *"?"* && "${target}" != *"["* && "${target}" != *","* ]]; then
    expected_targets_json="$(python3 - "${target}" <<'PY'
import json
import sys
print(json.dumps([sys.argv[1]], ensure_ascii=True))
PY
)"
  else
    rm -f "${output}"
    return 1
  fi
  local cmd=(salt)
  if [[ -n "${batch}" ]]; then
    cmd+=(--batch "${batch}")
  fi
  cmd+=("${target}" proxyfleet_mihomo.module_sha256 --out=json --static)
  if ! "${cmd[@]}" >"${output}" 2>/dev/null; then
    rm -f "${output}"
    return 1
  fi
  python3 - "${output}" "${expected_hash}" "${expected_targets_json}" <<'PY'
import json
import sys

path, expected, expected_targets_raw = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    data = json.loads(open(path, encoding="utf-8").read())
    expected_targets = set(json.loads(expected_targets_raw))
except Exception:
    sys.exit(1)
if not isinstance(data, dict) or not data or not expected_targets:
    sys.exit(1)
if set(map(str, data.keys())) != expected_targets:
    sys.exit(1)
for value in data.values():
    if not isinstance(value, dict) or value.get("sha256") != expected:
        sys.exit(1)
sys.exit(0)
PY
  local rc=$?
  rm -f "${output}"
  return "${rc}"
}

salt_assets_missing() {
  [[ -f "${SALT_STATES_ROOT}/_modules/proxyfleet_mihomo.py" ]] || return 0
  [[ -f "${SALT_STATES_ROOT}/proxyfleet/sync.sls" ]] || return 0
  [[ -d "${SALT_STATES_ROOT}/proxyfleet" ]] || return 0
  return 1
}

asset_mirror_prepare() {
  need_root
  check_os
  [[ -f "${PROJECT_ROOT}/component-locks.json" ]] || die "缺少 ${PROJECT_ROOT}/component-locks.json"
  local public_root="${ASSET_MIRROR_ROOT}/public/proxyfleet"
  local salt_dir="${public_root}/salt"
  local mihomo_dir="${public_root}/mihomo"
  install -d -m 0755 "${salt_dir}" "${mihomo_dir}"

  echo "[1/4] 准备 Salt ${SALT_VERSION} apt 源..."
  install_salt_repo
  apt-get update
  echo "[2/4] 下载 Salt ${SALT_VERSION} Minion 安装包和依赖到 ${salt_dir}..."
  rm -rf "${salt_dir:?}/"*
  install -d -m 0755 "${salt_dir}/partial"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --download-only --reinstall \
    -o "Dir::Cache::archives=${salt_dir}" \
    "salt-common=${SALT_VERSION}*" \
    "salt-minion=${SALT_VERSION}*" \
    debconf-utils || true
  (
    cd "${salt_dir}"
    apt-get download \
      "salt-common=${SALT_VERSION}*" \
      "salt-minion=${SALT_VERSION}*" \
      debconf-utils
  )
  rm -rf "${salt_dir}/partial" "${salt_dir}/lock"
  find "${salt_dir}" -maxdepth 1 -type f -name '*.deb' -print | sort
  find "${salt_dir}" -maxdepth 1 -type f -name 'salt-common_*.deb' | grep -q . || die "Salt 镜像缺少 salt-common deb"
  find "${salt_dir}" -maxdepth 1 -type f -name 'salt-minion_*.deb' | grep -q . || die "Salt 镜像缺少 salt-minion deb"

  echo "[3/4] 下载 Mihomo 固定版本资产到 ${mihomo_dir}..."
  python3 - "${PROJECT_ROOT}/component-locks.json" "${mihomo_dir}" <<'PY'
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

locks = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
target = Path(sys.argv[2])
target.mkdir(parents=True, exist_ok=True)

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def filename(url, digest):
    parsed = urlparse(url)
    name = Path(parsed.path).name if parsed.path else ""
    return name or f"{digest}.gz"

def candidate_urls(artifact):
    urls = []
    for key in ("mirror_urls", "mirrors"):
        values = artifact.get(key, [])
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    urls.append(value)
                elif isinstance(value, dict) and isinstance(value.get("url"), str):
                    urls.append(value["url"])
    url = artifact.get("url")
    if isinstance(url, str):
        urls.append(url)
    deduped = []
    seen = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped

def download_url(url, destination):
    parsed = urlparse(url)
    if parsed.scheme == "file":
        shutil.copyfile(Path(parsed.path), destination)
        return
    if parsed.scheme != "https":
        raise RuntimeError(f"unsupported mihomo url: {url}")
    tmp = destination.with_suffix(destination.suffix + ".download")
    tmp.unlink(missing_ok=True)
    curl = shutil.which("curl")
    if curl:
        subprocess.run(
            [
                curl,
                "-fL",
                "--connect-timeout",
                "15",
                "--max-time",
                "240",
                "--retry",
                "2",
                "--retry-delay",
                "2",
                "--progress-bar",
                "-o",
                str(tmp),
                url,
            ],
            check=True,
        )
        tmp.replace(destination)
        return
    with urlopen(url, timeout=60) as response, tmp.open("wb") as fh:
        shutil.copyfileobj(response, fh)
    tmp.replace(destination)

for component in locks.get("components", []):
    if component.get("name") != "mihomo":
        continue
    for arch, artifact in component.get("artifacts", {}).items():
        if not isinstance(artifact, dict):
            continue
        digest = artifact.get("sha256")
        urls = candidate_urls(artifact)
        if not isinstance(digest, str) or len(digest) != 64 or not urls:
            raise SystemExit(f"mihomo artifact invalid: {arch}")
        destination = target / filename(urls[-1], digest)
        if not destination.exists() or sha256(destination) != digest:
            errors = []
            for index, url in enumerate(urls, start=1):
                print(f"download mihomo {arch} [{index}/{len(urls)}]: {url}", file=sys.stderr, flush=True)
                try:
                    download_url(url, destination)
                    if sha256(destination) == digest:
                        break
                    errors.append(f"{url}: sha256 mismatch")
                    destination.unlink(missing_ok=True)
                except Exception as exc:
                    errors.append(f"{url}: {type(exc).__name__}")
                    destination.unlink(missing_ok=True)
            else:
                raise SystemExit(f"mihomo download failed: {arch}: {'; '.join(errors[-3:])}")
        else:
            print(f"reuse mihomo {arch}: {destination.name}", file=sys.stderr, flush=True)
        if sha256(destination) != digest:
            raise SystemExit(f"mihomo sha256 mismatch: {destination.name}")
        digest_path = target / digest
        if not digest_path.exists():
            shutil.copyfile(destination, digest_path)
PY

  echo "[4/4] 生成 bootstrap-manifest.json..."
  cp -f "${PROJECT_ROOT}/component-locks.json" "${public_root}/component-locks.json"
  python3 - "${public_root}" "${SALT_VERSION}" <<'PY'
import hashlib
import json
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
salt_version = sys.argv[2]

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

files = []
for path in sorted(root.rglob("*")):
    if path.is_file() and path.name != "bootstrap-manifest.json":
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256(path),
                "size": path.stat().st_size,
            }
        )

payload = {
    "schema_version": "1.0",
    "product": "proxyfleet",
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "salt_version": salt_version,
    "files": files,
}
(root / "bootstrap-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  echo "组件镜像已准备：${public_root}"
}

asset_mirror_serve() {
  need_root
  local public_dir="${ASSET_MIRROR_ROOT}/public"
  [[ -d "${public_dir}/proxyfleet" ]] || die "镜像目录不存在，请先执行 asset-mirror-prepare"
  cat > "/etc/systemd/system/${ASSET_MIRROR_SERVICE}" <<SERVICE
[Unit]
Description=ProxyFleet fixed asset mirror
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${public_dir}
ExecStart=/usr/bin/python3 -m http.server ${ASSET_MIRROR_PORT} --bind 0.0.0.0 --directory ${public_dir}
Restart=on-failure
RestartSec=3s

[Install]
WantedBy=multi-user.target
SERVICE
  systemctl daemon-reload
  systemctl enable --now "${ASSET_MIRROR_SERVICE}"
  echo "组件镜像服务已启动：http://<Master-IP>:${ASSET_MIRROR_PORT}/proxyfleet/"
}

asset_mirror_status() {
  echo "镜像目录：${ASSET_MIRROR_ROOT}/public/proxyfleet"
  if [[ -f "${ASSET_MIRROR_ROOT}/public/proxyfleet/bootstrap-manifest.json" ]]; then
    python3 -m json.tool "${ASSET_MIRROR_ROOT}/public/proxyfleet/bootstrap-manifest.json"
  else
    echo "bootstrap-manifest.json 不存在"
  fi
  systemctl status "${ASSET_MIRROR_SERVICE}" --no-pager || true
}

asset_mirror_deploy() {
  preview_write "medium" \
    "下载 Salt ${SALT_VERSION} deb 包" \
    "下载 Mihomo component-locks 固定版本资产" \
    "生成 bootstrap-manifest.json" \
    "启动只读 HTTP 镜像服务 0.0.0.0:${ASSET_MIRROR_PORT}" \
    "请在防火墙/安全组只允许局域网或受管 Minion 访问 ${ASSET_MIRROR_PORT}"
  confirm_phrase "DEPLOY MIRROR" "确认部署组件镜像服务？" || return 0
  asset_mirror_prepare
  asset_mirror_serve
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
E_TUI_UNAVAILABLE: 当前不是交互式终端，无法进入 Master TUI。

等价非交互命令示例：
  sudo scripts/proxyfleet-master.sh preflight
  sudo scripts/proxyfleet-master.sh install
  sudo scripts/proxyfleet-master.sh status
  sudo scripts/proxyfleet-master.sh select-sync
  sudo scripts/proxyfleet-master.sh uninstall
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
  PYTHONPATH="${PROJECT_ROOT}/src" python3 -m proxyfleet.cli "$@"
}

check_update_master() {
  proxyfleet_python check-update \
    --role master \
    --install-root "${PROJECT_ROOT}" \
    --state-path "${UPDATE_STATE_PATH}" \
    --manifest-url "${UPDATE_MANIFEST_URL}" \
    --current-version "${PROXYFLEET_VERSION}" \
    --current-commit "$(current_commit)"
}

apply_update_master() {
  need_root
  proxyfleet_python update \
    --role master \
    --install-root "${PROJECT_ROOT}" \
    --state-path "${UPDATE_STATE_PATH}" \
    --manifest-url "${UPDATE_MANIFEST_URL}" \
    --current-version "${PROXYFLEET_VERSION}" \
    --current-commit "$(current_commit)" \
    --yes
}

suppress_update_master() {
  local version="$1"
  proxyfleet_python suppress-update \
    --role master \
    --install-root "${PROJECT_ROOT}" \
    --state-path "${UPDATE_STATE_PATH}" \
    --manifest-url "${UPDATE_MANIFEST_URL}" \
    --current-version "${PROXYFLEET_VERSION}" \
    --current-commit "$(current_commit)" \
    --version "${version}"
}

monitor_init() {
  need_root
  proxyfleet_python monitor init --policy-path "${MONITOR_POLICY_PATH}"
}

monitor_status_cmd() {
  proxyfleet_python monitor status \
    --policy-path "${MONITOR_POLICY_PATH}" \
    --state-path "${MONITOR_STATE_PATH}" \
    --email-config "${MONITOR_EMAIL_CONFIG}"
}

monitor_auto_switch_cmd() {
  need_root
  local enabled="$1"
  [[ -f "${MONITOR_POLICY_PATH}" ]] || monitor_init >/dev/null
  proxyfleet_python monitor auto-switch --policy-path "${MONITOR_POLICY_PATH}" --enabled "${enabled}"
}

monitor_once_cmd() {
  need_root
  local release_dir="${PROJECT_ROOT}/releases/000001"
  local runtime_dir="${PROJECT_ROOT}/runtime"
  local mihomo_api="http://127.0.0.1:9090"
  local dry_run="false"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --release-dir) release_dir="$2"; shift 2 ;;
      --runtime-dir) runtime_dir="$2"; shift 2 ;;
      --mihomo-api) mihomo_api="$2"; shift 2 ;;
      --dry-run) dry_run="true"; shift ;;
      *) die "未知 monitor once 参数：$1" ;;
    esac
  done
  if [[ ! -d "${release_dir}" ]]; then
    local latest
    latest="$(latest_release_dir || true)"
    [[ -n "${latest}" ]] || die "找不到 release 目录，请先构建 release"
    release_dir="${latest}"
  fi
  [[ -f "${runtime_dir}/desired.yaml" ]] || die "缺少 ${runtime_dir}/desired.yaml，请先选择节点"
  [[ -f "${MONITOR_POLICY_PATH}" ]] || monitor_init >/dev/null
  local args=(
    monitor once
    --release-dir "${release_dir}"
    --runtime-dir "${runtime_dir}"
    --policy-path "${MONITOR_POLICY_PATH}"
    --state-path "${MONITOR_STATE_PATH}"
    --email-config "${MONITOR_EMAIL_CONFIG}"
    --mihomo-api "${mihomo_api}"
    --salt-root "${SALT_STATES_ROOT}"
    --component-locks "${PROJECT_ROOT}/component-locks.json"
    --target "*"
  )
  if [[ "${dry_run}" == "true" ]]; then
    args+=(--dry-run --no-email)
  fi
  proxyfleet_python "${args[@]}"
}

monitor_validate_candidates_cmd() {
  need_root
  local release_dir="${PROJECT_ROOT}/releases/000001"
  local runtime_dir="${PROJECT_ROOT}/runtime"
  local mihomo_api="http://127.0.0.1:9090"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --release-dir) release_dir="$2"; shift 2 ;;
      --runtime-dir) runtime_dir="$2"; shift 2 ;;
      --mihomo-api) mihomo_api="$2"; shift 2 ;;
      *) die "未知 monitor validate-candidates 参数：$1" ;;
    esac
  done
  if [[ ! -d "${release_dir}" ]]; then
    local latest
    latest="$(latest_release_dir || true)"
    [[ -n "${latest}" ]] || die "找不到 release 目录，请先构建 release"
    release_dir="${latest}"
  fi
  [[ -f "${runtime_dir}/desired.yaml" ]] || die "缺少 ${runtime_dir}/desired.yaml，请先选择节点"
  [[ -f "${MONITOR_POLICY_PATH}" ]] || monitor_init >/dev/null
  proxyfleet_python monitor validate-candidates \
    --release-dir "${release_dir}" \
    --runtime-dir "${runtime_dir}" \
    --policy-path "${MONITOR_POLICY_PATH}" \
    --state-path "${MONITOR_STATE_PATH}" \
    --email-config "${MONITOR_EMAIL_CONFIG}" \
    --mihomo-api "${mihomo_api}"
}

monitor_email_tui() {
  need_root
  local smtp_host smtp_port smtp_tls username sender recipients password
  read -r -p "SMTP Host: " smtp_host
  read -r -p "SMTP Port [465]: " smtp_port
  smtp_port="${smtp_port:-465}"
  read -r -p "启用 TLS/SSL？[Y/n]: " smtp_tls
  case "${smtp_tls}" in
    n|N|no|NO) smtp_tls="false" ;;
    *) smtp_tls="true" ;;
  esac
  read -r -p "SMTP 用户名/发件邮箱: " username
  read -r -p "发件人显示，例如 ProxyFleet Alert <alert@example.com>: " sender
  read -r -p "收件人邮箱，多个用逗号分隔: " recipients
  read -r -s -p "SMTP 密码或授权码（不会回显）: " password
  echo
  preview_write "high" \
    "写入邮件配置 ${MONITOR_EMAIL_CONFIG}" \
    "写入 SMTP 授权码 ${SMTP_PASSWORD_FILE}，权限 0600" \
    "收件人支持多个邮箱；不会写入 Git"
  confirm_phrase "WRITE" "确认写入邮件告警配置？" || return 0
  printf '%s\n' "${password}" | proxyfleet_python monitor configure-email \
    --email-config "${MONITOR_EMAIL_CONFIG}" \
    --smtp-host "${smtp_host}" \
    --smtp-port "${smtp_port}" \
    --smtp-tls "${smtp_tls}" \
    --username "${username}" \
    --password-file "${SMTP_PASSWORD_FILE}" \
    --password-stdin \
    --from "${sender}" \
    --recipient "${recipients}"
}

monitor_tui() {
  local choice
  while true; do
    tui_clear
    cat <<'MENU'
ProxyFleet Master / 节点健康监控

1) 初始化/修复默认健康监控策略
2) 配置邮件告警发件人和收件人
3) 查看健康监控状态
4) 启用自动切换
5) 关闭自动切换
6) 执行一次健康检查（dry-run，不发邮件、不切换）
7) 预验证自动切换候选节点并缓存可用节点
8) 执行一次健康检查（按策略推进状态）
b) 返回
MENU
    read -r -p "请选择: " choice
    case "${choice}" in
      1) preview_write "medium" "写入默认策略 ${MONITOR_POLICY_PATH}" "默认 10 分钟检测，自动切换关闭"; confirm_phrase "WRITE" "确认写入默认健康监控策略？" && monitor_init; tui_pause ;;
      2) monitor_email_tui; tui_pause ;;
      3) monitor_status_cmd; tui_pause ;;
      4) preview_write "critical" "启用健康监控自动切换" "仍会先邮件告警并等待 10 分钟；黑名单和限频保护继续生效"; confirm_phrase "ENABLE" "确认启用自动切换？" && monitor_auto_switch_cmd true; tui_pause ;;
      5) preview_write "medium" "关闭健康监控自动切换" "保留检测和邮件告警"; confirm_phrase "DISABLE" "确认关闭自动切换？" && monitor_auto_switch_cmd false; tui_pause ;;
      6) monitor_once_cmd --dry-run; tui_pause ;;
      7) preview_write "medium" "预验证自动切换候选节点" "会临时切换 Master 本机 Mihomo 节点做真实出口验证，完成后恢复当前节点，并缓存可用候选"; confirm_phrase "RUN" "确认执行候选节点预验证？" && monitor_validate_candidates_cmd; tui_pause ;;
      8) preview_write "high" "执行健康检查并按状态机推进" "可能发送邮件；仅当策略显式启用自动切换且等待窗口到期时才会切换"; confirm_phrase "RUN" "确认执行？" && monitor_once_cmd; tui_pause ;;
      b|B|q|Q) return 0 ;;
      *) echo "未知选项"; tui_pause ;;
    esac
  done
}

manual_switch_notify() {
  local node_id="$1"
  local mihomo_name="$2"
  local target="$3"
  [[ -f "${MONITOR_EMAIL_CONFIG}" ]] || return 0
  if ! proxyfleet_python monitor notify-manual-switch \
    --policy-path "${MONITOR_POLICY_PATH}" \
    --email-config "${MONITOR_EMAIL_CONFIG}" \
    --node-id "${node_id}" \
    --mihomo-name "${mihomo_name}" \
    --target "${target}" \
    --actor "${SUDO_USER:-${USER:-unknown}}" >/dev/null; then
    echo "警告：节点已同步，但手动切换邮件通知发送失败" >&2
  fi
}

load_local_env() {
  local env_file="${PROJECT_ROOT}/.env.proxyfleet"
  if [[ -f "${env_file}" ]]; then
    while IFS='=' read -r key value; do
      [[ -n "${key}" ]] || continue
      export "${key}=${value}"
    done < <(python3 - "${env_file}" <<'PY'
import re
import shlex
import sys
from pathlib import Path

for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    try:
        parts = shlex.split(line)
    except ValueError:
        continue
    if len(parts) != 2 or parts[0] != "export" or "=" not in parts[1]:
        continue
    key, value = parts[1].split("=", 1)
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        print(f"{key}={value}")
PY
)
  fi
}

write_subscription_provider() {
  local provider_id="$1"
  local env_name="$2"
  local name_prefix="$3"
  python3 - "${PROJECT_ROOT}/config-src/providers.json" "${provider_id}" "${env_name}" "${name_prefix}" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
provider_id, env_name, name_prefix = sys.argv[2:5]
if not re.fullmatch(r"[A-Za-z0-9_.-]+", provider_id):
    raise SystemExit("Provider ID 只能包含字母、数字、下划线、点和短横线")
if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env_name):
    raise SystemExit("环境变量名必须是大写字母、数字和下划线，且以字母开头")
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
else:
    data = {"schema_version": "1.0", "providers": []}
providers = data.setdefault("providers", [])
providers[:] = [item for item in providers if item.get("id") != provider_id]
providers.append(
    {
        "enabled": True,
        "id": provider_id,
        "kind": "subscription",
        "name_prefix": name_prefix,
        "output": f"providers/{provider_id}.yaml",
        "secret_ref": env_name,
    }
)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

next_release_revision() {
  local latest
  latest="$(latest_release_dir || true)"
  if [[ -n "${latest}" ]]; then
    printf '%d\n' "$((10#$(basename "${latest}") + 1))"
  else
    printf '1\n'
  fi
}

quick_subscription_tui() {
  local display_name subscription_url revision source_commit env_file
  read -r -p "请给这个订阅取一个名（例如 airport-main）: " display_name
  [[ -n "${display_name}" ]] || die "订阅名称不能为空"
  read -r -p "请输入订阅 URL: " subscription_url
  [[ -n "${subscription_url}" && "${subscription_url}" == *"://"* ]] || die "订阅 URL 无效"

  env_file="${PROJECT_ROOT}/.env.proxyfleet"
  revision="$(next_release_revision)"
  source_commit="$(git -C "${PROJECT_ROOT}" rev-parse --short HEAD 2>/dev/null || echo local)"
  preview_write "medium" \
    "生成/更新 ${PROJECT_ROOT}/config-src/base.json" \
    "生成/更新 ${PROJECT_ROOT}/config-src/providers.json" \
    "生成/更新 ${PROJECT_ROOT}/config-src/groups.json" \
    "生成/更新 ${PROJECT_ROOT}/config-src/rules.json" \
    "保存订阅 URL 到本地 ${env_file}（不会提交到 Git）" \
    "自动构建 release $(printf '%06d' "${revision}")"
  confirm_phrase "WRITE" "确认添加订阅并生成可用配置？" || return 0

  python3 - \
    "${PROJECT_ROOT}/config-src" \
    "${env_file}" \
    "${display_name}" \
    "${subscription_url}" <<'PY'
import json
import re
import shlex
import sys
from pathlib import Path

config_dir = Path(sys.argv[1])
env_file = Path(sys.argv[2])
display_name = sys.argv[3].strip()
subscription_url = sys.argv[4].strip()

slug = re.sub(r"[^a-zA-Z0-9]+", "-", display_name.lower()).strip("-") or "subscription"
provider_id = slug
env_name = "PROXYFLEET_SUB_" + re.sub(r"[^A-Z0-9]+", "_", slug.upper()).strip("_")
if not env_name or env_name == "PROXYFLEET_SUB_":
    env_name = "PROXYFLEET_SUB_SUBSCRIPTION"
name_prefix = f"[{display_name}] "

config_dir.mkdir(parents=True, exist_ok=True)
(config_dir / "base.json").write_text(
    json.dumps(
        {
            "schema_version": "1.0",
            "config": {
                "mixed-port": 7890,
                "allow-lan": False,
                "mode": "rule",
                "log-level": "info",
                "external-controller": "127.0.0.1:9090",
            },
            "proxy_mode": "tproxy",
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)

providers_path = config_dir / "providers.json"
if providers_path.exists():
    providers = json.loads(providers_path.read_text(encoding="utf-8"))
else:
    providers = {"schema_version": "1.0", "providers": []}
items = providers.setdefault("providers", [])
items[:] = [item for item in items if item.get("id") != provider_id]
items.append(
    {
        "enabled": True,
        "id": provider_id,
        "kind": "subscription",
        "name_prefix": name_prefix,
        "output": f"providers/{provider_id}.yaml",
        "secret_ref": env_name,
    }
)
providers_path.write_text(json.dumps(providers, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

groups_path = config_dir / "groups.json"
if groups_path.exists():
    groups = json.loads(groups_path.read_text(encoding="utf-8"))
else:
    groups = {"schema_version": "1.0", "groups": []}
fleet = None
for group in groups.setdefault("groups", []):
    if group.get("name") == "FLEET_PROXY":
        fleet = group
        break
if fleet is None:
    fleet = {"name": "FLEET_PROXY", "type": "select", "use": []}
    groups["groups"].append(fleet)
fleet.setdefault("use", [])
if provider_id not in fleet["use"]:
    fleet["use"].append(provider_id)
groups_path.write_text(json.dumps(groups, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

rules_path = config_dir / "rules.json"
if not rules_path.exists():
    rules_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "order": [{"match": "MATCH", "target": "FLEET_PROXY"}],
                "rule_providers": [],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

env_file.parent.mkdir(parents=True, exist_ok=True)
lines = []
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line.startswith(f"export {env_name}="):
            lines.append(line)
lines.append(f"export {env_name}={shlex.quote(subscription_url)}")
env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
env_file.chmod(0o600)
print(json.dumps({"provider_id": provider_id, "env_name": env_name}, ensure_ascii=False))
PY

  load_local_env
  proxyfleet_python build-release "${PROJECT_ROOT}/config-src" "${PROJECT_ROOT}/releases" \
    --revision "${revision}" \
    --source-git-commit "${source_commit}" \
    --component-locks "${PROJECT_ROOT}/component-locks.json" \
    --subscription-cache "${PROJECT_ROOT}/runtime/subscriptions"
  proxyfleet_python verify-release "${PROJECT_ROOT}/releases/$(printf '%06d' "${revision}")"
  echo "订阅已添加并构建 release。下一步可进入：节点配置相关 -> 选择节点并同步到 Minion"
}

master_config_subscription_tui() {
  local provider_id env_name name_prefix
  read -r -p "Provider ID [airport-main]: " provider_id
  provider_id="${provider_id:-airport-main}"
  read -r -p "订阅 URL 环境变量名 [AIRPORT_MAIN_URL]: " env_name
  env_name="${env_name:-AIRPORT_MAIN_URL}"
  read -r -p "节点名前缀（可空，例如 [机场] ）: " name_prefix
  preview_write "medium" \
    "写入 ${PROJECT_ROOT}/config-src/providers.json" \
    "只保存环境变量名 ${env_name}，不保存订阅 URL 明文" \
    "构建 release 前需执行：export ${env_name}='<你的订阅URL>'"
  confirm_phrase "WRITE" "确认写入订阅 Provider 配置？" || return 0
  write_subscription_provider "${provider_id}" "${env_name}" "${name_prefix}"
  echo "订阅 Provider 已写入。"
  echo "构建前请在当前 shell 设置：export ${env_name}='<你的订阅URL>'"
}

import_file_tui() {
  local source_path target_path label
  label="$1"
  target_path="$2"
  read -r -p "请输入${label}源文件路径: " source_path
  [[ -n "${source_path}" && -f "${source_path}" ]] || die "源文件不存在：${source_path}"
  preview_write "medium" "复制 ${source_path}" "覆盖 ${target_path}"
  confirm_phrase "WRITE" "确认导入${label}？" || return 0
  install -D -m 0644 "${source_path}" "${target_path}"
  echo "${label}已导入：${target_path}"
}

build_release_tui() {
  local revision source_commit
  local default_revision
  default_revision="$(next_release_revision)"
  read -r -p "Release revision [${default_revision}]: " revision
  revision="${revision:-${default_revision}}"
  source_commit="$(git -C "${PROJECT_ROOT}" rev-parse --short HEAD 2>/dev/null || echo local)"
  read -r -p "source git commit [${source_commit}]: " source_commit
  source_commit="${source_commit:-local}"
  preview_write "medium" \
    "读取 ${PROJECT_ROOT}/config-src" \
    "写入 ${PROJECT_ROOT}/releases/$(printf '%06d' "${revision}")" \
    "使用 ${PROJECT_ROOT}/component-locks.json 校验固定组件版本"
  confirm_phrase "BUILD" "确认构建 release？" || return 0
  load_local_env
  proxyfleet_python build-release "${PROJECT_ROOT}/config-src" "${PROJECT_ROOT}/releases" \
    --revision "${revision}" \
    --source-git-commit "${source_commit}" \
    --component-locks "${PROJECT_ROOT}/component-locks.json" \
    --subscription-cache "${PROJECT_ROOT}/runtime/subscriptions"
  proxyfleet_python verify-release "${PROJECT_ROOT}/releases/$(printf '%06d' "${revision}")"
}

port_policy_tui() {
  install -d -m 0755 "${PROJECT_ROOT}/config-src"
  local path="${PROJECT_ROOT}/config-src/port-policy.yaml"
  local ports source
  read -r -p "请输入要加入白名单的端口号（多个用空格或逗号分隔）: " ports
  [[ -n "${ports}" ]] || die "端口号不能为空"
  read -r -p "允许来源 CIDR/IP [any]: " source
  source="${source:-any}"
  preview_write "medium" \
    "写入 Master managed 端口白名单：${path}" \
    "允许 TCP 端口：${ports}" \
    "允许来源：${source}" \
    "该文件存在时 select-sync 默认按 merge 模式同步给 Minion" \
    "Master 不会覆盖 Minion 的 /etc/proxyfleet/local"
  cat <<'NOTE'
提示：Salt Master 自身需要对 Minion 开放 TCP 4505/4506。
如果这里配置的是“下发到 Minion 的端口白名单”，通常不需要把 4505/4506 加进去；
如果你是在配置 Master 机器自己的入站防火墙，则必须允许 Minion 访问 4505/4506。
NOTE
  confirm_phrase "WRITE" "确认写入端口白名单？" || return 0
  python3 - "${path}" "${ports}" "${source}" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
raw_ports = sys.argv[2]
source = sys.argv[3]
tokens = [item for item in re.split(r"[\s,]+", raw_ports.strip()) if item]
if not tokens:
    raise SystemExit("端口号不能为空")
ports = []
for token in tokens:
    if not token.isdigit():
        raise SystemExit(f"端口号无效: {token}")
    port = int(token)
    if port < 1 or port > 65535:
        raise SystemExit(f"端口号超出范围: {token}")
    ports.append(port)
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
else:
    data = {"schema_version": "1.0", "owner": "master", "allow": [], "deny": []}
if data.get("schema_version", "1.0") != "1.0" or data.get("owner") != "master":
    raise SystemExit("已有端口白名单 schema 或 owner 不匹配")
allow = data.setdefault("allow", [])
data.setdefault("deny", [])
seen = {(str(rule.get("protocol")), int(rule.get("port")), str(rule.get("source"))) for rule in allow if isinstance(rule, dict) and str(rule.get("port", "")).isdigit()}
for port in ports:
    key = ("tcp", port, source)
    if key not in seen:
        allow.append({"protocol": "tcp", "port": port, "source": source})
        seen.add(key)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"已写入 {len(ports)} 个端口到 {path}")
PY
}

accept_key_tui() {
  salt-key -F || true
  salt-key -L || true
  local minion_id
  read -r -p "请输入要接受的 Minion ID（留空返回）: " minion_id
  [[ -n "${minion_id}" ]] || return 0
  preview_write "high" "接受 Minion key：${minion_id}" "变更 Salt Master PKI 信任状态"
  confirm_phrase "ACCEPT" "确认接受该 Minion key？" || return 0
  salt-key -a "${minion_id}"
}

master_services_tui() {
  local choice
  echo "1) start salt-master"
  echo "2) stop salt-master"
  echo "3) restart salt-master"
  read -r -p "请选择服务操作: " choice
  case "${choice}" in
    1) start_master ;;
    2) preview_write "high" "停止 salt-master" "Minion 将暂时无法接收同步"; confirm_phrase "STOP" "确认停止？" && stop_master ;;
    3) restart_master ;;
    *) echo "已取消" ;;
  esac
}

master_install_menu() {
  local choice
  while true; do
    tui_clear
    cat <<'MENU'
ProxyFleet Master / 安装相关

1) 只读预检
2) 安装/修复 Salt Master
3) 一键部署 Salt/Mihomo 固定组件镜像
4) 查看组件镜像状态
5) 检测并更新 ProxyFleet Master
6) 卸载 Master
b) 返回
MENU
    read -r -p "请选择: " choice
    case "${choice}" in
      1) preflight; tui_pause ;;
      2) preview_write "medium" "安装 Salt Master ${SALT_VERSION}" "写入 ${MASTER_CONF}" "同步 Salt states"; confirm_phrase "INSTALL" "确认安装/修复 Master？" && install_master; tui_pause ;;
      3) asset_mirror_deploy; tui_pause ;;
      4) asset_mirror_status; tui_pause ;;
      5) update_master_tui; tui_pause ;;
      6) preview_write "critical" "停止 salt-master" "卸载 salt-master" "删除 Master PKI、配置、Salt states/pillar 和本项目运行数据"; confirm_phrase "UNINSTALL" "确认完整卸载 Master？" && uninstall_master --yes; tui_pause ;;
      b|B|q|Q) return 0 ;;
      *) echo "未知选项"; tui_pause ;;
    esac
  done
}

master_node_menu() {
  local choice
  while true; do
    tui_clear
    cat <<'MENU'
ProxyFleet Master / Master 节点相关

1) 查看 Master 状态和 Salt key
2) 核验并接受 Minion key
b) 返回
MENU
    read -r -p "请选择: " choice
    case "${choice}" in
      1) status_master; tui_pause ;;
      2) accept_key_tui; tui_pause ;;
      b|B|q|Q) return 0 ;;
      *) echo "未知选项"; tui_pause ;;
    esac
  done
}

master_config_menu() {
  local choice
  while true; do
    tui_clear
    cat <<'MENU'
ProxyFleet Master / 节点配置相关

1) 快速添加订阅 URL 并生成可用配置
2) 配置订阅 Provider
3) 导入自建节点文件
4) 导入自定义规则文件
5) 构建并校验 release
6) 配置端口白名单
7) 选择节点并同步到 Minion
8) 配置节点健康监控和邮件告警
b) 返回
MENU
    read -r -p "请选择: " choice
    case "${choice}" in
      1) quick_subscription_tui; tui_pause ;;
      2) master_config_subscription_tui; tui_pause ;;
      3) import_file_tui "自建节点文件" "${PROJECT_ROOT}/config-src/providers/self-hosted.yaml"; tui_pause ;;
      4) import_file_tui "自定义规则文件" "${PROJECT_ROOT}/config-src/rules/custom-rules.yaml"; tui_pause ;;
      5) build_release_tui; tui_pause ;;
      6) port_policy_tui; tui_pause ;;
      7) select_sync; tui_pause ;;
      8) monitor_tui ;;
      b|B|q|Q) return 0 ;;
      *) echo "未知选项"; tui_pause ;;
    esac
  done
}

master_service_menu() {
  local choice
  while true; do
    tui_clear
    cat <<'MENU'
ProxyFleet Master / 服务相关

1) 启动/停止/重启 Master 服务
2) 查看 Master 状态
b) 返回
MENU
    read -r -p "请选择: " choice
    case "${choice}" in
      1) master_services_tui; tui_pause ;;
      2) status_master; tui_pause ;;
      b|B|q|Q) return 0 ;;
      *) echo "未知选项"; tui_pause ;;
    esac
  done
}

master_tui() {
  if ! tui_available; then
    tui_unavailable
    return 2
  fi
  local choice
  while true; do
    tui_clear
    cat <<'MENU'
ProxyFleet Master 主控台

1) 安装相关
2) Master 节点相关
3) 节点配置相关
4) 服务相关
q) 退出
MENU
    read -r -p "请选择: " choice
    case "${choice}" in
      1) master_install_menu ;;
      2) master_node_menu ;;
      3) master_config_menu ;;
      4) master_service_menu ;;
      q|Q) return 0 ;;
      *) echo "未知选项"; tui_pause ;;
    esac
  done
}

latest_release_dir() {
  if [[ -d "${PROJECT_ROOT}/releases" ]]; then
    find "${PROJECT_ROOT}/releases" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
      | sort -n \
      | tail -n 1 \
      | sed "s#^#${PROJECT_ROOT}/releases/#"
  fi
}

update_master_tui() {
  local payload status version choice
  payload="$(check_update_master)" || return $?
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
        "下载并校验 update manifest 中的 Master 资产" \
        "备份并原子替换 allowlist 内文件" \
        "不会覆盖 .env.proxyfleet、config-src、runtime、releases、Salt PKI 或节点配置" \
        "更新后不会自动接受 key、不会自动切换节点"
      confirm_phrase "UPDATE" "确认应用 ProxyFleet Master 更新？" || return 0
      apply_update_master
      echo "更新完成。如更新了 salt/，请按需执行 sync-assets。"
      ;;
    3) suppress_update_master "${version}" ;;
    *) echo "已跳过更新" ;;
  esac
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
  local proxy_mode="tproxy"
  local refresh_health_first="false"
  local use_health_cache="true"
  local mihomo_api="http://127.0.0.1:9090"
  local health_timeout_ms="2000"
  local health_concurrency="8"
  local full_converge="false"
  local batch=""
  local concurrency="5"
  local plan_only="false"
  local log_dir="${PROJECT_ROOT}/runtime/logs/salt"

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
      --proxy-mode) proxy_mode="$2"; shift 2 ;;
      --full-converge) full_converge="true"; shift ;;
      --concurrency) concurrency="$2"; shift 2 ;;
      --plan) plan_only="true"; shift ;;
      --batch) batch="$2"; shift 2 ;;
      --log-dir) log_dir="$2"; shift 2 ;;
      *) die "未知 select-sync 参数：$1" ;;
    esac
  done
  case "${proxy_mode}" in
    tproxy|explicit-proxy) ;;
    *) die "未知 proxy-mode：${proxy_mode}" ;;
  esac

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

  local selected_line selected_node_id selected_name
  if [[ "${plan_only}" == "true" ]]; then
    [[ -f "${runtime_dir}/desired.yaml" ]] || die "缺少 ${runtime_dir}/desired.yaml，无法只读规划同步路径"
    selected_node_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("selected_node_id",""))' "${runtime_dir}/desired.yaml")"
    selected_name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("selected_mihomo_name",""))' "${runtime_dir}/desired.yaml")"
    echo "规划当前选择：${selected_name:-无}"
  else
    local catalog_file
    catalog_file="$(mktemp)"
    if [[ "${use_health_cache}" == "true" ]] && health_cache_has_useful_result "${health_cache}"; then
      proxyfleet_python nodes "${release_dir}" --health-cache "${health_cache}" > "${catalog_file}"
    else
      proxyfleet_python nodes "${release_dir}" > "${catalog_file}"
    fi

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
  fi

  local publish_args=(
    publish-salt
    "${release_dir}"
    "${runtime_dir}/desired.yaml"
    "${salt_root}"
    --component-locks "${PROJECT_ROOT}/component-locks.json"
    --port-policy-mode "${port_policy_mode}"
    --proxy-mode "${proxy_mode}"
  )
  local effective_salt_root="${salt_root}"
  local plan_salt_root=""
  if [[ "${plan_only}" == "true" ]]; then
    plan_salt_root="$(mktemp -d)"
    effective_salt_root="${plan_salt_root}"
    trap '[[ -n "${plan_salt_root:-}" ]] && rm -rf "${plan_salt_root}"' RETURN
    publish_args[3]="${effective_salt_root}"
  fi
  if [[ "${full_converge}" != "true" ]]; then
    publish_args+=(--lightweight)
  fi
  if [[ -n "${port_policy}" ]]; then
    publish_args+=(--port-policy "${port_policy}")
  fi
  proxyfleet_python "${publish_args[@]}" >/dev/null

  local source_module="${PROJECT_ROOT}/salt/modules/proxyfleet_mihomo.py"
  local expected_module_hash
  expected_module_hash="$(file_sha256 "${source_module}")"
  local sync_modules_required="true"
  if [[ "${plan_only}" == "true" ]]; then
    sync_modules_required="false"
  elif [[ "${full_converge}" != "true" ]] && salt_remote_module_hash_matches "${expected_module_hash}" "${target}" "${batch}"; then
    sync_modules_required="false"
  fi
  if [[ "${plan_only}" != "true" ]] && { [[ "${full_converge}" == "true" || "${sync_modules_required}" == "true" ]] || salt_assets_missing; }; then
    sync_assets
  fi
  if [[ "${plan_only}" != "true" && ( "${full_converge}" == "true" || "${sync_modules_required}" == "true" ) ]]; then
    echo "同步 Salt execution module..."
    # Salt 3008.1 的 batch 模式在 saltutil.sync_modules 上可能触发
    # "Some exception handling minion payload"。该操作本身很轻量，保持非 batch
    # 发布，batch 仅用于后续 state.apply。
    salt "${target}" saltutil.sync_modules >/dev/null
  else
    echo "远端 Salt module hash 已验证一致，跳过 saltutil.sync_modules"
  fi

  local sync_args=(
    sync
    "${release_dir}"
    "${runtime_dir}/desired.yaml"
    "${effective_salt_root}"
    --target "${target}"
    --salt-bin salt
    --port-policy-mode "${port_policy_mode}"
    --proxy-mode "${proxy_mode}"
    --concurrency "${concurrency}"
    --log-dir "${log_dir}"
  )
  if [[ "${full_converge}" == "true" ]]; then
    sync_args+=(--full-converge)
  fi
  if [[ "${plan_only}" == "true" ]]; then
    sync_args+=(--plan-only)
  fi
  if [[ -n "${batch}" ]]; then
    sync_args+=(--batch "${batch}")
  fi
  if [[ -n "${port_policy}" ]]; then
    sync_args+=(--port-policy-enabled)
  fi
  proxyfleet_python "${sync_args[@]}"
  if [[ "${plan_only}" != "true" ]]; then
    manual_switch_notify "${selected_node_id}" "${selected_name}" "${target}"
  fi
}

uninstall_master() {
  need_root
  local yes="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --purge-data) shift ;; # 兼容旧参数；当前 uninstall 默认完整清理。
      --yes) yes="1"; shift ;;
      *) die "未知卸载参数：$1" ;;
    esac
  done
  if [[ "${yes}" != "1" ]]; then
    if ! confirm_phrase "UNINSTALL PROXYFLEET MASTER" "危险操作：将停止并完整删除 ProxyFleet Master 受管数据和组件"; then
      die "已取消卸载"
    fi
  fi
  systemctl disable --now salt-master || true
  apt-mark unhold salt-master salt-common || true
  DEBIAN_FRONTEND=noninteractive apt-get purge -y salt-master || true
  echo "删除 ProxyFleet Master 受管数据。"
  rm -rf "${MASTER_PKI_DIR}" \
    "${MASTER_CONF_DIR}" \
    "${SALT_STATES_ROOT}" \
    "${SALT_PILLAR_ROOT}" \
    "${PROJECT_ROOT}/runtime" \
    "${PROJECT_ROOT}/cache" \
    "${PROJECT_ROOT}/releases" \
    "${PROJECT_ROOT}/config-src" \
    "${PROJECT_ROOT}/providers-cache" \
    "${PROJECT_ROOT}/subscriptions-cache"
  rm -f "${SALT_SOURCES}" "${SALT_PIN}" "${SALT_KEYRING}" "${PROJECT_ROOT}/.env.proxyfleet"
  echo "Master 卸载完成。未修改系统路由、DNS、防火墙或其它网络配置。"
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
  asset-mirror-deploy
                   下载并启动 Salt/Mihomo 固定组件镜像服务，默认端口 48080
  asset-mirror-prepare
                   只准备固定组件镜像文件，不启动 HTTP 服务
  asset-mirror-status
                   查看组件镜像 manifest 和服务状态
  start            启动 salt-master
  stop             停止 salt-master
  restart          重启 salt-master
  status           查看 salt-master 和 salt-key 状态
  sync-assets      同步 ProxyFleet Salt module/state 到 file_roots
  refresh-health   刷新本机 Mihomo API 节点测速缓存
  select-sync      进入实时 TUI 选择节点，并同步到所有 Minion
  monitor          节点健康监控：init/status/once
  check-update     检测 ProxyFleet Master 更新
  update [--yes]   应用 ProxyFleet Master 更新
  uninstall [--yes]
                   停止并完整卸载 ProxyFleet Master 受管数据和组件
  uninstall --purge-data [--yes]
                   兼容旧参数；行为等同 uninstall

select-sync 常用参数：
  --release-dir PATH       默认 releases/000001；不存在时自动使用 releases 下最大编号
  --runtime-dir PATH       默认 runtime
  --target '*'             默认同步全部 Minion
  --health-cache PATH      默认 runtime/health.json，存在时展示测速状态
  --proxy-mode MODE        默认 tproxy；可选 explicit-proxy 作为排障回退
  --live-health            兼容别名：行为与默认入口一致
  --mihomo-api URL         默认 http://127.0.0.1:9090
  --health-timeout-ms N    默认 2000
  --health-concurrency N   默认 8
  --port-policy PATH       可选：同步 Master managed 端口白名单；默认检测 config-src/port-policy.yaml
  --full-converge          完整发布 release、组件资产和 Salt module
  --concurrency N          ProxyFleet 应用层同步并发，默认 5
  --plan                   只输出 Minion 分类和执行计划，不执行同步
  --batch 10|20%           显式启用 Salt batch；默认不使用 Salt batch
  --log-dir PATH           完整 Salt 输出日志目录
  --refresh-health         deprecated：进入 TUI 前先刷新测速缓存
  --no-health-cache        deprecated：不读取测速缓存，只显示 unknown

monitor 常用子命令：
  monitor init              写入默认健康监控策略
  monitor status            查看策略、状态和邮件配置状态
  monitor auto-switch true|false
                            显式启用或关闭自动切换
  monitor once [--dry-run]  执行一轮健康检查；dry-run 不发邮件、不切换
  monitor validate-candidates
                            预验证自动切换候选节点并缓存可用节点
USAGE
}

command="${1:-}"
case "${command}" in
  "") master_tui ;;
  preflight) preflight ;;
  install) install_master ;;
  asset-mirror-deploy) asset_mirror_deploy ;;
  asset-mirror-prepare) asset_mirror_prepare ;;
  asset-mirror-status) asset_mirror_status ;;
  start) start_master ;;
  stop) stop_master ;;
  restart) restart_master ;;
  status) status_master ;;
  sync-assets) sync_assets ;;
  refresh-health) shift; refresh_health "$@" ;;
  select-sync) shift; select_sync "$@" ;;
  monitor)
    shift
    subcommand="${1:-}"
    case "${subcommand}" in
      init) shift; monitor_init "$@" ;;
      status) shift; monitor_status_cmd "$@" ;;
      auto-switch) shift; monitor_auto_switch_cmd "${1:-}" ;;
      once) shift; monitor_once_cmd "$@" ;;
      validate-candidates) shift; monitor_validate_candidates_cmd "$@" ;;
      *) die "未知 monitor 子命令：${subcommand:-}" ;;
    esac
    ;;
  check-update) shift; check_update_master "$@" ;;
  update) shift; need_root; if [[ "${1:-}" == "--yes" ]]; then apply_update_master; else update_master_tui; fi ;;
  uninstall) shift; uninstall_master "$@" ;;
  *) usage; exit 2 ;;
esac
