# Task Packet — TP-0010

- Title: 建立开源组件版本锁定基线和校验工具
- Status: ACTIVE
- Owner role: SECURITY
- Reviewer roles: ARCH-ORCH, QA-RELEASE, CONFIG-BUILD
- Created by: ARCH-ORCH
- Created at: 2026-06-23
- Related ADR: ADR-0001, ADR-0004, ADR-0005, ADR-0006
- Contract version: 0.2-draft

## Objective

建立 ProxyFleet 的开源组件版本锁定清单和本地校验工具，确保后续安装项目时不使用 `latest`、浮动 tag 或自动升级关键开源组件。

## Non-goals

- 不在本任务中下载生产二进制；
- 不安装 Salt、Mihomo、subconverter 或 Docker；
- 不声明生产 release 已可用；
- 不绕过缺失 SHA-256 / digest 的 fail-closed 规则。

## Inputs

- `PLAN.md`
- `PROJECT_STATE.md`
- `interfaces/CONTRACTS.md`
- `docs/DEPLOYMENT_DOCKER.md`
- `SOURCES.md`
- 用户明确要求固定开源组件版本，后续安装不得自动更新。

## Verified context

- `VERIFIED-TEST`：Git bootstrap commit 已推送并核验远端 SHA。
- `VERIFIED-DOC`：Salt 3008.1 LTS 已由 Salt 官方发布。
- `VERIFIED-DOC`：Mihomo GitHub 当前 latest 为 `v1.19.27`。
- `VERIFIED-DOC`：subconverter GitHub release 存在 `v0.9.0`。
- `UNKNOWN`：生产目标架构对应的 Mihomo/subconverter 二进制 SHA-256 尚未下载核验。
- `UNKNOWN`：Docker 基础镜像和项目镜像 digest 尚未构建。

## Repository context

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: a2ee765305205f44aa3a33862188650e199908c6
allowed_paths:
  - component-locks.json
  - pyproject.toml
  - src/proxyfleet/**
  - tests/**
  - docs/**
  - interfaces/**
  - tasks/TP-0010-component-locking-baseline.md
  - results/RP-0010-component-locking-baseline.md
  - SOURCES.md
expected_commit_scope: security/component-locking
push_required: yes
tag_required: no
forbidden_history_operations: force push, reset --hard, unrelated histories
```

## Constraints and forbidden actions

- 禁止使用浮动版本、`latest` tag 或未固定 apt 包作为可安装项；
- 缺失必需 hash/digest/signature 元数据时必须 fail-closed；
- 不新增第三方运行时依赖；
- 不把 token、订阅 URL、私钥或节点凭据写入仓库；
- 安装策略必须显式禁止自动升级关键组件。

## Deliverables

- 机器可读组件锁定清单；
- 组件锁校验工具；
- 单元测试；
- 供应链安全文档和测试矩阵补充；
- Result Packet。

## Required evidence/tests

```text
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json
git diff --check
```

## Dependencies

- TP-0002 已完成 bootstrap push。

## Failure/rollback expectations

- 校验失败时不生成 release，不安装组件；
- 缺失 SHA-256 或 digest 的候选条目只能标记为 `candidate`，不得标记 `installable`；
- 后续组件升级必须新增锁定清单变更、测试证据和 canary 记录。

## Definition of Done

- 锁定清单可被本地校验工具解析；
- 测试覆盖浮动版本、缺失 hash/digest 和 hold_policy；
- PROJECT_STATE / Result 记录当前仍非生产 release；
- 变更由 GIT-SCM commit/push 并核验远端 SHA。

## Communication/Handoff targets

- SECURITY：维护锁定策略；
- CONFIG-BUILD：release compiler 读取锁定清单；
- QA-RELEASE：将锁定校验纳入发布门禁。
