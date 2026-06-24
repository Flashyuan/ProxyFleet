# Result Packet — RP-0015

- Related task: TP-0015
- Owner role: ARCH-ORCH
- Status: SUCCESS
- Completed at: 2026-06-24
- Contract version: interfaces/CONTRACTS.md 0.2-draft

## Outcome

已实现代理配置、节点选择与 Salt 同步的最小可发布闭环。

## Completed

- 新增 `proxyfleet nodes`：从 release Provider 快照生成可选代理节点目录；
- 新增 `proxyfleet select-node`：按稳定 `node_id` 写入 `runtime/desired.yaml`；
- 新增 `proxyfleet desired-status`：读取 desired state；
- 新增 `proxyfleet publish-salt`：把 release 和 desired state 发布到 Salt file_roots；
- 新增 `proxyfleet sync`：生成同步计划并可调用 `salt state.apply proxyfleet.sync`；
- 新增 Mihomo API 最小客户端，执行 PUT 后必须 GET 回读验证；
- 新增 Salt Minion execution module/state，用于安装 release 并切换 `FLEET_PROXY`；
- Minion 侧新增 manifest/hash 应用前、staging 后、最终目录后校验；
- Minion 侧按“安装 release → 切 current → reload/restart → 选择节点 → 写 desired”执行；
- reload/restart 或 Mihomo API 失败时回滚 Minion `current`，且不写 desired state；
- `sync` 会把 CLI 指定的 Salt release/desired 路径作为 pillar 传给 state；
- 更新 Master 安装教程、运维文档、README 和 PROJECT_STATE。

## Not completed

- 未接入真实订阅 URL 和 subconverter；
- 未在真实 Mihomo/Salt Minion 上完成端到端测试；
- strict/best-effort 的分布式补偿回滚尚未完整实现。

## Facts and confidence

| Claim | Label | Evidence |
|---|---|---|
| release 可生成节点目录 | VERIFIED-TEST | `tests/test_fleet.py::test_build_node_catalog_from_release` |
| 选择节点会写入 desired state 且 revision 递增 | VERIFIED-TEST | `tests/test_fleet.py::test_select_node_writes_desired_and_increments_revision` |
| 未知 node_id fail-closed | VERIFIED-TEST | `tests/test_fleet.py::test_select_unknown_node_fails_closed` 和 CLI 返回 `E_NODE_NOT_FOUND` |
| Salt publish 会复制 release/desired | VERIFIED-TEST | `tests/test_fleet.py::test_publish_salt_copies_release_and_desired` |
| provider revision 不一致会阻断同步 | VERIFIED-TEST | `tests/test_fleet.py::test_sync_plan_rejects_provider_mismatch` |
| Mihomo API PUT 后 GET 验证 | VERIFIED-TEST | `tests/test_fleet.py::test_select_node_puts_then_gets_to_verify` |
| Mihomo 回读不一致会失败 | VERIFIED-TEST | `tests/test_fleet.py::test_select_node_detects_verify_mismatch` |
| Salt envelope 会脱敏 secret 字段 | VERIFIED-TEST | `tests/test_fleet.py::test_salt_envelope_redacts_secret_fields` |
| Minion 侧 release hash 不符会失败 | VERIFIED-TEST | `tests/test_fleet.py::test_verify_release_detects_hash_mismatch` |
| Minion API 失败不会切换 current/desired | VERIFIED-TEST | `tests/test_fleet.py::test_apply_desired_failure_does_not_switch_current_or_desired` |
| 非默认 salt_root 会进入 Salt pillar | VERIFIED-TEST | `tests/test_fleet.py::test_run_salt_sync_passes_selected_salt_paths` |
| CLI API 失败不会写入 desired | VERIFIED-TEST | `tests/test_fleet.py::test_cli_mihomo_failure_does_not_write_desired` |
| Minion reload 先于节点选择 | VERIFIED-TEST | `tests/test_fleet.py::test_apply_desired_reloads_before_selecting_node` |
| Minion reload 失败会回滚 current | VERIFIED-TEST | `tests/test_fleet.py::test_apply_desired_reload_failure_rolls_back_current` |

## Files changed

- `src/proxyfleet/fleet.py`
- `src/proxyfleet/cli.py`
- `tests/test_fleet.py`
- `salt/modules/proxyfleet_mihomo.py`
- `salt/states/proxyfleet/sync.sls`
- `docs/INSTALL_MASTER.md`
- `docs/OPERATIONS.md`
- `README.md`
- `PROJECT_STATE.md`
- `tasks/TP-0015-proxy-config-select-sync.md`
- `results/RP-0015-proxy-config-select-sync.md`

## Tests/evidence

```text
PYTHONPATH=src python3 -m unittest discover -s tests
Ran 38 tests in 1.344s
OK

python3 -m py_compile src/proxyfleet/*.py salt/modules/proxyfleet_mihomo.py
OK

git diff --check
OK

CLI fixture:
build-release -> nodes -> select-node -> publish-salt -> sync --dry-run
desired_revision: 1
unknown node_id: E_NODE_NOT_FOUND
```

## Git evidence（发生 Git 操作时必填）

```text
repository_path: /home/terence/project/ProxyFleet
branch: main
base_commit: aaa48fe2b6419c808113347f8796a9e12d21e74c
new_commit: pending
upstream_ref: origin/main
remote_url_redacted: ssh://git@ssh.github.com:443/Flashyuan/ProxyFleet.git
remote_head_before: aaa48fe2b6419c808113347f8796a9e12d21e74c
remote_head_after: pending
push_status: pending
worktree_status: clean before metadata amend
```

## Risks and regressions

- `INFERRED`：Salt state 已按契约编写，但真实 Minion 上仍需同步 `_modules` 后验证；
- `UNKNOWN`：真实 Mihomo API secret 和实际监听端口尚未接入 pillar；
- `PROPOSED`：下一轮应实现 strict/best-effort 分布式结果聚合与回滚。

## Decisions requested

- 是否将 `runtime/desired.yaml` 固定为 JSON/YAML 子集格式进入 Contract；
- 是否把 Mihomo API 地址和 secret 作为 Salt pillar 正式字段。

## Handoffs

```text
Task ID: TP-0015
base commit: aaa48fe2b6419c808113347f8796a9e12d21e74c
修改文件清单: 见 Files changed
测试命令和结果: 见 Tests/evidence
是否包含生成物: no
期望 commit scope/message: feat(fleet): add proxy selection and salt sync
是否允许 push/tag: push yes, tag no
已知 secret 风险: 未写入订阅 URL、API secret、节点密码；Mihomo secret 仅作为 CLI 入参使用，不写 desired。
```

## Next atomic action

由 GIT-SCM 执行只读 preflight、stage 本 Task 文件、commit、push 并核验远端 SHA。
