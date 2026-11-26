import threading
import time

import pandas as pd

import alphasift.candidate_context as candidate_context
from alphasift.candidate_context import (
    classify_announcement_categories,
    classify_negative_events,
    collect_candidate_context,
    fetch_stock_fund_flow_summary,
    fetch_stock_quote_summary,
    reset_provider_cooldowns,
)


def test_collect_candidate_context_uses_requested_providers(monkeypatch):
    class FakeAkshare:
        @staticmethod
        def stock_news_em(symbol):
            return pd.DataFrame([
                {"发布时间": "2026-04-28", "文章来源": "测试", "新闻标题": f"{symbol} 获资金关注"},
            ])

        @staticmethod
        def stock_individual_fund_flow(stock, market):
            return pd.DataFrame([
                {"日期": "2026-04-28", "主力净流入-净额": "1000万", "主力净流入-净占比": "3.5%"},
            ])

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)
    candidates = pd.DataFrame([{"code": 1.0, "name": "平安银行"}])

    rows, errors = collect_candidate_context(
        candidates,
        providers=["news", "fund_flow"],
    )

    assert errors == []
    assert rows[0]["code"] == "000001"
    assert "获资金关注" in rows[0]["news"]
    assert "主力净流入" in rows[0]["fund_flow"]
    assert rows[0]["source_count"] == 2
    assert rows[0]["source_confidence"] == 1.0
    assert rows[0]["source_weight_score"] == 1.0
    assert "新闻:" in rows[0]["context_summary"]
    assert isinstance(rows[0]["event_tags"], list)
    assert isinstance(rows[0]["negative_event_flags"], list)


def test_fetch_stock_quote_summary_parses_tencent_quote(monkeypatch):
    captured = {}
    parts = [""] * 50
    parts[1] = "平安银行"
    parts[3] = "11.24"
    parts[32] = "2.74"
    parts[33] = "11.25"
    parts[34] = "10.88"
    parts[37] = "226304"
    parts[38] = "1.05"
    parts[39] = "5.07"
    parts[44] = "2181.19"
    parts[45] = "2181.23"

    class FakeResponse:
        text = 'v_sz000001="' + "~".join(parts) + '";'

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("alphasift.candidate_context.requests.get", fake_get)

    summary = fetch_stock_quote_summary("1")

    assert captured["url"] == "https://qt.gtimg.cn/q=sz000001"
    assert captured["headers"]["User-Agent"] == "Mozilla/5.0"
    assert "现价=11.24" in summary
    assert "换手率=1.05" in summary
    assert "市盈率=5.07" in summary


def test_collect_candidate_context_supports_quote_provider(monkeypatch):
    monkeypatch.setattr(
        candidate_context,
        "fetch_stock_quote_summary",
        lambda code: "现价=11.24，市盈率=5.07，换手率=1.05",
    )
    candidates = pd.DataFrame([{"code": "000001", "name": "平安银行"}])

    rows, errors = collect_candidate_context(candidates, providers=["quote"])

    assert errors == []
    assert rows[0]["quote"] == "现价=11.24，市盈率=5.07，换手率=1.05"
    assert rows[0]["source_count"] == 1
    assert rows[0]["source_confidence"] == 1.0
    assert "行情估值:现价=11.24" in str(rows[0]["context_summary"])


def test_collect_candidate_context_concurrent_fetch_preserves_candidate_order(monkeypatch):
    barrier = threading.Barrier(2)

    def fake_news_summary(code, *, limit=3):
        barrier.wait(timeout=1)
        if code == "000001":
            time.sleep(0.05)
        return f"{code} 获资金关注"

    monkeypatch.setattr(candidate_context, "fetch_stock_news_summary", fake_news_summary)
    candidates = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行"},
            {"code": "000002", "name": "万科A"},
        ]
    )

    rows, errors = collect_candidate_context(candidates, providers=["news"])

    assert errors == []
    assert [row["code"] for row in rows] == ["000001", "000002"]
    assert rows[0]["news"] == "000001 获资金关注"
    assert rows[1]["news"] == "000002 获资金关注"


def test_collect_candidate_context_records_row_errors_without_aborting_other_candidates(monkeypatch):
    def fake_news_summary(code, *, limit=3):
        if code == "000001":
            raise ConnectionError("disconnect")
        return f"{code} 获资金关注"

    monkeypatch.setattr(candidate_context, "fetch_stock_news_summary", fake_news_summary)
    candidates = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行"},
            {"code": "000002", "name": "万科A"},
        ]
    )

    rows, errors = collect_candidate_context(candidates, providers=["news"])

    assert [row["code"] for row in rows] == ["000002"]
    assert errors == ["000001 news: disconnect"]


