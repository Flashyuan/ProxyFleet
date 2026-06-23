# ADR-0004：容器化边界

- 状态：Accepted
- 日期：2026-06-22
- 决策者：ARCH-ORCH
- 评审要求：OPS-PLATFORM、CONTROL-SALT、SECURITY、QA-RELEASE

## 背景

希望项目易于安装和迁移，但子节点透明代理会直接操作宿主机网络，已有 ShellCrash 也运行在宿主机。

## 决策

采用混合部署：

1. `host-control` 为生产参考：Salt Master 原生 systemd。
2. 提供 `docker-control` 便捷配置：Salt Master、构建工具可由 Docker Compose 管理。
3. Docker Salt Master 必须使用项目自建镜像，安装官方 Salt 3008.x DEB；不得依赖陈旧且声明不受支持的公共 Salt 镜像。
4. Salt Master 的 PKI、配置、缓存、日志、file roots、pillar roots 和工作区必须持久化并纳入备份。
5. 子节点 Salt Minion 原生安装。
6. 子节点 Mihomo 默认原生安装；V1 不支持容器化 TUN。
7. 现有 ShellCrash 保持原生运行。
8. 构建器/subconverter 优先作为短生命周期、无公网监听的容器。

## 理由

管理端容器化可锁定依赖、方便迁移；子节点 TUN 容器需要 host network、NET_ADMIN、TUN 设备和宿主机网络修改，隔离收益有限且故障面更大。Salt Minion 容器若要管理宿主机 systemd/网络，同样需要危险挂载和权限。

## 生产门槛

`docker-control` 只有在以下测试通过后才能标记 Production Supported：

- Master key 持久化；
- 整机迁移恢复；
- 镜像 point-release 升级/回滚；
- 4505/4506 防火墙验证；
- 容器重启后 Minion 无需重新注册；
- 备份恢复演练；
- 资源限制和日志轮转。

## 后果

用户可在主节点使用 Docker Compose，但子节点不需要 Docker，避免把 Docker 变成全网依赖。
