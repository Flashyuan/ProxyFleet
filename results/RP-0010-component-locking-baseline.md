# Result Packet — RP-0010

- Related task: TP-0010
- Owner role: SECURITY
- Status: SUCCESS
- Completed at: 2026-06-23
- Contract version: 0.2-draft

## Outcome

建立组件版本锁定基线、供应链安全文档、组件锁契约、最小测试矩阵和本地校验工具。当前清单可阻断浮动版本和自动更新，但 Mihomo/subconverter/Docker 镜像仍是 candidate/planned，进入可安装状态前必须补齐 SHA-256 或 digest。

## Completed

- 新增 `component-locks.json`；
- 新增 `proxyfleet verify-locks` CLI；
- 新增组件锁校验模块；
- 新增单元测试；
- 新增供应链安全文档；
- 新增组件锁契约文档；
- 新增 Phase 0/1 最小测试矩阵；
- 新增 TP-0010 Task Packet。

## Not completed

- 未下载生产二进制；
- 未计算 Mihomo/subconverter 制品 SHA-256；
- 未构建 Docker 镜像或记录 digest；
- 未安装 Salt/Mihomo/subconverter；
- 未执行 VM/服务器级 POC。

## Facts and confidence

| Claim | Label | Evidence |
|---|---|---|
| 锁文件禁止自动更新和浮动版本 | VERIFIED-TEST | `tests/test_component_locks.py` |
| 缺少 installable SHA/digest 会 fail-closed | VERIFIED-TEST | `tests/test_component_locks.py` |
| 当前组件锁清单可解析并校验通过 | VERIFIED-TEST | `PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json` |
| Salt 3008.1、Mihomo v1.19.27、subconverter v0.9.0 是候选锁定版本 | VERIFIED-DOC | 官方发布页和 GitHub release 查询 |
| Mihomo/subconverter/Docker 镜像尚不可生产安装 | OBSERVED | `component-locks.json` 状态为 candidate/planned，缺少 SHA/digest |

## Files changed

- `component-locks.json`
- `docs/SUPPLY_CHAIN_SECURITY.md`
- `interfaces/COMPONENT_LOCKS.md`
- `pyproject.toml`
- `src/proxyfleet/__init__.py`
- `src/proxyfleet/cli.py`
- `src/proxyfleet/component_locks.py`
- `tasks/TP-0010-component-locking-baseline.md`
- `tests/TEST_MATRIX.md`
- `tests/test_component_locks.py`
- `PROJECT_STATE.md`
- `results/RP-0010-component-locking-baseline.md`

## Tests/evidence

```text
PYTHONPATH=src python3 -m unittest discover -s tests
Ran 6 tests in 0.002s
OK

PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json
组件锁定清单校验通过

git diff --check
exit 0
```

## Git evidence

```text
repository_path: /home/terence/project/ProxyFleet
branch: main
base_commit: a2ee765305205f44aa3a33862188650e199908c6
new_commit: PENDING
upstream_ref: origin/main
remote_url_redacted: ssh://git@ssh.github.com:443/Flashyuan/ProxyFleet.git
remote_head_before: a2ee765305205f44aa3a33862188650e199908c6
remote_head_after: PENDING
push_status: not-attempted
worktree_status: dirty-explained (TP-0010 changes)
```

## Risks and regressions

- candidate 组件缺少 SHA/digest，不能进入生产安装；
- 当前未建立 VM 测试环境；
- 当前未实现 Salt/Mihomo/subconverter 安装流程。

## Decisions requested

- 是否将 Salt 3008.1、Mihomo v1.19.27、subconverter v0.9.0 作为首个 POC 固定版本继续推进；
- Docker 基础镜像和项目镜像 digest 需在 Docker POC 中冻结。

## Handoffs

- CONFIG-BUILD：release compiler 后续应读取 `component-locks.json`；
- OPS-PLATFORM：Docker POC 必须输出镜像 digest 和 SBOM；
- DATA-MIHOMO：Mihomo POC 必须补齐架构二进制 SHA-256；
- CONTROL-SALT：Salt POC 必须验证 apt pin/hold。

## Next atomic action

由 GIT-SCM 提交并推送 TP-0010 变更，然后创建 Salt/Mihomo/config-build POC 任务。
