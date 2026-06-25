# Mihomo Native Driver 最小契约

> Contract 版本：0.1-draft
> 状态：DATA-MIHOMO Proposed
> 适用驱动：`native-mihomo`
> 依据：`PLAN.md`、`interfaces/CONTRACTS.md`、`component-locks.json`

## 1. 目标与边界

本文定义 ProxyFleet 原生 Mihomo 节点驱动的最小契约。该契约约束 Salt
Minion 在本机执行的安装、发布、选择、验证、回滚和状态上报行为。

V1 原生节点只管理：

- 锁定版本 Mihomo 二进制；
- `/etc/proxyfleet` 下的受管配置、端口策略和 release 链接；
- `mihomo.service`；
- 仅本机可访问的 Mihomo API secret；
- `FLEET_PROXY` 策略组选择。

V1 原生节点不管理：

- ShellCrash 生命周期；
- 公开管理 API 或 Web UI；
- 订阅 URL；
- 自研代理协议或 TUN 栈；
- Git commit、tag、push。

## 2. 组件锁与版本校验

`component-locks.json` 是 Mihomo 二进制版本来源。生产可安装前必须按架构锁定
具体资产 URL、SHA-256 和压缩格式。当前锁定候选为：

```text
name: mihomo
version: v1.19.27
kind: binary
role: data-plane
status: installable
artifacts: linux-amd64, linux-arm64
```

当前实现格式：

```yaml
name: mihomo
version: v1.19.27
artifacts:
  linux-amd64-compatible:
    url: https://github.com/MetaCubeX/mihomo/releases/download/v1.19.27/mihomo-linux-amd64-compatible-v1.19.27.gz
    sha256: 36850c946615f5c712946b62dbbbd06f6941d6d8a7543b315198bcb24ada3ea9
    compression: gzip
    target_path: /usr/local/bin/mihomo
  linux-amd64-v1:
    url: https://github.com/MetaCubeX/mihomo/releases/download/v1.19.27/mihomo-linux-amd64-v1-v1.19.27.gz
    sha256: b922f6fc90a232b9265db1cc9c5206fee8479dc2047bb037ebf09bc3c9e3b352
    compression: gzip
    target_path: /usr/local/bin/mihomo
  linux-amd64-v2:
    url: https://github.com/MetaCubeX/mihomo/releases/download/v1.19.27/mihomo-linux-amd64-v2-v1.19.27.gz
    sha256: eb052d1896b28bab7e027a34b1e610dfdb2a15f0807a1fac87a7768102e1060e
    compression: gzip
    target_path: /usr/local/bin/mihomo
  linux-amd64-v3:
    url: https://github.com/MetaCubeX/mihomo/releases/download/v1.19.27/mihomo-linux-amd64-v3-v1.19.27.gz
    sha256: c88b795ebad1f835156f17d33ca8d68bd6ea4dc68ba1be7f1d9910664faf4062
    compression: gzip
    target_path: /usr/local/bin/mihomo
  linux-arm64:
    url: https://github.com/MetaCubeX/mihomo/releases/download/v1.19.27/mihomo-linux-arm64-v1.19.27.gz
    sha256: 87db0c6660a9557a901b5750f997967e71d8c0af07ea1d1dd4d04c28da7f7e6f
    compression: gzip
    target_path: /usr/local/bin/mihomo
```

驱动必须执行以下校验：

1. `detect()` 读取本机 Mihomo 实际版本。
2. `preflight()` 比对实际版本、release manifest 中的 `mihomo_version`
   和组件锁版本。
3. 版本不一致时不得应用 release，返回 `E_MIHOMO_VERSION`。
4. amd64 Minion 必须根据 CPU flags 在同一版本的
   `linux-amd64-v3`、`linux-amd64-v2`、`linux-amd64-v1` 和
   `linux-amd64-compatible` 中选择可运行的最高锁定资产；arm64 Minion
   选择 `linux-arm64`。
5. 缺少当前架构二进制 SHA-256 锁定值时，不得安装或升级 Mihomo 二进制，
   返回 `E_COMPONENT_INTEGRITY_MISSING`。
6. 禁止自动更新 Mihomo；升级必须经过新锁条目、canary、QA 证据和
   SECURITY 评审。

版本比较必须使用完整版本字符串，不得使用前缀、语义化近似或“最新版本”。

## 3. SHA-256 校验

驱动必须区分二进制完整性和 release 文件完整性。

### 3.1 Mihomo 二进制

安装或升级二进制前必须具备组件锁中的架构级 SHA-256。若 `sha256` 为 `null`，
驱动只能检测现有二进制和上报状态，不得下载、替换或覆盖二进制。

若资产为 `.gz`：

1. 下载压缩资产到临时文件；
2. 校验压缩资产 SHA-256；
3. 解压到临时二进制；
4. 设置执行权限；
5. 运行版本探测；
6. 原子替换目标二进制。

