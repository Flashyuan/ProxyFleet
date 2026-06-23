# ProxyFleet Git 仓库与版本操作手册

> 版本：1.0
> 状态：Accepted operational baseline
> Owner：GIT-SCM
> 更新日期：2026-06-23

## 1. 目的

本文件定义项目从零建立 Git、接入远端、提交、推送、发布标签、错误处理、证据记录和上下文恢复的统一流程。它不替代 Git 官方文档，也不授权绕过仓库权限或保护规则。

## 2. 角色与所有权

- 专业 Subagent：在 Task 允许范围内修改文件、运行测试、提供 Handoff；
- GIT-SCM：唯一执行 stage/commit/merge/rebase/tag/remote/push 的岗位；
- QA-RELEASE：验证提交对应的功能和发布证据；
- SECURITY：验证 secret、凭据、签名和供应链风险；
- ARCH-ORCH：解决 unrelated histories、历史重写和跨域冲突。

必须复用 `checkpoints/SESSION_REGISTRY.md` 中已有的 GIT-SCM 会话。

## 3. 首次启动所需输入

```yaml
remote_repository_url: "<required>"
user_name: "<required>"
user_email: "<required>"
default_branch: "main"
auth_method: "ssh | https-token | credential-helper"
credential_reference: "<secret reference, never committed>"
remote_expected_state: "empty | existing | unknown"
```

### 3.1 身份与认证的区别

- `user.name`、`user.email`：写入 commit 的 author/committer 元数据；
- SSH key、token 或 credential helper：证明有权访问和写入远端。

只提供 URL、用户名和邮箱时，可以初始化并提交本地仓库，但不一定能 push。缺少认证时应输出 `SCM_BLOCKED/AUTH_REQUIRED`。

## 4. 项目 bootstrap 流程

### 4.1 只读预检

```text
assert task == TP-0002
read PLAN/AGENTS/STATE/ADR/CONTRACTS/checkpoint/task
inspect filesystem without deleting anything
check git version
check whether .git exists
check current status/branch/HEAD/remotes
probe remote with git ls-remote
classify remote as empty/existing/unreachable/unauthorized
record exact evidence with secrets redacted
```

任何一步无法判断时停止，不猜测。

### 4.2 空本地目录 + 空远端

伪流程：

```text
copy approved project files into worktree
create .gitignore and .gitattributes from reviewed baseline
git init -b main
git config --local user.name  PROVIDED_NAME
git config --local user.email PROVIDED_EMAIL
git remote add origin PROVIDED_URL
run secret and generated-file preflight
git add only approved paths
git diff --cached --check
git diff --cached --stat
create atomic bootstrap commit
push with upstream
read remote ref again
assert remote/main == local HEAD
write Result + checkpoint + PROJECT_STATE
```

推荐首个提交语义：

```text
chore(repo): bootstrap ProxyFleet project
```

### 4.3 已有本地 Git 仓库

- 不重复 `git init` 作为修复手段，先读取现有 remote、branch、HEAD 和 status；
- 未提交改动不得被 `reset --hard`、`clean -fd` 或覆盖；
- 在任何可能改写工作树的操作前创建 backup branch、patch 或 bundle；
- remote URL 不一致时只报告，不静默 `set-url`；
- detached HEAD 时先创建命名分支保留当前 commit。

### 4.4 非空远端

```text
fetch remote refs
record remote default branch and SHA
find merge-base with local history
```

- 有共同祖先且可 fast-forward：按批准方向更新；
- 双方都有新提交：创建安全集成分支，解决冲突，重新测试；
- 无共同祖先：标记 `SCM_BLOCKED/UNRELATED_HISTORIES`，提交 RFC/决策，不自动 `--allow-unrelated-histories`；
- 远端已有 README/LICENSE 等初始化提交也属于真实历史，不得直接 force 覆盖。

## 5. 日常变更集成

### 5.1 输入 Handoff

GIT-SCM 仅接收包含以下信息的 Handoff：

```text
Task ID
Owner role
base commit
修改文件清单
测试命令与结果
生成物处理方式
期望 commit scope/message
是否需要 push/tag
secret 风险声明
```

### 5.2 预提交检查

```text
git status --porcelain=v2 --branch
verify current base/upstream
fetch origin without modifying working files
check remote divergence
inspect untracked and ignored files
run required tests
run secret scan or reviewed equivalent
git diff --check
git diff --stat
git diff --cached after staging
```

只暂存当前 Task 的文件。混入其他 Task 变更时必须拆分或退回 Owner。

### 5.3 提交策略

- 一个 commit 对应一个逻辑变更；
- 提交消息默认采用：`type(scope): summary`；
- 不使用无信息消息，如 `update`、`fix stuff`；
- 不把运行时缓存、订阅原文、secrets、私钥、token、release 临时目录或日志提交；
- `git commit --amend` 只允许修改尚未 push 的当前 Task commit，或有明确 Task 授权；
- 已 push commit 的修复默认用新 commit，不重写共享历史。

推荐类型：

```text
feat fix docs test refactor chore build ci perf revert
```

### 5.4 推送与验证

```text
fetch origin
assert expected remote SHA has not changed
git push --set-upstream origin <branch>   # first push
git push origin <branch>                  # later push
git ls-remote --heads origin <branch>
assert remote SHA == local HEAD
```

Result 至少记录：

```text
branch
local_head
upstream
remote_head_before
remote_head_after
push_status
worktree_status
```

## 6. 分支与发布模型

### 6.1 默认分支

