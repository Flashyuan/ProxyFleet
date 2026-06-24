# ADR-0007：生产节点统一使用 native-mihomo 与本地 override 边界

- Status: Accepted
- Date: 2026-06-24
- Decision owner: ARCH-ORCH
- Reviewers: PRODUCT-SPEC, DATA-MIHOMO, CONTROL-SALT, SECURITY, QA-RELEASE, OPS-PLATFORM

## Context

早期计划允许已安装 ShellCrash 的节点进入 `shellcrash-adopted` 或
`shellcrash-compat`，以降低迁移阻力。用户后续明确生产方向：所有生产机器先
卸载 ShellCrash，再统一使用 ProxyFleet Minion 管控。

同时，用户要求端口白名单由 Master 提供统一配置，但 Minion 必须能保留本机
单独配置，并且本机配置不能被 Master 同步覆盖。

## Decision

1. 生产主路径改为 `native-mihomo`。
2. ShellCrash 不再是生产目标路径，只作为迁移前只读探测、卸载前评估和应急兼容
   工具；V1 不再要求 ShellCrash adopted 进入生产成功条件。
3. 新生产 Minion 必须由 ProxyFleet 安装并拥有：
   - 锁定版本 Mihomo 二进制；
   - `mihomo.service`；
   - `/etc/proxyfleet/current`、`managed`、`local` 和 `effective`；
   - 本机 loopback Mihomo API。
4. Mihomo 安装必须补齐架构级固定资产、SHA-256 和压缩格式元数据。缺少完整性
   材料时继续 fail-closed。
5. 端口白名单采用分层所有权：
   - Master 只写 `/etc/proxyfleet/managed/port-policy.yaml`；
   - Minion 本机只写 `/etc/proxyfleet/local/port-policy.yaml`；
   - Minion 合并生成 `/etc/proxyfleet/effective/port-policy.yaml`；
   - Master 永远不得覆盖、删除或置空 `/etc/proxyfleet/local`。
6. 每台 Minion 可通过受控字段选择端口策略模式：
   - `merge`：Master 全局规则 + Minion 本地规则，默认；
   - `master-only`：只应用 Master 规则；
   - `local-only`：只应用 Minion 本地规则，需显式标记例外；
   - `disabled`：ProxyFleet 不管理端口白名单，需审计记录。

## Consequences

### Positive

- 生产路径更单一，减少 ShellCrash 路径、持久化和重启覆盖的不确定性；
- Mihomo 版本、配置和 systemd 所有权更清晰；
- Master 能统一发布公共端口白名单，Minion 又能保留本机业务端口；
- 本地 override 有明确保护目录，降低被 Salt 同步误覆盖的风险。

### Negative

- 已有 ShellCrash 节点需要迁移窗口，不能无缝原地接管；
- 端口白名单合并引入新的冲突检测、审计和回滚需求；
- `local-only` 和 `disabled` 会带来策略漂移，需要在状态报告中显式展示。

## Required follow-up

1. 补齐 Mihomo `v1.19.27` 目标架构资产 URL、SHA-256、压缩格式和安装测试。
2. 实现 native-mihomo 真实 Minion 端到端：安装、release 应用、测速、选择和回滚。
3. 实现端口白名单分层配置、合并器、冲突检测和 dry-run。
4. 实现本地 override 保护测试，确认 Salt state 不覆盖 `/etc/proxyfleet/local`。
5. 更新安装教程，明确生产机器应先卸载 ShellCrash，再执行 Minion bootstrap。
