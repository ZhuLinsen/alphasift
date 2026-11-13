# AlphaSift track record

Every trading day after the close, a GitHub Action runs each built-in strategy with `--no-llm --save-run` and commits the saved run here. Picks are never edited afterwards; the git history is the timestamped record. Each pick is then measured at T+5 / T+10 / T+20 trading days against its market benchmark.

**Dashboard:** https://zhulinsen.github.io/alphasift/ · Code: [ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift) · Updated 2026-11-13T22:34:49+00:00 · 51 saved runs

> For research only, not investment advice. Returns are close-to-close after a round-trip cost, ignore dividends, and small samples are noisy.

## Scorecard (T+5 / T+20)

| Market | Strategy | Runs | T+5 n | T+5 excess | T+5 beat | T+20 n | T+20 excess | T+20 beat |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| cn | 均衡多因子 | 3 | 0 | – | – | 0 | – | – |
| cn | 蓝筹收益质量 | 3 | 0 | – | – | 0 | – | – |
| cn | 资金热度 | 3 | 0 | – | – | 0 | – | – |
| cn | 双低选股 | 3 | 0 | – | – | 0 | – | – |
| cn | 低波质量 | 3 | 0 | – | – | 0 | – | – |
| cn | 趋势质量 | 3 | 0 | – | – | 0 | – | – |
| cn | 超跌反转 | 3 | 0 | – | – | 0 | – | – |
| cn | 稳健价值 | 3 | 0 | – | – | 0 | – | – |
| cn | 缩量回踩 | 3 | 0 | – | – | 0 | – | – |
| cn | 放量突破 | 3 | 0 | – | – | 0 | – | – |
| hk | 全球低估值 | 3 | 5 | +1.12% | 60% | 0 | – | – |
| in | 全球低估值 | 3 | 5 | -1.84% | 20% | 0 | – | – |
| jp | 全球低估值 | 3 | 5 | +5.03% | 100% | 0 | – | – |
| kr | 全球低估值 | 3 | 5 | +6.47% | 100% | 0 | – | – |
| tw | 全球低估值 | 3 | 5 | -4.14% | 0% | 0 | – | – |
| us | 全球低估值 | 3 | 0 | – | – | 0 | – | – |
| us | US Momentum Quality | 3 | 0 | – | – | 0 | – | – |

## Latest session

- **asia** finished 2026-11-13T10:40:10+00:00: 15/15 strategies ok
- **us** finished 2026-11-13T22:34:45+00:00: 2/2 strategies ok

Raw runs: [`data/runs/`](data/runs) · derived site data: [`site/`](site)
