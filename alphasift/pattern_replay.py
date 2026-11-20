# -*- coding: utf-8 -*-
"""250-day next_open CN pattern replay, regime slicing, and graduation gate."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alphasift.daily import _fetch_daily_sina
from alphasift.market_regime import (
    REGIME_STAGE_LABELS,
    REGIME_STAGE_ORDER,
    compute_limit_masks,
    compute_market_regime_series,
    summarize_regime_distribution,
)
from alphasift.pack import DailyPack, forward_adjust
from alphasift.patterns import (
    PatternSpec,
    build_pattern_context,
    compute_overhead_supply_10pct_row,
    evaluate_pattern_matrix,
    list_patterns,
    load_pattern,
)

GRADUATION_MIN_SAMPLES = 200
REGIME_SLICE_WEIGHT_READY_SAMPLES = 100
STABILITY_MIN_HALF_SAMPLES = 30
STABILITY_T_STAT_THRESHOLD = 1.96


def load_cn_benchmark(
    benchmark_csv: Path | None = None,
    *,
    lookback_days: int = 360,
    symbol: str = "sh000300",
) -> pd.DataFrame:
    """Load CN benchmark OHLC (default CSI 300 from Sina) for open-to-close excess."""
    if benchmark_csv is not None:
        df = pd.read_csv(benchmark_csv)
    else:
        df = _fetch_daily_sina(symbol, lookback_days=lookback_days)
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
        "open": pd.to_numeric(df["open"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
    })
    out = out.dropna(subset=["date", "open", "close"]).drop_duplicates(subset=["date"], keep="last")
    return out.sort_values("date").reset_index(drop=True)


def _mean_or_none(vals: list[float]) -> float | None:
    return round(float(np.mean(vals)), 3) if vals else None


def _median_or_none(vals: list[float]) -> float | None:
    return round(float(np.median(vals)), 3) if vals else None


def _win_rate_or_none(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(float(sum(1 for v in vals if v > 0) / len(vals) * 100.0), 2)


def _summarize_stability(
    obs_list: list[dict[str, Any]],
    *,
    mid_date: str,
    horizon: int = 5,
) -> dict[str, Any]:
    """Check split-half sign consistency (H1 vs H2) and t-stat over excess returns."""
    h_key = f"t{horizon}"
    all_vals: list[float] = []
    h1_vals: list[float] = []
    h2_vals: list[float] = []
    for item in obs_list:
        res = item["horizons"].get(h_key)
        if not isinstance(res, dict) or res.get("status") != "ok":
            continue
        ex = res.get("excess_return_pct")
        if ex is None or not np.isfinite(ex):
            continue
        val = float(ex)
        all_vals.append(val)
        if str(item["date"]) < mid_date:
            h1_vals.append(val)
        else:
            h2_vals.append(val)

    n = len(all_vals)
    h1_n = len(h1_vals)
    h2_n = len(h2_vals)
    mean_pct = _mean_or_none(all_vals)
    h1_mean = _mean_or_none(h1_vals)
    h2_mean = _mean_or_none(h2_vals)

    t_stat: float | None = None
    if n >= 2:
        std = float(np.std(all_vals, ddof=1))
        if std > 1e-12:
            t_stat = round(float(np.mean(all_vals) / (std / np.sqrt(n))), 2)

    sign_consistent = bool(
        h1_n >= 20
        and h2_n >= 20
        and h1_mean is not None
        and h2_mean is not None
        and (h1_mean * h2_mean > 0)
    )
    if sign_consistent and h1_mean is not None and h1_mean > 0:
        direction = "positive"
    elif sign_consistent and h1_mean is not None and h1_mean < 0:
        direction = "negative"
    else:
        direction = "mixed_or_insufficient"

    stability_ready = bool(
        n >= REGIME_SLICE_WEIGHT_READY_SAMPLES
        and h1_n >= STABILITY_MIN_HALF_SAMPLES
        and h2_n >= STABILITY_MIN_HALF_SAMPLES
        and sign_consistent
        and t_stat is not None
        and abs(t_stat) >= STABILITY_T_STAT_THRESHOLD
    )
    return {
        "n": n,
        "mean_pct": mean_pct,
        "t_stat": t_stat,
        "h1_n": h1_n,
        "h1_excess_mean_pct": h1_mean,
        "h2_n": h2_n,
        "h2_excess_mean_pct": h2_mean,
        "sign_consistent": sign_consistent,
        "stable_direction": direction,
        "stability_ready": stability_ready,
    }


def _summarize_horizon_obs(
    obs_list: list[dict[str, Any]],
    horizon: int,
) -> dict[str, Any]:
    raws: list[float] = []
    excesses: list[float] = []
    pending = 0
    delayed = 0
    h_key = f"t{horizon}"
    for item in obs_list:
        res = item["horizons"].get(h_key)
        if res is None:
            continue
        status = res["status"]
        if status == "ok":
            raws.append(res["raw_return_pct"])
            if res["excess_return_pct"] is not None:
                excesses.append(res["excess_return_pct"])
            if res["exit_delayed"]:
                delayed += 1
        elif status == "pending":
            pending += 1

    scored = len(raws)
    return {
        "horizon_days": horizon,
        "scored": scored,
        "pending": pending,
        "exit_delayed_count": delayed,
        "raw_mean_pct": _mean_or_none(raws),
        "raw_median_pct": _median_or_none(raws),
        "win_rate_pct": _win_rate_or_none(raws),
        "excess_mean_pct": _mean_or_none(excesses),
        "excess_median_pct": _median_or_none(excesses),
        "excess_win_rate_pct": _win_rate_or_none(excesses),
    }


def _evaluate_graduation(spec: PatternSpec, t5_summary: dict[str, Any]) -> dict[str, Any]:
    scored = int(t5_summary["scored"])
    excess = t5_summary["excess_mean_pct"]
    passed = scored >= GRADUATION_MIN_SAMPLES and excess is not None and excess > 0.0
    if scored < GRADUATION_MIN_SAMPLES:
        reason = f"T+5 样本 {scored} < 门槛 {GRADUATION_MIN_SAMPLES}"
    elif excess is None:
        reason = "缺少基准超额收益数据"
    elif excess <= 0.0:
        reason = f"T+5 平均超额 {excess:+.3f}% <= 0%"
    else:
        reason = f"达标：T+5 样本 {scored} >= {GRADUATION_MIN_SAMPLES} 且平均超额 {excess:+.3f}% > 0%"
    return {
        "passed": passed,
        "current_yaml_status": spec.status,
        "recommended_status": "active" if passed else "experimental",
        "min_samples": GRADUATION_MIN_SAMPLES,
        "t5_scored": scored,
        "t5_excess_mean_pct": excess,
        "reason": reason,
    }


def _overhead_bucket(val: float | None) -> str | None:
    if val is None or not np.isfinite(val):
        return None
    if val < 15.0:
        return "low_lt15"
    if val < 35.0:
        return "mid_15_35"
    return "high_ge35"


def replay_patterns(
    daily_pack: DailyPack,
    *,
    patterns: Sequence[str] | None = None,
    benchmark_df: pd.DataFrame | None = None,
    horizons: tuple[int, ...] = (5, 10),
    warmup_days: int = 60,
    cost_bps: float = 0.0,
    patterns_dir: Path | None = None,
) -> dict[str, Any]:
    """Replay CN patterns point-in-time on ``daily_pack`` using ``next_open`` + tradability rules."""
    sorted_horizons = tuple(sorted({int(h) for h in horizons if int(h) > 0}))
    if not sorted_horizons:
        raise ValueError("horizons must include at least one positive integer")
    max_h = max(sorted_horizons)

    if patterns:
        specs = [load_pattern(name, patterns_dir=patterns_dir) for name in patterns]
    else:
        specs = list_patterns(include_experimental=True, patterns_dir=patterns_dir)

    if benchmark_df is None:
        benchmark_df = load_cn_benchmark(lookback_days=max(len(daily_pack.dates) + 40, 320))

    bench_open = dict(zip(benchmark_df["date"].astype(str), benchmark_df["open"].astype(float)))
    bench_close = dict(zip(benchmark_df["date"].astype(str), benchmark_df["close"].astype(float)))

    limit_masks = compute_limit_masks(daily_pack)
    regime_series = compute_market_regime_series(daily_pack, masks=limit_masks)
    ctx = build_pattern_context(daily_pack)
    adj = forward_adjust(daily_pack)

    dates = [str(d) for d in daily_pack.dates]
    t_len = len(dates)
    end_t = t_len - max_h
    if end_t <= warmup_days:
        raise ValueError(
            f"Not enough sessions ({t_len}) for warmup_days={warmup_days} and max horizon={max_h}"
        )

    active = limit_masks["active"]
    one_lu = limit_masks["is_one_price_limit_up"]
    one_ld = limit_masks["is_one_price_limit_down"]
    adj_open = np.asarray(adj["open"], dtype=np.float64)
    adj_close = np.asarray(adj["close"], dtype=np.float64)

    eval_regimes = regime_series[warmup_days:end_t]
    regime_distribution = summarize_regime_distribution(eval_regimes)
    mid_date = dates[warmup_days + (end_t - warmup_days) // 2]

    pattern_reports: list[dict[str, Any]] = []
    for spec in specs:
        sig_mask, _ = evaluate_pattern_matrix(ctx, spec)
        total_signals = 0
        untradable_count = 0
        observations: list[dict[str, Any]] = []
        regime_signal_counts: dict[str, int] = {stage: 0 for stage in REGIME_STAGE_ORDER}
        regime_untradable_counts: dict[str, int] = {stage: 0 for stage in REGIME_STAGE_ORDER}

        for t in range(warmup_days, end_t):
            cols = np.flatnonzero(sig_mask[t])
            if cols.size == 0:
                continue
            overhead_vals = compute_overhead_supply_10pct_row(ctx, t, cols)
            stage = regime_series[t].regime_stage
            day_str = dates[t]

            for pos, j in enumerate(cols.tolist()):
                total_signals += 1
                regime_signal_counts[stage] = regime_signal_counts.get(stage, 0) + 1

                future_active = np.flatnonzero(active[t + 1 :, j]) + (t + 1)
                if future_active.size == 0:
                    observations.append({
                        "date": day_str,
                        "code": str(ctx.codes[j]),
                        "stage": stage,
                        "overhead": float(overhead_vals[pos]) if np.isfinite(overhead_vals[pos]) else None,
                        "untradable": False,
                        "horizons": {f"t{h}": {"status": "pending"} for h in sorted_horizons},
                    })
                    continue

                t_entry = int(future_active[0])
                entry_open_px = float(adj_open[t_entry, j])
                if one_lu[t_entry, j] or not np.isfinite(entry_open_px) or entry_open_px <= 0:
                    untradable_count += 1
                    regime_untradable_counts[stage] = regime_untradable_counts.get(stage, 0) + 1
                    observations.append({
                        "date": day_str,
                        "code": str(ctx.codes[j]),
                        "stage": stage,
                        "overhead": float(overhead_vals[pos]) if np.isfinite(overhead_vals[pos]) else None,
                        "untradable": True,
                        "horizons": {},
                    })
                    continue

                entry_date = dates[t_entry]
                b_open = bench_open.get(entry_date)
                h_map: dict[str, dict[str, Any]] = {}
                for h in sorted_horizons:
                    k = h - 1
                    while k < future_active.size and one_ld[int(future_active[k]), j]:
                        k += 1
                    if k >= future_active.size:
                        h_map[f"t{h}"] = {"status": "pending"}
                        continue
                    t_exit = int(future_active[k])
                    exit_close_px = float(adj_close[t_exit, j])
                    if not np.isfinite(exit_close_px) or exit_close_px <= 0:
                        h_map[f"t{h}"] = {"status": "pending"}
                        continue
                    raw_ret = (exit_close_px / entry_open_px - 1.0) * 100.0 - float(cost_bps) / 100.0
                    exit_date = dates[t_exit]
                    b_close = bench_close.get(exit_date)
                    excess_ret = None
                    if b_open is not None and b_close is not None and b_open > 0:
                        bench_ret = (b_close / b_open - 1.0) * 100.0
                        excess_ret = raw_ret - bench_ret
                    h_map[f"t{h}"] = {
                        "status": "ok",
                        "raw_return_pct": raw_ret,
                        "excess_return_pct": excess_ret,
                        "exit_delayed": bool(k > h - 1),
                    }

                observations.append({
                    "date": day_str,
                    "code": str(ctx.codes[j]),
                    "stage": stage,
                    "overhead": float(overhead_vals[pos]) if np.isfinite(overhead_vals[pos]) else None,
                    "untradable": False,
                    "horizons": h_map,
                })

        untradable_share = round((untradable_count / total_signals) * 100.0, 2) if total_signals > 0 else 0.0
        horizons_summary = {
            f"t{h}": _summarize_horizon_obs(observations, h) for h in sorted_horizons
        }
        primary_t5 = horizons_summary.get("t5") or horizons_summary[f"t{sorted_horizons[0]}"]
        primary_h = int(sorted_horizons[0]) if 5 not in sorted_horizons else 5
        graduation = _evaluate_graduation(spec, primary_t5)
        stability = _summarize_stability(observations, mid_date=mid_date, horizon=primary_h)

        by_regime: dict[str, Any] = {}
        for stage in REGIME_STAGE_ORDER:
            stage_obs = [o for o in observations if o["stage"] == stage]
            sig_n = regime_signal_counts.get(stage, 0)
            unt_n = regime_untradable_counts.get(stage, 0)
            s_t5 = _summarize_horizon_obs(stage_obs, 5) if 5 in sorted_horizons else None
            s_t10 = _summarize_horizon_obs(stage_obs, 10) if 10 in sorted_horizons else None
            stage_stab = _summarize_stability(stage_obs, mid_date=mid_date, horizon=primary_h)
            t5_scored = int(s_t5["scored"]) if s_t5 else 0
            by_regime[stage] = {
                "label": REGIME_STAGE_LABELS[stage],
                "signals": sig_n,
                "untradable_count": unt_n,
                "untradable_share_pct": round((unt_n / sig_n) * 100.0, 2) if sig_n > 0 else 0.0,
                "t5_scored": t5_scored,
                "t5_raw_mean_pct": s_t5["raw_mean_pct"] if s_t5 else None,
                "t5_excess_mean_pct": s_t5["excess_mean_pct"] if s_t5 else None,
                "t5_win_rate_pct": s_t5["win_rate_pct"] if s_t5 else None,
                "t10_scored": int(s_t10["scored"]) if s_t10 else 0,
                "t10_excess_mean_pct": s_t10["excess_mean_pct"] if s_t10 else None,
                "weight_eval_ready": t5_scored >= REGIME_SLICE_WEIGHT_READY_SAMPLES,
                "stability": stage_stab,
                "stability_ready": stage_stab["stability_ready"],
            }

        by_overhead: dict[str, Any] = {}
        for bucket in ("low_lt15", "mid_15_35", "high_ge35"):
            b_obs = [o for o in observations if _overhead_bucket(o["overhead"]) == bucket]
            s_t5 = _summarize_horizon_obs(b_obs, 5) if 5 in sorted_horizons else None
            s_t10 = _summarize_horizon_obs(b_obs, 10) if 10 in sorted_horizons else None
            b_stab = _summarize_stability(b_obs, mid_date=mid_date, horizon=primary_h)
            by_overhead[bucket] = {
                "signals": len(b_obs),
                "t5_scored": int(s_t5["scored"]) if s_t5 else 0,
                "t5_excess_mean_pct": s_t5["excess_mean_pct"] if s_t5 else None,
                "t5_win_rate_pct": s_t5["win_rate_pct"] if s_t5 else None,
                "t10_scored": int(s_t10["scored"]) if s_t10 else 0,
                "t10_excess_mean_pct": s_t10["excess_mean_pct"] if s_t10 else None,
                "stability": b_stab,
            }

        monthly_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for o in observations:
            monthly_groups[o["date"][:7]].append(o)
        by_month: dict[str, Any] = {}
        for ym in sorted(monthly_groups):
            m_obs = monthly_groups[ym]
            s_t5 = _summarize_horizon_obs(m_obs, 5) if 5 in sorted_horizons else None
            s_t10 = _summarize_horizon_obs(m_obs, 10) if 10 in sorted_horizons else None
            by_month[ym] = {
                "signals": len(m_obs),
                "t5_scored": int(s_t5["scored"]) if s_t5 else 0,
                "t5_excess_mean_pct": s_t5["excess_mean_pct"] if s_t5 else None,
                "t10_excess_mean_pct": s_t10["excess_mean_pct"] if s_t10 else None,
            }

        pattern_reports.append({
            "pattern": spec.name,
            "display_name": spec.display_name,
            "family": spec.family,
            "mode": spec.mode,
            "aligned_strategy": spec.aligned_strategy,
            "total_signals": total_signals,
            "untradable_count": untradable_count,
            "untradable_share_pct": untradable_share,
            "horizons": horizons_summary,
            "graduation": graduation,
            "stability": stability,
            "by_regime": by_regime,
            "by_overhead_supply": by_overhead,
            "by_month": by_month,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entry_mode": "next_open",
        "benchmark": "sh000300",
        "cost_bps": float(cost_bps),
        "graduation_rule": {"min_samples": GRADUATION_MIN_SAMPLES, "t5_excess_mean_pct_gt": 0.0},
        "regime_weight_policy": "reporting_and_slice_only",
        "pack_summary": {
            "dates_total": t_len,
            "codes_total": int(len(daily_pack.codes)),
            "eval_sessions": int(end_t - warmup_days),
            "eval_start_date": dates[warmup_days],
            "eval_mid_date": mid_date,
            "eval_end_date": dates[end_t - 1],
            "pack_end_date": dates[-1],
        },
        "regime_distribution": regime_distribution,
        "patterns": pattern_reports,
    }


def _fmt_pct(val: float | None) -> str:
    return "-" if val is None else f"{val:+.2f}%"


def _fmt_rate(val: float | None) -> str:
    return "-" if val is None else f"{val:.1f}%"


def render_replay_markdown(report: dict[str, Any]) -> str:
    """Render concise Markdown report for pattern replay, regime slices, and gating."""
    ps = report["pack_summary"]
    lines = [
        "# A 股形态 250 日 next_open 回放报告",
        "",
        f"- 评估区间: `{ps['eval_start_date']}` .. `{ps['eval_end_date']}` ({ps['eval_sessions']} 交易日, 股票池 {ps['codes_total']} 只, 包截止 `{ps['pack_end_date']}`)",
        f"- 口径: `{report['entry_mode']}` 入场（一字涨停不可成交剔除，退出一字跌停顺延），基准 `{report['benchmark']}` 同期开盘→收盘",
        f"- 毕业门槛: `T+5 样本 >= {GRADUATION_MIN_SAMPLES}` 且 `T+5 超额 > 0%`（否则标 `experimental`）；情绪阶段仅作切片观察（策略权重不随阶段调整）",
        "",
        "## 形态总览与毕业判定",
        "",
        "| 形态 | 谱系 | 模式 | 信号数 | 不可成交 | T+5 样本 | T+5 原始 | T+5 超额 | T+5 胜率 | T+10 超额 | 判定 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["patterns"]:
        h5 = item["horizons"].get("t5") or {}
        h10 = item["horizons"].get("t10") or {}
        grad = item["graduation"]
        lines.append(
            f"| {item['display_name']} (`{item['pattern']}`) | {item['family']} | {item['mode']} | "
            f"{item['total_signals']} | {item['untradable_share_pct']:.1f}% | "
            f"{h5.get('scored', 0)} | {_fmt_pct(h5.get('raw_mean_pct'))} | "
            f"{_fmt_pct(h5.get('excess_mean_pct'))} | {_fmt_rate(h5.get('win_rate_pct'))} | "
            f"{_fmt_pct(h10.get('excess_mean_pct'))} | **{grad['recommended_status']}** |"
        )

    lines.extend([
        "",
        "## 市场阶段分布（切片元数据）",
        "",
        "| 阶段 | 天数 | 占比 |",
        "|---|---:|---:|",
    ])
    for stage in REGIME_STAGE_ORDER:
        info = report["regime_distribution"][stage]
        lines.append(f"| {info['label']} (`{stage}`) | {info['days']} | {info['share_pct']:.1f}% |")

    lines.extend([
        "",
        "## 形态 × 市场阶段切片（T+5 样本 / 平均超额）",
        "",
        "| 形态 | " + " | ".join(f"{REGIME_STAGE_LABELS[s]}" for s in REGIME_STAGE_ORDER) + " |",
        "|---|" + "|".join("---:" for _ in REGIME_STAGE_ORDER) + "|",
    ])
    for item in report["patterns"]:
        cells = []
        for s in REGIME_STAGE_ORDER:
            sl = item["by_regime"][s]
            mark = "" if sl["weight_eval_ready"] else "*"
            cells.append(f"{sl['t5_scored']}{mark} / {_fmt_pct(sl['t5_excess_mean_pct'])}")
        lines.append(f"| {item['display_name']} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("_注：带 `*` 表示该格 T+5 样本 < 100，仅作观察，暂不满足调权样本要求。_")

    lines.extend([
        "",
        "## 上方 10% 筹码占比切片（仅特征观察，非一票否决）",
        "",
        "| 形态 | <15% (样本/T+5超额) | 15%-35% (样本/T+5超额) | >=35% (样本/T+5超额) |",
        "|---|---:|---:|---:|",
    ])
    for item in report["patterns"]:
        ov = item["by_overhead_supply"]
        c1 = f"{ov['low_lt15']['t5_scored']} / {_fmt_pct(ov['low_lt15']['t5_excess_mean_pct'])}"
        c2 = f"{ov['mid_15_35']['t5_scored']} / {_fmt_pct(ov['mid_15_35']['t5_excess_mean_pct'])}"
        c3 = f"{ov['high_ge35']['t5_scored']} / {_fmt_pct(ov['high_ge35']['t5_excess_mean_pct'])}"
        lines.append(f"| {item['display_name']} | {c1} | {c2} | {c3} |")

    lines.extend([
        "",
        f"## 时间前后半段稳定性检验（切分日 `{ps.get('eval_mid_date', '-')}`，防过拟合检查）",
        "",
        "| 形态 | H1 样本/T+5超额 | H2 样本/T+5超额 | 全区间 t-stat | 前后半段方向 | 达标稳定切片 |",
        "|---|---:|---:|---:|---|---|",
    ])
    stable_slices: list[str] = []
    for item in report["patterns"]:
        st = item.get("stability") or {}
        t_str = "-" if st.get("t_stat") is None else f"{st['t_stat']:+.2f}"
        pos_cells = [
            f"{item['display_name']}×{REGIME_STAGE_LABELS[s]}({sl['t5_excess_mean_pct']:+.2f}%)"
            for s, sl in (item.get("by_regime") or {}).items()
            if sl.get("stability_ready") and (sl.get("t5_excess_mean_pct") or 0) > 0
        ]
        stable_slices.extend(pos_cells)
        cell_txt = "、".join(pos_cells) if pos_cells else "无"
        lines.append(
            f"| {item['display_name']} | {st.get('h1_n', 0)} / {_fmt_pct(st.get('h1_excess_mean_pct'))} | "
            f"{st.get('h2_n', 0)} / {_fmt_pct(st.get('h2_excess_mean_pct'))} | {t_str} | "
            f"{st.get('stable_direction', '-')} | {cell_txt} |"
        )
    if not stable_slices:
        lines.append("")
        lines.append("_注：当前暂无同时满足单格样本 >= 100、前后半段同号（>=30/半段）且 |t| >= 1.96 的稳定正超额切片，保持情绪阶段不调权重。_")

    return "\n".join(lines) + "\n"
