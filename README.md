# AlphaSift track record

Every trading day after the close, a GitHub Action runs each built-in strategy with `--no-llm --save-run` and commits the saved run here. Picks are never edited afterwards; the git history is the timestamped record. Each pick is then measured at T+5 / T+10 / T+20 trading days against its market benchmark.

**Dashboard:** https://alphasift.zhulinsen.tech/ · Code: [ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift) · Updated 2026-11-27T10:40:59+00:00 · 255 saved runs

> For research only, not investment advice. From 2026-11-21, entry uses `next_open` (explicitly tracking one-price limit-up untradable blocks); legacy pre-switch runs used signal-day `close`. Returns deduct round-trip costs, ignore dividends, and small samples are noisy.

## Scorecard (T+5 / T+20)

| Market | Strategy | Runs | T+5 n | T+5 excess | T+5 beat | T+20 n | T+20 excess | T+20 beat |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| cn | 均衡多因子 [AI] | 4 | 0 | – | – | 0 | – | – |
| cn | 均衡多因子 | 13 | 40 | -0.30% | 55% | 0 | – | – |
| cn | 蓝筹收益质量 [AI] | 4 | 0 | – | – | 0 | – | – |
| cn | 蓝筹收益质量 | 13 | 40 | +1.34% | 75% | 0 | – | – |
| cn | 资金热度 [AI] | 5 | 0 | – | – | 0 | – | – |
| cn | 资金热度 | 13 | 40 | -5.74% | 35% | 0 | – | – |
| cn | 双低选股 [AI] | 4 | 0 | – | – | 0 | – | – |
| cn | 双低选股 | 13 | 40 | +0.75% | 62% | 0 | – | – |
| cn | 低波质量 [AI] | 5 | 0 | – | – | 0 | – | – |
| cn | 低波质量 | 13 | 40 | +1.27% | 70% | 0 | – | – |
| cn | 趋势质量 [AI] | 5 | 0 | – | – | 0 | – | – |
| cn | 趋势质量 | 13 | 40 | +0.49% | 70% | 0 | – | – |
| cn | 超跌反转 [AI] | 4 | 0 | – | – | 0 | – | – |
| cn | 超跌反转 | 13 | 40 | -2.85% | 28% | 0 | – | – |
| cn | 稳健价值 [AI] | 5 | 0 | – | – | 0 | – | – |
| cn | 稳健价值 | 13 | 40 | +0.89% | 62% | 0 | – | – |
| cn | 缩量回踩 [AI] | 4 | 0 | – | – | 0 | – | – |
| cn | 缩量回踩 | 13 | 39 | +1.23% | 69% | 0 | – | – |
| cn | 放量突破 | 13 | 26 | -4.62% | 27% | 0 | – | – |
| hk | 全球低估值 | 13 | 35 | +0.52% | 57% | 0 | – | – |
| in | 全球低估值 | 12 | 30 | -1.71% | 20% | 0 | – | – |
| jp | 全球低估值 | 12 | 30 | -0.84% | 43% | 0 | – | – |
| kr | 全球低估值 | 13 | 35 | +2.16% | 74% | 0 | – | – |
| tw | 全球低估值 | 13 | 35 | +0.92% | 46% | 0 | – | – |
| us | 全球低估值 | 11 | 30 | -0.42% | 47% | 0 | – | – |
| us | US Momentum Quality | 11 | 30 | -0.13% | 60% | 0 | – | – |

## Latest session

- **asia** finished 2026-11-27T10:40:01+00:00: 15/15 strategies ok
- **us** finished 2026-11-26T22:34:54+00:00: 0/0 strategies ok (2 skipped)

Raw runs: [`data/runs/`](data/runs) · derived site data: [`site/`](site)
