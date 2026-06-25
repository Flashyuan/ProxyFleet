# ProxyFleet 用户使用手册

> 本手册按实际操作顺序说明：在哪个节点执行什么命令，以及常用参数代表什么。

## 1. 最短路径总览

```text
Master 节点：下载完整项目 → 安装 Master
Minion 节点：下载 minion 脚本 → 安装 Minion
Master 节点：接受 Minion key
Master 节点：配置订阅/自建节点/规则 → 构建 release
Master 节点：进入 TUI 选择节点 → 同步到 Minion
Master 节点：验证 Minion 状态
```

## 2. Master 节点安装顺序

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

scripts/proxyfleet-master.sh preflight
sudo scripts/proxyfleet-master.sh install
scripts/proxyfleet-master.sh status
```

Master 防火墙或云安全组需要允许 Minion 访问：

```text
TCP 4505
TCP 4506
```

## 3. Minion 节点安装顺序

在每台 Minion 节点执行：

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates

mkdir -p ~/project/proxyfleet-minion/scripts
cd ~/project/proxyfleet-minion

curl -fsSL \
  https://raw.githubusercontent.com/Flashyuan/ProxyFleet/main/scripts/proxyfleet-minion.sh \
  -o scripts/proxyfleet-minion.sh

chmod +x scripts/proxyfleet-minion.sh

scripts/proxyfleet-minion.sh preflight

sudo scripts/proxyfleet-minion.sh install \
  --master <master-ip-or-dns> \
  --id <minion-id> \
  --environment production \
  --driver native-mihomo \
  --release-channel stable
```

安装后 Minion 会提示回到 Master 接受 key。

## 4. Master 接受 Minion Key

回到 Master 节点执行：

```bash
sudo salt-key -L
sudo salt-key -F
sudo salt-key -a <minion-id>
sudo salt '<minion-id>' test.ping
```

只有确认 fingerprint 和 Minion 身份后再接受 key。

## 5. Master 配置代理源

配置源在 Master 的 `config-src/` 目录。

常见文件：

```text
config-src/base.json
config-src/providers.json
config-src/groups.json
config-src/rules.json
```

订阅 URL 用环境变量注入：

```bash
cd ~/project/ProxyFleet
export PROXYFLEET_SUB_AIRPORT_MAIN='https://你的订阅URL'
```

构建 release：

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

## 6. Master 选择节点并同步

推荐使用 TUI：

```bash
sudo scripts/proxyfleet-master.sh select-sync
```

当前版本中，`select-sync` 默认就是实时 TUI。`--live-health` 只作为兼容别名。
TUI 会动态刷新节点延迟，并在顶部显示当前选中节点；如果没有当前选择，则显示
`当前选择：无`。

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

只同步某个 Minion：

```bash
sudo scripts/proxyfleet-master.sh select-sync \
  --target '<minion-id>'
```

