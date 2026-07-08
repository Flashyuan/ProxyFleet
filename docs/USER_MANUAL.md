# ProxyFleet 用户使用手册

本文按真实操作顺序说明：在哪个节点执行什么命令，以及常用参数代表什么。

## 1. 最短路径

```text
Master 节点：curl 下载完整项目
Master 节点：安装 Salt Master
Minion 节点：curl 下载 minion 脚本
Minion 节点：安装 Salt Minion
Master 节点：核验并接受 Minion key
Master 节点：输入订阅名称和订阅 URL
Master 节点：选择代理节点并同步到 Minion
```

脚本无参数运行时会进入 TUI：

```bash
sudo scripts/proxyfleet-master.sh
sudo scripts/proxyfleet-minion.sh
```

也可以配置全局命令。推荐使用 wrapper，不要直接软链接脚本：

```bash
sudo tee /usr/local/bin/pfmaster >/dev/null <<'EOF'
#!/usr/bin/env bash
export PROJECT_ROOT=/home/ubuntu/project/ProxyFleet
exec /home/ubuntu/project/ProxyFleet/scripts/proxyfleet-master.sh "$@"
EOF

sudo chmod +x /usr/local/bin/pfmaster
```

Minion：

```bash
sudo tee /usr/local/bin/pfminion >/dev/null <<'EOF'
#!/usr/bin/env bash
export PROJECT_ROOT=/home/ubuntu/project/proxyfleet-minion
exec /home/ubuntu/project/proxyfleet-minion/scripts/proxyfleet-minion.sh "$@"
EOF

sudo chmod +x /usr/local/bin/pfminion
```

如果项目目录不是 `/home/ubuntu/project/...`，请替换成真实路径。wrapper 会固定
`PROJECT_ROOT`，避免从 `/usr/local/bin` 启动时找不到 release。

## 2. Master 节点安装

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

Master 机器需要允许 Minion 访问：

```text
TCP 4505
TCP 4506
```

## 3. Minion 节点安装

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

参数说明：

```text
--master / --master-ip     Master IP 或 DNS
--id                       Minion 唯一 ID，Master 接受 key 时使用
--environment              默认 production
--driver                   默认 native-mihomo
--release-channel          默认 stable
```

## 4. Master 接受 Minion Key

回到 Master 节点执行：

```bash
sudo salt-key -L
sudo salt-key -F
sudo salt-key -a <minion-id>
sudo salt '<minion-id>' test.ping
```

必须先核验 fingerprint，再接受 key。

如果 Master 看不到 key，先在 Minion 上确认：

```bash
timeout 3 bash -c '</dev/tcp/<master-ip>/4505' && echo 4505-ok
timeout 3 bash -c '</dev/tcp/<master-ip>/4506' && echo 4506-ok
sudo systemctl restart salt-minion
```

注意把 `<master-ip>` 换成真实 IP。

## 5. 用 TUI 配置订阅并生成可用配置

在 Master 节点执行：

