import os
import sys

import pandas as pd

from alphasift.industry import (
    enrich_industry_concepts,
    fetch_akshare_board_map,
    load_board_heat_trends,
    load_industry_map,
    save_industry_map,
)


def test_load_industry_map_from_csv(tmp_path):
    path = tmp_path / "industry.csv"
    path.write_text(
        "code,industry,concepts,board_heat_score,board_heat_summary\n"
        "000001,银行,低估值,72.5,银行:+1.20%:rank=3\n",
        encoding="utf-8",
    )

    mapping = load_industry_map(path)

    assert mapping["000001"]["industry"] == "银行"
    assert mapping["000001"]["concepts"] == "低估值"
    assert mapping["000001"]["board_heat_score"] == 72.5
    assert mapping["000001"]["board_heat_summary"] == "银行:+1.20%:rank=3"


def test_load_industry_map_normalizes_numeric_and_suffixed_codes(tmp_path):
    path = tmp_path / "industry.json"
    path.write_text(
        """
        [
          {"code": 1.0, "industry": "银行"},
          {"code": "SZ000002", "concepts": "地产链"}
        ]
        """,
        encoding="utf-8",
    )

    mapping = load_industry_map(path)

    assert mapping["000001"]["industry"] == "银行"
    assert mapping["000002"]["concepts"] == "地产链"


def test_enrich_industry_concepts_from_file(tmp_path):
    path = tmp_path / "industry.csv"
    path.write_text(
        "code,industry,concepts,board_heat_score,board_heat_summary\n"
        "000001,银行,低估值,72.5,银行:+1.20%:rank=3\n"
        "600000,银行,中特估,61.0,银行:+0.20%:rank=12\n",
        encoding="utf-8",
    )
    df = pd.DataFrame([
        {"code": "000001", "name": "平安银行"},
        {"code": "600000", "name": "浦发银行", "concepts": "破净"},
    ])

    enriched, notes = enrich_industry_concepts(df, map_files=[path])

    assert enriched.loc[0, "industry"] == "银行"
    assert enriched.loc[0, "concepts"] == "低估值"
    assert enriched.loc[0, "board_heat_score"] == 72.5
    assert "银行:+1.20%" in enriched.loc[0, "board_heat_summary"]
    assert enriched.loc[1, "concepts"] == "破净,中特估"
    assert any("industry/concepts enrichment applied" in item for item in notes)


def test_enrich_industry_concepts_from_file_does_not_iterate_snapshot_rows(tmp_path, monkeypatch):
    path = tmp_path / "industry.csv"
    path.write_text(
        "code,industry,concepts,board_heat_score,board_heat_trend_score,board_heat_summary\n"
        "000001,银行,低估值,72.5,12.5,银行:+1.20%:rank=3\n"
        "600000,银行,中特估,61.0,-8.0,银行:+0.20%:rank=12\n",
        encoding="utf-8",
    )
    df = pd.DataFrame([
        {"code": "000001", "name": "平安银行"},
        {"code": "600000", "name": "浦发银行", "concepts": "破净"},
    ])

    def fail_iterrows(self):
        raise AssertionError("snapshot enrichment should use merge/vectorized application")

    monkeypatch.setattr(pd.DataFrame, "iterrows", fail_iterrows)

    enriched, notes = enrich_industry_concepts(df, map_files=[path])

    assert enriched.loc[0, "industry"] == "银行"
    assert enriched.loc[1, "concepts"] == "破净,中特估"
    assert enriched.loc[0, "board_heat_trend_score"] == 12.5
    assert any("industry/concepts enrichment applied" in item for item in notes)


def test_enrich_industry_concepts_preserves_existing_concepts_after_vectorized_merge(tmp_path):
    path = tmp_path / "industry.csv"
    path.write_text(
        "code,industry,concepts,board_heat_score,board_heat_trend_score,board_heat_summary,board_heat_state\n"
        "000001,银行,低估值,72.5,8.0,银行:+1.20%:rank=3,warming\n",
        encoding="utf-8",
    )
    df = pd.DataFrame([
        {
            "code": "000001",
            "industry": "金融",
            "concepts": "破净,低估值",
            "board_heat_score": 80.0,
            "board_heat_trend_score": -12.0,
            "board_heat_summary": "金融:+0.50%:rank=8",
            "board_heat_state": "cooling",
        },
    ])

    enriched, _ = enrich_industry_concepts(df, map_files=[path])

    assert enriched.loc[0, "industry"] == "金融"
    assert enriched.loc[0, "concepts"] == "破净,低估值"
    assert enriched.loc[0, "board_heat_score"] == 80.0
    assert enriched.loc[0, "board_heat_trend_score"] == -12.0
    assert enriched.loc[0, "board_heat_summary"] == "金融:+0.50%:rank=8 | 银行:+1.20%:rank=3"
    assert enriched.loc[0, "board_heat_state"] == "cooling"


