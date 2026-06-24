# Result Packet — RP-0018

- Task ID: TP-0018
- Title: 生产 native-mihomo 与端口白名单分层规划
- Owner role: ARCH-ORCH
- Result status: COMPLETED_DOCS_ONLY
- Created at: 2026-06-24
- Base commit: e36f30bf2633d792426c8a91e3567210fc857374

## Completed

- `ACCEPTED`：新增 ADR-0007，生产主路径改为 `native-mihomo`。
- `ACCEPTED`：ShellCrash 降级为迁移前只读探测、备份和卸载辅助，不再作为 V1 生产成功条件。
- `PROPOSED`：后续开发顺序固定为：
  1. Mihomo 固定资产 URL/SHA-256/gzip 安装；
  2. native-mihomo Minion 真实端到端；
  3. 端口白名单分层配置；
  4. Minion 本地 override 保护机制。
- `PROPOSED`：端口白名单文件所有权为 `managed/local/effective` 三层，Master 不覆盖 `/etc/proxyfleet/local`。
- `PROPOSED`：端口白名单支持 `merge/master-only/local-only/disabled` 四种模式。
- `PROPOSED`：Mihomo driver 契约补充 `.gz` 资产安装流程和架构级 SHA-256 锁定格式。

## Not completed

- 未修改实现代码；
- 未填入 `component-locks.json`；
- 未执行真实 Minion 端到端；
- 未实现端口策略合并器或 Salt state。

## Changed files

- `PLAN.md`
- `PROJECT_STATE.md`
- `DECISIONS.md`
- `README.md`
- `adr/ADR-0007-native-mihomo-production-and-local-overrides.md`
- `docs/DEPLOYMENT_DOCKER.md`
- `docs/SUPPLY_CHAIN_SECURITY.md`
- `interfaces/CONTRACTS.md`
- `interfaces/MIHOMO_DRIVER.md`
- `tests/TEST_MATRIX.md`
- `tasks/TP-0018-native-mihomo-port-policy-planning.md`
- `results/RP-0018-native-mihomo-port-policy-planning.md`

## Evidence

```text
git diff --check
OK
```

```text
rg -n "SHELLCRASH_ADOPTED|通过 localhost Mihomo API 和持久化适配层接管|已有 ShellCrash 节点优先复用|保留 ShellCrash \\+ Mihomo" PLAN.md README.md docs interfaces PROJECT_STATE.md
No production-path matches after update.
```

## Risks

- `UNKNOWN`：目标生产机器上 ShellCrash 卸载方式和残留路由/防火墙规则需要实机验证。
- `UNKNOWN`：端口白名单最终落地后端是 UFW、nftables 还是两者兼容层，需 OPS/SECURITY 决策。
- `BLOCKED`：真实 installable release 仍需补齐 Mihomo/subconverter SHA-256 和真实端到端证据。

## Handoff

后续建议创建：

- TP-0019：Mihomo 固定资产、SHA-256 和 gzip 安装；
- TP-0020：native-mihomo Minion 真实端到端；
- TP-0021：端口白名单分层配置与本地 override 保护。
