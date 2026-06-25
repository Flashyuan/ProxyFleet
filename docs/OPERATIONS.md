# ProxyFleet 启停与卸载操作

## Master

```bash
sudo scripts/proxyfleet-master.sh start
sudo scripts/proxyfleet-master.sh stop
sudo scripts/proxyfleet-master.sh restart
scripts/proxyfleet-master.sh status
sudo scripts/proxyfleet-master.sh uninstall
```

危险清理：

```bash
sudo scripts/proxyfleet-master.sh uninstall --purge-data
```

## Minion

```bash
sudo scripts/proxyfleet-minion.sh start
sudo scripts/proxyfleet-minion.sh stop
sudo scripts/proxyfleet-minion.sh restart
scripts/proxyfleet-minion.sh status
sudo scripts/proxyfleet-minion.sh uninstall
```

危险清理：

```bash
sudo scripts/proxyfleet-minion.sh uninstall --purge-data
```

## 注意事项

- `uninstall` 默认保留 Salt PKI，避免破坏信任关系；
- `--purge-data` 只适合测试环境确认后使用；
- Master 不自动接受 Minion key；
- 项目不启用公网 `salt-api`；
- Salt 安装固定 `3008.1`，安装后 hold，不随系统自动更新。

## 代理配置、节点选择和同步

Master 的运行顺序：

1. 构建不可变 release；
2. 查看 release 内可选节点；
3. 选择稳定 `node_id`，写入 `runtime/desired.yaml`；
4. 发布 release/desired 到 Salt file_roots；
5. 通过 Salt 让 Minion 安装 release 并切换 `FLEET_PROXY`。

### 订阅、自建节点和规则配置

配置源目录至少包含：

- `base.json`：Mihomo 基础配置；
- `providers.json`：订阅 Provider 和自建节点 Provider；
- `groups.json`：`FLEET_PROXY` 等策略组；
- `rules.json`：规则顺序和 rule provider；
- 自建节点 JSON 与自定义规则 JSON。

订阅 URL 不写入 Git。推荐在 Master 本机用环境变量注入：

```json
{
  "schema_version": "1.0",
  "providers": [
    {
      "id": "airport-main",
      "kind": "subscription",
      "enabled": true,
      "env": "PROXYFLEET_SUB_AIRPORT_MAIN",
      "name_prefix": "[AIR] ",
      "output": "providers/airport-main.yaml"
    },
    {
      "id": "self-hosted",
      "kind": "local_file",
      "enabled": true,
      "source": "provider-self-hosted.json",
      "name_prefix": "[SELF] ",
      "output": "providers/self-hosted.yaml"
    }
  ]
}
```

构建前设置真实订阅 URL：

```bash
export PROXYFLEET_SUB_AIRPORT_MAIN='https://subscription.example.invalid/subscription'
```

订阅 URL 可以返回两类内容：

- 纯 Mihomo/Clash provider：顶层为 `proxies`；
- 完整 Mihomo/Clash 配置：顶层包含 `proxies`、`proxy-groups`、`rules` 等。

构建器会自动提取顶层 `proxies` 生成受管 Provider。订阅侧的
`proxy-groups` 和 `rules` 不会进入 release；Master 仍以本地 `groups.json`
和 `rules.json` 为准统一管理策略组和规则。

### 分步执行

```bash
PYTHONPATH=src python3 -m proxyfleet.cli build-release \
  config-src releases --revision 1 \
  --source-git-commit "${PROXYFLEET_SOURCE_REF:-manual-config}" \
  --component-locks component-locks.json \
  --subscription-cache runtime/subscriptions

PYTHONPATH=src python3 -m proxyfleet.cli nodes releases/000001

PYTHONPATH=src python3 -m proxyfleet.cli health-check \
  releases/000001 runtime/health.json \
  --mihomo-api http://127.0.0.1:9090 \
  --all

PYTHONPATH=src python3 -m proxyfleet.cli nodes \
  releases/000001 \
  --health-cache runtime/health.json

sudo scripts/proxyfleet-master.sh select-sync
```