查看节点列表但不进入 TUI：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli nodes releases/000001
```

旧测速缓存入口 `--refresh-health` 已进入废弃路径，不再作为推荐操作。

## 7. 常用命令速查

Master 服务：

```bash
sudo scripts/proxyfleet-master.sh start
sudo scripts/proxyfleet-master.sh stop
sudo scripts/proxyfleet-master.sh restart
scripts/proxyfleet-master.sh status
sudo scripts/proxyfleet-master.sh sync-assets
```

Minion 服务：

```bash
sudo scripts/proxyfleet-minion.sh start
sudo scripts/proxyfleet-minion.sh stop
sudo scripts/proxyfleet-minion.sh restart
scripts/proxyfleet-minion.sh status
```

Salt key：

```bash
sudo salt-key -L
sudo salt-key -F
sudo salt-key -a <minion-id>
sudo salt-key -d <minion-id>
sudo salt-key -D
```

连通性：

```bash
sudo salt '*' test.ping
sudo salt '<minion-id>' grains.items
```

Minion 本机检查 Master 端口：

```bash
timeout 3 bash -c '</dev/tcp/<master-ip>/4505' && echo 4505-ok
timeout 3 bash -c '</dev/tcp/<master-ip>/4506' && echo 4506-ok
```

Mihomo 状态：

```bash
sudo salt '*' systemctl.status mihomo.service
```

## 8. Master 命令参数说明

`select-sync` 参数：

```text
--release-dir PATH       release 目录，默认 releases/000001
--runtime-dir PATH       runtime 目录，默认 runtime
--salt-root PATH         Salt file_roots，默认 /srv/proxyfleet/salt/states
--target TARGET          Salt 目标，默认 *
--target-group NAME      desired target_group，默认 production
--health-cache PATH      测速缓存，默认 runtime/health.json
--mihomo-api URL         Mihomo API，默认 http://127.0.0.1:9090
--health-timeout-ms N    单节点测速超时，默认 2000
--health-concurrency N   测速并发，默认 16
--port-policy PATH       默认 config-src/port-policy.yaml
--port-policy-mode MODE  merge/master-only/local-only/disabled
```

废弃参数：

```text
--live-health            兼容别名，等同 select-sync 默认 TUI
--refresh-health         废弃，不再作为推荐入口
--no-health-cache        废弃，不再作为推荐入口
```

`refresh-health` 参数：

```text
--release-dir PATH       release 目录
--health-cache PATH      输出测速缓存
--mihomo-api URL         Mihomo API
--timeout-ms N           单节点测速超时
--concurrency N          并发测速数量
--url URL                测速 URL，默认 https://www.gstatic.com/generate_204
```

## 8A. 端口白名单配置位置

Master 公共端口白名单默认写在：

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

该文件默认被 `.gitignore` 排除，不会误提交。执行
`sudo scripts/proxyfleet-master.sh select-sync` 时会自动检查它：存在就按
`merge` 模式同步到 Minion 的 managed 层；不存在则显示
`端口白名单：未配置`。

Minion 自己的本机例外规则写在：

```text
/etc/proxyfleet/local/port-policy.yaml
```

Master 不覆盖这个 local 文件。

## 9. Minion 命令参数说明

`install` / `bootstrap` 参数：

```text
--master / --master-ip     Master IP 或 DNS
--id                       Minion 唯一 ID
--environment              默认 production
--driver                   默认 native-mihomo
--release-channel          默认 stable
```

卸载参数：

```text
uninstall                  卸载 salt-minion，保留 PKI 和配置
uninstall --purge-data     危险清理，删除 Minion PKI 和配置
```

Mihomo 生命周期控制：

```text
start --with-mihomo         启动 salt-minion 后安全启动 Mihomo
stop --with-mihomo          安全停止 Mihomo 后停止 salt-minion
restart --with-mihomo       同时重启 salt-minion 和 Mihomo
uninstall --with-mihomo     卸载 salt-minion，并执行 Mihomo 安全卸载
mihomo-start                只启动本机 Mihomo
mihomo-stop                 只停止本机 Mihomo
mihomo-restart              只重启本机 Mihomo
mihomo-status               查看 Mihomo 服务和受管配置状态
mihomo-uninstall            卸载 Mihomo，默认保留 /etc/proxyfleet
```

危险清理参数：

```text
--purge-managed        删除 managed/effective 产物，保留 local override
--purge-all --yes      删除受管 release、链接、unit 和受管二进制
--purge-local-override 额外允许删除 /etc/proxyfleet/local
```

默认 `start/stop/restart/uninstall` 仍只控制 `salt-minion`。只有显式传入
`--with-mihomo` 或使用 `mihomo-*` 子命令时，脚本才会控制 Mihomo。

## 10. 卸载

Master 节点：

```bash
sudo scripts/proxyfleet-master.sh uninstall
sudo scripts/proxyfleet-master.sh uninstall --purge-data
```

Minion 节点：

```bash
sudo scripts/proxyfleet-minion.sh uninstall
sudo scripts/proxyfleet-minion.sh uninstall --purge-data
```

`--purge-data` 会删除 PKI 和配置，只适合测试环境或确认重建身份时使用。

## 11. 常见操作顺序

新增 Minion：

```text
Minion 节点：下载 proxyfleet-minion.sh
Minion 节点：install --master <master-ip> --id <minion-id>
Master 节点：salt-key -F
Master 节点：salt-key -a <minion-id>
Master 节点：salt '<minion-id>' test.ping
Master 节点：select-sync --target '<minion-id>'
```

切换代理节点：

```text
Master 节点：build-release
Master 节点：select-sync
Master 节点：salt '*' test.ping
```

更新项目后同步 Salt assets：

```text
Master 节点：重新 curl 下载完整项目
Master 节点：sync-assets
Master 节点：salt '*' saltutil.sync_modules
```