def test_enrich_industry_concepts_loads_companion_heat_history(tmp_path):
    path = tmp_path / "industry.csv"
    path.write_text(
        "code,industry,concepts,board_heat_score,board_heat_summary\n"
        "000001,银行,低估值,72.5,银行:+1.20%:rank=3\n",
        encoding="utf-8",
    )
    history = tmp_path / "industry.csv.history.jsonl"
    history.write_text(
        '{"generated_at":"2026-04-27T10:00:00","board":"银行","max_board_heat_score":60}\n'
        '{"generated_at":"2026-04-27T11:00:00","board":"银行","max_board_heat_score":999}\n'
        'not-json\n'
        '{"generated_at":"2026-04-28T10:00:00","board":"银行","max_board_heat_score":72.5}\n',
        encoding="utf-8",
    )

    trends = load_board_heat_trends(history)
    enriched, notes = enrich_industry_concepts(
        pd.DataFrame([{"code": "000001", "name": "平安银行"}]),
        map_files=[path],
    )

    assert trends["银行"]["board_heat_trend_score"] == 12.5
    assert trends["银行"]["board_heat_latest_score"] == 72.5
    assert trends["银行"]["board_heat_persistence_score"] == 100.0
    assert trends["银行"]["board_heat_state"] == "warming"
    assert enriched.loc[0, "board_heat_latest_score"] == 72.5
    assert enriched.loc[0, "board_heat_trend_score"] == 12.5
    assert enriched.loc[0, "board_heat_persistence_score"] == 100.0
    assert enriched.loc[0, "board_heat_observations"] == 2
    assert enriched.loc[0, "board_heat_state"] == "warming"
    assert any("board heat trends loaded" in item for item in notes)


def test_load_board_heat_trends_uses_rolling_window_and_cooling_signal(tmp_path):
    history = tmp_path / "industry.csv.history.jsonl"
    history.write_text(
        '{"generated_at":"2026-04-24T10:00:00","board":"AI算力","max_board_heat_score":82}\n'
        '{"generated_at":"2026-04-25T10:00:00","board":"AI算力","max_board_heat_score":78}\n'
        '{"generated_at":"2026-04-26T10:00:00","board":"AI算力","max_board_heat_score":70}\n'
        '{"generated_at":"2026-04-27T10:00:00","board":"AI算力","max_board_heat_score":62}\n'
        '{"generated_at":"2026-04-28T10:00:00","board":"AI算力","max_board_heat_score":55}\n',
        encoding="utf-8",
    )

    trends = load_board_heat_trends(history, window_size=3, hot_score=60, cooling_threshold=5)

    assert trends["AI算力"]["board_heat_latest_score"] == 55
    assert trends["AI算力"]["board_heat_trend_score"] == -15
    assert trends["AI算力"]["board_heat_cooling_score"] == 7
    assert trends["AI算力"]["board_heat_persistence_score"] == 66.6667
    assert trends["AI算力"]["board_heat_observations"] == 3
    assert trends["AI算力"]["board_heat_state"] == "cooling"


def test_save_industry_map_round_trips_csv(tmp_path):
    path = tmp_path / "industry_map.csv"

    save_industry_map(
        {
            "000001": {
                "industry": "银行",
                "concepts": "低估值",
                "board_heat_score": 70,
                "board_heat_latest_score": 71,
                "board_heat_persistence_score": 80,
                "board_heat_cooling_score": 2,
                "board_heat_summary": "银行:+1.00%:rank=5",
                "board_heat_state": "persistent_hot",
            }
        },
        path,
    )
    mapping = load_industry_map(path)

    assert mapping["000001"]["industry"] == "银行"
    assert mapping["000001"]["concepts"] == "低估值"
    assert mapping["000001"]["board_heat_score"] == 70
    assert mapping["000001"]["board_heat_latest_score"] == 71
    assert mapping["000001"]["board_heat_persistence_score"] == 80
    assert mapping["000001"]["board_heat_cooling_score"] == 2
    assert mapping["000001"]["board_heat_state"] == "persistent_hot"


def test_fetch_akshare_board_map_uses_provider_cache(tmp_path, monkeypatch):
    calls = {"industry_list": 0, "industry_cons": 0, "concept_list": 0, "concept_cons": 0}

    class FakeAkshare:
        @staticmethod
        def stock_board_industry_name_em():
            calls["industry_list"] += 1
            return pd.DataFrame([{"板块名称": "银行", "涨跌幅": 1.2, "排名": 3}])

        @staticmethod
        def stock_board_industry_cons_em(symbol):
            calls["industry_cons"] += 1
            assert symbol == "银行"
            return pd.DataFrame([{"代码": "000001"}])

        @staticmethod
        def stock_board_concept_name_em():
            calls["concept_list"] += 1
            return pd.DataFrame([{"板块名称": "低估值", "涨跌幅": 0.4, "排名": 8}])

        @staticmethod
        def stock_board_concept_cons_em(symbol):
            calls["concept_cons"] += 1
            assert symbol == "低估值"
            return pd.DataFrame([{"代码": "000001"}])

    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)

    first_mapping, first_notes = fetch_akshare_board_map(
        max_boards=1,
        cache_dir=tmp_path,
        cache_ttl_seconds=3600,
    )
    assert first_mapping["000001"]["industry"] == "银行"
    assert first_mapping["000001"]["concepts"] == "低估值"
    assert calls == {"industry_list": 1, "industry_cons": 1, "concept_list": 1, "concept_cons": 1}
    assert any("provider cache saved" in note for note in first_notes)

    class FailingAkshare:
        @staticmethod
        def stock_board_industry_name_em():
            raise AssertionError("live provider should not be called on cache hit")

        stock_board_industry_cons_em = stock_board_industry_name_em
        stock_board_concept_name_em = stock_board_industry_name_em
        stock_board_concept_cons_em = stock_board_industry_name_em

    monkeypatch.setitem(sys.modules, "akshare", FailingAkshare)

    cached_mapping, cached_notes = fetch_akshare_board_map(
        max_boards=1,
        cache_dir=tmp_path,
        cache_ttl_seconds=3600,
    )

    assert cached_mapping == first_mapping
    assert any("provider cache hit" in note for note in cached_notes)


