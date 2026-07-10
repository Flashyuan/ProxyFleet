# Master 节点安装、配置与命令说明

本文只描述 Master 节点。Master 负责安装 Salt Master、管理配置源、构建
release、接受 Minion key、选择代理节点并同步到所有 Minion。

## 1. Master 节点职责

Master 负责：

- 运行 Salt Master `3008.1`；
- 管理订阅 URL、自建节点、自定义规则和端口白名单；
- 构建 Mihomo release；
- 接受 Minion key；
- 通过 Salt 下发 release、desired state 和代理节点选择。

Master 默认不承担业务代理流量。业务代理由各 Minion 上的 Mihomo 执行。

## 2. 前置条件

- Ubuntu 22.04 或 24.04；
- 当前用户具备 sudo 权限；
- Minion 能访问 Master 的 TCP `4505` 和 `4506`；
- 不把 Salt Master 直接暴露到不可信公网；
- Salt 组件固定安装 `3008.1`，安装后会被 `apt-mark hold` 锁定。

如果 Master 有本机防火墙或云安全组，需要放行给 Minion：

```text
TCP 4505
TCP 4506
```

这两个端口是 Salt 通信端口，通常不需要写入下发给 Minion 的代理端口白名单。

## 3. 用 curl 下载完整项目

Master 需要完整项目文件，不能只下载单个脚本。

在 Master 节点执行：

```bash
sudo apt-get update
sudo apt-get install -y curl tar ca-certificates

mkdir -p ~/project/ProxyFleet
curl -fsSL \
  https://github.com/Flashyuan/ProxyFleet/archive/refs/heads/main.tar.gz \
  | tar -xz --strip-components=1 -C ~/project/ProxyFleet

cd ~/project/ProxyFleet
chmod +x scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh
export PROXYFLEET_SOURCE_REF="github-main-curl-$(date -u +%Y%m%dT%H%M%SZ)"
```

后续更新项目时，可以重新执行 `curl | tar` 下载覆盖项目代码。真实配置和运行数据
位于 `config-src/`、`runtime/`、`releases/` 和 `.env.proxyfleet`，这些目录和文件
默认不会提交到 Git。

## 3.1 配置全局命令 `pfmaster`

如果希望在任意目录执行 Master 脚本，不要直接把脚本软链接到
`/usr/local/bin/pfmaster`。直接软链接会让脚本把项目根目录误判成 `/usr/local`，
导致找不到 `releases/`、`config-src/` 等目录。

推荐使用 wrapper：

```bash
sudo tee /usr/local/bin/pfmaster >/dev/null <<'EOF'
#!/usr/bin/env bash
export PROJECT_ROOT=/home/ubuntu/project/ProxyFleet
exec /home/ubuntu/project/ProxyFleet/scripts/proxyfleet-master.sh "$@"
EOF

sudo chmod +x /usr/local/bin/pfmaster
```

如果你的项目不在 `/home/ubuntu/project/ProxyFleet`，请把上面两处路径替换成真实
Master 项目路径，例如 `/home/ubuntu/it_project/proxyfleet-master`。

验证：

```bash
sudo pfmaster preflight
sudo pfmaster status
```

确认输出中的 `Project root` 是真实项目目录，而不是 `/usr/local`。

## 4. 安装 Master

推荐先做预检，再安装：

```bash
cd ~/project/ProxyFleet
scripts/proxyfleet-master.sh preflight
sudo scripts/proxyfleet-master.sh install
scripts/proxyfleet-master.sh status
```

安装后会写入：

```text
/etc/apt/keyrings/salt-archive-keyring.pgp
/etc/apt/sources.list.d/salt.sources
/etc/apt/preferences.d/proxyfleet-salt-pin
/etc/salt/master.d/proxyfleet.conf
/srv/proxyfleet/salt/states
/srv/proxyfleet/salt/pillar
```

检查 Salt Master 端口：

```bash
sudo ss -ltnp | grep -E ':4505|:4506'
apt-cache policy salt-master salt-common
apt-mark showhold
```

## 5. Master TUI 主控台

无参数运行脚本会直接进入 Master TUI：

```bash
sudo scripts/proxyfleet-master.sh
```

主菜单分为四类：

```text
安装相关          预检、安装/修复、检测更新、卸载 Master
Master 节点相关   查看 Master 状态、Salt key、接受 Minion key
节点配置相关      订阅、自建节点、规则、端口白名单、构建和同步
服务相关          启动、停止、重启和查看 Master 服务
```

日常配置推荐优先使用 TUI。下面的子命令主要用于自动化、排障和文档复现。

## 6. Master 脚本命令

```text
scripts/proxyfleet-master.sh <command>
```

常用命令：

