# Minion 节点安装、配置与常用命令

> 适用：Ubuntu 22.04/24.04 原生 systemd Minion。Minion 负责运行 Salt Minion，
> 等待 Master 下发 release、安装 Mihomo、应用配置和切换 `FLEET_PROXY`。

## 1. Minion 节点职责

Minion 节点执行：

- 安装并运行 Salt Minion 3008.1；
- 主动连接 Master；
- 等待 Master 人工接受 key；
- 接收 Master 下发的 Mihomo release 和 desired state；
- 由 Salt state 安装/更新 Mihomo 并应用节点选择。

Minion 不需要 Git 仓库，也不需要完整项目文件。一般只需要下载
`scripts/proxyfleet-minion.sh`。

## 2. 前置条件

- 当前机器为 Ubuntu 22.04/24.04；
- 当前用户具备 sudo 权限；
- Minion 可以访问 Master TCP 4505/4506；
- 已规划唯一 Minion ID；
- Master 不自动接受 key，必须人工核验 fingerprint；
- Salt 固定安装 `3008.1`，安装后 `apt-mark hold`。

## 3. 通过 curl 获取 Minion 安装脚本

在 Minion 节点执行：

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

以后更新脚本时，重复执行上面的 `curl -o scripts/proxyfleet-minion.sh` 即可。

如果你希望 Minion 测试机也保留完整项目文件，可以下载完整压缩包：

```bash
sudo apt-get update
sudo apt-get install -y curl tar ca-certificates

mkdir -p ~/project/ProxyFleet
curl -fsSL \
  https://github.com/Flashyuan/ProxyFleet/archive/refs/heads/main.tar.gz \
  | tar -xz --strip-components=1 -C ~/project/ProxyFleet

cd ~/project/ProxyFleet
chmod +x scripts/proxyfleet-minion.sh
```

## 4. 安装 Minion

在 Minion 节点执行：

```bash
scripts/proxyfleet-minion.sh preflight

sudo scripts/proxyfleet-minion.sh install \
  --master <master-ip-or-dns> \
  --id <minion-id> \
  --environment production \
  --driver native-mihomo \
  --release-channel stable
```

下面的无参数命令会直接进入 Minion TUI 主控台，由菜单完成 Master
地址、Minion ID、Salt Minion 安装、Mihomo 生命周期和本机端口策略配置：

```bash
sudo scripts/proxyfleet-minion.sh
```

子命令仍保留给自动化、排障和文档复现。

兼容参数：

```bash
sudo scripts/proxyfleet-minion.sh install \
  --master-ip <master-ip> \
  --id <minion-id>
```

安装会写入：

- `/etc/apt/keyrings/salt-archive-keyring.pgp`
- `/etc/apt/sources.list.d/salt.sources`
- `/etc/apt/preferences.d/proxyfleet-salt-pin`
- `/etc/salt/minion.d/proxyfleet.conf`

安装后脚本会输出本机 fingerprint，并提示回到 Master 接受 key。

## 5. Minion 安装参数

```text
--master / --master-ip     Master IP 或 DNS
--id                       Minion 唯一 ID，Master 接受 key 时使用
--environment              默认 production
--driver                   默认 native-mihomo
--release-channel          默认 stable
```

当前推荐生产迁移方向是卸载 ShellCrash 后使用 `native-mihomo`，让 ProxyFleet 统一安装
和管控 Mihomo。

## 6. 在 Master 接受 key

这一步在 Master 节点执行，不是在 Minion 节点执行：

```bash
sudo salt-key -L
sudo salt-key -F
sudo salt-key -a <minion-id>
sudo salt '<minion-id>' test.ping
```

如果 Master 上看不到 unaccepted key，先在 Minion 检查：

```bash
scripts/proxyfleet-minion.sh status
sudo systemctl restart salt-minion
```

同时确认 Minion 能访问 Master：

```bash
timeout 3 bash -c '</dev/tcp/<master-ip>/4505' && echo 4505-ok
timeout 3 bash -c '</dev/tcp/<master-ip>/4506' && echo 4506-ok
```

## 7. Minion 常用命令

在 Minion 节点执行：

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

危险清理：

```bash
sudo scripts/proxyfleet-minion.sh uninstall --purge-data --yes
```

命令说明：

```text
preflight              只读检查 OS、systemd、sudo 和 Salt 目标版本
install/bootstrap      安装 Salt Minion 3008.1，并写入 Master/ID/grains 配置
start                  启动 salt-minion
stop                   停止 salt-minion
restart                重启 salt-minion
status                 查看 salt-minion 状态
uninstall              卸载 salt-minion，默认保留 Minion PKI 和配置
uninstall --purge-data [--yes]
                     危险清理，删除 Minion PKI 和配置
```

### 7.1 Mihomo 生命周期控制

`proxyfleet-minion.sh start/stop/restart/status/uninstall` 默认只控制
`salt-minion`。它不会隐式启动、停止或卸载本机 `mihomo.service`。

显式 Mihomo 控制入口：

```text
start --with-mihomo         启动 salt-minion 后安全启动 Mihomo
stop --with-mihomo          安全停止 Mihomo 后停止 salt-minion
restart --with-mihomo       同时按安全流程重启 salt-minion 和 Mihomo
uninstall --with-mihomo     卸载 salt-minion，并执行 Mihomo 安全卸载
mihomo-start                只安全启动本机 Mihomo
mihomo-stop                 只停止本机 Mihomo，保留配置和 release
mihomo-restart              只重启本机 Mihomo
mihomo-status               查看 Mihomo 受管状态
mihomo-uninstall            停止并禁用 Mihomo，默认保留 /etc/proxyfleet
```

Mihomo 卸载会采用分级清理：

```text
mihomo-uninstall                 只删除 ProxyFleet 拥有的 systemd unit
mihomo-uninstall --purge-managed 删除 managed/effective 产物，保留 local override
mihomo-uninstall --purge-all --yes
                                 删除受管 release、链接、unit 和受管二进制
--purge-local-override           额外允许删除 /etc/proxyfleet/local
```

任何 unit 不属于 ProxyFleet、路径不匹配、配置校验失败或二进制来源无法确认时，
Mihomo 生命周期命令必须停止执行，不能猜测删除范围。

## 8. 被 Master 管控后的操作边界

Minion 安装完成并被 Master 接受 key 后，日常代理配置不在 Minion 本机手动操作。

在 Master 上执行：

```bash
sudo scripts/proxyfleet-master.sh select-sync
```

Master 会通过 Salt 下发：

- Mihomo 固定版本资产；
- release 配置；
- desired state；
- `FLEET_PROXY` 选择。

Minion 本机只保留本地 override：

```text
/etc/proxyfleet/local/port-policy.yaml
```

该文件不会被 Master 覆盖，用于保留 Minion 自己的端口白名单规则。

## 9. 常见验证命令

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
