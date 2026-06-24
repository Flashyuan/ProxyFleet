# Task Packet — TP-0020

- Title: native-mihomo Minion 真实端到端路径
- Status: PARTIAL
- Owner role: CONTROL-SALT / DATA-MIHOMO
- Reviewer roles: SECURITY, QA-RELEASE
- Created by: Codex
- Created at: 2026-06-24
- Parent task: TP-0019/TP-0020/TP-0021 combined implementation
- Result: results/RP-0019-0021-native-mihomo-port-policy-implementation.md

## Objective

建立 native-mihomo 的最小端到端路径：release 构建、desired state、Salt publish、
Minion 本地安装、apply desired、reload/restart 和 `FLEET_PROXY` 选择验证。

## Scope

- `src/proxyfleet/fleet.py`
- `src/proxyfleet/cli.py`
- `salt/modules/proxyfleet_mihomo.py`
- `salt/states/proxyfleet/sync.sls`
- `tests/test_fleet.py`
- `interfaces/MIHOMO_DRIVER.md`

## Completion Criteria

- 本地 harness 覆盖 build → desired → publish → install → apply → select；
- reload 失败回滚 `current`；
- PUT 后 GET 选择验证失败时尝试恢复旧选择；
- 真实物理 Minion 验证仍作为后续发布门禁，不在本任务内假报完成。
