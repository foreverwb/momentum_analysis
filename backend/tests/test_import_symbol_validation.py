from fastapi import HTTPException
import pytest

from app.api.import_data import _assert_import_symbols_match, _parse_coverage_selection


def test_parse_coverage_selection_supports_top_weight_and_all() -> None:
    assert _parse_coverage_selection("top10") == ("top", 10)
    assert _parse_coverage_selection("weight85") == ("weight", 85)
    assert _parse_coverage_selection("all") == ("all", 0)


def test_assert_import_symbols_match_accepts_exact_match() -> None:
    expected = ["NVDA", "AAPL", "MSFT"]
    imported = ["NVDA", "AAPL", "MSFT"]
    result, alias_mappings = _assert_import_symbols_match(
        source_label="Finviz",
        etf_symbol="XLK",
        coverage="top3",
        expected_symbols=expected,
        imported_symbols=imported,
        required_field_hint="Ticker",
    )
    assert result == imported
    assert alias_mappings == []


def test_assert_import_symbols_match_accepts_share_class_alias() -> None:
    expected = ["BRK.B", "JPM"]
    imported = ["BRK-B", "JPM"]
    result, alias_mappings = _assert_import_symbols_match(
        source_label="Finviz",
        etf_symbol="XLF",
        coverage="weight85",
        expected_symbols=expected,
        imported_symbols=imported,
        required_field_hint="Ticker",
    )
    assert result == ["BRK.B", "JPM"]
    assert alias_mappings == ["BRK-B -> BRK.B"]


def test_assert_import_symbols_match_rejects_duplicate_symbols() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _assert_import_symbols_match(
            source_label="Finviz",
            etf_symbol="XLK",
            coverage="top3",
            expected_symbols=["NVDA", "AAPL", "MSFT"],
            imported_symbols=["NVDA", "AAPL", "AAPL"],
            required_field_hint="Ticker",
        )
    assert exc_info.value.status_code == 400
    assert "重复标的" in str(exc_info.value.detail)


def test_assert_import_symbols_match_rejects_missing_and_extra() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _assert_import_symbols_match(
            source_label="MarketChameleon",
            etf_symbol="XLK",
            coverage="top3",
            expected_symbols=["NVDA", "AAPL", "MSFT"],
            imported_symbols=["NVDA", "AAPL", "TSLA"],
            required_field_hint="symbol",
        )
    assert exc_info.value.status_code == 400
    assert "缺少" in str(exc_info.value.detail)
    assert "多出" in str(exc_info.value.detail)
