# Master 节点安装、配置与常用命令

> 适用：Ubuntu 22.04/24.04 原生 systemd Master。Master 负责构建 release、
> 管理 Salt Master、接受 Minion key、选择代理节点并同步到 Minion。

## 1. Master 节点职责

Master 节点执行：

- 下载完整 ProxyFleet 项目；
- 安装并运行 Salt Master 3008.1；
- 构建 Mihomo release；
- 管理订阅 URL、自建节点、自定义规则；
- 接受 Minion key；
- 通过 Salt 同步 release、desired state 和节点选择。

Master 不承载业务代理流量，业务流量由各 Minion 本机 Mihomo 直接连接代理节点。

## 2. 前置条件

- 当前机器为 Ubuntu 22.04/24.04；
- 当前用户具备 sudo 权限；
- Minion 可以访问 Master 的 TCP 4505/4506；
- 不启用公网 `salt-api`；
- Salt 固定安装 `3008.1`，安装后 `apt-mark hold`。

## 3. 通过 curl 获取完整项目

Master 需要完整项目文件，不能只下载一个脚本。

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

更新项目时，重新执行 `curl | tar` 解压命令即可。生产配置和运行数据请放在
`runtime/`、`config-src/` 或外部受控路径，并避免覆盖真实配置文件。

## 4. 安装 Master

在 Master 节点执行：

```bash
scripts/proxyfleet-master.sh preflight
sudo scripts/proxyfleet-master.sh install
```

下面的无参数命令会直接进入 Master TUI 主控台，由菜单完成预检、
安装、配置、订阅/规则导入和同步：

```bash
sudo scripts/proxyfleet-master.sh
```

子命令仍保留给自动化、排障和文档复现。

安装会写入：

- `/etc/apt/keyrings/salt-archive-keyring.pgp`
- `/etc/apt/sources.list.d/salt.sources`
- `/etc/apt/preferences.d/proxyfleet-salt-pin`
- `/etc/salt/master.d/proxyfleet.conf`
- `/srv/proxyfleet/salt/states`
- `/srv/proxyfleet/salt/pillar`

安装后检查：

```bash
scripts/proxyfleet-master.sh status
apt-cache policy salt-master salt-common
apt-mark showhold
sudo ss -ltnp | grep -E ':4505|:4506'
```

## 5. Master 脚本命令

```text
scripts/proxyfleet-master.sh <command>
```

常用命令：

```text
preflight              只读检查 OS、systemd、sudo 和 Salt 目标版本
install                安装 Salt Master 3008.1 并配置 file_roots/pillar_roots
start                  启动 salt-master
stop                   停止 salt-master
restart                重启 salt-master
status                 查看 salt-master 状态和 Salt key 列表
sync-assets            同步项目 Salt module/state 到 /srv/proxyfleet/salt/states
refresh-health         刷新 Master 本机 Mihomo API 测速缓存
select-sync            选择代理节点并同步到 Minion
uninstall              卸载 salt-master，默认保留 PKI 和状态目录
uninstall --purge-data [--yes]
                     危险清理，删除 Master PKI、配置和 states
```

服务启停：

```bash
sudo scripts/proxyfleet-master.sh start
sudo scripts/proxyfleet-master.sh stop
sudo scripts/proxyfleet-master.sh restart
scripts/proxyfleet-master.sh status
```

卸载：

```bash
sudo scripts/proxyfleet-master.sh uninstall
sudo scripts/proxyfleet-master.sh uninstall --purge-data --yes
```

Master 脚本的 `stop` 和 `uninstall` 只影响 Master 本机 `salt-master`。它不会自动
停止或卸载各 Minion 上的 `mihomo.service`。Minion 本机 Mihomo 生命周期后续会由
`proxyfleet-minion.sh --with-mihomo` 或 `mihomo-*` 专用命令显式控制。

## 6. 接受 Minion Key

Minion 安装后，在 Master 节点执行：

```bash
sudo salt-key -L
sudo salt-key -F
```

确认 fingerprint 和 Minion 身份后接受：

```bash
sudo salt-key -a <minion-id>
```

验证连通：

```bash
sudo salt '<minion-id>' test.ping
sudo salt '<minion-id>' grains.items
```

## 7. 配置订阅、自建节点和自定义规则

配置源目录为 `config-src/`。常见文件包括：

```text
config-src/base.json        Mihomo 基础配置
config-src/providers.json   订阅 Provider 和自建节点 Provider
config-src/groups.json      FLEET_PROXY 等策略组
config-src/rules.json       规则顺序和 rule provider
```

订阅 URL 不写入 Git，推荐用环境变量：

```json
{
  "id": "airport-main",
  "kind": "subscription",
  "enabled": true,
  "env": "PROXYFLEET_SUB_AIRPORT_MAIN",
  "name_prefix": "[AIR] ",
  "output": "providers/airport-main.yaml"
}
```

