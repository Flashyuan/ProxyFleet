# Task Packet — TP-0014

- Title: Master/Minion 安装与项目启停卸载脚本
- Status: ACTIVE
- Owner role: CONTROL-SALT
- Reviewer roles: SECURITY, QA-RELEASE, OPS-PLATFORM
- Created by: ARCH-ORCH
- Created at: 2026-06-23
- Related ADR: ADR-0003, ADR-0004
- Contract version: 0.2-draft

## Objective

提供当前项目的 Master/Minion 原生 systemd 安装、启动、停止、状态查看和卸载脚本，并给出主节点和新 Minion 测试机的中文安装配置说明。

## Non-goals

- 不在本任务中自动执行系统安装；
- 不自动接受 Minion key；
- 不修改云防火墙或 UFW；
- 不启用公网 `salt-api`；
- 不安装 Mihomo 或 ShellCrash。

## Inputs

- `tasks/TP-0012-salt-poc.md`
- `component-locks.json`
- `docs/SUPPLY_CHAIN_SECURITY.md`
- Salt 官方 Ubuntu/Debian 安装指南。

## Verified context

- `OBSERVED`：当前测试机是 Ubuntu 22.04.5 LTS，用户属于 sudo 组。
- `VERIFIED-DOC`：Salt 必须固定到 3008.1，安装后 hold/pin。
- `VERIFIED-DOC`：Minion key 必须人工核验后接受。

## Repository context

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: 01bad9e1fa8a4f06061053646a7a561c73efab31
allowed_paths:
  - scripts/**
  - docs/INSTALL_MASTER.md
  - docs/INSTALL_MINION.md
  - docs/OPERATIONS.md
  - tasks/TP-0014-salt-install-scripts.md
  - results/RP-0014-salt-install-scripts.md
  - PROJECT_STATE.md
expected_commit_scope: control-salt/install-scripts
push_required: yes
tag_required: no
forbidden_history_operations: force push, reset --hard, unrelated histories
```

## Constraints and forbidden actions

- 脚本必须使用 repo-local 项目路径，不把 secrets 写入 Git；
- Salt 包版本固定为 3008.1；
- 安装后必须 `apt-mark hold`；
- 卸载默认不删除 `/etc/salt/pki`，除非显式传入危险参数；
- 脚本必须支持 `start`、`stop`、`restart`、`status`、`uninstall`；
- 写系统文件和 apt 操作需用户二次确认后执行。

## Deliverables

- `scripts/proxyfleet-master.sh`
- `scripts/proxyfleet-minion.sh`
- 中文 Master 安装文档；
- 中文 Minion 安装文档；
- 中文启停卸载文档；
- Result Packet。

## Required evidence/tests

```text
bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh
scripts/proxyfleet-master.sh preflight
PYTHONPATH=src python3 -m unittest discover -s tests
git diff --check
```

## Dependencies

- 需要用户二次确认后才能执行 `install` 或 `uninstall --purge-data`。

## Failure/rollback expectations

- 安装失败时保留 apt/systemd 错误输出；
- 卸载默认保留 Salt PKI，避免破坏 Minion 信任关系；
- 脚本检测到非 Ubuntu 22.04/24.04 时 fail-closed。

## Definition of Done

- 脚本语法通过；
- 文档说明 Master 当前测试机配置步骤；
- 文档说明新 Minion 测试机安装配置和 key 接受流程；
- 启停卸载命令清晰；
- 变更提交并推送远端核验。

## Communication/Handoff targets

- SECURITY：复核 PKI、key、端口和 secret 边界；
- QA-RELEASE：复核脚本 dry-run / syntax 证据；
- OPS-PLATFORM：复核 systemd 和 Ubuntu 约束。
