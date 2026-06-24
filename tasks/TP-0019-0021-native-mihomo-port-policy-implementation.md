# Task Packet — TP-0019/TP-0020/TP-0021

- Title: Mihomo 锁定安装、native-mihomo 端到端和端口白名单 override 保护
- Status: ACTIVE
- Owner role: ARCH-ORCH
- Reviewer roles: DATA-MIHOMO, CONTROL-SALT, CONFIG-BUILD, SECURITY, QA-RELEASE
- Created by: Codex
- Created at: 2026-06-24
- Related ADR: ADR-0007
- Contract version: interfaces/CONTRACTS.md, interfaces/MIHOMO_DRIVER.md

## Objective

按 PLAN v2.3 实现：

1. Mihomo 固定资产 URL / SHA-256 / gzip 安装；
2. native-mihomo Minion 端到端 harness；
3. 端口白名单分层配置；
4. Minion 本地 override 保护机制。

## Non-goals

- 不安装或修改当前宿主机真实 Mihomo/systemd；
- 不执行真实 Salt Master/Minion 生产 apply；
- 不实现 UFW/nftables 真正防火墙落地；
- 不处理 ShellCrash adopted；
- 不引入新第三方依赖。

## Inputs

- `PLAN.md` Phase 3、16.5、16.6；
- `ADR-0007`；
- `component-locks.json`；
- `interfaces/CONTRACTS.md`；
- `interfaces/MIHOMO_DRIVER.md`；
- TP-0017 代码基线。

## Verified context

- `VERIFIED-DOC`：Mihomo v1.19.27 官方 release 提供 `linux-amd64` 和 `linux-arm64` gzip 资产及 SHA-256；
- `VERIFIED-TEST`：TP-0017 已有 install fail-closed POC；
- `OBSERVED`：真实测试机端到端仍需用户环境执行。

## Repository context

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: e36f30bf2633d792426c8a91e3567210fc857374
allowed_paths:
  - component-locks.json
  - src/proxyfleet/**
  - salt/**
  - tests/**
  - docs/**
  - interfaces/**
  - PLAN.md
  - PROJECT_STATE.md
  - tasks/**
  - results/**
expected_commit_scope: feat(minion): lock mihomo install and add port policy layers
push_required: yes
tag_required: no
```

## Required evidence/tests

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json`
- `python3 -m py_compile src/proxyfleet/*.py salt/modules/proxyfleet_mihomo.py`
- `bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh`
- `git diff --check`

## Definition of Done

- Mihomo installable artifacts pass lock validation；
- gzip install path has unit tests；
- local E2E harness covers build → desired → publish → install → apply → select；
- port policy merge/conflict/CLI tests pass；
- Salt state does not manage `/etc/proxyfleet/local/port-policy.yaml`；
- SECURITY and QA release gate allow push.
