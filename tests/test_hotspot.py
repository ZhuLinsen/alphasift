import json

import pandas as pd

from alphasift.hotspot import (
    HotspotStock,
    HotspotSummary,
    TimelineEvent,
    append_hotspot_history,
    assign_stock_roles,
    build_hotspot_route,
    classify_hotspot_stage,
    compute_hotspot_heat_score,
    discover_hotspots,
    get_hotspot_detail,
    load_hotspot_history,
    load_hotspots_json,
    load_hotspot_timeline,
    resolve_hotspot_topic,
    save_hotspots_json,
    score_hotspot_stock,
)


class FakeHotspotProvider:
    def stock_board_concept_name_em(self):
        return pd.DataFrame([
            {"板块名称": "AI算力", "涨跌幅": 3.0, "排名": 1},
            {"板块名称": "冷门概念", "涨跌幅": -1.0, "排名": 20},
        ])

    def stock_board_industry_name_em(self):
        return pd.DataFrame([
            {"名称": "银行", "涨跌幅": 2.0, "排名": 2},
        ])

    def stock_board_concept_cons_em(self, symbol):
        if symbol != "AI算力":
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "代码": "300001",
                "名称": "算力龙头",
                "涨跌幅": 10.1,
                "成交额": 2_000_000_000,
                "换手率": 12.0,
                "量比": 3.0,
                "主力净流入": 200_000_000,
                "活跃天数": 3,
                "证据数": 2,
            },
            {
                "代码": "300002",
                "名称": "算力助攻",
                "涨跌幅": 5.0,
                "成交额": 800_000_000,
                "换手率": 6.0,
                "量比": 2.0,
                "主力净流入": 50_000_000,
                "活跃天数": 2,
                "证据数": 1,
            },
        ])

    def stock_board_industry_cons_em(self, symbol):
        if symbol != "银行":
            return pd.DataFrame()
        return pd.DataFrame([
            {"代码": "000001", "名称": "平安银行", "涨跌幅": 2.0, "成交额": 900_000_000},
        ])


class FailingHotspotProvider:
    def stock_board_concept_name_em(self):
        raise RuntimeError("eastmoney disconnected")

    def stock_board_industry_name_em(self):
        raise RuntimeError("industry endpoint disconnected")

    def stock_board_concept_cons_em(self, symbol):
        raise RuntimeError(f"constituents failed for {symbol}")

    def stock_board_industry_cons_em(self, symbol):
        raise RuntimeError(f"industry constituents failed for {symbol}")


class ConstituentFailingProvider(FakeHotspotProvider):
    def stock_board_concept_cons_em(self, symbol):
        raise RuntimeError(f"constituents failed for {symbol}")

    def stock_board_industry_cons_em(self, symbol):
        raise RuntimeError(f"industry constituents failed for {symbol}")


class CanonicalOnlyProvider:
    def stock_board_concept_name_em(self):
        return pd.DataFrame([
            {"板块名称": "算力", "涨跌幅": 4.0, "排名": 1},
            {"板块名称": "机器人", "涨跌幅": 2.0, "排名": 2},
        ])

    def stock_board_industry_name_em(self):
        return pd.DataFrame()

    def stock_board_concept_cons_em(self, symbol):
        if symbol != "算力":
            return pd.DataFrame()
        return pd.DataFrame([
            {"代码": "300001", "名称": "算力龙头", "涨跌幅": 9.9, "成交额": 2_000_000_000},
        ])

    def stock_board_industry_cons_em(self, symbol):
        return pd.DataFrame()


def test_heat_score_matches_industry_board_semantics_and_stage_rules():
    assert compute_hotspot_heat_score(change_pct=1.0, rank=3) == 65.0
    assert classify_hotspot_stage(
        state="warming",
        trend_score=16,
        cooling_score=0,
        persistence_score=100,
        latest_score=76,
        observations=2,
    ) == "加速主升"
    assert classify_hotspot_stage(
        state="cooling",
        trend_score=-15,
        cooling_score=8,
        persistence_score=30,
        latest_score=55,
        observations=3,
    ) == "降温退潮"


