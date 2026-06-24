# 新 Minion 测试机安装与配置

> 适用：Ubuntu 22.04/24.04 原生 systemd Minion 测试机。

## 1. 前置条件

- Master 已安装并可从 Minion 访问 TCP 4505/4506；
- 已规划唯一、人工可识别的 Minion ID；
- Minion 不自动接受 key，必须由 Master 人工核验 fingerprint 后接受；
- Salt 固定安装 `3008.1`，安装后 hold。

## 2. 通过 curl 获取 Minion 安装脚本

Minion 节点只安装 Salt Minion 时，至少需要获取：

```text
scripts/proxyfleet-minion.sh
```

新机器不需要配置 Git 仓库。直接用 `curl` 获取单个脚本：

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

如果你希望 Minion 测试机也保留完整项目文件，可以用 `curl` 下载压缩包：

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

如果以后只更新 Minion 安装脚本，重新执行：

```bash
cd ~/project/proxyfleet-minion
curl -fsSL \
  https://raw.githubusercontent.com/Flashyuan/ProxyFleet/main/scripts/proxyfleet-minion.sh \
  -o scripts/proxyfleet-minion.sh
chmod +x scripts/proxyfleet-minion.sh
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