```bash
cd ~/project/ProxyFleet
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

脚本会自动：

- 保存订阅 URL 到本地 `.env.proxyfleet`；
- 生成或更新 `config-src/base.json`；
- 生成或更新 `config-src/providers.json`；
- 生成或更新 `config-src/groups.json`；
- 生成或更新 `config-src/rules.json`；
- 拉取订阅并提取可用节点；
- 构建 release。

多订阅时重复执行这个菜单即可。

## 6. 导入自建节点和自定义规则

在 Master TUI 中进入：

```text
节点配置相关 -> 导入自建节点文件
节点配置相关 -> 导入自定义规则文件
```

你可以提供：

```text
订阅 URL
自建节点 yaml 文件
自定义规则 yaml 文件
```

订阅返回完整配置时，构建器会自动提取顶层 `proxies`。最终策略组和规则由
Master 本地 `groups.json`、`rules.json` 统一生成。

## 7. 配置端口白名单

在 Master TUI 中进入：

```text
节点配置相关 -> 配置端口白名单
```

直接输入端口号。多个端口可用空格或逗号分隔：

```text
7890, 7891 9090
```

Master 会写入：

```text
config-src/port-policy.yaml
```

`select-sync` 会默认同步该文件。

Minion 本地 override 文件：

```text
/etc/proxyfleet/local/port-policy.yaml
```

Master 不覆盖这个 local 文件。完整卸载 Minion 时，它会随 `/etc/proxyfleet`
一起删除。

Salt Master 自身需要开放 TCP `4505/4506` 给 Minion，这是 Master 防火墙或云安全组
配置，不是通常意义上的 Mihomo 代理端口白名单。

## 8. 选择节点并同步

在 Master 节点执行：

```bash
sudo scripts/proxyfleet-master.sh select-sync
```

如果已配置全局命令，也可以执行：

```bash
sudo pfmaster select-sync
```

`select-sync` 默认进入实时 TUI，顶部会显示当前已选择节点。没有选择时显示：

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

只同步某个 Minion：

```bash
sudo scripts/proxyfleet-master.sh select-sync --target '<minion-id>'
```

资源优化行为：

- TUI 进入后先显示节点列表，优先测速当前选择、当前页和搜索结果；
- 日常切换节点时只发布 changed desired 和必要元数据，不重复发布不变的 Mihomo
  固定资产；
- 所有 Minion 仍最终同步成同一个节点，但 Salt 会支持分批执行，降低 Master
  瞬时 CPU、内存和输出压力；
- 终端默认显示精简进度和结果，完整 Salt 输出写入日志文件，方便排障。

## 9. Master 命令速查

```text
preflight                     只读检查 Master 运行环境
install                       安装 Salt Master 3008.1
start                         启动 salt-master
stop                          停止 salt-master
restart                       重启 salt-master
status                        查看 salt-master 和 salt-key 状态
sync-assets                   同步 Salt module/state 到 file_roots
refresh-health                刷新 Master 本机 Mihomo API 测速缓存
select-sync                   进入实时 TUI 选择节点并同步
monitor init                  初始化默认健康监控策略
monitor status                查看健康监控策略、状态和邮件配置状态
monitor auto-switch true|false
                              显式启用或关闭自动切换