- 默认分支：`main`；
- 初始空仓库允许首个 bootstrap commit 直接建立 `main`；
- 后续工作默认使用短生命周期分支：`work/TP-XXXX-slug`；
- 合并前必须满足 Task 的 reviewer、QA 和 SECURITY 要求；
- 无 Web UI 时，可由 GIT-SCM 在 CLI 中完成受控 merge，但仍需落盘评审结果。

### 6.2 Release tag

- tag 名称由产品发布规范决定，例如 `v0.1.0`；
- tag 必须指向已通过 QA/SECURITY 门禁的 commit；
- 同名远端 tag 存在但 SHA 不同时，禁止覆盖；
- tag push 后重新读取远端 tag SHA；
- release manifest 记录 `source_git_commit`。

## 7. 错误处理矩阵

| 错误/状态 | GIT-SCM 处理 | 禁止行为 | 升级条件 |
|---|---|---|---|
| `not a git repository` | 确认目录和 Task；仅在 bootstrap 时 init | 在未知目录盲目 init | 文件来源不明 |
| `remote origin already exists` | 读取并比较 URL | 直接覆盖 URL | URL 与用户输入不同 |
| `repository not found` | 核对 URL、账号访问权和命名 | 猜测新 URL | 需要仓库管理员授权 |
| `authentication failed` | 判定 SSH/HTTPS；验证 key/token/credential helper | 把 token 写进 URL 或日志 | 需要用户提供/授权凭据 |
| SSH host key 失败 | 通过可信渠道核验 host fingerprint | 使用关闭 host key 检查的永久配置 | 指纹无法核验 |
| `non-fast-forward` | fetch、比较、建立安全集成分支 | 裸 force push | 远端有未知提交或冲突 |
| unrelated histories | 停止并提交差异证据 | 自动 `--allow-unrelated-histories` | ARCH 决策 |
| detached HEAD | 创建保留当前 commit 的命名分支 | 丢弃当前 commit | commit 归属不清 |
| merge/rebase conflict | 交回内容 Owner 解决语义；GIT-SCM 管理 Git 状态 | 擅自选择业务内容 | 跨域冲突 |
| uncommitted changes | 分类、Handoff、patch/backup | `reset --hard`/`clean -fd` | 文件所有者不明 |
| protected branch rejected | 推工作分支或申请权限 | 绕过保护 | 需管理员修改规则 |
| secret scan failure | 停止，移除并轮换泄露秘密 | 继续 commit/push | SECURITY 立即阻断 |
| tag already exists | 比较 SHA；相同则幂等，不同则停止 | 删除/覆盖远端 tag | ARCH + QA 决策 |
| large file rejected | 确认是否误提交生成物；需要时评估 LFS/制品库 | 直接提高限制 | 架构/仓库策略变更 |
| hook/CI rejected | 保留输出，交回 Owner 修复 | `--no-verify` 绕过 | hook 本身错误时由 QA/ARCH 决定 |

## 8. 历史重写政策

默认全部禁止：

```text
git push --force
git reset --hard <shared-branch>
删除受保护远端分支
覆盖已发布 tag
filter-branch/filter-repo 改写共享历史
```

若秘密已进入远端历史，先由 SECURITY 吊销/轮换秘密，再建立独立事故 Task。历史清理不是撤销凭据泄露的替代措施。

例外必须同时具备：

1. 独立 Task 和影响说明；
2. 精确记录 expected remote SHA；
3. ARCH-ORCH 批准；
4. SECURITY 评审；
5. 远端备份或 bundle；
6. 通知所有协作者；
7. 操作后远端核验和恢复说明。

## 9. Secrets 与凭据

不得进入 Git 的内容包括：

- 订阅 URL/token；
- 自建节点密码、UUID、Reality 私钥；
- Salt master/minion 私钥；
- SSH 私钥和 PAT；
- Mihomo API secret；
- `.env` 实例文件、运行时缓存和脱敏前日志。

认证优先级：

```text
1. SSH key + ssh-agent/受控 key file
2. 平台支持的安全 credential helper
3. HTTPS fine-grained token，经安全渠道注入
```

remote URL 必须是无秘密形式，例如：

```text
git@host:owner/repo.git
https://host/owner/repo.git
```

不得使用：

```text
https://user:TOKEN@host/owner/repo.git
```

## 10. GIT-SCM checkpoint

每次写操作或上下文压缩前记录：

```text
repository_path
remote_name
remote_url_redacted
default_branch
current_branch
head_commit
upstream_ref
remote_head_verified
worktree_status
index_status
untracked_summary
active_git_operation
backup_refs
last_push_result
credential_state_without_secret
next_atomic_action
```

## 11. 操作伪代码

```text
git_integrate(task, handoff):
    recover_existing_GIT_SCM_session()
    read_authoritative_files()
    state = read_git_state()
    remote = probe_remote_read_only()

    if unsafe_or_unknown(state, remote):
        set SCM_BLOCKED
        emit Result with exact evidence
        return

    verify_handoff_scope(task, handoff)
    run_tests_and_secret_checks()
    stage_only_approved_files()
    create_atomic_commit()

    if task.push_required:
        fetch_and_recheck_expected_remote_sha()
        push_without_force()
        verify_remote_ref_equals_local_head()

    update_checkpoint_result_and_project_state()
```

## 12. 完成条件

一次 Git 操作只有在以下条件全部满足时才完成：

- Task/Handoff 合法；
- 修改范围清晰；
- 测试和 secret 检查满足要求；
- commit 可定位；
- 需要 push 时远端 SHA 已核验；
- 工作树剩余改动已解释；
- Result、checkpoint 和 PROJECT_STATE 已更新；
- 无被绕过的 QA/SECURITY/branch protection 门禁。
