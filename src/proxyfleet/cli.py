"""ProxyFleet 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .component_locks import ComponentLockError, assert_valid_lock_file
from .config_build import BuildOptions, ConfigBuildError, build_release, verify_release
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

    verify_release_parser = subparsers.add_parser("verify-release", help="校验 release manifest 文件哈希")
    verify_release_parser.add_argument("release_dir", help="release 目录")

    subscription_status = subparsers.add_parser("subscription-status", help="解析 Subscription-Userinfo 并输出状态 JSON")
    subscription_status.add_argument("--provider-id", default="provider", help="Provider ID")
    subscription_status.add_argument("--header", default=None, help="Subscription-Userinfo 头内容")
    subscription_status.add_argument("--body-file", default=None, help="订阅正文文件；省略时使用占位正文")

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

    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
