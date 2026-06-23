# Task Packet — TP-0002

- Title: 初始化 ProxyFleet Git 仓库并完成首个可验证远端推送
- Status: READY
- Owner role: GIT-SCM
- Reviewer roles: ARCH-ORCH, SECURITY, QA-RELEASE
- Created by: ARCH-ORCH
- Created at: 2026-06-23
- Related ADR: ADR-0006
- Contract version: 0.2-draft

## Objective

接收用户提供的远程仓库 URL、提交用户名、提交邮箱和认证方式，安全建立或接入 ProxyFleet Git 仓库，生成首个原子 commit，推送到正确远端并验证远端 SHA。

## Non-goals

- 不实现 ProxyFleet 业务代码；
- 不绕过远端权限或 branch protection；
- 不擅自覆盖非空远端历史；
- 不把认证秘密写入仓库或文档；
- 不创建第二个 GIT-SCM 会话。

## Required inputs

```text
remote_repository_url
user_name
user_email
default_branch（缺省 main）
auth_method（ssh | https-token | credential-helper）
credential_reference（安全通道）
remote_expected_state（empty | existing | unknown，可省略）
```

## Verified context

- `ACCEPTED`：GIT-SCM 是唯一 Git 写操作岗位；证据 ADR-0006。
- `VERIFIED-DOC`：v2.2 工程文档包已生成。
- `UNKNOWN`：实际远端状态、权限、分支保护和认证可用性。
- `UNKNOWN`：实际 project worktree 路径。

## Constraints and forbidden actions

- 必须先读取 SESSION_REGISTRY 并复用/创建唯一 GIT-SCM 会话；
- 所有 Git identity 使用 repo-local 配置；
- 不使用带 token 的 remote URL；
- 不执行裸 `push --force`；
- 不执行 `reset --hard` 或 `clean -fd` 处理未知文件；
- 不自动合并 unrelated histories；
- 不声称 push 成功，除非远端 ref 与本地 HEAD 一致。

## Deliverables

- 初始化或正确接入的 Git 仓库；
- repo-local user.name/user.email；
- 正确的 `origin` 和 upstream；
- 首个原子 commit；
- 远端 push 和 SHA 核验，或明确 `SCM_BLOCKED` 证据；
- 更新的 PROJECT_STATE、GIT-SCM checkpoint 和 Result Packet。

## Required evidence/tests

```text
git status --porcelain=v2 --branch
git config --local --get user.name
git config --local --get user.email
git remote -v（凭据脱敏）
git rev-parse HEAD
git rev-parse @{upstream}（推送后）
git ls-remote --heads origin <default_branch>
secret/generation preflight
git diff --cached --check（提交前）
```

## Dependencies

- 用户提供完整 Required inputs；
- SECURITY 确认认证秘密注入方式；
- 文档包作为首个提交输入。

## Failure/rollback expectations

- 远端不可达/无权限：保留本地 commit，标记 `SCM_BLOCKED`；
- 远端非空：fetch、备份、比较；未获决策前不写远端；
- 本地已有工作：先保留和归属，禁止丢弃；
- push 后核验不一致：立即停止后续操作，记录 local/remote SHA。

## Definition of Done

- 本地仓库状态可解释；
- commit 内容仅包含批准项目文件；
- 没有 secrets/运行时生成物；
- 远端 SHA 验证成功，或阻塞原因和用户所需动作精确可执行；
- Result、checkpoint、PROJECT_STATE 完整；
- GIT-SCM 会话已登记且可复用。

## Communication/Handoff targets

- 成功：Handoff 给 ARCH-ORCH 和所有后续 Task Owner，提供 base commit；
- 认证/权限：Handoff 给 SECURITY/用户；
- 历史分歧：RFC/证据提交 ARCH-ORCH；
- 测试/内容问题：退回对应 Owner。
