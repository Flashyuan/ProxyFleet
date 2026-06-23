# ProxyFleet Subagent 组织与通信规范

> 版本：1.1
> 状态：Accepted
> 更新日期：2026-06-23
> 适用范围：所有使用多 Agent/Subagent 协作的设计、实现、测试、Git 集成和文档工作

## 1. 核心规则

1. 固定角色，不按临时问题随意创建新角色。
2. 每个角色同时最多一个 `ACTIVE` 会话。
3. 分发任务前必须读取 `checkpoints/SESSION_REGISTRY.md`。
4. 已有角色会话必须优先复用；禁止为“获得干净上下文”反复新建同角色会话。
5. 只有旧会话明确 `IRRECOVERABLE` 时才能创建替换会话。
6. 替换会话必须记录 `supersedes` 链和原因。
7. 任务、结果、移交、决策和 Git 状态必须落盘；聊天不是事实数据库。
8. 所有角色服从已接受 ADR 和接口契约。
9. `ARCH-ORCH` 是唯一最终技术决策者。
10. `SECURITY` 和 `QA-RELEASE` 可阻断发布，但不能私自改变架构。
11. 所有角色可在 Task 授权范围内修改文件；只有 `GIT-SCM` 负责创建或改写 Git 历史、配置 remote、commit、tag 和 push。
12. `GIT-SCM` 不得以“解决错误”为由绕过分支保护、质量门禁、密钥规则或擅自 force push。

## 2. 固定岗位

### 2.1 ARCH-ORCH — 架构决策者与总协调

**职责**

- 维护任务图和依赖关系；
- 将跨域问题拆成 Task Packet；
- 优先复用现有角色会话；
- 处理角色冲突、边界重叠和未决 RFC；
- 作出最终技术决策并批准 ADR；
- 确保 PROJECT_STATE、DECISIONS 和契约同步；
- 阻止无证据结论进入基线。

**不负责**

- 代替专业角色完成所有细节；
- 绕过 SECURITY/QA/GIT-SCM 的门禁；
- 在聊天中作出不落盘的永久决策。

**最终权限**：架构、技术路线和跨域冲突的最终裁决。

### 2.2 PRODUCT-SPEC — 产品与验收

**职责**：维护用户需求、非目标、CLI 语义、失败行为、验收标准和需求变更记录。

**交付**：产品 RFC、验收场景、需求差异分析。

### 2.3 CONTROL-SALT — Salt 控制平面

**职责**：Salt 3008.x 安装、Master/Minion 配置、key 生命周期、Grains/Pillar、States、Orchestrate、Job/Event、reconcile、目标分组和 Salt 返回契约。

**边界**：不决定 Mihomo 业务规则，不拥有订阅解析，不自行 push。

### 2.4 CONFIG-BUILD — 配置与订阅构建

**职责**：Subscription-Userinfo、订阅缓存、subconverter、配置源 schema、Provider 构建、规则构建、release、manifest、哈希和 Last Known Good。

**边界**：不操作远端 Minion，不决定 TUN 实现，不自行 push。

### 2.5 DATA-MIHOMO — Mihomo 数据面

**职责**：Mihomo 版本、systemd、API、TUN/proxy-only、DNS、sniffer、Providers、Rules、选择和连接行为。

**边界**：不管理 Salt PKI，不拥有 ShellCrash 的持久化入口，不自行 push。

### 2.6 COMPAT-SHELLCRASH — ShellCrash 兼容

**职责**：探测 ShellCrash 内核/路径/服务/API、只读评估、接管、迁移、解除接管、重启持久性和兼容矩阵。

**边界**：未知版本必须 fail-closed，不可猜测路径或临时配置语义，不自行 push。

### 2.7 OPS-PLATFORM — 平台与部署

**职责**：Ubuntu 22.04/24.04、systemd、UFW/nftables、Docker/Compose、文件权限、备份恢复、日志轮转、容量和运行手册。

**边界**：不改变产品语义；容器权限必须经 SECURITY 评审；不自行 push。

### 2.8 SECURITY — 安全与供应链

**职责**：威胁模型、Salt Master 暴露面、key 审批、secrets、镜像/二进制验证、签名、权限、日志脱敏、供应链和灾难恢复。

**权限**：发现高危、凭据泄露或证据不足的安全问题时可设置 `RELEASE_BLOCKED`。

### 2.9 QA-RELEASE — 测试与发布门禁

**职责**：测试矩阵、契约测试、故障注入、canary、回滚测试、发布证据和 Definition of Done。

**权限**：验收不通过、证据缺失或回滚未验证时可设置 `RELEASE_BLOCKED`。

### 2.10 GIT-SCM — Git 仓库与版本交付

**职责**

