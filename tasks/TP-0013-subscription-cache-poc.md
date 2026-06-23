# Task Packet — TP-0013

- Title: 订阅状态解析与 Last Known Good 缓存 POC
- Status: ACTIVE
- Owner role: CONFIG-BUILD
- Reviewer roles: QA-RELEASE, SECURITY
- Created by: ARCH-ORCH
- Created at: 2026-06-23
- Related ADR: ADR-0005
- Contract version: 0.2-draft

## Objective

实现订阅响应头 `Subscription-Userinfo` 解析、订阅正文基础校验和 Last Known Good 缓存 POC，确保订阅失败、空正文或 HTML 错误页不会覆盖最后有效 Provider 快照。

## Non-goals

- 不访问真实订阅 URL；
- 不保存订阅 URL 或 token；
- 不调用 subconverter；
- 不生成生产 Provider；
- 不声明订阅集成已完成。

## Inputs

- `PLAN.md`
- `interfaces/CONTRACTS.md`
- `docs/SUPPLY_CHAIN_SECURITY.md`
- 本地测试 fixture。

## Verified context

- `VERIFIED-TEST`：release compiler POC 已可生成并校验本地 release。
- `VERIFIED-DOC`：订阅 URL 只保存在主节点，子节点只收到构建后的 Provider 快照。
- `VERIFIED-DOC`：订阅失败时必须使用缓存，不发布新 Provider。

## Repository context

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: 0551c30254c542eb5eab4582d8585eb0067e74fa
allowed_paths:
  - src/proxyfleet/**
  - tests/**
  - tasks/TP-0013-subscription-cache-poc.md
  - results/RP-0013-subscription-cache-poc.md
  - PROJECT_STATE.md
expected_commit_scope: config-build/subscription-cache
push_required: yes
tag_required: no
forbidden_history_operations: force push, reset --hard, unrelated histories
```

## Constraints and forbidden actions

- 禁止把订阅 URL、token 或响应原文写入日志/Result；
- 未知用量字段必须为 `null`，不得伪造成 0；
- 空正文、HTML、非 2xx、超时类错误不得覆盖 Last Known Good；
- 缓存写入必须原子化；
- 错误摘要必须脱敏。

## Deliverables

- 订阅状态解析模块；
- Last Known Good 缓存写入/读取；
- 单元测试；
- Result Packet。

## Required evidence/tests

```text
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m proxyfleet.cli subscription-status --header "upload=1; download=2; total=3; expire=4"
git diff --check
```

## Dependencies

- TP-0011 release compiler POC。

## Failure/rollback expectations

- 订阅失败时保留旧缓存；
- 缓存写入失败时不删除旧缓存；
- 解析失败返回可定位错误，不吞掉异常。

## Definition of Done

- 单元测试覆盖 header 正常解析、缺失字段、空正文、HTML 正文、失败不覆盖缓存；
- CLI 可输出脱敏 subscription status JSON；
- 变更由 GIT-SCM commit/push，若远端网络不可用则记录 SCM_BLOCKED。

## Communication/Handoff targets

- CONFIG-BUILD：后续接入真实 fetcher 和 subconverter；
- SECURITY：复核 secret/订阅 URL 不落盘；
- QA-RELEASE：扩展故障注入测试。
