# -*- coding: utf-8 -*-
"""Run 250-day next_open pattern replay on the CN DailyPack."""

from __future__ import annotations

import argparse
from pathlib import Path

from alphasift.config import Config
from alphasift.jsonutil import dumps_strict_json
from alphasift.pack import load_pack, pack_dir
from alphasift.pattern_replay import load_cn_benchmark, render_replay_markdown, replay_patterns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay CN patterns across a DailyPack with next_open entry.")
    parser.add_argument("--pack-dir", default=None, help="Path to CN DailyPack directory")
    parser.add_argument("--pattern", action="append", default=None, help="Pattern name (repeatable)")
    parser.add_argument("--benchmark-csv", default=None, help="Optional CSV with date,open,close columns")
    parser.add_argument("--warmup-days", type=int, default=60, help="Warmup sessions before evaluating signals")
    parser.add_argument("--cost-bps", type=float, default=0.0, help="Round-trip cost in bps")
    parser.add_argument(
        "--allowed-regimes",
        default=None,
        help="Comma-separated permitted regime stages (e.g. startup,main_up)",
    )
    parser.add_argument(
        "--exclude-regimes",
        default=None,
        help="Comma-separated excluded regime stages (e.g. freezing,ebb)",
    )
    parser.add_argument(
        "--max-overhead-pct",
        type=float,
        default=None,
        help="Keep only signals whose top-10%% overhead supply is strictly below this percentage (e.g. 15)",
    )
    parser.add_argument("--output-json", default=None, help="Write replay JSON report")
    parser.add_argument("--output-md", default=None, help="Write replay Markdown report")
    args = parser.parse_args(argv)

    config = Config.from_env()
    directory = Path(args.pack_dir).expanduser() if args.pack_dir else pack_dir(config)
    pack = load_pack(directory)
    bench = load_cn_benchmark(
        Path(args.benchmark_csv).expanduser() if args.benchmark_csv else None,
        lookback_days=max(len(pack.dates) + 40, 320),
    )
    report = replay_patterns(
        pack,
        patterns=args.pattern,
        benchmark_df=bench,
        warmup_days=args.warmup_days,
        cost_bps=args.cost_bps,
        allowed_regimes=[
            s.strip() for s in (args.allowed_regimes or "").split(",") if s.strip()
        ]
        or None,
        excluded_regimes=[
            s.strip() for s in (args.exclude_regimes or "").split(",") if s.strip()
        ]
        or None,
        max_overhead_pct=args.max_overhead_pct,
    )
    md = render_replay_markdown(report)

    if args.output_json:
        out_json = Path(args.output_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(dumps_strict_json(report, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        out_md = Path(args.output_md)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(md, encoding="utf-8")

    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
