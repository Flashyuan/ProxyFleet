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
