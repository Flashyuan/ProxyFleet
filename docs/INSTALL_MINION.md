# Minion 节点安装、配置与命令说明

本文只描述 Minion 节点。Minion 负责运行 Salt Minion，等待 Master 下发
release、安装并运行 ProxyFleet 受管 Mihomo、应用代理节点选择。

## 1. Minion 节点职责

Minion 负责：

- 运行 Salt Minion `3008.1`；
- 主动连接 Master；
- 等待 Master 人工接受 key；
- 接收 Master 下发的 release 和 desired state；
- 由 Salt state 安装固定版本 Mihomo；
- 应用 Master 选择的 `FLEET_PROXY` 节点。

Minion 不需要 Git 仓库，也不需要完整项目。通常只下载
`scripts/proxyfleet-minion.sh`。

## 2. 前置条件

- Ubuntu 22.04 或 24.04；
- 当前用户具备 sudo 权限；
- Minion 可以访问 Master TCP `4505` 和 `4506`；
- 推荐 Minion 可以访问 Master TCP `48080`，用于优先获取固定 Salt/Mihomo 组件镜像；
- 已规划唯一 Minion ID；
- Master 不自动接受 key，必须人工核验 fingerprint；
- Salt 组件固定安装 `3008.1`，安装后会被 `apt-mark hold` 锁定。

Minion 上检查 Master 端口：

```bash
timeout 3 bash -c '</dev/tcp/<master-ip>/4505' && echo 4505-ok
timeout 3 bash -c '</dev/tcp/<master-ip>/4506' && echo 4506-ok
```

注意把 `<master-ip>` 替换成真实 IP，不要带尖括号。

如果 Master 已经部署固定组件镜像，Minion 安装 Salt 时会默认访问：

```text
http://<master-ip>:48080/proxyfleet/
```

不需要额外传参数。脚本会下载 `bootstrap-manifest.json`，校验 Salt deb 的
SHA-256，然后安装固定版本 Salt `3008.1`。如果 Master 镜像不可达或校验失败，
才会回退官方 Salt 源。

## 3. 用 curl 下载 Minion 脚本

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
```

后续更新脚本时，重复执行上面的 `curl -o scripts/proxyfleet-minion.sh` 即可。

## 4. 安装 Minion

推荐先预检，再安装：

```bash
cd ~/project/proxyfleet-minion
scripts/proxyfleet-minion.sh preflight

sudo scripts/proxyfleet-minion.sh install \
  --master <master-ip-or-dns> \
  --id <minion-id> \
  --environment production \
  --driver native-mihomo \
  --release-channel stable
```

兼容旧参数：

```bash
sudo scripts/proxyfleet-minion.sh install \
  --master-ip <master-ip> \
  --id <minion-id>
