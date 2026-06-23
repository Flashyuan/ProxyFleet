# 主节点测试机安装与配置

> 适用：Ubuntu 22.04/24.04 原生 systemd Master 测试机。

## 1. 前置条件

- 当前机器是 Master 测试机；
- 用户具备 sudo 权限；
- 网络允许 Minion 访问 Master TCP 4505/4506；
- 不启用公网 `salt-api`；
- Salt 固定安装 `3008.1`，安装后 hold。

## 2. 只读预检

```bash
scripts/proxyfleet-master.sh preflight
```

## 3. 安装 Master

安装会写入：

- `/etc/apt/keyrings/salt-archive-keyring.pgp`
- `/etc/apt/sources.list.d/salt.sources`
- `/etc/apt/preferences.d/proxyfleet-salt-pin`
- `/etc/salt/master.d/proxyfleet.conf`
- `/srv/proxyfleet/salt/states/poc/init.sls`

执行：

```bash
sudo scripts/proxyfleet-master.sh install
```

安装完成后检查：

```bash
scripts/proxyfleet-master.sh status
apt-cache policy salt-master salt-minion
apt-mark showhold
sudo ss -ltnp | grep -E ':4505|:4506'
```

## 4. 接受 Minion Key

Minion 安装并启动后，在 Master 上查看 key：

```bash
sudo salt-key -L
sudo salt-key -F
```

确认 fingerprint 和 Minion 身份无误后接受：

```bash
sudo salt-key -a <minion-id>
```

验证连通：

```bash
sudo salt '<minion-id>' test.ping
sudo salt '<minion-id>' grains.items
sudo salt '<minion-id>' state.apply poc test=true
sudo salt '<minion-id>' state.apply poc
```

## 5. 启停与卸载

```bash
sudo scripts/proxyfleet-master.sh start
sudo scripts/proxyfleet-master.sh stop
sudo scripts/proxyfleet-master.sh restart
scripts/proxyfleet-master.sh status
```

默认卸载保留 Master PKI 和 POC state：

```bash
sudo scripts/proxyfleet-master.sh uninstall
```

危险清理会删除 Master PKI 和 POC state：

```bash
sudo scripts/proxyfleet-master.sh uninstall --purge-data
```

删除 Master PKI 会破坏 Minion 信任关系，只能在测试环境确认后执行。