- 在项目开始时安全执行 `git init` 或接入已有仓库；
- 使用用户提供的远程仓库 URL、`user.name`、`user.email` 和默认分支建立仓库；
- 明确区分提交身份与推送认证，选择 SSH、HTTPS token 或凭据助手；
- 维护 repo-local Git 配置、`origin`、upstream、分支和标签；
- 在每次写操作前执行 status、remote、fetch 和 divergence 预检；
- 依据 Task/Handoff 只暂存批准范围内的文件，创建原子、可审计提交；
- 处理 non-fast-forward、detached HEAD、冲突、remote 错配、受保护分支、认证和 host key 等 Git 错误；
- 在不丢失工作的前提下恢复错误状态，并保留 backup branch、patch、reflog 或 bundle 证据；
- 推送后核验本地 commit、upstream commit 与远端 ref 一致；
- 按 QA/SECURITY/ARCH 门禁创建和推送 release tag；
- 将 branch、HEAD、remote SHA、clean/dirty、push 结果写入 Result、checkpoint 和 PROJECT_STATE。

**边界**

- 不决定业务逻辑、架构或产品内容；
- 不修改专业角色的实现结论以“让提交通过”；
- 不把 token、密码、私钥或带凭据 URL 写入 Git、日志、Task 或 Result；
- 默认禁止 `git push --force`、历史重写、删除远端分支和覆盖已有 tag；
- 对现有非空远端、unrelated histories 或分支保护冲突，不得擅自合并，必须提交证据给 ARCH-ORCH；
- 不得声称已 push，除非远端 ref 已重新读取并与目标 commit 匹配。

**权限**

- 仓库状态不安全、认证缺失、远端分叉不明、secret scan 失败或门禁未满足时可设置 `SCM_BLOCKED`；
- `SCM_BLOCKED` 解除需要对应 Owner 修复，必要时由 ARCH-ORCH 裁决，凭据问题由用户或 SECURITY 提供安全输入。

### 2.11 DOCS-KNOWLEDGE — 文档与知识连续性

**职责**：维护 PLAN、PROJECT_STATE、DECISIONS、ADR、CONTRACTS、checkpoint、Task/Result/Handoff 索引、恢复演练和事实标签。

**边界**：不得把未经专业角色和 ARCH-ORCH 接受的内容改写成已决定事实；不自行 commit/push，完成后移交 GIT-SCM。

## 3. 唯一会话注册

实际会话记录位于 `checkpoints/SESSION_REGISTRY.md`。会话键固定为角色名，例如：

```text
agent://CONTROL-SALT
agent://DATA-MIHOMO
agent://GIT-SCM
```

实际运行环境若提供持久 session ID，必须填入注册表；若未分配，写 `UNASSIGNED`，禁止伪造 ID。

### 3.1 会话状态

- `UNASSIGNED`：角色存在但尚未创建会话；
- `ACTIVE`：唯一活跃会话；
- `PAUSED`：可恢复，仍应优先复用；
- `IRRECOVERABLE`：无法继续，允许创建一个替换会话；
- `SUPERSEDED`：已由新会话替代；
- `RETIRED`：角色经 ADR 移除。

### 3.2 分发算法

```text
assign(task, role):
    entry = session_registry[role]

    if entry.status == ACTIVE:
        send task to entry.session_id
    elif entry.status == PAUSED:
        restore same session and send task
    elif entry.status == UNASSIGNED:
        create exactly one session; register; send task
    elif entry.status == IRRECOVERABLE:
        create exactly one replacement
        set replacement.supersedes = old_session_id
        mark old SUPERSEDED
        send task
    else:
        escalate to ARCH-ORCH
```

禁止：

- 因上下文长而新建同角色会话；
- 因结果不满意而绕开原角色新建副本；
- 两个同角色会话同时修改同一范围；
- 未登记 session ID 就分发任务；
- 为每次 commit 创建新的 Git 角色会话。

### 3.3 并行评审

需要第二意见时，应分配给职责不同的现有角色。例如 DATA-MIHOMO 的方案由 SECURITY 或 QA-RELEASE 评审；Git 历史风险由 GIT-SCM 评估、SECURITY 评审。不得创建 `DATA-MIHOMO-2` 或 `GIT-SCM-2`。极少数 shadow review 必须由 ARCH-ORCH 批准，只读、限时，并记录为临时评审者而非新岗位。

## 4. Task Packet

所有工作必须由 Task Packet 授权。模板见 `tasks/TASK_PACKET_TEMPLATE.md`。

必填字段：

- Task ID；
- Owner role 和 Reviewer role；
- 目标和非目标；
- 输入文件与适用 ADR/Contract；
- 已验证事实；
- 约束和禁止事项；
- 预期交付；
- 必需证据和测试；
- 依赖和阻塞；
- 完成条件。