构建前在 Master 节点注入真实 URL：

```bash
export PROXYFLEET_SUB_AIRPORT_MAIN='https://你的订阅URL'
```

订阅返回完整 Mihomo/Clash 配置时，构建器会提取顶层 `proxies`。订阅里的
`proxy-groups` 和 `rules` 不进入 release，策略组和规则仍由 Master 本地
`groups.json`、`rules.json` 统一管理。

## 8. 构建 release

在 Master 节点执行：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli build-release \
  config-src \
  releases \
  --revision 1 \
  --source-git-commit "${PROXYFLEET_SOURCE_REF:-manual-config}" \
  --component-locks component-locks.json \
  --subscription-cache runtime/subscriptions
```

参数说明：

```text
config-src                  配置源目录
releases                    release 输出根目录
--revision                  release 编号
--source-git-commit         来源标识；curl 部署可用 PROXYFLEET_SOURCE_REF
--component-locks           组件锁定清单
--subscription-cache        订阅 Last Known Good 缓存目录
```

## 9. 查看节点和测速

查看可选节点：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli nodes releases/000001
```

刷新测速缓存：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli health-check \
  releases/000001 runtime/health.json \
  --mihomo-api http://127.0.0.1:9090 \
  --all
```

合并测速缓存查看：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli nodes \
  releases/000001 \
  --health-cache runtime/health.json
```

测速只调用 Master 本机 Mihomo delay API，不改变当前 `FLEET_PROXY`。

## 10. 选择节点并同步

最常用命令：

```bash
sudo scripts/proxyfleet-master.sh select-sync
```

当前版本中，`select-sync` 默认进入 `curses` TUI。`--live-health` 只作为兼容别名。

TUI 按键：

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
sudo scripts/proxyfleet-master.sh select-sync \
  --target '<minion-id>'
```

`select-sync` 参数：

`select-sync` 默认进入实时 TUI。`--live-health` 只作为兼容别名保留。

```text
--release-dir PATH       默认 releases/000001；不存在时取 releases 下最大编号
--runtime-dir PATH       默认 runtime
--salt-root PATH         默认 /srv/proxyfleet/salt/states
--target TARGET          Salt 目标，默认 *
--target-group NAME      desired target_group，默认 production
--health-cache PATH      默认 runtime/health.json
--mihomo-api URL         默认 http://127.0.0.1:9090，仅允许 loopback
--health-timeout-ms N    默认 2000
--health-concurrency N   默认 16
--port-policy PATH       默认 config-src/port-policy.yaml，发布 Master managed 端口白名单
--port-policy-mode MODE  merge/master-only/local-only/disabled
```

废弃参数：

```text
--live-health            兼容别名，等同 select-sync 默认 TUI
--refresh-health         废弃，不再作为推荐入口
--no-health-cache        废弃，不再作为推荐入口
```

## 11. 手动分步发布

选择节点，只写 `runtime/desired.yaml`：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli select-node \
  releases/000001 \
  runtime \
  --node-id <node-id> \
  --target-group production
```

发布 release 和 desired 到 Salt file_roots：

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli publish-salt \
  releases/000001 \
  runtime/desired.yaml \
  /srv/proxyfleet/salt/states \
  --component-locks component-locks.json
```

同步 Salt module：

```bash
sudo scripts/proxyfleet-master.sh sync-assets
sudo salt '*' saltutil.sync_modules
```

先 dry-run：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 \
  runtime/desired.yaml \
  /srv/proxyfleet/salt/states \
  --target '<minion-id-or-target>' \
  --dry-run
```

正式同步：

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 \
  runtime/desired.yaml \
  /srv/proxyfleet/salt/states \
  --target '<minion-id-or-target>'
```

## 12. 端口白名单

Master managed 端口白名单默认写入：

```text
config-src/port-policy.yaml
```

示例：

```yaml
schema_version: "1.0"
owner: master
mode: merge
allow:
  - protocol: tcp
    port: 22
    source: 192.168.1.0/24
    comment: ssh management
deny: []
```

该文件默认被 `.gitignore` 排除，不会误提交。`select-sync`
会默认检查这个文件：存在则按 `merge` 模式发布到 managed 层；不存在则显示
`端口白名单：未配置`。

手动发布 Master managed 端口白名单：

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli publish-salt \
  releases/000001 \
  runtime/desired.yaml \
  /srv/proxyfleet/salt/states \
  --component-locks component-locks.json \
  --port-policy config-src/port-policy.yaml \
  --port-policy-mode merge
```

Minion 本机 override 位于：

```text
/etc/proxyfleet/local/port-policy.yaml
```

Salt state 不覆盖、不删除 `/etc/proxyfleet/local` 下的本地规则。
