# ProxyFleet 组件版本锁定清单契约

> Contract 版本：0.1-draft
> 状态：Proposed
> Owner：CONFIG-BUILD
> 适用范围：Salt、Mihomo、subconverter、Docker/base image、运行时依赖和规则数据的可复现安装与升级校验

## 1. 目标

组件版本锁定清单用于描述 ProxyFleet 构建、部署和运行所依赖的外部组件。

该清单必须让控制平面在安装、升级、回滚和审计时回答三个问题：

1. 当前允许使用哪个组件版本；
2. 组件应从哪里获取并如何校验；
3. 组件是否允许自动升级、保持锁定或只读引用。

## 2. 顶层结构

伪结构：

```yaml
schema_version: "1.0"
generated_at: "2026-06-23T00:00:00Z"
source_git_commit: "<sha>"
components:
  - name: "mihomo"
    kind: "binary"
    version: "v1.19.8"
    source:
      type: "github_release"
      url: "https://github.com/MetaCubeX/mihomo/releases/download/v1.19.8/mihomo-linux-amd64-v1.19.8.gz"
      repository: "MetaCubeX/mihomo"
      ref: "v1.19.8"
    architecture: "linux/amd64"
    sha256: "<hex>"
    digest: null
    signature:
      type: "cosign|minisign|gpg|none"
      identity: null
      value: null
      certificate_sha256: null
    install_policy:
      mode: "managed"
      target_path: "/usr/local/bin/mihomo"
      owner: "root"
      group: "root"
      file_mode: "0755"
    hold_policy:
      mode: "hold"
      reason: "受管节点必须运行经验证版本"
    verification:
      required: true
      methods: ["sha256"]
      runtime_command: ["mihomo", "-v"]
      expected_output_pattern: "Mihomo Meta v1.19.8"
    upgrade_policy:
      channel: "stable"
      strategy: "manual"
      allow_prerelease: false
      rollback_to_previous: true
```

约束：

- `schema_version` 必填；不支持 major 时必须 fail-closed；
- `components[]` 必填；为空表示没有任何外部组件被授权安装；
- `name` 在同一清单内必须唯一；
- 所有时间必须使用 RFC 3339 UTC；
- 所有远程来源必须显式记录 `source`，不得依赖隐式下载地址；
- 可执行文件、归档、镜像和规则数据必须至少具备一种强校验方式；
- 未知字段允许保留，但未知必填语义不得静默忽略。

## 3. Component 字段

### 3.1 `name`

组件稳定名称，由项目定义。

示例：

- `salt-master`
- `salt-minion`
- `mihomo`
- `subconverter`
- `docker-engine`
- `base-image-ubuntu`
- `runtime-python`
- `rules-geosite`
- `rules-geoip`

约束：同一组件升级时 `name` 不变；语义不同的组件不得复用名称。

### 3.2 `kind`

组件类型。

允许值：

- `package`：系统包，例如 Salt、Docker Engine；
- `binary`：单文件或解压后可执行文件，例如 Mihomo；
- `container_image`：容器镜像，例如 subconverter 镜像；
- `base_image`：基础镜像，例如 Ubuntu；
- `archive`：压缩包或 release 产物；
- `runtime_dependency`：运行时依赖，例如 Python、Go、systemd 单元依赖；
- `ruleset`：规则数据，例如 geosite、geoip、自定义规则源；
- `config_template`：配置模板或生成器输入；
- `data_file`：非规则类数据文件。

### 3.3 `version`

组件版本。

约束：

- 上游存在语义化版本时应使用原始 tag 或版本号；
- 系统包应包含完整包版本；
- 容器镜像不得只写 `latest`，必须写 tag，并配合 `digest` 锁定；
- 规则数据没有发布版本时，必须写上游 commit、日期版本或内容版本。

### 3.4 `source`

组件来源。

伪结构：

```yaml
source:
  type: "apt|github_release|url|oci_registry|git|local|salt_repo|docker_repo"
  url: "https://example.invalid/artifact"
  repository: "owner/project"
  ref: "v1.0.0"
  package_name: "example"
  registry: "docker.io"
  image: "library/ubuntu"
```

约束：

- `type` 必填；
- 远程 URL 不得包含 token、密码、订阅地址或其它 secret；
- `local` 来源只能引用仓库内受管路径或已记录的构建产物；
- `git` 来源必须记录 commit 或 tag；只记录 branch 不足以锁定版本。

### 3.5 `architecture`

目标架构。

推荐格式：

- `linux/amd64`
- `linux/arm64`
- `linux/arm/v7`
- `all`

约束：同一组件需要多架构时，应为每个架构写独立条目，或在 `variants[]`
中显式枚举；不得让安装器根据当前机器自动下载未锁定产物。

### 3.6 `sha256`

组件内容 SHA-256。

适用对象：

- 二进制文件；
- 归档文件；
- 规则数据文件；
- 本地构建产物；
- OCI 镜像导出物或 manifest 文件。

约束：

- 可下载文件必须填写；
- 无法提前知道哈希时，必须在 `verification` 中说明替代强校验方式；
- 校验失败必须阻断安装或发布。

