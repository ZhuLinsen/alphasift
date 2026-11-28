<div align="center">

<a href="https://alphasift.zhulinsen.tech/?lang=en">
  <img src="docs/assets/alphasift-logo.svg" alt="AlphaSift Logo" width="480">
</a>

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | Türkçe

# 🔎 AlphaSift

**Yapay Zeka Destekli Kantitatif Hisse Senedi Tarayıcısı**

*7 piyasada tam piyasa YAML taraması -> Kırmızı bayrak YZ yeniden sıralaması -> Herkese açık `next_open` T+N kâğıt üzerinde kıyaslama*

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/alphasift?style=social)](https://github.com/ZhuLinsen/alphasift/stargazers)
[![PyPI](https://img.shields.io/pypi/v/alphasift?color=2563eb)](https://pypi.org/project/alphasift/)
[![Live Dashboard](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-0ea5e9.svg)](https://alphasift.zhulinsen.tech/?lang=en)
[![MCP Ready](https://img.shields.io/badge/MCP-STDIO%20Ready-8b5cf6.svg)](docs/ecosystem.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3b82f6.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-10b981.svg)](LICENSE)

[**Canlı Pano**](https://alphasift.zhulinsen.tech/?lang=en) · [**Neden AlphaSift**](#-neden-alphasift) · [**30sn Hızlı Başlangıç**](#-30-saniyede-hızlı-başlangıç) · [**Kıyaslamalar ve Mimari**](#-doğrulanmış-kıyaslamalar-ve-mimari) · [**Quant Trio**](#-quant-trio-ekosistemi) · [**Agent Skill**](SKILL.md)

</div>

> [!TIP]
> 🚀 **[daily_stock_analysis (73.6k★)](https://github.com/ZhuLinsen/daily_stock_analysis) ile tamamlayıcıdır**: **AlphaSift**, `5,000+` hisse senedi arasında kapanış sonrası keşif yapar ve canlı `T+N` doğruluğunu denetler; **DSA** derinlemesine tek hisse özetleri üretir; [**AlphaEvo**](https://github.com/ZhuLinsen/alphaevo) ise alfa kurallarını evrimleştirir ve yanlışlar.

---

## 🖥️ Kurulumsuz Canlı Pano ve Herkese Açık Kayıt Defteri

👉 **[Canlı Kıyaslamayı Açın (alphasift.zhulinsen.tech)](https://alphasift.zhulinsen.tech/?lang=en)** — her işlem gününde 7 piyasa konsensüs sinyalleri, `T+5 / T+10 / T+20` liderlik tabloları ve yan yana **YZ vs Kurallar** eşleştirilmiş atıfları ile güncellenir.

<p align="center">
  <a href="https://alphasift.zhulinsen.tech/?lang=en">
    <img src="docs/assets/dashboard-preview.gif" alt="AlphaSift Live Dashboard Interactive Preview" width="840">
  </a>
  <br><sub>Canlı terminali keşfetmek için önizlemeye tıklayın (Koyu / Açık temalar + anlık <code>ZH | EN | JA</code> geçişi)</sub>
</p>

<details>
<summary><strong>Statik koyu/açık ekran görüntülerini ve yazdırılabilir bağımsız günlük araştırma raporunu (<code>alphasift daily-report --output-html</code>) görüntüleyin</strong></summary>

<table>
  <tr>
    <td width="50%" align="center">
      <a href="https://alphasift.zhulinsen.tech/?lang=en&theme=dark">
        <img src="docs/assets/dashboard-dark.png" alt="AlphaSift Live Dashboard (Dark)" width="100%">
      </a>
      <br><sub><b>Obsidian Dark Terminal</b> — Konsensüs Sinyalleri, CN Mikroyapı Genişliği ve 7 Piyasa T+N Liderlik Tablosu</sub>
    </td>
    <td width="50%" align="center">
      <a href="https://alphasift.zhulinsen.tech/?lang=en&theme=light">
        <img src="docs/assets/dashboard-light.png" alt="AlphaSift Live Dashboard (Light)" width="100%">
      </a>
      <br><sub><b>Editorial Paper Light</b> — Çok Dilli Değiştirici (<code>ZH | EN | JA</code>) ve Denetlenmiş Performans Geçmişi</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <a href="docs/usage.md">
        <img src="docs/assets/daily-report.png" alt="AlphaSift Standalone Printable Daily Brief" width="88%">
      </a>
      <br><sub><b>Yazdırılabilir Bağımsız Araştırma Özeti</b> (<code>alphasift daily-report --output-html</code>) — Yönetici Özeti, 7 Kovalı Getiri Histogramı, Bildirim Riski Taraması ve 20G Mum Grafiği Eşleşmeleri</sub>
    </td>
  </tr>
</table>

</details>

---

## ✨ Neden AlphaSift

Çoğu yapay zeka hisse senedi aracı, önceden seçilmiş bir izleme listesi üzerinde sohbet etmekle veya geçmiş testlerden işine gelenleri seçmekle yetinir. **AlphaSift tam piyasa taramasını, kırmızı bayrak YZ filtrelemesini ve işlem sonrası halka açık yanlışlamayı tek bir birleşik işlem hattı olarak ele alır:**

1. **Anahtarsız Tam Piyasa Taraması**: 12 denetlenebilir YAML stratejisi ve 8 kovalı sektör çeşitliliği üst sınırları kullanarak CN A-Hisseleri, US, HK, JP, KR, TW ve IN piyasalarını saniyeler içinde tarar — deterministik kurallar için hiçbir API anahtarı gerekmez.
2. **Kodla Zorunlu Kılınan Kırmızı Çizgiler ve Dürüst `T+N` Kayıt Defteri**: İsteğe bağlı LLM yeniden sıralaması (varsayılan `gemini/gemini-3.8-flash` ve yedek `gemini/gemini-4-hydrogen`), adayları canlı bildirim/haber/fon akışı bağlamına dayandırır, çözülmemiş olumsuz bildirimleri **Python içinde `llm_score <= 35` ile sınırlar**, popülerlik yanlılığını yasaklar ve eşleştirilmiş `rules` vs `ai` artık getirilerini `next_open` üzerinden kaydeder (`untradable_limit_up` hariç tutulur).
3. **Ücretsiz Bulut Çalıştırmaları ve Yerel Ajan Yığını**: 12 kanallı `NOTIFY_URLS` uyarılarıyla GitHub Actions üzerinde günlük çalıştırmalar zamanlayın (Plan A fork koruması yinelenen fork web sitelerini engeller) veya sıfır bağımlılıklı STDIO **MCP** (`alphasift mcp`) ve yerel **Web Çalışma Tezgahı** (`alphasift serve` -> `/ui`) aracılığıyla doğrudan Claude Code, OpenClaw, Cursor ve Codex'e bağlayın.

---

## ⚡ 30 Saniyede Hızlı Başlangıç

### 1. Claude Code, Cursor, Codex veya OpenClaw'a Bağlanın (Yerel STDIO MCP)

Sıfır bağımlılıklı salt okunur MCP sunucusunu kaydedin (`14` araç, `4` kaynak; giden bildirimler olmadan yerel `scorecard` çalıştırır):

```json
{
  "mcpServers": {
    "alphasift": { "command": "alphasift", "args": ["mcp"] }
  }
}
```

> *Yukarıda Claude Code / Cursor JSON formatı gösterilmiştir; Codex (`mcp_servers` TOML) veya OpenClaw (`mcp.servers`) için [docs/ecosystem.md](docs/ecosystem.md) dosyasına bakın.*

**YZ asistanınıza şunları sormayı deneyin:**
- *"Bugünün CN `dual_low` stratejisini temiz bildirimlere sahip en iyi 5 düşük değerlemeli seçim için tara ve sektör dağılımını açıkla."*
- *"Dalgalı bir piyasa rejimi için `dual_low` ile `quality_value` faktör ağırlıklarını ve risk sınırlarını karşılaştır."*
- *"HK ve JP piyasalarında `--no-llm` ile `global_value` çalıştır ve seçimleri sektöre göre grupla."*

---

### 2. Yerel CLI, Etkileşimli Web Çalışma Tezgahı (`/ui`) ve Docker

Doğrudan [PyPI (`alphasift`)](https://pypi.org/project/alphasift/), [`v0.3.1` Sürüm wheel'i](https://github.com/ZhuLinsen/alphasift/releases/tag/v0.3.1) veya düzenlenebilir kaynak kodu kurulumuyla yükleyin:

```bash
# Seçenek A: PyPI üzerinden kurulum (pip / uvx destekler)
pip install alphasift

# Seçenek B: Düzenlenebilir kaynak kurulumu
git clone https://github.com/ZhuLinsen/alphasift.git && cd alphasift
pip install -e .
```

**Anahtarsız taramayı ve yerel Çalışma Tezgahını hemen çalıştırın:**
```bash
alphasift quickstart                            # 30sn uçtan uca örnek
alphasift screen dual_low --no-llm              # CN deterministik kurallar izi
alphasift screen global_value --market hk --no-llm
alphasift serve --host 127.0.0.1 --port 8765    # Yerel Workbench UI (/ui) ve salt okunur API
# Veya aynı loopback portunda konteyner olarak:
docker compose up --build -d
```

**İsteğe bağlı kırmızı bayrak YZ sıralaması, 250 günlük tekrar oynatma ve yazdırılabilir günlük rapor:**
```bash
cp .env.example .env                            # GEMINI_API_KEY, DEEPSEEK_API_KEY veya OPENAI_API_KEY ekleyin
alphasift pack build --days 250                 # replay / daily-report öncesinde yerel CN paketi oluşturun
alphasift screen dual_low --save-run
alphasift evaluate-strategies --window 5,10,20 --explain
alphasift daily-report --pack-dir ./data/pack/cn --output-html daily_report.html --push
```

---

### 3. Ücretsiz Bulut Günlük Taraması ve Fork Koruması

1. Bu depoyu **Fork**'layın ve **GitHub Actions**'ı etkinleştirin.
2. *Settings -> Secrets and variables -> Actions* altında isteğe bağlı **Secrets** ekleyin: eşleştirilmiş YZ sıralaması için `GEMINI_API_KEY` (veya `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`) ve tek satırlık anlık uyarılar için `NOTIFY_URLS`.
3. **Plan A Fork Koruması:** Fork'lanan depolar, Repository Variable olarak `ALPHASIFT_ENABLE_PAGES=true` ayarlanmadıkça ve *Settings -> Pages -> GitHub Actions* etkinleştirilmedikçe yinelenen GitHub Pages derlemelerini atlayarak tarama ve bildirimleri çalıştırır. Bkz. [docs/deployment.md](docs/deployment.md).

---

## 📊 Doğrulanmış Kıyaslamalar ve Mimari

| Boyut | Statik Tarayıcılar (`TradingView` / `EastMoney`) | Tek Hisse YZ (`daily_stock_analysis`) | **AlphaSift** |
|---|---|---|---|
| **Evren** | 1 piyasada manuel UI filtreleri | Önceden seçilmiş izleme listesinde derin analiz | **7 piyasada tam piyasa keşfi (`cn/us/hk/jp/kr/tw/in`)** |
| **Determinizm ve Çeşitlilik** | Şeffaf olmayan UI ön ayarları | Hisse başına istem (prompt) odaklı | **Denetlenebilir YAML DSL + 8 kovalı `hard_cap` ortogonalliği** |
| **YZ Korkulukları** | Yok | Tek hisse anlatısı | **Bildirim/fon akışı bağlamı, `<= 35` kırmızı bayrak sınırı, popülerlik yanlılığı karşıtı** |
| **İşlem Sonrası Denetim** | Yok | Manuel inceleme | **Herkese açık `track-record` kayıt defteri (`next_open` T+5/10/20 + tavan fiyat engelleri)** |

- **Ortogonal CN Strateji Paketi**: Tüm 10 CN stratejisinin 8 kovalı sert sektör sınırlarıyla (`max_same_bucket: 1`) yeniden yapılandırılması, 3 yerel 250G anlık görüntüsündeki ortalama ikili strateji örtüşmesini **%8.0–%24.9 -> %0.9–%1.8** (`maks` **%100 -> %20**) ve banka yoğunlaşmasını **%22–%31.1 -> %4.0–%9.1** düzeyine düşürdü.
- **Ampirik Olarak Denetlenmiş 250G Formasyon Radarı**: `2026-02-05 .. 2026-11-06` (`180` seans, `5,218` A-hissesi, CSI 300 ve All-A eşit ağırlıklıya karşı `next_open` girişi, **9** durumsuz YAML) genelinde formasyonlar yalnızca şu koşulların tamamını eşzamanlı olarak geçtiğinde `active` durumuna yükselir: eşleşmiş `T+5 N >= 200`, her iki kıyaslamaya karşı `25bp` gidiş-dönüş maliyeti sonrası pozitif net artık getiri, Bartlett Newey-West HAC `t >= 2.0`, BH-FDR `q <= 0.05` ve aynı işaretli pozitif yarı-bölüm kararlılığı (`H1/H2 >= 15d & >= 30`). Şu anda **`three_white_soldiers_pullback`**, **`three_white_soldiers`**, **`ma20_shrink_pullback`**, **`steady_trend_breakout`** ve kalan 5 formasyonun tamamı net artık getiri ve istatistiksel tanılamaları açıklarken **`experimental`** gözlem aşamasında kalmaktadır; negatif beklentili formasyonlar günlük rapor kartlarında otomatik olarak daraltılır.

```
+-------------------------------------------------------------------+
|  7 Markets Snapshot Chains  +  Private DailyPack (actions/cache)  |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  L1 Deterministic Engine: YAML Hard Filters & Factor Scoring      |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  L2 Red-Flag Skeptic LLM + Top-12 Context (<=35 Adverse Cap)      |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  Risk Overlay & 8-Bucket Hard Sector Cap (max_same_bucket: 1)     |
+----------------+--------------------------------+-----------------+
                 |                                |
                 v                                v
+---------------------------------+  +------------------------------+
|  L3 Analyzers (scorecard / DSA) |  |  Auditable track-record Log  |
|  Printable HTML & NOTIFY_URLS   |  |  next_open T+5/10/20 Audit   |
+---------------------------------+  +------------------------------+
```

---

<details>
<summary><strong>Yerleşik YAML Stratejileri (7 Piyasada 12 Strateji)</strong></summary>

| Strateji | Piyasalar | Stil | Temel Odak |
|---|---|---|---|
| `dual_low` | `cn` | Değer | Orta ölçekli düşük F/K ve PD/DD (`5B–60B CNY`), sektör kovası başına `hard_cap: 1` |
| `blue_chip_income` | `cn` | Gelir | Mega ölçekli likit temettü liderleri (`>= 50B CNY`) |
| `quality_value` | `cn` | GARP | Orta ölçekli büyüme değerleme istikrarı (`8B–120B CNY`, `>= MA20`) |
| `low_volatility_quality` | `cn` | Savunmacı | Düşük 20G oynaklık, kontrollü düşüş ve ATR (günlük K-çizgisi) |
| `balanced_alpha` | `cn` | Çok Faktörlü | Sektör sert üst sınırıyla geniş dengeli faktör keşfi |
| `momentum_quality` | `cn` | Trend Kalitesi | 60G trend onayı + kalite kapıları |
| `shrink_pullback` | `cn` | Geri Çekilme | Yükseliş trendinde MA20 desteğine daralan hacimli geri çekilme (günlük K-çizgisi) |
| `capital_heat` | `cn` | Momentum | Aşırı ısınma olmadan aktif devir hızı ve sermaye akışı |
| `oversold_reversal` | `cn` | Dönüş | Kontrollü düşüşlü ortalamaya dönüş adayları |
| `volume_breakout` | `cn` | Kırılım | 20G direncini kıran hacim genişlemesi |
| `global_value` | `us, hk, jp, kr, tw, in` | Değer | Küresel piyasalar için para biriminden bağımsız düşük F/K ve PD/DD tarayıcısı |
| `us_momentum_quality` | `us` | Trend | ABD büyük ölçekli (`>= $2B`) momentum + kalite |

</details>

<details>
<summary><strong>Tek Satırlık 12 Kanallı Anlık Bildirim (<code>NOTIFY_URLS</code>) ve Atom RSS</strong></summary>

Sıfır ek bağımlılıkla **virgül/yeni satır ile ayrılmış tek bir `NOTIFY_URLS` değişkeni** yapılandırın (`flock` korumalı `(trade_date, channel)` idempotency + otomatik token maskeleme; eski ortam değişkenleri uyumlu kalır):

```bash
NOTIFY_URLS="pushplus://TOKEN,sct://SENDKEY,bark://api.day.app/KEY,mailto://sender@qq.com:auth@qq.com?to=a@qq.com,https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
```

| Kanal | `NOTIFY_URLS` URI / URL | Bağımsız Ortam Değişkenleri |
|---|---|---|
| **PushPlus** | `pushplus://TOKEN[/TOPIC]` | `PUSHPLUS_TOKEN`, `PUSHPLUS_TOPIC` |
| **ServerChan / ServerChan3** | `sct://SENDKEY` (`SCT...` ve `sctp123t...`) | `SERVERCHAN_SENDKEY` |
| **Bark** | `bark://KEY` veya `bark://host/KEY` | `BARK_URL` |
| **Email SMTP** | `mailto://user:pass@host[:port]?to=a,b` | `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVERS` |
| **WeCom** | `wecom://KEY` veya webhook URL | `WECOM_WEBHOOK_URL` |
| **Feishu** | `feishu://TOKEN[#secret=SEC]` veya webhook URL | `FEISHU_WEBHOOK_URL`, `FEISHU_WEBHOOK_SECRET` |
| **DingTalk** | `dingtalk://TOKEN[#secret=SEC]` veya webhook URL | `DINGTALK_WEBHOOK_URL`, `DINGTALK_WEBHOOK_SECRET` |
| **Telegram** | `tgram://BOT_TOKEN/CHAT_ID` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **Discord** | `discord://ID/TOKEN` veya webhook URL | `DISCORD_WEBHOOK_URL` |
| **Slack** | `slack://T.../B.../...` veya webhook URL | `SLACK_WEBHOOK_URL` |
| **ntfy** | `ntfy://topic` veya `https://ntfy.sh/topic` | `NTFY_URL` |
| **Custom JSON / Apprise** | `custom://https://...` veya Apprise şeması | `CUSTOM_WEBHOOK_URL`, `CUSTOM_WEBHOOK_TOKEN` |

Atom 1.0 RSS akışı: [`site/feed.xml`](https://alphasift.zhulinsen.tech/site/feed.xml). Yerel olarak `alphasift notify status` ve `alphasift notify test --dry-run` ile doğrulayın.

</details>

<details>
<summary><strong>Desteklenen Piyasalar, Bağımsız Örnek Çalıştırma ve Temel Ortam Değişkenleri</strong></summary>

| Piyasa | Anlık Görüntü ve Günlük Kaynak | Kapsam Notları |
|---|---|---|
| `cn` | `em_datacenter -> sina -> efinance -> akshare_em` (token ile `tushare` ilk sırada); `DailyPack` / `tencent` / `sina` / `akshare` / `baostock` | Tam A-hissesi evreni, EastMoney sektör tamamlama, duyurular ve öne çıkanlar |
| `us, hk, jp, tw, in` | Yahoo Finance tarayıcısı + `yfinance` | Büyük/orta ölçekli alt sınır (`>= ~$1B` / `HK$8B` / `JPY 150B`), tek resmi olmayan uç nokta |
| `kr` | Yahoo Finance tarayıcısı + Naver Finance mobil API | Naver F/K ve PD/DD sağlar (`ALPHASIFT_KR_VALUATION=0` devre dışı bırakır); `~10s` ek süre |

- **2026-11-20 `--no-llm` örneği**: CN `dual_low` (5,215 -> 205 -> 5 farklı sektör: `601997`, `601117`, `600741`, `603799`, `601233`), HK `global_value` (`0267.HK`, `0001.HK`, `1339.HK`, `1398.HK`, `0358.HK`), JP `global_value` (`9501.T`, `5401.T`, `1605.T`, `9104.T`, `9022.T`).
- **Temel ortam değişkenleri**: `LLM_MODEL` (varsayılan `gemini/gemini-3.8-flash`), `LLM_FALLBACK_MODELS` (`gemini/gemini-4-hydrogen`), `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`, `LLM_CANDIDATE_CONTEXT_ENABLED=true` (CI Actions'da etkin; yerelde varsayılan kapalı), `NOTIFY_URLS`, `ALPHASIFT_ENABLE_PAGES=true`, `TUSHARE_TOKEN`, `DSA_API_URL`. Bkz. [docs/configuration.md](docs/configuration.md).
- **Bilinen sınırlamalar**: Yalnızca araştırma tarama ve denetim motorudur (emir yönlendirme veya temettüye göre düzeltilmiş portföy simülasyonu yoktur). `2026-11-21` öncesi `track-record` çalıştırmaları `close` girişini kullandı; `2026-11-21+` CN, ham tavan fiyat engeli muhasebesiyle `next_open` kullanır.

</details>

---

## 🔗 Quant Trio Ekosistemi

| Proje | Yığındaki Rolü | Nasıl Bağlanır |
|---|---|---|
| **[AlphaEvo](https://github.com/ZhuLinsen/alphaevo)** | Araştırma ve Faktör Madenciliği | Alfa genomlarını AlphaSift YAML kurallarına damıtmadan önce keşfeder ve stres testine tabi tutar |
| **[AlphaSift](https://github.com/ZhuLinsen/alphasift)** | **Çok Piyasalı Huni ve Kıyaslama** | 7 piyasada `5,000+` sembolü tarar → kısa listeye alınan seçimleri çıkarır ve `T+5 / 10 / 20` performansını denetler |
| **[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)** | L3 Tek Hisse Derin Analizi | Ayrıntılı temel veriler, haberler ve eylem planları için kısa listeye alınan seçimleri `DSA_API_URL` veya MCP üzerinden alır |

MCP araç şemaları ve Docker ayrıntıları için [docs/ecosystem.md](docs/ecosystem.md) dosyasına bakın.

---

## Sorumluluk Reddi, Dokümanlar ve Lisans

> Bu depo yalnızca araştırma, mühendislik doğrulaması ve eğitim deneyleri amacıyla oluşturulmuştur — hiçbir zaman yatırım tavsiyesi veya al/sat önerisi değildir. Piyasa verileri, LLM sıralamaları ve formasyon sinyalleri eksik veya gecikmeli olabilir.

[Kullanım](docs/usage.md) · [Yapılandırma](docs/configuration.md) · [Rejim Araştırması](docs/pattern-regime-research.md) · [Ekosistem ve MCP](docs/ecosystem.md) · [Dağıtım ve Ayna](docs/deployment.md) · [Strateji Rehberi](docs/strategy-guide.md) · [Puanlama](docs/scoring.md) · [Sonuç Şeması](docs/result-schema.md) · [Referans](docs/reference.md) · [Katkıda Bulunma](CONTRIBUTING.md) · [Güvenlik](SECURITY.md) · [Değişiklik Günlüğü](docs/CHANGELOG.md) · [SKILL.md](SKILL.md)

[Apache License 2.0](LICENSE) altında lisanslanmıştır.

## Topluluk

[LINUX DO](https://linux.do/) topluluğuna teşekkürler.