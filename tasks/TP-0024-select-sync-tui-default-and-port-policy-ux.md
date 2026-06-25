# Task Packet: TP-0024 select-sync 默认 TUI、当前选择展示与端口白名单 UX

> 状态：READY
> Owner role：PRODUCT-SPEC / DATA-MIHOMO / CONTROL-SALT
> Reviewer role：QA-RELEASE / SECURITY
> 创建日期：2026-06-25

## 1. 目标

收敛 `proxyfleet-master.sh select-sync` 的用户入口，让默认命令直接进入实时 TUI，
展示当前选中节点、动态刷新延迟，并自动发现 Master managed 端口白名单默认文件。

## 2. 非目标

- 不开发 Web UI；
- 不引入第三方 TUI 依赖；
- 不实现 fleet-wide Minion 本地延迟聚合；
- 不在用户确认选择前修改 desired state、`FLEET_PROXY` 或 Minion 状态；
- 不让 Master 覆盖 `/etc/proxyfleet/local/port-policy.yaml`。

## 3. 输入文件与契约

- `PLAN.md` 9.4、11、16.3、Phase 4；
- `interfaces/CONTRACTS.md` Live Select TUI Contract 和端口白名单契约；
- `scripts/proxyfleet-master.sh`；
- `src/proxyfleet/live_select.py`；
- `src/proxyfleet/cli.py`；
- `tests/TEST_MATRIX.md` 3.7A、3.8；
- `docs/INSTALL_MASTER.md`、`docs/OPERATIONS.md`、`docs/USER_MANUAL.md`。

## 4. 已验证事实

- `select-sync --live-health` 已实现 curses TUI；
- 当前 TUI 规划支持后台并发刷新延迟；
- 端口白名单已有 managed/local/effective 三层模型；
- `.gitignore` 已排除 `*.yaml` 和 `*.yml`。

## 5. 约束和禁止事项

- `select-sync` 不带参数必须进入 TUI；
- `--live-health` 只能作为兼容别名；
- `--refresh-health` 和 `--no-health-cache` 不再作为推荐帮助入口；
- TUI 必须显示当前选择：无选择时显示 `当前选择：无`；
- desired state 与 Mihomo API 当前选择不一致时必须显示 drift；
- 延迟刷新必须是动态后台刷新，不能要求用户等待全量测速完成；
- 选择确认前不得写 desired、不得触发 Salt sync；
- 端口白名单默认文件为 `config-src/port-policy.yaml`；
- 默认端口白名单模式为 `merge`，但文件不存在时不得自动生成允许规则。

## 6. 预期交付

### 6.1 CLI 语义

```text
sudo scripts/proxyfleet-master.sh select-sync
```

默认进入 TUI。

```text
sudo scripts/proxyfleet-master.sh select-sync --live-health
```

保留为兼容别名，行为与默认入口一致。

### 6.2 TUI 信息架构

TUI 固定区域：

```text
标题栏：ProxyFleet Select | release | target | 当前选择
状态栏：进度 ok/timeout/failed | 并发 | 耗时 | 数据来源 | 端口白名单状态
搜索栏：当前过滤条件
节点表格：序号 | 状态 | 延迟 | 当前标记 | mihomo_name | provider
帮助栏：↑/↓ j/k Enter / r s n q
```

当前选择显示规则：

- desired 和 Mihomo API 都无选择：`当前选择：无`；
- desired 有值且 API 一致：显示 `当前选择：<mihomo_name>`；
- desired 有值但 API 不一致：显示 `当前选择漂移：desired=<x> actual=<y>`；
- API 不可达：显示 `当前选择：未知（API 不可达）`。

### 6.3 端口白名单默认入口

- Master managed 默认文件：`config-src/port-policy.yaml`；
- 文件存在时，`select-sync` 默认以 `merge` 模式随 desired 一起发布；
- 文件不存在时，TUI 状态栏显示 `端口白名单：未配置`；
- `--port-policy PATH` 仍允许覆盖默认文件；
- Minion local override 仍为 `/etc/proxyfleet/local/port-policy.yaml`。

### 6.4 界面优化

- 使用颜色或安全降级样式区分 ok、timeout、failed、unknown、stale、selected；
- 节点名过长时截断，不能挤掉序号、延迟和状态；
- 高亮行、当前选中行、搜索命中行必须能区分；
- 窄终端必须降级显示核心列；
- 无颜色终端必须可读。

## 7. 必需证据和测试

- `bash -n scripts/proxyfleet-master.sh`
- `python3 -m py_compile src/proxyfleet/*.py`
- `PYTHONPATH=src python3 -m unittest discover -s tests`
- 单元测试：
  - 默认 `select-sync` 调用 TUI；
  - `--live-health` 兼容别名；
  - `--refresh-health` / `--no-health-cache` 非推荐帮助路径；
  - 当前选择有值、无值、drift、API 不可达；
  - 端口白名单默认文件存在/不存在；
  - TUI 状态布局和列截断。
- 伪终端测试：
  - 进入 TUI 后展示当前选择；
  - 后台延迟动态刷新；
  - 选择、退出、Ctrl-C 后终端恢复。

## 8. 完成条件

- `select-sync` 默认 TUI 可用；
- 用户进入 TUI 后能看到当前选中节点或 `当前选择：无`；
- 节点延迟动态刷新，且不刷乱终端；
- TUI 视觉层次明显优于当前版本；
- 端口白名单默认文件位置和同步状态在文档/TUI 中明确；
- QA-RELEASE 与 SECURITY 未设置阻断；
- GIT-SCM 完成 commit/push 前执行远端核验。
