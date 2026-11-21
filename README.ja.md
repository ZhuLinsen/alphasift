<div align="center">

<a href="https://zhulinsen.github.io/alphasift/?lang=ja">
  <img src="docs/assets/alphasift-logo.svg" alt="AlphaSift Logo" width="680">
</a>

# 🔎 AlphaSift

**オープンソース全市場 AI 株式スクリーナー・250日実証パターン検出・公開 T+N 検証ベンチマーク**

*中国A株・米国・香港・日本・韓国・台湾・インドの7市場 → 監査可能な YAML 戦略 → 開示リスク重視 AI 再ランク → 1行12チャネル通知＆T+5/10/20 公開検証*

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/alphasift?style=social)](https://github.com/ZhuLinsen/alphasift/stargazers)
[![CI](https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhuLinsen/alphasift/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3b82f6.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-10b981.svg)](LICENSE)
[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-0ea5e9.svg)](https://zhulinsen.github.io/alphasift/?lang=ja)
[![7 Markets](https://img.shields.io/badge/Markets-CN%20%7C%20US%20%7C%20HK%20%7C%20JP%20%7C%20KR%20%7C%20TW%20%7C%20IN-6366f1.svg)](https://zhulinsen.github.io/alphasift/?lang=ja)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-OpenClaw%20%7C%20Claude%20Code-10b981.svg)](SKILL.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/ZhuLinsen/alphasift/pulls)

[**ライブダッシュボード**](https://zhulinsen.github.io/alphasift/?lang=ja) · [**AlphaSift の特長**](#-なぜ-alphasift-なのか) · [**4つの始め方**](#-4-つのゼロ摩擦スタート) · [**1行12チャネル通知**](#-1行-notify_urls-通知チャネル一覧12種標準対応) · [**track-record 生ログ**](https://github.com/ZhuLinsen/alphasift/tree/track-record) · [**Agent Skill**](SKILL.md)

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

</div>

---

## ✨ なぜ AlphaSift なのか

多くの AI 銘柄分析ツールは単発のチャット要約や過学習したバックテストに留まります。**AlphaSift は全市場スクリーニング・開示情報連動 AI 再評価・公開事後検証を一つの透明なパイプラインへ統合しています：**

1. **API キー不要の決定的基盤＆直交分散**：L1 ハードフィルタ、マルチファクター評価、8 業種バケット上限分散（`portfolio_profile.mode: hard_cap`、`max_same_bucket: 1`）は API キーなしで決定的に動作します。中国 A 株 10 戦略の直交化により、250 日パック 3 時点検証で戦略間の平均重複率は **8.0%–24.9% → 0.9%–1.8%**（最大 **100% → 20%**）、銀行セクター集中度は **22%–31.1% → 4.0%–9.1%** へ低減しました。
2. **250日 `next_open` 実証パターン検出**：過去 180 営業日・5,218 銘柄の実証リプレイで `T+5 一致 >= 200` かつ `対 CSI 300 超過 > 0%` の条件を満たした 2 パターンのみ `active` 認定し、他の 5 パターンは `experimental` として分離しています。
3. **開示・資金フロー連動レッドライン AI**：標準モデル **`gemini/gemini-3.8-flash`**（`gemini/gemini-4-hydrogen` 自動フォールバック）をはじめ DeepSeek / OpenAI / Ollama に対応。`LLM_CANDIDATE_CONTEXT_ENABLED=true` により上位 12 銘柄の適時開示・ニュース・資金フローを注入し、重大な未解消悪材料は **`llm_score <= 35`** に制限（知名度バイアス禁止）、同日の `rules` vs `ai` 超過寄与を比較します。
4. **公開 `next_open` T+N 台帳・1行通知・Fork 保護**：毎日の選定は `track-record` ブランチへ記録され、`T+5 / T+10 / T+20` でベンチマーク比較されます。1行 **`NOTIFY_URLS`** で 12 チャネルへ通知でき、**Plan A Fork 保護**により Fork リポジトリは `ALPHASIFT_ENABLE_PAGES=true` を設定しない限り重複サイトを公開せず、スキャンと通知のみ安全実行します。

<table>
  <tr>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=ja&theme=dark">
        <img src="docs/assets/dashboard-ja.png" alt="AlphaSift ライブダッシュボード（ダーク・日本語）" width="100%">
      </a>
      <br><sub><b>Obsidian Dark ターミナル（日本語）</b> — 複数戦略コンセンサス、A 株7段階騰落分布、7市場ランキング</sub>
    </td>
    <td width="50%" align="center">
      <a href="https://zhulinsen.github.io/alphasift/?lang=en&theme=light">
        <img src="docs/assets/dashboard-light.png" alt="AlphaSift ライブダッシュボード（ライト・多言語切替）" width="100%">
      </a>
      <br><sub><b>Editorial Paper Light</b> — ヘッダーの <code>中 | EN | 日</code> で即座に言語切替、検証済みトラックレコード</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <a href="docs/usage.md">
        <img src="docs/assets/daily-report.png" alt="AlphaSift 日次リサーチレポート" width="88%">
      </a>
      <br><sub><b>印刷対応スタンドアロン日次レポート</b>（<code>alphasift daily-report --output-html</code>）— 引け後要約、適時開示チェック、20日ローソク足検出</sub>
    </td>
  </tr>
</table>

---

## ⚡ 4 つのゼロ摩擦スタート

### 1. API キー不要・30秒で全市場スキャン
```bash
git clone https://github.com/ZhuLinsen/alphasift.git && cd alphasift
pip install -e .

alphasift quickstart
alphasift screen dual_low --no-llm
alphasift screen global_value --market jp --no-llm
```

### 2. LLM 再ランク・250日リプレイ・日次 HTML レポート
```bash
cp .env.example .env   # GEMINI_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY を設定
alphasift screen dual_low --save-run
alphasift patterns replay --pack-dir ./data/pack/cn --output-md replay.md
alphasift daily-report --pack-dir ./data/pack/cn --output-html daily_report.html --push
```

### 3. Claude Code・OpenClaw・Cursor・Codex と連携（`SKILL.md` + HTTP API + Python）
[SKILL.md](SKILL.md) または [agents/openai.yaml](agents/openai.yaml) をエージェントへ読み込み、Python 呼び出しまたはローカル HTTP API で利用できます：
```python
from alphasift import screen

res = screen("dual_low", market="cn", use_llm=False)
for pick in res.picks:
    print(pick.rank, pick.code, pick.name, pick.industry, pick.final_score)
```
```bash
alphasift serve --host 127.0.0.1 --port 8000   # エージェント向け読み取り専用 JSON API
```

### 4. GitHub Actions で完全自動実行＆1行通知
1. リポジトリを Fork し **GitHub Actions** を有効化します。
2. *Settings -> Secrets and variables -> Actions -> Secrets* に `GEMINI_API_KEY`（任意）および `NOTIFY_URLS`（任意）を設定します。
3. **Plan A Fork Pages 保護**：Fork 先では重複サイト公開を防ぐため、Variables に `ALPHASIFT_ENABLE_PAGES=true` を設定しない限り GitHub Pages デプロイをスキップし、スクリーニングと通知のみ動作します。

---

## 🧭 既存ツールとの比較

| 比較軸 | 一般スクリーナー (`TradingView` 等) | 個別銘柄 AI 分析 (`daily_stock_analysis`) | マルチエージェント議論 (`TradingAgents`) | **AlphaSift** |
|---|---|---|---|---|
| **対象範囲** | 1市場ずつ手動条件絞り込み | 指定済みウォッチリスト深掘り | 単一銘柄のロールプレイ議論 | **7市場全量スクリーニング (CN/US/HK/JP/KR/TW/IN)** |
| **再現性と業種分散** | ブラックボックス / 手動設定 | プロンプト主導 | 会話合意 | **監査可能 YAML DSL ＋ 8業種 `hard_cap` 直交分散** |
| **AI ガードレール** | なし | 個別銘柄ナラティブ | 対話コンセンサス | **適時開示/資金フロー注入 ＋ 悪材料 `<= 35` 上限 ＋ 知名度バイアス禁止** |
| **事後検証** | なし | 手動振り返り | オフライン再生 | **公開 `track-record` 台帳 (`next_open` T+5/10/20＆ストップ高除外)** |
| **連携性** | 単体 UI | **後段 L3 詳細分析と好相性** | 個別スクリプト | **上流候補発掘 (`DSA_API_URL` 連携) ＋ 1行12チャネル通知** |

---

## 🏗️ システムアーキテクチャ

```
+-------------------------------------------------------------------+
|  7市場スナップショット連携  +  非公開日足パック (actions/cache)   |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  L1 決定的スクリーニング: YAML ハードフィルタ & マルチファクター  |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  L2 情報連動レッドライン AI + 上位12銘柄文脈 (悪材料 <= 35 上限)  |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  リスク制御層 & 8業種ハードキャップ分散 (max_same_bucket: 1)      |
+----------------+--------------------------------+-----------------+
                 |                                |
                 v                                v
+---------------------------------+  +------------------------------+
|  L3 分析 (scorecard / DSA)      |  |  track-record 不変履歴台帳   |
|  印刷対応 HTML & 12チャネル通知 |  |  next_open T+5/10/20 検証    |
+---------------------------------+  +------------------------------+
```

---

## 📊 実証パターン 250 日リプレイ結果（`next_open` 対 CSI 300）

検証期間 **`2026-02-05 .. 2026-11-06`**（180 営業日、対象 5,218 銘柄、寄付きストップ高除外）：

| パターン | 総シグナル | T+5 一致 | T+5 超過 | T+10 超過 | 判定 |
|---|---:|---:|---:|---:|---|
| **20日線低ボラ縮小押し目** (`ma20_shrink_pullback` v2.0) | 2,295 | 2,293 | **+0.158%** | **+0.905%** | **`active`** |
| **低ボラ堅調トレンド突破** (`steady_trend_breakout` v1.0) | 460 | 460 | **+0.271%** | **+0.560%** | **`active`** |
| その他 5 パターン (`single_yang_hold` / `box_breakout` 等) | 992–9,233 | 988–9,221 | -1.185% .. -0.175% | -1.207% .. -0.619% | `experimental` |

---

## 🔔 1行 `NOTIFY_URLS` 通知チャネル一覧（12種標準対応）

1つの変数 **`NOTIFY_URLS`** にカンマまたは改行区切りで URL を指定するだけでプロトコルを自動判定します（追加パッケージ不要、従来の個別変数も完全互換）：

```bash
NOTIFY_URLS="pushplus://TOKEN,sct://SENDKEY,bark://api.day.app/KEY,mailto://sender@qq.com:auth@qq.com?to=a@qq.com,b@qq.com,https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
```

| チャネル | 1行 `NOTIFY_URLS` 書式 | 個別環境変数 |
|---|---|---|
| **PushPlus** (`pushplus`) | `pushplus://TOKEN[/TOPIC]` | `PUSHPLUS_TOKEN`, `PUSHPLUS_TOPIC` |
| **ServerChan / ServerChan3** (`serverchan`) | `sct://SENDKEY` (`SCT...` / `sctp123t...`) | `SERVERCHAN_SENDKEY` |
| **Bark** (`bark`) | `bark://KEY` / `bark://host/KEY` | `BARK_URL` |
| **Email SMTP** (`email`) | `mailto://user:pass@host[:port]?to=a,b` | `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` |
| **WeCom** (`wecom`) | `wecom://KEY` / Webhook URL | `WECOM_WEBHOOK_URL` |
| **Feishu** (`feishu`) | `feishu://TOKEN[#secret=SEC]` | `FEISHU_WEBHOOK_URL`, `FEISHU_WEBHOOK_SECRET` |
| **DingTalk** (`dingtalk`) | `dingtalk://TOKEN[#secret=SEC]` | `DINGTALK_WEBHOOK_URL`, `DINGTALK_WEBHOOK_SECRET` |
| **Telegram** (`telegram`) | `tgram://BOT_TOKEN/CHAT_ID` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **Discord** (`discord`) | `discord://ID/TOKEN` / Webhook URL | `DISCORD_WEBHOOK_URL` |
| **Slack** (`slack`) | `slack://T.../B.../...` / Webhook URL | `SLACK_WEBHOOK_URL` |
| **ntfy** (`ntfy`) | `ntfy://topic` / `https://ntfy.sh/topic` | `NTFY_URL` |
| **Custom JSON** (`custom`) | `custom://https://...` / 不明な HTTPS | `CUSTOM_WEBHOOK_URL`, `CUSTOM_WEBHOOK_TOKEN` |
| **Apprise（任意）** | 任意の Apprise スキーム（`apprise` 導入時） | `NOTIFY_URLS` |

> 全チャネルで `(trade_date, channel)` のファイルロック冪等台帳を共有し、トークン・秘密情報はエラー出力時に自動マスクされます（確認：`alphasift notify status` / `alphasift notify test --dry-run`）。フッターに控えめな [`site/feed.xml`](https://zhulinsen.github.io/alphasift/site/feed.xml) Atom 1.0 RSS も出力します。

---

<details>
<summary><strong>対応市場・内蔵 12 戦略・2026-11-20 実行例・Fork Pages 保護</strong></summary>

- **対応市場（7 市場）**：`cn`（中国 A 株）、`us`（米国株 >= $1B）、`hk`（香港株）、`jp`（日本株 >= 1,500 億円）、`kr`（韓国株、Yahoo + Naver Finance）、`tw`（台湾株）、`in`（インド株）。
- **2026-11-20 実測出力例**：
  - 中国 A 株 `dual_low`：5,215 銘柄 → 205 銘柄 → 5 業種分散 Top 5（`601997` 貴陽銀行、`601117` 中国化学、`600741` 華域汽車、`603799` 華友鈷業、`601233` 桐昆股份）。
  - 日本株 `global_value --market jp`：748 銘柄 → 311 銘柄（`9501.T` 東京電力HD、`5401.T` 日本製鉄、`1605.T` INPEX、`9104.T` 商船三井、`9022.T` JR東海）。
- **Plan A Fork Pages 保護 & 制限事項**：Fork リポジトリでは重複サイト公開を防ぐため、Variables に `ALPHASIFT_ENABLE_PAGES=true` を設定しない限り GitHub Pages 構築・デプロイをスキップします（銘柄スキャンと通知は正常動作）。詳細は [docs/configuration.md](docs/configuration.md) と [docs/deployment.md](docs/deployment.md) をご参照ください。

</details>

---

## 免責事項・ドキュメント・ライセンス

> 本プロジェクトは学習・調査・エンジニアリング検証を目的としており、投資助言や売買推奨を行うものではありません。

[使い方](docs/usage.md) · [設定](docs/configuration.md) · [デプロイガイド](docs/deployment.md) · [戦略ガイド](docs/strategy-guide.md) · [スコアリング](docs/scoring.md) · [設計](docs/design.md) · [位置付け](docs/positioning.md) · [比較](docs/comparison.md) · [リファレンス](docs/reference.md) · [変更履歴](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

[Apache License 2.0](LICENSE) の下で公開されています。
