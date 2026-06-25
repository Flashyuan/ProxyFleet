# ProxyFleet Phase 0/1 最小测试矩阵

> Owner：QA-RELEASE
> 状态：PROPOSED
> 范围：Phase 0/1 发布门禁所需的最小测试集合
> 约束：所有测试证据必须关联 Task/Result；涉及 Git 写操作时必须由 GIT-SCM 记录并核验。

## 1. 测试分层

- **静态/契约测试**：验证配置、manifest、锁文件、digest、SHA、版本约束和发布门禁条件。
- **集成测试**：验证 Git bootstrap、安装流程、组件下载与校验、Salt/Mihomo/subconverter/Docker 的最小可用路径。
- **故障注入测试**：验证校验失败、版本不匹配、网络失败、权限失败、回滚失败等失败路径。
- **升级/回滚测试**：验证安装后不自动更新、Salt 3008.x point release 升级、组件锁定版本升级和 Last Known Good 回滚。

## 2. Phase 0：仓库与供应链门禁

### 2.1 Git bootstrap

- **目标**：确认仓库初始化、repo-local 身份、remote、分支和 push 语义可审计。
- **覆盖点**：
  - `git init` 或接入已有仓库不会覆盖用户已有修改。
  - `user.name` / `user.email` 仅写入 repo-local 配置，不误当作认证凭据。
  - remote URL 输出必须脱敏，不记录 token、密码或私钥。
  - push 后重新读取远端 ref，确认远端 SHA 与本地目标 commit 一致。
  - non-fast-forward、detached HEAD、远端非空、unrelated histories 必须阻断并记录。
- **最小证据**：
  - `git status --short`
  - `git config --local --list`
  - `git remote -v` 脱敏摘要
  - push 前后本地 HEAD 与远端 ref SHA

### 2.2 组件锁校验

- **目标**：确认所有外部组件均由锁文件或 manifest 明确版本、来源和校验材料。
- **覆盖点**：
  - Salt、Mihomo、subconverter、Docker 镜像均有固定版本或 digest。
  - 锁文件缺失、字段缺失、未知组件、重复组件必须 fail-fast。
  - manifest 与实际下载目标不一致时必须拒绝发布。
- **最小证据**：
  - lock/manifest 静态校验结果
  - 缺失字段的失败样例

### 2.3 安装不自动更新

- **目标**：确认安装流程不会隐式升级系统包、二进制、容器镜像或配置生成器。
- **覆盖点**：
  - 安装脚本不得执行无约束的 `upgrade`、`dist-upgrade`、`latest` 拉取。
  - Docker 镜像不得使用未锁定的 `latest` 标签作为发布输入。
  - Salt/Mihomo/subconverter 只使用 manifest 指定版本。
  - 自动更新服务、timer 或 cron 默认不得启用。
- **最小证据**：
  - 安装命令 dry-run 或脚本审计结果
  - systemd timer/cron 检查结果

### 2.4 发布门禁

- **目标**：定义 Phase 0 进入 Phase 1 前必须满足的最低发布条件。
- **阻断条件**：
  - 任一组件缺少版本、SHA、digest 或来源。
  - secret scan 发现凭据或带凭据 URL。
  - Git 远端状态未核验却声明已 push。
  - SECURITY 或 QA-RELEASE 标记 `RELEASE_BLOCKED`。
  - 回滚路径没有可复现实验证据。
- **最小证据**：
  - 门禁清单结果
  - 阻断项与解除条件

## 3. Phase 1：组件集成、故障注入与回滚

### 3.1 Salt 3008.x point release

- **目标**：确认 Salt 控制平面固定在 3008.x point release，并能安全处理小版本升级。
- **覆盖点**：
  - Master/Minion 安装版本必须匹配 manifest 允许范围。
  - 3008.x point release 升级前后 key 生命周期、grains、pillar、state.apply、orchestrate 基本可用。
  - 版本低于 3008.x、跨大版本或来源不可信必须阻断。
  - 升级失败时不得破坏既有 Master/Minion 可恢复状态。
