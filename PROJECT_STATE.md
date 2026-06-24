# ProxyFleet 当前项目状态

> State 版本：1.3
> 更新时间：2026-06-24
> 当前阶段：Phase 2 / Proxy Selection Sync POC
> 当前 Git commit：TP-0017 发布前以 GIT-SCM 远端核验结果为准

## 1. 当前结论

- `VERIFIED-DOC`：目标平台为 Ubuntu 22.04/24.04，以 22.04 为主。
- `ACCEPTED`：控制平面使用 Salt 3008 LTS Master/Minion。
- `ACCEPTED`：数据面使用 Mihomo；订阅转换使用主节点本地 subconverter/构建器；配置源使用 Git。
- `ACCEPTED`：采用分布式同步选择，业务流量不经过主节点。
- `ACCEPTED`：所有严格受管节点共用同一不可变 release。
- `ACCEPTED`：节点切换只改变 `FLEET_PROXY` 期望选择。
- `ACCEPTED`：管理端支持 Docker Compose；子节点 V1 原生 systemd。
- `ACCEPTED`：生产子节点统一使用 `native-mihomo`；ShellCrash 仅作为迁移前只读探测、备份和卸载评估工具。
- `ACCEPTED`：新增唯一固定岗位 `GIT-SCM`，负责 Git 初始化、commit、tag、remote、push、错误处理和远端核验。
- `ACCEPTED`：其他 Subagent 可修改 Task 范围内文件，但不得自行创建/改写 Git 历史或 push。
- `ACCEPTED`：安装和发布必须使用固定开源组件版本；禁止 `latest`、浮动 tag 和自动升级关键组件。
- `VERIFIED-TEST`：本地配置源校验与 release compiler POC 可生成 release manifest 并验证文件哈希。
- `VERIFIED-TEST`：订阅状态解析与 Provider 级 Last Known Good 缓存 POC 可阻止空正文/HTML/失败覆盖有效快照。
- `VERIFIED-TEST`：代理节点目录、desired state、Mihomo API PUT 后 GET 验证、Salt publish/sync dry-run 已有本地 POC 和单元测试。
- `VERIFIED-TEST`：订阅 URL 拉取、订阅 Provider 快照转换、订阅+自建节点+自定义 rule 合成 release 已有本地单元测试。
- `VERIFIED-TEST`：节点测速缓存、精确测速 URL allowlist、节点测速失败映射和 `nodes --health-cache` 显示已有本地单元测试。
- `VERIFIED-TEST`：安装脚本不再拉取浮动 Salt `latest` sources，Salt state 重复 ID 已有静态契约测试。
- `VERIFIED-TEST`：Mihomo v1.19.27 已按 `linux-amd64` 和 `linux-arm64` 固定资产 URL、SHA-256 和 gzip 压缩格式；安装模块可校验 gzip 资产、解压、执行版本探测并安装。
- `ACCEPTED`：端口白名单采用 Master managed 层和 Minion local override 层；Master 不覆盖 `/etc/proxyfleet/local`。
- `VERIFIED-TEST`：端口白名单 managed/local/effective 合并、冲突 fail-closed、CLI build 和 Minion local override 保留已有单元测试。

## 2. 当前产物

- [x] PLAN v2.2
- [x] AGENTS v1.1，包含 11 个固定岗位
- [x] PROJECT_STATE v1.1
- [x] DECISIONS 索引
- [x] ADR-0001 至 ADR-0006
- [x] interfaces/CONTRACTS v0.2-draft
- [x] 全部角色 checkpoint 初始文件，包括 GIT-SCM
- [x] Session Registry
- [x] Task/Result/Handoff/RFC 模板
- [x] Git 操作与错误处理手册
- [x] RP-0002 Git 治理文档基线结果
- [x] Docker 部署评估
- [x] 官方证据索引
- [x] 实际 Git 仓库
- [x] 远程仓库接入和首次 push
- [x] 组件版本锁定清单与本地校验工具
- [x] 配置源校验与 release compiler POC
- [x] 订阅状态解析与 Provider 级 Last Known Good 缓存 POC
- [x] 代理配置、节点选择与 Salt 同步 POC
- [x] 订阅 URL 拉取/转换、订阅+自建节点+自定义规则生成 POC
- [x] 节点测速显示和缓存 POC
- [x] Mihomo 安装 fail-closed state POC
- [x] Mihomo 固定资产 URL/SHA-256/gzip 安装
- [x] native-mihomo Minion 本地端到端 harness
- [x] 端口白名单分层配置
- [x] Minion 本地 override 保护机制
- [ ] 测试环境
- [x] 可运行 POC

## 3. Workstream 状态

