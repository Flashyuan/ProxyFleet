# ProxyFleet 供应链安全基线

> 版本：0.1
> 状态：Draft security baseline
> Owner：SECURITY
> 更新日期：2026-06-23

## 1. 目的

本文定义 ProxyFleet 在依赖、二进制、容器镜像、APT 包、Secrets、SBOM、漏洞扫描和升级发布上的供应链安全基线。

本基线约束以下范围：

- Salt Master/Minion；
- Mihomo；
- subconverter 和配置构建器；
- Docker/Compose 管理端镜像；
- Ubuntu APT 包；
- release 包、manifest 和运行时制品；
- Git 仓库中的源码、文档、任务和证据。

任何无法满足校验、版本锁定或发布门禁的变更必须 fail-closed，不得降级为“尽力而为”继续发布。

## 2. 基本原则

1. 生产组件必须使用固定开源组件版本，不使用 `latest`、浮动 tag、浮动分支或未记录来源的二进制。
2. 所有严格受管节点必须使用同一 release revision、同一文件 SHA-256 和同一 Mihomo 版本。
3. Salt 生产部署必须锁定 Salt 3008 LTS 的明确 point release，升级必须经过 canary。
4. Docker 管理端必须记录基础镜像 digest、项目镜像 digest、Salt 包版本和构建来源。
5. release manifest 必须记录源 Git commit、Mihomo 版本、每个发布文件哈希和兼容 schema 版本。
6. 订阅 URL、节点凭据、Salt PKI、SSH 私钥、PAT、Mihomo API secret 和生产 `.env` 实例不得进入普通 Git 历史、镜像层、日志或命令行历史。
7. 升级必须经过 canary、QA-RELEASE 验证和 SECURITY 审查；缺少任一证据时不得批量发布。

## 3. 版本锁定

### 3.1 Salt

Salt Master 和 Salt Minion 必须安装 Salt 3008 LTS 的明确 point release，例如 `3008.x` 中已验证的具体包版本。

禁止：

- 使用未指定 point release 的安装命令；
- 让生产节点自动漂移到新的 Salt 包版本；
- 直接采用公开且声明不受官方支持、标签陈旧的 `saltstack/salt` Docker 镜像作为生产基础。

要求：

- APT 源必须按 Salt 官方 DEB 安装指南配置；
- `salt-master`、`salt-minion` 和相关 Salt 包必须使用 apt pin 或 apt hold 固定；
- Salt 包版本、APT 源、仓库签名材料和安装时间必须写入部署证据；
- Salt 升级必须先在 canary 节点验证 Master/Minion 连接、key 生命周期、State 执行、release 分发和回滚。

### 3.2 Mihomo

Mihomo 必须锁定具体版本和二进制 SHA-256。

要求：

- 每个 Mihomo 二进制必须记录下载来源、版本、平台架构和 SHA-256；
- 安装前必须校验 SHA-256，校验失败立即停止；
- release manifest 必须记录 Mihomo 版本；
- 所有严格受管生产节点必须运行同一已批准 Mihomo 版本；
- 已有 ShellCrash 节点应在迁移前备份和卸载，再由 ProxyFleet 安装锁定 Mihomo。

禁止：

- 使用运行时自动下载的未校验 Mihomo；
- 使用浮动 release 链接作为生产安装依据；
- 在未通过 canary 的情况下批量替换 Mihomo。

### 3.3 subconverter 和构建器

subconverter 和配置构建器只应在主节点构建阶段运行，优先使用短生命周期容器。

要求：

- subconverter 版本必须固定；
- 容器镜像必须固定 digest；
- 构建容器应在接收已验证输入后使用 `network:none` 运行；
- 构建输出必须经过锁定版本 Mihomo 离线校验；
- 生成 release 前必须计算所有输出文件 SHA-256。

禁止：

- 将订阅 URL 写入镜像、Compose 文件、命令行参数或日志；
- 让转换器容器在构建期间主动访问外网；
- 将未校验输出直接发布到稳定 release。

## 4. 容器镜像与 digest

管理端 Docker 可以作为支持配置，但生产镜像必须由项目维护，不依赖不受支持的公共 Salt 镜像。

要求：

1. Dockerfile 的基础镜像必须使用不可变 digest，例如 `image@sha256:<digest>`。
2. Compose 文件必须引用项目镜像 digest，不使用 `latest` 或浮动 tag。
3. 镜像构建必须记录：
   - 基础镜像名称和 digest；
   - Salt point release；
   - subconverter/构建器版本；
   - 构建 Git commit；
   - 构建时间；
   - SBOM 位置；
   - 漏洞扫描结果。
4. 镜像不得内置生产 secrets、Salt Master keys、订阅 URL 或节点凭据。
5. 镜像启动时必须拒绝缺失持久卷，尤其是 `/etc/salt/pki/master`、配置 roots 和工作区挂载。

禁止：

- 使用 `latest`、`stable`、`main`、`master`、日期滚动 tag 或未固定 digest 的镜像作为生产输入；
- 使用 `docker compose down -v` 作为常规运维动作；
- 用高权限容器绕过 V1 对子节点原生 systemd 部署的边界。

## 5. APT hold/pin

Ubuntu 22.04/24.04 节点必须避免关键包无审计漂移。

必须固定的包类别：