monitor validate-candidates   预验证自动切换候选节点并缓存可用节点
monitor once [--dry-run]      执行一轮健康检查；dry-run 不发邮件、不切换
check-update                  检测 ProxyFleet Master 新版本
update [--yes]                应用 ProxyFleet Master 更新
uninstall [--yes]             完整卸载 Master 受管数据和组件
uninstall --purge-data [--yes] 兼容旧参数；行为等同 uninstall
```

Master 服务：

```bash
sudo scripts/proxyfleet-master.sh start
sudo scripts/proxyfleet-master.sh stop
sudo scripts/proxyfleet-master.sh restart
scripts/proxyfleet-master.sh status
```

Master 更新：

```bash
sudo scripts/proxyfleet-master.sh check-update
sudo scripts/proxyfleet-master.sh update
```

Master 健康监控：

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

邮件告警在 TUI 中配置发件 SMTP 和多个收件人。SMTP 授权码默认写入：

```text
/etc/proxyfleet/secrets/smtp-password
```

邮件配置默认写入：

```text
/etc/proxyfleet/notify/email.json
```

授权码文件权限会设置为 `0600`。健康监控默认 10 分钟检测一次，自动切换默认关闭；
进入等待人工处理窗口后默认 10 分钟内不会自动切换。

自动切换前会先使用 `monitor validate-candidates` 生成的未过期可用候选缓存。
如果没有缓存，`monitor once` 在自动切换前会先临时切换 Master 本机 Mihomo
逐个验证候选节点；验证不通过的候选不会被自动切换选中。

同一份邮件配置也会用于手动切换节点成功通知。通过 `select-sync` 或 TUI
“选择节点并同步到 Minion”完成同步后，Master 会向多个管理员收件人发送邮件。
该通知只依赖 Master 侧配置，Minion 不需要为此功能单独更新。

## 10. `select-sync` 参数说明

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

普通使用不需要传 `--proxy-mode`。默认 `tproxy` 会让 Minion 上的命令行程序优先
通过 Mihomo 当前选中节点访问公网；`explicit-proxy` 仅用于临时回退到手动代理端口。

废弃但兼容：

```text
--live-health            兼容别名，等同 select-sync 默认 TUI
--refresh-health         废弃，不再作为推荐入口
--no-health-cache        废弃，不再作为推荐入口
```

## 11. Minion 命令速查

```text
preflight                       只读检查 Minion 运行环境
install/bootstrap               安装 Salt Minion 并写入 Master/ID/grains
start                           启动 salt-minion
start --with-mihomo             启动 salt-minion 后安全启动 Mihomo
stop                            停止 salt-minion
stop --with-mihomo              安全停止 Mihomo 后停止 salt-minion
restart                         重启 salt-minion
restart --with-mihomo           同时重启 salt-minion 和 Mihomo
status                          查看 salt-minion 状态
check-update                    检测 ProxyFleet Minion 脚本新版本
update [--yes]                  应用 ProxyFleet Minion 脚本更新
uninstall [--yes]               完整卸载 Minion、受管 Mihomo 和本项目数据
uninstall --purge-data [--yes]  兼容旧参数；行为等同 uninstall
mihomo-start                    只启动本机 Mihomo
mihomo-stop                     只停止本机 Mihomo
mihomo-restart                  只重启本机 Mihomo
mihomo-status                   查看 Mihomo 状态
mihomo-uninstall [--yes]        完整卸载 ProxyFleet 受管 Mihomo
takeover-mihomo [--yes]         备份并停止已有 ShellCrash/Mihomo，准备交给 ProxyFleet 接管
```

Minion 服务：

```bash
sudo scripts/proxyfleet-minion.sh start
sudo scripts/proxyfleet-minion.sh stop
sudo scripts/proxyfleet-minion.sh restart
scripts/proxyfleet-minion.sh status
```

Minion 更新：

```bash
sudo scripts/proxyfleet-minion.sh check-update
sudo scripts/proxyfleet-minion.sh update
```

Mihomo 服务：

```bash
sudo scripts/proxyfleet-minion.sh mihomo-start
sudo scripts/proxyfleet-minion.sh mihomo-stop
sudo scripts/proxyfleet-minion.sh mihomo-restart
scripts/proxyfleet-minion.sh mihomo-status
```

已有 ShellCrash/Mihomo：

```bash
sudo scripts/proxyfleet-minion.sh takeover-mihomo
```

该命令只备份、停止并禁用旧服务，不删除 ShellCrash 数据。接管准备完成后，在
Master 执行 `select-sync`，由 Salt 下发 ProxyFleet 受管 Mihomo。

Mihomo 离线资产：

Master 一键部署固定组件镜像：

```bash
sudo scripts/proxyfleet-master.sh asset-mirror-deploy
sudo scripts/proxyfleet-master.sh asset-mirror-status
```

TUI 路径：

```text
安装相关 -> 一键部署 Salt/Mihomo 固定组件镜像
```

默认服务地址：

```text
http://<Master-IP>:48080/proxyfleet/
```

Minion 安装时会默认优先从 Master 的 `48080` 获取 Salt 固定版本安装包，不需要
额外参数。Mihomo 固定资产会在 Master 构建/同步后通过 Salt assets 下发。

```text
component-assets/
assets/
offline-assets/
```

把锁定版本的 `.gz` 包放到以上任一目录，或在 `component-locks.json` 的 artifact
中配置 `local_path` / `mirror_urls`。同步时 Master 会发布到 Salt assets，Minion
安装时仍按 SHA-256 校验后才使用。

说明：这些资产主要服务于新 Minion、离线安装、组件升级和接管修复。日常切换
默认不会重复发布不变的大文件；缺少安全基线时会提示执行 `--full-converge`。

日常切换时，Master 会先让 Minion 自检当前状态：

- 旧 Minion：组件锁、release、systemd 和 Mihomo 均正常时，只调用 Mihomo API
  切换当前节点，不重装组件；
- 新 Minion 或漂移 Minion：缺少组件、release、锁文件或受管服务时，自动走
  完整 `state.apply`；
- 离线 Minion：本轮跳过并记录到结果里，不阻断其他在线 Minion。

如需提前查看这次会怎么分流，可执行：

```bash
sudo scripts/proxyfleet-master.sh select-sync --plan
```

`--plan` 会使用临时 Salt root 生成计划输入，不会修改生产
`/srv/proxyfleet/salt/states`，也不会执行 `saltutil.sync_modules` 或
`state.apply`。

## 12. 卸载

Master 节点：

```bash
sudo scripts/proxyfleet-master.sh uninstall
```

会清理 Master 本机 Salt Master、Master PKI、Salt states/pillar 和项目运行数据。

Minion 节点：

```bash
sudo scripts/proxyfleet-minion.sh uninstall
```

会清理 `salt-minion`、ProxyFleet 受管 Mihomo、`/etc/proxyfleet`、Minion PKI 和
配置。

卸载不会重置系统路由、DNS、防火墙或其它系统网络配置。

## 13. 常见验证

在 Master 节点：

```bash
sudo salt '*' test.ping
sudo salt '*' grains.items
sudo salt '*' systemctl.status mihomo.service
sudo salt '*' state.apply proxyfleet.sync test=true
```

在 Minion 节点：

```bash
scripts/proxyfleet-minion.sh status
systemctl status mihomo --no-pager || true
ls -R /etc/proxyfleet || true
```
