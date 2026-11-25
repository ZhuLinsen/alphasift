# AlphaSift track record

Every trading day after the close, a GitHub Action runs each built-in strategy with `--no-llm --save-run` and commits the saved run here. Picks are never edited afterwards; the git history is the timestamped record. Each pick is then measured at T+5 / T+10 / T+20 trading days against its market benchmark.

**Dashboard:** https://alphasift.zhulinsen.tech/ · Code: [ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift) · Updated 2026-11-25T22:34:34+00:00 · 207 saved runs

> For research only, not investment advice. From 2026-11-21, entry uses `next_open` (explicitly tracking one-price limit-up untradable blocks); legacy pre-switch runs used signal-day `close`. Returns deduct round-trip costs, ignore dividends, and small samples are noisy.

## Scorecard (T+5 / T+20)

| Market | Strategy | Runs | T+5 n | T+5 excess | T+5 beat | T+20 n | T+20 excess | T+20 beat |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| cn | 均衡多因子 [AI] | 2 | 0 | – | – | 0 | – | – |
| cn | 均衡多因子 | 11 | 30 | +0.11% | 63% | 0 | – | – |
| cn | 蓝筹收益质量 [AI] | 2 | 0 | – | – | 0 | – | – |
| cn | 蓝筹收益质量 | 11 | 30 | +2.05% | 87% | 0 | – | – |
| cn | 资金热度 [AI] | 3 | 0 | – | – | 0 | – | – |
| cn | 资金热度 | 11 | 30 | -8.41% | 23% | 0 | – | – |
| cn | 双低选股 [AI] | 2 | 0 | – | – | 0 | – | – |
| cn | 双低选股 | 11 | 30 | +1.14% | 73% | 0 | – | – |
| cn | 低波质量 [AI] | 3 | 0 | – | – | 0 | – | – |
| cn | 低波质量 | 11 | 30 | +2.09% | 80% | 0 | – | – |
| cn | 趋势质量 [AI] | 3 | 0 | – | – | 0 | – | – |
| cn | 趋势质量 | 11 | 30 | +1.09% | 77% | 0 | – | – |
| cn | 超跌反转 [AI] | 2 | 0 | – | – | 0 | – | – |
| cn | 超跌反转 | 11 | 30 | -4.14% | 13% | 0 | – | – |
| cn | 稳健价值 [AI] | 3 | 0 | – | – | 0 | – | – |
| cn | 稳健价值 | 11 | 30 | +1.51% | 73% | 0 | – | – |
| cn | 缩量回踩 [AI] | 2 | 0 | – | – | 0 | – | – |
| cn | 缩量回踩 | 11 | 29 | +2.11% | 79% | 0 | – | – |
| cn | 放量突破 | 11 | 21 | -4.53% | 29% | 0 | – | – |
| hk | 全球低估值 | 11 | 30 | +0.68% | 60% | 0 | – | – |
| in | 全球低估值 | 10 | 25 | -1.28% | 28% | 0 | – | – |
| jp | 全球低估值 | 10 | 25 | -1.65% | 28% | 0 | – | – |
| kr | 全球低估值 | 11 | 30 | +1.08% | 70% | 0 | – | – |
| tw | 全球低估值 | 11 | 30 | +0.63% | 43% | 0 | – | – |
| us | 全球低估值 | 11 | 25 | -0.72% | 44% | 0 | – | – |
| us | US Momentum Quality | 11 | 25 | -0.33% | 56% | 0 | – | – |

## Latest session

- **asia** finished 2026-11-25T10:40:12+00:00: 15/15 strategies ok
- **us** finished 2026-11-25T22:34:28+00:00: 2/2 strategies ok

Raw runs: [`data/runs/`](data/runs) · derived site data: [`site/`](site)
