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

示例：

```bash
PYTHONPATH=src python3 -m proxyfleet.cli build-release \
  tests/fixtures/config-src releases --revision 1 \
  --source-git-commit "$(git rev-parse HEAD)" \
  --component-locks component-locks.json

PYTHONPATH=src python3 -m proxyfleet.cli nodes releases/000001

PYTHONPATH=src python3 -m proxyfleet.cli select-node \
  releases/000001 runtime --node-id <node-id>

sudo PYTHONPATH=src python3 -m proxyfleet.cli publish-salt \
  releases/000001 runtime/desired.yaml /srv/salt

PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 runtime/desired.yaml /srv/salt \
  --target '<minion-id-or-target>' --dry-run

sudo PYTHONPATH=src python3 -m proxyfleet.cli sync \
  releases/000001 runtime/desired.yaml /srv/salt \
  --target '<minion-id-or-target>'
```

`select-node` 不会重建 `config.yaml`；它只改变 desired state 中的
`selected_node_id` 和 `selected_mihomo_name`。
