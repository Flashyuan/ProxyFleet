# Master TUI 使用引导

本文给 Master 节点管理员使用。优先说明如何切换代理节点并同步给所有 Minion。

## 1. 切换节点并同步所有 Minion

在 Master 节点进入项目目录：

```bash
cd ~/project/ProxyFleet
sudo scripts/proxyfleet-master.sh
```

如果已配置全局命令：

```bash
sudo pfmaster
```

进入菜单：

```text
节点配置相关 -> 选择节点并同步到 Minion
```

进入实时节点选择界面后：

```text
↑/↓ 或 j/k    移动高亮节点
/             搜索节点名称
r             重新测速
s             按延迟排序
n             恢复原始序号
Enter         选择当前高亮节点并同步
q             退出，不切换
```

确认选择后，Master 会执行：

```text
写入 runtime/desired.yaml
校验 Salt file_roots 中已有 release、组件锁和组件资产基线
轻量发布 desired state 和端口白名单
必要时同步 Salt assets 和 execution module
读取各 Minion 的当前受管状态并分类
旧 Minion 只调用 Mihomo API 切换 FLEET_PROXY
新 Minion 或漂移 Minion 才执行 state.apply proxyfleet.sync
无法安全分类的 Minion 标记为 unknown/defer，不拖累在线节点
如已配置邮件告警，向管理员发送手动切换成功通知
```

第一次同步新 Minion 时会安装 Mihomo，耗时会比普通切换更长。节点列表里显示
`failed` 不一定代表订阅节点坏了；如果 Master 本机还没有 Mihomo，Master 本机测速
会失败，但仍可以选择节点并由 Minion 执行同步。

性能优化行为：

- TUI 测速优先当前已选节点、当前页和搜索结果，非可见节点低优先级后台刷新；
- 默认测速并发为 8，避免进入 TUI 时压高 Master 本机 Mihomo 资源；
- 日常切换节点与完整组件收敛拆开，普通切换不重复发布不变的 Mihomo 离线资产；
- Salt file_roots 缺少完整基线时，TUI 会提示显式执行 `select-sync --full-converge`，
  不会自动对全目标完整收敛；
- 某台 Minion 分类失败时只标记 `unknown/defer`，已分类的在线 Minion 继续按
  `switch-only` 或 `full-converge` 执行；
- TUI 默认使用 `releases` 下最大编号的最新 release，不再固定同步
  `releases/000001`；
- 默认不启用 Salt batch，改由 ProxyFleet 按较小并发分组，避免 Master 瞬时
  fork 和事件处理压力过高；
- 同步所有 Minion 时默认 batch 分批，最终仍保证目标 Minion 都收敛到同一个节点；
- Salt 输出摘要优先，完整 highstate 输出写入权限受限日志文件。
- 默认 `tproxy` release 会关闭 DNS fallback GeoIP 过滤，避免 Minion 启动时因
  MMDB 在线下载超时导致 Mihomo 无法监听 9090/7890/7893；
- 默认 `tproxy` 会保护 Docker/K8s/CNI 内部网络，支持通过
  `config-src/tproxy-excludes.json` 或 `config-src/tproxy-excludes.yaml` 追加
  Pod CIDR、Service CIDR、bridge 和企业内网。

如果同步失败并提示：

```text
No matching sls found for 'proxyfleet.sync'
```

在 Master 上执行：

```bash
sudo pfmaster sync-assets
sudo systemctl restart salt-master
sudo salt-run fileserver.clear_file_list_cache
sudo salt-run fileserver.file_list saltenv=base | grep proxyfleet/sync.sls
```

如果提示已有 `state.apply` 在运行：

```text
The function "state.apply" is running as PID ...
```

说明上一次同步还没结束。先检查：

```bash
sudo salt '*' saltutil.running
```

确认卡住后再终止对应 job：

```bash
sudo salt '<minion-id>' saltutil.kill_job <jid>
sudo systemctl restart salt-minion
```

## 2. 第一次配置订阅

进入：

```text
节点配置相关 -> 快速添加订阅 URL 并生成可用配置
```

按提示输入：

```text
订阅名称
订阅 URL
```

TUI 会自动生成基础配置、拉取订阅、提取节点并构建 release。

多订阅时重复执行这个入口即可。

## 3. 接受 Minion Key

进入：

```text
Master 节点相关 -> 核验并接受 Minion key
```

操作前先核验 fingerprint。非交互命令：

```bash
sudo salt-key -F
sudo salt-key -L
sudo salt-key -a <minion-id>
sudo salt '<minion-id>' test.ping
```

## 4. 配置端口白名单

进入：

```text
节点配置相关 -> 配置端口白名单
```

直接输入一个或多个端口：

```text
7890, 7891 9090
```

TUI 会写入：

```text
config-src/port-policy.yaml
```

`select-sync` 时会默认同步该文件。Salt Master 的 `4505/4506` 是 Master 防火墙或
云安全组配置，不属于通常意义上的 Mihomo 代理端口白名单。

## 5. 配置健康监控和邮件告警

进入：

```text
节点配置相关 -> 配置节点健康监控和邮件告警
```

常用操作：

```text
初始化/修复默认健康监控策略
配置邮件告警发件人和收件人
查看健康监控状态
启用自动切换
关闭自动切换
执行一次健康检查 dry-run
预验证自动切换候选节点并缓存可用节点
```

默认策略：

```text
每 10 分钟检测一次
自动切换默认关闭
节点疑似失效后先邮件告警
等待 10 分钟人工处理
自动切换受香港/台湾黑名单和限频保护
自动切换前必须有未过期的可用候选验证结果
```

SMTP 授权码默认写入：

```text
/etc/proxyfleet/secrets/smtp-password
```

邮件配置默认写入：

```text
/etc/proxyfleet/notify/email.json
```

同一份邮件配置也用于“手动切换节点并同步成功”通知。也就是说，管理员通过
`选择节点并同步到 Minion` 成功切换节点后，Master 会给配置好的收件人发送通知。
如果没有配置邮件，手动切换不会被阻断，只是跳过邮件通知。

## 6. 检测和应用 ProxyFleet 更新

进入：

```text
安装相关 -> 检测并更新 ProxyFleet Master
```

更新不会覆盖订阅 URL、节点配置、release、runtime、Salt PKI 或 Minion key。

非交互命令：

```bash
sudo pfmaster check-update
sudo pfmaster update
```

## 7. 服务操作

进入：

```text
服务相关 -> 启动/停止/重启 Master 服务
```

非交互命令：

```bash
sudo pfmaster start
sudo pfmaster stop
sudo pfmaster restart
pfmaster status
```
