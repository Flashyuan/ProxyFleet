# ADR-0001：平台与核心技术栈

- 状态：Accepted
- 日期：2026-06-22
- 决策者：ARCH-ORCH

## 背景

受管服务器统一为 Ubuntu 22.04/24.04，需要无 Web、可批量管理、统一配置、可兼容现有 ShellCrash/Mihomo。

## 决策

- Ubuntu 22.04 为主要基线，24.04 为兼容基线；
- Salt 3008 LTS 作为控制平面；
- Mihomo 作为统一数据面；
- subconverter/项目构建器只在主节点构建阶段使用；
- Git 保存配置源、决策和工程状态。

## 理由

Salt 提供成熟 Master/Minion、State、目标分组和远程结果；Mihomo 提供 Provider、Rule、TUN 和本地 API；两者避免自研控制协议和代理核心。

## 后果

- Salt Master 成为高信任基础设施；
- 子节点必须安装 Salt Minion；
- 需要锁定 Salt/Mihomo/subconverter 版本；
- 需要分别处理原生 Mihomo 和 ShellCrash/Mihomo 驱动。
