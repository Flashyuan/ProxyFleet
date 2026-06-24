# Result Packet — RP-0017

- Task ID: TP-0017
- Title: 订阅拉取转换、Mihomo 安装配置、节点测速和最少步骤 apply
- Owner role: ARCH-ORCH
- Reviewer roles: CONFIG-BUILD, DATA-MIHOMO, SECURITY, QA-RELEASE
- Result status: PARTIAL_POC_READY
- Created at: 2026-06-24
- Base commit: 861e5bc7d4ed5c2c9fc9fea8a0aa143ccc433aa0

## Completed

- `VERIFIED-TEST`：订阅 URL 可通过 `env`/`secret_ref` 注入并拉取，构建时转换为 Provider 快照。
- `VERIFIED-TEST`：订阅失败时保留 Provider 级 Last Known Good，不用错误正文覆盖有效快照。
- `VERIFIED-TEST`：release 构建支持订阅 Provider、自建 `local_file` Provider 和自定义 rule provider 合成。
- `VERIFIED-TEST`：节点目录可合并健康缓存，显示 `last_delay_ms`、`health_status`、`freshness` 等测速字段。
- `VERIFIED-TEST`：`health-check` 调用 Mihomo 单节点 delay API，不改变 `FLEET_PROXY` 选择。
- `VERIFIED-TEST`：测速 URL 精确限制为 `https://www.gstatic.com/generate_204`。
- `VERIFIED-TEST`：Mihomo 安装模块在组件锁缺少 SHA-256 时返回 `E_COMPONENT_INTEGRITY_MISSING`，不下载未锁定版本。
- `VERIFIED-TEST`：Master 安装脚本提供 `sync-assets`，同步 Salt module/state 到 file_roots。
- `VERIFIED-TEST`：Minion 安装脚本提供 `bootstrap` 别名并输出本机 fingerprint，仍要求 Master 人工核验 key。
- `VERIFIED-TEST`：CLI 增加 `apply`，可编排 build、select、publish 和 sync；`--dry-run` 不写 runtime/Salt，也不执行 Salt。

## Not completed

- `BLOCKED`：`component-locks.json` 中 Mihomo 与 subconverter 的 SHA-256 仍为空，真实安装发布前必须补齐。
- `BLOCKED`：尚未在真实 Salt Master/Minion + Mihomo 测试机完成端到端 apply 证据。
- `PARTIAL`：subconverter 二进制未集成；当前订阅转换支持 Mihomo Provider YAML/JSON 快照的受限解析。

## Changed files

- `README.md`
- `PLAN.md`
- `PROJECT_STATE.md`
- `SOURCES.md`
- `docs/INSTALL_MASTER.md`
- `docs/OPERATIONS.md`
- `salt/modules/proxyfleet_mihomo.py`
- `salt/states/proxyfleet/sync.sls`
- `scripts/proxyfleet-master.sh`
- `scripts/proxyfleet-minion.sh`
- `src/proxyfleet/cli.py`
- `src/proxyfleet/config_build.py`
- `src/proxyfleet/fleet.py`
- `src/proxyfleet/subscription.py`
- `tests/test_config_build.py`
- `tests/test_fleet.py`
- `tests/test_security_contracts.py`
- `tests/test_subscription.py`
- `tasks/TP-0016-plan-health-and-ux.md`
- `tasks/TP-0017-subscription-mihomo-health-apply.md`
- `results/RP-0016-plan-health-and-ux.md`
- `results/RP-0017-subscription-mihomo-health-apply.md`

## Evidence

```text
PYTHONPATH=src python3 -m unittest discover -s tests
Ran 52 tests
OK
```

```text
python3 -m py_compile src/proxyfleet/*.py salt/modules/proxyfleet_mihomo.py
OK
```

```text
bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh
OK
```

```text
git diff --check
OK
```

## Risks

- `PASS_WITH_RISK`：测试套件仍出现一次 `ResourceWarning: unclosed socket`，当前不影响测试退出码；后续应继续定位。
- `RELEASE_BLOCKED`：缺少 Mihomo/subconverter SHA-256 和真实端到端测试证据前，不得标记为 installable release。
- `PASS_WITH_RISK`：`--mihomo-secret` 仍可作为 CLI 参数传入，可能进入 shell history；后续应增加 env/root-only secret 文件方式。

## Reviewer notes

- CONFIG-BUILD 已完成订阅与配置构建实现并报告单元测试通过。
- DATA-MIHOMO 已完成 Mihomo install fail-closed、health check 和 Salt 集成实现。
- SECURITY 初审阻断 Salt `latest` sources、重复 Salt state ID 和 Mihomo SHA 缺失；前两项已修复，SHA 缺失仍阻断真实安装发布。
- QA-RELEASE 初审要求补 Result Packet、修复 Salt state、补充测试；本 Result 和静态契约测试已补齐，真实端到端证据仍缺。

## Handoff

给 GIT-SCM：

```text
Task ID: TP-0017
base commit: 861e5bc7d4ed5c2c9fc9fea8a0aa143ccc433aa0
expected commit scope: feat(fleet): add subscription health and apply flow
push required: yes, if SECURITY/QA allow POC merge
tag required: no
known release block: no installable Mihomo release until SHA-256 locks are filled
secret risk: subscription URLs and API secrets must not be staged; no real secret files expected
```