```text
preflight                     只读检查 OS、systemd、sudo 和 Salt 目标版本
install                       安装 Salt Master 3008.1 并写入 Master 配置
start                         启动 salt-master
stop                          停止 salt-master
restart                       重启 salt-master
status                        查看 salt-master 状态和 Salt key 列表
sync-assets                   同步 ProxyFleet Salt module/state 到 file_roots
refresh-health                刷新 Master 本机 Mihomo API 测速缓存
select-sync                   进入实时 TUI 选择节点，并同步到 Minion
monitor validate-candidates   预验证自动切换候选节点并缓存可用节点
monitor once [--dry-run]      执行一轮健康监控；dry-run 不发邮件、不切换
check-update                  检测 ProxyFleet Master 新版本
update [--yes]                应用 ProxyFleet Master 更新
uninstall [--yes]             完整卸载 Master 受管数据和组件
uninstall --purge-data [--yes] 兼容旧参数；行为等同 uninstall
```

服务启停：

```bash
sudo scripts/proxyfleet-master.sh start
sudo scripts/proxyfleet-master.sh stop
sudo scripts/proxyfleet-master.sh restart
scripts/proxyfleet-master.sh status
```

完整卸载：

```bash
sudo scripts/proxyfleet-master.sh uninstall
```

Master 卸载会停止并卸载本机 `salt-master`，删除 Master PKI、Master 配置、
Salt states/pillar，以及本项目生成的 `runtime/`、`releases/`、`config-src/`、
`.env.proxyfleet` 等运行数据。

Master 卸载不会自动进入远端 Minion 卸载 Mihomo。Minion 的完整卸载需要在对应
Minion 上执行：

```bash
sudo scripts/proxyfleet-minion.sh uninstall
```

卸载不会重置系统路由、DNS、防火墙或其它系统网络配置。

## 7. 检测并更新 Master

推荐在 Master TUI 中进入：

```text
安装相关 -> 检测并更新 ProxyFleet Master
```

非交互命令：

```bash
sudo scripts/proxyfleet-master.sh check-update
sudo scripts/proxyfleet-master.sh update
sudo scripts/proxyfleet-master.sh update --yes
```

`check-update` 只读。`update` 默认仍会询问确认；`--yes` 用于自动化，但不会跳过
manifest、SHA-256、路径 allowlist/denylist、备份、语法检查和回滚。

Master 更新只允许覆盖 `README.md`、`component-locks.json`、`update-manifest.json`、
`scripts/` 中的 ProxyFleet 脚本、`src/`、`salt/` 和 `docs/`。

更新不会覆盖 `.env.proxyfleet`、`config-src/`、`runtime/`、`releases/`、Salt PKI、
Minion key、订阅缓存或节点配置。更新也不会自动接受 Minion key，且不会自动切换
代理节点。

如果更新了 `salt/`，更新完成后按需执行：

```bash
sudo scripts/proxyfleet-master.sh sync-assets
```

## 7.1 Mihomo 资产镜像和离线包

推荐在 Master TUI 中一键部署固定组件镜像：

```bash
sudo scripts/proxyfleet-master.sh
```

进入：

```text
安装相关 -> 一键部署 Salt/Mihomo 固定组件镜像
```

该操作会：

1. 下载 Salt 固定版本 `3008.1` 的 Minion 安装 deb；
2. 下载 `component-locks.json` 中 Mihomo 固定版本资产；
3. 生成 `bootstrap-manifest.json`；
4. 启动只读 HTTP 服务：

```text
http://<Master-IP>:48080/proxyfleet/
```

也可以用命令执行：

```bash
sudo scripts/proxyfleet-master.sh asset-mirror-deploy
sudo scripts/proxyfleet-master.sh asset-mirror-status
```

请在防火墙或安全组中只允许局域网/受管 Minion 访问 TCP `48080`。

Minion 安装 Salt 时会默认优先访问：

```text
http://<Master-IP>:48080/proxyfleet/bootstrap-manifest.json
```

下载后会校验 manifest 中的 SHA-256，校验失败会回退官方 Salt 源。

`component-locks.json` 仍然是唯一可信来源，所有 Mihomo 资产都必须固定版本和
SHA-256。每个架构的 artifact 可以增加：

```json
{
  "local_path": "component-assets/mihomo-linux-amd64-compatible-v1.19.27.gz",
  "mirror_urls": [
    "https://<your-mirror>/mihomo-linux-amd64-compatible-v1.19.27.gz"
  ]
}
```

推荐把离线包放在 Master 项目目录下：

```text
component-assets/
assets/
offline-assets/
```

