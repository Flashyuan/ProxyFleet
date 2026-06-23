# Task Packet — TP-0012

- Title: Salt 3008.1 原生 Master/Minion POC
- Status: READY
- Owner role: CONTROL-SALT
- Reviewer roles: SECURITY, QA-RELEASE, OPS-PLATFORM, ARCH-ORCH
- Created by: CONTROL-SALT
- Created at: 2026-06-23
- Related ADR: ADR-0003, ADR-0001, ADR-0004, ADR-0005
- Contract version: 0.2-draft

## Objective

在 Ubuntu 原生 systemd 环境中验证 Salt 3008.1 Master/Minion 控制平面 POC，形成可复现证据，证明 ProxyFleet 可以使用 Salt 执行节点身份接入、分组、基础 State、远程命令、返回结果、Master 重启和 Minion 离线恢复场景。

本任务必须特别验证 Salt 安装的版本锁定、APT 源签名、apt pin 和 apt hold 状态，确保后续生产安装不会漂移到未批准版本。

## Non-goals

- 不实现 `fleetctl` 正式 CLI；
- 不实现完整 release compiler、Mihomo 安装或配置发布；
- 不安装 ShellCrash，也不处理 ShellCrash adopted 模式；
- 不验证 Docker Salt Master，Docker 控制面由 OPS-PLATFORM 专项任务负责；
- 不开放公网 `salt-api`，也不引入自研常驻 Agent；
- 不提交生产 secrets、订阅 URL、Minion 私钥、Master 私钥或节点凭据；
- 不声明 Salt POC 已可生产发布，POC 通过后仍需 SECURITY 和 QA-RELEASE 门禁。

## Inputs

- `PLAN.md`
- `PROJECT_STATE.md`
- `adr/ADR-0003-salt-control-plane.md`
- `component-locks.json`
- `interfaces/CONTRACTS.md`
- `docs/SUPPLY_CHAIN_SECURITY.md`
- `docs/DEPLOYMENT_DOCKER.md`
- `tasks/TP-0010-component-locking-baseline.md`

## Verified context

- `VERIFIED-DOC`：PLAN 已接受 Salt 3008 LTS + Mihomo + subconverter + Git 作为核心选型。
- `VERIFIED-DOC`：ADR-0003 已接受 Salt Master/Minion 作为日常控制平面，不使用 SSH 批量执行。
- `VERIFIED-DOC`：ADR-0003 要求 Minion key 必须核验后接受，Master 4505/4506 应限制来源，不启用公网 `salt-api`。
- `VERIFIED-DOC`：ADR-0003 要求 Salt 版本锁定 3008.x 明确 point release。
- `VERIFIED-DOC`：`component-locks.json` 将 `salt` 锁定为 `3008.1`，包包括 `salt-master` 和 `salt-minion`，安装策略要求 exact version、禁用自动升级并安装后 hold。
- `VERIFIED-DOC`：PROJECT_STATE 当前将 Salt 控制平面标为 `NOT_STARTED`，阻塞项为“需 POC”。
- `VERIFIED-DOC`：TP-0010 后续 Handoff 明确 Salt POC 必须验证 apt pin/hold。
- `OBSERVED`：当前仓库已有 Git bootstrap 和组件锁定基线，实际 POC 尚未开始。
- `UNKNOWN`：测试 VM 的真实 IP、网络安全组、UFW 状态、CPU 架构和云厂商防火墙配置尚未登记。
- `UNKNOWN`：Salt 官方 DEB 仓库在目标 Ubuntu 22.04/24.04 上暴露的完整 APT 包版本字符串尚未在测试 VM 中验证。
- `UNKNOWN`：arm64 smoke test 环境是否可用尚未登记。

