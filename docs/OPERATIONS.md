# ProxyFleet 运维操作说明

> 本文是日常运维入口。完整安装和用户操作手册见：
>
> - `docs/INSTALL_MASTER.md`
> - `docs/INSTALL_MINION.md`
> - `docs/USER_MANUAL.md`

## 1. 节点职责

```text
Master：构建 release、接受 key、选择节点、同步配置
Minion：运行 salt-minion、接收 release、运行 Mihomo
```

日常代理节点切换、订阅刷新、规则构建都在 Master 节点执行。

## 2. Master 常用操作

在 Master 项目目录执行：

```bash
cd ~/project/ProxyFleet
```

直接运行脚本进入 Master TUI 主控台。

```bash
sudo scripts/proxyfleet-master.sh
```

TUI 主菜单分为四类：

- 安装相关：预检、安装/修复、卸载 Master；
- Master 节点相关：查看状态和 Salt key、接受 Minion key；
- 节点配置相关：订阅、自建节点、规则、release、端口白名单、节点同步；
- 服务相关：启动、停止、重启和查看 Master 服务。

下面的子命令保留给自动化和故障恢复。

服务启停：

```bash
sudo scripts/proxyfleet-master.sh start
sudo scripts/proxyfleet-master.sh stop
sudo scripts/proxyfleet-master.sh restart
scripts/proxyfleet-master.sh status
```

同步项目 Salt assets：

```bash
sudo scripts/proxyfleet-master.sh sync-assets
sudo salt '*' saltutil.sync_modules
```

卸载：

```bash
sudo scripts/proxyfleet-master.sh uninstall
```

Master 卸载会清理 Master PKI、Master 配置、Salt states/pillar 和本项目生成的
运行数据；不会重置系统路由、DNS、防火墙。

## 3. Minion 常用操作

在 Minion 脚本目录执行：

```bash
cd ~/project/proxyfleet-minion
```

直接运行脚本进入 Minion TUI 主控台。

```bash
sudo scripts/proxyfleet-minion.sh
```

TUI 覆盖 Master 地址、Minion ID、Salt Minion 安装、Mihomo 生命周期、
本机端口白名单和端口策略模式。下面的子命令保留给自动化和故障恢复。

服务启停：

```bash
sudo scripts/proxyfleet-minion.sh start
sudo scripts/proxyfleet-minion.sh stop
sudo scripts/proxyfleet-minion.sh restart
scripts/proxyfleet-minion.sh status
```

卸载：

```bash
sudo scripts/proxyfleet-minion.sh uninstall
```

### Minion Mihomo 生命周期

Minion 的 `start/stop/restart` 默认只管理 `salt-minion`。`uninstall` 是完整
卸载，会先安全停止和卸载 ProxyFleet 受管 Mihomo，再卸载 `salt-minion` 并删除
`/etc/proxyfleet`、Minion PKI 和配置。

显式联动命令：

```bash
sudo scripts/proxyfleet-minion.sh start --with-mihomo
sudo scripts/proxyfleet-minion.sh stop --with-mihomo
sudo scripts/proxyfleet-minion.sh restart --with-mihomo
```

Mihomo 专用命令：

```bash
sudo scripts/proxyfleet-minion.sh mihomo-start
sudo scripts/proxyfleet-minion.sh mihomo-stop
sudo scripts/proxyfleet-minion.sh mihomo-restart
scripts/proxyfleet-minion.sh mihomo-status
sudo scripts/proxyfleet-minion.sh mihomo-uninstall
```

安全边界：

- `mihomo-stop` 只停服务，不删配置；
- `mihomo-uninstall` 会删除 ProxyFleet 受管 unit、二进制、receipt 和 `/etc/proxyfleet`；
- 非 ProxyFleet unit 或 ownership 校验失败时，脚本跳过对应对象，不会误删；
- 卸载不会重置系统路由、DNS、防火墙或其它系统网络配置。

## 4. Salt Key 操作

在 Master 节点执行：

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

## 5. 构建和同步顺序

在 Master 节点执行。

