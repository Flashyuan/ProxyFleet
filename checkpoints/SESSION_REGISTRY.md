# Subagent 唯一会话注册表

> 更新时间：2026-06-23
> 规则：每个角色最多一个 ACTIVE 会话；实际 session ID 未创建时必须保持 UNASSIGNED。

| Role | Logical key | Actual session ID | Status | Checkpoint | Supersedes | Active task |
|---|---|---|---|---|---|---|
| ARCH-ORCH | agent://ARCH-ORCH | UNASSIGNED | UNASSIGNED | ARCH-ORCH.md | - | TP-0002 coordination |
| PRODUCT-SPEC | agent://PRODUCT-SPEC | UNASSIGNED | UNASSIGNED | PRODUCT-SPEC.md | - | - |
| CONTROL-SALT | agent://CONTROL-SALT | UNASSIGNED | UNASSIGNED | CONTROL-SALT.md | - | - |
| CONFIG-BUILD | agent://CONFIG-BUILD | UNASSIGNED | UNASSIGNED | CONFIG-BUILD.md | - | - |
| DATA-MIHOMO | agent://DATA-MIHOMO | UNASSIGNED | UNASSIGNED | DATA-MIHOMO.md | - | - |
| COMPAT-SHELLCRASH | agent://COMPAT-SHELLCRASH | UNASSIGNED | UNASSIGNED | COMPAT-SHELLCRASH.md | - | - |
| OPS-PLATFORM | agent://OPS-PLATFORM | UNASSIGNED | UNASSIGNED | OPS-PLATFORM.md | - | - |
| SECURITY | agent://SECURITY | UNASSIGNED | UNASSIGNED | SECURITY.md | - | TP-0002 credential review |
| QA-RELEASE | agent://QA-RELEASE | UNASSIGNED | UNASSIGNED | QA-RELEASE.md | - | - |
| GIT-SCM | agent://GIT-SCM | UNASSIGNED | UNASSIGNED | GIT-SCM.md | - | TP-0002 |
| DOCS-KNOWLEDGE | agent://DOCS-KNOWLEDGE | UNASSIGNED | UNASSIGNED | DOCS-KNOWLEDGE.md | - | - |

## 注册变更流程

1. ARCH-ORCH 读取本表；
2. 若角色 UNASSIGNED，创建一次会话并立即写实际 ID；
3. 若 ACTIVE/PAUSED，复用该 ID；
4. 仅 IRRECOVERABLE 可创建替换；
5. 新条目填写 Supersedes，旧会话改 SUPERSEDED；
6. 在 PROJECT_STATE 和 Result 中记录变更原因；
7. GIT-SCM 不得按 commit 次数创建新会话，必须持续复用同一岗位会话。
