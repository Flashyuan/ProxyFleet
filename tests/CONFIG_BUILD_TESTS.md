# CONFIG-BUILD / Release Compiler POC 测试要求

> Owner：QA-RELEASE
> 状态：PROPOSED
> 范围：配置构建与 release compiler POC 的最小测试要求
> 契约版本：0.2-draft

## 1. 目标

验证配置源、Provider、策略组、规则、release manifest、组件锁和 Last Known Good
路径在 POC 阶段满足可审计、可回滚、fail-closed 的最低发布门禁。

本文件只定义测试要求，不声明实现已完成，也不替代 `interfaces/CONTRACTS.md`
和 `interfaces/COMPONENT_LOCKS.md`。

## 2. 非目标

- 不测试真实订阅服务的商业可用性；
- 不下载或安装生产 Mihomo / subconverter / Docker 制品；
- 不验证 Salt 远端分发和 Minion 运行态；
- 不把 candidate 组件视为 installable；
- 不放宽缺失 hash、digest 或组件锁时的 fail-closed 规则。

## 3. 输入与前置约束

POC 测试输入至少包含：

- `providers.yaml`：订阅、本地节点和输出路径声明；
- `groups.yaml`：包含受管策略组 `FLEET_PROXY`；
- `rules.yaml`：包含显式顺序的规则列表；
- fixture 订阅或本地节点文件；
- `component-locks.json`；
- 构建输出目录；
- 可比对的上一版 Last Known Good release。

前置约束：

1. 所有输入结构必须包含 `schema_version`。
2. 不支持的 major schema 必须 fail-closed。
3. 所有输出路径必须是 release 目录内相对路径。
4. 日志和错误不得包含订阅 URL、节点密钥、UUID 私密字段或 API secret。
5. 缺少组件锁或锁定材料不足时不得生成可发布 release。

## 4. 测试分层

### 4.1 静态契约测试

验证 schema、字段、引用、路径、组件锁和 manifest 结构，不依赖外部网络。

### 4.2 编译行为测试

使用 fixture 输入执行 release compiler，验证输出文件、顺序、哈希和引用关系。

### 4.3 故障注入测试

向输入注入缺失字段、非法引用、路径逃逸、锁缺失、订阅异常和写入失败，
验证错误路径 fail-closed 且保留诊断信息。

### 4.4 回滚测试

模拟构建失败、校验失败和发布切换失败，验证 Last Known Good 不被覆盖，
且后续恢复仍可验证上一版 release。

## 5. 必测项

### 5.1 Schema 校验

测试要求：

1. `providers.yaml`、`groups.yaml`、`rules.yaml`、`manifest.json`
   都必须校验 `schema_version`。
2. 缺少 `schema_version` 必须失败。
3. 不支持的 major 版本必须失败。
4. 缺少必填字段、未知必填语义或字段类型错误必须失败。
5. 可选字段缺失时只能按契约默认处理，不得用猜测补值。

最小用例：

- `schema-valid-minimal`：最小合法输入可编译；
- `schema-missing-version`：缺少 `schema_version` 被拒绝；
- `schema-unsupported-major`：`2.0` 在未支持时被拒绝；
- `schema-wrong-type`：列表、字符串、布尔类型错误被拒绝。

### 5.2 Provider 引用完整性

测试要求：

1. `providers[].id` 必须唯一。
2. `groups[].use` 中的每个 provider id 必须存在且启用。
3. `rules[].rule_provider` 必须引用存在的规则源或内置匹配语义。
4. 禁止生成悬空 provider、空 provider 文件或无法被 Mihomo 引用的输出。
5. 禁用 provider 不得被 `FLEET_PROXY` 引用。

最小用例：

- `provider-valid-reference`：合法 provider 被策略组引用并生成输出；
- `provider-duplicate-id`：重复 id 被拒绝；
- `provider-missing-reference`：策略组引用不存在 id 被拒绝；
- `provider-disabled-reference`：引用禁用 provider 被拒绝。

### 5.3 `FLEET_PROXY` 受管策略组

测试要求：

1. `FLEET_PROXY` 必须存在。
2. `FLEET_PROXY` 必须是可选择组。
3. `FLEET_PROXY.use` 必须覆盖所有受管 provider。
4. compiler 不得改名、删除或拆分 `FLEET_PROXY`。
5. 节点切换语义不得要求重新生成 `config.yaml`。

最小用例：

- `fleet-proxy-valid`：合法组生成 Mihomo 可识别的 select 组；
- `fleet-proxy-missing`：缺少受管组被拒绝；
- `fleet-proxy-wrong-type`：非可选择组被拒绝；
- `fleet-proxy-provider-gap`：受管 provider 未进入 use 列表被拒绝。

### 5.4 规则顺序

测试要求：

1. `rules.yaml` 中 `order` 的顺序是语义，compiler 不得重排。
2. `MATCH` 兜底规则必须保持在显式规则之后。
3. 指向 `FLEET_PROXY`、`DIRECT` 或其他目标组的规则必须保持原目标。
4. 重复规则只能按契约允许的方式保留或拒绝，不得静默去重改变语义。
5. 输出规则文件和 manifest 记录必须能证明顺序未变。

最小用例：

- `rules-order-preserved`：输出顺序与输入顺序一致；
- `rules-match-not-promoted`：`MATCH` 不会被提前；
- `rules-target-preserved`：目标组不被改写；
- `rules-duplicate-explicit`：重复规则行为有明确失败或保留证据。

