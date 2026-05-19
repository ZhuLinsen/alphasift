# -*- coding: utf-8 -*-
"""Tests for filter_a_shares_only in snapshot module."""

import math

import pandas as pd
import pytest

from alphasift.snapshot import filter_a_shares_only


def _make_df(codes: list) -> pd.DataFrame:
    """Build a minimal DataFrame with a 'code' column."""
    return pd.DataFrame({"code": codes, "price": [1.0] * len(codes)})


class TestFilterASharesOnly:
    """Validate A-share code filtering logic."""

    # ---- codes that SHOULD be kept ----

    @pytest.mark.parametrize(
        "code",
        [
            "600519",  # 贵州茅台 — 上交所主板
            "601398",  # 工商银行 — 上交所主板
            "603259",  # 药明康德 — 上交所主板
            "605358",  # 上交所主板 (605xxx)
            "688981",  # 中芯国际 — 科创板
            "689009",  # 科创板
            "000001",  # 平安银行 — 深交所主板
            "001872",  # 深交所主板 (001xxx)
            "002594",  # 比亚迪 — 深交所主板 (002xxx)
            "003816",  # 深交所主板 (003xxx)
            "300750",  # 宁德时代 — 创业板
            "301099",  # 创业板 (301xxx)
            "430047",  # 北交所
            "830799",  # 北交所
            "873305",  # 北交所
        ],
    )
    def test_keeps_valid_a_share(self, code: str):
        df = _make_df([code])
        result = filter_a_shares_only(df)
        assert len(result) == 1, f"Expected {code} to be kept"

    # ---- codes that SHOULD be excluded ----

    @pytest.mark.parametrize(
        "code",
        [
            # ETFs
            "510300",  # 沪深300ETF
            "510050",  # 上证50ETF
            "512880",  # 证券ETF
            "515790",  # 光伏ETF
            "516160",  # 新能源ETF
            "518880",  # 黄金ETF
            "560080",  # 科创芯片ETF
            "159915",  # 创业板ETF
            # 债券 / 可转债
            "110059",  # 上交所可转债
            "113050",  # 上交所可转债
            "123136",  # 深交所可转债
            "127025",  # 深交所可转债
            "128129",  # 深交所可转债
            # 封闭式基金 / LOF
            "500001",  # 基金金泰
            "501001",  # 基金
            "160105",  # LOF
            # B 股
            "900901",  # 上交所B股
        ],
    )
    def test_excludes_non_stock(self, code: str):
        df = _make_df([code])
        result = filter_a_shares_only(df)
        assert len(result) == 0, f"Expected {code} to be excluded"

    # ---- edge cases ----

    def test_empty_df(self):
        df = pd.DataFrame({"code": [], "price": []})
        result = filter_a_shares_only(df)
        assert result.empty

    def test_missing_code_column(self):
        df = pd.DataFrame({"name": ["test"], "price": [1.0]})
        result = filter_a_shares_only(df)
        assert len(result) == 1  # returns unchanged

    @pytest.mark.parametrize("bad", [None, float("nan"), "", "nan", "None"])
    def test_invalid_codes_excluded(self, bad):
        df = _make_df([bad])
        result = filter_a_shares_only(df)
        assert len(result) == 0

    def test_int_codes_padded(self):
        """Integer codes like 1 should be padded to 000001 → valid A-share."""
        df = _make_df([1, 600519])
        result = filter_a_shares_only(df)
        assert len(result) == 2

    def test_mixed_valid_and_invalid(self):
        df = _make_df(["600519", "510300", "000001", "110059", "300750", "900901"])
        result = filter_a_shares_only(df)
        assert list(result["code"]) == ["600519", "000001", "300750"]

    def test_leading_zeros_preserved(self):
        """Codes like '000001' should match even if stored as string."""
        df = _make_df(["000001"])
        result = filter_a_shares_only(df)
        assert len(result) == 1
        assert result.iloc[0]["code"] == "000001"

    def test_short_code_zero_filled(self):
        """A 3-digit int 1 → '000001' → valid."""
        df = _make_df([1])
        result = filter_a_shares_only(df)
        assert len(result) == 1

    def test_seven_digit_code_excluded(self):
        """7-digit codes are not valid A-share codes."""
        df = _make_df(["6005190"])
        result = filter_a_shares_only(df)
        assert len(result) == 0
