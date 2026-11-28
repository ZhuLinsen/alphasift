# 部署、Fork 启用与 Cloudflare Pages 镜像说明

AlphaSift 当前看板定位为**量化形态观测与回测基准**，仅供研究与后验验证，不作自动交易或投资建议。

## Fork 后 3 步启用（非“一键自动跑”）

由于 GitHub 对 Fork 仓库默认**禁用定时 workflow**，且 **GitHub Pages 默认关闭**，“Fork 即一键拥有”并不成立。请按以下 3 步开启：

1. **启用 GitHub Actions**：进入 Fork 仓库的 **Actions** 页签，点击允许运行工作流（特别是 `track-record.yml`）。如需在自动筛选中开启 **AI 赛道** 或 **通知推送**，在 *Settings → Secrets and variables → Actions* 按需配置可选 Secrets：
   - 可选 AI：`DEEPSEEK_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY`（支持 `LLM_CHANNELS` 与 `LLM_DEEPSEEK_*` / `LLM_GEMINI_*` / `LLM_OPENAI_*`、`LLM_MODEL`、`LLM_FALLBACK_MODELS`、`OPENAI_BASE_URL`；可选 `TAVILY_API_KEYS` / `SERPAPI_API_KEYS` 作为盘后市场快讯与个股新闻兜底；CN AI 赛道默认开启 `LLM_CANDIDATE_CONTEXT_ENABLED=true`，注入公告/资讯/资金流上下文并启用红线风控；未配置 Key 时自动仅跑纯规则赛道，不报错）。
   - 可选通知推送：推荐一行配置 **`NOTIFY_URLS`**（逗号/换行分隔多目标 URL，零依赖自动嗅探 **12 种原生通道**：`wecom://`、飞书 `https://open.feishu.cn/...`、钉钉 `https://oapi.dingtalk.com/...`、`pushplus://`、`sct://`（Server酱/³）、`bark://`、`mailto://`（SMTP 邮件）、`tgram://`（Telegram）、Discord、`https://hooks.slack.com/...`、`ntfy://`、`custom://`，装了 `apprise` 时亦可自动兜底 90+ 平台；同时完全兼容传统单通道环境变量如 `WECOM_WEBHOOK_URL`、`FEISHU_WEBHOOK_URL`、`DINGTALK_WEBHOOK_URL`、`PUSHPLUS_TOKEN`、`SERVERCHAN_SENDKEY`、`BARK_URL`、`EMAIL_SENDER`+`EMAIL_PASSWORD`+`EMAIL_RECEIVERS`+可选`EMAIL_SMTP_HOST`/`EMAIL_SMTP_PORT`、`TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID`、`DISCORD_WEBHOOK_URL`、`SLACK_WEBHOOK_URL`、`NTFY_URL`、`CUSTOM_WEBHOOK_URL`），未配置时静默跳过。支持 `alphasift daily-report --markets us` 等多市场简报推送。
2. **手动开启 GitHub Pages（Plan A Fork 安全防护）**：为避免用户 Fork 后直接自动上线一份一模一样的公开网站，工作流默认**仅在 `ZhuLinsen/alphasift` 上生成并部署网页**；Fork 仓库默认只执行选股扫描、AI 复核与推送通知（推送消息自动隐藏作者官网链接，避免误导）。若确需在 Fork 独立部署网站，须在 *Settings → Secrets and variables → Actions → Variables* 设置 **`ALPHASIFT_ENABLE_PAGES=true`**，并进入 *Settings → Pages* 将 Source 设为 `GitHub Actions`（同时可按需设置 `ALPHASIFT_DASHBOARD_URL` 与 `ALPHASIFT_NEXT_OPEN_SWITCH_DATE`；开启 `ALPHASIFT_ENABLE_PAGES=true` 时会自动推导 `https://<owner>.github.io/<repo>/`）。
   - 公开看板与独立研报支持 `?lang=zh|en|ja` 多语言切换与 `?theme=dark|light` 主题持久化，并在页面底部低调提供 `site/feed.xml` Atom 1.0 订阅源（无配置要求）。