```

安装会写入：

```text
/etc/apt/keyrings/salt-archive-keyring.pgp
/etc/apt/sources.list.d/salt.sources
/etc/apt/preferences.d/proxyfleet-salt-pin
/etc/salt/minion.d/proxyfleet.conf
```

安装后脚本会输出本机 fingerprint，并提示回到 Master 接受 key。

## 5. Minion TUI 主控台

无参数运行脚本会进入 Minion TUI：

```bash
sudo scripts/proxyfleet-minion.sh
```

TUI 可完成：

- Salt Minion 安装；
- ProxyFleet Minion 脚本检测更新和确认后更新；
- Master 地址和 Minion ID 配置；
- Salt Minion 启动、停止、重启；
- ProxyFleet 受管 Mihomo 启动、停止、重启和卸载；
- 本机端口白名单 override 配置；
- 完整卸载 Minion。

日常安装和配置推荐使用 TUI。下面的子命令主要用于自动化、排障和文档复现。

## 6. 回到 Master 接受 Key

这一步在 Master 节点执行，不是在 Minion 上执行：

```bash
sudo salt-key -L
sudo salt-key -F
sudo salt-key -a <minion-id>
sudo salt '<minion-id>' test.ping
```

如果 Master 看不到 unaccepted key：

1. 确认 Minion 安装命令里的 `--master` 是真实 Master IP 或 DNS；
2. 在 Minion 上确认能访问 Master `4505/4506`；
3. 在 Minion 上执行 `sudo systemctl restart salt-minion`；
4. 在 Master 上确认 `salt-master` 正在监听 `4505/4506`。

## 7. Minion 脚本命令

```text
scripts/proxyfleet-minion.sh <command> [options]
```

常用命令：

```text
preflight                       只读检查 OS、systemd、sudo 和 Salt 目标版本
install/bootstrap               安装 Salt Minion 3008.1，并写入 Master/ID/grains
start                           启动 salt-minion
start --with-mihomo             启动 salt-minion 后安全启动 Mihomo
stop                            停止 salt-minion
stop --with-mihomo              安全停止 Mihomo 后停止 salt-minion
restart                         重启 salt-minion
restart --with-mihomo           同时按安全流程重启 salt-minion 和 Mihomo
status                          查看 salt-minion 状态
check-update                    检测 ProxyFleet Minion 脚本新版本
update [--yes]                  应用 ProxyFleet Minion 脚本更新
uninstall [--yes]               完整卸载 Minion、受管 Mihomo 和本项目数据
uninstall --purge-data [--yes]  兼容旧参数；行为等同 uninstall
mihomo-start                    只安全启动本机 Mihomo
mihomo-stop                     只停止本机 Mihomo，保留配置和 release
mihomo-restart                  只重启本机 Mihomo
mihomo-status                   查看 Mihomo 受管状态
mihomo-uninstall [--yes]        完整卸载 ProxyFleet 受管 Mihomo
takeover-mihomo [--yes]         安全接管已有 ShellCrash/Mihomo
```

安装参数：

```text
--master / --master-ip     Master IP 或 DNS
--id                       Minion 唯一 ID，Master 接受 key 时使用
--environment              默认 production
--driver                   默认 native-mihomo
--release-channel          默认 stable
```

旧 Mihomo 卸载参数仍兼容，但不再改变当前完整卸载语义：

```text
--purge-managed
--purge-all
--purge-local-override
--with-mihomo
```

## 8. 检测并更新 Minion 脚本

推荐在 Minion TUI 中选择：

```text
检测并更新 ProxyFleet Minion
```

非交互命令：

```bash
sudo scripts/proxyfleet-minion.sh check-update
sudo scripts/proxyfleet-minion.sh update
sudo scripts/proxyfleet-minion.sh update --yes
```

`check-update` 只读。`update` 默认仍会询问确认；`--yes` 用于自动化，但不会跳过
manifest、SHA-256、路径 allowlist/denylist、备份、语法检查和回滚。

Minion 更新默认只允许覆盖 `scripts/proxyfleet-minion.sh` 和
`/etc/proxyfleet/local/update-state.json`。不会覆盖 `/etc/salt`、`/etc/proxyfleet`
中的 current/managed/effective、local override、Mihomo 二进制、Mihomo systemd
unit、release 或运行数据。

更新不会自动启动、停止、重启或卸载 Mihomo。只有旧版单脚本且没有 `src/` 的
Minion，也可以使用内置轻量 fallback 更新 `scripts/proxyfleet-minion.sh`。

## 8.1 安全接管已有 ShellCrash/Mihomo

如果这台机器已经运行 ShellCrash 或非 ProxyFleet 管理的 Mihomo，先执行：

```bash
sudo scripts/proxyfleet-minion.sh takeover-mihomo
```

确认后脚本会：

1. 备份已发现的 `mihomo.service`、`clash.service`、`shellcrash.service` 等 unit；
2. 停止并禁用这些旧服务；
3. 记录 `/etc/proxyfleet/local/takeover.json`；
4. 保留 ShellCrash 原始目录，不删除数据；
5. 不修改系统路由、DNS、防火墙。

接管完成后，回到 Master 执行 `select-sync`。下一次 Salt 同步会安装
ProxyFleet 受管 Mihomo，并应用 Master 生成的 `config.yaml`。

## 9. Mihomo 生命周期

`start`、`stop`、`restart` 默认只控制 `salt-minion`。

需要同时控制 Mihomo 时使用：

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

完整卸载 Mihomo：

```bash
sudo scripts/proxyfleet-minion.sh mihomo-uninstall
```

脚本只处理 ProxyFleet 明确受管的 Mihomo unit、二进制、receipt 和
`/etc/proxyfleet`。如果 unit 不属于 ProxyFleet、路径不匹配或来源无法确认，
脚本会跳过对应对象，不猜测删除范围。

## 10. 完整卸载 Minion

在 Minion 节点执行：

```bash
sudo scripts/proxyfleet-minion.sh uninstall
```

Minion 完整卸载会：

- 停止 ProxyFleet 受管 Mihomo；
- 删除 ProxyFleet 受管 Mihomo unit、二进制和 receipt；
- 删除 `/etc/proxyfleet`；
- 停止并卸载 `salt-minion`；
- 删除 Minion PKI 和 Salt Minion 配置。

卸载不会重置系统路由、DNS、防火墙或其它系统网络配置。

## 11. 被 Master 管控后的操作边界

Minion 安装完成并被 Master 接受 key 后，日常代理配置不要在 Minion 本机手动改。

代理源、节点选择、规则和公共端口白名单都在 Master 上配置，然后由 Master 执行：

```bash
sudo scripts/proxyfleet-master.sh select-sync
```

Master 会通过 Salt 下发：

- Mihomo 固定版本资产；
- release 配置；
- desired state；
- `FLEET_PROXY` 当前选择；
- Master managed 端口白名单。

Minion 本机只保留 local override：

```text
/etc/proxyfleet/local/port-policy.yaml
```

该文件不会被 Master 覆盖。完整卸载 Minion 时，该文件会随 `/etc/proxyfleet`
一起删除。

## 12. 常见验证

在 Minion 节点执行：

```bash
scripts/proxyfleet-minion.sh status
systemctl status mihomo --no-pager || true
ls -R /etc/proxyfleet || true
```

在 Master 节点执行：

```bash
sudo salt '<minion-id>' test.ping
sudo salt '<minion-id>' systemctl.status mihomo.service
sudo salt '<minion-id>' state.apply proxyfleet.sync test=true
```
