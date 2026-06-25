# ProxyFleet 工程化实施计划

> 文档状态：Accepted Baseline v2.3
> 更新日期：2026-06-24
> 目标平台：Ubuntu Server 22.04 LTS（主基线）/ 24.04 LTS（兼容基线）
> 核心选型：Salt 3008 LTS + Mihomo + subconverter + Git
> 管理方式：纯命令行；不开发 Web UI；不以 SSH 作为日常控制平面
> 数据路径：分布式同步选择，子节点直接连接统一选中的代理节点

---

## 0. 文档目的

本文定义 ProxyFleet 的产品边界、系统架构、配置构建、子节点接入、统一节点切换、ShellCrash 迁移边界、端口白名单分层配置、容器化边界、发布与回滚、测试验收，以及多 Subagent 协作和上下文恢复制度。

以下文件与本计划共同组成规范，缺一不可：

- `AGENTS.md`
- `PROJECT_STATE.md`
- `DECISIONS.md` 和 `adr/`
- `interfaces/CONTRACTS.md`
- `checkpoints/`
- `tasks/`、`results/`、`handoffs/`
- `SOURCES.md`
- `docs/USER_MANUAL.md`

---

## 1. 已冻结的产品与架构决策

修改下列任一项必须新增或修订 ADR：

1. 服务器平台限定为 Ubuntu 22.04/24.04，以 22.04 为主验证环境。
2. 使用分布式同步选择：主节点同步配置和选择状态，子节点直接连接真实代理节点；主节点不承载业务代理流量。
3. 主节点只维护一套配置源；最终 `config.yaml`、providers、rules 由构建流程自动生成。
4. 所有严格受管子节点使用同一 release revision、同一文件 SHA-256 和同一 Mihomo 版本。
5. 节点切换不重新生成 `config.yaml`，只改变 `FLEET_PROXY` 的期望选择。
6. 日常控制使用 Salt Master/Minion，不使用 SSH 批量执行。
7. 生产子节点统一使用 `native-mihomo`：生产机器应卸载 ShellCrash 后由 ProxyFleet Minion 安装并拥有 Mihomo；ShellCrash 仅作为迁移前只读探测和应急兼容工具。
8. 订阅 URL 只保存在主节点；子节点只收到构建后的 Provider 快照。
9. 每次执行操作类 `fleetctl` 命令时刷新订阅用量；失败时显示缓存和 stale 状态，不伪造剩余量。
10. 不开发公开管理 API 和 Web UI；管理员在主节点使用 CLI。
11. 管理端支持 Docker 化部署；子节点 V1 默认原生 systemd 部署，不要求 Docker。
12. Git、ADR、契约、状态文件和测试证据是事实来源；聊天记忆不是事实来源。
13. 固定 `GIT-SCM` 岗位负责仓库初始化、commit、tag、remote、push、错误处理和远端核验；其他 Subagent 不自行改写 Git 历史。
14. 端口白名单采用分层所有权：Master 管理公共规则，Minion 保留本机 override，Master 不覆盖 `/etc/proxyfleet/local`。
15. Minion 脚本默认只控制 `salt-minion` 生命周期；Mihomo 启停和卸载必须通过显式 `--with-mihomo` 参数或 `mihomo-*` 专用子命令触发，避免误停代理数据面。
16. `select-sync` 默认进入实时 TUI；`--live-health` 保留为兼容别名，`--refresh-health` 和 `--no-health-cache` 进入废弃路径，不作为推荐用户入口。
17. Master/Minion 脚本无参数运行时默认进入 TUI 主控台；底层子命令保留给自动化、文档可复现步骤和故障恢复，不再作为普通用户主入口。

对应 ADR 见 `DECISIONS.md`。

---

## 2. 目标、非目标和成功条件

### 2.1 目标

- 统一维护订阅节点、自建节点、策略组和规则；
- 自动生成 Mihomo 可加载的不可变发布包；
- 将相同发布包同步给所有目标子节点；
- 一条命令让某个分组所有在线子节点切换到同一稳定节点 ID；
- 收集逐节点 READY/APPLIED/FAILED/OFFLINE 状态；
- 离线节点恢复后自动追平最新 release 和 desired state；
- 支持生产原生 Mihomo 节点；ShellCrash 仅作为迁移前探测、卸载评估和应急兼容路径；
- 支持 Master 统一端口白名单和 Minion 本地端口白名单分层合并；
- 配置失败、订阅异常和节点切换失败均可回滚；
- 只通过 CLI 管理；
- 管理主节点可以选择原生或 Docker Compose 部署；
- 项目启动即建立 Git 仓库，并由唯一 GIT-SCM 会话维护正确远端版本。

### 2.2 非目标

V1 不实现：

- 业务流量经过中央网关；
- 自研代理核心、TUN 栈或代理协议；
- Web 面板；
- ShellCrash/sing-box 的生产接管；
- 每台服务器单独的订阅账单；
- Kubernetes；
- 子节点全容器化透明代理；
- 跨公网的严格分布式原子事务；
- 在分布式直连模式下隐藏真实节点凭据。

### 2.3 V1 成功条件

1. 20 台测试节点可接收同一 release，文件校验一致率 100%。
2. 一条切换命令可统一选择目标节点，并输出逐节点结果。
3. Salt Master 停机时，子节点继续使用最后有效配置和当前选择。
4. 订阅服务返回空内容、HTML、5xx 或超时时不会覆盖有效 Provider。
5. Ubuntu 22.04/24.04 原生节点均通过安装、重启、升级和回滚测试。
6. 至少一台真实 `native-mihomo` Minion 完成锁定 Mihomo 安装、release 应用、节点测速、节点选择和回滚验证。
7. Docker 管理端通过备份恢复、镜像升级和 Salt 密钥持久化测试。
8. 高风险网络配置必须先 canary，再批量发布。
9. 首个工程提交可被远端 SHA 验证，后续每个发布可追溯到唯一 Git commit。
10. 端口白名单 `merge/master-only/local-only/disabled` 四种模式均有 dry-run、应用和回滚证据；Minion 本地 override 不被 Master 覆盖。

---

## 3. 总体架构

```text
                         管理主节点
┌─────────────────────────────────────────────────────────┐
│ Git：配置源、Salt States、ADR、任务、测试证据            │
│                                                         │
│ fleetctl                                                │
│  ├─ 刷新订阅及 Subscription-Userinfo                    │
│  ├─ 调用构建器/subconverter                             │
│  ├─ 生成 release + manifest + hashes                    │
│  ├─ 更新 desired state                                  │
│  └─ 调用 Salt CLI / Orchestrate                          │
│                                                         │
│ salt-master                                             │
│  ├─ file roots / pillar roots                           │
│  ├─ Minion 认证与目标分组                               │
│  └─ 发布、远程执行、结果与事件                          │
└─────────────────────────┬───────────────────────────────┘
                          │ Salt 4505/4506
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
     原生节点 A       原生节点 B       原生节点 C
     salt-minion      salt-minion      salt-minion
     mihomo.service   mihomo.service   mihomo.service
     localhost API    localhost API    localhost API
     local override   local override   local override
            └─────────────┬─────────────┘
                          ▼
                 统一选中的真实代理节点
```

