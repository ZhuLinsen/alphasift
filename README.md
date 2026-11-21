# AlphaSift track record

Every trading day after the close, a GitHub Action runs each built-in strategy with `--no-llm --save-run` and commits the saved run here. Picks are never edited afterwards; the git history is the timestamped record. Each pick is then measured at T+5 / T+10 / T+20 trading days against its market benchmark.

**Dashboard:** https://zhulinsen.github.io/alphasift/ · Code: [ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift) · Updated 2026-11-21T10:06:17+00:00 · 136 saved runs

> For research only, not investment advice. Returns are close-to-close after a round-trip cost, ignore dividends, and small samples are noisy.

## Scorecard (T+5 / T+20)

| Market | Strategy | Runs | T+5 n | T+5 excess | T+5 beat | T+20 n | T+20 excess | T+20 beat |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| cn | 均衡多因子 | 8 | 15 | +1.02% | 53% | 0 | – | – |
| cn | 蓝筹收益质量 | 8 | 15 | +2.72% | 80% | 0 | – | – |
| cn | 资金热度 | 8 | 15 | -6.81% | 33% | 0 | – | – |
| cn | 双低选股 | 8 | 15 | +1.47% | 73% | 0 | – | – |
| cn | 低波质量 | 8 | 15 | +2.43% | 73% | 0 | – | – |
| cn | 趋势质量 | 8 | 15 | +3.36% | 80% | 0 | – | – |
| cn | 超跌反转 | 8 | 15 | -5.14% | 13% | 0 | – | – |
| cn | 稳健价值 | 8 | 15 | +2.06% | 73% | 0 | – | – |
| cn | 缩量回踩 | 8 | 14 | +3.44% | 86% | 0 | – | – |
| cn | 放量突破 | 8 | 8 | -0.83% | 12% | 0 | – | – |
| hk | 全球低估值 | 8 | 15 | +2.17% | 73% | 0 | – | – |
| in | 全球低估值 | 8 | 15 | -1.76% | 20% | 0 | – | – |
| jp | 全球低估值 | 8 | 15 | -0.52% | 47% | 0 | – | – |
| kr | 全球低估值 | 8 | 15 | +3.17% | 80% | 0 | – | – |
| tw | 全球低估值 | 8 | 15 | +2.62% | 53% | 0 | – | – |
| us | 全球低估值 | 8 | 15 | +1.51% | 53% | 0 | – | – |
| us | US Momentum Quality | 8 | 15 | +0.33% | 60% | 0 | – | – |

## Latest session

- **asia** finished 2026-11-20T10:35:49+00:00: 15/15 strategies ok
- **us** finished 2026-11-20T22:34:55+00:00: 2/2 strategies ok

Raw runs: [`data/runs/`](data/runs) · derived site data: [`site/`](site)
