# Task Packet — TP-0011

- Title: 配置源校验与 release compiler POC
- Status: ACTIVE
- Owner role: CONFIG-BUILD
- Reviewer roles: QA-RELEASE, SECURITY, DATA-MIHOMO
- Created by: ARCH-ORCH
- Created at: 2026-06-23
- Related ADR: ADR-0005
- Contract version: 0.2-draft

## Objective

实现本地配置源校验和不可变 release 构建 POC，生成 `config.yaml`、Provider 文件、规则文件和 `manifest.json`，并对所有输出计算 SHA-256。

## Non-goals

- 不联网获取真实订阅；
- 不调用真实 subconverter；
- 不安装或运行 Mihomo；
- 不发布到真实子节点；
- 不处理生产 secrets。

## Inputs

- `interfaces/CONTRACTS.md`
- `component-locks.json`
- 本地 fixture 配置源
- 用户要求开源组件固定版本且安装后不自动更新

## Verified context

- `VERIFIED-TEST`：Git bootstrap 和组件锁定基线已推送并核验远端 SHA。
- `VERIFIED-TEST`：`component-locks.json` 可通过本地校验。
- `UNKNOWN`：真实订阅 fixture 和真实 subconverter 输出尚未提供。

## Repository context

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: 7cd89810e409b4210d7e694f4d9c71e9664c7798
allowed_paths:
  - src/proxyfleet/**
  - tests/**
  - tasks/TP-0011-config-build-poc.md
  - results/RP-0011-config-build-poc.md
  - PROJECT_STATE.md
expected_commit_scope: config-build-poc
push_required: yes
tag_required: no
forbidden_history_operations: force push, reset --hard, unrelated histories
```

## Constraints and forbidden actions

- 不新增第三方依赖；
- 输出路径不得逃逸 release 目录；
- `FLEET_PROXY` 必须存在且类型为 `select`；
- Provider 引用必须存在；
- 规则顺序不可重排；
- 缺少组件锁或组件锁校验失败时必须阻断构建；
- 生成物必须进入临时目录，测试结束后可删除。

## Deliverables

- release compiler POC；
- 配置源校验；
- manifest hash 生成；
- 单元测试和 fixture；
- Result Packet。

## Required evidence/tests

```text
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json
PYTHONPATH=src python3 -m proxyfleet.cli build-release tests/fixtures/config-src <tmpdir> --revision 1 --source-git-commit <sha>
git diff --check
```

## Dependencies

- TP-0010 组件锁定基线。

## Failure/rollback expectations

- 构建失败不得污染既有 release；
- 输出路径逃逸、缺少 Provider、缺少 `FLEET_PROXY`、组件锁失败均 fail-closed；
- 后续真实发布必须保留 Last Known Good，本 POC 只验证 manifest 和目录产物。

## Definition of Done

- 单元测试覆盖正常构建和关键失败路径；
- `manifest.json` 包含 release revision、source commit、Mihomo 版本和文件 SHA-256；
- 变更由 GIT-SCM commit/push 并核验远端 SHA。

## Communication/Handoff targets

- CONTROL-SALT：使用 release 目录作为 Salt 分发输入；
- DATA-MIHOMO：使用 `config.yaml` 和 Provider 作为 native driver 输入；
- QA-RELEASE：扩展集成测试和故障注入。
