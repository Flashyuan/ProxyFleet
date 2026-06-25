# Result Packet: RP-0025 Master/Minion 默认 TUI 主控台规划

> Task ID：TP-0025
> Owner role：DOCS-KNOWLEDGE / PRODUCT-SPEC
> Reviewer role：OPS-PLATFORM / CONTROL-SALT / DATA-MIHOMO / SECURITY / QA-RELEASE
> 日期：2026-06-25

## 1. 完成内容

- `PLAN.md` 明确 Master/Minion 脚本无参数运行时默认进入 TUI 主控台；
- `PLAN.md` 明确底层子命令保留给自动化、文档复现和故障恢复；
- `interfaces/CONTRACTS.md` 新增 Default Control TUI Contract；
- `tests/TEST_MATRIX.md` 新增默认 TUI 主控台测试矩阵；
- `docs/INSTALL_MASTER.md`、`docs/INSTALL_MINION.md`、`docs/OPERATIONS.md`、
  `docs/USER_MANUAL.md` 增加下一轮默认 TUI 入口说明；
- 新增 `tasks/TP-0025-default-control-tui.md`。

## 2. 未完成内容

- 尚未修改 `scripts/proxyfleet-master.sh` 或 `scripts/proxyfleet-minion.sh`；
- 尚未实现 Master/Minion 主控台菜单；
- 尚未实现 Minion 本机 `/etc/proxyfleet/local/options.json` 持久选项；
- 尚未执行伪终端测试、脚本测试或发布。

## 3. 事实标签

- VERIFIED-DOC：规划已写入 PLAN、契约、测试矩阵、安装文档、运维文档和用户手册；
- PROPOSED：`sudo scripts/proxyfleet-master.sh` 无参数进入 Master TUI；
- PROPOSED：`sudo scripts/proxyfleet-minion.sh` 无参数进入 Minion TUI；
- PROPOSED：TUI 写操作必须先展示修改文件、服务、目标和危险等级；
- PROPOSED：Minion 本机端口策略模式持久化到 `/etc/proxyfleet/local/options.json`；
- PROPOSED：端口策略模式优先级为 Minion local option > Master 下发 mode > 默认 merge。

## 4. 修改文件

- `PLAN.md`
- `PROJECT_STATE.md`
- `interfaces/CONTRACTS.md`
- `tests/TEST_MATRIX.md`
- `docs/INSTALL_MASTER.md`
- `docs/INSTALL_MINION.md`
- `docs/OPERATIONS.md`
- `docs/USER_MANUAL.md`
- `tasks/TP-0025-default-control-tui.md`

## 5. 风险

- 默认无参数进入 TUI 后，无 TTY、脚本自动化和管道调用场景必须有清晰 fallback；
- TUI 若直接写配置，必须复用现有 schema/release/lock 校验，不能绕过安全门禁；
- 卸载、清理和服务停止属于危险操作，必须二次确认；
- 订阅 URL、节点密码、API secret 和完整代理 URI 必须脱敏，不能写入日志。

## 6. 后续 Handoff

交给 PRODUCT-SPEC / OPS-PLATFORM / CONTROL-SALT / DATA-MIHOMO：

- 用户确认后按 TP-0025 实现 Master/Minion 默认 TUI 主控台；
- 补齐伪终端入口测试、菜单导航测试、配置写入测试、危险确认测试和无 TTY fallback；
- 交 SECURITY 和 QA-RELEASE 审计；
- 审计通过后交 GIT-SCM commit/push。