业务路径：

```text
命中受管规则 → FLEET_PROXY → 子节点直接连接统一选中节点
未命中规则   → DIRECT      → 子节点自身公网出口
```

控制平面和业务平面完全分离。

---

## 4. 组件职责

### 4.1 `fleetctl`

管理员唯一入口，非守护进程。职责：初始化、订阅刷新、配置构建、发布、切换、回滚、状态和审计。它不得成为唯一状态存储，也不承载业务流量。

脚本入口必须 ShellCrash 化：普通用户执行 `scripts/proxyfleet-master.sh` 或
`scripts/proxyfleet-minion.sh` 时默认进入 TUI 主控台；需要自动化、CI、排障或
文档复现时才使用 `install/select-sync/mihomo-start` 等显式子命令。

### 4.2 Salt Master

负责 Minion 身份、目标匹配、文件分发、State、Orchestrate 和结果收集。生产环境锁定 Salt 3008 LTS 的明确 point release，升级只能经过 canary。

### 4.3 Salt Minion

每个子节点唯一新增的控制服务。它主动连接 Master，在宿主机执行受控 State 和本地 Mihomo API 操作。

Minion 安装脚本的基础 `start/stop/restart/uninstall` 语义默认只管理
`salt-minion`。如需让脚本联动 Mihomo，必须使用显式参数或专用子命令，
并在执行前完成所有权校验、路径校验和回滚边界检查。

### 4.4 Mihomo

统一数据面，负责 TUN/代理入口、DNS、规则、Proxy Provider、Rule Provider 和 `FLEET_PROXY` 选择。API 只监听 loopback 或 Unix socket。

### 4.5 subconverter/配置构建器

只在主节点构建阶段运行。输入是主节点已下载的订阅快照和自建节点，输出规范 Provider 或配置片段。不得对公网开放。

### 4.6 Git 与 `GIT-SCM`

Git 保存配置源、Salt States、接口、ADR、状态和测试证据。生产 secrets 和明文节点凭据不得进入普通 Git 历史。

固定岗位 `GIT-SCM` 是唯一 Git 写操作执行者，负责：

- 项目开始时 `git init` 或安全接入已有仓库；
- repo-local `user.name`/`user.email`、remote、branch 和 upstream；
- 原子 commit、受控 merge/rebase、release tag 和 push；
- non-fast-forward、认证、detached HEAD、冲突和 branch protection 等错误处理；
- push 后远端 SHA 核验；
- Git 状态写入 checkpoint、Result 和 PROJECT_STATE。

专业角色仍可修改 Task 范围内文件，但必须通过 Handoff 交给 GIT-SCM 集成。用户名和邮箱是提交身份，不是认证凭据；push 认证必须使用 SSH key、token 或凭据助手，秘密不得进入仓库。详细规则见 `docs/GIT_OPERATIONS.md` 和 ADR-0006。

---

## 5. 仓库布局

```text
proxyfleet/
├── .gitignore
├── .gitattributes
├── PLAN.md
├── AGENTS.md
├── PROJECT_STATE.md
├── DECISIONS.md
├── SOURCES.md
├── adr/
├── interfaces/
├── checkpoints/
├── tasks/
├── results/
├── handoffs/
├── rfcs/
├── docs/
│   ├── GIT_OPERATIONS.md
│   └── DEPLOYMENT_DOCKER.md
├── config-src/
│   ├── base.yaml
│   ├── providers.yaml
│   ├── groups.yaml
│   └── rules.yaml
├── nodes/
│   └── self-hosted.yaml
├── rule-sets/
├── salt/
│   ├── states/
│   ├── pillar/
│   ├── orchestrate/
│   └── modules/
├── releases/
├── runtime/
│   ├── desired.yaml
│   └── subscription-status.json
├── src/
└── tests/
```

生成物和密钥必须与源文件分开。

### 5.1 Git 仓库启动顺序

实际项目开始时，第一项工程 Task 必须是 `TP-0002`，由已登记且可复用的 `GIT-SCM` 会话执行：

```text
接收 remote URL、user.name、user.email、默认分支和认证方式
→ 只读探测本地与远端状态
→ 空仓库时 git init -b main
→ repo-local 设置提交身份
→ 生成 .gitignore/.gitattributes
→ secret/生成物预检
→ 创建首个原子 commit
→ push 并设置 upstream
→ git ls-remote 再次读取远端 SHA
→ 更新 PROJECT_STATE/checkpoint/Result
```

若远端已有历史，必须先 fetch 和比较。无共同祖先、远端未知提交或 branch protection 冲突时，GIT-SCM 设置 `SCM_BLOCKED` 并提交证据，不得用 force push 覆盖。

### 5.2 日常 Git 集成

- 每个专业 Task 完成后向同一个 GIT-SCM 会话发送 Handoff；
- GIT-SCM 只 stage 当前 Task 批准的文件；
- 默认使用短生命周期 `work/TP-XXXX-*` 分支；
- 已 push 的共享 commit 默认用新 commit 修复，不 amend/rewrite；
- release tag 需要 QA、SECURITY 无阻断且 ARCH-ORCH 接受；
- 所有 push 必须记录 local HEAD、remote before/after 和最终 worktree 状态。

完整流程和错误矩阵见 `docs/GIT_OPERATIONS.md`。

---

## 6. 配置源与自动生成

### 6.1 唯一配置所有者

主节点配置源是唯一人工维护入口；`config.yaml` 永远是构建产物，不允许手改。

人工维护：

- `base.yaml`：DNS、TUN、API、日志等共同基础；
- `providers.yaml`：订阅和本地节点来源声明；
- `groups.yaml`：`FLEET_PROXY`、自动选择和故障转移；
- `rules.yaml`：规则顺序与目标组；
- `nodes/self-hosted.yaml`：自建节点；
- `rule-sets/`：规则正文。

### 6.2 多 Provider 逻辑融合

订阅 A、订阅 B、自建节点分别生成 file Provider，由 `FLEET_PROXY` 的 `use` 同时引用。V1 不物理合并所有协议，避免自研完整协议解析器。

### 6.3 构建流程

```text
读取配置源
→ 获取订阅正文和用量头
→ 验证正文
→ 转换/归一 Provider
→ 复制自建节点和规则
→ 生成 config.yaml
→ 引用完整性检查
→ 使用锁定版本 Mihomo 做配置校验
→ 生成 manifest 和 SHA-256
→ 原子发布 release
```

伪代码：

```text
build_release():
    source = load_sources()
    snapshots = refresh_subscriptions_without_overwriting_last_good()
    providers = compile_provider_files(source, snapshots)
    config = compile_mihomo_config(source, providers)
    validate_references(config)
    validate_with_pinned_mihomo(config)
    manifest = hash_all_files(config, providers, rules)
    publish_atomically(manifest)
```

---

## 7. 发布包契约

每次配置变化产生不可变目录：

```text
releases/000042/
├── config.yaml
├── providers/
├── rules/
├── manifest.json
└── manifest.sha256
```

