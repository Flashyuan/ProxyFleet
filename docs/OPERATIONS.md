# ProxyFleet 日常运维手册

本文按“在哪台节点执行什么命令”整理日常操作。完整安装细节见：

- `docs/INSTALL_MASTER.md`
- `docs/INSTALL_MINION.md`
- `docs/USER_MANUAL.md`

## 1. 节点分工

```text
Master：构建 release、接受 key、管理配置、选择节点、同步到 Minion
Minion：运行 salt-minion、接收 release、运行 ProxyFleet 受管 Mihomo
```

订阅、规则、节点切换和公共端口白名单都在 Master 上操作。

## 2. Master 常用操作

进入 Master 项目目录：

```bash
cd ~/project/ProxyFleet
```

打开 TUI：

```bash
sudo scripts/proxyfleet-master.sh
```

服务操作：

```bash
sudo scripts/proxyfleet-master.sh start
sudo scripts/proxyfleet-master.sh stop
sudo scripts/proxyfleet-master.sh restart
scripts/proxyfleet-master.sh status
```

同步 Salt assets：

```bash
sudo scripts/proxyfleet-master.sh sync-assets
sudo salt '*' saltutil.sync_modules
```

完整卸载 Master：

```bash
sudo scripts/proxyfleet-master.sh uninstall
```

Master 卸载只清理 Master 本机受管组件和项目运行数据，不会进入远端 Minion
卸载 Mihomo，也不会重置系统路由、DNS、防火墙。

## 3. Minion 常用操作

进入 Minion 脚本目录：

```bash
cd ~/project/proxyfleet-minion
```

打开 TUI：

```bash
sudo scripts/proxyfleet-minion.sh
```

Salt Minion 服务：

```bash
sudo scripts/proxyfleet-minion.sh start
sudo scripts/proxyfleet-minion.sh stop
sudo scripts/proxyfleet-minion.sh restart
scripts/proxyfleet-minion.sh status
```

同时联动 Mihomo：

```bash
sudo scripts/proxyfleet-minion.sh start --with-mihomo
sudo scripts/proxyfleet-minion.sh stop --with-mihomo
sudo scripts/proxyfleet-minion.sh restart --with-mihomo
```

只控制 Mihomo：

```bash
sudo scripts/proxyfleet-minion.sh mihomo-start
sudo scripts/proxyfleet-minion.sh mihomo-stop
sudo scripts/proxyfleet-minion.sh mihomo-restart
scripts/proxyfleet-minion.sh mihomo-status
```

完整卸载 Minion：

```bash
sudo scripts/proxyfleet-minion.sh uninstall
```

Minion 卸载会清理 `salt-minion`、ProxyFleet 受管 Mihomo 和 `/etc/proxyfleet`，
但不会重置系统路由、DNS、防火墙。

## 4. Salt Key 运维

以下命令在 Master 节点执行：

```bash
sudo salt-key -L
sudo salt-key -F
sudo salt-key -a <minion-id>
sudo salt-key -d <minion-id>
sudo salt-key -D
```

说明：

```text
-L              列出 accepted/unaccepted/rejected key
-F              显示 fingerprint，用于人工核验
-a <id>         接受指定 Minion
-d <id>         删除指定 Minion key
-D              删除全部 key，危险操作
```

## 5. 最常用部署顺序

在 Master 节点：

```bash
sudo scripts/proxyfleet-master.sh install
```

在每台 Minion 节点：

```bash
sudo scripts/proxyfleet-minion.sh install \
  --master <master-ip-or-dns> \
  --id <minion-id> \
  --environment production \
  --driver native-mihomo \
  --release-channel stable
```

回到 Master 节点：

```bash
sudo salt-key -F
sudo salt-key -a <minion-id>
sudo salt '<minion-id>' test.ping
```

继续在 Master TUI 中：

```text
节点配置相关 -> 快速添加订阅 URL 并生成可用配置
节点配置相关 -> 选择节点并同步到 Minion
```

## 6. 选择节点并同步

在 Master 节点执行：

```bash
sudo scripts/proxyfleet-master.sh select-sync
```

当前 `select-sync` 默认进入实时 TUI，并在后台动态刷新节点延迟。`--live-health`
只是兼容别名。

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

## 7. `select-sync` 参数

```text
--release-dir PATH       release 目录，默认 releases/000001；不存在时取最大编号
--runtime-dir PATH       runtime 目录，默认 runtime
--salt-root PATH         Salt file_roots，默认 /srv/proxyfleet/salt/states
--target TARGET          Salt 目标，默认 *
--target-group NAME      desired target_group，默认 production
--health-cache PATH      测速缓存，默认 runtime/health.json
--mihomo-api URL         Mihomo API，默认 http://127.0.0.1:9090
--health-timeout-ms N    单节点测速超时，默认 2000
--health-concurrency N   测速并发，默认 16
--port-policy PATH       Master managed 端口白名单，默认 config-src/port-policy.yaml
--port-policy-mode MODE  merge/master-only/local-only/disabled
```

废弃但兼容的参数：

```text
--live-health            兼容别名，等同 select-sync 默认 TUI
--refresh-health         废弃，不再作为推荐入口
--no-health-cache        废弃，不再作为推荐入口
```

## 8. 订阅和配置源

推荐使用 Master TUI：

```text
节点配置相关 -> 快速添加订阅 URL 并生成可用配置
```

每次输入：

```text
订阅名称
订阅 URL
```

脚本会写入 `.env.proxyfleet`，生成或更新 `config-src/`，并构建 release。
多订阅时重复执行该菜单即可。

常见配置源：

```text
config-src/base.json
config-src/providers.json
config-src/groups.json
config-src/rules.json
config-src/port-policy.yaml
```

## 9. 端口白名单

Master 公共端口白名单：

```text
config-src/port-policy.yaml
```

在 Master TUI 中进入：

```text
节点配置相关 -> 配置端口白名单
```

输入一个或多个端口号即可：

```text
7890, 7891 9090
```

`select-sync` 会默认同步这个文件。

Minion 本地 override：

```text
/etc/proxyfleet/local/port-policy.yaml
```

Master 不覆盖 Minion local override。

Salt Master 自身的 TCP `4505/4506` 要在 Master 防火墙或安全组中放行给
Minion。它们通常不需要加入下发到 Minion 的代理端口白名单。

## 10. 手动分步发布

通常不需要手动执行。排障时可在 Master 节点分步复现。

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

选择节点：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli select-node \
  releases/000001 runtime \
  --node-id <node-id>
```

发布到 Salt file_roots：

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli publish-salt \
  releases/000001 runtime/desired.yaml /srv/proxyfleet/salt/states \
  --component-locks component-locks.json
```

dry-run：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 runtime/desired.yaml /srv/proxyfleet/salt/states \
  --target '<minion-id-or-target>' \
  --dry-run
```

正式同步：

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 runtime/desired.yaml /srv/proxyfleet/salt/states \
  --target '<minion-id-or-target>'
```

## 11. 常见验证

Master 节点：

```bash
sudo salt '*' test.ping
sudo salt '*' grains.items
sudo salt '*' systemctl.status mihomo.service
sudo salt '*' state.apply proxyfleet.sync test=true
```

Minion 节点：

```bash
scripts/proxyfleet-minion.sh status
systemctl status mihomo --no-pager || true
ls -R /etc/proxyfleet || true
```