执行 `select-sync` 或 `publish-salt` 时，Master 会把这些文件发布到 Salt
file_roots 的 `proxyfleet/assets/`，Minion 会同步到 `/etc/proxyfleet/assets/`。
Minion 安装 Mihomo 时会按顺序尝试：

1. artifact 的 `local_path` 或 `file`；
2. `/etc/proxyfleet/assets/` 中按文件名或 SHA-256 命中的离线包；
3. `/var/cache/proxyfleet/assets/` 中的本机离线包；
4. `mirror_urls` / `mirrors`；
5. 原始 `url`。

无论来自镜像还是离线包，最终都会校验 artifact 的 `sha256`。校验失败会
fail-closed，不会安装。

说明：组件资产发布用于新 Minion 首次安装、离线安装、组件版本升级和接管修复。
日常节点切换通常只需要更新 `desired.yaml`；当前版本已将日常切换与完整组件收敛
拆开，避免每次切换都重新发布不变的 Mihomo 离线资产。

## 8. 接受 Minion Key

Minion 安装后，回到 Master 节点执行：

```bash
sudo salt-key -L
sudo salt-key -F
```

确认 fingerprint 和 Minion 身份后接受：

```bash
sudo salt-key -a <minion-id>
sudo salt '<minion-id>' test.ping
```

清理 key：

```bash
sudo salt-key -d <minion-id>
sudo salt-key -D
```

`salt-key -D` 会删除全部 key，是危险操作。

## 9. 配置订阅 URL

最少步骤方式：

```bash
sudo scripts/proxyfleet-master.sh
```

进入：

```text
节点配置相关 -> 快速添加订阅 URL 并生成可用配置
```

按提示输入：

```text
订阅名称
订阅 URL
```

脚本会自动完成：

- 把订阅 URL 写入本地 `.env.proxyfleet`；
- 生成或更新 `config-src/base.json`；
- 生成或更新 `config-src/providers.json`；
- 生成或更新 `config-src/groups.json`；
- 生成或更新 `config-src/rules.json`；
- 拉取订阅并从完整 Clash/Mihomo 配置中提取顶层 `proxies`；
- 构建 release。

默认规则是：

```text
MATCH,FLEET_PROXY
```

也就是所有未被其它规则命中的流量都走当前选择的代理节点。

## 10. 多订阅

多订阅不需要手写 JSON。重复执行：

```text
节点配置相关 -> 快速添加订阅 URL 并生成可用配置
```

每次使用不同订阅名称和 URL。脚本会新增 provider，并把该 provider 追加进
`FLEET_PROXY` 策略组。

订阅 URL 只保存在本地 `.env.proxyfleet`，不会提交到 Git。

## 11. 导入自建节点和自定义规则

在 Master TUI 中进入：

```text
节点配置相关 -> 导入自建节点文件
节点配置相关 -> 导入自定义规则文件
```

自建节点文件需要包含 Mihomo/Clash `proxies`。订阅返回的是完整配置文件也没关系，
构建器会自动提取顶层 `proxies`。

自定义规则用于补充 `rules.json` 或 rule provider。规则顺序由 Master 本地
配置统一管理，订阅里的 `proxy-groups` 和 `rules` 不会直接进入最终 release。

## 12. 端口白名单

Master managed 端口白名单默认写入：

```text
config-src/port-policy.yaml
```

在 Master TUI 中进入：

```text
节点配置相关 -> 配置端口白名单
```

直接输入一个或多个端口号即可。多个端口可以用空格或逗号分隔：

```text
7890, 7891 9090
```

`select-sync` 会默认检查 `config-src/port-policy.yaml`。文件存在时按 `merge`
模式同步到 Minion managed 层；文件不存在时显示 `端口白名单：未配置`。

Minion 本地 override 文件是：

```text
/etc/proxyfleet/local/port-policy.yaml
```

Salt state 只保证 `/etc/proxyfleet/local` 目录存在，不覆盖、不删除这个本地文件。
因此 Minion 可以保留自己的本机端口规则。

当前版本不会自动把 SSH `22` 或 Salt `4505/4506` 写进这个文件。原因是
`config-src/port-policy.yaml` 是下发给 Minion 的代理端口策略，而 Salt
`4505/4506` 是 Master 入站控制平面端口，应该在 Master 防火墙或云安全组中
只对受管 Minion 放行。SSH 端口是否加入白名单取决于你的本机代理/防火墙策略。

## 13. 选择节点并同步

推荐命令：

```bash
sudo scripts/proxyfleet-master.sh select-sync
```

当前版本中，`select-sync` 默认进入实时 TUI。`--live-health` 只是兼容别名。

TUI 顶部会显示当前选择。没有已选择节点时显示：

```text
当前选择：无
```

常用按键：

