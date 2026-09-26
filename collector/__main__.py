"""Manual collector runner: python -m collector <name> [--write]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .base import REPO_ROOT, CollectorError, discover


def main(argv=None):
    registry = discover()
    parser = argparse.ArgumentParser(
        prog="python -m collector",
        description="Fetch provider data and merge it into data/ (manual, never commits).",
    )
    parser.add_argument("name", nargs="?", choices=sorted(registry),
                        help="collector to run")
    parser.add_argument("--list", action="store_true",
                        help="list available collectors")
    parser.add_argument("--write", action="store_true",
                        help="write files (default: dry run)")
    parser.add_argument("--root", default=None, help="repository root")
    args = parser.parse_args(argv)

    if args.list or args.name is None:
        for name, collector in sorted(registry.items()):
            auth = collector.env_var or "no API key required"
            print(f"{name:12s} provider={collector.provider_id:12s} {auth}")
        return 0

    root = Path(args.root) if args.root else REPO_ROOT
    collector = registry[args.name]
    print(f"collector: {collector.name} (provider {collector.provider_id}), "
          f"source {collector.api_url}")
    try:
        report = collector.run(root, write=args.write)
    except (CollectorError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 1
    collector.print_report(report, write=args.write)
    return 1 if report.get("invalid") else 0


if __name__ == "__main__":
    sys.exit(main())
