# Task Packet — TP-0015

- Title: 代理配置、节点选择与 Salt 同步闭环
- Status: ACTIVE
- Owner role: ARCH-ORCH
- Reviewer roles: QA-RELEASE, SECURITY
- Created by: Codex
- Created at: 2026-06-24
- Related ADR: ADR-0002, ADR-0003, ADR-0005
- Contract version: interfaces/CONTRACTS.md 0.2-draft

## Objective

实现 PLAN.md 中已规划的三项关键能力最小可发布闭环：

1. 从 release 中生成并查看代理节点目录；
2. 在 Master 上选择稳定 `node_id`，写入 desired state；
3. 通过 Salt 同步 release 与 desired state，并调用 Minion 本地 Mihomo API 切换 `FLEET_PROXY`。

## Non-goals

- 不接入真实订阅 URL 和 subconverter；
- 不实现 Web UI 或公开 API；
- 不自动接受 Salt Minion key；
- 不修改系统级 Salt 配置或当前测试机服务状态；
- 不实现 ShellCrash adopted 写入路径。

## Inputs

- PLAN.md 第 6、8、9、17 节；
- interfaces/CONTRACTS.md 第 3、4、5、8、9、10、12 节；
- 已有 release compiler POC；
- 已有 Salt Master/Minion 安装脚本。

## Verified context

- VERIFIED-DOC：节点切换只改变 `FLEET_PROXY` 的期望选择，不重建 `config.yaml`。
- VERIFIED-DOC：所有严格受管节点应使用同一 release revision、provider revision 和 Mihomo 版本。
- VERIFIED-TEST：已有 release compiler POC 可生成并校验 manifest/hash。
- OBSERVED：当前仓库 HEAD 为 `aaa48fe2b6419c808113347f8796a9e12d21e74c`，工作树开始时干净。

## Repository context（涉及文件变更时必填）

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: aaa48fe2b6419c808113347f8796a9e12d21e74c
allowed_paths:
  - src/proxyfleet/**
  - tests/**
  - salt/**
  - docs/**
  - tasks/TP-0015-proxy-config-select-sync.md
  - results/RP-0015-proxy-config-select-sync.md
  - PROJECT_STATE.md
expected_commit_scope: feat(fleet): add proxy selection and salt sync
push_required: yes
tag_required: no
forbidden_history_operations: force push, amend pushed commits, reset --hard, deleting remote refs
```

## Constraints and forbidden actions

- 使用标准库和项目已有依赖，不新增第三方依赖；
- 不把订阅 URL、节点密码、UUID、API secret 输出到日志或 Salt 结果；
- Salt 同步默认需要显式命令触发，不自动变更系统；
- 失败路径必须 fail-closed，并返回契约错误码。

## Deliverables

- release 节点目录生成与查看 CLI；
- desired state 写入与状态查看 CLI；
- Mihomo API 最小驱动；
- Salt 发布目录准备和同步命令；
- Minion 侧 Salt execution module/state；
- 单元测试和文档更新。

## Required evidence/tests

- `python -m unittest`
- `python -m proxyfleet.cli build-release ...`
- `python -m proxyfleet.cli nodes ...`
- `python -m proxyfleet.cli select-node ...`
- `python -m proxyfleet.cli publish-salt ...`
- `python -m proxyfleet.cli sync --dry-run ...`

## Dependencies

- TP-0011 release compiler POC；
- TP-0012 Salt 安装 POC；
- TP-0014 安装/启停脚本。

## Failure/rollback expectations

- release hash 校验失败时拒绝同步；
- node_id 不存在时不写 desired；
- Mihomo API 选择后回读不一致时返回 `E_SELECT_VERIFY`；
- Salt 命令失败时不报告成功。

## Definition of Done

- 三项功能均有 CLI 入口和单元测试；
- dry-run 可展示同步计划；
- 文档说明 Master 如何配置、选择、同步；
- 代码和测试通过后由 GIT-SCM 提交并推送。

## Communication/Handoff targets

- QA-RELEASE：测试覆盖与发布门禁评审；
- SECURITY：确认输出脱敏、无 secret 泄露；
- GIT-SCM：提交、推送、远端 SHA 核验。
