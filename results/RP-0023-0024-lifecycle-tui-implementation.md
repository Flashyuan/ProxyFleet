# Result Packet: RP-0023-0024 生命周期与 TUI 实现

> Task ID：TP-0023 / TP-0024
> Owner role：CONTROL-SALT / DATA-MIHOMO / PRODUCT-SPEC
> Reviewer role：QA-RELEASE / SECURITY
> 日期：2026-06-25

## 1. 完成内容

- `scripts/proxyfleet-minion.sh`
  - 默认 `start/stop/restart/uninstall` 只控制 `salt-minion`；
  - 新增 `--with-mihomo` 联动语义；
  - 新增 `mihomo-start/stop/restart/status/uninstall`；
  - Mihomo 操作前校验 ProxyFleet unit、ExecStart、组件锁、receipt 和受管配置；
  - `mihomo-uninstall` 支持默认保留、`--purge-managed`、
    `--purge-all --yes`、`--purge-local-override`。
- `scripts/proxyfleet-master.sh`
  - `select-sync` 默认进入实时 TUI；
  - `--live-health` 保留为兼容别名；
  - `--refresh-health` / `--no-health-cache` 保留兼容但帮助标记 deprecated；
  - 默认检测 `config-src/port-policy.yaml`，存在时同步 managed 端口白名单。
- `src/proxyfleet/live_select.py`
  - TUI 增加标题栏、状态栏、搜索栏、节点表格、图例和帮助栏；
  - 显示当前选择、无选择、API 不可达和 desired/API drift；
  - 显示端口白名单状态；
  - 保持后台并发动态刷新节点延迟。
- `src/proxyfleet/cli.py`
  - `live-select` 增加 `--desired-path`、`--release-label`、
    `--target-label`、`--port-policy-status`。
- 新增/更新测试：
  - `tests/test_minion_script.py`
  - `tests/test_live_select.py`
  - `tests/test_security_contracts.py`

## 2. 未完成内容

- 真实 Ubuntu Minion smoke 尚未执行；
- 生产端口白名单落地后端 UFW/nftables 仍未实现。

## 3. 事实标签

- VERIFIED-TEST：全量单元/伪终端测试 118 项通过；
- VERIFIED-TEST：`bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh` 通过；
- VERIFIED-TEST：`python3 -m py_compile src/proxyfleet/*.py salt/modules/proxyfleet_mihomo.py` 通过；
- VERIFIED-TEST：`PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json` 通过；
- VERIFIED-TEST：`git diff --check` 通过；
- OBSERVED：测试过程中出现 Python ResourceWarning，但不影响测试通过。

## 4. 修改文件

- `scripts/proxyfleet-master.sh`
- `scripts/proxyfleet-minion.sh`
- `src/proxyfleet/cli.py`
- `src/proxyfleet/live_select.py`
- `tests/test_live_select.py`
- `tests/test_minion_script.py`
- `tests/test_security_contracts.py`
- `PROJECT_STATE.md`
- `PLAN.md`
- `interfaces/CONTRACTS.md`
- `interfaces/MIHOMO_DRIVER.md`
- `tests/TEST_MATRIX.md`
- `docs/INSTALL_MASTER.md`
- `docs/INSTALL_MINION.md`
- `docs/OPERATIONS.md`
- `docs/USER_MANUAL.md`

## 5. 测试命令

```bash
bash -n scripts/proxyfleet-master.sh scripts/proxyfleet-minion.sh
PYTHONPATH=src python3 -m py_compile src/proxyfleet/*.py salt/modules/proxyfleet_mihomo.py
PYTHONPATH=src python3 -m unittest tests.test_minion_script -v
PYTHONPATH=src python3 -m unittest tests.test_live_select -v
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m proxyfleet.cli verify-locks component-locks.json
git diff --check
```

## 6. 风险与后续

- 真实 Minion smoke 需要在生产窗口执行，避免误停代理服务；
- `--refresh-health` / `--no-health-cache` 仍保留兼容入口，后续可按 deprecation 周期移除；
- `mihomo-uninstall --purge-all --yes --purge-local-override` 是危险操作，文档和脚本均要求显式参数。