- Salt Master/Minion 及其 Python 依赖包；
- Mihomo 安装包或本地封装包；
- Docker Engine、Compose 插件和容器运行时；
- 会影响路由、防火墙或 systemd 行为的关键平台包。

最低要求：

```text
apt-mark hold <package>
或
/etc/apt/preferences.d/<proxyfleet-pin>
```

pin/hold 状态必须在部署证据中记录。解除 hold 或调整 pin 属于升级动作，必须走 canary、QA-RELEASE 和 SECURITY 门禁。

## 6. 二进制 SHA-256

所有进入 release 或节点安装路径的二进制必须有 SHA-256。

适用对象：

- Mihomo 二进制；
- subconverter 二进制或镜像内对应制品；
- 项目自建工具制品；
- 离线安装包；
- release 包内所有配置、provider、rule 和 manifest 文件。

校验规则：

1. 下载后立即计算 SHA-256。
2. 与批准清单中的 SHA-256 比对。
3. 比对成功后才允许进入 staging。
4. staging 生成 release 前再次 hash 全量文件。
5. 节点 reconcile 时对比期望 release、实际哈希和期望选择。

缺少批准清单、清单格式错误、哈希不匹配或无法读取文件时，必须 fail-closed。

## 7. Secrets 禁止项

以下内容禁止进入 Git、镜像层、release 包、测试 fixture、日志、Result Packet 明文和命令行历史：

- 订阅 URL、订阅 token 和订阅响应原文；
- 自建节点密码、UUID、Reality 私钥和短 ID；
- Salt Master/Minion 私钥、accepted key 私钥材料和 PKI 备份；
- SSH 私钥、GitHub PAT、HTTPS token 和 credential helper 明文；
- Mihomo API secret；
- 生产 `.env` 实例文件；
- 脱敏前日志、运行时缓存和 provider 原始快照；
- 带凭据的远端 URL。

允许进入仓库的只能是：

- secret 引用名称；
- 脱敏示例；
- 空模板；
- 说明如何通过安全渠道注入的文档。

发现 secret scan 失败、疑似凭据泄露或 secret 已进入远端历史时，SECURITY 必须阻断发布。后续处置优先吊销和轮换秘密，历史清理不能替代凭据轮换。

## 8. SBOM 与漏洞扫描

每个可发布镜像和二进制 release 都必须生成 SBOM，并执行漏洞扫描。

最低要求：

- 镜像 SBOM 覆盖基础镜像、系统包、Python/构建依赖和项目文件；
- release SBOM 覆盖 Mihomo、subconverter、项目工具和发布文件；
- 漏洞扫描结果必须关联到 Git commit、镜像 digest 或 release revision；
- 高危或可利用漏洞必须由 SECURITY 明确接受、缓解或阻断；
- 扫描工具不可用、扫描失败或结果无法追溯时，不得标记为可发布。

扫描结果应作为 QA/SECURITY release gate 证据，而不是发布后的补充记录。

## 9. Fail-closed 条件

出现以下任一情况必须停止当前构建、发布或升级：

- 使用了 `latest`、浮动 tag、浮动分支或未固定 digest 的生产依赖；
- 缺少 Mihomo、subconverter、镜像或 release 文件 SHA-256；
- SHA-256、镜像 digest 或远端 Git SHA 与期望不一致；
- apt hold/pin 缺失，或关键包版本无法证明；
- SBOM 缺失、漏洞扫描失败或扫描结果不可追溯；
- 订阅 URL、节点凭据、Salt PKI、API secret 或 Git 凭据疑似泄露；
- Salt key、Master PKI、release manifest 或 desired state 的来源无法确认；
- canary、回滚或 QA/SECURITY 证据缺失；
- ShellCrash adopted 节点版本、路径或持久化行为未知。

fail-closed 后只能输出错误、保留证据并回传 Owner，不得自动切换到未校验版本、跳过扫描或临时放宽策略。

## 10. 升级流程

Salt、Mihomo、subconverter、Docker 基础镜像、Compose 栈和关键 Ubuntu 包的升级必须按以下顺序执行：

```text
提出升级 Task
→ 固定目标版本、digest、SHA-256 和来源
→ 更新 SBOM 和漏洞扫描
→ 在 staging 构建 release
→ 使用锁定 Mihomo 离线校验配置
→ canary 节点部署
→ 验证健康检查、业务路径和回滚
→ QA-RELEASE 记录测试证据
→ SECURITY 审查供应链证据
→ ARCH-ORCH 接受需要的长期决策
→ GIT-SCM 创建可追溯提交或 tag
→ 批量发布
```

升级不得跳过 canary。高风险网络配置、Salt 3008.x point release、Mihomo 主版本变化、Docker host network 变更和 ShellCrash adopted 行为变化必须额外验证回滚路径。

## 11. 发布证据清单

发布前至少保留以下证据：

- 源 Git commit；
- release revision；
- release manifest；
- 每个发布文件 SHA-256；
- Mihomo 版本和 SHA-256；
- Salt point release 和 apt hold/pin 状态；
- Docker 基础镜像 digest 和项目镜像 digest；
- subconverter/构建器版本；
- SBOM；
- 漏洞扫描结果；
- secret scan 或人工等价审查结果；
- canary 节点、时间、命令和结果；
- 回滚验证结果；
- QA-RELEASE 和 SECURITY gate 结论。

缺少上述关键证据时，release 状态只能是 `BLOCKED` 或 `PARTIAL`，不得标记为生产可发布。