下载失败、SHA 不匹配、gzip 解压失败、版本不匹配或权限设置失败均必须
fail-closed，不得覆盖现有可执行文件。

### 3.2 Release 文件

应用 release 时必须校验：

- `manifest.json` schema major 可支持；
- `manifest.sha256` 与 `manifest.json` 匹配；
- `config.yaml`、providers、rules 等所有 manifest 文件 SHA-256 匹配；
- 文件路径均为 release 目录内相对路径，禁止路径逃逸；
- 应用前和应用后各校验一次。

任一校验失败必须 fail-closed，不重启服务，不切换 release 链接，并返回
`E_RELEASE_HASH`。

## 4. 文件与 systemd 所有权

`native-mihomo` 拥有以下本机资源：

```text
/etc/proxyfleet/
  current -> /etc/proxyfleet/releases/<release_revision>
  previous -> /etc/proxyfleet/releases/<previous_release_revision>
  releases/
  managed/port-policy.yaml
  local/port-policy.yaml
  effective/port-policy.yaml
mihomo.service
```

约束：

- Provider 文件和 API secret 必须 root-only；
- release 目录不可变，更新通过新目录加原子链接切换完成；
- `current` 切换失败时必须保留旧链接；
- systemd unit 必须指向 `current/config.yaml`；
- systemd `daemon-reload`、`reload-or-restart` 失败必须返回
  `E_SERVICE_SYSTEMD`；
- `reload_or_restart()` 优先使用 Mihomo 支持的配置重载；重载不可用或失败时，
  才允许重启 `mihomo.service`；
- systemd 操作失败必须保留原始错误摘要并脱敏。

服务状态至少区分：

- `active`：服务运行；
- `inactive`：服务停止；
- `failed`：systemd failed；
- `unknown`：systemd 查询失败。

## 5. Loopback API 契约

Mihomo API 必须仅监听本机 loopback 地址或 Unix socket。禁止监听公网地址，
禁止通过未受保护的网络接口暴露 API。

驱动只依赖以下最小语义操作：

```text
get_version() -> MihomoVersion
get_policy_group(group_name) -> PolicyGroup
select_policy_group(group_name, mihomo_name) -> ApiWriteResult
reload_config() -> ApiWriteResult
get_provider(provider_name) -> ProviderStatus
update_provider(provider_name) -> ApiWriteResult
health_check(target?) -> HealthResult
close_managed_connections(target?) -> ApiWriteResult
```

其中 `health_check`、`close_managed_connections` 为可选能力。默认连接策略为
`preserve`，不得在未显式授权时关闭既有连接。

API 适配层可以映射到 Mihomo/Clash-compatible HTTP 端点或 Unix socket，但
本文不冻结具体端点路径。实现必须以锁定 Mihomo 版本的契约测试证明映射正确。

实时测速菜单使用 `health_check` 的只读子集。实现必须：

- 仅调用 loopback Mihomo API；
- 仅访问受控 allowlist 测速 URL；
- 不写 desired state；
- 不修改 `FLEET_PROXY` 当前选择；
- 不触发 reload/restart；
- 单节点失败只影响该节点的 `HealthResult`，不得中断其他节点测速；
- Master 本机结果标注为 `master-local`，不得混同为所有 Minion 的延迟。

API 调用必须：

- 使用本机 API secret；
- 设置短超时；
- 对连接失败、超时、非 2xx、JSON 解析失败统一映射为 `E_LOCAL_API`；
- 不在日志、Result、evidence 中输出 API secret。

## 6. `FLEET_PROXY` 选择契约

`FLEET_PROXY` 是保留策略组名，必须存在且为可选择组。统一节点切换只修改
该组选择，不重新生成 `config.yaml`。

`select_node(group, mihomo_name)` 必须按以下顺序执行：

1. 确认 `group == FLEET_PROXY` 或等于 desired state 的
   `managed_policy_group`。
2. 确认本机 release revision、provider revision 与 desired state 一致。
3. GET 策略组，确认目标 `selected_mihomo_name` 存在且可选。
4. 执行选择写入。
5. 再次 GET 同一策略组。
6. 确认当前选择等于目标 `selected_mihomo_name`。
7. 上报 `selected_node_id`、`selected_mihomo_name`、release/provider revision
   和脱敏证据。

若目标节点不存在，返回 `E_NODE_NOT_FOUND`。若写入后 GET 验证不一致，返回
`E_SELECT_VERIFY` 并触发回滚流程。

## 7. GET 再验证

所有会改变本机状态的操作都必须 GET 或等价只读查询再验证。单次写操作成功
不代表最终成功。

必须再验证的操作：

- release 链接切换后读取实际链接和文件 SHA；
- reload/restart 后读取 systemd 状态和 API version；
- Provider 更新后读取 provider revision 或可验证状态；
- `FLEET_PROXY` 选择后读取策略组当前选择；
- rollback 后读取 release、服务状态和策略组选择。

