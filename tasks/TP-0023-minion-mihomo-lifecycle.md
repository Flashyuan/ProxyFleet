# Task Packet: TP-0023 Minion Mihomo 安全生命周期控制

> 状态：READY
> Owner role：CONTROL-SALT / DATA-MIHOMO
> Reviewer role：SECURITY / QA-RELEASE
> 创建日期：2026-06-25

## 1. 目标

让 `proxyfleet-minion.sh` 支持显式、安全地控制本机 Mihomo 服务启动、停止、
状态查看和完整卸载，并保持 Salt Minion 基础生命周期命令的默认安全语义。

## 2. 非目标

- 不让 `start/stop/restart/uninstall` 默认隐式操作 Mihomo；
- 不在 Master 脚本中批量卸载所有 Minion 的 Mihomo；
- 不删除 `/etc/proxyfleet/local`，除非用户显式传入危险参数；
- 不绕过组件锁、release manifest、systemd unit 所有权校验；
- 不兼容未知 ShellCrash 管理的 Mihomo 服务。

## 3. 输入文件与契约

- `PLAN.md`
- `interfaces/MIHOMO_DRIVER.md`
- `docs/INSTALL_MINION.md`
- `docs/OPERATIONS.md`
- `docs/USER_MANUAL.md`
- `scripts/proxyfleet-minion.sh`
- `tests/TEST_MATRIX.md`

## 4. 已验证事实

- `proxyfleet-minion.sh` 现有 `start/stop/restart/status/uninstall` 只管理
  `salt-minion`；
- `native-mihomo` 已定义受管路径 `/etc/proxyfleet`、`mihomo.service` 和
  release/current/previous 链接；
- 端口白名单 local override 位于 `/etc/proxyfleet/local`，不得被 Master 或卸载
  默认流程覆盖删除。

## 5. 约束和禁止事项

- 默认命令必须保持向后兼容，只控制 `salt-minion`；
- Mihomo 生命周期必须通过 `--with-mihomo` 或 `mihomo-*` 子命令显式触发；
- 所有删除动作必须先确认 unit、路径和文件所有权属于 ProxyFleet；
- systemd、配置校验、版本校验或路径校验失败时必须 fail-closed；
- `--purge-all` 必须要求 `--yes`；
- 删除 `/etc/proxyfleet/local` 必须额外要求 `--purge-local-override`；
- 不得静默吞掉 systemd 错误。

## 6. 预期交付

### 6.1 命令语义

```text
start --with-mihomo
stop --with-mihomo
restart --with-mihomo
uninstall --with-mihomo
mihomo-start
mihomo-stop
mihomo-restart
mihomo-status
mihomo-uninstall
```

### 6.2 安全启动

- 验证 `mihomo.service` 为 ProxyFleet unit；
- 验证 `ExecStart` 指向受管二进制和受管 `config.yaml`；
- 验证当前配置可被 Mihomo 加载；
- 启动后验证 systemd active，必要时验证 loopback API；
- 失败时保留 Last Known Good。

### 6.3 安全停止

- 只停止服务；
- 保留二进制、配置、release、日志、local override；
- systemd stop 失败返回 `E_SERVICE_SYSTEMD`。

### 6.4 安全卸载

- 默认：停止并禁用服务，删除 ProxyFleet unit，保留 `/etc/proxyfleet`；
- `--purge-managed`：删除 managed/effective 产物，保留 local override；
- `--purge-all --yes`：删除受管 release、链接、unit 和受管二进制；
- `--purge-local-override`：仅与 `--purge-all --yes` 同用时删除 local override。

## 7. 必需证据和测试

- `bash -n scripts/proxyfleet-minion.sh`
- 默认 `start/stop/restart/uninstall` 不触碰 Mihomo 的自动化测试；
- `--with-mihomo` 顺序和失败路径测试；
- `mihomo-start/status/stop` mock systemd 测试；
- `mihomo-uninstall` 各 purge 级别删除清单测试；
- 至少一次真实 Ubuntu Minion smoke：启动、状态、停止、重新启动。

## 8. 依赖和阻塞

- 依赖 `native-mihomo` systemd unit 所有权标记稳定；
- 依赖组件锁和 release manifest 能提供二进制版本/哈希校验信息；
- 若现有机器由 ShellCrash 管理 Mihomo，必须先迁移或 fail-closed。

## 9. 完成条件

- 命令实现符合 `interfaces/MIHOMO_DRIVER.md`；
- 测试矩阵 3.9 通过；
- `docs/INSTALL_MINION.md`、`docs/OPERATIONS.md`、`docs/USER_MANUAL.md`
  更新为可执行教程；
- QA-RELEASE 与 SECURITY 未设置阻断；
- Result Packet 记录修改文件、测试命令和真实或 mock 证据。