`select-sync` 会列出带序号的节点，节点名为 `mihomo_name`。输入序号后，
脚本会写入 desired state、发布当前 release，并默认同步到所有 Minion。
如果希望接近 Yacd 面板的实时测速体验，使用：

```bash
sudo scripts/proxyfleet-master.sh select-sync --live-health
```

该模式会先显示节点列表，再后台并发刷新延迟；用户可以不等测速全部完成，
随时输入当前稳定序号完成选择。若只想批量刷新缓存再进入菜单，可使用
`--refresh-health`；若不想读取旧测速缓存，可使用 `--no-health-cache`。
如需限制目标：

```bash
sudo scripts/proxyfleet-master.sh select-sync --target '<minion-id-or-target>'
```

手动分步选择时：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli select-node \
  releases/000001 runtime --node-id <node-id>

sudo PYTHONPATH=src python3 -m proxyfleet.cli publish-salt \
  releases/000001 runtime/desired.yaml /srv/proxyfleet/salt/states

PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 runtime/desired.yaml /srv/proxyfleet/salt/states \
  --target '<minion-id-or-target>' --dry-run

sudo PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 runtime/desired.yaml /srv/proxyfleet/salt/states \
  --target '<minion-id-or-target>'
```

`select-node` 不会重建 `config.yaml`；它只改变 desired state 中的
`selected_node_id` 和 `selected_mihomo_name`。

### 最少步骤执行

已经知道目标 `node_id` 时，可以用一条命令完成构建、选择、发布和 Salt 同步：

```bash
sudo --preserve-env=PROXYFLEET_SUB_AIRPORT_MAIN \
  PYTHONPATH=src python3 -m proxyfleet.cli apply \
  config-src releases runtime /srv/proxyfleet/salt/states \
  --revision 1 \
  --source-git-commit "$(git rev-parse HEAD)" \
  --component-locks component-locks.json \
  --subscription-cache runtime/subscriptions \
  --select <node-id> \
  --target '<minion-id-or-target>'
```

首次执行或不确定影响范围时先加 `--dry-run`。`apply --dry-run` 只输出计划，
不会写 runtime、Salt file_roots，也不会执行 Salt。

### Mihomo 安装配置边界

Salt state 会调用 `proxyfleet_mihomo.install_mihomo`。该步骤只接受
`component-locks.json` 中已固定 URL、SHA-256 和压缩格式的 Mihomo 资产。
当前已锁定 Mihomo `v1.19.27` 的 `linux-amd64` 和 `linux-arm64` gzip 资产。
下载后先校验 gzip 包 SHA-256，再解压并原子安装；不会自动下载 `latest`。

### 端口白名单分层配置

Master 可发布公共端口白名单：

```bash
sudo PYTHONPATH=src python3 -m proxyfleet.cli publish-salt \
  releases/000001 runtime/desired.yaml /srv/proxyfleet/salt/states \
  --component-locks component-locks.json \
  --port-policy config-src/port-policy.json \
  --port-policy-mode merge
```

Minion 本机可维护：

```text
/etc/proxyfleet/local/port-policy.yaml
```

Salt state 只确保 `/etc/proxyfleet/local` 目录存在，不覆盖、不删除本机文件。
最终合并输出为：

```text
/etc/proxyfleet/effective/port-policy.yaml
```

本轮实现的是策略合并和防覆盖保护；UFW/nftables 真正落地后端仍是后续任务。

### 测速显示边界

`health-check` 调用本机 Mihomo delay API，不修改 `FLEET_PROXY` 当前选择。
测速 URL 限定为项目允许列表，默认是：

```text
https://www.gstatic.com/generate_204
```

`select-sync --live-health` 是本机实时测速菜单：它调用 Master 本机
`http://127.0.0.1:9090` 的 Mihomo API。该延迟只代表 Master 本机到代理节点
的观测结果。若要比较每台 Minion 自身网络质量，需要后续 fleet-wide 汇总模式，
由各 Minion 在本机调用自己的 Mihomo API 后回传结果。
