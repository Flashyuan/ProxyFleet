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

检测并更新 Master：

```bash
sudo scripts/proxyfleet-master.sh check-update
sudo scripts/proxyfleet-master.sh update
```

TUI 入口：

```text
安装相关 -> 检测并更新 ProxyFleet Master
```

健康监控和邮件告警：

```bash
sudo scripts/proxyfleet-master.sh monitor init
sudo scripts/proxyfleet-master.sh monitor status
sudo scripts/proxyfleet-master.sh monitor auto-switch true
sudo scripts/proxyfleet-master.sh monitor auto-switch false
sudo scripts/proxyfleet-master.sh monitor validate-candidates
sudo scripts/proxyfleet-master.sh monitor once --dry-run
sudo scripts/proxyfleet-master.sh monitor once
```

TUI 入口：

```text
节点配置相关 -> 配置节点健康监控和邮件告警
```

默认路径：

```text
策略：runtime/health-monitor-policy.json
状态：runtime/health-monitor-state.json
邮件配置：/etc/proxyfleet/notify/email.json
SMTP 授权码：/etc/proxyfleet/secrets/smtp-password
```

健康监控默认 10 分钟检测一次。连续多轮低分后先给多个管理员邮箱发告警，
等待 10 分钟人工处理；自动切换默认关闭，启用后仍受节点名称黑名单、冷却期
和每小时/每日次数限制。

`monitor validate-candidates` 会按自动切换优先级临时切换 Master 本机 Mihomo
节点，验证候选节点的 delay、出口 IP、Google、ChatGPT 可达性，完成后恢复当前
节点，并把可用候选写入 `runtime/health-monitor-state.json`。自动切换前会优先
使用这批未过期的可用候选；没有可用候选时不会自动切换。

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

检测并更新 Minion 脚本：

```bash
sudo scripts/proxyfleet-minion.sh check-update
sudo scripts/proxyfleet-minion.sh update
```

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
会自动升级为一次 `full-converge` 发布和同步；用户不需要每次手动追加
`--full-converge`。基线补齐后，后续日常切换会回到智能分流轻量路径。

默认 `tproxy` 会把透明代理运行参数写入新构建的 release，并在同步切换时作为
Salt plan 记录。只有排障时建议临时切到 `explicit-proxy`。

资源占用优化行为：

- TUI 先显示节点列表，再按当前选择、当前页和搜索结果优先后台测速；
- 默认测速并发为 8，避免进入 TUI 时压高 Master 本机 Mihomo；
- 日常切换默认走智能分流：旧 Minion 只通过 Mihomo API 切换节点，新 Minion
  或组件漂移 Minion 才走完整 `state.apply`；
- 如果 Salt file_roots 缺 release、组件锁、组件资产 marker 或 hash 不一致，会
  自动执行一次 `full-converge` 发布和同步；
- 所有 Minion 仍最终同步成同一个节点；默认不启用 Salt batch，而是由
  ProxyFleet 按 `--concurrency` 做应用层小批量同步；
- Salt 输出默认精简，完整输出写入 `--log-dir`，日志目录权限为 `0700`，文件为
  `0600`，并做敏感信息脱敏；
- 仅当远端 Minion 回报的 `proxyfleet_mihomo` module SHA-256 与 Master 当前模块
  一致时，才跳过 `saltutil.sync_modules`；旧模块或不一致会自动同步。

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

当前版本不会默认写入 SSH `22` 或 Salt `4505/4506`。如确实要把 SSH 端口作为
Minion 本机代理端口策略的一部分，请在 TUI 中手动输入 `22`，或写入
`/etc/proxyfleet/local/port-policy.yaml`。

## 9.1 Mihomo 镜像和离线包

推荐入口：

```bash
sudo scripts/proxyfleet-master.sh asset-mirror-deploy
```

或在 Master TUI 中进入：

```text
安装相关 -> 一键部署 Salt/Mihomo 固定组件镜像
```

服务地址：

```text
http://<Master-IP>:48080/proxyfleet/
```

Minion 安装时默认优先从该地址获取 Salt `3008.1` deb 包，并校验
`bootstrap-manifest.json` 中的 SHA-256。镜像不可用时才回退官方 Salt 源。

Master 会在 `publish-salt` 时把 `component-locks.json` 同目录下的
`component-assets/`、`assets/`、`offline-assets/` 发布到 Salt 的
`proxyfleet/assets/`。Minion 同步后会优先使用 `/etc/proxyfleet/assets/`
中的离线包，再尝试 artifact 的 `mirror_urls`，最后才访问原始 `url`。

所有来源都必须匹配 `component-locks.json` 中对应架构的 SHA-256。

设计说明：组件资产发布最初用于保证新 Minion 第一次同步时即使没有外网，也能
安装固定版本 Mihomo。日常切换节点通常只改变 `desired.yaml`，当前版本默认避免
每次 `select-sync` 都重新发布不变的 Mihomo 离线包。完整资产发布保留给新 Minion、
组件版本变化、接管修复、漂移恢复和显式 `--full-converge` 场景。

## 9.2 接管已有 ShellCrash/Mihomo

在 Minion 上执行：

```bash
sudo scripts/proxyfleet-minion.sh takeover-mihomo
```

该命令只备份、停止并禁用旧服务，不删除 ShellCrash 数据。随后在 Master 上执行
`select-sync`，由 Salt 安装和接管 ProxyFleet 受管 Mihomo。

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
