# Result Packet: RP-0025 Master/Minion 默认 TUI 主控台实现

> Task ID：TP-0025
> Owner role：PRODUCT-SPEC / OPS-PLATFORM / CONTROL-SALT / DATA-MIHOMO
> Reviewer role：QA-RELEASE / SECURITY
> 日期：2026-06-25

## 1. 完成内容

- `scripts/proxyfleet-master.sh` 无参数运行时进入 Master 主控台；
- `scripts/proxyfleet-minion.sh` 无参数运行时进入 Minion 主控台；
- 非交互终端无参数运行时返回 `E_TUI_UNAVAILABLE` 并输出等价非交互命令；
- Master 主控台支持预检、安装、状态/key、接受 key、订阅 Provider、导入自建节点、
  导入自定义规则、构建 release、选择同步、端口白名单、服务控制和卸载；
- Minion 主控台支持预检、安装、Master 连通性测试、Salt/Mihomo 状态、服务控制、
  本机端口白名单和卸载；
- TUI 写操作会展示文件、服务、目标或危险等级，并要求确认词；
- Master `uninstall --purge-data` 增加确认词保护，自动化可显式传入 `--yes`；
- Minion 可写入 `/etc/proxyfleet/local/options.json`；
- Minion `uninstall --purge-data` 增加确认词保护，自动化可显式传入 `--yes`；
- Salt Minion apply 读取本机 `options.json`，实现
  `Minion local option > Master 下发 mode > 默认 merge`。

## 2. 未完成内容

- 未引入图形化 Web UI；
- 未引入第三方 TUI 依赖；
- 未在真实生产 Minion 上执行人工 TUI smoke。

## 3. 事实标签

- VERIFIED-TEST：Master/Minion 无参数入口测试通过；
- VERIFIED-TEST：无 TTY fallback 测试通过；
- VERIFIED-TEST：Master purge-data 取消确认不会触发底层卸载命令；
- VERIFIED-TEST：Minion TUI 可写入 local `options.json`；
- VERIFIED-TEST：Salt apply 会使用 local `options.json` 覆盖 Master mode；
- VERIFIED-TEST：全量 127 项 unittest 通过；
- OBSERVED：测试期间仍有既有 socket `ResourceWarning`，未影响断言。

## 4. 修改文件

- `scripts/proxyfleet-master.sh`
- `scripts/proxyfleet-minion.sh`
- `salt/modules/proxyfleet_mihomo.py`
- `salt/states/proxyfleet/sync.sls`
- `tests/test_master_script.py`
- `tests/test_minion_script.py`
- `tests/test_fleet.py`
- `PROJECT_STATE.md`
- `docs/INSTALL_MASTER.md`
- `docs/INSTALL_MINION.md`
- `docs/OPERATIONS.md`
- `docs/USER_MANUAL.md`
- `tasks/TP-0025-default-control-tui.md`

## 5. 测试和证据

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

结果：127 项通过。

```bash
bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh
python3 -m py_compile src/proxyfleet/*.py salt/modules/proxyfleet_mihomo.py
```

结果：通过。

## 6. 风险

- 主控台是 Bash 菜单式 TUI，节点选择仍复用 Python `curses` TUI；
- 真实服务器上的编辑器、终端尺寸和用户操作路径仍建议做一次人工 smoke；
- 订阅 URL 仍通过环境变量传入构建流程，TUI 只写环境变量名，不落盘 URL 明文。

## 7. 发布 Handoff

交给 GIT-SCM：

- 期望 commit scope：`feat: add default control TUI entrypoints`
- 允许 commit/push；
- 已知 secret 风险：未写入订阅 URL、节点密码或 API secret；配置 YAML 仍由 `.gitignore` 屏蔽。