发布包必须包含：revision、构建时间、Mihomo 版本、源 Git commit、每个文件哈希、兼容 schema 版本。详细字段见 `interfaces/CONTRACTS.md`。

---

## 8. 新服务器接入

### 8.1 原生节点

新服务器只需首次执行一次可信 bootstrap：

1. 验证 Ubuntu 版本和架构；
2. 安装锁定版本 Salt Minion；
3. 写入明确的 Minion ID、Master 地址和 Master 指纹；
4. 启动 `salt-minion.service`；
5. 管理员在主节点核验并接受 key；
6. Salt State 安装锁定版本 Mihomo；
7. 部署当前 release；
8. 启动并验证 `mihomo.service`；
9. 应用当前 desired node；
10. 回报状态。

不得自动接受未知 Minion key。

### 8.2 节点身份与分组

使用 Salt Minion ID 作为主身份，Grains/Pillar 表示环境、角色、驱动和发布组，例如：

```text
environment=production
driver=native-mihomo
os_baseline=ubuntu-22.04
release_channel=stable
```

### 8.3 离线追平

Minion 恢复连接后执行 reconcile：对比期望 release、实际哈希和期望节点；只应用最新状态，不重放所有历史操作。

### 8.4 Minion 本机 Mihomo 生命周期控制

目标：让 `proxyfleet-minion.sh` 能安全控制本机 Mihomo，但不让普通
Salt Minion 操作误伤代理数据面。

命令语义：

- `start/stop/restart/status/uninstall`：默认只控制 `salt-minion`；
- `start --with-mihomo`：先启动 `salt-minion`，再执行 Mihomo 安全启动；
- `stop --with-mihomo`：先停止 Mihomo，再停止 `salt-minion`；
- `restart --with-mihomo`：按 `salt-minion` 和 Mihomo 各自安全流程重启；
- `uninstall --with-mihomo`：卸载 Salt Minion，同时执行 Mihomo 安全卸载；
- `mihomo-start/mihomo-stop/mihomo-restart/mihomo-status/mihomo-uninstall`：
  只控制本机 Mihomo。

安全启动必须满足：

- `/usr/local/bin/mihomo` 存在且版本匹配组件锁或当前 release manifest；
- `mihomo.service` 由 ProxyFleet 管理，`ExecStart` 指向受管 `config.yaml`；
- `/etc/proxyfleet/current/config.yaml` 可读且校验通过；
- API secret、runtime 目录和日志目录权限符合契约；
- `systemctl start mihomo` 后必须验证 systemd active，必要时验证 loopback API；
- 失败时返回明确错误，不覆盖 Last Known Good。

安全停止必须满足：

- 只停止 `mihomo.service`，不删除二进制、配置、release、override 或日志；
- systemd stop 失败必须返回 `E_SERVICE_SYSTEMD`，保留错误摘要。

安全卸载分级：

- 默认 `mihomo-uninstall`：停止并禁用服务，删除 ProxyFleet 拥有的 unit；
  保留 `/etc/proxyfleet`、release、local override 和日志；
- `--purge-managed`：额外删除 `/etc/proxyfleet/managed` 和
  `/etc/proxyfleet/effective`，仍保留 local override；
- `--purge-all --yes`：删除 ProxyFleet 受管 release、current/previous 链接、
  managed/effective、受管 systemd unit 和受管二进制；
- `--purge-local-override`：必须与 `--purge-all --yes` 同时使用，才允许删除
  `/etc/proxyfleet/local`。

任何路径不匹配、unit 非 ProxyFleet 拥有、二进制非组件锁来源、配置校验失败、
local override 存在但未显式允许删除时，卸载必须 fail-closed。

---

## 9. 统一节点切换

### 9.1 关键语义

切换只修改 `FLEET_PROXY` 的选择，不重建 `config.yaml`。

### 9.2 两阶段流程

```text
PREPARE
  - 刷新订阅用量
  - 确认稳定 node_id 存在
  - 确认所有目标节点使用要求的 provider revision
  - 本地 API 可用
  - 目标节点存在并可选

COMMIT
  - Salt 并行调用本地 Mihomo API
  - PUT FLEET_PROXY → 目标 Mihomo 名称
  - GET 再验证
  - 汇总结果
  - 更新 desired state
```

默认保留已有连接；只有显式策略允许时才关闭受管代理连接。

### 9.3 一致性

V1 提供：

- `strict`：任一在线目标 PREPARE 失败则不提交；COMMIT 部分失败则补偿回滚；
- `best-effort`：成功节点提交，失败和离线节点记录漂移；
- `scheduled`：预发布并在 `activate_at` 本地切换，用于近同时切换。

严格模式不能承诺网络意义上的真正原子事务，只能做到预检、分阶段提交和补偿回滚。

### 9.4 代理节点测速显示

管理员必须能在 Master 上用 CLI 查看当前 release 中所有可选择代理节点的健康状态
和最近延迟，用于切换前判断节点质量。测速显示是观测能力，不得隐式改变
`config.yaml`、desired state 或 `FLEET_PROXY` 当前选择。

推荐用户入口：

```text
fleetctl nodes
fleetctl nodes --refresh
fleetctl health-check --node-id <node-id>
fleetctl health-check --all --target-group production
scripts/proxyfleet-master.sh select-sync
```

`nodes` 默认读取最近缓存；只有显式 `--refresh` 或 `health-check` 才主动触发
探测。测速结果必须标注 `fresh|stale|unknown`，不能把未知或超时写成成功。

`select-sync` 默认使用 Python 标准库 `curses` TUI。`--live-health` 仅作为兼容别名
保留；`--refresh-health` 和 `--no-health-cache` 不再作为推荐入口，后续应移出帮助
或标记为 deprecated。历史 Bash/ANSI 版本只作为过渡实现，不得作为默认体验。

TUI 目标体验：

- 进入 alternate screen，不污染原终端历史；
- 只渲染当前 viewport，节点数量超过屏幕高度时支持上下滚动；
- 顶部固定显示产品标题、当前 release、当前 `FLEET_PROXY` 选择、总进度、
  `ok/timeout/failed`、并发、耗时和数据来源；
- 当前选择必须清晰显示：若 desired 或 Mihomo API 无当前选择，显示
  `当前选择：无`；若 desired 与实际 Mihomo API 不一致，显示 drift 提示；
- 列表内实时刷新每个可见节点的 `pending/ok/timeout/failed` 与延迟；
- 支持 `↑/↓` 或 `j/k` 移动、`Enter` 选择、`/` 搜索、`r` 重新测速、`q` 退出；
- 一次会话内默认序号稳定，不因测速结果到达而自动重排；
- 如加入延迟排序，必须由显式按键触发，且排序后仍显示原始序号和当前高亮项；
- 用户不需要等待全量测速完成，可随时选择当前高亮或输入稳定序号；
- 视觉上使用固定区域：标题栏、状态栏、过滤/搜索栏、节点表格、帮助栏；
  长文本必须截断并保留节点序号、`mihomo_name` 和延迟状态；
- 状态呈现至少区分：当前选中、当前高亮、pending、ok、timeout、failed、
  stale、unknown，不得只显示一组裸文本；