- **最小证据**：
  - `salt --versions-report` 摘要
  - Master/Minion 连通性结果
  - point release 升级与失败回滚记录

### 3.2 Mihomo SHA 校验

- **目标**：确认 Mihomo 二进制下载、安装和运行前必须通过 SHA 校验。
- **覆盖点**：
  - 下载产物 SHA 与 manifest 完全一致才允许安装。
  - `.gz` 资产必须先校验压缩包 SHA，再解压并原子替换目标二进制。
  - SHA 不匹配、下载截断、文件替换、权限异常必须 fail-closed。
  - gzip 解压失败、目标架构缺失、版本输出不匹配必须 fail-closed。
  - systemd 启动前校验通过，失败时不覆盖 Last Known Good。
  - Mihomo API 最小健康检查可验证。
- **最小证据**：
  - SHA 校验成功记录
  - SHA 不匹配失败记录
  - systemd 与 API 健康检查结果
  - gzip 解压与版本探测证据

### 3.3 subconverter digest

- **目标**：确认 subconverter 镜像或二进制使用固定 digest，并且订阅转换结果可追溯。
- **覆盖点**：
  - digest 与 manifest 不一致时拒绝运行。
  - 订阅输入、转换输出、release manifest、哈希之间可追溯。
  - 订阅源不可达、返回格式异常、Subscription-Userinfo 异常必须进入失败路径。
  - 缓存命中不得绕过 digest 与输出哈希校验。
- **最小证据**：
  - digest 校验记录
  - 正常转换样例
  - 订阅异常与缓存异常失败样例

### 3.4 Docker digest

- **目标**：确认所有容器镜像按 digest 拉取和运行，不依赖可变标签。
- **覆盖点**：
  - Compose 或部署配置中镜像必须包含 digest。
  - digest 不匹配、镜像拉取失败、平台架构不匹配必须阻断。
  - 容器权限、挂载、网络边界必须与 SECURITY/OPS 约束一致。
  - 重启后容器仍使用相同 digest。
- **最小证据**：
  - `docker inspect` digest 摘要
  - Compose 配置校验结果
  - 拉取失败与 digest 不匹配失败样例

### 3.5 回滚

- **目标**：确认配置、二进制、镜像和服务状态可从失败发布回到 Last Known Good。
- **覆盖点**：
  - Mihomo 配置发布失败后恢复上一个可用配置。
  - Salt state/orchestrate 失败后保留可诊断日志，不进入半成功状态。
  - Docker 镜像升级失败后回到上一 digest。
  - 回滚后健康检查必须通过，否则继续标记发布失败。
  - 回滚操作不得删除诊断证据。
- **最小证据**：
  - Last Known Good manifest
  - 回滚前后版本/digest/SHA 对比
  - 回滚后健康检查结果

### 3.6 失败路径

- **目标**：确认关键失败不会被静默吞没，且错误信息可定位、可复现。
- **覆盖点**：
  - manifest 缺失、锁文件损坏、digest/SHA 不匹配。
  - 网络不可达、DNS 失败、下载超时、磁盘空间不足。
  - systemd 启动失败、权限不足、端口占用。
  - Salt key 未审批、Minion 离线、state 返回非零。
  - Mihomo API 不可达、配置解析失败、provider 更新失败。
  - Git remote 认证失败、分支保护、non-fast-forward。
- **最小证据**：
  - 每类失败至少一个可复现摘要
  - 对应日志位置
  - 是否触发 `RELEASE_BLOCKED` 或 `SCM_BLOCKED`

### 3.7 native-mihomo 端到端

- **目标**：确认生产主路径不依赖 ShellCrash，单台真实 Minion 可完整接收并应用
  ProxyFleet 管理。
- **覆盖点**：
  - ShellCrash 已卸载或未安装；
  - `proxyfleet-minion.sh bootstrap` 安装固定 Salt Minion；
  - Master 人工核验 Salt key；
  - Salt state 安装锁定 Mihomo，启动 `mihomo.service`；
  - release 校验、应用、`FLEET_PROXY` 选择和 GET 再验证；
  - `health-check` 能返回节点延迟或明确失败原因；
  - 重启后 `mihomo.service` 和当前 release 持久。
