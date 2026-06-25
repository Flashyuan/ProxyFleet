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
3) 卸载 Master
b) 返回
MENU
    read -r -p "请选择: " choice
    case "${choice}" in
      1) preflight; tui_pause ;;
      2) preview_write "medium" "安装 Salt Master ${SALT_VERSION}" "写入 ${MASTER_CONF}" "同步 Salt states"; confirm_phrase "INSTALL" "确认安装/修复 Master？" && install_master; tui_pause ;;
      3) preview_write "critical" "卸载 salt-master" "默认保留 PKI 和 /srv/proxyfleet/salt"; confirm_phrase "UNINSTALL" "确认卸载 Master？" && uninstall_master; tui_pause ;;
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
  local purge_data="0"
  local yes="0"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --purge-data) purge_data="1"; shift ;;
      --yes) yes="1"; shift ;;
      *) die "未知卸载参数：$1" ;;
    esac
  done
  if [[ "${purge_data}" == "1" && "${yes}" != "1" ]]; then
    if ! confirm_phrase "PURGE MASTER DATA" "危险操作：将删除 /etc/salt/pki/master、/etc/salt/master.d 和 /srv/proxyfleet/salt"; then
      die "已取消 purge-data"
    fi
  fi
  systemctl disable --now salt-master || true
  apt-mark unhold salt-master salt-common || true
  DEBIAN_FRONTEND=noninteractive apt-get purge -y salt-master || true
  if [[ "${purge_data}" == "1" ]]; then
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
  uninstall --purge-data [--yes]
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
  "") master_tui ;;
  preflight) preflight ;;
  install) install_master ;;
  start) start_master ;;
  stop) stop_master ;;
  restart) restart_master ;;
  status) status_master ;;
  sync-assets) sync_assets ;;
  refresh-health) shift; refresh_health "$@" ;;
  select-sync) shift; select_sync "$@" ;;
  uninstall) shift; uninstall_master "$@" ;;
  *) usage; exit 2 ;;
esac