| Workstream | Owner | 状态 | 当前输出 | 阻塞 |
|---|---|---|---|---|
| 产品规格 | PRODUCT-SPEC | BASELINED | PLAN 目标/非目标/验收 | 需真实 CLI 场景评审 |
| Salt 控制平面 | CONTROL-SALT | ACTIVE | 安装脚本 + publish/sync state POC | 需真实 Minion 验证 |
| 配置构建 | CONFIG-BUILD | ACTIVE | release compiler + subscription URL/cache/provider POC | 需 subconverter 二进制锁定后集成 |
| Mihomo 数据面 | DATA-MIHOMO | ACTIVE | Mihomo API select/health + gzip install + local E2E harness | 需在真实 Ubuntu 测试机端到端验证 |
| 端口策略 | CONTROL-SALT / OPS-PLATFORM | ACTIVE | managed/local/effective 合并器与 Salt local 保护测试 | 需选择 UFW/nftables 落地后端 |
| ShellCrash 迁移 | COMPAT-SHELLCRASH | DEPRIORITIZED | 仅保留只读探测/备份/卸载评估 | 生产主路径改为 native-mihomo |
| Docker/平台 | OPS-PLATFORM | BASELINED | ADR-0004、Docker 文档 | 需 Compose POC |
| 安全 | SECURITY | ACTIVE | 供应链版本锁定基线 | 需正式威胁模型 |
| QA/发布 | QA-RELEASE | ACTIVE | Phase 0/1 最小测试矩阵 | 需测试 harness |
| Git/SCM | GIT-SCM | ACTIVE | bootstrap 和状态同步均已推送并核验 | 后续变更继续原子提交 |
| 知识治理 | DOCS-KNOWLEDGE | BASELINED | v2.2 文档包 | 需首次恢复演练 |

## 4. 已接受决策

见 `DECISIONS.md`。当前有效：ADR-0001 至 ADR-0006。

## 5. 未决问题

1. 原生节点 V1 默认 Profile 是 `proxy-only` 还是 `tun-host`？当前建议默认 `proxy-only`，TUN 显式启用。
2. strict 模式遇到离线节点时，是中止还是把离线节点排除在在线事务外？需要产品决策。
3. 是否在 V1 支持多个订阅，还是数据结构支持但 CLI 先单订阅？
4. Salt Master 的生产默认是否从原生切换为 Docker 控制面？当前 ADR 规定原生为参考、Docker 为支持配置。
5. ShellCrash adopted 不再是生产主路径；是否保留迁移前只读探测样本矩阵待定。
6. 默认分支保护策略尚未知。
7. 初始远端 `main` 已由 bootstrap push 创建；后续仍需每次 push 前 fetch/compare。
8. 组件锁定清单中 subconverter/Docker 镜像仍是 candidate/planned；进入 installable 前必须补齐 SHA-256 或 digest。
9. release compiler POC 已支持 `local_file` 和 `subscription` Provider；subconverter 二进制仍需锁定 SHA 后纳入。
10. Last Known Good 当前覆盖 Provider 快照层，尚未实现 release 指针和节点回滚层。
11. 代理选择、测速和安装 apply 已通过本地端到端 harness，尚未在真实 Mihomo/Salt Minion 上完成端到端验证。
12. `component-locks.json` 中 subconverter SHA 仍为空；subconverter 进入安装发布前必须补齐。
13. 端口白名单 managed/local/effective schema、冲突规则和 local override 保护已实现；UFW/nftables 落地后端尚未实现。

## 6. 风险/阻塞

- `UNKNOWN`：需要迁移的 ShellCrash 节点数量、配置路径和卸载恢复策略。
- `UNKNOWN`：现有服务器是否都可从 Master 访问 TCP 4505/4506。
- `UNKNOWN`：订阅提供商是否都返回 `Subscription-Userinfo`。
- `UNKNOWN`：GitHub 默认分支保护策略、SSO 策略和后续 tag 权限。
- `VERIFIED-DOC`：Mihomo v1.19.27 `linux-amd64` 和 `linux-arm64` 资产 URL 与 SHA-256 已写入组件锁。
- `INFERRED`：Salt Master 容器化可行，但需要自建镜像和灾难恢复验证。
- `INFERRED`：透明代理子节点 Docker 化会显著扩大权限和网络故障面，因此不纳入 V1。

## 7. 下一批 Task Packet

- TP-0002：Git 仓库初始化、首个 commit 和远端 push；Owner GIT-SCM；状态 READY，等待用户输入。
- TP-0003：Salt 3008.1 原生 Master/Minion POC；Owner CONTROL-SALT。
- TP-0004：Docker Salt Master POC 与持久化恢复；Owner OPS-PLATFORM，Reviewer CONTROL-SALT/SECURITY。
- TP-0005：Mihomo Ubuntu 22.04/24.04 基线；Owner DATA-MIHOMO。
- TP-0006：配置 schema 和 release compiler POC；Owner CONFIG-BUILD。
- TP-0007：ShellCrash 只读探测；Owner COMPAT-SHELLCRASH。
- TP-0008：威胁模型；Owner SECURITY。
- TP-0009：测试矩阵与 CI/VM harness；Owner QA-RELEASE。
- TP-0010：组件版本锁定基线和校验工具；Owner SECURITY；状态 ACTIVE。
- TP-0011：配置源校验与 release compiler POC；Owner CONFIG-BUILD；状态 ACTIVE。
- TP-0012：Salt 3008.1 原生 Master/Minion POC；Owner CONTROL-SALT；状态 READY，等待测试机。
- TP-0013：订阅状态解析与 Last Known Good 缓存 POC；Owner CONFIG-BUILD；状态 ACTIVE。
- TP-0015：代理配置、节点选择与 Salt 同步闭环；Owner ARCH-ORCH；状态 ACTIVE。
- TP-0017：订阅拉取转换、Mihomo 安装配置、节点测速和最少步骤 apply；Owner ARCH-ORCH；状态 ACTIVE，等待 SECURITY/QA 最终门禁。
- TP-0018：生产 native-mihomo 与端口白名单分层规划；Owner ARCH-ORCH；状态 ACTIVE，文档更新。
- TP-0019：Mihomo 固定资产、SHA-256 和 gzip 安装；Owner DATA-MIHOMO；状态 IMPLEMENTED，本地测试通过。
- TP-0020：native-mihomo Minion 端到端；Owner CONTROL-SALT/DATA-MIHOMO；状态 PARTIAL，本地 harness 通过，systemd 错误边界和选择失败回滚已有单元测试，等待真实测试机验证。
- TP-0021：端口白名单分层配置与本地 override 保护；Owner OPS-PLATFORM/CONTROL-SALT；状态 IMPLEMENTED，落地后端待决策。

