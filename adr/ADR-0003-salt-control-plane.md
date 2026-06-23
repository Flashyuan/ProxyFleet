# ADR-0003：Salt Master/Minion 作为控制平面

- 状态：Accepted
- 日期：2026-06-22
- 决策者：ARCH-ORCH

## 决策

日常控制使用 Salt Master/Minion，不使用 SSH 批量执行，也不自研常驻 Agent 协议。

## 理由

- Minion 主动连接 Master；
- 支持分组、State、Orchestrate、返回结果和离线后 reconcile；
- 避免开发注册、心跳、任务队列和远程执行安全模型；
- 管理入口仍可封装为纯 CLI `fleetctl`。

## 安全约束

- Minion key 必须核验后接受；
- Master 4505/4506 应限制来源；
- 不启用公网 salt-api；
- Master 私钥和 PKI 必须备份；
- Salt 版本锁定 3008.x 明确 point release。

## 后果

所有子节点至少新增一个原生 `salt-minion.service`。
