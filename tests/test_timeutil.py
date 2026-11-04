from datetime import timezone

from alphasift.evaluate import entry_cutoff_date
from alphasift.models import EvaluationResult, ScreenResult
from alphasift.run_history import _run_sort_key
from alphasift.timeutil import MIN_TIMESTAMP, now_iso, parse_timestamp


def test_new_timestamps_carry_utc_offset():
    assert parse_timestamp(now_iso()).utcoffset() is not None
    assert parse_timestamp(ScreenResult(strategy="dual_low", market="cn").created_at).utcoffset() is not None
    evaluation = EvaluationResult(run_id="r", strategy="dual_low", market="cn", created_at="")
    assert parse_timestamp(evaluation.evaluated_at).utcoffset() is not None


def test_parse_timestamp_reads_naive_as_local_and_rejects_garbage():
    parsed = parse_timestamp("2026-04-01T10:00:00")
    assert parsed is not None and parsed.tzinfo is not None
    assert parsed.replace(tzinfo=None).isoformat() == "2026-04-01T10:00:00"
    assert parse_timestamp("") is None
    assert parse_timestamp(None) is None
    assert parse_timestamp("not a date") is None


def test_entry_cutoff_uses_the_saved_offset_not_the_evaluating_machine():
    # 2026-04-01 22:00 in New York is 04-02 10:00 in Tokyo (after the 09:00 open).
    assert str(entry_cutoff_date("2026-04-01T22:00:00-04:00", "jp")) == "2026-04-02"
    # The same instant written in UTC gives the same session.
    assert str(entry_cutoff_date("2026-04-02T02:00:00+00:00", "jp")) == "2026-04-02"
    # 08:30 Tokyo is before the open: the previous session is the entry.
    assert str(entry_cutoff_date("2026-04-02T08:30:00+09:00", "jp")) == "2026-04-01"


def test_run_sort_handles_old_naive_and_new_aware_timestamps_together():
    items = [
        {"run_id": "new", "created_at": "2026-04-02T10:00:00+00:00"},
        {"run_id": "old", "created_at": "2020-01-01T10:00:00"},
        {"run_id": "bad", "created_at": ""},
    ]
    ordered = sorted(items, key=_run_sort_key)
    assert [item["run_id"] for item in ordered] == ["bad", "old", "new"]
    assert MIN_TIMESTAMP.tzinfo is timezone.utc


def test_parse_timestamp_accepts_z_suffix():
    parsed = parse_timestamp("2026-04-02T02:00:00Z")
    assert parsed is not None and parsed.utcoffset().total_seconds() == 0
    assert str(entry_cutoff_date("2026-04-02T02:00:00Z", "jp")) == "2026-04-02"


def test_history_summaries_order_strategies_by_real_time_not_string(tmp_path):
    from alphasift.run_history import build_strategy_run_summary
    from alphasift.store import save_screen_result

    # 12:00+08:00 is 04:00 UTC: an hour before 05:00+00:00, though it sorts later as text.
    for strategy, created in (("dual_low", "2026-11-04T12:00:00+08:00"), ("global_value", "2026-11-04T05:00:00+00:00")):
        save_screen_result(
            ScreenResult(strategy=strategy, market="cn", run_id=strategy, created_at=created), data_dir=tmp_path
        )

    payload = build_strategy_run_summary(data_dir=tmp_path)

    assert [item["strategy"] for item in payload["strategies"]] == ["global_value", "dual_low"]
