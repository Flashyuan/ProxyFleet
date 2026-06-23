# ADR-0005：配置构建与发布所有权

- 状态：Accepted
- 日期：2026-06-22
- 决策者：ARCH-ORCH

## 决策

- 主节点配置源是唯一人工维护入口；
- 最终 `config.yaml`、Provider 和 Rule Provider 自动生成；
- 发布物不可变，并带 revision、Git commit、Mihomo 版本和哈希；
- 所有严格受管节点应用完全相同的发布物；
- 节点选择保存在独立 desired state，不因切换节点重新构建配置；
- ShellCrash adopted 模式下，ProxyFleet 成为最终配置所有者。

## 理由

消除手工漂移，保证可审计、可回滚和多服务器一致性。

## 后果

- 任何直接修改子节点 `config.yaml` 都是 drift；
- ShellCrash compat 模式不能承诺最终配置哈希一致；
- 构建和发布必须验证所有引用和节点唯一性。
