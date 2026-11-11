# AlphaSift

**AI エージェントのための、市場全体からの銘柄発掘。** AlphaSift は、すべての A 株（またはほかの 6 つの市場の主要な上場銘柄）を走査し、監査できる YAML の戦略でふるいにかけ、必要に応じて LLM に候補を順位付けさせ、最終的な選定銘柄をセクター間に分散させ、すべての実行を保存して、あとで選定が当たったかを確認できるようにします。

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
![Markets](https://img.shields.io/badge/markets-CN%20%7C%20US%20%7C%20HK%20%7C%20JP%20%7C%20KR%20%7C%20TW%20%7C%20IN-orange)

[English](README.md) | [中文](README.zh-CN.md) | 日本語

```text
full market ──► L1 hard filters + factor scores ──► L2 LLM ranking (optional)
  (5,000+ names)    (YAML strategy, no API key)        (cross-candidate reasoning)
                                                              │
saved run ◄── L3 post-analysis ◄── risk overlay + sector diversity cap
   │          (scorecard / DSA / HTTP)
   └──► T+N evaluation: returns, win rate, failure review
```

## AlphaSift を使う理由

- **A 株が第一で、ほかの 6 つの市場はベータ版です。** 中国の A 株は、専用の複数ソースの連鎖を通ります。アメリカ、香港、日本、韓国、台湾、インドは Yahoo Finance のスクリーナーを通ります。これは海外のサーバーや CI のランナーからでも使えます。これらの市場はデータソースが非公式なもの 1 つだけで、フィールドも少なめです（既知の制限を参照）。
- **API キーなしで動きます。** L1 のスクリーニング、スコアリング、リスクと分散の制御は決定的です。LLM は、設定した場合にだけ候補を並べ替えます。
- **戦略はコードではなく YAML です。** フィルター、ファクターの重み、スコアリングの曲線、リスクのしきい値、セクターの区分は、差分を取ってレビューできる読みやすいファイルにあります。
- **選定銘柄が 1 つのセクターに偏りません。** すべての行に業種またはセクターのラベルが付きます。`portfolio_profile.mode: hard_cap` で、Top N の中のセクターごとの銘柄数を最大 N に抑えます。
- **データソースは自己修復します。** ソースの結果は実行をまたいで保存されるので、使えないソースは最後に試されます。各ソースには時間の予算があります。生きているソースがすべて失敗したときは、最後に正常だったスナップショットを、古いものとして印を付けて使います。
- **すべての実行を検証できます。** 実行を保存しておき、あとで取引コスト、勝率、失敗したサンプル、任意で価格の推移（最大ドローダウン／最大上昇）とともに評価します。
- **エージェントのために作られています。** [SKILL.md](SKILL.md) に呼び出せるインターフェースを書いています。`alphasift serve` は、ダッシュボードやオーケストレーター向けに読み取り専用の JSON API を公開します。

## クイックスタート

```bash
pip install -e .

# A-shares, no API key needed
alphasift screen dual_low --no-llm

# Other markets: us, hk, jp, kr, tw, in
alphasift screen global_value --market hk --no-llm

# Add LLM ranking: set GEMINI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY
# (or LITELLM_MODEL / LLM_CHANNELS) in .env first
cp .env.example .env
alphasift screen dual_low

# Save a run, then evaluate it a few days later
alphasift screen dual_low --no-llm --save-run
alphasift evaluate <run_id> --with-price-path --explain
```

`alphasift quickstart` でキー不要のガイド付きのデモを、`alphasift strategies` で戦略の一覧を表示します。

## 出力の例

`--no-llm` を付けた 2026-11-03 の実際の実行です。**エンジンが何を出力するかを示すもので、推奨ではありません。**

**中国 A 株**（`dual_low`）：5,218 銘柄、フィルター後 284 銘柄、Top 5 はセクターごとに最大 2 銘柄

| # | コード | 銘柄名 | 業種 | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | 601169 | 北京银行 | 銀行 | 5.8 | 0.43 |
| 2 | 600016 | 民生银行 | 銀行 | 5.7 | 0.26 |
| 3 | 601668 | 中国建筑 | 建設 | 6.6 | 0.39 |
| 4 | 601186 | 中国铁建 | インフラ | 6.3 | 0.29 |
| 5 | 601919 | 中远海控 | 海運 | 7.9 | 1.12 |

**香港**（`global_value --market hk`）：581 銘柄、フィルター後 275 銘柄

| # | コード | 銘柄名 | セクター | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | 0998.HK | China CITIC Bank | 金融サービス | 5.8 | 0.43 |
| 2 | 0267.HK | CITIC Limited | 資本財 | 5.3 | 0.38 |
| 3 | 1398.HK | ICBC | 金融サービス | 6.5 | 0.59 |
| 4 | 0001.HK | CK Hutchison | 資本財 | 6.9 | 0.45 |
| 5 | 0358.HK | Jiangxi Copper | 素材 | 5.7 | 0.77 |

**日本**（`global_value --market jp`）：773 銘柄、フィルター後 408 銘柄

| # | コード | 銘柄名 | セクター | PE | PB |
|---:|---|---|---|---:|---:|
| 1 | 9501.T | Tokyo Electric Power | 公益事業 | 2.6 | 0.21 |
| 2 | 9022.T | Central Japan Railway | 資本財 | 7.2 | 0.71 |
| 3 | 9502.T | Chubu Electric Power | 公益事業 | 10.6 | 0.66 |
| 4 | 1911.T | Sumitomo Forestry | 一般消費財 | 9.0 | 0.70 |
| 5 | 7203.T | Toyota Motor | 一般消費財 | 8.7 | 0.97 |

海外のサーバーでは、ソースの健全性の情報がたまっていれば、A 株の実行は約 10 秒で終わります。Yahoo の各市場は 2〜10 秒です。

## 対応している市場

| `--market` | 市場 | スナップショットのソース | 備考 |
|---|---|---|---|
| `cn` | 中国 A 株 | sina → efinance → akshare_em → em_datacenter（トークンを設定すると Tushare が先頭） | 健全性に応じた順序。EastMoney による業種の補完 |
| `us` | アメリカ | Yahoo のスクリーナー（NYSE / Nasdaq の時価総額 10 億ドル以上の上場銘柄、ADR を含む） | `ALPHASIFT_US_TICKERS` を使うと、代わりに明示的なティッカーの一覧を使います |
| `hk` | 香港 | Yahoo のスクリーナー | 対象の下限は約 80 億香港ドル |
| `jp` | 日本 | Yahoo のスクリーナー | 対象の下限は約 1,500 億円 |
| `kr` | 韓国 | Yahoo のスクリーナー ＋ Naver Finance | Yahoo には韓国の PE/PB がないため、Naver の（非公式の）モバイル API から取得し、約 10 秒余分にかかります。`ALPHASIFT_KR_VALUATION=0` で無効にできます |
| `tw` | 台湾 | Yahoo のスクリーナー | TWSE と TPEx の上場銘柄 |
| `in` | インド | Yahoo のスクリーナー | NSE と BSE の上場銘柄 |

中国以外のコードは Yahoo のシンボルです（`AAPL`、`0700.HK`、`7203.T`、`005930.KS`）。これらの市場では、日足の K 線による情報の追加と T+N の評価に yfinance を使います。候補ごとのニュース、開示、資金の流れの情報は A 株のみです。

## 組み込みの戦略

| 戦略 | 市場 | 種類 | 考え方 |
|---|---|---|---|
| `dual_low` | cn | バリュー | 低 PE ＋ 低 PB、売買の活発さと安定性の確認、セクターごとの上限 |
| `quality_value` | cn | バリュー | 流動性があり、ボラティリティが抑えられた、妥当なバリュエーション |
| `blue_chip_income` | cn | インカム | 配当の質が高い、流動性のある優良株 |
| `low_volatility_quality` | cn | クオリティ | 日次のボラティリティ、ドローダウン、ATR を使った守りのスクリーニング |
| `volume_breakout` | cn | トレンド | 出来高の増加を伴う抵抗線の突破 |
| `shrink_pullback` | cn | トレンド | 上昇トレンドの中での支持線までの押し目（日足の K 線） |
| `capital_heat` | cn | モメンタム | 極端な過熱のない、活発な資金の流れ |
| `oversold_reversal` | cn | リバーサル | ドローダウンが抑えられた、回復の候補 |
| `balanced_alpha` | cn | フレームワーク | 汎用的なマルチファクターによる発掘 |
| `momentum_quality` | cn | フレームワーク | トレンドの確認 ＋ クオリティのフィルター |
| `global_value` | us, hk, jp, kr, tw, in | バリュー | ほかの市場向けの `dual_low` で、通貨に依存するしきい値はありません |
| `us_momentum_quality` | us | トレンド | アメリカの大型株のモメンタムとクオリティ |

`strategies/` に自分の戦略を書けます。[戦略のガイド](docs/strategy-guide.md)を参照してください。

## 設定

`.env.example` を `.env` にコピーします。AlphaSift は LiteLLM 形式の設定を読むので、[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) の設定を使い回せます。よく使う設定：

| 変数 | 用途 | デフォルト |
|---|---|---|
| `LITELLM_MODEL` | メインのモデル。`provider/model` の形式 | `gemini/gemini-2.5-flash` |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | LLM による順位付けのためのプロバイダーのキー | - |
| `LLM_CHANNELS` / `LITELLM_CONFIG` | マルチチャンネルまたは LiteLLM Router の設定 | - |
| `TUSHARE_TOKEN` | A 株の連鎖で Tushare を先頭にします | - |
| `SNAPSHOT_SOURCE_PRIORITY` | A 株のソースの順序を上書きします | トークンによる |
| `ALPHASIFT_SNAPSHOT_CALL_TIMEOUT_SEC` | スナップショットのソースごとの時間の予算 | `60` |
| `INDUSTRY_AUTO_BACKFILL` | A 株の欠けている業種のラベルを補います | `true` |
| `ALPHASIFT_DATA_DIR` | 実行、キャッシュ、ソースの健全性 | `./data` |
| `DSA_API_URL` | 任意の DSA による詳細な分析の段階を有効にします | - |

すべての一覧は [docs/configuration.md](docs/configuration.md) にあります。

## その他の機能

- **Python API**：`from alphasift import screen, evaluate_saved_run` のあと、`screen("dual_low", use_llm=False, market="cn")`。
- **LLM のコンテキスト**：`--context "..."` で市場についてのメモを、`--candidate-context-file` で銘柄ごとの調査を追加します。
- **事後分析（L3）**：ローカルの `scorecard` がデフォルトで動きます。`--post-analyzer dsa` を付けると、最終的な候補を [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) に送り、個別銘柄の詳細な分析を行います。
- **注目テーマ**：`alphasift hotspots` と `alphasift hotspot "<topic>"` は、A 株のテーマを順位付けし、キャッシュとフォールバックのメタデータを使って主導銘柄を特定します。
- **エージェントと UI 向けのペイロード**：`alphasift overview --json`、`alphasift serve`、`alphasift doctor data-sources --all-strategies --explain`。エンドポイントは[使い方のガイド](docs/usage.md)に一覧があります。

## 既知の制限

- AlphaSift は発掘と順位付けのエンジンで、バックテストのツールや売買の執行システムではありません。T+N の評価は、保存した価格とその後の価格を比べるもので、配当、売買停止、ポジションの制約はモデル化していません。
- `evaluate-strategies --window 5,10,20` は本当の T+N を測ります：各選定銘柄の、エントリー後 N 本目の取引日の終値でのリターンを、同じ期間の市場のベンチマーク（CSI 300、S&P 500、ハンセン指数、日経 225、KOSPI、TAIEX、Nifty 50）と比べます。期間がまだ過ぎていない選定銘柄は保留として報告します。期間を指定しない `evaluate` と `evaluate-batch` は、引き続き最新の価格までのリターンを測ります。
- エントリーは取引所の時刻で決まります：取引開始前に保存した実行は前日の終値でエントリーし、取引中または取引後に保存した実行は、その日の足を上昇幅やドローダウンに含めません。取引所の休日は、データソースが返す足以上にはモデル化していません。
- Yahoo のスクリーナーの市場は、市場全体ではありません：対象は時価総額の下限（約 10 億米ドル）を上回る上場銘柄で、Yahoo のセクターごとに 1 回ずつ問い合わせ、4000 行が上限です。非公式のエンドポイント 1 つに依存し、売買代金を価格 × 出来高で推定し、時価総額の合計を浮動株の時価総額として使います。韓国の PE/PB は Naver Finance（もう 1 つの非公式のエンドポイント）から取得し、赤字の企業には PE がありません。PE/PB を EPS と純資産から導くのは、取引の通貨と報告の通貨が一致する場合だけです。
- 日足の K 線を使う戦略は、市場全体ではなく、L1 の候補だけに情報を追加します。
- `strategies/` と `alphasift/strategies/` は互いの写し（開発用とインストールされるパッケージ）で、同期させておく必要があります。

## 免責事項

このプロジェクトは、学習、研究、エンジニアリングの実験のためのものです。投資の助言、リターンの保証、売買の指示ではありません。マーケットデータ、LLM の出力、戦略のパラメーターは、遅れていたり、不完全だったり、誤っていたりすることがあります。自分自身の調査、法令の遵守、コスト、判断には、あなた自身が責任を持ってください。

## ドキュメント

[使い方](docs/usage.md) · [設定](docs/configuration.md) · [戦略のガイド](docs/strategy-guide.md) · [スコアリング](docs/scoring.md) · [設計](docs/design.md) · [位置付け](docs/positioning.md) · [比較](docs/comparison.md) · [リファレンス](docs/reference.md) · [変更履歴](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

## ライセンス

[Apache License 2.0](LICENSE)
