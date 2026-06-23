# ProxyFleet 工程文档包

> 状态：Architecture Baseline v2.2
> 日期：2026-06-23
> 目标系统：Ubuntu Server 22.04 LTS（主基线）、Ubuntu Server 24.04 LTS（兼容基线）

本目录是 ProxyFleet 的完整工程治理与实施文档基线。当前仍处于架构与工程准备阶段，不包含生产代码。

## 入口

1. [PLAN.md](PLAN.md)：主工程计划、阶段、验收与恢复顺序。
2. [AGENTS.md](AGENTS.md)：11 个固定 Subagent 岗位、唯一会话注册、通信与复用规则。
3. [PROJECT_STATE.md](PROJECT_STATE.md)：当前事实、进度、阻塞项和下一步。
4. [DECISIONS.md](DECISIONS.md)：架构决策索引。
5. [interfaces/CONTRACTS.md](interfaces/CONTRACTS.md)：跨组件、Salt、Release 与 Git 操作契约。
6. [docs/GIT_OPERATIONS.md](docs/GIT_OPERATIONS.md)：Git 初始化、提交、推送、错误处理和远端验证。
7. [docs/DEPLOYMENT_DOCKER.md](docs/DEPLOYMENT_DOCKER.md)：Docker 可行性、边界和推荐部署方式。
8. [SOURCES.md](SOURCES.md)：外部事实与官方证据索引。

## 固定 Subagent 岗位

除原有架构、产品、Salt、配置、Mihomo、ShellCrash、平台、安全、QA 和知识治理岗位外，v2.2 新增：

```text
GIT-SCM — Git 仓库初始化、分支、提交、标签、远端、推送、冲突和错误处理
```

任何已有 `GIT-SCM` 会话必须优先复用，禁止重复创建同岗位会话。

## Git 启动边界

项目实际开始时，第一项工程任务是由 `GIT-SCM`：

1. 接收远程仓库 URL、`user.name`、`user.email`、默认分支和认证方式；
2. 检查本地目录与远端状态；
3. 安全执行 `git init` 或接入已有仓库；
4. 生成首个原子提交；
5. 推送并核验远端分支 SHA；
6. 将 branch、commit、remote SHA 和工作树状态写回项目状态文件。

`user.name` 和 `user.email` 只决定提交作者/提交者元数据，不等同于推送认证。实际推送还需要 SSH key、令牌或受支持的凭据助手；认证秘密不得写入仓库、任务包、日志或聊天摘要。

## 恢复顺序

任何新会话、替换会话或上下文压缩后的会话，必须按以下顺序恢复：

```text
1. PLAN.md
2. AGENTS.md
3. PROJECT_STATE.md
4. DECISIONS.md 和相关 ADR
5. interfaces/CONTRACTS.md
6. 自身 checkpoint
7. 当前 Task Packet
8. 相关 Result/Handoff
9. 实际代码、测试和 Git 状态
```

`GIT-SCM` 还必须读取 `docs/GIT_OPERATIONS.md`，并核对本地 HEAD、upstream、remote HEAD 和工作树。不得以聊天摘要替代上述文件。

## 当前容器化结论

采用“**管理端可容器化、子节点默认原生安装**”的混合模式：

- `fleetctl` 构建环境和 subconverter：适合容器化；
- Salt Master：可以容器化，但必须使用项目自建且锁版的镜像，并持久化密钥、缓存、file roots 和 pillar roots；生产参考实现仍保留原生 systemd 方式；
- Salt Minion：安装在子节点宿主机，由 systemd 管理；
- Mihomo：透明代理/TUN 节点默认安装在宿主机；
- 已有 ShellCrash：保留宿主机原生运行，只由 Salt Minion 和本地适配器接管受管部分；
- V1 不要求任何子节点安装 Docker。