def test_collect_candidate_context_uses_cache(monkeypatch, tmp_path):
    calls = []
    calls_lock = threading.Lock()

    def fake_news_summary(code, *, limit=3):
        with calls_lock:
            calls.append(code)
        return f"{code} 首次抓取"

    monkeypatch.setattr(candidate_context, "fetch_stock_news_summary", fake_news_summary)
    candidates = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行"},
            {"code": "000002", "name": "万科A"},
        ]
    )

    first, _ = collect_candidate_context(
        candidates,
        providers=["news"],
        cache_dir=tmp_path,
    )
    second, _ = collect_candidate_context(
        candidates,
        providers=["news"],
        cache_dir=tmp_path,
    )

    assert sorted(calls) == ["000001", "000002"]
    assert second == first


def test_collect_candidate_context_enriches_legacy_cache(tmp_path):
    cache = tmp_path / "000001_news.json"
    cache.write_text(
        """
        {
          "cached_at": "2999-01-01T00:00:00",
          "row": {
            "code": "000001",
            "name": "平安银行",
            "news": "公司公告回购计划，收到监管问询函",
            "context_summary": "新闻:旧摘要"
          }
        }
        """,
        encoding="utf-8",
    )
    candidates = pd.DataFrame([{"code": "000001", "name": "平安银行"}])

    rows, errors = collect_candidate_context(
        candidates,
        providers=["news"],
        cache_dir=tmp_path,
    )

    assert errors == []
    assert "回购增持" in rows[0]["event_tags"]
    assert "监管" in rows[0]["negative_event_flags"]
    assert "负面风险:监管" in rows[0]["context_summary"]


def test_collect_candidate_context_partial_sources_have_partial_confidence(monkeypatch):
    class FakeAkshare:
        @staticmethod
        def stock_news_em(symbol):
            return pd.DataFrame([
                {"发布时间": "2026-04-28", "新闻标题": f"{symbol} 获资金关注"},
            ])

        @staticmethod
        def stock_individual_fund_flow(stock, market):
            return pd.DataFrame()

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)
    candidates = pd.DataFrame([{"code": "000001", "name": "平安银行"}])

    rows, errors = collect_candidate_context(
        candidates,
        providers=["news", "fund_flow"],
    )

    assert errors == []
    assert rows[0]["source_count"] == 1
    assert rows[0]["source_confidence"] == 0.5
    assert rows[0]["source_weight_score"] == 0.4643


def test_collect_candidate_context_accepts_custom_source_weights(monkeypatch):
    class FakeAkshare:
        @staticmethod
        def stock_news_em(symbol):
            return pd.DataFrame([
                {"发布时间": "2026-04-28", "新闻标题": f"{symbol} 获资金关注"},
            ])

        @staticmethod
        def stock_zh_a_disclosure_report_cninfo(**kwargs):
            return pd.DataFrame()

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)
    candidates = pd.DataFrame([{"code": "000001", "name": "平安银行"}])

    rows, errors = collect_candidate_context(
        candidates,
        providers=["news", "announcement"],
        source_weights={"news": 0.5, "announcement": 2.0},
    )

    assert errors == []
    assert rows[0]["source_confidence"] == 0.5
    assert rows[0]["source_weight_score"] == 0.2


def test_classify_negative_events_from_announcement_text():
    row = {
        "code": "000001",
        "announcement": "股东拟减持股份，公司收到监管问询函",
        "news": "公司公告回购计划",
    }

    flags = classify_negative_events(row)

    assert "减持" in flags
    assert "监管" in flags


def test_classify_announcement_categories_from_announcement_text():
    row = {
        "code": "000001",
        "announcement": "公司发布年度业绩预增公告，并披露股份回购方案",
    }

    categories = classify_announcement_categories(row)

    assert "业绩" in categories
    assert "回购增持" in categories


