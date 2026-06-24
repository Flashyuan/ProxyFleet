# ProxyFleet 接口契约

> Contract 版本：0.2-draft
> 状态：Architecture Baseline；实现前仍可通过 ADR/RFC 修订

## 1. 版本原则

- 每个结构包含 `schema_version`；
- 向后兼容变更提升 minor；
- 破坏性变更提升 major，并要求迁移；
- 未知必填字段或不支持 major 时必须 fail-closed；
- 时间统一 RFC 3339 UTC；
- node_id、release_revision、operation_id 不复用。

## 2. 配置源契约

### 2.1 `providers.yaml`

伪结构：

```yaml
schema_version: "1.0"
providers:
  - id: airport-main
    kind: subscription
    secret_ref: AIRPORT_MAIN_URL
    output: providers/airport-main.yaml
    name_prefix: "[A] "
    enabled: true
  - id: self-hosted
    kind: local_file
    source: nodes/self-hosted.yaml
    output: providers/self-hosted.yaml
    name_prefix: "[SELF] "
    enabled: true
```

约束：`id` 唯一；secret_ref 只在主节点解析；输出路径不得逃逸 release 目录。

### 2.2 `groups.yaml`

```yaml
schema_version: "1.0"
groups:
  - name: FLEET_PROXY
    type: select
    use: [airport-main, self-hosted]
```

`FLEET_PROXY` 是保留名称，必须存在且为可选择组。

### 2.3 `rules.yaml`

```yaml
schema_version: "1.0"
order:
  - rule_provider: direct
    target: DIRECT
  - rule_provider: force-proxy
    target: FLEET_PROXY
  - match: MATCH
    target: DIRECT
```

规则顺序是语义的一部分，不允许构建器重排。

## 3. Release Manifest

`manifest.json` 伪结构：

```json
{
  "schema_version": "1.0",
  "release_revision": 42,
  "created_at": "2026-06-22T12:00:00Z",
  "source_git_commit": "<sha>",
  "mihomo_version": "<pinned-version>",
  "provider_revision": 18,
  "files": [
    {"path": "config.yaml", "sha256": "...", "size": 1234}
  ]
}
```

约束：

- revision 单调递增；
- 所有路径为 release 内相对路径；
- SHA-256 必须在应用前和应用后验证；
- manifest 自身写入后不可修改；
- 发布通过原子目录/链接切换。

## 4. Desired State

```yaml
schema_version: "1.0"
desired_revision: 107
release_revision: 42
provider_revision: 18
target_group: production
managed_policy_group: FLEET_PROXY
selected_node_id: node-a81f92
selected_mihomo_name: "[A] JP-01"
connection_policy: preserve
activate_at: null
failure_policy: fail-closed
```

约束：

- selected_node_id 是管理层稳定身份；
- selected_mihomo_name 是本 release 中 API 实际名称；
- Agent/Minion 必须先验证 release/provider revision，再切换；
- 离线节点只应用最新 desired_revision。

## 5. 节点目录

每个节点至少包含：

```text
node_id
mihomo_name
provider_id
protocol
fingerprint
availability
```

V1 的稳定 ID 可由规范化连接参数的哈希生成，但不得在日志中泄露密钥。重命名不应改变 node_id；连接参数变更应产生新 ID，除非有显式迁移映射。

## 6. Subscription Status

```json
{
  "schema_version": "1.0",
  "provider_id": "airport-main",
  "freshness": "fresh|stale|unknown",
  "fetched_at": "...",
  "upload_bytes": 0,
  "download_bytes": 0,
  "total_bytes": 0,
  "remaining_bytes": 0,
  "expire_at": null,
  "userinfo_source": "header|body|cache|absent",
  "content_sha256": "...",
  "last_error_code": null
}
```

缺失字段使用 null，不得把未知写成 0。

## 7. Minion 身份与驱动

必需属性：

```yaml
minion_id: vps-01
environment: production
driver: native-mihomo | shellcrash-discovery | shellcrash-compat
os_baseline: ubuntu-22.04 | ubuntu-24.04
release_channel: stable | canary
port_policy_mode: merge | master-only | local-only | disabled
```

Minion ID 必须人工可识别且唯一，不依赖临时 IP。

## 8. 本地驱动接口

所有驱动提供相同逻辑操作：

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

### 8.1 `native-mihomo`

拥有 `/etc/proxyfleet`、`mihomo.service` 和 API secret。

生产主路径。所有生产 Minion 应使用该驱动。

### 8.2 `shellcrash-discovery`

只读探测 ShellCrash 状态、路径、内核和可迁移信息；不得写入配置或启动第二个
Mihomo。

### 8.3 `shellcrash-compat`

仅用于迁移窗口内的有限应急操作；不作为生产成功条件，不承诺 config hash 一致。

## 8A. 端口白名单契约

端口白名单配置分为三层：

```text
managed:   /etc/proxyfleet/managed/port-policy.yaml
local:     /etc/proxyfleet/local/port-policy.yaml
effective: /etc/proxyfleet/effective/port-policy.yaml
```

`managed` 由 Master 同步；`local` 由 Minion 本机维护；`effective` 由 Minion
合并生成。Master 不得覆盖或删除 `local`。

最小 schema：

```yaml
schema_version: "1.0"
owner: master | local
mode: merge
allow:
  - protocol: tcp
    port: 22
    source: 192.168.1.0/24
    comment: ssh management
deny: []
```

合并结果必须保留每条规则来源。冲突、语法错误或应用失败必须返回结构化错误，
且不得覆盖 Last Known Good effective policy。

## 9. Mihomo API 契约

