# Result Packet — RP-0019/TP-0020/TP-0021

- Related task: TP-0019/TP-0020/TP-0021
- Owner role: ARCH-ORCH
- Status: SUCCESS_WITH_RISK
- Completed at: 2026-06-24
- Contract version: interfaces/CONTRACTS.md, interfaces/COMPONENT_LOCKS.md, interfaces/MIHOMO_DRIVER.md

## Outcome

完成 Mihomo 固定资产 URL/SHA-256/gzip 安装、native-mihomo 本地端到端 harness、
端口白名单 managed/local/effective 分层配置和 Minion local override 保护。

本结果允许 POC 合并发布；真实生产 Minion 端到端仍需在用户测试机执行 Salt
state、systemd、Mihomo API 和重启持久性验证。

## Completed

- `component-locks.json` 中 Mihomo `v1.19.27` 进入 `installable`，固定
  `linux-amd64`、`linux-arm64` 官方 gzip 资产 URL、SHA-256 和 `target_path`。
- `component_locks.py` 支持架构级 `artifacts` 校验，覆盖 schema major、
  RFC3339 UTC、架构完整覆盖、凭据 URL、压缩格式和受控目标路径。
- `proxyfleet_mihomo.install_mihomo()` 支持按本机架构选择 artifact、下载压缩资产、
  校验压缩包 SHA-256、gzip 解压、版本探测、原子替换和安装 receipt。
- systemd `daemon-reload` 与 `reload-or-restart` 失败映射为 `E_SERVICE_SYSTEMD`。
- `FLEET_PROXY` PUT 后 GET 验证失败时尝试恢复旧选择，并 GET 验证回滚结果。
- 新增端口白名单 `managed/local/effective` 合并器和 CLI，支持
  `merge/master-only/local-only/disabled`。
- Salt state 创建 `/etc/proxyfleet/managed`、`/etc/proxyfleet/local`、
  `/etc/proxyfleet/effective`，只管理 managed/effective，不覆盖 local override；
  启用端口策略时，`apply_desired` 依赖端口策略成功。
- Salt state 调用执行模块时启用 `fail_on_error: true`，执行模块失败 envelope 会转为
  Salt `CommandExecutionError`，确保 requisites 能 fail-closed。
- `publish-salt`、`sync`、`apply` 支持端口策略参数。
- 更新 PLAN、ADR、契约、安装/运维/供应链文档、测试矩阵和项目状态。

## Not completed

- 未在真实 Ubuntu Minion 上安装或启动真实 `mihomo.service`。
- 未实现 UFW/nftables 防火墙落地后端；当前只生成 effective policy。
- 未把 subconverter 从 candidate 提升到 installable；其 SHA-256 仍需后续补齐。

## Facts and confidence

| Claim | Label | Evidence |
|---|---|---|
| Mihomo installable artifacts 已固定 URL/SHA/gzip | VERIFIED-TEST | `PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json` 通过 |
| gzip 安装先校验压缩包 SHA，再解压和版本探测 | VERIFIED-TEST | `tests/test_fleet.py::test_install_mihomo_gzip_artifact_with_sha`、`test_install_mihomo_version_probe_fails_closed` |
| native-mihomo 本地端到端 harness 通过 | VERIFIED-TEST | `tests/test_fleet.py::test_native_mihomo_local_end_to_end` |
| 端口策略 local override 不被覆盖 | VERIFIED-TEST | `tests/test_fleet.py::test_apply_port_policy_preserves_local_override`、`tests/test_port_policy.py` |
| 端口策略无效 schema/source 会 fail-closed | VERIFIED-TEST | `tests/test_port_policy.py`、`tests/test_fleet.py::test_apply_port_policy_rejects_bad_schema_and_source` |
| 选择失败回滚会验证旧选择 | VERIFIED-TEST | `tests/test_fleet.py::test_select_mihomo_rolls_back_previous_on_verify_mismatch`、`test_select_mihomo_reports_rollback_failure` |
| Salt module.run 能感知执行模块失败 | VERIFIED-TEST | `tests/test_fleet.py::test_install_mihomo_fail_on_error_raises_for_salt_state`、`test_apply_desired_fail_on_error_raises_on_early_failure`、`tests/test_security_contracts.py` |
| 真实物理 Minion 生产端到端 | UNKNOWN | 本轮未操作真实 Minion 测试机 |

## Files changed

- `component-locks.json`
- `src/proxyfleet/component_locks.py`
- `src/proxyfleet/port_policy.py`
- `src/proxyfleet/cli.py`
- `src/proxyfleet/fleet.py`
- `salt/modules/proxyfleet_mihomo.py`
- `salt/states/proxyfleet/sync.sls`
- `tests/test_component_locks.py`
- `tests/test_port_policy.py`
- `tests/test_fleet.py`
- `PLAN.md`
- `PROJECT_STATE.md`
- `DECISIONS.md`
- `README.md`
- `SOURCES.md`
- `docs/DEPLOYMENT_DOCKER.md`
- `docs/INSTALL_MASTER.md`
- `docs/OPERATIONS.md`
- `docs/SUPPLY_CHAIN_SECURITY.md`
- `interfaces/COMPONENT_LOCKS.md`
- `interfaces/CONTRACTS.md`
- `interfaces/MIHOMO_DRIVER.md`
- `tests/TEST_MATRIX.md`
- `adr/ADR-0007-native-mihomo-production-and-local-overrides.md`
- `tasks/TP-0018-native-mihomo-port-policy-planning.md`
- `tasks/TP-0019-0021-native-mihomo-port-policy-implementation.md`
- `results/RP-0018-native-mihomo-port-policy-planning.md`
- `results/RP-0019-0021-native-mihomo-port-policy-implementation.md`

## Tests/evidence

```text
PYTHONPATH=src python3 -m unittest discover -s tests
Ran 77 tests in 5.220s
OK
OBSERVED: ResourceWarning for closed socket; assertions still passed.

PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json
组件锁定清单校验通过

python3 -m py_compile src/proxyfleet/*.py salt/modules/proxyfleet_mihomo.py
bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh
git diff --check
OK
```

## Git evidence（发生 Git 操作时必填）

```text
repository_path: /home/terence/project/ProxyFleet
branch: main
base_commit: e36f30bf2633d792426c8a91e3567210fc857374
new_commit: PENDING
upstream_ref: origin/main
remote_url_redacted: origin
remote_head_before: PENDING
remote_head_after: PENDING
push_status: not-attempted
worktree_status: dirty before GIT-SCM integration
```

## Risks and regressions

- 真实生产发布仍需要物理 Minion 端到端验证。
- ResourceWarning 仍存在，当前不阻断 POC 合并，但发布前应继续定位。
- effective port policy 尚未落到真实 UFW/nftables。

## Decisions requested

- 后续是否优先实现 UFW 还是 nftables 后端。
- 是否将真实 Minion 端到端验证作为下一轮发布前硬门禁。

## Handoffs

- To QA-RELEASE：复核 67 项测试、真实 Minion 未覆盖风险和 ResourceWarning。
- To SECURITY：复核 Mihomo 官方资产 URL/SHA、无凭据 URL、local override 不被 Master 覆盖。
- To GIT-SCM：待门禁通过后执行范围化 stage、commit、push 和远端 SHA 核验。

## Next atomic action

等待 SECURITY/QA final gate；通过后由 GIT-SCM 提交并推送。
