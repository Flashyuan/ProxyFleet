# Result Packet — RP-0016

- Related task: TP-0016
- Owner role: ARCH-ORCH
- Status: SUCCESS
- Completed at: 2026-06-24
- Contract version: interfaces/CONTRACTS.md 0.2-draft, interfaces/MIHOMO_DRIVER.md 0.1-draft

## Outcome

已在 `PLAN.md` 明确补充“代理节点测速显示”和“最少步骤安装、配置、同步与切换体验”的开发规划。

## Completed

- 新增 `PLAN.md` 9.4，定义代理节点测速显示的用户入口、Mihomo API 方向、字段、错误码和安全边界；
- 更新 `PLAN.md` 15 节状态显示字段，加入测速缓存新鲜度、最近延迟和失败原因；
- 新增 `PLAN.md` 15.1，定义 `master setup`、`minion bootstrap`、`apply`、`select`、`apply --select` 等最少步骤命令语义；
- 更新 `PLAN.md` 16 节测试策略，补充测速与最少步骤体验验收；
- 更新 `PLAN.md` 17 节实施阶段，将 setup/bootstrap/apply、节点健康检查/测速、convergence report 纳入阶段目标；
- 更新 `SOURCES.md`，补充 Mihomo API delay/provider healthcheck 证据用途；
- 复用 DATA-MIHOMO、CONTROL-SALT、QA-RELEASE 既有会话完成只读审计。

## Not completed

- 未实现测速 CLI；
- 未实现 `fleetctl master setup`、`fleetctl minion bootstrap`、`fleetctl apply` 等命令；
- 未修改安装脚本；
- 未更新接口契约文件。

## Facts and confidence

| Claim | Label | Evidence |
|---|---|---|
| PLAN 已明确代理节点测速显示 | VERIFIED-FILE | `PLAN.md` 9.4 |
| PLAN 已明确最少步骤操作体验 | VERIFIED-FILE | `PLAN.md` 15.1 |
| QA 验收要求已进入 PLAN | VERIFIED-FILE | `PLAN.md` 16.3、16.4 |
| DATA-MIHOMO 建议已纳入 | VERIFIED-REVIEW | 复用会话 `019ef31a-05d4-7d20-99d3-d179f86f3b09` |
| CONTROL-SALT 建议已纳入 | VERIFIED-REVIEW | 复用会话 `019ef31a-03f6-7ac1-8aa9-24b0ca956a74` |
| QA-RELEASE 建议已纳入 | VERIFIED-REVIEW | 复用会话 `019ef30f-4327-7192-99a6-b33b997a754c` |

## Files changed

- `PLAN.md`
- `SOURCES.md`
- `tasks/TP-0016-plan-health-and-ux.md`
- `results/RP-0016-plan-health-and-ux.md`

## Tests/evidence

```text
git diff --check
OK

rg -n "代理节点测速显示|最少步骤安装|节点测速显示验收|E_HEALTHCHECK|fleetctl nodes --refresh|master setup|minion bootstrap|apply --select" PLAN.md
matched expected sections
```

## Git evidence（发生 Git 操作时必填）

```text
repository_path: /home/terence/project/ProxyFleet
branch: main
base_commit: 861e5bc7d4ed5c2c9fc9fea8a0aa143ccc433aa0
new_commit: not-created
upstream_ref: origin/main
remote_url_redacted: ssh://git@ssh.github.com:443/Flashyuan/ProxyFleet.git
remote_head_before: not-checked-for-push
remote_head_after: not-applicable
push_status: not-requested
worktree_status: dirty
```

## Risks and regressions

- `PROPOSED`：新增错误码应在后续接口契约中同步；
- `PROPOSED`：后续实现必须验证 Mihomo API delay/healthcheck 在锁定版本中的端点行为；
- `UNKNOWN`：不同 Provider healthcheck 对订阅节点协议和网络环境的实际稳定性。

## Decisions requested

- 是否把 `fleetctl` 作为正式 CLI 名称替换当前 `proxyfleet` 命令；
- 是否将测速 allowlist 默认 URL 固定为 `https://www.gstatic.com/generate_204`、`https://cp.cloudflare.com` 或由配置源声明。

## Handoffs

- DOCS-KNOWLEDGE：后续生成完整 Master + Minion 端到端教程；
- CONTROL-SALT：后续实现 setup/bootstrap/apply 命令编排；
- DATA-MIHOMO：后续实现节点测速和健康检查。

## Next atomic action

若用户要求继续开发，创建 TP-0017，实现最少步骤安装脚本/CLI 或节点测速 CLI。
