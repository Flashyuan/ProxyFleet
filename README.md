# ProxyFleet

ProxyFleet 用 Salt Master/Minion 统一管理多台服务器上的 Mihomo 代理配置、节点选择和同步。

已实现的主干能力包括：

- Master/Minion 安装脚本；
- Master TUI 主控台；
- 订阅 URL 拉取和 Provider 快照转换；
- 一键订阅 URL 生成可用配置；
- 多订阅 Provider 合并；
- release 构建与 Salt 同步；
- Master/Minion 受控自更新；
- Mihomo 固定版本安装和本机节点选择；
- Minion 本机端口白名单 override。

## 文档入口

- [Master 安装与配置](docs/INSTALL_MASTER.md)
- [Minion 安装与配置](docs/INSTALL_MINION.md)
- [日常运维命令](docs/OPERATIONS.md)
- [用户使用手册](docs/USER_MANUAL.md)

## Master TUI

在 Master 项目目录执行：

```bash
sudo scripts/proxyfleet-master.sh
```

常用流程：

```text
节点配置相关 -> 快速添加订阅 URL 并生成可用配置
节点配置相关 -> 选择节点并同步到 Minion
```

## 当前容器化结论

采用“**管理端可容器化、子节点默认原生安装**”的混合模式：

- `fleetctl` 构建环境和 subconverter：适合容器化；
- Salt Master：可以容器化，但必须使用项目自建且锁版的镜像，并持久化密钥、缓存、file roots 和 pillar roots；生产参考实现仍保留原生 systemd 方式；
- Salt Minion：安装在子节点宿主机，由 systemd 管理；
- Mihomo：透明代理/TUN 节点默认安装在宿主机；
- 已有 ShellCrash：生产迁移时先备份和卸载，再进入 `native-mihomo`；只保留只读探测/迁移辅助能力；
- V1 不要求任何子节点安装 Docker。
