"""ProxyFleet 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .component_locks import ComponentLockError, assert_valid_lock_file
from .config_build import BuildOptions, ConfigBuildError, build_release, verify_release
from .fleet import (
    FleetError,
    MihomoClient,
    build_desired_state,
    build_node_catalog,
    build_sync_plan,
    load_desired_state,
    prepare_salt_publish,
    run_salt_sync,
    select_node,
    write_desired_state,
    write_node_catalog,
)
from .subscription import SubscriptionError, build_subscription_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proxyfleet")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_locks = subparsers.add_parser("verify-locks", help="校验组件版本锁定清单")
    verify_locks.add_argument("path", help="组件锁定清单 JSON 文件路径")

    build_release_parser = subparsers.add_parser("build-release", help="构建本地 release POC")
    build_release_parser.add_argument("source_dir", help="配置源目录")
    build_release_parser.add_argument("output_dir", help="release 输出根目录")
    build_release_parser.add_argument("--revision", type=int, required=True, help="release revision")
    build_release_parser.add_argument("--source-git-commit", required=True, help="源 Git commit")
    build_release_parser.add_argument("--component-locks", default="component-locks.json", help="组件锁定清单")
    build_release_parser.add_argument("--subscription-cache", default=None, help="订阅 Last Known Good 缓存目录")
    build_release_parser.add_argument("--subscription-timeout", type=float, default=10.0, help="订阅 HTTP 超时秒数")

    verify_release_parser = subparsers.add_parser("verify-release", help="校验 release manifest 文件哈希")
    verify_release_parser.add_argument("release_dir", help="release 目录")

    subscription_status = subparsers.add_parser("subscription-status", help="解析 Subscription-Userinfo 并输出状态 JSON")
    subscription_status.add_argument("--provider-id", default="provider", help="Provider ID")
    subscription_status.add_argument("--header", default=None, help="Subscription-Userinfo 头内容")
    subscription_status.add_argument("--body-file", default=None, help="订阅正文文件；省略时使用占位正文")

    nodes = subparsers.add_parser("nodes", help="查看 release 内可选代理节点")
    nodes.add_argument("release_dir", help="release 目录")
    nodes.add_argument("--health-cache", default=None, help="可选：合并节点健康缓存 JSON")
    nodes.add_argument("--write-catalog", action="store_true", help="写入 release/node-catalog.json")

    health = subparsers.add_parser("health-check", help="刷新节点测速缓存")
    health.add_argument("release_dir", help="release 目录")
    health.add_argument("health_cache", help="健康缓存 JSON 输出路径")
    health.add_argument("--mihomo-api", required=True, help="本机 Mihomo API，例如 http://127.0.0.1:9090")
    health.add_argument("--mihomo-secret", default=None, help="Mihomo API secret")
    health.add_argument("--node-id", default=None, help="只测速指定稳定 node_id")
    health.add_argument("--all", action="store_true", help="测速 release 内全部节点")
    health.add_argument("--url", default="https://www.gstatic.com/generate_204", help="健康检查 URL")
    health.add_argument("--timeout-ms", type=int, default=3000, help="单节点测速超时")

    select = subparsers.add_parser("select-node", help="选择代理节点并写入 desired state")
    select.add_argument("release_dir", help="release 目录")
    select.add_argument("runtime_dir", help="runtime 目录")
    select.add_argument("--node-id", required=True, help="稳定 node_id")
    select.add_argument("--target-group", default="production", help="目标分组")
    select.add_argument("--connection-policy", default="preserve", choices=["preserve"], help="连接处理策略")
    select.add_argument("--mihomo-api", default=None, help="可选：本机 Mihomo API，例如 http://127.0.0.1:9090")
    select.add_argument("--mihomo-secret", default=None, help="可选：Mihomo API secret；不会写入 desired state")

    desired = subparsers.add_parser("desired-status", help="查看 desired state")
    desired.add_argument("desired_path", help="desired.yaml 路径")

    publish = subparsers.add_parser("publish-salt", help="复制 release/desired 到 Salt file_roots")
    publish.add_argument("release_dir", help="release 目录")
    publish.add_argument("desired_path", help="desired.yaml 路径")
    publish.add_argument("salt_root", help="Salt file_roots 根目录")
    publish.add_argument("--component-locks", default="component-locks.json", help="组件锁定清单")

    sync = subparsers.add_parser("sync", help="通过 Salt 同步 release 并应用节点选择")
    sync.add_argument("release_dir", help="release 目录")
    sync.add_argument("desired_path", help="desired.yaml 路径")
    sync.add_argument("salt_root", help="Salt file_roots 根目录")
    sync.add_argument("--target", default="*", help="Salt target")
    sync.add_argument("--salt-bin", default="salt", help="salt 命令路径")
    sync.add_argument("--dry-run", action="store_true", help="只输出同步计划，不执行 Salt")

    apply_parser = subparsers.add_parser("apply", help="最少步骤：构建、可选选择、发布并同步")
    apply_parser.add_argument("source_dir", help="配置源目录")
    apply_parser.add_argument("output_dir", help="release 输出根目录")
    apply_parser.add_argument("runtime_dir", help="runtime 目录")
    apply_parser.add_argument("salt_root", help="Salt file_roots 根目录")
    apply_parser.add_argument("--revision", type=int, required=True, help="release revision")
    apply_parser.add_argument("--source-git-commit", required=True, help="源 Git commit")
    apply_parser.add_argument("--component-locks", default="component-locks.json", help="组件锁定清单")
    apply_parser.add_argument("--subscription-cache", default=None, help="订阅 Last Known Good 缓存目录")
    apply_parser.add_argument("--subscription-timeout", type=float, default=10.0, help="订阅 HTTP 超时秒数")
    apply_parser.add_argument("--select", dest="node_id", default=None, help="可选：构建后选择 node_id")
    apply_parser.add_argument("--target-group", default="production", help="目标分组")
    apply_parser.add_argument("--target", default="*", help="Salt target")
    apply_parser.add_argument("--salt-bin", default="salt", help="salt 命令路径")
    apply_parser.add_argument("--dry-run", action="store_true", help="只输出计划，不写 runtime/Salt、不执行 Salt")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "verify-locks":
        try:
            assert_valid_lock_file(args.path)
        except ComponentLockError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print("组件锁定清单校验通过")
        return 0

    if args.command == "build-release":
        try:
            release_dir = build_release(
                BuildOptions(
                    source_dir=Path(args.source_dir),
                    output_dir=Path(args.output_dir),
                    revision=args.revision,
                    source_git_commit=args.source_git_commit,
                    component_locks=Path(args.component_locks),
                    cache_dir=Path(args.subscription_cache) if args.subscription_cache else None,
                    subscription_timeout=args.subscription_timeout,
                )
            )
        except (ComponentLockError, ConfigBuildError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"release 构建完成: {release_dir}")
        return 0

    if args.command == "verify-release":
        try:
            verify_release(Path(args.release_dir))
        except ConfigBuildError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print("release 校验通过")
        return 0

    if args.command == "subscription-status":
        try:
            body = Path(args.body_file).read_bytes() if args.body_file else b"proxy-provider-placeholder\n"
            status = build_subscription_status(args.provider_id, args.header, body)
        except SubscriptionError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(status.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "nodes":
        try:
            health_cache = Path(args.health_cache) if args.health_cache else None
            nodes = [entry.to_dict() for entry in build_node_catalog(Path(args.release_dir), health_cache)]
            payload = {"schema_version": "1.0", "nodes": nodes}
            if args.write_catalog:
                payload["catalog_path"] = str(write_node_catalog(Path(args.release_dir)))
        except FleetError as exc:
            print(f"{exc.error_code}: {exc.message}", file=sys.stderr)
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "health-check":
        try:
            nodes = build_node_catalog(Path(args.release_dir))
            if not args.all and not args.node_id:
                raise FleetError("E_NODE_NOT_FOUND", "必须指定 --node-id 或 --all")
            selected = nodes if args.all else [next((node for node in nodes if node.node_id == args.node_id), None)]
            if selected == [None]:
                raise FleetError("E_NODE_NOT_FOUND", f"未知 node_id: {args.node_id}")
            client = MihomoClient(args.mihomo_api, args.mihomo_secret)
            cache: dict[str, object] = {"schema_version": "1.0", "nodes": {}}
            for node in selected:
                assert node is not None
                try:
                    health = client.health_check(node.mihomo_name, args.url, args.timeout_ms)
                    cache["nodes"][node.node_id] = {
                        "last_delay_ms": health["last_delay_ms"],
                        "health_status": "ok",
                        "measured_at": health["measured_at"],
                        "freshness": "fresh",
                        "last_error_code": None,
                    }
                except FleetError as exc:
                    cache["nodes"][node.node_id] = {
                        "last_delay_ms": None,
                        "health_status": "timeout" if exc.error_code == "E_HEALTHCHECK_TIMEOUT" else "failed",
                        "measured_at": None,
                        "freshness": "fresh",
                        "last_error_code": exc.error_code,
                    }
            path = Path(args.health_cache)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except FleetError as exc:
            print(f"{exc.error_code}: {exc.message}", file=sys.stderr)
            return 2
        print(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "select-node":
        try:
            if args.mihomo_api:
                desired = build_desired_state(
                    Path(args.release_dir),
                    Path(args.runtime_dir),
                    node_id=args.node_id,
                    target_group=args.target_group,
                    connection_policy=args.connection_policy,
                )
                MihomoClient(args.mihomo_api, args.mihomo_secret).select_node(
                    desired["managed_policy_group"],
                    desired["selected_mihomo_name"],
                )
                write_desired_state(Path(args.runtime_dir) / "desired.yaml", desired)
            else:
                desired = select_node(
                    Path(args.release_dir),
                    Path(args.runtime_dir),
                    node_id=args.node_id,
                    target_group=args.target_group,
                    connection_policy=args.connection_policy,
                )
        except FleetError as exc:
            print(f"{exc.error_code}: {exc.message}", file=sys.stderr)
            return 2
        print(json.dumps(desired, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "desired-status":
        try:
            desired = load_desired_state(Path(args.desired_path))
        except FleetError as exc:
            print(f"{exc.error_code}: {exc.message}", file=sys.stderr)
            return 2
        print(json.dumps(desired, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "publish-salt":
        try:
            plan = prepare_salt_publish(Path(args.release_dir), Path(args.desired_path), Path(args.salt_root), Path(args.component_locks))
        except FleetError as exc:
            print(f"{exc.error_code}: {exc.message}", file=sys.stderr)
            return 2
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "sync":
        try:
            plan = build_sync_plan(Path(args.release_dir), Path(args.desired_path), Path(args.salt_root), args.target)
            if args.dry_run:
                payload = {"dry_run": True, "plan": plan.to_dict()}
                print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
                return 0
            rc = run_salt_sync(plan, args.salt_bin)
        except FleetError as exc:
            print(f"{exc.error_code}: {exc.message}", file=sys.stderr)
            return 2
        if rc != 0:
            print(f"Salt 同步失败，退出码: {rc}", file=sys.stderr)
            return rc
        print(json.dumps({"status": "success", "plan": plan.to_dict()}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "apply":
        try:
            release_path = Path(args.output_dir) / f"{args.revision:06d}"
            plan_payload = {
                "source_dir": args.source_dir,
                "release_dir": str(release_path),
                "runtime_dir": args.runtime_dir,
                "salt_root": args.salt_root,
                "target": args.target,
                "selected_node_id": args.node_id,
            }
            if args.dry_run:
                print(json.dumps({"dry_run": True, "plan": plan_payload}, ensure_ascii=False, indent=2, sort_keys=True))
                return 0
            release_dir = build_release(
                BuildOptions(
                    source_dir=Path(args.source_dir),
                    output_dir=Path(args.output_dir),
                    revision=args.revision,
                    source_git_commit=args.source_git_commit,
                    component_locks=Path(args.component_locks),
                    cache_dir=Path(args.subscription_cache) if args.subscription_cache else None,
                    subscription_timeout=args.subscription_timeout,
                )
            )
            desired_path = Path(args.runtime_dir) / "desired.yaml"
            if args.node_id:
                desired = select_node(release_dir, Path(args.runtime_dir), args.node_id, args.target_group)
            elif desired_path.exists():
                desired = load_desired_state(desired_path)
            else:
                raise FleetError("E_NODE_NOT_FOUND", "未指定 --select，且 runtime/desired.yaml 不存在")
            publish_plan = prepare_salt_publish(release_dir, desired_path, Path(args.salt_root), Path(args.component_locks))
            sync_plan = build_sync_plan(release_dir, desired_path, Path(args.salt_root), args.target)
            rc = run_salt_sync(sync_plan, args.salt_bin)
        except (ComponentLockError, ConfigBuildError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except FleetError as exc:
            print(f"{exc.error_code}: {exc.message}", file=sys.stderr)
            return 2
        if rc != 0:
            print(f"Salt 同步失败，退出码: {rc}", file=sys.stderr)
            return rc
        print(json.dumps({"status": "success", "desired": desired, "publish": publish_plan.to_dict(), "sync": sync_plan.to_dict()}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
