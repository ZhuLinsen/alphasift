<div align="center">

<a href="https://alphasift.zhulinsen.tech/?lang=ja">
  <img src="docs/assets/alphasift-logo.svg" alt="AlphaSift Logo" width="480">
</a>

[简体中文](README.md) | [English](README.en.md) | 日本語

# 🔎 AlphaSift

**AI クオンツ株式スクリーナー**

*世界7市場（中国A株・米国・香港・日本・韓国・台湾・インド）のマルチファクター選定 → AI 開示リスク再評価 → 公開 T+N 検証*

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/alphasift?style=social)](https://github.com/ZhuLinsen/alphasift/stargazers)
[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-0ea5e9.svg)](https://alphasift.zhulinsen.tech/?lang=ja)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Ready-8b5cf6.svg)](docs/ecosystem.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3b82f6.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-10b981.svg)](LICENSE)

[**ライブダッシュボード**](https://alphasift.zhulinsen.tech/?lang=ja) · [**特長**](#-なぜ-alphasift-なのか) · [**30秒スタート**](#-30秒ゼロ摩擦スタート) · [**検証データ＆構成**](#-実証データとシステムアーキテクチャ) · [**Quant Trio**](#-quant-trio関連プロジェクト) · [**Agent Skill**](SKILL.md)

</div>

> [!TIP]
> 🚀 **[daily_stock_analysis（73.6k★）](https://github.com/ZhuLinsen/daily_stock_analysis) 姉妹プロジェクト**：**AlphaSift** が全市場 `5,000+` 銘柄の一次スクリーニングと `T+N` 公開検証を担い、**DSA** が個別銘柄の詳細レポート、[**AlphaEvo**](https://github.com/ZhuLinsen/alphaevo) が進化的ファクター発掘を担います。

---

## 🖥️ インストール不要・本日の選定銘柄＆公開実績を見る

👉 **[公開ダッシュボードを開く（alphasift.zhulinsen.tech）](https://alphasift.zhulinsen.tech/?lang=ja)** — 毎営業日の大引け後に自動更新される 7市場コンセンサス銘柄、`T+5 / T+10 / T+20` 成績表、および **AI vs ルール同日対照結果** を確認できます。

<p align="center">
  <a href="https://alphasift.zhulinsen.tech/?lang=ja">
    <img src="docs/assets/dashboard-preview.gif" alt="AlphaSift ライブダッシュボード操作プレビュー" width="840">
  </a>
  <br><sub>画像クリックで公開ダッシュボードへ（Dark / Light テーマ・<code>中 | EN | 日</code> 即時切替対応）</sub>
</p>

<details>
<summary><strong>静止画キャプチャ・印刷対応日次レポート例（<code>alphasift daily-report --output-html</code>）を見る</strong></summary>

<table>
  <tr>
    <td width="50%" align="center">
      <a href="https://alphasift.zhulinsen.tech/?lang=ja&theme=dark">
        <img src="docs/assets/dashboard-ja.png" alt="AlphaSift ライブダッシュボード（ダーク・日本語）" width="100%">
      </a>
      <br><sub><b>Obsidian Dark ターミナル（日本語）</b> — 複数戦略コンセンサス、A 株7段階騰落分布、7市場ランキング</sub>
    </td>
    <td width="50%" align="center">
      <a href="https://alphasift.zhulinsen.tech/?lang=en&theme=light">
        <img src="docs/assets/dashboard-light.png" alt="AlphaSift ライブダッシュボード（ライト）" width="100%">
      </a>
      <br><sub><b>Editorial Paper Light</b> — ヘッダーの <code>中 | EN | 日</code> 言語切替＆検証台帳</sub>
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

</details>

---

## ✨ なぜ AlphaSift なのか

多くの AI 銘柄ツールは指定銘柄のチャット要約や都合の良い過去チャートに留まります。**AlphaSift は全市場発掘・適時開示リスク制御・公開事後検証を一つの透明な仕組みに統合しています：**

1. **API キー不要で 7市場を自動スクリーニング**：中国 A株・米国・香港・日本・韓国・台湾・インドに対応し、監査可能な 12 の YAML 戦略と 8業種ハードキャップ分散を決定的（ルールベース）に実行できます。
2. **悪材料レッドライン制限＆公開 `T+N` 台帳**：LLM 再ランク有効時は適時開示・ニュース・資金フローを注入し（標準 `gemini/gemini-3.8-flash` / 自動フォールバック `gemini/gemini-4-hydrogen`）、重大な悪材料銘柄をコードレベルで **`llm_score <= 35` に制限**。選定結果はすべて公開 [`track-record`](https://github.com/ZhuLinsen/alphasift/tree/track-record) ブランチへ記録し、`next_open`・ストップ高除外口径で `AI vs ルール` の純増αを検証します。
3. **無料クラウド自動実行＆即戦力 AI 連携**：GitHub Actions での無料毎日実行＆12チャネル通知（Fork 時の重複サイト公開を防ぐ Plan A 保護内蔵）に加え、依存ゼロの STDIO **MCP Server**（`alphasift mcp`）とローカル **Workbench UI**（`alphasift serve` → `/ui`）を同梱しています。

---

## ⚡ 30秒ゼロ摩擦スタート

### 1. Claude Code・Cursor・Codex・OpenClaw と連携（ネイティブ MCP）

読み取り専用の STDIO MCP サーバー（`10` ツール + `2` リソース、外部通知を送らない `scorecard` 後処理のみ実行）を 5 行の JSON で接続できます：

```json
{
  "mcpServers": {
    "alphasift": { "command": "alphasift", "args": ["mcp"] }
  }
}
```

> *上記は Claude Code / Cursor 用 JSON 例です。Codex（`mcp_servers` TOML）や OpenClaw（`mcp.servers`）の設定形式は [docs/ecosystem.md](docs/ecosystem.md) を参照してください。*

**接続後のプロンプト例：**
- *「AlphaSift で割安かつ適時開示の悪材料がない中国A株 `dual_low` 上位5銘柄を抽出し、業種分散と根拠を要約して」*
- *「`dual_low` と `quality_value` のファクター配分・リスク上限を比較して、レンジ相場向けの戦略を提案して」*
- *「`global_value` で日本株と香港株を `--no-llm` でスクリーニングし、セクター別に並べて」*

---

### 2. ローカル CLI・Web Workbench (`/ui`)・Docker

[`v0.3.0` Release](https://github.com/ZhuLinsen/alphasift/releases/tag/v0.3.0) から wheel を直接導入するか、リポジトリから開発インストールできます：

```bash
# 方法 A：v0.3.0 Release Wheel を直接インストール
pip install https://github.com/ZhuLinsen/alphasift/releases/download/v0.3.0/alphasift-0.3.0-py3-none-any.whl

# 方法 B：ソースコードからインストール
git clone https://github.com/ZhuLinsen/alphasift.git && cd alphasift
pip install -e .
```

**API キー不要で今すぐ実行：**
```bash
alphasift quickstart                            # 30秒デモ
alphasift screen dual_low --no-llm              # 中国A株ルールスクリーニング
alphasift screen global_value --market jp --no-llm   # 日本株バリュー選定
alphasift serve --host 127.0.0.1 --port 8765    # ローカル Workbench UI (/ui)
# または Docker Compose で同一ループバックポート起動：
docker compose up --build -d
```

**AI 再ランク・250日リプレイ・日次 HTML レポート：**
```bash
cp .env.example .env                            # GEMINI_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY を設定
alphasift pack build --days 250                 # replay / daily-report 前にローカル CN 日次パックを構築
alphasift screen dual_low --save-run
alphasift evaluate-strategies --window 5,10,20 --explain
alphasift daily-report --pack-dir ./data/pack/cn --output-html daily_report.html --push
```

---

### 3. GitHub Actions で無料定期実行＆Fork 保護

1. リポジトリを **Fork** し **GitHub Actions** を有効化します。
2. *Settings -> Secrets and variables -> Actions -> Secrets* に `GEMINI_API_KEY`（任意）および `NOTIFY_URLS`（任意）を追加します。
3. **Plan A Fork Pages 保護**：Fork 先では重複サイト公開を防ぐため、Variables に `ALPHASIFT_ENABLE_PAGES=true` を設定しない限り GitHub Pages デプロイをスキップし、スクリーニングと通知のみ動作します。詳細は [docs/deployment.md](docs/deployment.md)。

---

## 📊 実証データとシステムアーキテクチャ

| 比較軸 | 一般スクリーナー (`TradingView` 等) | 個別銘柄 AI (`daily_stock_analysis`) | **AlphaSift** |
|---|---|---|---|
| **対象範囲** | 1市場ずつ手動条件絞り込み | 指定済みウォッチリスト深掘り | **7市場全量スクリーニング (`cn/us/hk/jp/kr/tw/in`)** |
| **再現性と業種分散** | ブラックボックス / 手動設定 | プロンプト主導 | **監査可能 YAML DSL ＋ 8業種 `hard_cap` 直交分散** |
| **AI ガードレール** | なし | 個別銘柄ナラティブ | **適時開示/資金フロー注入 ＋ 悪材料 `<= 35` 上限** |
| **事後検証** | なし | 手動振り返り | **公開 `track-record` 台帳 (`next_open` T+5/10/20＆ストップ高除外)** |

- **直交分散の実測改善**：中国 A株 10 戦略に 8業種ハードキャップ（`max_same_bucket: 1`）を導入した結果、250日パック3時点検証で戦略間の平均重複率は **8.0%–24.9% → 0.9%–1.8%**（最大 **100% → 20%**）、銀行集中度は **22%–31.1% → 4.0%–9.1%** へ低減しました。
- **250日 `next_open` 実証パターン検出**：`2026-02-05 .. 2026-11-06`（180 営業日・5,218 銘柄、対 CSI 300、全 **9** パターン）で **`ma20_shrink_pullback`（+0.158% T+5 / +0.905% T+10）** と **`steady_trend_breakout`（+0.271% T+5 / +0.560% T+10）** を `active` 認定。新設の **`three_white_soldiers`（赤三兵: +0.414% T+5）** と **`three_white_soldiers_pullback`（+0.451% T+5）** は前後半安定性検証中（`t = 0.03 / 0.12`）のため他 5 種と同様 `experimental` として分離。

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
|  L3 分析 (scorecard / DSA)      |  |  track-record 公開監査台帳   |
|  印刷対応 HTML & 12チャネル通知 |  |  next_open T+5/10/20 検証    |
+---------------------------------+  +------------------------------+
```

---

<details>
<summary><strong>内蔵 12 戦略一覧（A 株 10 戦略 + 米国/グローバル 2 戦略）</strong></summary>

| 戦略名 | 市場 | スタイル | 主な狙い |
|---|---|---|---|
| `dual_low` | `cn` | バリュー | 中型低 PE/PB（時価総額 `5B–60B CNY`）、業種上限 `1` |
| `blue_chip_income` | `cn` | 高配当 | 超大型・高流動性・高配当（`>= 50B CNY`） |
| `quality_value` | `cn` | GARP | 中型成長×適正バリュエーション×MA20 トレンド維持（`8B–120B CNY`） |
| `low_volatility_quality` | `cn` | 防御 | 20 日ボラティリティ＆ドローダウン制御（要日足） |
| `balanced_alpha` | `cn` | 多因子 | マルチファクター総合＋業種分散 |
| `momentum_quality` | `cn` | トレンド品質 | 60 日トレンド確認＋ファンダ基準 |
| `shrink_pullback` | `cn` | 押し目 | 上昇基調中の出来高縮小 MA20 押し目（要日足） |
| `capital_heat` | `cn` | モメンタム | 売買代金回転率・資金流入（過熱追随を除外） |
| `oversold_reversal` | `cn` | リバーサル | 短期売られ過ぎからの自律反発 |
| `volume_breakout` | `cn` | ブレイクアウト | 出来高伴う 20 日高値ブレイク |
| `global_value` | `us, hk, jp, kr, tw, in` | グローバル | 通貨中立の割安低 PE/PB スクリーニング |
| `us_momentum_quality` | `us` | 米国株 | 米国大型株 (`>= $2B`) モメンタム＋クオリティ |

</details>

<details>
<summary><strong>1行 <code>NOTIFY_URLS</code> 通知チャネル一覧（12種標準対応）＆ Atom RSS</strong></summary>

1つの変数 **`NOTIFY_URLS`** にカンマまたは改行区切りで URL を指定するだけでプロトコルを自動判定します（追加パッケージ不要、従来の個別変数も完全互換）：

```bash
NOTIFY_URLS="pushplus://TOKEN,sct://SENDKEY,bark://api.day.app/KEY,mailto://sender@qq.com:auth@qq.com?to=a@qq.com,https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
```

| チャネル | 1行 `NOTIFY_URLS` 書式 | 個別環境変数 |
|---|---|---|
| **PushPlus** | `pushplus://TOKEN[/TOPIC]` | `PUSHPLUS_TOKEN`, `PUSHPLUS_TOPIC` |
| **ServerChan / ServerChan3** | `sct://SENDKEY` (`SCT...` / `sctp123t...`) | `SERVERCHAN_SENDKEY` |
| **Bark** | `bark://KEY` / `bark://host/KEY` | `BARK_URL` |
| **Email SMTP** | `mailto://user:pass@host[:port]?to=a,b` | `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` |
| **WeCom** | `wecom://KEY` / Webhook URL | `WECOM_WEBHOOK_URL` |
| **Feishu** | `feishu://TOKEN[#secret=SEC]` | `FEISHU_WEBHOOK_URL`, `FEISHU_WEBHOOK_SECRET` |
| **DingTalk** | `dingtalk://TOKEN[#secret=SEC]` | `DINGTALK_WEBHOOK_URL`, `DINGTALK_WEBHOOK_SECRET` |
| **Telegram** | `tgram://BOT_TOKEN/CHAT_ID` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **Discord** | `discord://ID/TOKEN` / Webhook URL | `DISCORD_WEBHOOK_URL` |
| **Slack** | `slack://T.../B.../...` / Webhook URL | `SLACK_WEBHOOK_URL` |
| **ntfy** | `ntfy://topic` / `https://ntfy.sh/topic` | `NTFY_URL` |
| **Custom JSON / Apprise** | `custom://https://...` / Apprise スキーム | `CUSTOM_WEBHOOK_URL`, `CUSTOM_WEBHOOK_TOKEN` |

確認コマンド：`alphasift notify status` / `alphasift notify test --dry-run`。フッターで Atom 1.0 RSS [`site/feed.xml`](https://alphasift.zhulinsen.tech/site/feed.xml) も配信しています。

</details>

<details>
<summary><strong>対応市場・2026-11-20 サンプル出力・主な環境変数</strong></summary>

| 市場 | スナップショット＆日足ソース | 補足事項 |
|---|---|---|
| `cn` | `em_datacenter -> sina -> efinance -> akshare_em`（`tushare` トークンで最優先） | 全 A 株対応、業種補完、適時開示・テーマ連携 |
| `us, hk, jp, tw, in` | Yahoo Finance スクリーナー + `yfinance` | 大型・中型流動性フィルター、非公式エンドポイント |
| `kr` | Yahoo Finance + Naver Finance | Naver で PE/PB 補完（`ALPHASIFT_KR_VALUATION=0` で無効化） |

- **2026-11-20 `--no-llm` サンプル**：A株 `dual_low`（`601997`, `601117`, `600741`, `603799`, `601233`）、香港 `global_value`（`0267.HK`, `0001.HK`, `1339.HK`, `1398.HK`, `0358.HK`）、日本 `global_value`（`9501.T`, `5401.T`, `1605.T`, `9104.T`, `9022.T`）。
- **主な環境変数**：`LITELLM_MODEL`（既定 `gemini/gemini-3.8-flash`）、`LITELLM_FALLBACK_MODELS`（`gemini/gemini-4-hydrogen`）、`GEMINI_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`、`LLM_CANDIDATE_CONTEXT_ENABLED=true`、`NOTIFY_URLS`、`ALPHASIFT_ENABLE_PAGES=true`、`DSA_API_URL`（[詳細](docs/configuration.md)）。

</details>

---

## 🔗 Quant Trio（関連プロジェクト）

| プロジェクト | 役割 | 連携フロー |
|---|---|---|
| **[AlphaEvo](https://github.com/ZhuLinsen/alphaevo)** | 進化的ファクター発掘 | AST/LLM でアルファ遺伝子を探索し AlphaSift YAML へ蒸留 |
| **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** | **7市場ファネル＆検証台帳** | `5,000+` 銘柄から厳選候補を抽出し `T+5 / 10 / 20` を公開記録 |
| **[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)** | L3 個別銘柄深掘り AI | `DSA_API_URL` / MCP 経由で厳選銘柄の適時開示・投資判断を自動化 |

構成の詳細は [docs/ecosystem.md](docs/ecosystem.md) をご覧ください。

---

## 免責事項・ドキュメント・ライセンス

> 本プロジェクトは学習・調査・エンジニアリング検証を目的としており、投資助言や売買推奨を行うものではありません。

[使い方](docs/usage.md) · [設定](docs/configuration.md) · [エコシステム＆MCP](docs/ecosystem.md) · [デプロイガイド](docs/deployment.md) · [戦略ガイド](docs/strategy-guide.md) · [スコアリング](docs/scoring.md) · [出力スキーマ](docs/result-schema.md) · [リファレンス](docs/reference.md) · [コントリビュート](CONTRIBUTING.md) · [セキュリティ](SECURITY.md) · [変更履歴](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

[Apache License 2.0](LICENSE) の下で公開されています。

## コミュニティ

[LINUX DO](https://linux.do/) コミュニティのサポートに感謝します。
