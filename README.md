# AlphaSift track record

Every trading day after the close, a GitHub Action runs each built-in strategy with `--no-llm --save-run` and commits the saved run here. Picks are never edited afterwards; the git history is the timestamped record. Each pick is then measured at T+5 / T+10 / T+20 trading days against its market benchmark.

**Dashboard:** https://alphasift.zhulinsen.tech/ · Code: [ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift) · Updated 2026-11-24T17:35:59+00:00 · 179 saved runs

> For research only, not investment advice. From 2026-11-21, entry uses `next_open` (explicitly tracking one-price limit-up untradable blocks); legacy pre-switch runs used signal-day `close`. Returns deduct round-trip costs, ignore dividends, and small samples are noisy.

## Scorecard (T+5 / T+20)

| Market | Strategy | Runs | T+5 n | T+5 excess | T+5 beat | T+20 n | T+20 excess | T+20 beat |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| cn | 均衡多因子 [AI] | 1 | 0 | – | – | 0 | – | – |
| cn | 均衡多因子 | 10 | 25 | +0.45% | 60% | 0 | – | – |
| cn | 蓝筹收益质量 [AI] | 1 | 0 | – | – | 0 | – | – |
| cn | 蓝筹收益质量 | 10 | 25 | +1.94% | 84% | 0 | – | – |
| cn | 资金热度 [AI] | 2 | 0 | – | – | 0 | – | – |
| cn | 资金热度 | 10 | 25 | -7.57% | 24% | 0 | – | – |
| cn | 双低选股 [AI] | 1 | 0 | – | – | 0 | – | – |
| cn | 双低选股 | 10 | 25 | +1.07% | 72% | 0 | – | – |
| cn | 低波质量 [AI] | 2 | 0 | – | – | 0 | – | – |
| cn | 低波质量 | 10 | 25 | +1.71% | 76% | 0 | – | – |
| cn | 趋势质量 [AI] | 2 | 0 | – | – | 0 | – | – |
| cn | 趋势质量 | 10 | 25 | +2.03% | 80% | 0 | – | – |
| cn | 超跌反转 [AI] | 1 | 0 | – | – | 0 | – | – |
| cn | 超跌反转 | 10 | 25 | -4.18% | 16% | 0 | – | – |
| cn | 稳健价值 [AI] | 2 | 0 | – | – | 0 | – | – |
| cn | 稳健价值 | 10 | 25 | +1.42% | 72% | 0 | – | – |
| cn | 缩量回踩 [AI] | 1 | 0 | – | – | 0 | – | – |
| cn | 缩量回踩 | 10 | 24 | +2.31% | 79% | 0 | – | – |
| cn | 放量突破 | 10 | 18 | -4.66% | 28% | 0 | – | – |
| hk | 全球低估值 | 10 | 25 | +1.04% | 60% | 0 | – | – |
| in | 全球低估值 | 9 | 20 | -1.54% | 25% | 0 | – | – |
| jp | 全球低估值 | 9 | 20 | -0.21% | 50% | 0 | – | – |
| kr | 全球低估值 | 10 | 25 | +2.90% | 76% | 0 | – | – |
| tw | 全球低估值 | 10 | 25 | +3.13% | 56% | 0 | – | – |
| us | 全球低估值 | 9 | 20 | -0.40% | 40% | 0 | – | – |
| us | US Momentum Quality | 9 | 20 | -0.37% | 55% | 0 | – | – |

## Latest session

- **asia** finished 2026-11-24T10:32:50+00:00: 4/4 strategies ok (11 skipped)
- **us** finished 2026-11-23T22:35:45+00:00: 2/2 strategies ok

Raw runs: [`data/runs/`](data/runs) · derived site data: [`site/`](site)