- 退出后恢复原终端状态，不留下错位光标、残留 raw mode 或半屏内容。

实时刷新不得改变 desired state，只有用户确认序号或高亮项后才写入 desired 并同步
Minion。TUI 不得引入新第三方依赖，除非先完成依赖锁定、安全审计和用户确认。

节点测速使用每个 Minion 本机 Mihomo API 的单节点延迟或 Provider 健康检查能力：

- 优先使用单节点延迟探测，例如 `GET /proxies/{proxy_name}/delay`；
- 实时菜单的本机模式只代表 Master 本机 Mihomo 到节点的延迟；fleet-wide 模式
  必须让每台 Minion 调用自己的 `127.0.0.1:9090` 后由 Master 汇总；
- Provider 级刷新可使用 Provider healthcheck；
- 不默认使用策略组级 delay 作为 `FLEET_PROXY` 的常规测速入口，因为组级测速
  可能批量触发探测，并对自动策略组的固定选择产生副作用；
- 探测 URL 必须来自受控 allowlist，低成本、无身份信息，预期返回 200/204；
- 禁止使用订阅 URL、业务站点、metadata 地址或携带 token 的 URL 作为测速目标。

`fleetctl nodes` 至少显示或可 JSON 输出：

- `node_id`、`provider_id`、`mihomo_name`、`protocol`；
- `availability`：`available|hidden|disabled|unknown`；
- `selectable`：当前 `FLEET_PROXY` 是否可选；
- `selected`：是否为当前 `FLEET_PROXY` 选择；
- `last_delay_ms`：最近一次探测延迟，未知为 `null`；
- `health_status`：`ok|timeout|failed|unknown|stale`；
- `measured_at`：RFC 3339 UTC；
- `freshness`：`fresh|stale|unknown`；
- `release_revision`、`provider_revision`；
- `last_error_code`。

输出不得包含订阅 URL、节点密码、UUID 私密字段、Reality 私钥、API secret 或
完整代理 URI。必要时只显示协议类型、脱敏指纹和稳定 `node_id`。

新增或复用以下错误码：

- `E_HEALTHCHECK_UNSUPPORTED`：当前 Mihomo/API 不支持所需测速能力；
- `E_HEALTHCHECK_TIMEOUT`：测速超时；
- `E_HEALTHCHECK_FAILED`：测速失败或响应不可解析；
- `E_HEALTHCHECK_TARGET_BLOCKED`：测速 URL 不在 allowlist；
- `E_HEALTHCHECK_RATE_LIMITED`：触发本地限频；
- `E_LOCAL_API`：Mihomo API 不可用；
- `E_NODE_NOT_FOUND`：目标节点不存在；
- `E_PROVIDER_MISMATCH`：provider revision 不一致。

测速失败不等同于节点切换失败，除非处于明确的 PREPARE 验证流程。

---

## 10. 订阅使用量与节点快照

每次操作类命令优先刷新订阅：

```text
HTTP response headers → Subscription-Userinfo
HTTP response body    → 节点快照
```

解析 upload、download、total、expire；缺失时显示 unknown。请求失败时保留最后有效快照并标记 stale，禁止错误正文覆盖 Provider。

节点使用量是共享订阅账户总量，不代表每台服务器的独立消耗。

---

## 11. 端口白名单分层配置

生产节点的端口白名单由 Master 管理层和 Minion 本地层共同组成。该能力用于
控制子节点本机入站端口策略，不用于管理订阅节点、代理协议或云厂商安全组。

### 11.1 文件所有权

```text
config-src/
└── port-policy.yaml           # Master 本机配置源，默认读取，Git 忽略

/etc/proxyfleet/
├── managed/
│   └── port-policy.yaml       # Master 同步，可覆盖
├── local/
│   └── port-policy.yaml       # Minion 本机维护，Master 禁止覆盖
└── effective/
    └── port-policy.yaml       # Minion 合并生成，可覆盖
```

Master 公共规则默认从 `config-src/port-policy.yaml` 读取。该文件属于生产本机
配置源，默认被 `.gitignore` 排除；如果需要提交示例，只能使用
`config-src/port-policy.example.yaml`。

Master 只能写 `managed/`。Salt state 不得对 `/etc/proxyfleet/local` 使用
`file.managed`、`file.recurse clean=True`、`file.absent` 或其它会覆盖/删除本机
配置的操作。若需要创建目录，只能确保目录存在和权限正确。

### 11.2 策略模式

每台 Minion 必须显式或默认选择一个模式：

- `merge`：默认，公共规则和本机规则合并；
- `master-only`：只使用 Master 公共规则，忽略本机规则但不删除本机文件；
- `local-only`：只使用本机规则，必须在状态报告中标记为策略例外；
- `disabled`：ProxyFleet 不管理端口白名单，必须记录审计原因。

`merge` 模式下，Master 规则和 local 规则都保留来源字段。若出现同一端口/协议
的冲突，默认 fail-closed 并要求用户修正，不静默选择任一侧。

### 11.3 建议 schema

```yaml
schema_version: "1.0"
owner: master | local
mode: merge
allow:
  - protocol: tcp
    port: 22
    source: 192.168.1.0/24
    comment: ssh management
deny: []
```

约束：

- 端口必须是 `1..65535`，协议只能是 `tcp|udp`；
- `source` 必须是 CIDR、明确 IP 或 `any`；
- `local` 文件不得包含订阅 URL、节点凭据或 API secret；
- Master 发布不得因为 local 文件不存在而失败；
- local 文件语法错误时，不应用新的 effective 规则，保留 Last Known Good。

### 11.4 CLI 与状态

推荐入口：

```text
fleetctl port-policy build --target-group production --dry-run
fleetctl port-policy apply --target-group production
fleetctl port-policy status --target-group production
```

脚本入口规划：

- `scripts/proxyfleet-master.sh select-sync` 默认检查 `config-src/port-policy.yaml`；
- 文件存在时，默认以 `merge` 模式随 release/desired 一起发布到 managed 层；
- 文件不存在时，TUI 状态栏显示 `端口白名单：未配置`，不隐式创建规则；
- 用户仍可用 `--port-policy PATH` 指定其它 managed 规则文件；
- Minion 本机规则只写 `/etc/proxyfleet/local/port-policy.yaml`，Master 不覆盖。

状态报告至少包含：

- 当前模式；
- managed/local/effective 三层文件 SHA-256；
- 本地 override 是否存在；
- 冲突列表；
- Last Known Good effective 文件；
- 最近一次应用结果和错误码。

---

## 11A. ShellCrash 迁移边界

### 11A.1 驱动状态

- `NATIVE_MIHOMO`：ProxyFleet 安装并拥有 Mihomo；
- `SHELLCRASH_DISCOVERY`：只读探测 ShellCrash、Mihomo 版本、路径和 API 能力；
- `SHELLCRASH_COMPAT`：仅用于迁移窗口内的有限应急操作；
- `UNSUPPORTED`：ShellCrash 使用 sing-box、API 不可持久化或环境未知。

### 11A.2 迁移原则

