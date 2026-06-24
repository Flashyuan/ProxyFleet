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

## 5. 配置代理、选择节点并同步

以下命令在 Master 项目目录执行。示例使用测试 fixture；生产时应替换为真实
`config-src/`、`runtime/` 和 `/srv/salt` 路径。

### 5.1 构建 release

```bash
PYTHONPATH=src python3 -m proxyfleet.cli build-release \
  tests/fixtures/config-src \
  releases \
  --revision 1 \
  --source-git-commit "$(git rev-parse HEAD)" \
  --component-locks component-locks.json
```

### 5.2 查看可选代理节点

```bash
PYTHONPATH=src python3 -m proxyfleet.cli nodes releases/000001
```

输出中的 `node_id` 是 Master 选择节点时使用的稳定 ID。

### 5.3 选择节点

```bash
PYTHONPATH=src python3 -m proxyfleet.cli select-node \
  releases/000001 \
  runtime \
  --node-id <node-id> \
  --target-group production
```

该命令只写入 `runtime/desired.yaml`，不会重建 `config.yaml`。

### 5.4 发布到 Salt file_roots

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli publish-salt \
  releases/000001 \
  runtime/desired.yaml \
  /srv/salt
```

该命令会把 release 和 desired state 复制到：

```text
/srv/salt/proxyfleet/releases/000001
/srv/salt/proxyfleet/desired.yaml
```

首次使用前，还需要把项目 Salt module/state 同步到 Salt file_roots：

```bash
sudo mkdir -p /srv/salt/_modules /srv/salt/proxyfleet
sudo cp salt/modules/proxyfleet_mihomo.py /srv/salt/_modules/
sudo cp -r salt/states/proxyfleet /srv/salt/
sudo salt '*' saltutil.sync_modules
```

### 5.5 同步并应用到 Minion

先查看 dry-run 计划：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 \
  runtime/desired.yaml \
  /srv/salt \
  --target '<minion-id-or-target>' \
  --dry-run
```

确认后执行：

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 \
  runtime/desired.yaml \
  /srv/salt \
  --target '<minion-id-or-target>'
```

Minion 会安装当前 release 到 `/etc/proxyfleet/releases/<revision>`，
更新 `/etc/proxyfleet/current`，并通过本机 Mihomo API 选择 `FLEET_PROXY`。

## 6. 启停与卸载

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
