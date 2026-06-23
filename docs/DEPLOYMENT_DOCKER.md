# ProxyFleet Docker 部署可行性与便捷性

> 结论：**可以把管理端打包成 Docker Compose，但不建议把所有子节点都容器化。**

## 1. 推荐部署组合

| 组件 | 原生 systemd | Docker | V1 推荐 |
|---|---:|---:|---|
| fleetctl | 是 | 是 | 主机包装命令或控制容器均可 |
| Salt Master | 是 | 可行 | 原生为生产参考，Docker 为支持配置 |
| 配置构建器 | 是 | 很适合 | Docker 一次性任务 |
| subconverter | 是 | 很适合 | Docker 一次性任务 |
| Salt Minion | 是 | 技术上可行但不便 | 原生 |
| Mihomo proxy-only | 是 | 可行 | 原生优先 |
| Mihomo TUN/透明代理 | 是 | 高权限可行 | V1 原生，不支持容器方式 |
| ShellCrash | 是 | 不适合迁移 | 保留原生 |

最终用户体验应是：

```text
管理节点可选：docker compose up -d
每个子节点：只执行一次 bootstrap，安装 salt-minion 和需要的 mihomo 服务
已有 ShellCrash 节点：只增加 salt-minion，不安装第二个 mihomo
```

## 2. 管理端 Docker 的便利性

### 优点

- 构建依赖和版本易于锁定；
- 管理主节点迁移时只需仓库、持久卷和 secrets；
- subconverter 不污染宿主机；
- 可对构建任务使用只读文件系统、短生命周期和无网络模式；
- 一套 Compose 可用于开发、测试和小规模生产。

### 成本

- Salt Master keys、缓存和 file roots 必须正确挂载；
- 容器镜像需自行维护；
- 4505/4506 的防火墙行为需要额外验证；
- 备份恢复比普通无状态容器严格；
- `docker compose down -v` 可能造成灾难性数据丢失，必须在运行手册中禁止。

## 3. Salt Master 镜像策略

公开的 `saltstack/salt` Docker Hub 页面明确说明其容器“不受官方支持”，现有标签也停留在较旧版本。因此 V1 不直接采用它。

项目镜像应：

1. 从明确基础镜像开始；
2. 使用 Salt 官方 DEB 仓库安装锁定的 3008.x point release；
3. 记录基础镜像 digest 和 Salt 包版本；
4. 不内置生产 secrets 或 Master keys；
5. 以 CI 构建并生成 SBOM/哈希；
6. 镜像启动时拒绝缺失持久卷；
7. 不启用 salt-api。

## 4. 必须持久化的数据

```text
/etc/salt/pki/master          # Master 身份和 Minion 信任，最高重要性
/etc/salt/master.d            # Master 配置
/var/cache/salt/master        # 缓存和部分运行状态
/var/log/salt                 # 审计/诊断，可独立日志驱动
/srv/salt                     # States/file roots
/srv/pillar                   # Pillar roots
/workspace/proxyfleet         # Git 工作区、releases、runtime state
```

备份分级：

- Tier 0：`/etc/salt/pki/master`、secrets；必须加密和离线副本；
- Tier 1：配置源、Pillar、release manifest、desired state；
- Tier 2：缓存和日志。

## 5. 网络模式

Salt Master 需要 TCP 4505/4506。两种方式均可 POC：

### Bridge + 显式端口发布

优点是容器隔离较清晰；缺点是 Docker 端口发布和宿主机防火墙交互要专项验证。必须使用云防火墙/DOCKER-USER 规则限制来源。

### Host network

无 NAT，行为更接近原生服务，故障排查简单；代价是网络隔离降低。Linux Docker 支持 host network。

ADR 不强制二选一，POC 后由 SECURITY 和 OPS 选定参考 Compose。无论何种方式，都不对公网开放 salt-api。

## 6. 构建器容器

推荐把构建拆成两步：

```text
fleetctl 在主节点获取订阅、响应头和快照
→ 把已验证输入交给短生命周期 builder/subconverter 容器
→ 容器在 network:none 下生成 staging release
→ 主节点使用锁定 Mihomo 校验
→ 原子发布
```

好处是订阅 URL 无需进入容器镜像或命令行历史，转换器也不能主动访问外网。

## 7. 为什么 Salt Minion 不放容器

Minion 的任务是修改宿主机 `/etc/mihomo`、systemd 服务、文件权限和可能的路由。普通容器看不到或不能控制这些资源；为了实现同样能力，需要挂载宿主机根目录、systemd socket、网络命名空间或 Docker socket，并授予高权限。这样既弱化隔离，也让故障排查和回滚更复杂。

因此 V1 将 `salt-minion.service` 原生安装到 Ubuntu 宿主机。

## 8. 为什么 TUN Mihomo 不放容器

Mihomo TUN 的 auto-route/auto-redirect 会操作宿主机路由和 iptables/nftables。容器运行通常至少需要：

```text
network_mode: host
CAP_NET_ADMIN
CAP_NET_RAW
/dev/net/tun
持久配置目录
```

这类容器已经拥有很强的宿主机网络控制权，并可能与 Docker 自身网络规则、UFW 和云网络产生交互。V1 不把它作为支持模式。

只提供 HTTP/SOCKS 入站、不接管宿主机流量的 `proxy-only` 容器，未来可作为低风险可选 Profile。

## 9. 已安装 ShellCrash 的节点

不将 ShellCrash 搬入容器。节点上：

```text
保留 ShellCrash + Mihomo + 原有 TUN/TProxy
原生安装 salt-minion
通过 localhost Mihomo API 和持久化适配层接管 FLEET_PROXY
```

若 ShellCrash 使用 sing-box 或无法持久化本地 API，V1 标记 unsupported，不通过容器绕过。

## 10. Docker 管理端上线门槛

以下全部通过才标记 Production Supported：

- [ ] 容器重启后 Minion key 无需重新接受；
- [ ] 主节点迁移到新主机后 Minion 正常重连；
- [ ] Salt 3008.x point release 升级与回滚；
- [ ] Master PKI 加密备份和恢复演练；
- [ ] 4505/4506 仅目标来源可达；
- [ ] 磁盘满、只读卷和损坏缓存故障注入；
- [ ] 日志轮转；
- [ ] 镜像 digest、SBOM 和漏洞扫描；
- [ ] `compose down` 不删除数据卷的运维护栏；
- [ ] 原生和 Docker Master 的行为契约测试一致。

## 11. 便捷性评价

- 管理端 Docker：高，特别适合一键部署和固定依赖；
- 子节点 Docker：低，透明代理和宿主机控制抵消了容器优势；
- 推荐整体方案：`docker-control + native-node` 或 `host-control + native-node`。

对用户而言，二者的子节点接入方式完全相同；区别只在主节点如何运行 Salt Master 和构建工具。
