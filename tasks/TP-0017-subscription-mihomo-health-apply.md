# Task Packet — TP-0017

- Title: 订阅拉取转换、Mihomo 安装配置、节点测速和最少步骤 apply
- Status: ACTIVE
- Owner role: ARCH-ORCH
- Reviewer roles: CONFIG-BUILD, DATA-MIHOMO, CONTROL-SALT, SECURITY, QA-RELEASE
- Created by: Codex
- Created at: 2026-06-24
- Related ADR: ADR-0002, ADR-0003, ADR-0005
- Contract version: interfaces/CONTRACTS.md 0.2-draft, interfaces/MIHOMO_DRIVER.md 0.1-draft

## Objective

按 `PLAN.md` 推进下一轮实现，优先解决：

1. 订阅 URL 拉取与 Provider 转换；
2. 订阅 Provider、自建节点和自定义 rule 生成可用 release/config；
3. 原生 Mihomo 安装配置的可执行 state/脚本语义；
4. 代理节点测速显示；
5. 最少步骤 apply/select 同步入口。

## Non-goals

- 不绕过 Salt key 人工核验；
- 不下载或安装缺少 SHA-256 锁定的 Mihomo 二进制；
- 不引入新第三方依赖；
- 不实现 Web UI；
- 不把订阅 URL、API secret、节点凭据写入 Git、日志或 Result。

## Inputs

- `PLAN.md` 6、8、9.4、15.1、16.3、16.4、17；
- `interfaces/CONTRACTS.md`；
- `interfaces/MIHOMO_DRIVER.md`；
- `component-locks.json`；
- TP-0015 代码与测试。

## Verified context

- VERIFIED-DOC：订阅 URL 只保存在 Master，子节点只收到构建后的 Provider 快照。
- VERIFIED-DOC：Mihomo 安装必须有锁定版本和 SHA-256；缺失完整性时 fail-closed。
- VERIFIED-DOC：节点测速是观测能力，不得改变 desired state 或 `FLEET_PROXY` 当前选择。
- OBSERVED：当前 `component-locks.json` 中 Mihomo/subconverter SHA 仍为 `null`。
- OBSERVED：当前工作树包含 TP-0016 PLAN/SOURCES/Task/Result 文档改动，需纳入本轮提交或先提交。

## Repository context（涉及文件变更时必填）

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: 861e5bc7d4ed5c2c9fc9fea8a0aa143ccc433aa0
allowed_paths:
  - src/proxyfleet/**
  - salt/**
  - scripts/**
  - tests/**
  - docs/**
  - PLAN.md
  - SOURCES.md
  - PROJECT_STATE.md
  - component-locks.json
  - tasks/TP-0016-plan-health-and-ux.md
  - tasks/TP-0017-subscription-mihomo-health-apply.md
  - results/RP-0016-plan-health-and-ux.md
  - results/RP-0017-subscription-mihomo-health-apply.md
expected_commit_scope: feat(fleet): add subscription build health and apply flow
push_required: yes
tag_required: no
forbidden_history_operations: force push, reset --hard, deleting remote refs, accepting Salt keys automatically
```

## Constraints and forbidden actions

- 订阅 URL 必须通过环境变量或本机 secret 引用读取，不提交真实 URL；
- 订阅失败不得覆盖 Last Known Good；
- Mihomo 安装缺少 SHA 时必须返回 `E_COMPONENT_INTEGRITY_MISSING`；
- 节点测速必须短超时、允许列表 URL、脱敏输出；
- 所有新功能必须有单元测试或 CLI fixture 证据。

## Deliverables

- 订阅 Provider 拉取/转换能力；
- release 构建支持 subscription + local_file + rules；
- Mihomo 安装配置 state/模块能力；
- 节点健康/测速 CLI 与缓存；
- 最少步骤 apply/select 入口；
- 安装脚本同步 Salt assets；
- 文档和 Result Packet。

## Required evidence/tests

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `python3 -m py_compile src/proxyfleet/*.py salt/modules/proxyfleet_mihomo.py`
- `bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh`
- CLI fixture 覆盖 subscription build、nodes --refresh、apply --dry-run
- `git diff --check`

## Dependencies

- CONFIG-BUILD、DATA-MIHOMO、CONTROL-SALT、QA-RELEASE 复用既有会话审计。

## Failure/rollback expectations

- 若组件完整性缺失，Mihomo install state 只能 fail-closed；
- 若订阅转换失败且无 LKG，阻断构建；
- 若测速失败，只标记节点 health failed/stale，不改变选择。

## Definition of Done

- 四个优先能力均有可运行入口；
- 安全门禁不降级；
- QA-RELEASE 无 P1/P2 阻断；
- GIT-SCM 完成 commit/push 并核验远端 SHA。

## Communication/Handoff targets

- GIT-SCM：最终提交与推送；
- DOCS-KNOWLEDGE：后续完整教程更新。