### 3.7 `digest`

内容寻址摘要，主要用于 OCI 镜像。

示例：

```yaml
digest: "sha256:<hex>"
```

约束：

- `container_image` 和 `base_image` 必须填写；
- tag 与 digest 同时存在时，实际拉取结果必须匹配 digest；
- digest 变更必须视为组件变更，即使 tag 未变。

### 3.8 `signature`

签名或证明材料。

伪结构：

```yaml
signature:
  type: "cosign|minisign|gpg|none"
  identity: "release@example.invalid"
  value: "<signature-or-reference>"
  certificate_sha256: "<hex>"
  transparency_log: "rekor"
```

约束：

- 上游提供签名时应记录并验证；
- `type: none` 必须显式表示没有签名，不得省略；
- 签名验证失败时必须 fail-closed；
- 签名不替代 `sha256` 或 `digest`，两者可互为补强。

### 3.9 `install_policy`

安装策略。

伪结构：

```yaml
install_policy:
  mode: "managed|external|readonly|build_only"
  target_path: "/usr/local/bin/example"
  package_manager: "apt|docker|manual|none"
  service_name: "example.service"
  owner: "root"
  group: "root"
  file_mode: "0755"
  restart_required: true
```

含义：

- `managed`：ProxyFleet 负责安装、更新和校验；
- `external`：由外部系统安装，ProxyFleet 只验证版本；
- `readonly`：只读取或引用，不安装；
- `build_only`：仅在构建阶段使用，不进入运行节点。

### 3.10 `hold_policy`

保持锁定策略。

伪结构：

```yaml
hold_policy:
  mode: "hold|allow_patch|allow_minor|track_channel|none"
  reason: "说明锁定原因"
  expires_at: null
```

约束：

- 核心数据面组件默认应使用 `hold`；
- `track_channel` 只允许用于非关键数据或经 SECURITY/QA 接受的低风险依赖；
- `expires_at` 只表达复审时间，不代表到期自动升级。

### 3.11 `verification`

安装前后验证策略。

伪结构：

```yaml
verification:
  required: true
  methods: ["sha256", "signature", "runtime_version", "service_health"]
  runtime_command: ["example", "--version"]
  expected_output_pattern: "example 1.0.0"
  service_health:
    type: "systemd|http|docker"
    target: "example.service"
  fail_policy: "block_install|block_release|warn_only"
```

约束：

- `required: true` 时，所有列出的强校验必须通过；
- 核心组件不得使用 `warn_only`；
- 运行时命令不得输出 secret；
- 校验结果应进入 Result Packet 或发布证据。

### 3.12 `upgrade_policy`

升级策略。

伪结构：

```yaml
upgrade_policy:
  channel: "stable|canary|security|manual"
  strategy: "manual|proposal_only|auto_patch|auto_minor"
  allow_prerelease: false
  requires_adr: false
  requires_security_review: true
  requires_qa_evidence: true
  rollback_to_previous: true
```

约束：

- 默认策略为 `manual`；
- 会改变运行时行为、网络边界或数据面兼容性的升级必须要求 QA 证据；
- 安全修复可进入 `security` channel，但仍必须保留版本、来源和校验证据；
- 任何自动升级策略不得绕过 `verification`。

## 4. 组件表达规范

### 4.1 Salt

Salt 相关组件应拆分为独立条目：

- `salt-master`：Master 包版本；
- `salt-minion`：Minion 包版本；
- `salt-repo-key`：仓库签名 key 或 keyring；
- `salt-bootstrap`：安装脚本或 bootstrap 产物。

表达要求：

- `kind` 通常为 `package` 或 `data_file`；
- `source.type` 可为 `apt`、`salt_repo` 或 `url`；
- `version` 必须包含 Salt 3008.x 的完整包版本；
- `signature` 必须记录仓库签名或 keyring 校验；
- `install_policy` 应声明包管理器和服务名；
- `verification` 应至少包含包版本查询和 systemd 服务状态。

### 4.2 Mihomo

Mihomo 应表达为数据面核心二进制。

表达要求：

- `name: mihomo`；
- `kind: binary` 或 `archive`；
- `source.type` 通常为 `github_release` 或 `url`；
- `architecture` 必须匹配目标节点；
- `sha256` 必填；
- 如上游提供签名或校验文件，必须在 `signature` 或额外组件中表达；
- `install_policy.mode` 通常为 `managed`；
- `hold_policy.mode` 默认 `hold`；
- `verification` 必须包含运行时版本验证。

### 4.3 subconverter

subconverter 可按实际部署方式表达。

二进制方式：

```yaml
kind: "binary"
source:
  type: "github_release"
```

容器方式：

```yaml
kind: "container_image"
source:
  type: "oci_registry"
  registry: "docker.io"
  image: "tindy2013/subconverter"
digest: "sha256:<hex>"
```

表达要求：

- 容器镜像必须填写 `digest`；
- 构建阶段使用时，`install_policy.mode` 应为 `build_only`；
- 对外提供 HTTP 服务时，`verification` 应包含健康检查；
- 不得在 `source.url` 中记录订阅 URL。

