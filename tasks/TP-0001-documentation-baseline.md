# Task Packet — TP-0001

- Title: 补齐工程治理、恢复文件和 Docker 架构决策
- Status: DONE
- Owner role: DOCS-KNOWLEDGE
- Reviewer roles: ARCH-ORCH, OPS-PLATFORM, SECURITY
- Created by: ARCH-ORCH
- Created at: 2026-06-22
- Related ADR: ADR-0001..0005
- Contract version: 0.1-draft

## Objective

补齐 PLAN 引用但未交付的文件，建立固定 Subagent 岗位、唯一会话复用、通信和上下文恢复制度，并明确 Docker 部署边界。

## Non-goals

- 不实现 ProxyFleet 代码；
- 不提供可执行 Docker Compose；
- 不声称任何 POC 已通过。

## Inputs

- 用户确认的产品方向；
- Ubuntu 22.04/24.04 基线；
- Salt、Mihomo、Docker 官方资料。

## Constraints

- 禁止虚构 session ID；
- 所有角色必须固定且可复用；
- Docker 决策必须区分管理端和子节点；
- 文档引用必须实际存在。

## Deliverables

- PLAN、AGENTS、PROJECT_STATE、DECISIONS、ADR、CONTRACTS；
- Checkpoints、Session Registry；
- Task/Result/Handoff/RFC 模板；
- Docker 评估；
- SOURCES。

## Required evidence/tests

- 文件存在性；
- PLAN 24.5 恢复顺序存在；
- 所有 checkpoint 文件存在；
- 所有 ADR 在 DECISIONS 中可定位；
- 打包 ZIP 可打开。

## Definition of Done

上述文件全部生成并通过静态检查。


## Amendment — v2.2

根据新增需求，文档基线范围扩展为包含固定 GIT-SCM 岗位、Git 操作手册、ADR-0006、Git 接口契约和仓库 bootstrap Task。该 amendment 不代表实际仓库已初始化。