def test_classify_negative_events_disambiguates_false_positives_and_falls_back_to_search(monkeypatch):
    # Benign routine filings must NOT trigger false alarms
    benign_cases = [
        "2026-10-30 关于计提资产减值准备的公告",
        "2026-10-28 2026年度第一期科技创新债券发行结果公告",
        "2026-11-15 关于控股股东部分股份解除质押的公告",
        "2026-11-18 关于股东承诺不减持及提前终止减持计划的公告",
        "2026-11-12 关于收到诉讼胜诉判决及结案的公告",
        "2026-11-14 FIRST BEST STOCK LISTING announcement",
    ]
    for title in benign_cases:
        assert classify_negative_events({"announcement": title}) == [], f"false positive for: {title}"

    # Genuine severe or mixed cases MUST still trigger
    assert "财务风险" in classify_negative_events({"announcement": "关于大额计提资产减值准备并预计亏损的公告"})
    assert "业绩压力" in classify_negative_events({"announcement": "关于大额计提资产减值准备并预计亏损的公告"})
    assert "减持" in classify_negative_events({"announcement": "部分股东承诺不减持 | 实控人拟减持3%"})
    assert "退市风险" in classify_negative_events({"announcement": "关于公司股票被实施*ST退市风险警示的公告"})
    assert "诉讼风险" in classify_negative_events({"announcement": "2026-11-10 关于控股股东涉诉进展公告"})
    assert "质押冻结" in classify_negative_events({"announcement": "2026-11-07 华友钴业关于控股股东部分股份质押的公告"})
    assert "诉讼风险" not in classify_negative_events({"announcement": "2026-11-07 华友钴业关于控股股东部分股份质押的公告"})

    # fetch_stock_news_summary falls back to web search when akshare stock_news_em is empty
    class EmptyAkshare:
        @staticmethod
        def stock_news_em(symbol):
            return pd.DataFrame()

    monkeypatch.setitem(__import__("sys").modules, "akshare", EmptyAkshare)
    monkeypatch.setattr(
        "alphasift.market_news.search_stock_news_via_web",
        lambda query, *, limit=3: [{"published_at": "11-20", "source": "Tavily", "title": "601668 签重大工程合同"}],
    )
    out = candidate_context.fetch_stock_news_summary("601668", limit=2)
    assert "签重大工程合同" in out


def test_fetch_cn_market_news_dedupes_filters_noise_and_falls_back(monkeypatch, tmp_path):
    from alphasift.market_news import fetch_cn_market_news, search_stock_news_via_web

    class _Resp:
        def __init__(self, status_code: int, body: dict):
            self.status_code = status_code
            self._body = body

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code} api_key=tvly-secret-12345")

        def json(self) -> dict:
            return self._body

    def fake_get(url: str, **kwargs):
        if "eastmoney.com" in url:
            return _Resp(200, {
                "data": {
                    "fastNewsList": [
                        {"title": "互动平台：某公司回复投资者提问", "summary": "", "showTime": "2026-11-20 15:05:00"},
                        {"title": "央行开展逆回购操作呵护月末流动性", "summary": "政策信号", "showTime": "2026-11-20 15:30:00"},
                        {"title": "证监会发布市值管理新规指引", "summary": "", "showTime": "2026-11-20 16:10:00"},
                    ]
                }
            })
        if "10jqka.com.cn" in url:
            return _Resp(200, {
                "data": {
                    "list": [
                        {"title": "央行开展逆回购操作呵护月末流动性", "digest": "dup", "rtime": "2026-11-20 15:31:00"},
                        {"title": "半导体国产替代板块尾盘异动", "digest": "板块拉升", "rtime": "2026-11-20 14:55:00"},
                    ]
                }
            })
        raise RuntimeError("offline")

    monkeypatch.setattr("alphasift.market_news.requests.get", fake_get)
    items, sources, errs = fetch_cn_market_news(limit=3, trade_date="2026-11-20", cache_dir=tmp_path)
    assert not errs
    assert "东方财富7x24" in sources
    titles = [x["title"] for x in items]
    # Duplicate excluded, low-signal 互动平台 deprioritized when sufficient clean headlines exist
    assert len(titles) == 3
    assert "互动平台：某公司回复投资者提问" not in titles
    assert "央行开展逆回购操作呵护月末流动性" in titles

    # Error redaction on Tavily web fallback
    def broken_post(url: str, **kwargs):
        raise RuntimeError("boom key=tvly-super-secret-xyz")

    monkeypatch.setattr("alphasift.market_news.requests.post", broken_post)
    monkeypatch.setenv("TAVILY_API_KEYS", "tvly-super-secret-xyz")
    assert search_stock_news_via_web("test query") == []


def test_fetch_stock_fund_flow_summary_supports_akshare_1_20_rename(monkeypatch):
    seen_calls: list[tuple[str, dict[str, object]]] = []

    class FakeAkNew:
        @staticmethod
        def stock_fund_flow_individual_hist_em(symbol):
            seen_calls.append(("new", {"symbol": symbol}))
            return pd.DataFrame([
                {"日期": "2026-11-24", "主力净流入-净额": "2.1亿", "主力净流入-净占比": "6.2%"},
            ])

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkNew)
    summary_new = fetch_stock_fund_flow_summary("600519")
    assert seen_calls == [("new", {"symbol": "600519"})]
    assert "主力净流入-净额=2.1亿" in summary_new

    class FakeAkLegacy:
        @staticmethod
        def stock_individual_fund_flow(stock, market):
            seen_calls.append(("legacy", {"stock": stock, "market": market}))
            return pd.DataFrame([
                {"日期": "2026-11-24", "主力净流入-净额": "-800万"},
            ])

    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkLegacy)
    summary_legacy = fetch_stock_fund_flow_summary("000001")
    assert seen_calls[-1] == ("legacy", {"stock": "000001", "market": "sz"})
    assert "主力净流入-净额=-800万" in summary_legacy