def test_score_hotspot_stock_and_assign_roles_are_deterministic():
    leader = {
        "code": "300001",
        "name": "算力龙头",
        "change_pct": 10.0,
        "amount": 2_000_000_000,
        "turnover_rate": 12.0,
        "volume_ratio": 3.0,
        "net_inflow": 200_000_000,
        "is_limit_up": True,
        "active_days": 3,
        "evidence_count": 2,
    }
    rows = [
        leader,
        {
            "code": "300002",
            "name": "算力助攻",
            "change_pct": 5.0,
            "amount": 800_000_000,
            "turnover_rate": 6.0,
            "volume_ratio": 2.0,
            "net_inflow": 50_000_000,
            "active_days": 2,
            "evidence_count": 1,
        },
        {"code": "300003", "name": "补涨", "change_pct": 1.0, "amount": 100_000_000, "turnover_rate": 2.0},
        {"code": "300004", "name": "掉队", "change_pct": -4.0, "amount": 10_000_000, "net_inflow": -10_000_000},
    ]

    scored = [{**row, "hot_stock_score": score_hotspot_stock(row)} for row in rows]
    ranked = assign_stock_roles(scored)

    assert scored[0]["hot_stock_score"] == 100.0
    assert [item.code for item in ranked] == ["300001", "300002", "300003", "300004"]
    assert [item.role for item in ranked] == ["核心龙头", "助攻", "补涨", "掉队"]


def test_discover_hotspots_merges_history_trends_and_leaders(tmp_path):
    history = tmp_path / "hotspot.history.jsonl"
    history.write_text(
        '{"generated_at":"2026-06-04T10:00:00","board":"AI算力","max_board_heat_score":60}\n'
        '{"generated_at":"2026-06-05T10:00:00","board":"AI算力","max_board_heat_score":76}\n',
        encoding="utf-8",
    )

    hotspots = discover_hotspots(
        provider=FakeHotspotProvider(),
        max_boards=5,
        history_path=history,
        top=1,
    )

    assert len(hotspots) == 1
    assert hotspots[0].topic == "AI算力"
    assert hotspots[0].trend_score == 16
    assert hotspots[0].persistence_score == 100
    assert hotspots[0].stage == "加速主升"
    assert hotspots[0].sample_stock_count == 2
    assert hotspots[0].leaders == ["算力龙头"]


def test_load_hotspots_json_reads_saved_shape_and_skips_malformed_rows(tmp_path):
    cache = tmp_path / "hotspots.json"
    save_hotspots_json(
        cache,
        [
            HotspotSummary(
                topic="AI算力",
                source="concept",
                rank=1,
                heat_score=82.5,
                leaders=["算力龙头"],
            )
        ],
    )
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["metadata"]["schema_version"] == 2
    payload["hotspots"].extend([
        {"topic": "", "heat_score": 80},
        {"topic": "坏数据", "heat_score": 999},
        "not-a-row",
    ])
    cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    hotspots = load_hotspots_json(cache)

    assert len(hotspots) == 1
    assert hotspots[0].topic == "AI算力"
    assert hotspots[0].heat_score == 82.5
    assert hotspots[0].leaders == ["算力龙头"]


def test_load_hotspots_json_reads_old_array_and_dict_shapes(tmp_path):
    array_cache = tmp_path / "old-array.json"
    array_cache.write_text(
        json.dumps([{"topic": "AI算力", "source": "concept", "heat_score": 80}], ensure_ascii=False),
        encoding="utf-8",
    )
    dict_cache = tmp_path / "old-dict.json"
    dict_cache.write_text(
        json.dumps({"AI算力": {"topic": "AI算力", "heat_score": 81}}, ensure_ascii=False),
        encoding="utf-8",
    )

    assert load_hotspots_json(array_cache)[0].topic == "AI算力"
    assert load_hotspots_json(dict_cache)[0].heat_score == 81


def test_resolve_hotspot_topic_returns_canonical_candidates_from_cache(tmp_path):
    cache = tmp_path / "hotspots.json"
    save_hotspots_json(
        cache,
        [
            HotspotSummary(
                topic="算力",
                source="concept",
                rank=1,
                heat_score=84,
                aliases=["AI算力"],
            )
        ],
    )

    resolution = resolve_hotspot_topic("AI算力", fallback_cache_path=cache)

    assert resolution.canonical_topic == "算力"
    assert resolution.unresolved is False
    assert resolution.confidence >= 0.55
    assert resolution.candidates[0]["topic"] == "算力"


