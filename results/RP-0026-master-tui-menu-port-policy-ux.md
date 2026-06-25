# Result Packet: RP-0026 Master TUI 菜单与端口白名单 UX

> Task ID：TP-0026
> Owner role：PRODUCT-SPEC / OPS-PLATFORM
> Reviewer role：QA-RELEASE / SECURITY
> 日期：2026-06-25

## 1. 完成内容

- Master TUI 主菜单从 12 个平铺选项简化为 4 个父级入口：
  `安装相关`、`Master 节点相关`、`节点配置相关`、`服务相关`；
- 原有预检、安装、key 管理、订阅、导入、release、同步、服务控制和卸载功能
  移入对应子菜单；
- `配置端口白名单` 从打开编辑器改为输入一个或多个端口号，脚本自动写入
  `config-src/port-policy.yaml`；
- 支持空格或逗号分隔端口，例如 `7890, 7891 9090`；
- 端口白名单写入前展示预览并要求 `WRITE` 确认；
- TUI 和文档明确 Salt Master 的 TCP `4505/4506` 只在配置 Master 入站防火墙时
  必须放行给 Minion，通常不应默认下发到所有 Minion 的端口白名单。

## 2. 未完成内容

- 未实现 UFW/nftables 实际防火墙落地后端；
- 未把 Minion TUI 菜单做同等信息架构重排。

## 3. 测试和证据

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

结果：128 项通过。

```bash
bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh
python3 -m py_compile src/proxyfleet/*.py salt/modules/proxyfleet_mihomo.py
PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json
git diff --check
```

结果：通过。

## 4. 修改文件

- `scripts/proxyfleet-master.sh`
- `tests/test_master_script.py`
- `docs/INSTALL_MASTER.md`
- `docs/OPERATIONS.md`
- `docs/USER_MANUAL.md`
- `PROJECT_STATE.md`

## 5. 风险

- 端口策略文件仍是 JSON 语法的 YAML 子集；文档已同步真实可用示例；
- Salt `4505/4506` 是否加入白名单取决于用户配置的是 Master 入站防火墙还是
  Minion 下发策略，不能无条件自动加入。
