# ProxyFleet 当前项目状态

> State 版本：1.1
> 更新时间：2026-06-23
> 当前阶段：Architecture Baseline / Pre-implementation
> 当前 Git commit：83087c0c4e8629e5c70ede6afc47ae03c6ffb0a2（bootstrap commit 已推送并核验远端 SHA）

## 1. 当前结论

- `VERIFIED-DOC`：目标平台为 Ubuntu 22.04/24.04，以 22.04 为主。
- `ACCEPTED`：控制平面使用 Salt 3008 LTS Master/Minion。
- `ACCEPTED`：数据面使用 Mihomo；订阅转换使用主节点本地 subconverter/构建器；配置源使用 Git。
- `ACCEPTED`：采用分布式同步选择，业务流量不经过主节点。
- `ACCEPTED`：所有严格受管节点共用同一不可变 release。
- `ACCEPTED`：节点切换只改变 `FLEET_PROXY` 期望选择。
- `ACCEPTED`：管理端支持 Docker Compose；子节点 V1 原生 systemd。
- `ACCEPTED`：已有 ShellCrash/Mihomo 节点可接管；ShellCrash/sing-box V1 不直接接管。
- `ACCEPTED`：新增唯一固定岗位 `GIT-SCM`，负责 Git 初始化、commit、tag、remote、push、错误处理和远端核验。
- `ACCEPTED`：其他 Subagent 可修改 Task 范围内文件，但不得自行创建/改写 Git 历史或 push。

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
- [ ] 测试环境
- [ ] 可运行 POC

## 3. Workstream 状态

| Workstream | Owner | 状态 | 当前输出 | 阻塞 |
|---|---|---|---|---|
| 产品规格 | PRODUCT-SPEC | BASELINED | PLAN 目标/非目标/验收 | 需真实 CLI 场景评审 |
| Salt 控制平面 | CONTROL-SALT | NOT_STARTED | ADR-0003 | 需 POC |
| 配置构建 | CONFIG-BUILD | NOT_STARTED | CONTRACTS schema 草案 | 需 fixture 订阅 |
| Mihomo 数据面 | DATA-MIHOMO | NOT_STARTED | ADR-0001/2 | 需 Ubuntu 测试机 |
| ShellCrash 兼容 | COMPAT-SHELLCRASH | NOT_STARTED | 接管状态模型 | 需样本版本 |
| Docker/平台 | OPS-PLATFORM | BASELINED | ADR-0004、Docker 文档 | 需 Compose POC |
| 安全 | SECURITY | NOT_STARTED | 基础安全原则 | 需正式威胁模型 |
| QA/发布 | QA-RELEASE | NOT_STARTED | 初步矩阵 | 需测试 harness |
| Git/SCM | GIT-SCM | ACTIVE | bootstrap commit 已推送并完成远端 SHA 核验 | 下一步提交状态同步和版本锁定基线 |
| 知识治理 | DOCS-KNOWLEDGE | BASELINED | v2.2 文档包 | 需首次恢复演练 |

## 4. 已接受决策

见 `DECISIONS.md`。当前有效：ADR-0001 至 ADR-0006。

## 5. 未决问题

1. 原生节点 V1 默认 Profile 是 `proxy-only` 还是 `tun-host`？当前建议默认 `proxy-only`，TUN 显式启用。
2. strict 模式遇到离线节点时，是中止还是把离线节点排除在在线事务外？需要产品决策。
3. 是否在 V1 支持多个订阅，还是数据结构支持但 CLI 先单订阅？
4. Salt Master 的生产默认是否从原生切换为 Docker 控制面？当前 ADR 规定原生为参考、Docker 为支持配置。
5. ShellCrash adopted 模式支持的最低版本和可识别目录矩阵未知。
6. 默认分支保护策略尚未知。
7. 初始远端 `main` 已由 bootstrap push 创建；后续仍需每次 push 前 fetch/compare。

## 6. 风险/阻塞

- `UNKNOWN`：具体 ShellCrash 版本分布和内核配置。
- `UNKNOWN`：现有服务器是否都可从 Master 访问 TCP 4505/4506。
- `UNKNOWN`：订阅提供商是否都返回 `Subscription-Userinfo`。
- `UNKNOWN`：GitHub 默认分支保护策略、SSO 策略和后续 tag 权限。
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

除 TP-0002 外，其余任务尚未创建正式 Task Packet，不得视为已开始。TP-0002 只可在获得完整 Git 输入后进入 ACTIVE。

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
- 当前没有实际代码或自动化测试，因此所有“实现能力”和“已推送”状态仍为 UNKNOWN/未开始。
