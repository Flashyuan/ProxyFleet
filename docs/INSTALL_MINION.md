# 新 Minion 测试机安装与配置

> 适用：Ubuntu 22.04/24.04 原生 systemd Minion 测试机。

## 1. 前置条件

- Master 已安装并可从 Minion 访问 TCP 4505/4506；
- 已规划唯一、人工可识别的 Minion ID；
- Minion 不自动接受 key，必须由 Master 人工核验 fingerprint 后接受；
- Salt 固定安装 `3008.1`，安装后 hold。

## 2. 复制项目或脚本

在新服务器上获取项目仓库，或至少复制：

```text
scripts/proxyfleet-minion.sh
```

## 3. 只读预检

```bash
scripts/proxyfleet-minion.sh preflight
```

## 4. 安装 Minion

示例：

```bash
sudo scripts/proxyfleet-minion.sh install \
  --master <master-ip-or-dns> \
  --id vps-01 \
  --environment production \
  --driver native-mihomo \
  --release-channel stable
```

脚本会写入：

- `/etc/apt/keyrings/salt-archive-keyring.pgp`
- `/etc/apt/sources.list.d/salt.sources`
- `/etc/apt/preferences.d/proxyfleet-salt-pin`
- `/etc/salt/minion.d/proxyfleet.conf`

安装后检查：

```bash
scripts/proxyfleet-minion.sh status
apt-cache policy salt-minion
apt-mark showhold
```

## 5. 回到 Master 接受 key

在 Master 上执行：

```bash
sudo salt-key -L
sudo salt-key -F
sudo salt-key -a vps-01
sudo salt 'vps-01' test.ping
```

## 6. 启停与卸载

```bash
sudo scripts/proxyfleet-minion.sh start
sudo scripts/proxyfleet-minion.sh stop
sudo scripts/proxyfleet-minion.sh restart
scripts/proxyfleet-minion.sh status
```

默认卸载保留 Minion PKI 和配置：

```bash
sudo scripts/proxyfleet-minion.sh uninstall
```

危险清理会删除 Minion PKI 和配置：

```bash
sudo scripts/proxyfleet-minion.sh uninstall --purge-data
```
