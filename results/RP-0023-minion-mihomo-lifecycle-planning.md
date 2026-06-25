# Result Packet: RP-0023 Minion Mihomo 安全生命周期控制规划

> Task ID：TP-0023
> Owner role：DOCS-KNOWLEDGE / ARCH-ORCH
> Reviewer role：CONTROL-SALT / DATA-MIHOMO / SECURITY / QA-RELEASE
> 日期：2026-06-25

## 1. 完成内容

- `PLAN.md` 增加 Minion 脚本 Mihomo 生命周期决策、规划、验收和 Phase 3 任务；
- `interfaces/MIHOMO_DRIVER.md` 增加 Minion 脚本生命周期契约；
- `tests/TEST_MATRIX.md` 增加 3.9 Minion 脚本 Mihomo 生命周期测试矩阵；
- `tasks/TP-0023-minion-mihomo-lifecycle.md` 新增后续实现 Task Packet；
- `PROJECT_STATE.md` 登记 TP-0023 为 READY；
- `docs/INSTALL_MASTER.md`、`docs/INSTALL_MINION.md`、`docs/OPERATIONS.md`、
  `docs/USER_MANUAL.md` 增加用户侧操作边界说明。

## 2. 未完成内容

- 尚未修改 `scripts/proxyfleet-minion.sh`；
- 尚未实现 `--with-mihomo` 或 `mihomo-*` 子命令；
- 尚未执行真实 Minion smoke。

## 3. 事实标签

- VERIFIED-DOC：默认 Minion 脚本命令只控制 `salt-minion` 的目标语义已写入
  PLAN、接口契约和用户文档；
- PROPOSED：`--with-mihomo` 和 `mihomo-*` 子命令为后续实现规划；
- UNKNOWN：真实生产机器上的 Mihomo unit 是否均带有足够 ProxyFleet 所有权标记，
  需实现时验证。

## 4. 修改文件

- `PLAN.md`
- `PROJECT_STATE.md`
- `interfaces/MIHOMO_DRIVER.md`
- `tests/TEST_MATRIX.md`
- `tasks/TP-0023-minion-mihomo-lifecycle.md`
- `docs/INSTALL_MASTER.md`
- `docs/INSTALL_MINION.md`
- `docs/OPERATIONS.md`
- `docs/USER_MANUAL.md`

## 5. 测试和证据

- 计划执行 `git diff --check`；
- 计划执行关键词检查：
  `rg "TP-0023|with-mihomo|mihomo-uninstall|purge-local-override"`。

## 6. 风险

- 如果后续实现直接把 `uninstall --with-mihomo` 做成默认行为，会违反当前规划；
- 如果 Mihomo unit 没有可靠所有权标记，安全卸载必须 fail-closed；
- 删除 `/etc/proxyfleet/local` 必须保持额外显式授权。

## 7. 后续 Handoff

交给 CONTROL-SALT / DATA-MIHOMO：

- 按 TP-0023 实现脚本命令；
- 补齐 mock systemd 和真实 Minion smoke；
- 完成后交 SECURITY / QA-RELEASE 审计；
- 最终交 GIT-SCM 原子 commit/push。
