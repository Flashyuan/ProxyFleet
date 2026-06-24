# Task Packet — TP-0018

- Title: 生产 native-mihomo 与端口白名单分层规划
- Status: ACTIVE
- Owner role: ARCH-ORCH
- Reviewer roles: PRODUCT-SPEC, DATA-MIHOMO, CONTROL-SALT, OPS-PLATFORM, SECURITY, QA-RELEASE
- Created by: Codex
- Created at: 2026-06-24
- Related ADR: ADR-0007
- Contract version: interfaces/CONTRACTS.md, interfaces/MIHOMO_DRIVER.md

## Objective

根据用户最新方向更新开发文档：

1. 补齐 Mihomo 固定版本和 SHA-256 安装的规划；
2. 明确 native-mihomo Minion 真实端到端为下一主线；
3. 增加端口白名单分层配置；
4. 增加 Minion 本地 override 保护机制；
5. 将 ShellCrash 从生产主路径降级为迁移前只读探测和备份/卸载辅助。

## Non-goals

- 不修改实现代码；
- 不直接改 `component-locks.json`；
- 不执行真实系统安装；
- 不提交或推送 Git；
- 不引入新第三方依赖。

## Inputs

- 用户明确生产方向：所有生产机器卸载 ShellCrash，统一使用本项目 Minion 管控；
- `PLAN.md`；
- `PROJECT_STATE.md`；
- `interfaces/CONTRACTS.md`；
- `interfaces/MIHOMO_DRIVER.md`；
- `tests/TEST_MATRIX.md`；
- `docs/DEPLOYMENT_DOCKER.md`；
- `docs/SUPPLY_CHAIN_SECURITY.md`。

## Verified context

- `OBSERVED`：当前 `component-locks.json` 中 Mihomo/subconverter SHA 仍为空；
- `OBSERVED`：当前代码已有 Mihomo fail-closed 安装 POC；
- `OBSERVED`：当前文档仍包含 ShellCrash adopted/保留原生运行的旧生产路径表述；
- `INFERRED`：端口白名单需要 Master managed 层和 Minion local 层分离，否则 Salt 同步可能覆盖本机业务端口。

## Repository context

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: e36f30bf2633d792426c8a91e3567210fc857374
allowed_paths:
  - PLAN.md
  - PROJECT_STATE.md
  - DECISIONS.md
  - README.md
  - adr/**
  - docs/**
  - interfaces/**
  - tests/TEST_MATRIX.md
  - tasks/TP-0018-native-mihomo-port-policy-planning.md
  - results/RP-0018-native-mihomo-port-policy-planning.md
push_required: no
tag_required: no
forbidden_history_operations: force push, reset --hard, deleting remote refs
```

## Deliverables

- ADR-0007；
- PLAN v2.3 updates；
- PROJECT_STATE v1.3 updates；
- interface/test/deployment/security docs updates；
- Result Packet。

## Required evidence/tests

- `git diff --check`
- 文档 grep 确认 ShellCrash 生产接管旧表述已替换。

## Definition of Done

- 后续开发顺序明确为 Mihomo 锁定安装 → native-mihomo E2E → 端口白名单分层 → local override 保护；
- ShellCrash 不再是生产成功条件；
- 端口白名单所有权和保护目录写入契约；
- 本轮不声称实现已完成。