- **最小证据**：
  - `salt '<minion-id>' test.ping`
  - `systemctl status mihomo`
  - Mihomo API 策略组 GET/PUT/GET 摘要
  - release manifest SHA 校验摘要

### 3.7A 实时测速选择菜单

- **目标**：确认标准库 `curses` TUI 实时测速不阻塞节点选择，且不改变运行状态。
- **覆盖点**：
  - `select-sync --live-health` 先显示稳定序号列表，再后台并发刷新延迟；
  - 用户可在测速未完成时输入序号；
  - 一次菜单会话内序号不因延迟结果到达而重排；
  - 长列表不得跨屏改写历史输出；
  - TUI viewport 支持上下滚动、高亮、搜索、重新测速、退出恢复终端；
  - TUI 只刷新可见行、状态栏和输入区域；
  - `q`、Ctrl-C 和异常退出必须恢复 cooked mode；
  - 并发和超时有硬上限，非法值 fail-fast；
  - Mihomo API 仅允许 loopback 地址；
  - 缓存绑定 release/provider revision，不合并旧 release 缓存；
  - 缓存写入使用原子替换；
  - 单节点 timeout/failed 不影响其他节点测速。
- **最小证据**：
  - `select-sync --live-health --health-concurrency <n>` 屏幕录像或终端摘要；
  - `curses` TUI 伪终端测试覆盖滚动、搜索、选择、退出和异常恢复；
  - health cache JSON 中 `release_revision/provider_revision/source_scope`；
  - 非 loopback API 被拒绝的错误摘要；
  - 单元测试覆盖进度输出、缓存绑定和参数边界。

### 3.8 端口白名单与本地 override

- **目标**：确认 Master 可统一下发公共端口白名单，同时 Minion 本地规则不会被覆盖。
- **覆盖点**：
  - `merge/master-only/local-only/disabled` 四种模式；
  - `/etc/proxyfleet/local/port-policy.yaml` 不被 Salt 同步覆盖或删除；
  - managed/local 合并结果保留规则来源；
  - 冲突、local 语法错误、effective 应用失败均 fail-closed；
  - 回滚到 Last Known Good effective policy；
  - canary 期间不切断当前管理连接。
- **最小证据**：
  - managed/local/effective 三层 SHA-256；
  - dry-run 输出；
  - 冲突失败样例；
  - Salt state 对 `/etc/proxyfleet/local` 的防覆盖测试。

## 4. 最小通过标准

Phase 0 通过条件：

1. Git bootstrap 门禁证据齐全。
2. 所有组件锁校验通过。
3. 安装流程确认不会自动更新。
4. 发布门禁无阻断项。

Phase 1 通过条件：

1. Salt 3008.x point release 安装、连通性和升级/失败路径通过。
2. Mihomo SHA/gzip 安装、subconverter digest、Docker digest 均完成成功与失败样例验证。
3. 回滚路径完成至少一次端到端演练。
4. 失败路径均有错误、日志、阻断状态和恢复建议。
5. native-mihomo 真实 Minion 端到端通过。
6. 端口白名单本地 override 防覆盖测试通过。
7. QA-RELEASE 与 SECURITY 均未设置 `RELEASE_BLOCKED`。

## 5. 结果记录要求

- 每次测试必须记录 Task ID、执行环境、输入版本、命令摘要、结果和证据位置。
- `VERIFIED` 只用于有命令、日志或文件证据的结论。
- `OBSERVED` 用于人工观察到但尚未自动化的事实。
- `INFERRED` 必须说明推断依据，不能作为发布门禁通过证据。
- `UNKNOWN` 必须列入阻断或后续任务，不能被默认视为通过。
- 发布前 Result Packet 必须包含修改文件、测试结果、风险、阻断状态和回滚证据。