def test_discover_hotspots_falls_back_to_last_good_cache_on_provider_errors(tmp_path):
    cache = tmp_path / "hotspots.json"
    save_hotspots_json(
        cache,
        [HotspotSummary(topic="AI算力", source="concept", rank=1, heat_score=82, leaders=["算力龙头"])],
    )

    hotspots = discover_hotspots(
        provider=FailingHotspotProvider(),
        fallback_cache_path=cache,
        top=5,
    )

    assert len(hotspots) == 1
    assert hotspots[0].topic == "AI算力"
    assert hotspots[0].fallback_used is True
    assert hotspots[0].stale is True
    assert any("eastmoney disconnected" in error for error in hotspots[0].source_errors)
    assert getattr(hotspots, "fallback_used") is True


def test_discover_hotspots_tolerates_unknown_provider_and_none_without_network():
    hotspots = discover_hotspots(provider="unknown,none", top=5)

    assert list(hotspots) == []
    assert getattr(hotspots, "provider_used") == "none"
    assert any("unknown provider" in error for error in getattr(hotspots, "source_errors"))


def test_discover_hotspots_preserves_cached_leaders_when_constituents_fail(tmp_path):
    cache = tmp_path / "hotspots.json"
    save_hotspots_json(
        cache,
        [
            HotspotSummary(
                topic="AI算力",
                source="concept",
                rank=1,
                heat_score=82,
                leaders=["缓存龙头"],
                leader_stocks=[HotspotStock(code="300009", name="缓存龙头", role="核心龙头")],
            )
        ],
    )

    hotspots = discover_hotspots(
        provider=ConstituentFailingProvider(),
        fallback_cache_path=cache,
        top=1,
    )

    assert len(hotspots) == 1
    assert hotspots[0].topic == "AI算力"
    assert hotspots[0].fallback_used is True
    assert hotspots[0].quality_status == "partial"
    assert hotspots[0].leaders == ["缓存龙头"]
    assert hotspots[0].leader_stocks[0].source == "last_good_cache.leader_stocks"
    assert "live_stocks" in hotspots[0].missing_fields
    assert any("constituents failed for AI算力" in error for error in hotspots[0].source_errors)


def test_get_hotspot_detail_scores_stocks_and_sorts_timeline(tmp_path):
    timeline = tmp_path / "timeline.jsonl"
    timeline.write_text(
        '{"date":"2026-06-05","topic":"AI算力","source":"公告","title":"算力订单落地","event_type":"order","impact_score":8,"related_codes":["SZ300001"]}\n'
        'not-json\n'
        '{"date":"2026-06-04","topics":["AI算力"],"source":"新闻","title":"AI算力扩散","impact_score":6,"related_codes":"300002, bad"}\n'
        '{"date":"2026-06-03","topic":"银行","source":"新闻","title":"银行事件"}\n',
        encoding="utf-8",
    )

    detail = get_hotspot_detail(
        "AI算力",
        provider=FakeHotspotProvider(),
        top_stocks=2,
        timeline_path=timeline,
    )

    assert detail.summary.topic == "AI算力"
    assert detail.stocks[0].role == "核心龙头"
    assert [event.date for event in detail.timeline] == ["2026-06-04", "2026-06-05"]
    assert detail.timeline[0].related_codes == ["300002"]
    assert detail.timeline[1].related_codes == ["300001"]


def test_get_hotspot_detail_uses_canonical_topic_for_provider_lookup():
    detail = get_hotspot_detail(
        "AI算力",
        provider=CanonicalOnlyProvider(),
        top_stocks=1,
    )

    assert detail.summary.topic == "AI算力"
    assert detail.summary.canonical_topic == "算力"
    assert detail.summary.quality_status == "available"
    assert [stock.name for stock in detail.stocks] == ["算力龙头"]


def test_get_hotspot_detail_builds_display_route_from_timeline(tmp_path):
    timeline = tmp_path / "timeline.jsonl"
    timeline.write_text(
        '{"date":"2026-06-05T10:30:00","topic":"AI绠楀姏","source":"notice","title":"Order catalyst","description":"GPU cluster order landed and expanded demand visibility.","event_type":"order","impact_score":8,"related_codes":["SZ300001"],"url":"https://example.test/order"}\n'
        '{"date":"2026-06-04","topic":"AI绠楀姏","source":"news","title":"Early spread","impact_score":6,"related_codes":"300002"}\n',
        encoding="utf-8",
    )

    detail = get_hotspot_detail(
        "AI绠楀姏",
        provider=FakeHotspotProvider(),
        top_stocks=2,
        timeline_path=timeline,
    )

    assert [event.description for event in detail.timeline] == ["", "GPU cluster order landed and expanded demand visibility."]
    assert detail.timeline[1].url == "https://example.test/order"
    assert [item.date for item in detail.route] == ["2026-06-05", "2026-06-04"]
    assert detail.route[0].title == "Order catalyst"
    assert detail.route[0].description == "GPU cluster order landed and expanded demand visibility."
    assert detail.route[0].related_codes == ["300001"]