def test_fund_flow_rate_limit_trips_circuit_breaker_and_collapses_errors(monkeypatch):
    reset_provider_cooldowns()
    calls: list[str] = []

    def fake_news(code, *, limit=3):
        return f"{code} 新闻正常"

    def fake_fund_flow(code):
        calls.append(code)
        raise ConnectionError(
            "东方财富 push2 行情服务器断开了连接，通常是短时间内请求过多，当前 IP 被临时限流。"
            "首次限流一般约 5 分钟后恢复，反复触发后可能需要 40 分钟以上；等待期间不要重复调用东方财富的行情接口。"
        )

    monkeypatch.setattr(candidate_context, "fetch_stock_news_summary", fake_news)
    monkeypatch.setattr(candidate_context, "fetch_stock_fund_flow_summary", fake_fund_flow)
    candidates = pd.DataFrame([
        {"code": "600699", "name": "均胜电子"},
        {"code": "688308", "name": "欧科亿"},
        {"code": "002414", "name": "高德红外"},
        {"code": "000021", "name": "深科技"},
    ])
    try:
        rows, errors = collect_candidate_context(candidates, max_rows=4, providers=["news", "fund_flow"])
        assert len(calls) == 1
        assert len(rows) == 4
        assert len(errors) == 2
        assert len(errors[0]) <= 160
        assert "fund_flow:" in errors[0]
        assert errors[1] == "fund_flow: provider cooldown active (skipped 3 candidates)"

        # Subsequent batch in the same process should keep fund_flow skipped cleanly (0 calls)
        rows2, errors2 = collect_candidate_context(candidates.head(2), max_rows=2, providers=["news", "fund_flow"])
        assert len(calls) == 1
        assert len(rows2) == 2
        assert errors2 == ["fund_flow: provider cooldown active (skipped 2 candidates)"]

        # Resetting cooldown restores normal fund_flow calls immediately
        reset_provider_cooldowns()
        monkeypatch.setattr(candidate_context, "fetch_stock_fund_flow_summary", lambda code: f"{code} 主力净流入=500万")
        rows3, errors3 = collect_candidate_context(candidates.head(1), max_rows=1, providers=["news", "fund_flow"])
        assert errors3 == []
        assert "500万" in str(rows3[0]["fund_flow"])
    finally:
        reset_provider_cooldowns()


def test_fund_flow_non_rate_limit_error_does_not_trip_cooldown(monkeypatch):
    reset_provider_cooldowns()

    def fake_fund_flow(code):
        if code == "600001":
            raise ValueError("bad symbol payload")
        return f"{code} 主力净流入=100万"

    monkeypatch.setattr(candidate_context, "fetch_stock_fund_flow_summary", fake_fund_flow)
    candidates = pd.DataFrame([
        {"code": "600001", "name": "A"},
        {"code": "600002", "name": "B"},
    ])
    try:
        rows, errors = collect_candidate_context(candidates, max_rows=2, providers=["fund_flow"])
        assert errors == ["600001 fund_flow: bad symbol payload"]
        assert [row["code"] for row in rows] == ["600002"]
        assert "100万" in str(rows[0]["fund_flow"])
    finally:
        reset_provider_cooldowns()


def test_candidate_context_scrubs_nonfinite_and_bool_cooldown_and_weights():
    import math

    reset_provider_cooldowns()
    try:
        candidate_context._trip_provider_cooldown("fund_flow", cooldown_sec=float("nan"), now=100.0)
        until_nan_cd = candidate_context._PROVIDER_COOLDOWN_UNTIL["fund_flow"]
        assert math.isfinite(until_nan_cd)
        assert until_nan_cd == 100.0 + candidate_context._PROVIDER_COOLDOWN_SEC

        reset_provider_cooldowns()
        candidate_context._trip_provider_cooldown("fund_flow", cooldown_sec=True, now=float("inf"))  # type: ignore[arg-type]
        until_bool_inf = candidate_context._PROVIDER_COOLDOWN_UNTIL["fund_flow"]
        assert math.isfinite(until_bool_inf)
        assert until_bool_inf > 0.0

        weights = candidate_context._normalized_source_weights({
            "news": float("nan"),
            "announcement": float("inf"),
            "fund_flow": True,  # type: ignore[dict-item]
            "quote": -2.0,
        })
        assert weights["news"] == candidate_context._SOURCE_WEIGHTS["news"]
        assert weights["announcement"] == candidate_context._SOURCE_WEIGHTS["announcement"]
        assert weights["fund_flow"] == candidate_context._SOURCE_WEIGHTS["fund_flow"]
        assert weights["quote"] == 0.0
    finally:
        reset_provider_cooldowns()
