# Task Packet: TP-0025 Master/Minion 默认 TUI 主控台

> 状态：IMPLEMENTED
> Owner role：PRODUCT-SPEC / OPS-PLATFORM / CONTROL-SALT / DATA-MIHOMO
> Reviewer role：SECURITY / QA-RELEASE
> 创建日期：2026-06-25

## 1. 目标

让 `proxyfleet-master.sh` 和 `proxyfleet-minion.sh` 无参数运行时默认进入 TUI
主控台，用户通过菜单完成安装、配置、导入、同步、服务控制和卸载。

## 2. 非目标

- 不开发 Web UI；
- 不引入第三方 TUI 依赖，除非先完成组件锁定和安全审计；
- 不删除现有非交互子命令；
- 不绕过 Salt key 人工核验、组件锁、release hash、Mihomo API 回读验证；
- 不在 TUI 日志中输出订阅 URL、节点密码、API secret 或完整代理 URI。

## 3. 入口语义

```bash
sudo scripts/proxyfleet-master.sh
sudo scripts/proxyfleet-minion.sh
```

无参数进入 TUI。

显式子命令继续可用：

```bash
sudo scripts/proxyfleet-master.sh install
sudo scripts/proxyfleet-master.sh select-sync
sudo scripts/proxyfleet-minion.sh install --master <ip> --id <id>
sudo scripts/proxyfleet-minion.sh mihomo-status
```

## 4. Master TUI 菜单范围

- 安装/预检 Salt Master；
- 查看和接受 Salt Minion key；
- 配置订阅 URL；
- 导入自建节点文件；
- 导入自定义规则文件；
- 构建和校验 release；
- 进入节点测速选择 TUI 并同步；
- 配置 `config-src/port-policy.yaml`；
- 选择端口白名单同步模式；
- 查看服务状态和关键日志；
- 卸载和危险清理，危险操作二次确认。

## 5. Minion TUI 菜单范围

- 配置 Master 地址、Minion ID、environment、driver、release channel；
- 安装/重装 Salt Minion；
- 测试 Master TCP 4505/4506 连通性；
- 查看 Salt Minion 状态；
- 查看 Mihomo 状态；
- 执行 `mihomo-start/stop/restart/status/uninstall`；
- 编辑或导入 `/etc/proxyfleet/local/port-policy.yaml`；
- 设置本机端口策略模式：`merge/master-only/local-only/disabled`；
- 卸载和危险清理，危险操作二次确认。

## 6. Minion 本机策略模式

新增本机持久选项，例如：

```text
/etc/proxyfleet/local/options.json
```

示例：

```json
{
  "schema_version": "1.0",
  "port_policy_mode": "local-only"
}
```

优先级：

```text
Minion local option > Master 下发 mode > 默认 merge
```

## 7. 安全和确认

- 每个写操作先展示将修改的文件、服务、目标和危险等级；
- 写入配置后必须执行 schema/manifest 校验；
- 危险操作必须输入明确确认词；
- 无 TTY 或 curses 不可用时显示等价非交互命令；
- TUI 异常退出必须恢复终端状态。

## 8. 必需测试

- Master/Minion 无参数入口伪终端测试；
- 菜单导航、取消、确认和返回测试；
- 写入临时配置目录并校验文件内容；
- Minion local option 覆盖 Master mode 测试；
- 危险操作二次确认测试；
- 无 TTY fallback 测试；
- 全量 `unittest discover`、`bash -n`、`py_compile`、`git diff --check`。