1. 生产目标是卸载 ShellCrash 后进入 `native-mihomo`；
2. 迁移前只读探测版本、目录、内核类型、API 和现有代理能力；
3. 不猜测 ShellCrash 私有路径；
4. 不启动第二个 Mihomo；
5. 不让 ShellCrash 与 ProxyFleet 同时拥有同一 `config.yaml`；
6. 迁移窗口必须保留回滚说明和原始配置备份；
7. 不满足条件时 fail-closed，不进入生产发布。

### 11A.3 推荐迁移路径

```text
只读探测 ShellCrash
→ 导出现有订阅/自建节点信息
→ 备份 ShellCrash 配置
→ 停止并卸载 ShellCrash
→ 安装 ProxyFleet Minion
→ native-mihomo 端到端 apply
→ 验证代理、端口白名单和重启持久性
```

V1 不以 ShellCrash adopted 作为生产成功条件。

---

## 12. Docker 可行性与部署边界

### 12.1 结论

项目可以提供 Docker Compose 管理端，但不应要求子节点 Docker 化。推荐组合：

```text
管理主节点：原生 Salt Master（生产参考）或 Docker Compose（便捷配置）
构建器/subconverter：一次性容器
子节点 Salt Minion：宿主机 systemd
子节点 Mihomo：宿主机 systemd
已有 ShellCrash：迁移前只读探测和备份，生产目标为卸载后进入 native-mihomo
```

### 12.2 为什么管理端适合 Docker

- 构建依赖、subconverter 和工具版本容易锁定；
- 一键启动、迁移和备份较方便；
- 构建器可作为短生命周期容器，输入输出明确；
- 主节点不承载业务代理流量。

### 12.3 Salt Master 容器化要求

不得直接依赖陈旧且声明“不受官方支持”的公共 Salt 镜像。项目应从官方 Salt DEB 仓库构建自己的 3008.x 镜像并锁定 digest。

必须持久化：

```text
/etc/salt/pki/master
/etc/salt/master.d
/var/cache/salt/master
/var/log/salt
/srv/salt
/srv/pillar
/workspace/proxyfleet
```

必须备份 Master keys；丢失后会破坏 Minion 信任关系。只开放 4505/4506，不启用 salt-api。

### 12.4 为什么子节点默认不 Docker 化

透明代理需要宿主机 TUN、路由、nftables 和网络能力。容器化后通常需要 `network_mode: host`、`CAP_NET_ADMIN`、`CAP_NET_RAW`、`/dev/net/tun` 和宿主机目录挂载；这显著削弱隔离，还会增加与 Docker 自身网络规则冲突的风险。

Salt Minion 若要管理宿主机 systemd、文件、路由和本地端口白名单，也需要大量宿主机权限和挂载，复杂度高于原生安装。

### 12.5 支持级别

- `host-control`：生产参考；Salt Master 原生 systemd。
- `docker-control`：支持的便捷方案；通过专项备份、恢复和升级测试后用于生产。
- `native-node`：V1 唯一生产支持的子节点形式。
- `docker-node-proxy-only`：后续可选实验模式，只提供 HTTP/SOCKS 端口，不接管宿主机全流量。
- `docker-node-tun`：V1 不支持。

完整说明见 `docs/DEPLOYMENT_DOCKER.md` 和 ADR-0004。

---

## 13. 安全模型

- Salt Master 是最高信任级基础设施；
- Minion key 需要人工核验指纹后接受；
- 4505/4506 仅允许受管节点来源，配合云防火墙；
- Mihomo API 仅监听 loopback/Unix socket；
- 不启用公网 salt-api；
- 订阅 URL、节点密钥和 API secret 不进普通 Git；
- Provider 文件在子节点 root-only；
- release manifest 和源 commit 可审计；
- Docker 镜像、Mihomo、Salt 和 subconverter 均锁定版本/digest；
- 日志必须脱敏；
- 分布式直连意味着子节点可读取节点凭据，这是产品边界而非实现缺陷。

---

## 14. 发布、回滚与 Last Known Good

配置发布流程：

```text
build → offline validate → canary → health verify → batch rollout → convergence report
```

每个节点保留：当前 release、前一 release、最后有效配置。切换使用原子符号链接或目录交换；失败恢复旧 release 并重启/重载验证。

节点选择回滚记录上一个稳定 node_id；COMMIT 失败时尝试恢复，并区分“切换失败”和“回滚失败”。

---

## 15. 状态、审计与可观测性

`fleetctl status` 至少显示：

- Minion 在线状态；
- 驱动类型；
- release revision 和 config SHA-256；
- provider revision；
- `FLEET_PROXY` 当前选择；
- Mihomo 版本和服务状态；
- 最近应用时间与结果；
- 订阅余额、到期时间和 fresh/stale；
- 节点测速缓存的新鲜度、最近延迟和失败原因；
- 漂移原因。

所有写操作生成 operation ID，并记录操作者、目标、输入 revision、结果和回滚状态。

### 15.1 最少步骤安装、配置、同步与切换体验

用户日常操作必须以最少步骤和最少命令完成，但命令减少只能通过编排已审计的底层
动作实现，不得绕过人工核验、组件锁、release hash、Mihomo API GET 再验证和
回滚门禁。底层命令必须保留，方便排障和审计；常用路径提供组合命令。

默认交互入口：

```text
sudo scripts/proxyfleet-master.sh
sudo scripts/proxyfleet-minion.sh
```

上述无参数命令必须进入 TUI 主控台，而不是打印 help 后退出。TUI 负责询问必要
输入、写入对应配置文件、执行已有子命令，并在执行前展示将要修改的文件、服务、
目标 Minion 和危险等级。CLI 子命令仍保留，用于自动化、文档复现和故障恢复。

Master 推荐入口：

```text
sudo fleetctl master prepare
sudo fleetctl master install
sudo fleetctl master configure
sudo fleetctl master setup
fleetctl master status
```

`setup` 等价于 `prepare → install → configure → status`，但每一步必须可单独
执行、可重复执行、失败可定位。

- `prepare`：只读预检 Ubuntu 版本、架构、sudo、端口 4505/4506、APT 源可达性和已有 Salt 状态；
- `install`：安装锁定版本 Salt，写入官方 DEB 源、APT pin、apt hold，并启动 `salt-master.service`；
- `configure`：写入 ProxyFleet Master 配置、file roots、pillar roots 和受管 Salt module/state，不启用公网 `salt-api`；
- `status`：展示 Salt 版本、hold/pin 状态、服务状态、监听端口、已接受和待接受 Minion key 数量。

`setup` 不得自动接受任何 Minion key。

Master TUI 主控台必须覆盖：

- 安装/预检 Salt Master；
- 查看和接受 Salt Minion key；
- 配置订阅 URL、自建节点和自定义规则；
- 构建/校验 release；
- 进入节点测速选择 TUI 并同步；
- 配置 `config-src/port-policy.yaml`；
- 选择端口白名单同步模式；
- 查看服务状态和关键日志位置；
- 卸载和危险清理，危险操作必须二次确认。

Minion 推荐单命令 bootstrap：

```text
sudo fleetctl minion bootstrap \
  --master <master-ip-or-dns> \
  --id <minion-id> \
  --environment production \
  --driver native-mihomo \
  --release-channel stable
```