验证失败必须返回具体错误码，并在 Salt envelope 中将 `status` 标记为
`failed` 或 `drifted`，不得标记为 `success`。

## 8. 回滚契约

每个节点至少保留：

- 当前 release；
- 前一 release；
- 最后有效配置；
- 上一个稳定 `node_id` 和 `selected_mihomo_name`。

回滚分为两类：

### 8.1 Release 回滚

触发条件：

- 新 release 应用后校验失败；
- reload/restart 后 API 不可用；
- 配置加载失败；
- 健康验证失败且策略要求回滚。

流程：

1. 将 `current` 原子切回 `previous` 或 Last Known Good。
2. reload 或 restart `mihomo.service`。
3. 校验 manifest SHA、API version、systemd 状态。
4. 按需要恢复前一稳定节点选择。
5. 上报回滚结果。

### 8.2 节点选择回滚

触发条件：

- `FLEET_PROXY` COMMIT 失败；
- strict 模式下部分在线节点提交失败；
- GET 再验证不一致。

流程：

1. 对失败节点尝试选择回上一个稳定 `selected_mihomo_name`。
2. 再次 GET 验证。
3. 区分原始切换失败和回滚失败。
4. 回滚失败必须返回 `E_ROLLBACK_FAILED`，并设置最高优先级告警。

回滚不得猜测目标。缺少 previous release 或 previous node 记录时，必须返回
`E_ROLLBACK_UNAVAILABLE`，并保留当前可观测状态。

## 9. 逻辑接口

驱动对 Salt State/Module 暴露统一逻辑接口：

```text
detect() -> DriverInfo
preflight(release, desired) -> PrepareResult
install_release(release) -> ApplyResult
reload_or_restart() -> ServiceResult
select_node(group, mihomo_name) -> SelectResult
verify(release, desired) -> VerifyResult
rollback(previous_release, previous_node) -> RollbackResult
status() -> NodeStatus
```

返回值必须可映射到 `interfaces/CONTRACTS.md` 的 Salt 作业 envelope。所有
`message` 和 `evidence` 均须脱敏，不得包含订阅 URL、节点密码、UUID 私密字段
或 API secret。

## 10. 错误码映射

本文件补充 native driver 层错误码。若与 `interfaces/CONTRACTS.md` 中标准码
重叠，优先使用标准码。

| 错误码 | 触发条件 | 默认行为 |
|---|---|---|
| E_MIHOMO_VERSION | 实际 Mihomo 版本、manifest 版本或组件锁版本不一致 | PREPARE 失败，fail-closed |
| E_COMPONENT_INTEGRITY_MISSING | 组件锁缺少 Mihomo 二进制 SHA-256 | 禁止安装/升级 |
| E_RELEASE_HASH | manifest 或 release 文件 SHA-256 不符 | 阻断应用 |
| E_CONFIG_VALIDATE | Mihomo 配置校验或加载失败 | 阻断发布/回滚 |
| E_SERVICE_SYSTEMD | `mihomo.service` 查询、reload、restart 失败 | 失败/按策略回滚 |
| E_LOCAL_API | loopback API 不可用、超时、非 2xx 或响应不可解析 | 失败/回滚 |
| E_PROVIDER_MISMATCH | provider revision 与 desired state 不一致 | PREPARE 失败 |
| E_NODE_NOT_FOUND | 目标 `selected_mihomo_name` 不在 `FLEET_PROXY` 可选项中 | 不提交 |
| E_SELECT_VERIFY | 选择后 GET 再验证不一致 | 回滚 |
| E_ROLLBACK_UNAVAILABLE | 缺少 previous release 或 previous node 记录 | 停止猜测，报告漂移 |
| E_ROLLBACK_FAILED | 回滚执行或回滚后验证失败 | 最高优先级告警 |
| E_SCHEMA_UNSUPPORTED | schema major 不支持或未知必填字段 | fail-closed |

## 11. 最小验收证据

每次 native driver 实现或变更至少需要以下证据：

- Ubuntu 22.04 x86_64 原生节点 install/reload/rollback 通过；
- Ubuntu 24.04 x86_64 smoke test 通过；
- `FLEET_PROXY` 成功选择后 GET 再验证通过；
- 目标节点不存在时返回 `E_NODE_NOT_FOUND`；
- API 不可用时返回 `E_LOCAL_API` 并不误报成功；
- release SHA 错误时返回 `E_RELEASE_HASH` 且不切换 current；
- 缺少 Mihomo 二进制 SHA 时禁止安装/升级；
- 回滚成功和回滚失败路径均有脱敏证据。

未完成上述证据前，结果只能标记为 PROPOSED 或 PARTIAL，不得标记为生产可用。
