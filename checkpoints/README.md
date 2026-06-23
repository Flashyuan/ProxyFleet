# Checkpoint 规范

每个固定角色拥有一个唯一 checkpoint 文件。它是角色恢复入口，不是完整日志。

## 通用必填字段

```text
role
session_key
session_id
status
updated_at
active_task_id
loaded_commit
contract_version
objective
completed
verified_facts
files_changed
commands_and_tests
open_questions
blockers
next_atomic_action
last_result_id
handoffs
```

## GIT-SCM 附加字段

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
```

## 更新时机

- 接受新 Task；
- 完成可交付阶段；
- 任务暂停；
- 上下文压缩前；
- 会话替换前；
- Result/Handoff 写入后；
- 恢复读取完成后；
- 任意 commit、merge、rebase、tag、remote 或 push 操作后。

## 原则

- 不复制整段聊天；
- 只记录能恢复工作所需的事实和证据；
- UNKNOWN 不得用猜测补齐；
- 文件、commit、remote ref 和测试证据优先；
- 下一步必须是单个原子动作；
- 不记录 token、密码、私钥或带凭据 URL。
