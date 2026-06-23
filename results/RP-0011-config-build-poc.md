# Result Packet — RP-0011

- Related task: TP-0011
- Owner role: CONFIG-BUILD
- Status: SUCCESS
- Completed at: 2026-06-23
- Contract version: 0.2-draft

## Outcome

实现本地配置源校验与 release compiler POC。该 POC 可读取本地 fixture 配置源，生成不可变 revision 目录、`config.yaml`、Provider、Rule Provider、`manifest.json` 和 `manifest.sha256`，并提供 release 哈希校验命令。

## Completed

- 新增 `proxyfleet build-release` CLI；
- 新增 `proxyfleet verify-release` CLI；
- 实现配置源 schema、Provider、策略组和规则校验；
- 实现 `FLEET_PROXY` 必需组校验；
- 实现 Provider/rule 路径逃逸防护；
- 实现 release staging 目录和 revision 目录生成；
- 实现 manifest 文件 SHA-256、size 和 manifest 自身哈希校验；
- 新增 fixture 和单元测试；
- 新增 Mihomo native driver 最小契约；
- 新增 CONFIG-BUILD 测试要求；
- 新增 Salt 3008.1 POC Task Packet。

## Not completed

- 未接入真实订阅获取；
- 未调用真实 subconverter；
- 未运行锁定版本 Mihomo 做配置离线校验；
- 未通过 Salt 分发 release；
- 未在真实 Ubuntu 节点执行 systemd/Mihomo 验证；
- 未实现 Last Known Good 指针切换。

## Facts and confidence

| Claim | Label | Evidence |
|---|---|---|
| release compiler 可生成本地 release 目录 | VERIFIED-TEST | `proxyfleet build-release tests/fixtures/config-src <tmp> --revision 2 ...` |
| release manifest 可验证文件 SHA 和 size | VERIFIED-TEST | `proxyfleet verify-release <tmp>/000002` 与单元测试 |
| `FLEET_PROXY` 缺失会阻断构建 | VERIFIED-TEST | `tests/test_config_build.py` |
| 未知 Provider 引用会阻断构建 | VERIFIED-TEST | `tests/test_config_build.py` |
| 路径逃逸会阻断构建 | VERIFIED-TEST | `tests/test_config_build.py` |
| 当前 POC 不代表生产发布能力 | OBSERVED | 未接入真实订阅、subconverter、Mihomo 校验或 Salt 分发 |

## Files changed

- `PROJECT_STATE.md`
- `interfaces/MIHOMO_DRIVER.md`
- `src/proxyfleet/cli.py`
- `src/proxyfleet/config_build.py`
- `tasks/TP-0011-config-build-poc.md`
- `tasks/TP-0012-salt-poc.md`
- `tests/CONFIG_BUILD_TESTS.md`
- `tests/fixtures/config-src/base.json`
- `tests/fixtures/config-src/groups.json`
- `tests/fixtures/config-src/provider-self-hosted.json`
- `tests/fixtures/config-src/providers.json`
- `tests/fixtures/config-src/rules-force-proxy.json`
- `tests/fixtures/config-src/rules.json`
- `tests/test_config_build.py`
- `results/RP-0011-config-build-poc.md`

## Tests/evidence

```text
PYTHONPATH=src python3 -m unittest discover -s tests
Ran 14 tests in 0.078s
OK

tmp=$(mktemp -d) && PYTHONPATH=src python3 -m proxyfleet.cli build-release tests/fixtures/config-src "$tmp" --revision 2 --source-git-commit $(git rev-parse HEAD) && PYTHONPATH=src python3 -m proxyfleet.cli verify-release "$tmp/000002" && rm -rf "$tmp"
release 构建完成: <tmp>/000002
release 校验通过

PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json
组件锁定清单校验通过

git diff --check
exit 0
```

## Git evidence

```text
repository_path: /home/terence/project/ProxyFleet
branch: main
base_commit: 7cd89810e409b4210d7e694f4d9c71e9664c7798
new_commit: PENDING
upstream_ref: origin/main
remote_url_redacted: ssh://git@ssh.github.com:443/Flashyuan/ProxyFleet.git
remote_head_before: 7cd89810e409b4210d7e694f4d9c71e9664c7798
remote_head_after: PENDING
push_status: not-attempted
worktree_status: dirty-explained (TP-0011 changes)
```

## Risks and regressions

- POC 使用 JSON fixture，生产配置源仍需 YAML 支持或明确 JSON-only 决策；
- 当前未执行 Mihomo 官方配置校验；
- 当前未处理真实订阅错误正文、缓存和 Last Known Good；
- 当前未建立 Salt file roots / pillar roots 分发链路。

## Decisions requested

- 是否继续让 CONFIG-BUILD 接入真实订阅刷新和 subconverter；
- 是否将配置源格式固定为 YAML，或允许 JSON fixture 仅作为测试输入。

## Handoffs

- CONTROL-SALT：TP-0012 可使用 release 目录作为后续 Salt 分发输入；
- DATA-MIHOMO：`interfaces/MIHOMO_DRIVER.md` 定义 native driver 应用 release 的边界；
- QA-RELEASE：`tests/CONFIG_BUILD_TESTS.md` 可继续扩展为自动化故障注入。

## Next atomic action

由 GIT-SCM 提交并推送 TP-0011 变更；下一轮进入 Salt POC 准备或订阅/subconverter 集成。