## Repository context（涉及文件变更时必填）

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: 7cd89810e409b4210d7e694f4d9c71e9664c7798
allowed_paths:
  - tasks/TP-0012-salt-poc.md
  - results/RP-0012-salt-poc.md
  - salt/**
  - tests/**
  - docs/**
  - checkpoints/CONTROL-SALT.md
expected_commit_scope: control-salt/native-salt-poc
push_required: yes
tag_required: no
forbidden_history_operations: force push, reset --hard, unrelated histories, deleting remote refs, rewriting existing tags
```

## Constraints and forbidden actions

- 必须使用 Salt `3008.1`，禁止 `latest`、浮动仓库通道或未固定版本安装；
- 必须使用 Salt 官方 DEB 仓库，并记录仓库签名材料和 APT 源配置；
- 必须显式配置 apt pin，使 Salt 相关包只能安装批准的 3008.1 point release；
- 必须在安装后执行 `apt-mark hold`，至少覆盖 `salt-master`、`salt-minion` 和实际安装中引入的 Salt 关键包；
- 必须记录 `apt-cache policy`、`apt-mark showhold` 和已安装包版本作为证据；
- 必须验证 `unattended-upgrades` 或等价自动升级机制不会升级 Salt 关键包；
- Minion key 必须由人工核验指纹后接受，禁止自动接受未知 key；
- Master 仅开放 Salt 必需 TCP 4505/4506，且应限制到受管节点来源；
- 禁止启用公网 `salt-api`；
- Master PKI、Minion 私钥、订阅 URL、节点凭据和 API secret 不得写入 Git、日志或 Result；
- 不得以 SSH 批量执行替代 Salt 控制面验证；SSH 仅可作为一次性 VM 准备和故障排查通道；
- POC State 必须保持最小化，不得修改宿主机路由、TUN、DNS 或 Mihomo 生产路径；
- 任何高风险网络变更必须先停止并回报 ARCH-ORCH，不得在本任务内自行扩展范围。

## Deliverables

- Salt 3008.1 原生 Master/Minion POC 的最小 State、Pillar 或 Orchestrate 草案；
- Ubuntu 22.04 主矩阵验证证据；
- Ubuntu 24.04 兼容矩阵验证证据，若环境缺失则标记 `BLOCKED` 并说明缺口；
- Salt key 生命周期验证记录：pending、fingerprint 核验、accept、通信成功、reject/delete 失败路径；
- 基础目标分组验证记录，至少覆盖环境、驱动、OS baseline 或 release channel 之一；
- 基础 State 执行验证记录，至少包含无害文件或 test state 的 apply 成功与失败返回；
- Master 重启后 Minion 自动恢复连接的验证记录；
- Minion 离线后恢复连接并执行最新状态的 reconcile 验证记录；
- APT pin/hold、版本锁和自动升级禁止证据；
- Result Packet：`results/RP-0012-salt-poc.md`；
- Handoff 给 SECURITY、QA-RELEASE、OPS-PLATFORM 和 GIT-SCM。

## Required evidence/tests

必须保存可复现命令摘要和脱敏输出，至少包含：

```text
lsb_release -a
uname -m
apt-cache policy salt-master salt-minion
dpkg-query -W 'salt*'
apt-mark showhold
systemctl status salt-master --no-pager
systemctl status salt-minion --no-pager
salt-key -L
salt-key -F
salt '<minion-id>' test.ping
salt '<minion-id>' grains.items
salt '<minion-id>' state.apply <poc-state> test=true
salt '<minion-id>' state.apply <poc-state>
salt-run jobs.list_jobs
ss -ltnp | grep -E ':4505|:4506'
git diff --check
```

故障和恢复证据至少包含：

```text
systemctl restart salt-master
salt '<minion-id>' test.ping
systemctl stop salt-minion
salt '<minion-id>' test.ping
systemctl start salt-minion
salt '<minion-id>' state.apply <reconcile-or-poc-state>
```

安全证据至少包含：

```text
apt-cache policy <salt-related-package>
apt-mark showhold
grep -R "salt" /etc/apt/preferences.d /etc/apt/sources.list.d
systemctl is-enabled salt-master
systemctl is-enabled salt-minion
```

证据输出必须脱敏，不得包含私钥、token、订阅 URL、节点凭据或生产 IP 的敏感上下文。

## Dependencies

- TP-0010 组件锁定基线已提供 `component-locks.json`；
- 需要至少 1 台 Ubuntu 22.04 x86_64 Master 测试机和 1 台 Ubuntu 22.04 x86_64 Minion 测试机；
- 需要 1 台 Ubuntu 24.04 x86_64 Minion 测试机用于兼容验证；
- 需要 SECURITY 确认可用于 POC 的网络来源限制方式；
- 需要 QA-RELEASE 确认 POC 证据目录和最小验收矩阵；
- 如使用云防火墙或 UFW 写操作，必须先记录当前规则并取得对应授权。

## Failure/rollback expectations

- Salt 包版本无法精确锁定到 `3008.1` 时，任务必须 `BLOCKED`，不得安装浮动版本继续；
- APT 仓库签名、keyring 或 pin/hold 无法验证时，任务必须 fail-closed；
- Minion key 指纹无法人工核验时，不得 accept key；
- Master 或 Minion 安装失败时，必须保留安装日志摘要并停止扩散；
- State 执行失败时，不得静默重试到成功，必须记录 jid、返回码和失败原因；
- Master PKI 异常、key 误接受或疑似 secret 泄露时，立即通知 SECURITY 并设置发布阻断建议；
- 回滚必须能移除 POC State、清理测试 key，并恢复 POC 前的防火墙或 systemd 改动；不得删除生产数据。

## Definition of Done

- Salt Master/Minion 均证明运行在锁定的 `3008.1` 版本；
- apt pin 和 apt hold 状态有证据，且自动升级不会漂移 Salt 关键包；
- Ubuntu 22.04 主矩阵完成 Master/Minion 通信、key 生命周期、State 执行、返回结果和 Master 重启验证；
- Ubuntu 24.04 兼容矩阵完成至少 Minion 接入、test.ping 和基础 State 验证，或明确记录环境阻塞；
- Minion 离线恢复后能追平最新 POC state，不重放历史操作；
- 4505/4506 暴露面和 `salt-api` 禁用状态有证据；
- Result Packet 区分 `VERIFIED-TEST`、`OBSERVED`、`UNKNOWN` 和未完成项；
- 修改文件清单、测试证据、风险和后续 Handoff 已落盘；
- GIT-SCM 完成原子 commit/push 并重新读取远端 SHA 后，方可标记集成完成。

## Communication/Handoff targets

- SECURITY：审查 Salt key、APT 源签名、pin/hold、端口暴露和 secret 泄露风险；
- QA-RELEASE：审查测试证据、故障注入和 Definition of Done；
- OPS-PLATFORM：复核 systemd、UFW/云防火墙和 Ubuntu 22.04/24.04 运维约束；
- CONFIG-BUILD：后续接收 Salt file roots、pillar roots 和 release 分发需求；
- DATA-MIHOMO：后续接收 Minion 侧调用本地 Mihomo API 的控制边界；
- GIT-SCM：仅在 Owner 和 Reviewer 证据齐备后执行 commit/push，不得自行改变 Salt POC 语义。
