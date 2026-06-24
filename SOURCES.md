# 官方证据索引

> 更新日期：2026-06-23
> 规则：只登记用于架构决策的官方文档、官方仓库或项目官方发布页。外部事实引用必须写明用途和访问日期。

## Salt

1. Salt version support lifecycle
   https://docs.saltproject.io/salt/install-guide/en/latest/topics/salt-version-support-lifecycle.html
   用途：确认 Salt 3008 LTS 于 2026-05-27 发布，支持周期及生产优先使用 LTS。访问：2026-06-22。

2. Salt Linux DEB install guide
   https://docs.saltproject.io/salt/install-guide/en/latest/topics/install-by-operating-system/linux-deb.html
   用途：Ubuntu/Debian 安装、3008 LTS pin、官方 DEB 包和 point release 锁定。访问：2026-06-22。

3. Salt Minion configuration
   https://docs.saltproject.io/en/master/ref/configuration/minion.html
   用途：Minion 主动连接 Master、master 配置和多 Master 能力。访问：2026-06-22。

4. Salt in 10 Minutes
   https://docs.saltproject.io/en/3006/topics/tutorials/walkthrough.html
   用途：Master/Minion 模型、4505/4506、key 指纹核验。访问：2026-06-22。

5. saltstack/salt Docker Hub image
   https://hub.docker.com/r/saltstack/salt
   用途：官方页面警告该容器不受官方支持，且公开标签较旧；支持自建 3008 镜像的决策。访问：2026-06-22。

## Mihomo

6. Mihomo TUN documentation
   https://wiki.metacubex.one/en/config/inbound/tun/
   用途：auto-route、auto-redirect、nftables/iptables、route exclude 等宿主机网络行为。访问：2026-06-22。

7. Mihomo systemd service
   https://wiki.metacubex.one/en/startup/service/
   用途：原生 systemd 运行、能力、重载和日志。访问：2026-06-22。

8. Mihomo API
   https://wiki.metacubex.one/en/api/
   用途：策略组选择、单节点 delay、Provider healthcheck、Provider 更新、配置重载、状态验证和连接操作。访问：2026-06-22；节点测速规划复核访问：2026-06-24。

9. Mihomo proxy-providers health check
   https://wiki.metacubex.one/en/config/proxy-providers/
   用途：确认 Proxy Provider health-check 的 URL、interval、timeout 等测速/健康检查配置项。访问：2026-06-24。

10. Salt Project DEB packages repository
    https://docs.saltproject.io/salt/install-guide/en/latest/topics/install-by-operating-system/linux-deb.html
    用途：确认 Salt DEB 官方仓库位于 `https://packages.broadcom.com/artifactory/saltproject-deb/`，并确认可安装精确版本 `3008.1`；项目脚本直接写固定仓库地址，不使用 `releases/latest/download/salt.sources`。访问：2026-06-24。

11. MetaCubeX/mihomo v1.19.27 release assets
    https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.27
    用途：锁定 Mihomo `linux-amd64` 与 `linux-arm64` gzip 资产 URL 和 SHA-256。访问：2026-06-24。

## Docker

10. Docker host network driver
   https://docs.docker.com/engine/network/drivers/host/
   用途：Linux host network 的能力和隔离权衡。访问：2026-06-22。

11. Docker Compose services reference
    https://docs.docker.com/reference/compose-file/services/
    用途：network_mode、ports、capabilities 和设备配置。访问：2026-06-22。

12. Docker Compose trust model
    https://docs.docker.com/compose/trust-model/
    用途：privileged、cap_add、host network、devices、bind mounts 的宿主机风险。访问：2026-06-22。

13. Docker Engine container run
    https://docs.docker.com/engine/containers/run/
    用途：镜像 digest、挂载和容器隔离基本模型。访问：2026-06-22。

## Git / 远端认证

14. Git `git-init` documentation
    https://git-scm.com/docs/git-init
    用途：确认 `git init`、`--initial-branch/-b` 和已有仓库安全重初始化语义。访问：2026-06-23。

15. Git `git-config` documentation
    https://git-scm.com/docs/git-config
    用途：确认 `user.name`/`user.email` 是 commit author/committer 元数据，与认证凭据区分。访问：2026-06-23。

16. Git `git-push` documentation
    https://git-scm.com/docs/git-push
    用途：upstream、非 fast-forward 拒绝、force 风险和远端更新语义。访问：2026-06-23。

17. Git `git-fetch` documentation
    https://git-scm.com/docs/git-fetch
    用途：在写远端前获取和比较 remote refs。访问：2026-06-23。

18. Git `git-status` documentation
    https://git-scm.com/docs/git-status
    用途：使用稳定 porcelain 格式记录和解析工作树状态。访问：2026-06-23。

19. GitHub authentication overview（仅适用于远端为 GitHub 时）
    https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github
    用途：HTTPS token/credential helper 与 SSH key 认证方式；说明账号名/邮箱不足以完成 push。访问：2026-06-23。

## 证据状态

- 上述资料证明组件具备相应基础能力；
- 它们不证明 ProxyFleet 已实现任何功能；
- ProxyFleet 的实现事实必须由本仓库代码和测试证明。
