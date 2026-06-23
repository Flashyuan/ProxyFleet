# Subagent 唯一会话注册表

> 更新时间：2026-06-23
> 规则：每个角色最多一个 ACTIVE 会话；实际 session ID 未创建时必须保持 UNASSIGNED。

| Role | Logical key | Actual session ID | Status | Checkpoint | Supersedes | Active task |
|---|---|---|---|---|---|---|
| ARCH-ORCH | agent://ARCH-ORCH | UNASSIGNED | UNASSIGNED | ARCH-ORCH.md | - | TP-0002 coordination |
| PRODUCT-SPEC | agent://PRODUCT-SPEC | UNASSIGNED | UNASSIGNED | PRODUCT-SPEC.md | - | - |
| CONTROL-SALT | agent://CONTROL-SALT | 019ef31a-03f6-7ac1-8aa9-24b0ca956a74 | PAUSED | CONTROL-SALT.md | - | TP-0012 completed draft |
| CONFIG-BUILD | agent://CONFIG-BUILD | 019ef30f-4167-7271-b5de-f3ba6bacbda9 | PAUSED | CONFIG-BUILD.md | - | COMPONENT_LOCKS completed |
| DATA-MIHOMO | agent://DATA-MIHOMO | 019ef31a-05d4-7d20-99d3-d179f86f3b09 | PAUSED | DATA-MIHOMO.md | - | MIHOMO_DRIVER completed |
| COMPAT-SHELLCRASH | agent://COMPAT-SHELLCRASH | UNASSIGNED | UNASSIGNED | COMPAT-SHELLCRASH.md | - | - |
| OPS-PLATFORM | agent://OPS-PLATFORM | UNASSIGNED | UNASSIGNED | OPS-PLATFORM.md | - | - |
| SECURITY | agent://SECURITY | 019ef30f-3dd7-7233-adf1-af0474ad2da2 | PAUSED | SECURITY.md | - | SUPPLY_CHAIN_SECURITY completed |
| QA-RELEASE | agent://QA-RELEASE | 019ef30f-4327-7192-99a6-b33b997a754c | PAUSED | QA-RELEASE.md | - | TEST_MATRIX completed; reuse for QA tasks |
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

## Governance drift — 2026-06-23

- `OBSERVED`：本轮错误地创建了第二个 QA-RELEASE subagent `019ef31a-087e-7882-b5ba-399f6631cc1d`（Pascal），任务为 `tests/CONFIG_BUILD_TESTS.md`。
- `VIOLATION`：该行为违反“已有角色会话必须优先复用”和“每个角色同时最多一个 ACTIVE 会话”的精神约束；正确做法应复用 `019ef30f-4327-7192-99a6-b33b997a754c`（Kant）。
- `REMEDIATION`：后续所有 QA-RELEASE 工作必须优先恢复并复用 Kant；Pascal 不再作为固定角色会话使用，其输出已作为一次性错误创建会话的产物纳入主线程审查，不作为新岗位。
