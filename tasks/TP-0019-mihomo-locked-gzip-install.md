# Task Packet — TP-0019

- Title: Mihomo 固定资产 URL / SHA-256 / gzip 安装
- Status: IMPLEMENTED
- Owner role: DATA-MIHOMO
- Reviewer roles: CONFIG-BUILD, SECURITY, QA-RELEASE
- Created by: Codex
- Created at: 2026-06-24
- Parent task: TP-0019/TP-0020/TP-0021 combined implementation
- Result: results/RP-0019-0021-native-mihomo-port-policy-implementation.md

## Objective

将 Mihomo `v1.19.27` 固定到架构级官方 gzip 资产 URL、SHA-256 和目标路径，
并在 Minion 安装时执行下载、压缩包 SHA 校验、gzip 解压、版本探测和原子替换。

## Scope

- `component-locks.json`
- `src/proxyfleet/component_locks.py`
- `salt/modules/proxyfleet_mihomo.py`
- `tests/test_component_locks.py`
- `tests/test_fleet.py`
- `interfaces/COMPONENT_LOCKS.md`
- `interfaces/MIHOMO_DRIVER.md`

## Completion Criteria

- 锁文件校验通过；
- gzip 安装成功路径有单元测试；
- SHA 缺失、版本不匹配、systemd 失败路径 fail-closed；
- 不引入浮动版本或自动更新。
