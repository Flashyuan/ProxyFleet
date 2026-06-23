"""ProxyFleet 命令行入口。"""

from __future__ import annotations

import argparse
import sys

from .component_locks import ComponentLockError, assert_valid_lock_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proxyfleet")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_locks = subparsers.add_parser("verify-locks", help="校验组件版本锁定清单")
    verify_locks.add_argument("path", help="组件锁定清单 JSON 文件路径")

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

    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