def test_get_hotspot_detail_falls_back_to_cache_and_keeps_valid_timeline(tmp_path):
    cache = tmp_path / "hotspots.json"
    timeline = tmp_path / "timeline.jsonl"
    save_hotspots_json(
        cache,
        [HotspotSummary(topic="AI算力", source="concept", rank=1, heat_score=82, leaders=["算力龙头"])],
    )
    timeline.write_text(
        '{"date":"2026-06-05","topic":"AI算力","source":"公告","title":"订单落地"}\n',
        encoding="utf-8",
    )

    detail = get_hotspot_detail(
        "AI算力",
        provider=FailingHotspotProvider(),
        top_stocks=3,
        fallback_cache_path=cache,
        timeline_path=timeline,
    )

    assert detail.summary.topic == "AI算力"
    assert detail.summary.fallback_used is True
    assert detail.summary.stale is True
    assert detail.summary.leaders == ["算力龙头"]
    assert len(detail.stocks) == 1
    assert detail.stocks[0].name == "算力龙头"
    assert detail.stocks[0].source == "last_good_cache.leaders"
    assert detail.stocks[0].fallback_used is True
    assert [event.title for event in detail.timeline] == ["订单落地"]
    assert any("eastmoney disconnected" in error for error in detail.summary.source_errors)


def test_get_hotspot_detail_uses_structured_leader_stock_fallback(tmp_path):
    cache = tmp_path / "hotspots.json"
    save_hotspots_json(
        cache,
        [
            HotspotSummary(
                topic="算力",
                source="concept",
                rank=1,
                heat_score=82,
                leaders=["算力龙头"],
                leader_stocks=[
                    HotspotStock(
                        code="300001",
                        name="算力龙头",
                        role="核心龙头",
                        hot_stock_score=90,
                        source="akshare.concept_constituents",
                        source_confidence=1.0,
                    )
                ],
            )
        ],
    )

    detail = get_hotspot_detail(
        "AI算力",
        provider="none",
        top_stocks=3,
        fallback_cache_path=cache,
    )

    assert detail.summary.canonical_topic == "算力"
    assert detail.summary.quality_status == "stale"
    assert detail.stocks[0].code == "300001"
    assert detail.stocks[0].source == "last_good_cache.leader_stocks"
    assert detail.stocks[0].source_confidence == 0.65
    assert detail.route[0].title == "Current fermentation"
    assert "heat 82.0" in detail.route[0].description
    assert detail.route[0].related_codes == ["300001"]


def test_get_hotspot_detail_records_timeline_failure_without_losing_cache(tmp_path):
    cache = tmp_path / "hotspots.json"
    save_hotspots_json(
        cache,
        [HotspotSummary(topic="AI算力", source="concept", rank=1, heat_score=82, leaders=["算力龙头"])],
    )

    detail = get_hotspot_detail(
        "AI算力",
        provider="none",
        fallback_cache_path=cache,
        timeline_path=tmp_path / "missing.jsonl",
    )

    assert detail.stocks[0].name == "算力龙头"
    assert "timeline" in detail.summary.missing_fields
    assert any("timeline:" in error for error in detail.summary.source_errors)


def test_build_hotspot_route_groups_by_day_and_compacts_long_text():
    long_description = " ".join(["demand"] * 80)

    route = build_hotspot_route(
        HotspotSummary(topic="AI绠楀姏", heat_score=88),
        [
            TimelineEvent(
                date="2026-06-05T10:30:00",
                source="news",
                title="first catalyst",
                description=long_description,
                impact_score=5,
                related_codes=["300001"],
            ),
            TimelineEvent(
                date="2026-06-05T14:00:00",
                source="notice",
                title="second catalyst",
                description="contract disclosed",
                event_type="announcement",
                impact_score=9,
                related_codes=["300002"],
            ),
            TimelineEvent(
                date="2026-06-04",
                source="news",
                title="early spread",
                impact_score=3,
            ),
        ],
        max_description_chars=60,
    )

    assert [item.date for item in route] == ["2026-06-05", "2026-06-04"]
    assert route[0].title == "second catalyst"
    assert route[0].impact_score == 9
    assert route[0].related_codes == ["300002", "300001"]
    assert len(route[0].description) <= 60