```text
↑/↓ 或 j/k    移动
Enter         选择并同步
/             搜索
r             重新测速
s             按延迟排序
n             恢复原始序号
q             退出
```

只同步指定 Minion：

```bash
sudo scripts/proxyfleet-master.sh select-sync --target '<minion-id>'
```

`select-sync` 会把选择写入 `runtime/desired.yaml`，发布 release 到 Salt
file_roots，然后执行 Salt 同步。

性能优化行为：`select-sync` 默认走智能分流路径，TUI 优先测速当前选择、当前页
和搜索结果；所有 Minion 仍同步成同一个节点，但已完成基线安装的旧 Minion
只执行 Mihomo API 轻量切换，新 Minion 或组件漂移 Minion 才执行完整
`state.apply`。默认不启用 Salt batch，而是由 ProxyFleet 按较小并发分组执行，
降低 Master 瞬时 CPU、内存和终端输出压力。终端默认只显示进度和摘要，完整
Salt 输出写入日志。

## 14. `select-sync` 参数

```text
--release-dir PATH       release 目录，默认 releases/000001；不存在时取最大编号
--runtime-dir PATH       runtime 目录，默认 runtime
--salt-root PATH         Salt file_roots，默认 /srv/proxyfleet/salt/states
--target TARGET          Salt 目标，默认 *
--target-group NAME      desired target_group，默认 production
--health-cache PATH      测速缓存，默认 runtime/health.json
--mihomo-api URL         Mihomo API，默认 http://127.0.0.1:9090
--health-timeout-ms N    单节点测速超时，默认 2000
--health-concurrency N   测速并发，默认 8
--port-policy PATH       Master managed 端口白名单，默认 config-src/port-policy.yaml
--port-policy-mode MODE  merge/master-only/local-only/disabled
--proxy-mode MODE        Mihomo 运行模式，默认 tproxy；可选 explicit-proxy
--full-converge          完整发布 release、组件资产和 Salt module
--concurrency N          ProxyFleet 应用层同步并发，默认 5
--plan                   只输出 Minion 分类和执行计划，不执行同步
--batch 10|20%           显式启用 Salt batch；默认不使用 Salt batch
--log-dir PATH           完整 Salt 输出日志目录，默认 runtime/logs/salt
```

`--plan` 只读取当前选择并输出 Minion 分类与执行计划。它使用临时 Salt root，
不会修改生产 `/srv/proxyfleet/salt/states`，也不会执行真实同步。

普通 `select-sync` 如果发现生产 Salt file_roots 缺少 release、组件锁或资产基线，
会 fail-closed 并提示管理员确认后显式执行 `select-sync --full-converge`。基线
补齐后，后续日常切换会回到智能分流轻量路径。

Master 更新后，如果某台 Minion 的 Salt execution module 缺失或 hash 不一致，
只会对这台 Minion 执行 `saltutil.sync_modules + full-converge`。其它已经
`module-current + ready-old` 的旧 Minion 继续走 `switch-only`。

默认 `tproxy` 会在 release 的 `config.yaml` 中启用 Mihomo TUN 自动路由和
`tproxy-port`，让 Minion 本机进程不显式设置 `HTTP_PROXY` 时也可以走当前选中节点。
该模式会覆盖订阅配置中关闭透明代理的字段，例如 `tun.enable: false` 和
`tproxy-port: 0`。
如果 Minion 同时运行 Docker、K8s 或 CNI，默认 release 会前置私网和集群域名的
DIRECT 规则，并把常见私网、Pod/Service CIDR、bridge、loopback、link-local 等
网段加入 `route-exclude-address`。如需追加本环境特殊网段，可创建
`config-src/tproxy-excludes.json` 或 `config-src/tproxy-excludes.yaml`。
如需排查透明代理导致的路由问题，可临时使用 `--proxy-mode explicit-proxy`。

废弃但兼容的参数：

```text
--live-health            兼容别名，等同 select-sync 默认 TUI
--refresh-health         废弃，不再作为推荐入口
--no-health-cache        废弃，不再作为推荐入口
```

## 15. 手动构建 release

通常 TUI 会自动构建。需要手动复现时执行：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli build-release \
  config-src releases \
  --revision 1 \
  --source-git-commit "${PROXYFLEET_SOURCE_REF:-manual-config}" \
  --component-locks component-locks.json \
  --subscription-cache runtime/subscriptions
```

查看节点：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli nodes releases/000001
```

合并测速缓存查看：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli nodes \
  releases/000001 \
  --health-cache runtime/health.json
```

## 16. 常见验证

在 Master 节点执行：

```bash
sudo salt '*' test.ping
sudo salt '*' grains.items
sudo salt '*' systemctl.status mihomo.service
sudo salt '*' state.apply proxyfleet.sync test=true
```