### 4.4 Docker

Docker 应拆分表达：

- `docker-engine`：Docker Engine 或 Moby 包；
- `docker-cli`：CLI 包；
- `docker-compose-plugin`：Compose 插件；
- `docker-repo-key`：仓库 keyring；
- `docker-rootless-extras`：如启用 rootless 时单独记录。

表达要求：

- `kind` 通常为 `package`；
- `source.type` 可为 `apt` 或 `docker_repo`；
- `version` 使用完整包版本；
- `signature` 记录仓库签名信任链；
- `verification` 包含 `docker version` 或包版本查询；
- 是否启用 Docker 不由本清单决定，本清单只锁定允许版本。

### 4.5 Base image

基础镜像用于构建或运行容器。

表达要求：

- `kind: base_image`；
- `source.type: oci_registry`；
- `version` 写 tag，例如 `22.04` 或 `24.04`；
- `digest` 必填；
- `architecture` 必须匹配构建平台；
- `hold_policy` 至少为 `allow_patch` 或 `hold`；
- digest 变化必须触发重新构建和验证。

### 4.6 运行时依赖

运行时依赖包括 Python、Go、systemd、ca-certificates、openssl、curl、jq 等。

表达要求：

- 项目直接依赖且影响构建/运行行为的依赖应单独列出；
- 操作系统基础依赖可按包组表达，但必须能追溯版本；
- `kind: runtime_dependency`；
- `install_policy.mode` 可为 `managed` 或 `external`；
- `verification` 应说明如何查询版本；
- 不影响行为的传递依赖可由系统包锁文件或镜像 digest 间接覆盖。

### 4.7 规则数据

规则数据包括 geosite、geoip、ASN、直连/代理规则源和自定义规则文件。

表达要求：

- `kind: ruleset`；
- `version` 使用上游版本、commit、日期版本或内容版本；
- `source.type` 可为 `git`、`url` 或 `local`；
- `sha256` 必填；
- `install_policy.mode` 通常为 `build_only` 或 `readonly`；
- `verification` 应包含内容哈希和格式校验；
- 规则顺序仍由 `interfaces/CONTRACTS.md` 中 `rules.yaml` 契约决定，本清单只锁定规则数据来源与版本。

## 5. 多架构与变体

同一组件存在多架构产物时推荐写多个组件条目：

```yaml
components:
  - name: "mihomo-linux-amd64"
    kind: "binary"
    architecture: "linux/amd64"
  - name: "mihomo-linux-arm64"
    kind: "binary"
    architecture: "linux/arm64"
```

如必须保持同一 `name`，可使用 `variants[]`：

```yaml
components:
  - name: "mihomo"
    kind: "binary"
    version: "v1.19.8"
    variants:
      - architecture: "linux/amd64"
        sha256: "<hex>"
        source:
          type: "github_release"
          url: "https://example.invalid/mihomo-linux-amd64.gz"
      - architecture: "linux/arm64"
        sha256: "<hex>"
        source:
          type: "github_release"
          url: "https://example.invalid/mihomo-linux-arm64.gz"
```

约束：安装器必须先选择匹配架构，再执行下载和校验；无匹配架构时必须失败。

## 6. 安全与失败策略

- 清单不得包含 secret、订阅 URL、API token、私钥或带凭据的下载地址；
- 下载、解压、安装、运行时验证任一步失败时，核心组件必须 fail-closed；
- `sha256`、`digest` 和签名校验结果冲突时，必须阻断并记录证据；
- 允许缓存已验证产物，但缓存命中仍必须重新校验内容哈希；
- 组件锁变更必须进入代码评审和发布证据；
- SECURITY 可以因签名缺失、来源不明或供应链风险阻断发布。

## 7. 与其它契约的关系

- Release Manifest 记录某次发布实际包含的文件哈希；
- Component Locks 记录外部组件允许使用的版本、来源和验证方式；
- Desired State 不应直接引用未锁定组件；
- Salt 作业结果应记录安装和验证证据，但不得回传 secret；
- 规则语义、策略组顺序和 Mihomo API 仍以 `interfaces/CONTRACTS.md` 为准。

## 8. 最小有效示例

```yaml
schema_version: "1.0"
generated_at: "2026-06-23T00:00:00Z"
source_git_commit: "<sha>"
components:
  - name: "base-image-ubuntu-24.04"
    kind: "base_image"
    version: "24.04"
    source:
      type: "oci_registry"
      registry: "docker.io"
      image: "library/ubuntu"
    architecture: "linux/amd64"
    sha256: null
    digest: "sha256:<hex>"
    signature:
      type: "none"
      identity: null
      value: null
      certificate_sha256: null
    install_policy:
      mode: "build_only"
      package_manager: "docker"
    hold_policy:
      mode: "allow_patch"
      reason: "基础镜像允许在同一版本线内经验证更新"
    verification:
      required: true
      methods: ["digest"]
      fail_policy: "block_release"
    upgrade_policy:
      channel: "stable"
      strategy: "proposal_only"
      allow_prerelease: false
      requires_security_review: true
      requires_qa_evidence: true
      rollback_to_previous: true
```
