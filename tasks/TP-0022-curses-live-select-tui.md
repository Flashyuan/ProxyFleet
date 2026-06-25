# Task Packet — TP-0022

- Title: `curses` TUI 实时测速选择菜单
- Status: IMPLEMENTED
- Owner role: DATA-MIHOMO / PRODUCT-SPEC
- Reviewer roles: QA-RELEASE / SECURITY / OPS-PLATFORM
- Created by: Codex
- Created at: 2026-06-25
- Related ADR: ADR-0001, ADR-0005, ADR-0006
- Contract version: interfaces/CONTRACTS.md Live Select TUI Contract

## Objective

将 `scripts/proxyfleet-master.sh select-sync --live-health` 从 Bash/ANSI 过渡实现
升级为 Python 标准库 `curses` TUI。目标体验接近 `top/htop/btop`：实时刷新原数据、
可滚动、可搜索、可高亮选择、可退出恢复终端，并保持最少命令入口。

## Non-goals

- 不开发 Web UI。
- 不引入第三方 TUI 依赖。
- 不改变 release 构建、desired state schema 或 Salt 同步契约。
- 不实现 fleet-wide Minion 本地延迟聚合；本任务只做 Master-local TUI。
- 不在用户确认选择前修改 `FLEET_PROXY`、desired state 或 Minion 状态。

## Inputs

- `PLAN.md` 9.4、16.3、Phase 4。
- `interfaces/CONTRACTS.md` 6A/6B。
- `interfaces/MIHOMO_DRIVER.md` 实时测速菜单契约。
- `scripts/proxyfleet-master.sh` 当前 `select-sync --live-health` 入口。
- `src/proxyfleet/cli.py`、`src/proxyfleet/fleet.py` 的 nodes/health/select 能力。
- `tests/TEST_MATRIX.md` 3.7A。

## Verified context

- `VERIFIED-TEST`：当前过渡实现已支持后台并发测速、稳定序号、loopback API 限制和
  长列表追加结果。
- `OBSERVED`：长列表超过终端高度时，跨屏 ANSI 光标回写会导致界面错乱。
- `ACCEPTED`：正式交互应使用标准库 `curses` TUI，不新增第三方依赖。
- `ACCEPTED`：实时测速是只读观测能力，确认选择前不得写 desired 或修改 Mihomo。

## Repository context

```text
repository_path: /home/terence/project/ProxyFleet
base_branch: main
base_commit: ddb10d9c1919cc8e9b148077d1a0998e6b381b88
allowed_paths:
  - PLAN.md
  - PROJECT_STATE.md
  - docs/
  - interfaces/
  - scripts/proxyfleet-master.sh
  - src/proxyfleet/
  - tests/
expected_commit_scope: feat(master): add curses live select tui
push_required: yes
tag_required: no
forbidden_history_operations:
  - git push --force
  - git reset --hard
  - deleting remote branches
  - rewriting existing tags
```

## Constraints and forbidden actions

- 保持用户入口不变：`sudo scripts/proxyfleet-master.sh select-sync --live-health`。
- TUI 必须进入 alternate screen 或等价模式，并在退出时恢复终端。
- TUI 必须支持 viewport，不得依赖跨屏改写历史输出。
- 默认序号稳定，不因测速结果到达而自动重排。
- 允许显式按键排序，但必须保留原始序号和当前选择可理解性。
- `q`、Ctrl-C、异常退出必须恢复 cooked mode。
- Mihomo API 仅允许 loopback。
- 选择确认前禁止写 `runtime/desired.yaml`、禁止调用 Salt sync、禁止修改 `FLEET_PROXY`。
- 不新增第三方依赖；如确需新增，必须暂停并请求用户确认。

## Deliverables

- Python 标准库 `curses` TUI 实现。
- Master 脚本调用 TUI，保留原命令入口。
- TUI 支持：
  - 上下滚动；
  - 高亮选择；
  - `Enter` 确认；
  - `/` 搜索；
  - `r` 重新测速；
  - `q` 退出；
  - 状态栏显示进度、ok/timeout/failed、耗时、并发、数据来源；
  - 可见节点行实时刷新延迟与状态。
- 文档和测试矩阵同步更新。

## Required evidence/tests

- 单元测试：
  - 节点视图模型稳定排序和稳定序号；
  - 搜索过滤不破坏原始 node_id；
  - 测速结果更新只影响目标节点；
  - 确认选择前不写 desired。
- 伪终端/集成测试：
  - 进入并退出 TUI 后终端状态恢复；
  - 长列表滚动；
  - 搜索；
  - 选择并输出选中 node_id；
  - Ctrl-C 退出恢复；
  - 非 loopback Mihomo API 被拒绝。
- 回归测试：
  - `PYTHONPATH=src python3 -m unittest discover -s tests`
  - `bash -n scripts/proxyfleet-master.sh`
  - `python3 -m py_compile src/proxyfleet/*.py`
  - `git diff --check`

## Dependencies

- 当前 `nodes` catalog 和 `health-check` 逻辑可复用。
- 当前 loopback API 限制、健康缓存 revision 绑定和 allowlist 规则必须保留。

## Failure/rollback expectations

- TUI 初始化失败时应给出清晰错误，并不得写 desired。
- 无 TTY 时 fail-fast，并提示使用非交互命令。
- Ctrl-C 或异常退出时恢复终端模式。
- 发布后若 TUI 有阻断问题，可临时回退到过渡实现，但必须保留安全约束。

## Definition of Done

- `select-sync --live-health` 进入 `curses` TUI。
- 长列表不再刷乱、不再只显示进度、不污染终端历史。
- 用户可用键盘完成查看、搜索、选择和退出。
- 测试、伪终端验证、QA/SECURITY 审计通过。
- GIT-SCM 完成 commit、push，并核验远端 SHA。

## Implementation evidence

- `src/proxyfleet/live_select.py`：标准库 `curses` TUI，复用 `MihomoClient.health_check()`。
- `src/proxyfleet/cli.py`：新增 `live-select` 子命令和 `--selection-output`。
- `scripts/proxyfleet-master.sh`：`select-sync --live-health` 保持入口不变，绑定
  `/dev/tty` 运行 TUI，并通过临时文件回传选中 TSV。
- `tests/test_live_select.py`：覆盖视图模型、搜索、排序、健康更新、非 loopback 拒绝、
  伪终端选择、搜索选择、`q` 退出和 Ctrl-C。
- `tests/test_security_contracts.py`：覆盖脚本入口、TUI 关键能力和确认前无 desired/Salt/Mihomo 写操作。

## Communication/Handoff targets

- DATA-MIHOMO 负责 TUI 数据流和 Mihomo health 只读契约。
- PRODUCT-SPEC 负责按键语义和最少步骤体验。
- QA-RELEASE 负责伪终端测试和发布门禁。
- SECURITY 负责 API loopback、secret 和终端异常恢复审计。
- GIT-SCM 负责最终 commit/push/远端核验。
