#!/usr/bin/env python3
"""Build the CN offline daily pack from a checkout for CI or local use."""

import argparse
import json
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main() -> None:
    from alphasift import pack

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backfill = sub.add_parser("backfill", help="Build a fresh window using Baostock")
    backfill.add_argument("--codes-limit", type=int, help="Limit the number of codes for a sample build")
    update = sub.add_parser("update", help="Append the next session and fill earlier gaps")
    for command in (backfill, update):
        command.add_argument("--days", type=int, default=pack.DEFAULT_DAYS, help="Window in trading days")
        command.add_argument("--trade-date", help="Target date in YYYY-MM-DD format")
        command.add_argument("--dir", type=Path, help="Override the configured pack directory")
    args = parser.parse_args()
    try:
        if args.command == "backfill":
            manifest = pack.backfill(args.dir, days=args.days, codes_limit=args.codes_limit, trade_date=args.trade_date)
        else:
            manifest = pack.update(args.dir, days=args.days, trade_date=args.trade_date)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
