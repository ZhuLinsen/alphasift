# AlphaSift track record

Every trading day after the close, a GitHub Action runs each built-in strategy with `--no-llm --save-run` and commits the saved run here. Picks are never edited afterwards; the git history is the timestamped record. Each pick is then measured at T+5 / T+10 / T+20 trading days against its market benchmark.

**Dashboard:** https://alphasift.zhulinsen.tech/ · Code: [ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift) · Updated 2026-11-23T10:34:21+00:00 · 150 saved runs

> For research only, not investment advice. From 2026-11-21, entry uses `next_open` (explicitly tracking one-price limit-up untradable blocks); legacy pre-switch runs used signal-day `close`. Returns deduct round-trip costs, ignore dividends, and small samples are noisy.

## Scorecard (T+5 / T+20)

| Market | Strategy | Runs | T+5 n | T+5 excess | T+5 beat | T+20 n | T+20 excess | T+20 beat |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| cn | 均衡多因子 | 9 | 20 | +1.07% | 65% | 0 | – | – |
| cn | 蓝筹收益质量 | 9 | 20 | +2.27% | 85% | 0 | – | – |
| cn | 资金热度 | 9 | 20 | -7.49% | 25% | 0 | – | – |
| cn | 双低选股 | 9 | 20 | +1.26% | 75% | 0 | – | – |
| cn | 低波质量 | 9 | 20 | +2.08% | 80% | 0 | – | – |
| cn | 趋势质量 | 9 | 20 | +2.86% | 85% | 0 | – | – |
| cn | 超跌反转 | 9 | 20 | -4.04% | 20% | 0 | – | – |
| cn | 稳健价值 | 9 | 20 | +1.69% | 75% | 0 | – | – |
| cn | 缩量回踩 | 9 | 19 | +2.92% | 84% | 0 | – | – |
| cn | 放量突破 | 9 | 13 | -4.07% | 15% | 0 | – | – |
| hk | 全球低估值 | 9 | 15 | +2.17% | 73% | 0 | – | – |
| in | 全球低估值 | 9 | 15 | -1.76% | 20% | 0 | – | – |
| jp | 全球低估值 | 8 | 15 | -0.52% | 47% | 0 | – | – |
| kr | 全球低估值 | 9 | 15 | +3.17% | 80% | 0 | – | – |
| tw | 全球低估值 | 9 | 15 | +2.62% | 53% | 0 | – | – |
| us | 全球低估值 | 8 | 15 | +1.51% | 53% | 0 | – | – |
| us | US Momentum Quality | 8 | 15 | +0.33% | 60% | 0 | – | – |

## Latest session

- **asia** finished 2026-11-23T10:33:41+00:00: 14/14 strategies ok (1 skipped)
- **us** finished 2026-11-20T22:34:55+00:00: 2/2 strategies ok

Raw runs: [`data/runs/`](data/runs) · derived site data: [`site/`](site)