def test_fetch_akshare_board_map_refetches_after_provider_cache_ttl(tmp_path, monkeypatch):
    calls = {"industry_list": 0, "industry_cons": 0, "concept_list": 0, "concept_cons": 0}

    class FakeAkshare:
        @staticmethod
        def stock_board_industry_name_em():
            calls["industry_list"] += 1
            board = "银行" if calls["industry_list"] == 1 else "券商"
            return pd.DataFrame([{"板块名称": board, "涨跌幅": 1.0, "排名": 1}])

        @staticmethod
        def stock_board_industry_cons_em(symbol):
            calls["industry_cons"] += 1
            return pd.DataFrame([{"代码": "000001"}])

        @staticmethod
        def stock_board_concept_name_em():
            calls["concept_list"] += 1
            return pd.DataFrame([{"板块名称": "低估值", "涨跌幅": 0.4, "排名": 8}])

        @staticmethod
        def stock_board_concept_cons_em(symbol):
            calls["concept_cons"] += 1
            return pd.DataFrame([{"代码": "000001"}])

    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)

    first_mapping, _ = fetch_akshare_board_map(
        max_boards=1,
        cache_dir=tmp_path,
        cache_ttl_seconds=60,
    )
    assert first_mapping["000001"]["industry"] == "银行"

    cache_file = next(tmp_path.glob("*.json"))
    expired = cache_file.stat().st_mtime - 120
    os.utime(cache_file, (expired, expired))

    refreshed_mapping, refreshed_notes = fetch_akshare_board_map(
        max_boards=1,
        cache_dir=tmp_path,
        cache_ttl_seconds=60,
    )

    assert refreshed_mapping["000001"]["industry"] == "券商"
    assert calls["industry_list"] == 2
    assert any("provider cache expired" in note for note in refreshed_notes)


def test_fetch_akshare_board_map_limits_and_merges_parallel_results(monkeypatch):
    calls = {"industry": [], "concepts": []}

    class FakeAkshare:
        @staticmethod
        def stock_board_industry_name_em():
            return pd.DataFrame([
                {"板块名称": "银行", "涨跌幅": 1.2, "排名": 3},
                {"板块名称": "地产", "涨跌幅": 0.2, "排名": 12},
            ])

        @staticmethod
        def stock_board_industry_cons_em(symbol):
            calls["industry"].append(symbol)
            return pd.DataFrame([{"代码": "000001"}])

        @staticmethod
        def stock_board_concept_name_em():
            return pd.DataFrame([
                {"板块名称": "低估值", "涨跌幅": 0.4, "排名": 8},
                {"板块名称": "中特估", "涨跌幅": 2.0, "排名": 1},
            ])

        @staticmethod
        def stock_board_concept_cons_em(symbol):
            calls["concepts"].append(symbol)
            return pd.DataFrame([{"代码": "000001"}, {"代码": "000002"}])

    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)

    mapping, notes = fetch_akshare_board_map(max_boards=1, cache_dir=None)

    assert calls == {"industry": ["银行"], "concepts": ["低估值"]}
    assert mapping["000001"]["industry"] == "银行"
    assert mapping["000001"]["concepts"] == "低估值"
    assert mapping["000002"]["industry"] == ""
    assert mapping["000002"]["concepts"] == "低估值"
    assert any("akshare industry boards loaded: 1/1" in note for note in notes)
    assert any("akshare concepts boards loaded: 1/1" in note for note in notes)


def test_eastmoney_industry_backfill_is_bounded_by_the_snapshot_budget(tmp_path, monkeypatch):
    import time as time_module

    import alphasift.industry as industry

    def hang():
        time_module.sleep(5)
        return {"000001": {"industry": "银行"}}

    monkeypatch.setattr(industry, "_fetch_eastmoney_industry_rows", hang)
    monkeypatch.setenv("ALPHASIFT_SNAPSHOT_CALL_TIMEOUT_SEC", "0.3")

    started = time_module.monotonic()
    mapping, notes = industry.fetch_eastmoney_industry_map(cache_dir=tmp_path)

    assert time_module.monotonic() - started < 2
    assert mapping == {}
    assert any("eastmoney" in note for note in notes)
