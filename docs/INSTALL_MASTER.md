# 主节点测试机安装与配置

> 适用：Ubuntu 22.04/24.04 原生 systemd Master 测试机。

## 1. 前置条件

- 当前机器是 Master 测试机；
- 用户具备 sudo 权限；
- 网络允许 Minion 访问 Master TCP 4505/4506；
- 不启用公网 `salt-api`；
- Salt 固定安装 `3008.1`，安装后 hold。

## 2. 通过 curl 获取项目和安装脚本

Master 节点需要完整项目文件，因为后续 `sync-assets` 需要同步 `salt/`、
`scripts/` 和 Python 模块。新机器不需要配置 Git 仓库，直接用 `curl`
下载 `main` 分支压缩包即可。

安装必要工具：

```bash
sudo apt-get update
sudo apt-get install -y curl tar ca-certificates
```

下载并解压完整项目：

```bash
mkdir -p ~/project/ProxyFleet
curl -fsSL \
  https://github.com/Flashyuan/ProxyFleet/archive/refs/heads/main.tar.gz \
  | tar -xz --strip-components=1 -C ~/project/ProxyFleet

cd ~/project/ProxyFleet
chmod +x scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh
```

记录本次 curl 部署来源标识，后续构建 release 时使用：

```bash
export PROXYFLEET_SOURCE_REF="github-main-curl-$(date -u +%Y%m%dT%H%M%SZ)"
```

如果以后需要更新项目，重新执行上面的 `curl | tar` 解压命令即可。

## 3. 只读预检

```bash
scripts/proxyfleet-master.sh preflight
```

## 4. 安装 Master

安装会写入：

- `/etc/apt/keyrings/salt-archive-keyring.pgp`
- `/etc/apt/sources.list.d/salt.sources`
- `/etc/apt/preferences.d/proxyfleet-salt-pin`
- `/etc/salt/master.d/proxyfleet.conf`
- `/srv/proxyfleet/salt/states/proxyfleet/sync.sls`
- `/srv/proxyfleet/salt/states/_modules/proxyfleet_mihomo.py`

执行：

```bash
sudo scripts/proxyfleet-master.sh install
```

以后项目代码更新后，可只同步 Salt assets：

```bash
sudo scripts/proxyfleet-master.sh sync-assets
sudo salt '*' saltutil.sync_modules
```

安装完成后检查：

```bash
scripts/proxyfleet-master.sh status
apt-cache policy salt-master salt-minion
apt-mark showhold
sudo ss -ltnp | grep -E ':4505|:4506'
```

## 5. 接受 Minion Key

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

## 6. 配置代理、选择节点并同步

以下命令在 Master 项目目录执行。示例使用测试 fixture；生产时应替换为真实
`config-src/`、`runtime/` 和 `/srv/proxyfleet/salt/states` 路径。

订阅 URL 不写入配置文件。Provider 使用 `env` 或 `secret_ref` 引用：

```json
{
  "id": "airport-main",
  "kind": "subscription",
  "enabled": true,
  "env": "PROXYFLEET_SUB_AIRPORT_MAIN",
  "name_prefix": "[AIR] ",
  "output": "providers/airport-main.yaml"
}
```

构建前只在 Master 本机注入真实 URL：

```bash
export PROXYFLEET_SUB_AIRPORT_MAIN='https://subscription.example.invalid/subscription'
```

### 6.1 构建 release

```bash
PYTHONPATH=src python3 -m proxyfleet.cli build-release \
  config-src \
  releases \
  --revision 1 \
  --source-git-commit "${PROXYFLEET_SOURCE_REF:-github-main-curl}" \
  --component-locks component-locks.json \
  --subscription-cache runtime/subscriptions
```

### 6.2 查看可选代理节点

```bash
PYTHONPATH=src python3 -m proxyfleet.cli nodes releases/000001
```

输出中的 `node_id` 是 Master 选择节点时使用的稳定 ID。

如需显示测速结果，先刷新健康缓存，再合并查看：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli health-check \
  releases/000001 runtime/health.json \
  --mihomo-api http://127.0.0.1:9090 \
  --all

PYTHONPATH=src python3 -m proxyfleet.cli nodes \
  releases/000001 \
  --health-cache runtime/health.json
```

测速只调用本机 Mihomo delay API，不改变当前选择。

### 6.3 选择节点

```bash
PYTHONPATH=src python3 -m proxyfleet.cli select-node \
  releases/000001 \
  runtime \
  --node-id <node-id> \
  --target-group production
```

该命令只写入 `runtime/desired.yaml`，不会重建 `config.yaml`。

### 6.4 发布到 Salt file_roots

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli publish-salt \
  releases/000001 \
  runtime/desired.yaml \
  /srv/proxyfleet/salt/states
```

该命令会把 release 和 desired state 复制到：

```text
/srv/proxyfleet/salt/states/proxyfleet/releases/000001
/srv/proxyfleet/salt/states/proxyfleet/desired.yaml
```

首次使用前，还需要把项目 Salt module/state 同步到 Salt file_roots。安装脚本
已内置同步入口：

```bash
sudo scripts/proxyfleet-master.sh sync-assets
sudo salt '*' saltutil.sync_modules
```

### 6.5 同步并应用到 Minion

先查看 dry-run 计划：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 \
  runtime/desired.yaml \
  /srv/proxyfleet/salt/states \
  --target '<minion-id-or-target>' \
  --dry-run
```

确认后执行：

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 \
  runtime/desired.yaml \
  /srv/proxyfleet/salt/states \
  --target '<minion-id-or-target>'
```

Minion 会安装当前 release 到 `/etc/proxyfleet/releases/<revision>`，
更新 `/etc/proxyfleet/current`，并通过本机 Mihomo API 选择 `FLEET_PROXY`。

### 6.6 最少步骤入口

已经知道 `node_id` 时，可用一条命令完成构建、选择、发布和同步：

```bash
sudo --preserve-env=PROXYFLEET_SUB_AIRPORT_MAIN \
  PYTHONPATH=src python3 -m proxyfleet.cli apply \
  config-src releases runtime /srv/proxyfleet/salt/states \
  --revision 1 \
  --source-git-commit "${PROXYFLEET_SOURCE_REF:-github-main-curl}" \
  --component-locks component-locks.json \
  --subscription-cache runtime/subscriptions \
  --select <node-id> \
  --target '<minion-id-or-target>'
```

首次执行建议增加 `--dry-run` 先看计划。

注意：Mihomo 真安装受 `component-locks.json` 保护。当前已锁定 Mihomo
`v1.19.27` 的 `linux-amd64` 和 `linux-arm64` gzip 资产。Minion 会先校验
gzip 包 SHA-256，再解压安装；SHA 不匹配或解压失败会 fail-closed。

## 7. 启停与卸载

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