该命令负责验证 Ubuntu 版本、架构和 Master TCP 4505/4506 可达，安装锁定版本
Salt Minion，配置 APT pin 和 apt hold，写入 Minion ID、Master 地址和 Grains，
启动 `salt-minion.service`，并输出本机 Minion key fingerprint 和下一步 Master
端审核命令。它不得自动接受 key，不得自动安装 Mihomo，不得自动切换代理节点。

Minion TUI 主控台必须覆盖：

- 配置 Master 地址、Minion ID、environment、driver、release channel；
- 安装/重装 Salt Minion；
- 测试 Master TCP 4505/4506 连通性；
- 显示 Salt Minion 状态；
- 显示 Mihomo 状态；
- 执行 `mihomo-start/stop/restart/status/uninstall`；
- 编辑或导入 `/etc/proxyfleet/local/port-policy.yaml`；
- 设置本机端口策略模式：`merge/master-only/local-only/disabled`；
- 危险卸载必须二次确认。

Minion 本机端口策略模式应作为本机持久选项保存，例如：

```text
/etc/proxyfleet/local/options.json
```

优先级为：

```text
Minion local option > Master 下发 mode > 默认 merge
```

这保证 Minion 可自行选择只使用本机规则或禁用端口策略，不被 Master 默认同步覆盖。

用户日常不应手动执行 `build-release → publish-salt → sync`。推荐组合命令：

```text
fleetctl apply --target-group production
fleetctl select <node-id> --target-group production
fleetctl apply --select <node-id> --target-group production
```

`apply` 负责刷新订阅和用量、构建不可变 release、使用锁定版本 Mihomo 离线校验、
发布 release、desired 和 managed port policy 到 Salt file_roots、通过 Salt 同步到
目标 Minion，并输出 convergence report。

`select` 负责第 9 节 PREPARE/COMMIT 流程，只改变 `FLEET_PROXY` 期望选择，
不重建 `config.yaml`。

`apply --select` 的语义必须明确为“先 apply 新 release，再 select 节点”，审计
记录中仍拆成两个 operation phase。

所有组合命令必须支持 `--dry-run`，展示将读取、写入、同步和切换的对象。生产
批量或网络高风险目标必须先 canary，再推广，或要求显式确认。

减少命令不得省略以下人工核验：

1. Master 上查看 pending key：`sudo salt-key -L`；
2. Master 上查看 fingerprint：`sudo salt-key -F`；
3. 与 Minion bootstrap 输出的 fingerprint、Minion ID、资产来源人工比对；
4. 人工确认后执行：`sudo salt-key -a <minion-id>`；
5. 接受后验证：`sudo salt '<minion-id>' test.ping` 和 `sudo salt '<minion-id>' grains.items`。

禁止默认 `auto_accept`，禁止通配接受未知 key，禁止在 fingerprint 未核验时继续
发布 release。

---

## 16. 测试策略

### 16.1 环境矩阵

- Ubuntu 22.04 x86_64：主矩阵；
- Ubuntu 24.04 x86_64：兼容矩阵；
- 至少一项 arm64 smoke test；
- UFW 开启/关闭；
- IPv4-only 和双栈；
- Docker 已安装但 Mihomo 原生运行；
- native-mihomo canary；
- ShellCrash 卸载迁移前只读探测；
- Salt Master 原生与 Docker 两种管理端。

### 16.2 测试层级

- 单元：订阅头、schema、ID、manifest、错误映射；
- 单元：节点测速结果解析、stale 判定、错误码映射和 secret 脱敏；
- 契约：Salt 返回、Mihomo API、release manifest、单节点 delay/provider healthcheck；
- 集成：构建器、Salt State、原生 Mihomo；
- 故障注入：订阅 5xx、空文件、Master 重启、Minion 离线、API 失败、磁盘满；
- 故障注入：测速 API 超时、节点不存在、provider 不一致、健康检查 URL 被拒绝、限频；
- 故障注入：端口白名单冲突、local 语法错误、managed 同步失败、effective 应用失败；
- 网络安全：SSH 不断联、metadata 可达、入站服务响应不被误代理；
- 升级/回滚：Salt、Mihomo、Docker 控制面、端口白名单和 ShellCrash 卸载迁移。

### 16.3 节点测速显示验收

- `fleetctl nodes` 能按 release/provider revision 显示节点、当前选择、延迟、
  freshness、失败原因和数据来源；
- `fleetctl nodes --refresh` 或 `fleetctl health-check` 能主动刷新缓存；
- 多个节点返回延迟时可排序，失败节点显示原因但不影响其他节点；
- `select-sync` 进入后必须先显示节点列表，再后台并发刷新延迟；
  用户可在测速未完成时输入序号，序号在一次菜单会话内必须稳定；
- `--live-health` 只能作为兼容别名进入同一 TUI；
- TUI 必须在固定顶部显示当前选中节点；无选择时显示 `当前选择：无`；
- `curses` TUI 必须支持 viewport 滚动、搜索、键盘选择、退出恢复终端和
  可见行原位刷新；长列表不得依赖跨屏 ANSI 光标回写历史输出；
- TUI 必须显示清晰的标题栏、状态栏、搜索栏、节点表格、帮助栏和状态图例；
- 实时测速必须显示进度或动态状态，长耗时操作不得表现为无输出卡住；
- `--dry-run` 不写 release、desired、Salt file_roots 或 Mihomo 状态；
- 测速不得改变 `FLEET_PROXY` 当前选择，不得关闭连接，不得触发 reload；
- 日志、Result 和 Salt envelope 不得包含 secret、订阅 URL、节点密码或完整代理 URI。

### 16.4 最少步骤体验验收

- 无参数运行 `proxyfleet-master.sh` 必须进入 Master TUI；
- 无参数运行 `proxyfleet-minion.sh` 必须进入 Minion TUI；
- TUI 每个写操作必须显示将修改的文件、服务、目标和危险等级；
- TUI 写入订阅、自建节点、自定义规则、端口白名单和 Minion local option 后，
  生成文件必须通过既有 schema 校验；
- TUI 不得把 secrets、订阅 URL、节点密码或 API secret 输出到日志；
- 单节点原生 Ubuntu 22.04 从空 runtime 完成 `master setup`、`minion bootstrap`、
  key 人工核验、`apply`、`nodes --refresh`、`select`、Mihomo reload 和
  `FLEET_PROXY` GET 再验证；
- 多节点场景至少覆盖一个 online 成功、一个 offline 标记为 `OFFLINE`；
- 重复执行相同输入不得破坏当前 release，desired revision 单调递增且可审计；
- Salt key 未人工接受、组件锁缺失、release hash 不符、manifest path 逃逸、
  Mihomo API 不可用、reload/restart 失败和回滚失败必须 fail-closed；
- QA-RELEASE 或 SECURITY 任一阻断时，不得标记为发布可用。

### 16.5 native-mihomo 端到端验收

- `component-locks.json` 必须记录目标架构 Mihomo 资产 URL、SHA-256、压缩格式和
  期望版本输出；
