# Result Packet — RP-0014

- Related task: TP-0014
- Owner role: CONTROL-SALT
- Status: PARTIAL
- Completed at: 2026-06-23
- Contract version: 0.2-draft

## Outcome

已新增 Master/Minion 原生安装和启停卸载脚本，并提供中文安装配置文档。由于安装 Salt、写 `/etc/salt` 和启停 systemd 属于环境写操作，本结果未执行安装，等待用户二次确认。

## Completed

- 新增 `scripts/proxyfleet-master.sh`；
- 新增 `scripts/proxyfleet-minion.sh`；
- 新增 `docs/INSTALL_MASTER.md`；
- 新增 `docs/INSTALL_MINION.md`；
- 新增 `docs/OPERATIONS.md`；
- 新增 TP-0014 Task Packet。

## Not completed

- 未执行 `sudo scripts/proxyfleet-master.sh install`；
- 未安装 Salt Master；
- 未验证 TCP 4505/4506 实际监听；
- 未接入真实 Minion；
- 未接受 Minion key。

## Facts and confidence

| Claim | Label | Evidence |
|---|---|---|
| 当前机器是 Ubuntu 22.04.5 LTS | OBSERVED | `/etc/os-release` |
| 当前用户属于 sudo 组 | OBSERVED | `id` |
| 脚本固定 Salt 3008.1 并安装后 hold | VERIFIED-TEST | 脚本静态检查 |
| 脚本不自动接受 Minion key | VERIFIED-TEST | 脚本静态检查 |

## Files changed

- `scripts/proxyfleet-master.sh`
- `scripts/proxyfleet-minion.sh`
- `docs/INSTALL_MASTER.md`
- `docs/INSTALL_MINION.md`
- `docs/OPERATIONS.md`
- `tasks/TP-0014-salt-install-scripts.md`
- `results/RP-0014-salt-install-scripts.md`

## Tests/evidence

```text
bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh
exit 0

scripts/proxyfleet-master.sh preflight
OS: Ubuntu 22.04.5 LTS
Salt target version: 3008.1
Project root: /home/terence/project/ProxyFleet
systemd: systemd 249 (249.11-0ubuntu3.21)
sudo: /usr/bin/sudo

scripts/proxyfleet-minion.sh preflight
OS: Ubuntu 22.04.5 LTS
Salt target version: 3008.1
systemd: systemd 249 (249.11-0ubuntu3.21)
sudo: /usr/bin/sudo

PYTHONPATH=src python3 -m unittest discover -s tests
Ran 24 tests in 0.098s
OK

PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json
组件锁定清单校验通过

git diff --check
exit 0
```

## Git evidence

```text
repository_path: /home/terence/project/ProxyFleet
branch: main
base_commit: 01bad9e1fa8a4f06061053646a7a561c73efab31
new_commit: PENDING
upstream_ref: origin/main
remote_url_redacted: ssh://git@ssh.github.com:443/Flashyuan/ProxyFleet.git
remote_head_before: 01bad9e1fa8a4f06061053646a7a561c73efab31
remote_head_after: PENDING
push_status: not-attempted
worktree_status: dirty-explained (TP-0014 scripts/docs)
```

## Risks and regressions

- 官方 Salt DEB 包完整版本字符串需在 `apt-cache policy` 中实际确认；
- 脚本会写系统目录，执行前需要用户二次确认；
- 防火墙/云安全组不由脚本自动修改，需要运维侧限制 4505/4506 来源。

## Decisions requested

- 是否现在执行 Master 安装脚本配置当前机器。

## Handoffs

- SECURITY：复核 Salt key、PKI 保留和端口暴露；
- QA-RELEASE：复核 dry-run、syntax 和安装证据；
- OPS-PLATFORM：复核 systemd 和卸载语义。

## Next atomic action

运行脚本语法和 preflight 验证；经用户二次确认后执行 Master 安装。
