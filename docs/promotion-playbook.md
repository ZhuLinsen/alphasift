# AlphaSift 推广运营与开源增长手册（Promotion & Growth Playbook）

- **Repo**: [https://github.com/ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift)
- **Live Benchmark**: [https://alphasift.zhulinsen.tech/](https://alphasift.zhulinsen.tech/)
- **Baseline Snapshot**: 14 天内 `2,789` views / `1,314` unique visitors（Search referrals: `Google: 34`、`Bing: 17`、`Baidu: 2`），对比同作者生态项目 `ZhuLinsen/daily_stock_analysis`（`73.6k★`）与 `ZhuLinsen/alphaevo`（`233★`）存在巨大内外部引流杠杆空间。

---

## 1. 视觉资产与图文搭配（Promo Cards & Dashboard）

| 视觉素材 | 文件路径 | 核心信息 | 最佳投放渠道 |
|---|---|---|---|
| **Promo Card 1 — 总览英雄卡** | `docs/assets/promo/promo-card-1-overview.png` | `7 Markets` · `12 YAML` · `T+5/10/20 next_open` · `MCP + Workbench UI + Docker` | GitHub Discussions、X/Twitter 首图、V2EX/掘金封面 |
| **Promo Card 2 — 开源量化铁三角** | `docs/assets/promo/promo-card-2-trio.png` | `AlphaEvo (研究) -> AlphaSift (初筛+验证) -> daily_stock_analysis (L3精研)` | `daily_stock_analysis` / `AlphaEvo` 互链 PR、知乎长文、公众号 |
| **Promo Card 3 — 反过拟合与护栏** | `docs/assets/promo/promo-card-3-benchmark.png` | 涨停不可成交扣除 · 同日配对 Rules vs AI · 重大负面 `<=35` 代码级强封顶 | Show HN、Reddit `r/algotrading`、知乎量化专栏 |
| **Live Dashboard 实拍图** | `docs/assets/dashboard-dark.png` / `dashboard-light.png` | 真实公开 T+N 榜单、跨策略共振、7 市场领跑与暗/亮双主题 | Reddit `r/LocalLLaMA`、小红书图文、X Thread 第 2 帖 |

---

## 2. 第一优先级零成本杠杆：Quant Trio 生态互链（PR 现成文案）

> `ZhuLinsen/daily_stock_analysis` 拥有 **73.6k Stars**，单日自然访客远超所有外部社媒。直接在 DSA 与 AlphaEvo 仓库补齐生态漏斗互链，是转化率最高的精准流量来源。

### 2.1 `ZhuLinsen/daily_stock_analysis` README 增补片段（可直接提 PR）

**中文版位置建议：放在 README “生态联动 / 相关项目” 章节：**

```markdown
### 🔗 全市场初筛上游（Quant Trio 量化铁三角）

`daily_stock_analysis` 专注于单票 L3 深度研报与多源资讯汇总；如需在 **每日收盘后从全市场 5,000+ 标的中筛选高共识候选并公开验证 `T+5 / T+10 / T+20` 真实超额收益**，推荐配合上游同源仓库使用：

- **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** — L1/L2 多市场初筛与公开回测账本（覆盖 A股 / 美 / 港 / 日 / 韩 / 台 / 印 7 大市场、12 套 YAML 策略、重大负面 `<= 35` 分代码级封顶、原生 `alphasift mcp` & `DSA_API_URL` 联动）。
- **[AlphaEvo](https://github.com/ZhuLinsen/alphaevo)** — 进化式因子挖掘与样本外稳健性验证研究底座。
```

**English snippet for `daily_stock_analysis` README:**

```markdown
### 🔗 Upstream Market Screener (`Quant Trio`)

Looking to automatically shortlist 3–5 auditable candidates across 5,000+ equities after market close before deep-diving with `daily_stock_analysis`?

- **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** — Cross-market L1/L2 discovery across 7 exchanges (CN/US/HK/JP/KR/TW/IN), 12 deterministic YAML strategies, code-enforced LLM red-flag guardrails (`<= 35` cap), `alphasift mcp` STDIO tools, optional `DSA_API_URL` L3 hook, and a public `next_open` T+5/10/20 ledger.
```

### 2.2 `ZhuLinsen/alphaevo` README 增补片段

```markdown
### 🔗 Downstream Deployment & Live Tracking (`AlphaSift`)

Factors discovered cleanly in `AlphaEvo` can be promoted into deterministic YAML strategies and audited daily across live markets in **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** (public `track-record` branch with limit-up untradable accounting & Rules vs AI paired attribution).
```

---

## 3. 各平台即发文案模板（Copy-and-Paste Ready）

### 3.1 Hacker News — `Show HN`（建议发帖时间：美东周二/周三 09:00–11:00 EST）

- **Title**: `Show HN: AlphaSift – Auditable 7-market stock screener with next_open T+N benchmark and STDIO MCP`
- **Url**: `https://github.com/ZhuLinsen/alphasift`
- **Top Comment（作者首评）**:

> Hey HN — author here. I built **AlphaSift** after getting frustrated with two common failure modes in "AI stock picking" tools: (1) backtests that silently book paper profits on untradable limit-up opens, and (2) LLM agents overriding bad financial filings just because a stock is famous.
>
> Key design choices in AlphaSift v0.3:
> - **Deterministic L1/L2 base**: 12 auditable YAML strategies across 7 markets (CN/HK/US/JP/KR/TW/IN) with piecewise-linear quantile scoring and orthogonal sector caps (`hard_cap`).
> - **Code-enforced LLM guardrails**: optional L2 re-ranking runs via a zero-SDK `requests` OpenAI/Gemini client (works with OpenAI, Gemini, DeepSeek, Ollama), but adverse filings cap LLM score at `35.0` in Python—not just in a prompt—and omitted picks never keep stale scores.
> - **Paired attribution**: CN sessions log both deterministic `rules` and `ai` tracks side-by-side (when LLM credentials are configured and non-degraded) so you can measure whether AI actually adds excess return over rules (`T+5 / T+10 / T+20` vs index benchmark at `next_open`).
> - **MCP + Local Workbench**: `alphasift mcp` speaks zero-dependency STDIO JSON-RPC 2.0 (10 tools, 2 resources; read-only `scorecard` post-analysis without outbound pushes); `alphasift serve --port 8765` launches an offline-safe local Web UI at `/ui`. Install from source with `pip install -e .` (PyPI package publish queued in Week 1).
>
> Live verifiable ledger: https://alphasift.zhulinsen.tech/?lang=en
> Happy to answer questions on `next_open` entry timing and limit-up accounting, non-saturating factor curves, or MCP safety boundaries!

### 3.2 Reddit — `r/algotrading` & `r/LocalLLaMA`

**`r/algotrading` Title**: `Open-source 7-market YAML stock screener that measures whether LLM reranking actually beats deterministic rules (public next_open T+5/10/20 ledger)`
- **Attach**: `docs/assets/promo/promo-card-3-benchmark.png` + `docs/assets/dashboard-dark.png`
- **Body Highlights**: Emphasize `next_open` entry (not signal close), explicit `untradable_limit_up` denominator tracking, filter waterfall p25/p50/p75 quantiles, and portfolio exposure conflict detection. Strictly state research-only / zero investment advice.

**`r/LocalLLaMA` Title**: `Zero-SDK STDIO MCP stock research server + local Ollama/DeepSeek/OpenAI reranker with code-enforced <=35 adverse-filing caps`
- **Attach**: `docs/assets/promo/promo-card-1-overview.png`
- **Body Highlights**: Show 5-line Claude Code / Cursor `mcpServers` JSON snippet, zero external JS CDN Workbench UI (`/ui`), origin-isolated API key handling, and `<=35` Python guardrail override test.

### 3.3 X / Twitter 6-Post Thread（英文/双语高密度）

1. **1/6 (Hook + `promo-card-1-overview.png`)**: Most AI stock tools fail at two basic engineering checks: booking fake gains on untradable limit-up opens, and letting LLM vibes override regulatory probe filings. Introducing **AlphaSift v0.3** (Apache-2.0): 7 markets, 12 auditable YAML strategies, zero-SDK LLM guardrails, STDIO MCP, and a public `T+5/10/20` ledger.
2. **2/6 (`dashboard-dark.png`)**: Every session logs real picks publicly on GitHub Pages (`alphasift.zhulinsen.tech/?lang=en`). No cherry-picked screenshots: `next_open` entry pricing, matched index benchmarks (CSI 300 / S&P 500 / Nikkei / Hang Seng), and explicit `untradable_limit_up` tracking.
3. **3/6 (`promo-card-3-benchmark.png`)**: Does LLM re-ranking actually add alpha—or subtract it? AlphaSift runs Rules and AI tracks in parallel on identical dates/strategies so you can inspect `AI - Rules` paired delta, `AI Added`, and `AI Dropped` case studies.
4. **4/6**: Why prompts alone aren't safety: in AlphaSift, adverse regulatory/delisting/stake-sale keywords are capped at `35.0` in Python (`_LLM_RED_FLAG_MAX_SCORE`), with negated-phrase filtering (`"无立案调查"`). Zero `litellm` bloat—just clean `requests` + retry/redaction.
5. **5/6**: Connects straight into Claude Code, Cursor, Codex, and OpenClaw via `alphasift mcp` (10 tools) or local `alphasift serve --port 8765` (`/ui` Workbench, zero external CDN, hashed script CSP) + 1-line Docker Compose.
6. **6/6 (`promo-card-2-trio.png`)**: Pairs natively with `ZhuLinsen/daily_stock_analysis` (L3 single-stock deep research, 73.6k★) and `ZhuLinsen/alphaevo` (evolutionary alpha discovery). Star/fork with zero duplicate Pages clutter (Plan A fork guard): https://github.com/ZhuLinsen/alphasift

### 3.4 中文社区 — V2EX (`/go/share` or `/go/python`) · 知乎 · 掘金

- **V2EX 标题**：`开源了一个可验证的 7 市场量化初筛与 T+N 公开账本引擎 AlphaSift v0.3（支持 MCP / 本地 Web UI / Docker）`
- **知乎长文选题**：《为什么绝大多数“AI 选股”都在回测里作弊？我用 AlphaSift 做了一套可同日归因的公开基准》
- **结构拆解**：
  1. 痛点剖析：信号日收盘价买入的未来函数、`Z-score` 线性截断导致的头部扎堆、AI 看见“茅台/宁王”就无脑打高分的名气偏见。
  2. 工程解法：L1 分段线性非饱和打分、L2 重大负面 `<=35` 代码级强封顶、行业 `hard_cap: 1` 正交分散、规则 vs AI 同日配对归因。
  3. 即开即用：`alphasift mcp` 接入 Claude Code / Cursor / OpenClaw、`12` 通道 `NOTIFY_URLS` 一行推送、与 `daily_stock_analysis` 联动的 Quant Trio 全链路图（配 `promo-card-2-trio.png`）。

### 3.5 微信公众号 & 小红书图文模板（轻量化强视觉）

- **小红书标题（限 20 字内）**：`开源！给 AI 装上“不许吹票”的代码锁` / `把 73k 星选股项目做成全市场雷达`
- **小红书 4 图轮播顺序**：`promo-card-1-overview.png` -> `dashboard-light.png` -> `promo-card-2-trio.png` -> `promo-card-3-benchmark.png`
- **公众号次条/头条摘要**：用通俗案例讲清“同样是用大模型看股票，只靠提示词和有代码级红线、同日 Rules vs AI 对照实验的差异”，文末附 GitHub 与 Pages 体验地址。

---

## 4. SEO 与检索增长矩阵（GitHub / PyPI / 搜索引擎）

| 渠道 | 目标高频关键词 | 落地配置位置 |
|---|---|---|
| **GitHub Search / Topics** | `mcp`, `a-shares`, `stock-screener`, `quantitative-finance`, `ai-agent`, `backtesting`, `claude-code`, `openclaw`, `akshare`, `yfinance` | Repository Topics (`20/20`) + Bilingual Bio + `README*.md` 首屏 |
| **PyPI & `CITATION.cff`** | `quantitative-finance`, `stock-screener`, `mcp`, `multi-market`, `track-record`, `ai-agent`, `china-equities` | `pyproject.toml` keywords/classifiers + `CITATION.cff` |
| **Google / Bing 长尾词** | `"auditable stock screener mcp"`, `"rules vs llm stock selection benchmark"`, `"next_open survivorship bias python"`, `"alphasift serve"` | `README.en.md`、`docs/ecosystem.md`、`docs/result-schema.md`、Pages `<title>`/`<meta>` |
| **Baidu / 知乎 / 掘金中文词** | `A股 开源选股 MCP`, `Python 量化初筛 涨停不可成交`, `daily_stock_analysis 上游选股`, `Claude Code 选股 skill` | `README.md`（主中文）与 `dashboard-preview.gif`、知乎/掘金文章标题 |

---

## 5. 30 天冷启动增长日历与指标追踪

| 周期 | 动作清单 | 验证指标 & 目标 |
|---|---|---|
| **Week 1：生态内循环 + 基础指数收录** | 提交 `daily_stock_analysis` & `AlphaEvo` 互链 PR；确认 GitHub 20/20 Topics（含 `mcp`）；发布 PyPI 首版（同步 `pyproject.toml` keywords/classifiers）与 Bing/Google Pages sitemap 索引 | DSA 引流点击率、Google/Bing 品牌词检索收录、GitHub Stars 周增量 |
| **Week 2：英文开发者社区集中爆发** | 周二发布 `Show HN` + 同步 X Thread（4 张图）；周四发布 `r/LocalLLaMA`（主打 Zero-SDK MCP + Ollama）与 `r/algotrading`（主打 `next_open` 涨停不可成交口径） | 首页 Referral 峰值、Fork 启用数、Clones 数 |
| **Week 3：中文技术社区沉淀长尾搜索** | V2EX `/go/share` 工程向分享 + 知乎深度剖析长文 + 掘金 Docker/MCP 上手实战，全篇配 `promo-card-2/3` 清晰图解 | Baidu/知乎长尾搜索露出、`NOTIFY_URLS` 讨论与 Strategy Issue 数 |
| **Week 4：实盘数据复盘闭环** | 提取 `track-record` 累计 ≥10 天同日配对后的真实 `Rules vs AI` 归因数据，发布首期“实证月报”帖并反哺 README 示例与小红书图集 | 自然复访率（Unique/Views 比值）、社区 Strategy/Pattern PR 贡献 |