- `install_mihomo` 必须支持 `.gz` 解压安装，下载文件和最终二进制均有可复现
  校验证据；
- Ubuntu 22.04 x86_64 至少完成一次真实 Minion 端到端：bootstrap、key 人工核验、
  Mihomo 安装、systemd 启动、release 应用、`FLEET_PROXY` 选择、测速和回滚；
- 缺 SHA、SHA 不匹配、gzip 解压失败、版本不匹配、systemd 启动失败必须
  fail-closed，不能覆盖 Last Known Good。

### 16.5A Minion 脚本 Mihomo 生命周期验收

- 默认 `proxyfleet-minion.sh start/stop/restart/uninstall` 不得启动、停止或删除
  Mihomo；
- `--with-mihomo` 和 `mihomo-*` 子命令必须先验证 systemd unit、二进制、
  配置路径和 ProxyFleet 所有权；
- `mihomo-start` 必须完成 active/API 就绪验证；
- `mihomo-stop` 必须保留配置、二进制、release、Last Known Good 和 local override；
- `mihomo-uninstall` 默认保留 `/etc/proxyfleet`，危险清理必须要求
  `--purge-all --yes`；
- `/etc/proxyfleet/local` 只有显式 `--purge-local-override` 才能删除；
- 所有失败路径必须 fail-closed，并返回可恢复建议。

### 16.6 端口白名单与本地 override 验收

- Master 发布 managed port policy 后，Minion 可生成 effective policy；
- `/etc/proxyfleet/local/port-policy.yaml` 存在时，Salt 同步不得覆盖、删除或清空；
- `merge/master-only/local-only/disabled` 四种模式均有 dry-run 和状态输出；
- local 语法错误或冲突时不应用新的 effective policy，保留 Last Known Good；
- 状态报告必须展示 managed/local/effective SHA-256 和策略模式；
- 端口白名单变更必须 canary，避免误关闭当前管理连接。

---

## 17. 实施阶段

### Phase 0：Git bootstrap、规范与实验环境

1. GIT-SCM 完成远端仓库初始化、首个 commit、push 和 SHA 核验；
2. 交付本文档包、测试 VM、版本锁、基础威胁模型和接口契约；
3. 后续 Task 均以已核验 base commit 为输入。

### Phase 1：配置构建与订阅

实现订阅刷新、用量、Provider、config 编译、Mihomo 离线校验、manifest 和缓存。

### Phase 2：Salt 控制平面

实现 Master/Minion 基线、分组、States、release 分发、reconcile、结果模型和
最少步骤 setup/bootstrap/apply 编排。

### Phase 3：原生节点

按以下顺序实现：

1. 补齐 Mihomo 固定资产 URL、SHA-256、gzip 解压安装和版本校验；
2. 完成真实 `native-mihomo` Minion 端到端；
3. 增加端口白名单分层配置；
4. 增加 Minion 本地 override 保护机制；
5. 完成 TUN/proxy-only profiles、节点健康检查/测速和回滚；
6. 增加 Minion 脚本显式 Mihomo 安全启动、停止、状态和完整卸载。

### Phase 4：统一节点切换

实现稳定 node_id、PREPARE/COMMIT、strict/best-effort、验证、漂移、补偿回滚、
节点测速显示和 convergence report。`select-sync` 默认进入标准库 `curses` TUI，
提供 `top/htop/btop` 风格实时交互、当前选择展示、长列表 viewport、搜索、选择、
动态延迟刷新、端口白名单状态提示和终端恢复。

### Phase 5：默认 TUI 主控台

实现 Master/Minion 无参数默认 TUI 主控台。主控台用于配置、导入、校验、同步、
服务控制和卸载；显式子命令保留给自动化。该阶段优先使用 Python 标准库
`curses`，不得引入第三方 TUI 依赖，除非先完成组件锁定和安全审计。

### Phase 6：ShellCrash 迁移工具

只保留只读探测、配置导出、卸载前备份和迁移核验；不作为生产主路径，不要求
ShellCrash 接管式发布进入 V1 成功条件。

### Phase 7：Docker 管理端

构建项目 Salt 3008.x 镜像、Compose、持久卷、备份恢复、升级和灾难恢复。

### Phase 8：硬化和发布

安全审查、故障注入、文档、可重复安装、支持矩阵和 release gate。

---

## 18. Definition of Done

任何功能只有在以下条件同时满足时才完成：

1. 契约已更新；
2. 正常和失败路径测试存在；
3. 结果有可复现证据；
4. 不泄露 secrets；
5. Ubuntu 22.04 主矩阵通过；
6. 需要时 Ubuntu 24.04 兼容矩阵通过；
7. 回滚路径验证；
8. PROJECT_STATE、checkpoint 和相关 ADR 已更新；
9. QA-RELEASE 通过，SECURITY 无阻断项；
10. 需要进入仓库的变更已由 GIT-SCM 创建原子 commit，并在要求 push 时完成远端 SHA 核验；
11. ARCH-ORCH 接受。

---

## 19. Subagent 治理入口

固定角色、职责、会话复用、通信格式和决策权全部定义在 `AGENTS.md`。本计划只规定：

- 每个角色同时最多一个活跃会话；
- 分发任务前必须查会话注册表；
- 优先恢复并复用已有角色会话；
- 不得用新会话规避已有角色的未完成问题；
- 所有任务使用 Task Packet，结果使用 Result Packet；
- 架构决策写 ADR，不得只存在聊天中；
- `ARCH-ORCH` 是单一最终技术决策者；
- SECURITY 和 QA-RELEASE 可阻断发布，但不能绕过 ADR 修改架构。

---

## 20. Subagent 岗位概览

| 角色 | 主要职责 |
|---|---|
| ARCH-ORCH | 任务分解、跨域协调、最终技术决策、冲突裁决 |
| PRODUCT-SPEC | 产品范围、用户流程、验收标准、需求变更 |
| CONTROL-SALT | Salt 架构、States、Pillar、Orchestrate、Minion 生命周期 |
| CONFIG-BUILD | 订阅、subconverter、配置编译、release/manifest |
| DATA-MIHOMO | Mihomo 配置、API、TUN、Provider/Rule 行为 |
| COMPAT-SHELLCRASH | ShellCrash 探测、接管、迁移、恢复 |
| OPS-PLATFORM | Ubuntu、systemd、Docker、备份、运行手册 |
| SECURITY | 威胁模型、密钥、暴露面、供应链、发布安全阻断 |
| QA-RELEASE | 测试矩阵、canary、故障注入、发布门禁 |
| GIT-SCM | Git init、身份/remote、commit、tag、push、冲突与错误处理、远端核验 |
| DOCS-KNOWLEDGE | ADR、状态、checkpoint、一致性和恢复机制 |

详细边界见 `AGENTS.md`。

---

## 21. Subagent 通信机制

唯一合法的跨角色通信产物：

- Task Packet：任务授权和输入；
- Result Packet：结果、证据和未决项；
- Handoff：跨角色后续工作；
- RFC：尚未决定的跨域方案；
- ADR：已接受的决策；
- Checkpoint：角色恢复状态；
- Git Integration Handoff：专业 Owner 将已测试变更交给现有 GIT-SCM 会话集成。

