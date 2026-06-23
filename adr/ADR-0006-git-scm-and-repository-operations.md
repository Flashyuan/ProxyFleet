# ADR-0006：固定 GIT-SCM 岗位与 Git 仓库操作权

- Status: Accepted
- Date: 2026-06-23
- Decision owner: ARCH-ORCH
- Reviewers: SECURITY, QA-RELEASE, DOCS-KNOWLEDGE

## Context

项目要求从工程开始即建立 Git 仓库，并由一个稳定岗位负责 `git init`、commit、remote、push、版本标签和所有 Git 错误处理。同时项目采用长期 Subagent 会话复用，不能为每次提交创建新角色或新会话。若各专业角色各自提交和推送，会造成历史混乱、remote 状态竞争、凭据扩散、重复会话和上下文压缩后的状态误报。

用户将提供远程仓库链接、提交用户名和提交邮箱。需要明确：`user.name`/`user.email` 是 commit 元数据，不是远端认证凭据；push 仍需要 SSH key、令牌或凭据助手。

## Decision

1. 新增固定角色 `GIT-SCM`，逻辑会话键为 `agent://GIT-SCM`，遵守唯一 ACTIVE 会话和优先复用制度。
2. 所有角色可在 Task 授权范围内修改文件，但只有 GIT-SCM 可以：
   - 初始化/重初始化仓库；
   - 设置或修改 remote；
   - stage、commit、amend、merge、rebase；
   - 创建/删除分支或 tag；
   - push 或删除远端 ref。
3. 项目启动的第一个实际工程 Task 是 Git 仓库 bootstrap。
4. Git 身份默认使用 repo-local 配置，避免污染主机全局身份：

   ```text
   git config --local user.name  <provided-name>
   git config --local user.email <provided-email>
   ```

5. 认证秘密不得写入 remote URL、Git 配置、仓库文件、Task、Result、日志或 checkpoint。推荐 SSH key 或平台支持的安全凭据助手；HTTPS token 必须经安全渠道注入。
6. 初始远端处理分三类：
   - 空远端：创建 `main` 首个原子提交并设置 upstream；
   - 已有兼容历史：fetch、比较、在备份 ref 后安全集成；
   - unrelated/未知历史：停止写操作，提交证据，由 ARCH-ORCH 决定保留哪条历史。
7. 默认禁止 `git push --force`。任何历史重写必须单独 Task、明确期望远端 SHA、ARCH-ORCH 批准和 SECURITY 评审；即便批准，也优先使用带显式 expect 的 lease，而不是裸 force。
8. 每次 push 后必须重新读取远端 ref，并记录 local HEAD、upstream、remote HEAD 是否一致。命令返回 0 不是唯一成功证据。
9. GIT-SCM 遇到认证缺失、分支保护、远端分叉、secret scan 失败或无法证明无数据丢失时，设置 `SCM_BLOCKED`，不得采用破坏性捷径。
10. release tag 只能在 QA/SECURITY 无阻断且 ARCH-ORCH 接受后由 GIT-SCM 创建和推送。

## Consequences

### Positive

- Git 状态和操作责任唯一，避免并发 push 与重复会话；
- commit、tag、remote 和发布证据可集中审计；
- 专业 Subagent 聚焦本域，不需要各自维护凭据；
- 上下文压缩后可通过 checkpoint、Git refs 和远端 SHA 恢复事实；
- Git 错误处理有明确升级路径，不会因“自动修复”覆盖历史。

### Negative

- 所有变更需要一次 GIT-SCM 集成 Handoff；
- GIT-SCM 会成为版本写入串行点；
- 远端权限、SSO 或 branch protection 仍可能需要用户/仓库管理员操作，GIT-SCM 无法凭空获得权限。

## Operational rules

详细流程、错误矩阵和伪代码见 `docs/GIT_OPERATIONS.md`。接口与结果 envelope 见 `interfaces/CONTRACTS.md`。
