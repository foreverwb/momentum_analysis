import os
import json
import pytest

os.environ["CLI_NO_VENV"] = "1"

from app import cli


def test_parse_mc_coverage_supports_requested_formats() -> None:
    assert cli.parse_mc_coverage("t-10") == ("top", 10, "top10")
    assert cli.parse_mc_coverage("85") == ("weight", 85, "weight85")


def test_parse_etf_symbols_dedup_and_normalize() -> None:
    assert cli.parse_etf_symbols("XLK, XLC,XLK, xlv") == ["XLK", "XLC", "XLV"]


def test_filter_mc_source_fields_keeps_required_fields_only() -> None:
    rows = [
        {
            "symbol": "aapl",
            "RelVolTo90D": "1.2",
            "CallVolume": "100",
            "PutVolume": "50",
            "Earnings": "2026-02-01",
            "PutPct": "33%",
            "IV30": "25",
            "IVR": "40%",
            "HV20": "22",
            "PriceChgPct": "1.1%",
            "IV30ChgPct": "-2.0%",
            "RelNotionalTo90D": "0.5",
        }
    ]
    filtered = cli.filter_mc_source_fields(rows)
    assert len(filtered) == 1
    item = filtered[0]
    assert item["symbol"] == "AAPL"
    assert "RelNotionalTo90D" not in item
    assert set(item.keys()) == set(cli.MC_IMPORT_FIELDS)


def test_select_rows_by_expected_symbols_supports_share_class_alias() -> None:
    rows = [
        {"symbol": "BRK-B", "IV30": "19"},
        {"symbol": "JPM", "IV30": "24"},
    ]
    selected, missing, duplicates = cli._select_rows_by_expected_symbols(rows, ["BRK.B", "JPM"])
    assert [row["symbol"] for row in selected] == ["BRK.B", "JPM"]
    assert missing == []
    assert duplicates == []


def test_load_finviz_source_rows_supports_json_data_payload(tmp_path) -> None:
    file_path = tmp_path / "finviz.json"
    file_path.write_text(
        json.dumps({"data": [{"Ticker": "AAPL", "Price": "185.5"}]}),
        encoding="utf-8",
    )

    rows, source_format = cli.load_finviz_source_rows(str(file_path))

    assert source_format == "json"
    assert rows == [{"Ticker": "AAPL", "Price": "185.5"}]


def test_load_finviz_source_rows_supports_csv(tmp_path) -> None:
    file_path = tmp_path / "finviz.csv"
    file_path.write_text("Ticker,Price\nAAPL,185.5\n", encoding="utf-8")

    rows, source_format = cli.load_finviz_source_rows(str(file_path))

    assert source_format == "csv"
    assert rows == [{"Ticker": "AAPL", "Price": "185.5"}]


def test_build_parser_accepts_finviz_without_coverage() -> None:
    args = cli.parse_cli_args(["finviz", "-f", "finviz.csv"])

    assert args.command == "finviz"
    assert args.resource == "etfs"
    assert args.file == "finviz.csv"
    assert args.date is None
    assert args.coverage is None
    assert args.etfs is None


@pytest.mark.parametrize("command", ["uploads", "update"])
def test_parse_cli_args_defaults_holdings_date_to_today(monkeypatch, command: str) -> None:
    monkeypatch.setattr(cli, "_today_iso_date", lambda: "2026-03-14")

    args = cli.parse_cli_args([command, "-t", "sector", "-a", "XLK", "holdings.xlsx"])

    assert args.command == command
    assert args.date == "2026-03-14"
    assert args.file == "holdings.xlsx"


def test_build_parser_accepts_finviz_with_mc_style_coverage() -> None:
    args = cli.parse_cli_args(["finviz", "-s", "XLK,XLC", "-w", "85", "-f", "finviz.csv"])

    assert args.command == "finviz"
    assert args.resource == "etfs"
    assert args.etfs == "XLK,XLC"
    assert args.coverage == "85"
    assert args.file == "finviz.csv"


def test_build_parser_accepts_provider_etfs_subcommand() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["finviz", "etfs", "-f", "finviz.csv"])

    assert args.command == "finviz"
    assert args.resource == "etfs"
    assert args.file == "finviz.csv"


def test_parse_cli_args_accepts_mc_etfs_subcommand() -> None:
    args = cli.parse_cli_args(["mc", "etfs", "-s", "XLK,XLC", "-w", "85", "-f", "mc.json"])

    assert args.command == "mc"
    assert args.resource == "etfs"
    assert args.etfs == "XLK,XLC"
    assert args.coverage == "85"
    assert args.file == "mc.json"


def test_parse_cli_args_accepts_mc_without_coverage() -> None:
    args = cli.parse_cli_args(["mc", "etfs", "-f", "mc.json"])

    assert args.command == "mc"
    assert args.resource == "etfs"
    assert args.file == "mc.json"
    assert args.etfs is None
    assert args.coverage is None


def test_normalize_cli_argv_inserts_default_etfs_subcommand_for_legacy_provider_commands() -> None:
    assert cli.normalize_cli_argv(["finviz", "-f", "finviz.csv"]) == ["finviz", "etfs", "-f", "finviz.csv"]
    assert cli.normalize_cli_argv(["mc", "-s", "XLK", "-w", "85", "-f", "mc.json"]) == [
        "mc",
        "etfs",
        "-s",
        "XLK",
        "-w",
        "85",
        "-f",
        "mc.json",
    ]