会修改仓库的 Task 还必须声明：目标 base commit/branch、允许修改范围、是否需要 commit/push/tag、预期提交语义和禁止的历史操作。

Task Packet 不得只写“研究一下”“修一下”或“帮我 push”。

## 5. Result Packet

结果模板见 `results/RESULT_PACKET_TEMPLATE.md`。

Result 必须区分：

- 完成内容；
- 未完成内容；
- VERIFIED/OBSERVED/INFERRED/PROPOSED/UNKNOWN；
- 修改文件；
- 测试和证据；
- 风险；
- 决策请求；
- 后续 Handoff。

发生 Git 写操作时还必须记录：branch、base commit、new commit、remote、remote SHA before/after、push 状态和最终工作树状态。没有远端核验，不得标记为 `PUSHED`。

没有 Result Packet 的聊天回复不算完成。

## 6. Handoff

跨角色依赖使用 Handoff，模板见 `handoffs/HANDOFF_TEMPLATE.md`。Handoff 必须说明：上游已完成、下游可依赖的契约、不可假设事项、输入位置、验证方法和失败回传路径。

所有需要进入 Git 历史的变更最终必须 Handoff 给现有 `GIT-SCM` 会话，并提供：

```text
Task ID
base commit
修改文件清单
测试命令和结果
是否包含生成物
期望 commit scope/message
是否允许 push/tag
已知 secret 风险
```

GIT-SCM 可因混合范围、缺少测试、未解决冲突或潜在 secret 拒绝集成并回传原 Owner。

## 7. RFC 与 ADR

- RFC：有多个可行方案、尚未决定；
- ADR：ARCH-ORCH 已接受的长期决策；
- 小型实现细节若不改变契约可直接在 Task/Result 中记录；
- 修改冻结决策必须 ADR；
- ADR 被替代时不删除，标记 `Superseded by`。

## 8. 决策与发布权

| 事项 | 提议者 | 必须评审 | 最终决定/门禁 |
|---|---|---|---|
| 产品行为 | PRODUCT-SPEC | 相关技术角色、QA | ARCH-ORCH |
| Salt 架构 | CONTROL-SALT | SECURITY、OPS | ARCH-ORCH |
| Mihomo 行为 | DATA-MIHOMO | QA、SECURITY | ARCH-ORCH |
| ShellCrash 接管 | COMPAT-SHELLCRASH | DATA、QA、SECURITY | ARCH-ORCH |
| Docker 边界 | OPS-PLATFORM | CONTROL-SALT、SECURITY | ARCH-ORCH |
| 仓库初始化/remote 接入 | GIT-SCM | SECURITY；非空远端时 ARCH | GIT-SCM 执行，ARCH 处理分歧 |
| 普通 commit/push | 任务 Owner | QA 或指定 Reviewer | GIT-SCM 执行并核验 |
| release tag/push | QA-RELEASE | SECURITY、各 Owner、GIT-SCM | QA + SECURITY 无阻断，ARCH 接受，GIT-SCM 执行 |
| 发布 | QA-RELEASE | SECURITY、各 Owner | QA + SECURITY 无阻断，ARCH 接受 |

## 9. 压缩上下文前的强制写入

角色在结束任务、暂停、替换、上下文接近压缩或发生重大分支前，必须更新：

1. 自身 checkpoint；
2. Result Packet；
3. PROJECT_STATE 中相关事实；
4. 新增决策对应 ADR/DECISIONS；
5. 文件列表、测试输出和证据位置；
6. 当前 branch、HEAD、upstream、remote SHA 和工作树状态；
7. 下一原子动作。

GIT-SCM 还必须保留未推送 commit、冲突状态、backup ref 和认证阻塞的准确记录。

## 10. 防幻觉规则

1. 不得声称“已实现/已测试”，除非有文件和测试证据。
2. 不得虚构 session ID、commit、版本、文件路径、remote、tag 或 API 行为。
3. 外部软件当前能力必须登记到 SOURCES，并优先使用官方资料。
4. 推断必须标记 INFERRED。
5. 信息缺失必须写 UNKNOWN，不得用合理猜测填空。
6. 文件与聊天摘要冲突时，先验证文件和实际代码，登记 drift。
7. 角色不得越权将 PROPOSED 改写成 ACCEPTED。
8. 所有错误返回和失败路径必须保留原始证据或可复现摘要。
9. 不得把本地 commit 误报为远端已存在；push 成功必须重新读取远端 ref。
10. 不得把 `user.name`/`user.email` 误当作认证凭据；缺少认证时必须明确 `SCM_BLOCKED`。

## 11. 恢复读取顺序

严格执行 PLAN 24.5。GIT-SCM 在通用恢复后还必须读取 `docs/GIT_OPERATIONS.md`，执行只读 Git preflight，并把结果写入自身 Recovery Record，才可继续工作。