def test_history_append_loads_trend_compatible_jsonl(tmp_path):
    history = tmp_path / "hotspot.history.jsonl"

    append_hotspot_history(
        history,
        [HotspotSummary(topic="AI算力", source="concept", rank=1, heat_score=72.5, leaders=["算力龙头"])],
        generated_at="2026-06-05T10:00:00",
    )

    rows = load_hotspot_history(history)
    assert rows[0]["topic"] == "AI算力"
    assert rows[0]["board"] == "AI算力"
    assert rows[0]["max_board_heat_score"] == 72.5
    assert rows[0]["leaders"] == ["算力龙头"]


def test_load_hotspot_timeline_skips_malformed_rows(tmp_path):
    path = tmp_path / "timeline.jsonl"
    path.write_text(
        '{"date":"2026-06-05","topic":"机器人","source":"新闻","title":"订单增长","related_codes":["300001"]}\n'
        '{"date":"2026-06-04","topic":"机器人","source":"公告"}\n'
        'not-json\n'
        '{"date":"2026-06-03","topic":"AI算力","source":"新闻","title":"无关"}\n',
        encoding="utf-8",
    )

    events = load_hotspot_timeline(path, topic="机器人")

    assert len(events) == 1
    assert events[0].title == "订单增长"
    assert events[0].related_codes == ["300001"]


def test_hotspot_scrubs_nonfinite_and_bool_heat_rank_and_clamp():
    from alphasift.hotspot import HotspotSummary, _clamp, _hotspot_sort_key, score_hotspot_stock

    assert _clamp(float("nan"), 0.0, 18.0) == 0.0
    assert _clamp(float("inf"), 0.0, 18.0) == 0.0
    assert _clamp(True, 0.0, 18.0) == 0.0  # type: ignore[arg-type]
    assert _clamp(25.0, 0.0, 18.0) == 18.0

    bad_item = HotspotSummary(
        topic="测试概念",
        heat_score=float("nan"),
        trend_score=float("inf"),
        persistence_score=True,  # type: ignore[arg-type]
        cooling_score=float("-inf"),
        change_pct=float("nan"),
        rank=True,  # type: ignore[arg-type]
    )
    good_item = HotspotSummary(topic="真实算力", heat_score=76.0, change_pct=2.1, rank=2)
    ordered = sorted([bad_item, good_item], key=_hotspot_sort_key, reverse=True)
    assert ordered[0].topic == "真实算力"

    stock_score = score_hotspot_stock({"change_pct": float("nan"), "amount": float("inf"), "net_inflow": True})
    assert isinstance(stock_score, float) and stock_score == stock_score


def test_hotspot_roles_and_limits_scrub_nonfinite_and_bool_inputs():
    from dataclasses import asdict
    import json

    from alphasift.hotspot import HotspotStock, assign_stock_roles, discover_hotspots

    bad_stock = HotspotStock(
        code="300001",
        name="异常股",
        change_pct=float("nan"),
        amount=float("inf"),
        hot_stock_score=float("nan"),
    )
    good_stock = HotspotStock(
        code="300002",
        name="算力真龙头",
        change_pct=8.5,
        amount=2e9,
        hot_stock_score=86.0,
    )
    roles = assign_stock_roles([bad_stock, good_stock])
    assert roles[0].code == "300002"
    assert roles[0].role == "核心龙头"
    json.dumps([asdict(item) for item in roles], allow_nan=False)

    provider = {
        "concept_boards": pd.DataFrame([
            {"板块名称": "AI算力", "排名": 1, "涨跌幅": 3.5},
            {"板块名称": "半导体", "排名": 2, "涨跌幅": 2.0},
            {"板块名称": "机器人", "排名": 3, "涨跌幅": 1.2},
        ])
    }
    res_nan_top = discover_hotspots(provider=provider, max_boards=float("nan"), top=True)  # type: ignore[arg-type]
    assert len(res_nan_top) == 3
    res_zero_top = discover_hotspots(provider=provider, top=-5)
    assert res_zero_top == []