推荐使用 TUI：

```bash
sudo scripts/proxyfleet-master.sh
```

然后进入：

```text
节点配置相关 -> 快速添加订阅 URL 并生成可用配置
节点配置相关 -> 选择节点并同步到 Minion
```

该流程会把订阅 URL 写入本地 `.env.proxyfleet`，自动生成最小可用配置并构建
release。

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

实时选择并同步：

```bash
sudo scripts/proxyfleet-master.sh select-sync
```

只同步指定 Minion：

```bash
sudo scripts/proxyfleet-master.sh select-sync \
  --target '<minion-id>'
```

## 6. `select-sync` 参数

`select-sync` 默认进入实时 TUI，并在后台动态刷新节点延迟。`--live-health`
只作为兼容别名保留。

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
--port-policy PATH       Master managed 端口白名单，默认 config-src/port-policy.yaml
--port-policy-mode MODE  merge/master-only/local-only/disabled
```

废弃参数：

```text
--live-health            兼容别名，等同 select-sync 默认 TUI
--refresh-health         废弃，不再作为推荐入口
--no-health-cache        废弃，不再作为推荐入口
```

## 7. TUI 操作

```bash
sudo scripts/proxyfleet-master.sh select-sync
```

进入后顶部必须显示当前选中的节点。没有选择时显示：

```text
当前选择：无
```

按键：

```text
↑/↓ 或 j/k    移动
Enter         选择并同步
/             搜索
r             重新测速
s             按延迟排序
n             恢复原始序号
q             退出
```

TUI 调用 Master 本机 `http://127.0.0.1:9090` 的 Mihomo API。
测速结果代表 Master 本机网络视角，不代表每台 Minion 的本机出口质量。
延迟信息由后台 worker 动态刷新；列表序号在一次会话内保持稳定。

## 8. 手动分步同步

选择节点：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli select-node \
  releases/000001 runtime \
  --node-id <node-id>
```

发布：

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

## 9. 端口白名单

Master managed 端口白名单默认文件：

```text
config-src/port-policy.yaml
```

TUI 里选择“节点配置相关 → 配置端口白名单”，输入一个或多个端口号即可自动
写入该文件。多个端口可用空格或逗号分隔，例如：

```text
7890, 7891 9090
```

当前端口策略文件使用 JSON 语法，保存为 `.yaml` 扩展名时仍是合法 YAML 子集。
示例：

```json
{
  "allow": [
    {
      "port": 7890,
      "protocol": "tcp",
      "source": "192.168.1.0/24"
    }
  ],
  "deny": [],
  "owner": "master",
  "schema_version": "1.0"
}
```

`*.yaml` 默认被 `.gitignore` 排除，不会误提交到仓库。执行 `select-sync` 时，
如果该文件存在，默认按 `merge` 模式一起同步；如果不存在，则显示
`端口白名单：未配置`。

Salt Master 自身需要让 Minion 访问 TCP `4505` 和 `4506`。如果你配置的是
Master 机器的入站防火墙，这两个端口必须放行给 Minion；如果配置的是
ProxyFleet 下发到 Minion 的端口白名单，通常不需要把 `4505/4506` 加进去。

手动发布 managed 端口白名单：

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli publish-salt \
  releases/000001 runtime/desired.yaml /srv/proxyfleet/salt/states \
  --component-locks component-locks.json \
  --port-policy config-src/port-policy.yaml \
  --port-policy-mode merge
```

Minion 本地 override：

```text
/etc/proxyfleet/local/port-policy.yaml
```

Salt state 只确保 `/etc/proxyfleet/local` 存在，不覆盖、不删除本机 override。

## 10. 常见验证

在 Master 节点执行：

```bash
sudo salt '*' test.ping
sudo salt '*' grains.items
sudo salt '*' systemctl.status mihomo.service
sudo salt '*' state.apply proxyfleet.sync test=true
```

在 Minion 节点执行：

```bash
scripts/proxyfleet-minion.sh status
systemctl status mihomo --no-pager || true
ls -R /etc/proxyfleet || true
```
