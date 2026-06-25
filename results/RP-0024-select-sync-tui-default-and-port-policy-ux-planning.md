# Result Packet: RP-0024 select-sync 默认 TUI 与端口白名单 UX 规划

> Task ID：TP-0024
> Owner role：DOCS-KNOWLEDGE / PRODUCT-SPEC
> Reviewer role：DATA-MIHOMO / CONTROL-SALT / QA-RELEASE / SECURITY
> 日期：2026-06-25

## 1. 完成内容

- `PLAN.md` 明确 `select-sync` 默认进入实时 TUI；
- `PLAN.md` 将 `--live-health` 标记为兼容别名，将 `--refresh-health` 和
  `--no-health-cache` 标记为废弃规划；
- `PLAN.md` 增加 TUI 当前选择展示、drift 展示、视觉区域和端口白名单状态要求；
- `interfaces/CONTRACTS.md` 更新 Live Select TUI Contract 和端口白名单默认源；
- `tests/TEST_MATRIX.md` 增加默认 TUI、当前选择、drift、UI 结构和端口白名单默认文件测试要求；
- `docs/INSTALL_MASTER.md`、`docs/OPERATIONS.md`、`docs/USER_MANUAL.md`
  更新推荐命令和端口白名单配置位置；
- 新增 `tasks/TP-0024-select-sync-tui-default-and-port-policy-ux.md`。

## 2. 未完成内容

- 尚未修改 `scripts/proxyfleet-master.sh`；
- 尚未修改 `src/proxyfleet/live_select.py`；
- 尚未实现默认 TUI、当前选择展示或端口白名单自动发现；
- 尚未执行测试或发布。

## 3. 事实标签

- VERIFIED-DOC：当前规划已写入 PLAN、契约、测试矩阵和用户文档；
- PROPOSED：`select-sync` 默认 TUI、`--live-health` 兼容别名、废弃测速参数；
- PROPOSED：Master managed 端口白名单默认文件为 `config-src/port-policy.yaml`；
- OBSERVED：当前已有文档和任务包声明 `select-sync --live-health` 是 curses TUI，
  并支持后台并发延迟刷新。

## 4. 修改文件

- `PLAN.md`
- `PROJECT_STATE.md`
- `interfaces/CONTRACTS.md`
- `tests/TEST_MATRIX.md`
- `docs/INSTALL_MASTER.md`
- `docs/OPERATIONS.md`
- `docs/USER_MANUAL.md`
- `tasks/TP-0024-select-sync-tui-default-and-port-policy-ux.md`

## 5. 风险

- 若默认 `select-sync` 改为 TUI 后无 TTY 场景未处理，自动化环境可能失败；
- `--refresh-health` 和 `--no-health-cache` 废弃需兼容过渡，不能直接破坏已有用户脚本；
- TUI 读取当前选择时，desired state 与 Mihomo API 可能漂移，必须清晰提示；
- 端口白名单默认文件存在时自动同步，必须先校验 schema，避免误关闭管理端口。

## 6. 后续 Handoff

交给 PRODUCT-SPEC / DATA-MIHOMO / CONTROL-SALT：

- 按 TP-0024 实现脚本入口和 TUI 改造；
- 补齐默认入口、兼容别名、废弃参数、当前选择、drift、端口白名单状态测试；
- 交 QA-RELEASE 和 SECURITY 审计；
- 通过后交 GIT-SCM commit/push。