聊天中的结论必须在相应文件落盘后才视为项目事实。

---

## 22. 决策者与冲突处理

- `ARCH-ORCH`：最终技术决策者和唯一跨域裁决者；
- `PRODUCT-SPEC`：解释产品意图；
- `SECURITY`：可因高危问题阻断发布；
- `QA-RELEASE`：可因验收或证据不足阻断发布；
- `GIT-SCM`：可因远端分叉、认证、secret、branch protection 或无法证明无数据丢失而设置 `SCM_BLOCKED`；
- 其他角色：对本域提出方案和证据，不可单方面修改冻结决策。

冲突流程：Result/Handoff → 必要时 RFC → 角色评审 → ARCH-ORCH 决定 → ADR/DECISIONS 更新。

---

## 23. 防失忆和防幻觉制度

### 23.1 权威来源

- 期望行为：PLAN、已接受 ADR、CONTRACTS；
- 当前项目进度：PROJECT_STATE；
- 当前实现事实：代码、测试和可复现输出；
- 外部事实：SOURCES 中登记的官方资料；
- 角色局部状态：checkpoint。

冲突时不得偷偷选择一方，必须登记 drift 并升级。

### 23.2 事实标签

每个 Result 和 State 中的关键陈述应标记：

- `VERIFIED-TEST`：由可复现测试证明；
- `VERIFIED-DOC`：由官方资料证明；
- `OBSERVED`：本次环境观察；
- `INFERRED`：基于证据的推断；
- `PROPOSED`：未接受方案；
- `UNKNOWN`：尚无证据。

推断不得写成已验证事实。

### 23.3 压缩前协议

任何预计会触发上下文压缩、会话结束或任务移交之前，当前角色必须：

1. 更新自身 checkpoint；
2. 写 Result Packet；
3. 更新 PROJECT_STATE 中与本任务相关的事实；
4. 新决策写 ADR/DECISIONS；
5. 记录修改文件、Git branch/HEAD/upstream/remote SHA/working tree 状态和测试证据；
6. 把下一步拆成单个可执行动作；
7. 不把唯一信息留在聊天中。

### 23.4 压缩后协议

恢复者必须按 24.5 顺序读取，核对 checkpoint 的 commit/file hash，然后才能继续执行。GIT-SCM 还必须核对实际 remote ref，不得只相信上一次 push 摘要。若文件和摘要冲突，以文件和实际测试为准，并登记冲突。

---

## 24. 会话恢复规范

### 24.1 新会话

新角色会话只能在注册表中不存在可复用会话，或旧会话被明确标记为不可恢复时创建。

### 24.2 替换会话

替换会话必须记录 `supersedes`、原因、旧 checkpoint、最后 Result 和未完成任务。旧会话状态改为 `SUPERSEDED`，不得同时保持两个同角色活跃会话。

### 24.3 会话复用

任务分发前由 ARCH-ORCH 查询 `checkpoints/SESSION_REGISTRY.md`：

```text
role exists and ACTIVE → 复用原会话
role exists and PAUSED → 恢复原会话
role exists but IRRECOVERABLE → 创建一个替换会话并登记
role absent → 创建一次并登记
```

### 24.4 恢复完成条件

恢复者必须能准确说明：当前目标、最后已验证状态、未决问题、适用 ADR、接口版本、最近测试证据和下一原子动作。无法说明时不得修改代码或配置。

### 24.5 恢复读取顺序

任何新会话或替换会话必须按顺序读取：

```text
1. PLAN.md
2. AGENTS.md
3. PROJECT_STATE.md
4. DECISIONS.md 和相关 ADR
5. interfaces/CONTRACTS.md；GIT-SCM 同时读取 docs/GIT_OPERATIONS.md
6. 自身 checkpoint
7. 当前 Task Packet
8. 相关 Result/Handoff
9. 实际代码、测试，以及 Git branch/HEAD/upstream/remote 状态
```

### 24.6 恢复校验

恢复后写一段短的 Recovery Record 到 checkpoint，至少包括：

```text
loaded_commit
loaded_contract_version
active_task_id
last_verified_result_id
open_blockers
next_atomic_action
```

---

## 25. 当前交付物

本次文档包应包含：

- `PLAN.md`
- `AGENTS.md`
- `PROJECT_STATE.md`
- `DECISIONS.md`
- `SOURCES.md`
- 至少 6 个 ADR
- `interfaces/CONTRACTS.md`
- 全部 11 个角色 checkpoint
- Session Registry
- Task/Result/Handoff/RFC 模板
- 当前 Task 和 Result
- Docker 部署评估
- Git 操作与错误处理手册
- Git bootstrap Task Packet

---

## 26. 主要风险

| 风险 | 对策 |
|---|---|
| Salt Master 被攻破 | 单独主机、最小端口、严格 key 审批、备份和审计 |
| 公共 Salt Docker 镜像陈旧/不受支持 | 自建镜像，使用官方 DEB，锁定版本和 digest |
| Docker 管理端丢失 Master keys | 持久化、离线加密备份、恢复演练 |
| 子节点 TUN 导致管理连接断开 | canary、旁路 Master/metadata、自动恢复和入站回包测试 |
| ShellCrash 覆盖受管配置 | 明确配置所有权，只写持久入口，重启验证 |
| 订阅错误正文覆盖节点 | 内容验证、Last Known Good、原子发布 |
| 节点同名或改名 | 稳定 node_id + 唯一 Mihomo 名称 |
| 子节点泄露节点凭据 | root-only、日志脱敏、凭据轮换；接受分布式模式边界 |
| Subagent 重复创建和结论冲突 | 唯一会话注册表、强制复用、单一决策者 |
| 上下文压缩失忆 | checkpoint、Result、PROJECT_STATE、恢复顺序和证据标签 |
| 多角色自行 commit/push 导致历史冲突 | GIT-SCM 唯一写入岗位、Handoff 和唯一会话复用 |
| 认证凭据进入 Git/日志 | 安全凭据引用、无秘密 URL、secret scan、SECURITY 阻断 |
| non-fast-forward 被错误 force 覆盖 | fetch/compare、backup ref、默认禁止 force、ARCH 决策 |

---

## 27. 下一步

1. 用户提供远程仓库 URL、user.name、user.email、默认分支和认证方式；
2. ARCH-ORCH 查询 Session Registry，创建或复用唯一 GIT-SCM 会话；
3. GIT-SCM 执行 TP-0002 只读预检、init/commit/push 和远端 SHA 核验；
4. CONTROL-SALT 做 Salt 3008.1 原生与容器化 POC；
5. DATA-MIHOMO 验证 Ubuntu 22.04/24.04 的 proxy-only 与 TUN 基线；
6. COMPAT-SHELLCRASH 建立只读探测矩阵；
7. CONFIG-BUILD 固化源 schema 和 release manifest；
8. SECURITY 输出威胁模型；
9. QA-RELEASE 建立可重复 VM 测试矩阵。

除已创建的 TP-0002 外，后续执行前必须创建新的 Task Packet。任何代码 Task 都必须引用 TP-0002 产生的已核验 base commit。
