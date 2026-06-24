# Task Packet — TP-0021

- Title: 端口白名单分层配置与 Minion local override 保护
- Status: IMPLEMENTED
- Owner role: OPS-PLATFORM / CONTROL-SALT
- Reviewer roles: SECURITY, QA-RELEASE
- Created by: Codex
- Created at: 2026-06-24
- Parent task: TP-0019/TP-0020/TP-0021 combined implementation
- Result: results/RP-0019-0021-native-mihomo-port-policy-implementation.md

## Objective

实现 Master managed 端口白名单、Minion local override 和 effective policy 三层模型，
使 Master 能统一下发公共规则，同时不覆盖子节点本地规则。

## Scope

- `src/proxyfleet/port_policy.py`
- `src/proxyfleet/cli.py`
- `src/proxyfleet/fleet.py`
- `salt/modules/proxyfleet_mihomo.py`
- `salt/states/proxyfleet/sync.sls`
- `tests/test_port_policy.py`
- `tests/test_fleet.py`
- `interfaces/CONTRACTS.md`
- `tests/TEST_MATRIX.md`

## Completion Criteria

- 支持 `merge/master-only/local-only/disabled`；
- managed/local 合并保留规则来源；
- 冲突 fail-closed 且不覆盖现有 effective；
- Salt state 不管理、删除或覆盖 `/etc/proxyfleet/local/port-policy.yaml`；
- UFW/nftables 落地后端明确为后续任务。