本项目只依赖以下最小能力：

- 读取版本；
- 读取特定策略组；
- 选择策略组节点；
- 读取/更新特定 Proxy Provider；
- 重载配置；
- 可选健康检查；
- 可选读取/关闭受管连接。

API 必须只在本机可访问。驱动调用后必须 GET 再验证，不以单次 HTTP 成功作为最终成功。

## 10. Salt 作业结果

所有受管操作返回统一 envelope：

```json
{
  "schema_version": "1.0",
  "operation_id": "op-...",
  "minion_id": "vps-01",
  "phase": "prepare|apply|verify|rollback|status",
  "status": "success|failed|skipped|offline|drifted",
  "error_code": null,
  "message": "redacted summary",
  "release_revision": 42,
  "desired_revision": 107,
  "evidence": {"config_sha256": "...", "selected_node_id": "..."}
}
```

禁止在 message/evidence 中返回订阅 URL、节点密码、UUID 私密字段或 API secret。

## 11. 状态机

```text
UNENROLLED
→ ENROLLED
→ READY
→ PREPARING
→ APPLYING
→ VERIFYING
→ APPLIED

任一阶段可进入 DEGRADED 或 ROLLBACK_REQUIRED；
Master 不可达时状态为 CONTROL_OFFLINE，但数据面可保持 APPLIED。
```

## 12. 标准错误码

| 错误码 | 含义 | 默认行为 |
|---|---|---|
| E_SUB_FETCH | 订阅获取失败 | 使用缓存，不发布新 Provider |
| E_SUB_INVALID | 正文无效/HTML/空 | 阻断构建 |
| E_RELEASE_HASH | release 哈希不符 | 阻断应用 |
| E_CONFIG_VALIDATE | Mihomo 配置校验失败 | 阻断发布 |
| E_PROVIDER_MISMATCH | Provider revision 不一致 | PREPARE 失败 |
| E_NODE_NOT_FOUND | 目标节点不存在 | 不提交 |
| E_LOCAL_API | 本机 API 不可用 | 失败/回滚 |
| E_SELECT_VERIFY | 选择后验证不符 | 回滚 |
| E_SHELLCRASH_UNSUPPORTED | 不支持的 ShellCrash 环境 | fail-closed |
| E_ROLLBACK_FAILED | 回滚失败 | 最高优先级告警 |
| E_SCHEMA_UNSUPPORTED | 契约版本不支持 | fail-closed |

## 13. Git Repository Profile

首次 bootstrap 的输入契约：

```yaml
schema_version: "1.0"
remote_repository_url: "<url>"
user_name: "<commit identity>"
user_email: "<commit identity>"
default_branch: "main"
auth_method: "ssh|https-token|credential-helper"
credential_reference: "<out-of-repo reference>"
remote_expected_state: "empty|existing|unknown"
```

约束：

- `user_name`/`user_email` 只用于 commit 元数据；
- `credential_reference` 不得包含在 Result、日志或 Git 文件中；
- URL 必须脱敏，不得内嵌 token/password；
- remote 状态必须通过只读探测验证，不能只相信 `remote_expected_state`。

## 14. Git Operation Result

```json
{
  "schema_version": "1.0",
  "operation_id": "git-op-...",
  "task_id": "TP-0002",
  "status": "success|blocked|failed|no-op",
  "repository_path": "<local path>",
  "branch": "main",
  "base_commit": null,
  "new_commit": "<sha-or-null>",
  "upstream_ref": "refs/remotes/origin/main",
  "remote_url_redacted": "<safe url>",
  "remote_head_before": null,
  "remote_head_after": "<sha-or-null>",
  "push_status": "not-requested|not-attempted|blocked|pushed-and-verified",
  "worktree_status": "clean|dirty-explained|conflicted",
  "error_code": null,
  "evidence_paths": []
}
```

约束：

- `pushed-and-verified` 仅在重新读取远端 ref 并与 `new_commit` 一致时使用；
- remote SHA、branch、commit 不得虚构；
- 工作树非 clean 时必须列出归属或原因；
- 任何认证秘密均不得出现在 envelope；
- GIT-SCM 是本契约的唯一写操作 producer。

### 14.1 Git 标准错误码

| 错误码 | 含义 | 默认行为 |
|---|---|---|
| E_GIT_INPUT | bootstrap 输入不完整 | SCM_BLOCKED，等待输入 |
| E_GIT_AUTH | 认证失败或凭据缺失 | 不重试泄露凭据，升级用户/SECURITY |
| E_GIT_REMOTE | remote 不存在、URL 错误或不可达 | 保留本地状态，阻断 push |
| E_GIT_DIVERGED | 本地和远端均有新提交 | fetch 后安全集成，不 force |
| E_GIT_UNRELATED | 历史无共同祖先 | ARCH 决策 |
| E_GIT_PROTECTED | 分支保护拒绝写入 | 使用工作分支或请求权限 |
| E_GIT_SECRET | 检测到秘密/敏感文件 | SECURITY 阻断并轮换 |
| E_GIT_CONFLICT | merge/rebase 冲突 | 内容 Owner 解决语义 |
| E_GIT_REMOTE_VERIFY | push 后远端 SHA 不符 | 停止后续发布，最高优先核查 |
| E_GIT_HISTORY_POLICY | 请求了未授权历史重写 | 拒绝操作 |

## 15. 兼容与变更

任何角色修改本文件必须：

1. 创建 Task Packet；
2. 说明兼容影响；
3. 由相关 Owner、QA 和 SECURITY 评审；
4. 破坏性修改通过 ADR；
5. 更新契约测试。
