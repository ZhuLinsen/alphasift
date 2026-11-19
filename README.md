# AlphaSift track record

Every trading day after the close, a GitHub Action runs each built-in strategy with `--no-llm --save-run` and commits the saved run here. Picks are never edited afterwards; the git history is the timestamped record. Each pick is then measured at T+5 / T+10 / T+20 trading days against its market benchmark.

**Dashboard:** https://zhulinsen.github.io/alphasift/ · Code: [ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift) · Updated 2026-11-19T22:34:56+00:00 · 119 saved runs

> For research only, not investment advice. Returns are close-to-close after a round-trip cost, ignore dividends, and small samples are noisy.

## Scorecard (T+5 / T+20)

| Market | Strategy | Runs | T+5 n | T+5 excess | T+5 beat | T+20 n | T+20 excess | T+20 beat |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| cn | 均衡多因子 | 7 | 5 | +0.24% | 20% | 0 | – | – |
| cn | 蓝筹收益质量 | 7 | 5 | -0.82% | 40% | 0 | – | – |
| cn | 资金热度 | 7 | 5 | +4.20% | 80% | 0 | – | – |
| cn | 双低选股 | 7 | 5 | -1.02% | 40% | 0 | – | – |
| cn | 低波质量 | 7 | 5 | -3.31% | 20% | 0 | – | – |
| cn | 趋势质量 | 7 | 5 | +1.41% | 60% | 0 | – | – |
| cn | 超跌反转 | 7 | 5 | -2.07% | 20% | 0 | – | – |
| cn | 稳健价值 | 7 | 5 | -1.82% | 20% | 0 | – | – |
| cn | 缩量回踩 | 7 | 5 | +1.49% | 80% | 0 | – | – |
| cn | 放量突破 | 7 | 1 | -1.84% | 0% | 0 | – | – |
| hk | 全球低估值 | 7 | 5 | +1.12% | 60% | 0 | – | – |
| in | 全球低估值 | 7 | 5 | -1.84% | 20% | 0 | – | – |
| jp | 全球低估值 | 7 | 5 | +5.03% | 100% | 0 | – | – |
| kr | 全球低估值 | 7 | 5 | +6.47% | 100% | 0 | – | – |
| tw | 全球低估值 | 7 | 5 | -4.14% | 0% | 0 | – | – |
| us | 全球低估值 | 7 | 5 | +0.81% | 40% | 0 | – | – |
| us | US Momentum Quality | 7 | 5 | -2.19% | 40% | 0 | – | – |

## Latest session

- **asia** finished 2026-11-19T10:34:48+00:00: 15/15 strategies ok
- **us** finished 2026-11-19T22:34:53+00:00: 2/2 strategies ok

Raw runs: [`data/runs/`](data/runs) · derived site data: [`site/`](site)
