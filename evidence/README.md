# Evidence 目录

保存可复现测试输出、环境清单、脱敏日志、截图、哈希清单和 Git 操作证据。

规则：

- 不保存 secrets；
- 文件名包含 Task/Result ID；
- 每个 Result 引用具体 evidence 路径；
- 外部官方事实登记到 `SOURCES.md`；
- Git evidence 可包含脱敏的 status、log、remote refs、commit SHA 和 push 输出；
- 不保存带凭据 remote URL、token、SSH 私钥或 credential helper 数据；
- 大文件可存外部制品库，但必须记录不可变 URI 和 SHA-256。