### 5.5 Manifest Hash

测试要求：

1. `manifest.json` 必须记录 release 内每个发布文件的 `path`、`sha256`、`size`。
2. hash 必须基于最终写入内容计算。
3. manifest 记录路径必须是 release 内相对路径。
4. manifest 写入后不得再修改被记录文件。
5. `manifest.sha256` 必须能校验 `manifest.json` 本身。
6. 任一文件 hash 或 size 不匹配时不得发布。

最小用例：

- `manifest-hash-valid`：所有输出文件 hash 可复算；
- `manifest-detects-content-change`：篡改输出文件后校验失败；
- `manifest-detects-size-change`：size 不匹配被拒绝；
- `manifest-self-hash-valid`：`manifest.sha256` 可校验 manifest。

### 5.6 路径逃逸

测试要求：

1. provider output、local source、rule output、manifest path 都不得逃逸工作目录或 release 目录。
2. 必须拒绝 `../`、绝对路径、空路径、控制字符路径和符号链接逃逸。
3. 路径规范化后仍必须位于允许目录内。
4. 失败时不得创建逃逸目标文件。

最小用例：

- `path-relative-valid`：合法相对路径可写入；
- `path-parent-escape`：`../outside.yaml` 被拒绝；
- `path-absolute-escape`：绝对路径被拒绝；
- `path-symlink-escape`：符号链接指向 release 外被拒绝。

### 5.7 缺少组件锁

测试要求：

1. compiler 必须读取 `component-locks.json` 或等价锁定输入。
2. 缺少锁文件必须 fail-closed。
3. 缺少 Mihomo、subconverter、规则数据或基础镜像锁定项时必须失败。
4. `installable` 组件缺少 SHA-256、digest 或签名材料时必须失败。
5. `candidate` 或 `planned` 组件不得被当作可发布 release 依赖。

最小用例：

- `locks-valid`：完整锁定输入允许进入构建；
- `locks-file-missing`：锁文件缺失被拒绝；
- `locks-component-missing`：关键组件缺失被拒绝；
- `locks-candidate-used`：candidate 被用于发布时被拒绝。

### 5.8 错误路径

测试要求：

1. 所有可恢复错误必须返回可定位错误码和脱敏摘要。
2. 不可恢复错误必须 fail-fast，不得继续生成半成品 release。
3. 失败后不得覆盖 Last Known Good。
4. 失败后必须保留足够诊断证据，包括输入摘要、阶段、错误码和输出目录状态。
5. 错误日志不得泄露 secret、订阅 URL 或节点凭据。

最小用例：

- `error-subscription-unavailable`：订阅不可达进入失败路径；
- `error-subconverter-invalid-output`：转换输出非法被拒绝；
- `error-manifest-write-failed`：manifest 写入失败不发布；
- `error-partial-output-cleanup`：半成品不会被标记为 release；
- `error-redaction`：错误摘要完成脱敏。

### 5.9 Last Known Good

测试要求：

1. 成功发布前必须存在可识别的当前 release 状态。
2. 新 release 只有在 manifest 校验、文件 hash 校验和编译验证全部通过后，
   才能替换 Last Known Good 指针。
3. 构建失败、校验失败、原子切换失败均不得覆盖 Last Known Good。
4. 回滚后必须重新验证上一版 manifest 和文件 hash。
5. Last Known Good 必须记录 release revision、provider revision、source git commit
   和 `FLEET_PROXY` 当前选择。

最小用例：

- `lkg-preserved-on-build-failure`：构建失败保留上一版；
- `lkg-preserved-on-hash-failure`：hash 失败保留上一版；
- `lkg-updated-after-success`：成功发布后更新指针；
- `lkg-rollback-validates-manifest`：回滚后复验上一版 manifest。

## 6. 发布阻断条件

任一条件成立时，QA-RELEASE 必须标记 `RELEASE_BLOCKED`：

1. schema 校验缺失或存在未知 major 仍继续构建；
2. `FLEET_PROXY` 缺失、类型错误或 provider 覆盖不完整；
3. provider、rule provider 或 manifest 出现悬空引用；
4. 规则顺序被 compiler 静默重排；
5. manifest hash、size 或自哈希无法复算；
6. 任一路径可逃逸 release 目录；
7. 缺少组件锁或使用未达到 installable 条件的组件；
8. 错误路径静默吞没异常、泄露 secret 或生成半成品 release；
9. 失败发布覆盖或破坏 Last Known Good；
10. 测试证据无法关联 Task/Result。

## 7. 最小证据要求

每次 CONFIG-BUILD POC 测试 Result 至少记录：

- Task ID；
- 输入 fixture 名称和摘要；
- compiler 命令摘要；
- 输出 release 目录摘要；
- manifest 校验结果；
- 组件锁校验结果；
- Last Known Good 更新或保留证据；
- 失败用例的错误码、脱敏错误摘要和日志位置；
- `git status --short`；
- 是否设置 `RELEASE_BLOCKED`。

## 8. 完成标准

CONFIG-BUILD / release compiler POC 进入下一阶段前必须满足：

1. 本文件所有必测项均有自动化测试或明确的人工验证证据；
2. 成功路径可生成可复算 hash 的 release manifest；
3. 失败路径覆盖 schema、引用、路径、组件锁、manifest 和 Last Known Good；
4. 测试结果已写入 Result Packet；
5. QA-RELEASE 与 SECURITY 均未设置 `RELEASE_BLOCKED`。
