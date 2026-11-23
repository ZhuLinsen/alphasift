# AlphaSift 推广运营与开源增长手册（Launch Kit & Growth Playbook）

- **Repo**: [https://github.com/ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift)
- **Live Benchmark**: [https://alphasift.zhulinsen.tech/](https://alphasift.zhulinsen.tech/)
- **Baseline Snapshot（2026-11-23）**：`547★` · `256 Forks` · `7 Watchers` · `v0.3.1` 已发布 · `655+ pytest tests` · **`T+5` 样本池已解锁（`2026-11-23` 榜单 `momentum_quality` `+2.86%` 净超额 / `85%` 胜率, `n=20`）**；14 天内 `2,523` views / `1,180` unique visitors、`6,450` clones / `1,880` unique cloners；对比同作者生态 `ZhuLinsen/daily_stock_analysis`（`73.7k★`）与 `ZhuLinsen/alphaevo`（`235★`）仍有显著漏斗放大空间。
- **线上 SEO 与埋点基建**：已上线 `social-preview.png`（1280×640）、`robots.txt`、`sitemap.xml`、`SoftwareApplication` JSON-LD、Atom 1.0 `site/feed.xml` 及可选零 Cookie Cloudflare Web Analytics（`CF_WEB_ANALYTICS_TOKEN`）。各渠道宣传统一附带 `?utm_source=<channel>` 参数便于归因。

---

## 0. 1-Minute Ops Launch Checklist（正式大规模分发前必检）

1. **开启每日 `AI 对照` 赛道积累同日配对样本（最高优先级）**：
   - 前往 `https://github.com/ZhuLinsen/alphasift/settings/secrets/actions` 添加 `GEMINI_API_KEY`（或 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`）。
   - 当前仓库 Actions Secrets 为空，`track-record` 仅跑纯规则赛道（看板显示 `AI 对照 | 0/10 配对日 · 待积累`）；配齐密钥后即可自动累积真实同日 `Rules vs AI` 归因样本，满 10 日即可产出一篇高说服力实证复盘。
2. **发布 PyPI 首版（降低 CLI / MCP 上手门槛）**：
   - 在 PyPI（[pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing/)）绑定 Trusted Publisher：Owner `ZhuLinsen`、Repo `alphasift`、Workflow `publish.yml`。
   - 到 Actions 手动触发 [`Publish to PyPI`](https://github.com/ZhuLinsen/alphasift/actions/workflows/publish.yml)（先跑 `testpypi` 验证后再选 `pypi`），随后社区用户即可直接 `pip install alphasift` / `uvx alphasift mcp`。
3. **可选开启零 Cookie 渠道统计（`CF_WEB_ANALYTICS_TOKEN`）**：
   - 在 Cloudflare Web Analytics 创建 `alphasift.zhulinsen.tech` 站点拿到 Token 后，写入仓库 Actions Variables：`CF_WEB_ANALYTICS_TOKEN=<hex_token>`，`track-record.yml` 发布 `_site/index.html` 与 `_site/site/daily_report.html` 时会自动注入，精确统计 `utm_source=linuxdo / xhs / v2ex / x / hn` 流量。
4. **落地 Quant Trio 仓库互链（见第 2 节 PR 文案）**：
   - 升级 `daily_stock_analysis`（`73.7k★`）顶部/相关项目互链（直指 `alphasift.zhulinsen.tech` 实时看板），并在 `AlphaEvo`（`235★`）README 补齐下游部署链接。

---

## 1. 视觉资产与图文搭配（Promo Cards & Live Captures）

> 提示：下列资产已于 `2026-11-22 / 11-23` 基于实时线上站点重拍与同步，可直接使用。

| 视觉素材 | 文件路径 | 核心信息 | 最佳投放渠道 |
|---|---|---|---|
| **Promo Card 1 — 总览英雄卡** | `docs/assets/promo/promo-card-1-overview.png` | `7 Markets` · `12 YAML` · `9 Empirical Patterns` · `T+5/10/20 next_open` · `620+ Tests` | X/Twitter 首图、LINUX DO、V2EX、掘金封面 |
| **Promo Card 2 — 开源量化铁三角** | `docs/assets/promo/promo-card-2-trio.png` | `AlphaEvo (研究) -> AlphaSift (初筛+验证) -> daily_stock_analysis (L3精研)` | `daily_stock_analysis` / `AlphaEvo` 互链、知乎长文、公众号 |
| **Promo Card 3 — 反过拟合与护栏** | `docs/assets/promo/promo-card-3-benchmark.png` | 涨停不可成交扣除 · 同日配对 Rules vs AI · 重大负面 `<=35` 代码级强封顶 | Show HN、Reddit `r/algotrading`、知乎量化专栏 |
| **Live Dashboard 中文暗色实拍** | `docs/assets/dashboard-zh.png` | 真实线上 A 股微观盘面（涨跌宽度 / 7×24 资讯）、策略曲线与 9 套形态雷达 | LINUX DO 晒图、小红书图 2、中文社区详情 |
| **Live Dashboard 英/日/亮暗对比** | `docs/assets/dashboard-light.png` · `dashboard-dark.png` · `dashboard-ja.png` | Editorial Paper Light / Obsidian Dark 三语切换实拍 | 小红书图集、X Thread、海外社区展示 |
| **Live Dashboard 动图轮播** | `docs/assets/dashboard-preview.gif` | 中暗主屏 → 策略追踪曲线 → 英亮主题 → 日暗主题 4 帧实拍轮播 | README 首屏、LINUX DO、V2EX 帖子配图 |
| **独立可打印盘后研报** | `docs/assets/daily-report.png` | `daily-report --output-html` 生成：盘后综述、7 档涨跌分布、公告排雷与 20 日迷你 K 线 | 小红书图 4、V2EX/知乎长文案例 |
| **1280×640 社交分享封面** | `docs/assets/social-preview.png` | GitHub Social Preview & Open Graph / Twitter Card 大图 | GitHub Settings、外链预览卡片 |

---

## 2. 第一优先级零成本杠杆：Quant Trio 生态互链（PR 现成文案）

> `ZhuLinsen/daily_stock_analysis` 拥有 **73.7k Stars**，当前仅顶部有单行 TIP 文字，补齐“实时公开看板 + 场景说明”是最直接的高转化导流；`AlphaEvo`（**235 Stars**）目前尚无反链。

### 2.1 `ZhuLinsen/daily_stock_analysis` README 增补片段

**中文版位置建议：放在 README “生态联动 / 相关项目” 或扩展章节：**

```markdown
### 🔗 全市场初筛上游（Quant Trio 量化铁三角）

`daily_stock_analysis` 专注于单票 L3 深度研报与多源资讯汇总；如需在 **每日收盘后从全市场 `5,000+` 标的中自动筛选高共识候选，并公开跟踪 `T+5 / T+10 / T+20` 真实超额收益**，推荐配合同源上游项目使用：

- **[AlphaSift](https://github.com/ZhuLinsen/alphasift)**（[公开在线看板](https://alphasift.zhulinsen.tech/?utm_source=dsa_readme)）— L1/L2 多市场初筛、250 日形态雷达与公开回测账本（覆盖 A股 / 美 / 港 / 日 / 韩 / 台 / 印 7 大市场、12 套 YAML 策略、重大负面 `<= 35` 分代码级封顶、原生 `alphasift mcp` & `DSA_API_URL` 一键联动）。
- **[AlphaEvo](https://github.com/ZhuLinsen/alphaevo)** — 进化式因子挖掘与样本外稳健性验证研究底座。
```

**English snippet for `daily_stock_analysis` README:**

```markdown
### 🔗 Upstream Market Screener (`Quant Trio`)

Looking to automatically shortlist 3–5 auditable candidates across 5,000+ equities after market close before deep-diving with `daily_stock_analysis`?

- **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** ([Live Dashboard](https://alphasift.zhulinsen.tech/?lang=en&utm_source=dsa_readme)) — Cross-market L1/L2 discovery across 7 exchanges (CN/US/HK/JP/KR/TW/IN), 12 deterministic YAML strategies, 9 empirical pattern detectors, code-enforced LLM red-flag guardrails (`<= 35` cap), zero-SDK `alphasift mcp` STDIO tools, optional `DSA_API_URL` L3 hook, and a public `next_open` T+5/10/20 ledger.
```

### 2.2 `ZhuLinsen/alphaevo` README 增补片段

```markdown
### 🔗 Downstream Deployment & Live Tracking (`AlphaSift`)

Factors discovered cleanly in `AlphaEvo` can be promoted into deterministic YAML strategies and audited daily across live markets in **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** ([Live Ledger](https://alphasift.zhulinsen.tech/?lang=en&utm_source=alphaevo_readme)) — complete with `next_open` limit-up untradable accounting and Rules vs AI paired attribution.
```

---

## 3. 各平台即发文案终稿（Copy-and-Paste Ready）

### 3.1 LINUX DO 发帖终稿（`/开发调优` 或 `/开源分享`）

- **标题**：`【开源】AlphaSift v0.3.1：形态雷达 + Walk-Forward 情绪门控 + T+5 (+2.86%/85% 胜率) 公开跟踪榜（零成本 Actions + 原生 MCP）`
- **链接（带归因）**：`https://alphasift.zhulinsen.tech/?lang=zh&utm_source=linuxdo` · `https://github.com/ZhuLinsen/alphasift`
- **配图顺序**：`docs/assets/dashboard-preview.gif`（或 `promo-card-1-overview.png`）→ `docs/assets/dashboard-zh.png` → `docs/assets/daily-report.png`
- **正文终稿**：

```markdown
继 `daily_stock_analysis` 之后，顺手把“全市场初筛 + Walk-Forward 情绪门控形态实证 + 公开事后账本”这段独立开源成了 **AlphaSift（v0.3.1）**。今天（2026-11-23）公开看板刚解锁首个达到 20 笔以上的 **`T+5` 榜单**：`momentum_quality`（趋势质量）净超额 **`+2.86%` / `85%` 胜率**（全策略加权 `+0.37%` / 297 股次 / 150 次运行）。

起因很简单：做单只股票的 AI 深度分析已经有很多方案了，但每天收盘后面对 A 股 5,000+ 只标的，“先看哪几只”一直缺少一个**透明、无 API Key 也能跑、并且敢把每天选出来的结果按同一口径持续核算 T+5/10/20 胜率**的上游筛选器。

👉 线上实时公开看板（每日 GitHub Actions 盘后自动构建部署）：https://alphasift.zhulinsen.tech/?lang=zh&utm_source=linuxdo
👉 GitHub 开源仓库（Apache-2.0）：https://github.com/ZhuLinsen/alphasift

### 做了哪些工程向设计？
1. **免 LLM 也能全量跑，接 LLM 也加了代码硬锁**
   - 内置 12 套透明 YAML 量化策略（`dual_low`、`volume_breakout`、`shrink_pullback` 等，覆盖 A股 / 美 / 港 / 日 / 韩 / 台 / 印 7 个市场）。
   - L1 层做硬筛选 + 分段线性打分 + **8 行业桶硬上限正交分散**（把 A 股策略间两两重合度从 8%~25% 压到 1%~2%，不让银行股把榜单占满）。
   - 接入大模型做 L2 复核时，直接走零外部 SDK 依赖的 `requests` OpenAI/Gemini 客户端（支持 DeepSeek / Gemini / OpenAI / Ollama / OpenRouter 等），并自动注入公告、新闻与资金流；**遇到未消除重大利空，直接在 Python 代码层面把得分封顶 `<= 35`**，防止模型“看见白马股就硬夸”。
2. **形态雷达 + 反作弊公开回测口径**
   - 内置 9 套无状态 K 线形态（红三兵、红三兵回踩确认、箱体突破等），结合私有 250 日离线日线包做样本外回放，必须同时过 25bp 成本扣除、Bartlett HAC t>=2.0、BH-FDR 多重检验校正及前后半样本稳定性门槛才会标为 `active`（当前阶段严苛门槛下 9 套全诚实标为 `experimental` 观察期，绝不强行美化）。
   - 所有线上跟踪统一按次日开盘价 **`next_open`** 计价，并单独剔除、标注**开盘一字涨停无法成交**的样本，拒绝用信号日收盘价算纸面富贵。
3. **30 秒本地跑通 / 原生接入 Claude Code & Cursor MCP**
   - 直接安装 `v0.3.1` Wheel 或源码安装：
     ```bash
     pip install https://github.com/ZhuLinsen/alphasift/releases/download/v0.3.1/alphasift-0.3.1-py3-none-any.whl
     alphasift quickstart                          # 无 Key 30 秒看全链路结果
     alphasift screen dual_low --no-llm            # 纯规则 A 股双低选股
     alphasift serve --host 127.0.0.1 --port 8765  # 本机离线安全 Web 工作台 (/ui)
     ```
   - 加 5 行配置即可作为零依赖 STDIO MCP Server 挂载给 AI 编程/桌面助手（10 个只读工具 + 2 个资源，默认不触发任何外部消息推送）：
     ```json
     {
       "mcpServers": {
         "alphasift": { "command": "alphasift", "args": ["mcp"] }
       }
     }
     ```
4. **Fork 零打扰 + 12 渠道一行推送**
   - Fork 后开启 GitHub Actions 即可用 `NOTIFY_URLS` 推到飞书/企微/钉钉/Telegram/Bark/PushPlus/邮件等 12 个渠道（带 token 脱敏与防重推双锁），默认跳过重复官网构建（`ALPHASIFT_ENABLE_PAGES=true` 才自建站点）。

项目已经带了 620+ pytest 单测和完整可打印独立盘后日报（`alphasift daily-report --output-html`），也支持通过 `DSA_API_URL` 串联 `daily_stock_analysis` 做 L3 精研。感谢 LINUX DO 佬友们的反馈，欢迎来看板围观每日实盘数据、提策略 PR 或压测提 Issue！（仅供技术研究与工程实验，不构成投资建议。）
```

---

### 3.2 小红书图文终稿（第三方推荐口吻 · 不违规不吹票）

- **可选标题（均严格 ≤ 20 字）**：
  1. `扒到一个神仙开源项目！全市场选股还公开战绩`
  2. `开源量化工具也太卷了，连一字涨停都帮你扣掉`
  3. `把 AI 选股和纯规则拉出来公开 PK，免费白嫖`
- **4 图轮播顺序**：
  1. **首图（封面吸睛）**：`docs/assets/promo/promo-card-1-overview.png`（或实拍 `docs/assets/dashboard-dark.png` 裁掉顶部网址微调）
  2. **图 2（真实看板）**：`docs/assets/dashboard-zh.png`（展示 A 股微观盘面、7×24 资讯和策略共识）
  3. **图 3（浅色/三语体验）**：`docs/assets/dashboard-light.png`
  4. **图 4（盘后独立研报）**：`docs/assets/daily-report.png`
- **正文终稿（第三人称安利视角）**：

```text
最近在 GitHub 逛开源工具的时候挖到一个宝藏项目叫 AlphaSift，用了几天觉得它的设计思路真的太戳痛点了，忍不住按头安利给喜欢用 Python / AI 辅助复盘的小伙伴👇

以前看很多“AI 选股”工具，总觉得有两件事特别虚：
❌ 只敢拿过去某一段涨得最好的截图做宣传，不敢把每天选出来的票留在公开网页上算 T+5、T+10、T+20 战绩；
❌ 回测按当天收盘价算买入，A 股好多强票第二天一字涨停根本买不进去，纯属纸面富贵。

而这个完全开源免费的工具直接反着来：
1️⃣ 公开透明的在线成绩单：每天收盘后 GitHub Actions 自动跑完 7 个市场（A股/美股/港股/日韩台印），选出来的票、每条策略的净值曲线、9 套 K 线形态雷达直接挂在公开网页上，按次日开盘价算收益，买不进去的一字板还会单独统计剔除，不玩虚的。
2️⃣ 规则打底 + AI 装“防吹票锁”：可以完全不配 API Key 用纯规则 YAML 策略跑；如果接大模型复核，系统会把公司公告、新闻和资金流一起喂进去，代码层面写死了遇到重大负面风险直接封顶压分，不让 AI 瞎吹。
3️⃣ 盘后自动出可打印日报 + 一键推送：还会总结当天全市场涨跌分布、情绪温度、个股 20 日迷你 K 线图，支持飞书/企微/Bark/邮箱等十几种通知方式，还能接 Claude / Cursor 里当技能工具直接对话调用。

⚠️ 提前叠个甲：作者写得很清楚，纯属开源工程和量化研究工具，不构成任何投资建议～但作为日常盘后复盘省时间、做数据筛选的雷达，免费还代码开源，真的比市面上很多收费“黑盒选股软件”良心太多了！

#开源项目 #量化研究 #AI工具 #Python #程序员副业工具 #GitHub宝藏项目 #复盘工具
```
- **置顶评论引导（规避站外直链限流）**：
  `感兴趣的可以直接去 GitHub 搜 "ZhuLinsen/alphasift" 或者搜同名项目主页（页面可以直接看每天盘后自动更新的公开看板和盘后日报截图，本地一行命令也能直接跑起来~）`

---

### 3.3 V2EX `/go/share` 终稿（配合 v0.3.1 发布）

- **Title**: `开源了一个可验证的 7 市场量化初筛与 T+N 公开账本引擎 AlphaSift v0.3.1（刚解锁 T+5 +2.86% 实时榜单 / 原生 MCP / Walk-Forward 情绪门控）`
- **Url**: `https://alphasift.zhulinsen.tech/?lang=zh&utm_source=v2ex`
- **要点**：重点写清楚“上次分享后完善了 v0.3.1 闭环”——新增 A 股全市场 250 日离线日线包与 `walk_forward_regime_audit` 零前视 H1→H2 情绪门控校验、9 套形态雷达（FDR + HAC 检验下全部诚实标观察期）、`T+5` 榜单首个达成 `n>=20` 解锁（`momentum_quality` `+2.86% / 85% 胜率`）、`next_open` 涨停不可成交核算、独立可打印盘后 HTML 日报、10 工具零依赖 STDIO MCP 与本地 `/ui` 工作台。附 `promo-card-1-overview.png` + `dashboard-preview.gif`。

---

### 3.4 Hacker News — `Show HN`（建议美东周二/周三 09:00–11:00 EST）

- **Title**: `Show HN: AlphaSift – Auditable 7-market stock screener with next_open T+N benchmark and STDIO MCP`
- **Url**: `https://github.com/ZhuLinsen/alphasift`
- **Top Comment（作者首评）**：

> Hey HN — author here. I built **AlphaSift** after getting frustrated with two common failure modes in "AI stock picking" tools: (1) backtests that silently book paper profits on untradable limit-up opens, and (2) LLM agents overriding bad financial filings just because a stock is famous.
>
> Key design choices in AlphaSift v0.3.1:
> - **Deterministic L1/L2 base**: 12 auditable YAML strategies across 7 markets (CN/HK/US/JP/KR/TW/IN) with piecewise-linear quantile scoring and orthogonal sector caps (`hard_cap`).
> - **Code-enforced LLM guardrails**: optional L2 re-ranking runs via a zero-SDK `requests` OpenAI/Gemini client (works with OpenAI, Gemini, DeepSeek, Ollama), but adverse filings cap LLM score at `35.0` in Python—not just in a prompt—and omitted picks never keep stale scores (flagged `1` live case on `2026-11-23`).
> - **Empirical 250D pattern radar & Walk-Forward regime gate (no cherry-picking)**: 9 stateless pattern detectors must pass 25bp round-trip costs, Bartlett HAC `t >= 2.0`, Benjamini-Hochberg FDR `q <= 0.05`, H1/H2 subsample stability, and zero-snooping H1→H2 regime selection (`--allowed-regimes` / `--exclude-regimes`) before leaving `experimental` status (today all 9 are honestly marked `experimental`).
> - **Paired attribution & unlocked T+5 milestone**: CN sessions log `rules` and `ai` tracks side-by-side (`next_open` entry); first `n >= 20` cohort unlocked `2026-11-23` with `momentum_quality` at `+2.86%` net excess / `85%` beat rate across `150` runs.
> - **MCP + Local Workbench**: `alphasift mcp` speaks zero-dependency STDIO JSON-RPC 2.0 (10 tools, 2 resources; read-only without outbound pushes); `alphasift serve --port 8765` launches an offline-safe local Web UI at `/ui`. Install directly via the v0.3.1 release wheel or `pip install -e .`.
>
> Live verifiable ledger: https://alphasift.zhulinsen.tech/?lang=en&utm_source=hn
> Happy to answer questions on `next_open` entry timing and limit-up accounting, FDR/HAC pattern graduation, or MCP safety boundaries!

---

### 3.5 Reddit — `r/algotrading` & `r/LocalLLaMA`

- **`r/algotrading` Title**: `Open-source 7-market YAML stock screener & 250D pattern radar with public next_open T+5/10/20 ledger`
  - **Attach**: `docs/assets/promo/promo-card-3-benchmark.png` + `docs/assets/dashboard-dark.png`
  - **Link**: `https://alphasift.zhulinsen.tech/?lang=en&utm_source=reddit_algotrading`
  - **Body Highlights**: Emphasize `next_open` entry (not signal close), explicit `untradable_limit_up` denominator tracking, BH-FDR (`q <= 0.05`) + Bartlett HAC (`t >= 2.0`) gating why all 9 patterns remain honestly labeled `experimental`, and orthogonal 8-sector bucket caps. Strictly state research-only / zero investment advice.
- **`r/LocalLLaMA` Title**: `Zero-SDK STDIO MCP stock research server + DeepSeek/Ollama/OpenAI reranker with code-enforced <=35 adverse-filing caps`
  - **Attach**: `docs/assets/promo/promo-card-1-overview.png` + `docs/assets/daily-report.png`
  - **Link**: `https://alphasift.zhulinsen.tech/?lang=en&utm_source=reddit_localllama`
  - **Body Highlights**: Show 5-line Claude Code / Cursor `mcpServers` JSON snippet, `620+ pytest tests`, zero external JS CDN Workbench UI (`/ui`), redacted error logging, and the `<= 35` Python guardrail override test.

---

### 3.6 X / Twitter 6-Post Thread（已验证 `t.co` 为站外第一流量引擎）

1. **1/6 (Hook + `promo-card-1-overview.png`)**: Most AI stock tools fail at two basic engineering checks: booking fake gains on untradable limit-up opens, and letting LLM vibes override regulatory probe filings. Introducing **AlphaSift v0.3.1** (Apache-2.0): 7 markets, 12 YAML strategies, 9 FDR + Walk-Forward checked patterns, zero-SDK MCP, and a live `T+5` ledger just unlocked at `+2.86%` / `85%` beat rate (`n=20`).
2. **2/6 (`dashboard-dark.png`)**: Every session logs real picks publicly (`https://alphasift.zhulinsen.tech/?lang=en&utm_source=x`). No cherry-picked screenshots: `next_open` entry pricing, matched index benchmarks (CSI 300 / S&P 500 / Nikkei / Hang Seng), and explicit `untradable_limit_up` tracking.
3. **3/6 (`promo-card-3-benchmark.png`)**: We refuse to overfit: our 250-day pattern radar requires beating both CSI 300 & All-A equal-weight after 25bp costs, plus Bartlett HAC `t >= 2.0`, BH-FDR `q <= 0.05`, and H1/H2 stability — so today all 9 detectors stay honestly flagged `experimental`.
4. **4/6**: Why prompts alone aren't safety: in AlphaSift, adverse regulatory/delisting/stake-sale keywords are capped at `35.0` in Python (`_LLM_RED_FLAG_MAX_SCORE`), with negated-phrase filtering (`"无立案调查"`). Zero `litellm` bloat—just clean `requests` + key redaction.
5. **5/6 (`daily-report.png`)**: Connects straight into Claude Code, Cursor, Codex, and OpenClaw via `alphasift mcp` (10 tools) or local `alphasift serve --port 8765` (`/ui` Workbench) + printable post-close HTML daily reports + 1-line `NOTIFY_URLS` across 12 channels.
6. **6/6 (`promo-card-2-trio.png`)**: Pairs natively with `ZhuLinsen/daily_stock_analysis` (L3 single-stock deep research, `73.7k★`) and `ZhuLinsen/alphaevo` (`235★`). Star/fork safely with zero duplicate Pages clutter: `https://github.com/ZhuLinsen/alphasift`

---

### 3.7 知乎 & 微信公众号长文（第 2 波 / 攒满 10 个 AI 配对日后收割长尾）

- **知乎长文选题**：《为什么绝大多数“AI 选股”都在回测里作弊？我做了套全公开可核验的量化基准（附开源代码）》
- **核心结构**：
  1. 揭穿回测三大作弊点：信号日收盘买进的未来函数、一字涨停纸面富贵、9 种技术形态不做多重检验校正直接上线；
  2. 工程解法：L1 分段线性打分 + 8 行业桶硬上限正交分散 + L2 重大利空 `<= 35` 代码硬锁 + Bartlett HAC & BH-FDR 毕业门控；
  3. 生态闭环：从 `AlphaEvo` 挖因子 → `AlphaSift` 初筛与公开跟踪 → `daily_stock_analysis` 深度研报（配 `promo-card-2-trio.png` + `daily-report.png`）。

---

## 4. SEO 与检索增长矩阵（GitHub / PyPI / 搜索引擎）

| 渠道 | 目标高频关键词 | 落地配置位置 |
|---|---|---|
| **GitHub Search / Topics** | `mcp`, `a-shares`, `stock-screener`, `quantitative-finance`, `ai-agent`, `backtesting`, `claude-code`, `openclaw`, `akshare`, `yfinance` | Repository Topics（`20/20`）+ Bilingual Bio + `README*.md` |
| **PyPI & `CITATION.cff`** | `quantitative-finance`, `stock-screener`, `mcp`, `multi-market`, `track-record`, `ai-agent`, `china-equities` | `pyproject.toml` keywords/classifiers（待完成 Trusted Publisher 首版发布） |
| **Google / Bing 长尾词** | `"auditable stock screener mcp"`, `"rules vs llm stock selection benchmark"`, `"next_open survivorship bias python"`, `"alphasift serve"` | `robots.txt`、`sitemap.xml`、`SoftwareApplication` JSON-LD、`docs/*.md` |
| **Baidu / 知乎 / 掘金 / 小红书** | `A股 开源选股 MCP`, `Python 量化初筛 涨停不可成交`, `daily_stock_analysis 上游选股`, `Claude Code 选股 skill` | `README.md`（主中文）+ `dashboard-preview.gif` + 社区文章与图文 |

---

## 5. 30 天冷启动增长日历与指标追踪

| 周期 | 动作清单 | 验证指标 & 目标 |
|---|---|---|
| **Week 1：基建补齐 + 中文首波分发** | ① 配置 `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` 启动每日 `AI 对照` 累积；② 发布 PyPI 首版；③ 合并 `#69`（推理模型 `finish_reason=length` 自动扩容）；④ 发 **LINUX DO** + **小红书**（第三人称）+ **V2EX `/go/share`**，更新 `DSA`/`AlphaEvo` 互链 | AI 配对日开始增长（`1..10/10`）、PyPI 下载数、GitHub `views` & `Stars` 增量、`utm_source` 来源分布 |
| **Week 2：英文开发者社区集中爆发** | 周二晚美东上午发 `Show HN` + 同步 X 6 连英文 Thread；周四发 `r/LocalLLaMA`（主打 Zero-SDK MCP + 推理模型自动扩容）与 `r/algotrading`（主打 `next_open` 涨停不可成交 + BH-FDR） | `t.co` / `news.ycombinator` / `reddit` Referral 峰值、Fork 启用数、Discussions 首批讨论帖 |
| **Week 3：中文技术社区沉淀长尾搜索** | 知乎深度剖析长文 + 掘金 Docker/MCP 上手实战 + 公众号图文推送（均配 `promo-card-2/3` 与 `daily-report.png`） | Google/Bing/Baidu 长尾词收录、Strategy Proposal / Discussions 数量 |
| **Week 4：10 日实盘 AI 对照复盘闭环** | 攒满 ≥10 个同日配对日后，提取真实 `Rules vs AI` 净超额与 `AI Added / AI Dropped` 案例发布首期“实证月报”，反哺 README 与全网二次传播 | 看板自然复访率（`Views / Uniques` 比值提升）、外部 Strategy / Pattern PR 贡献 |
