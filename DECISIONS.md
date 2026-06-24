# ProxyFleet 决策索引

> 版本：1.2
> 更新日期：2026-06-24
> 最终技术决策者：ARCH-ORCH

## 有效 ADR

| ADR | 状态 | 决策摘要 | 日期 |
|---|---|---|---|
| [ADR-0001](adr/ADR-0001-platform-and-stack.md) | Accepted | Ubuntu 22.04/24.04；Salt 3008 LTS + Mihomo + subconverter + Git | 2026-06-22 |
| [ADR-0002](adr/ADR-0002-distributed-selection.md) | Accepted | 分布式同步选择，业务流量不经过主节点 | 2026-06-22 |
| [ADR-0003](adr/ADR-0003-salt-control-plane.md) | Accepted | Salt Master/Minion 作为非 SSH 日常控制平面 | 2026-06-22 |
| [ADR-0004](adr/ADR-0004-containerization-boundary.md) | Accepted | 管理端可 Docker 化，子节点 V1 原生 systemd | 2026-06-22 |
| [ADR-0005](adr/ADR-0005-config-build-and-release-ownership.md) | Accepted | 主节点配置源唯一所有权，生成不可变 release | 2026-06-22 |
| [ADR-0006](adr/ADR-0006-git-scm-and-repository-operations.md) | Accepted | 固定 GIT-SCM 岗位，安全初始化、提交、推送、核验和错误处理 | 2026-06-23 |
| [ADR-0007](adr/ADR-0007-native-mihomo-production-and-local-overrides.md) | Accepted | 生产节点统一 native-mihomo；ShellCrash 降级为迁移工具；端口白名单支持 Master 管理层与 Minion 本地 override | 2026-06-24 |

## 决策修改规则

- 不直接编辑已接受 ADR 的结论以掩盖历史；
- 小幅澄清可追加 amendment；
- 改变结论时新建 ADR，并将旧 ADR 标记为 Superseded；
- 任何冻结决策变更必须由 ARCH-ORCH 接受；
- SECURITY/QA/GIT-SCM 的阻断必须在 PROJECT_STATE 中可见；
- Git 历史重写、force push、删除远端 tag 或合并 unrelated histories 必须有独立 Task 和明确批准。

## 待决策项

| ID | 问题 | Owner | 状态 |
|---|---|---|---|
| D-006 | 原生节点默认 proxy-only 还是 tun-host | PRODUCT-SPEC / DATA-MIHOMO | Open |
| D-007 | strict 模式如何处理离线节点 | PRODUCT-SPEC / CONTROL-SALT | Open |
| D-008 | V1 多订阅 CLI 范围 | PRODUCT-SPEC / CONFIG-BUILD | Open |
| D-009 | Git 托管平台、认证方式和默认分支保护策略 | GIT-SCM / SECURITY | Awaiting user input |