3. **验证环境与手动首发**：
   - 本地可用 `alphasift doctor radar --explain` 与 `alphasift notify status` / `alphasift notify test --dry-run` 一次检查日线包新鲜度、形态目录同步、LLM 与推送渠道就绪状态（输出不泄露任何密钥）。
   - `track-record.yml` 亚洲盘会先串行调用 `data-pack.yml` 在 GitHub Actions 内部私有缓存（`actions/cache`）中构建或增量更新日线包（不对外公开分发 `daily.npz` / `meta.csv.gz` 原始行情资产），再执行选股、`Daily report`（产出 `site/report.json` 与可打印独立研报 `site/daily_report.html`，自动聚合东财/同花顺/新浪快讯、20 只高共识优先公告消歧排雷，配置 LLM Key 时自动附带 `--ai-brief auto` 综述，并在包新鲜时幂等推送）与 `Build site data`；美股盘会触发 `alphasift daily-report --markets us` 全球简报推送。若数据包构建超时或落后于目标交易日，下游会标为 `pack_is_stale=True` 做降级网页展示，且自动跳过未强制的 IM 推送。
   - 在 GitHub **Actions → Track record → Run workflow** 手动触发一次 `asia` 或 `rebuild` 确认落盘与页面正常构建。

## Cloudflare Pages 静态镜像（仅文档方案）

若希望为看板提供境内/多线镜像，可直接用 Cloudflare Pages 零构建托管公开战绩分支 `track-record`（无需改动仓库代码）：

1. 登录 Cloudflare Dashboard → **Workers & Pages → Create → Pages → Connect to Git**，选择本仓库（或你的 Fork）。
2. 构建配置如下：
   - **Production branch**：`track-record`
   - **Framework preset**：`None`
   - **Build command**：留空
   - **Build output directory**：`.`（仓库根目录直接包含 `index.html` 与 `site/`）
3. 保存后每次 `track-record` 分支更新都会自动触发静态镜像部署。

## 看板中的门槛与演化约定

- **形态毕业门槛**：在 250 日 A 股数据包上按 `next_open` 口径回放，`T+5 样本 >= 200`、扣除 `25bp` 往返成本后相对沪深 300 与同日全 A 等权均值均为正、Bartlett Newey-West HAC 检验 `t >= 2.0`、BH-FDR 校正 `q <= 0.05` 且前/后半样本（`H1/H2 >= 15d & >= 30`）同向为正时才晋级 `active`；其余标记 `experimental` 并在看板与日报中区分观察。
- **情绪阶段切片**：`冰点 / 启动 / 主升 / 分歧 / 退潮 / 震荡` 仅作报告与切片观察维度；只有当 `形态 × 阶段` 格点样本数 `>= 100` 且长期表现差异稳定时，才会在后续迭代中评估是否引入权重逻辑（看板对样本 `< 100` 的格点强制置灰并标 `*`）。
- **多模型委员会推迟条件**：单模型 `rules` vs `ai` 双赛道至少积累 `>= 60` 个交易日的同口径后验战绩后再作评估。

## PyPI Trusted Publishing（手动触发）

仓库内置了 [`.github/workflows/publish.yml`](../.github/workflows/publish.yml)（仅 `workflow_dispatch` 手动触发，避免未配置 OIDC 前误报失败），用于发布稳定 wheel / sdist 至 PyPI 或 TestPyPI：

1. 登录 PyPI（或 TestPyPI）→ **Your projects / Publishing → Add a new pending publisher**：
   - **PyPI Project Name**：`alphasift`
   - **Owner**：`ZhuLinsen`
   - **Repository name**：`alphasift`
   - **Workflow name**：`publish.yml`
2. 配置完成后执行：
   ```bash
   gh workflow run publish.yml --repo ZhuLinsen/alphasift -f target=pypi
   ```
   即可免长期 API Token、通过 GitHub OIDC 构建并发布 `alphasift` 到 PyPI。