TP-0018 已创建规划 Task/Result；TP-0019/TP-0020/TP-0021 已创建独立 Task Packet，并通过合并 Result Packet 记录实现证据。历史 TP-0003 至 TP-0009 仍为早期路线占位，不得视为已开始。

## 8. Git 启动所需输入

```text
remote_repository_url   已提供；origin 使用 ssh://git@ssh.github.com:443/Flashyuan/ProxyFleet.git
user_name               已提供；repo-local user.name=Flashyuan
user_email              已提供；repo-local user.email=250072920@qq.com
default_branch          main
auth_method             ssh
credential_reference    ssh-agent / 本机 SSH 配置；未写入 Git 文档或日志
remote_expected_state   已观察：main 初始不存在，已由 bootstrap push 创建
```

用户名和邮箱只用于提交元数据。当前已写入 repo-local Git 配置，未修改全局 Git 配置。当前环境的 GitHub SSH 22 端口握手失败，origin 已改为 GitHub SSH-over-443 URL。

## 9. 最近验证记录

- v2.2 文档包所要求的 Git 岗位、ADR、checkpoint、手册、契约和 Task Packet 已创建并通过存在性检查。
- `VERIFIED-TEST`：2026-06-23 已在当前项目目录执行 `git init -b main`，并配置 repo-local `user.name=Flashyuan`、`user.email=250072920@qq.com`。
- `VERIFIED-TEST`：bootstrap commit `83087c0c4e8629e5c70ede6afc47ae03c6ffb0a2` 已推送到 `origin/main`，`git ls-remote --heads origin main` 返回相同 SHA。
- `OBSERVED`：当前环境 GitHub SSH 22 端口连接被关闭，SSH-over-443 可用，origin 已设置为 `ssh://git@ssh.github.com:443/Flashyuan/ProxyFleet.git`。
- `VERIFIED-TEST`：状态同步 commit `a2ee765305205f44aa3a33862188650e199908c6` 已推送到 `origin/main`，远端 SHA 与本地 HEAD 一致。
- `VERIFIED-TEST`：组件锁校验工具通过 `component-locks.json`，单元测试 6 项通过。
- `VERIFIED-TEST`：release compiler POC 单元测试 14 项通过，可构建并校验 `manifest.json`、`manifest.sha256` 和 release 文件哈希。
- `VERIFIED-TEST`：订阅状态/LKG POC 单元测试纳入总计 24 项；CLI 可输出脱敏 subscription status JSON。
- `VERIFIED-TEST`：代理配置/节点选择/同步 POC 单元测试纳入总计 32 项；CLI fixture 可完成 build-release、nodes、select-node、publish-salt、sync --dry-run，并对未知 node_id 返回 `E_NODE_NOT_FOUND`。
- `VERIFIED-TEST`：TP-0017 本地单元测试总计 52 项通过；覆盖订阅 URL 拉取/LKG、订阅+自建节点+自定义 rule release、节点测速缓存、精确测速 URL allowlist、安装脚本不拉 `latest`、Salt state 唯一 ID 和 Mihomo 缺失 SHA fail-closed。
- `VERIFIED-TEST`：TP-0019/TP-0020/TP-0021 快速回归 `PYTHONPATH=src python3 -m unittest tests.test_component_locks tests.test_port_policy tests.test_fleet` 通过 43 项；覆盖锁文件 schema major/RFC3339/artifact 覆盖、gzip 安装、版本探测 fail-closed、systemd 错误码、选择验证失败回滚、端口策略 override。
- `VERIFIED-TEST`：`PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json` 通过，当前 Mihomo installable artifacts 满足 URL/SHA-256/gzip 契约。
- `VERIFIED-TEST`：TP-0019/TP-0020/TP-0021 全量回归 `PYTHONPATH=src python3 -m unittest discover -s tests` 通过 77 项；`py_compile`、安装脚本 `bash -n` 和 `git diff --check` 均通过。仍观察到既有 `ResourceWarning`，未影响断言。
