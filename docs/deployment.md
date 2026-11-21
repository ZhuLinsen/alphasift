# 部署、Fork 启用与 Cloudflare Pages 镜像说明

AlphaSift 当前看板定位为**量化形态观测与回测基准**，仅供研究与后验验证，不作自动交易或投资建议。

## Fork 后 3 步启用（非“一键自动跑”）

由于 GitHub 对 Fork 仓库默认**禁用定时 workflow**，且 **GitHub Pages 默认关闭**，“Fork 即一键拥有”并不成立。请按以下 3 步开启：

1. **启用 GitHub Actions**：进入 Fork 仓库的 **Actions** 页签，点击允许运行工作流（特别是 `track-record.yml`）。如需在自动筛选中开启 **AI 赛道** 或 **IM 推送**，在 *Settings → Secrets and variables → Actions* 按需配置可选 Secrets：
   - 可选 AI：`DEEPSEEK_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY`（未配置时自动仅跑纯规则赛道，不报错）。
   - 可选 IM 推送：`WECOM_WEBHOOK_URL`、`FEISHU_WEBHOOK_URL`（可选 `FEISHU_WEBHOOK_SECRET`）、`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`（未配置时静默跳过）。
2. **手动开启 GitHub Pages**：进入 *Settings → Pages*，将 Source 设为 `GitHub Actions`（或按需托管 `track-record` 分支静态产物）。如需覆盖 IM 卡片详情链接，可在 *Settings → Secrets and variables → Actions → Variables* 设置 `ALPHASIFT_DASHBOARD_URL`（以及可选切换日期 `ALPHASIFT_NEXT_OPEN_SWITCH_DATE`）。
3. **验证环境与手动首发**：
   - 本地可用 `alphasift doctor radar --explain` 一次检查日线包新鲜度、形态目录同步、LLM 与 IM 推送就绪状态（输出不泄露任何密钥）。
   - `track-record.yml` 亚洲盘会先串行调用 `data-pack.yml` 在 GitHub Actions 内部私有缓存（`actions/cache`）中构建或增量更新日线包（不对外公开分发 `daily.npz` / `meta.csv.gz` 原始行情资产），再执行选股、`Daily report`（产出 `site/report.json` 与可打印独立研报 `site/daily_report.html`，配置 LLM Key 时自动附带 `--ai-brief auto` 综述，并在包新鲜时幂等推送）与 `Build site data`。若数据包构建超时或落后于目标交易日，下游会标为 `pack_is_stale=True` 做降级网页展示，且自动跳过未强制的 IM 推送。
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

- **形态毕业门槛**：在 250 日 A 股数据包上按 `next_open` 口径回放，`T+5 样本 >= 200` 且 `T+5 相对沪深 300 超额 > 0%` 才标记 `active` 进默认日报；其余标记 `experimental` 并置灰提示。
- **情绪阶段切片**：`冰点 / 启动 / 主升 / 分歧 / 退潮 / 震荡` 仅作报告与切片观察维度；只有当 `形态 × 阶段` 格点样本数 `>= 100` 且长期表现差异稳定时，才会在后续迭代中评估是否引入权重逻辑（看板对样本 `< 100` 的格点强制置灰并标 `*`）。
- **多模型委员会推迟条件**：单模型 `rules` vs `ai` 双赛道至少积累 `>= 60` 个交易日的同口径后验战绩后再作评估。
