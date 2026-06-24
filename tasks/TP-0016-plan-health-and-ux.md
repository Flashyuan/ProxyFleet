# Task Packet — TP-0016

- Title: 明确节点测速显示与最少步骤运维体验规划
- Status: ACTIVE
- Owner role: ARCH-ORCH
- Reviewer roles: DATA-MIHOMO, CONTROL-SALT, QA-RELEASE
- Created by: Codex
- Created at: 2026-06-24
- Related ADR: ADR-0002, ADR-0003, ADR-0005
- Contract version: interfaces/CONTRACTS.md 0.2-draft, interfaces/MIHOMO_DRIVER.md 0.1-draft

## Objective

在 `PLAN.md` 中明确补充：

1. “代理节点测速显示”的用户可见功能、数据字段、边界、错误处理和测试要求；
2. 安装、配置、节点同步切换应尽量使用最少步骤和最少命令的产品要求；
3. 明确哪些安全步骤不能因为减少命令而被省略。

## Non-goals

- 本任务不编写功能代码；
- 不修改安装脚本；
- 不修改接口契约文件；
- 不执行系统安装或 Salt/Mihomo 真实操作。

## Inputs

- `PLAN.md`
- `interfaces/CONTRACTS.md`
- `interfaces/MIHOMO_DRIVER.md`
- `docs/INSTALL_MASTER.md`
- `docs/INSTALL_MINION.md`
- `docs/OPERATIONS.md`
- DATA-MIHOMO、CONTROL-SALT、QA-RELEASE 只读审计意见

## Verified context

- VERIFIED-DOC：`PLAN.md` 已有 `health verify`，但缺少“代理节点测速显示”的明确用户命令规格。
- VERIFIED-DOC：`PLAN.md` 已有安装、配置构建、节点切换流程，但当前用户体验分散为多个命令。
- VERIFIED-DOC：Salt key 人工核验、组件锁定、secret 不入 Git/日志是既定安全边界。

## Repository context（涉及文件变更时必填）

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: 861e5bc7d4ed5c2c9fc9fea8a0aa143ccc433aa0
allowed_paths:
  - PLAN.md
  - tasks/TP-0016-plan-health-and-ux.md
  - results/RP-0016-plan-health-and-ux.md
expected_commit_scope: docs(plan): specify node health display and streamlined operations
push_required: no
tag_required: no
forbidden_history_operations: force push, reset --hard, deleting remote refs
```

## Constraints and forbidden actions

- 不把 planned 能力写成已实现；
- 不移除人工 Salt key 核验；
- 不引入会泄露订阅 URL、节点密码、UUID、API secret 的状态字段；
- 不承诺分布式网络原子事务。

## Deliverables

- `PLAN.md` 新增或更新相关章节；
- Result Packet 记录审计意见、修改内容和未实现状态。

## Required evidence/tests

- `git diff --check`
- `rg` 核对新增章节存在

## Dependencies

- 复用已有 DATA-MIHOMO、CONTROL-SALT、QA-RELEASE 会话。

## Failure/rollback expectations

- 若 subagent 审计指出安全冲突，应暂停并报告；
- 若规划与既有 ADR 冲突，应改为 RFC/ADR，不直接改写冻结决策。

## Definition of Done

- `PLAN.md` 明确包含节点测速显示功能；
- `PLAN.md` 明确最少步骤/命令的目标操作链；
- 保留人工核验与安全边界；
- 审计意见已纳入或记录为未采纳原因。

## Communication/Handoff targets

- DOCS-KNOWLEDGE：后续可据此生成完整教程；
- GIT-SCM：若用户要求发布，再提交推送。
