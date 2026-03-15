import os
import json
import pytest

os.environ["CLI_NO_VENV"] = "1"

from app import cli


@pytest.fixture(autouse=True)
def _isolated_cli_cfg(tmp_path, monkeypatch) -> None:
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "\n".join(
            [
                "cli:",
                "  downloads_dir: './downloads'",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MOMENTUM_CFG_PATH", str(cfg_file))


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


def test_parse_cli_args_accepts_short_actualiser_entrypoint() -> None:
    args = cli.parse_cli_args(["status", "12"], prog="Actualiser")

    assert args.command == "Actualiser"
    assert args.resource == "status"
    assert args.job_id == 12


def test_parse_cli_args_accepts_legacy_refresh_entrypoint() -> None:
    args = cli.parse_cli_args(["status", "12"], prog="refresh")

    assert args.command == "Actualiser"
    assert args.resource == "status"
    assert args.job_id == 12


def test_parse_cli_args_accepts_short_finviz_entrypoint() -> None:
    args = cli.parse_cli_args(["-f", "finviz.csv"], prog="finviz")

    assert args.command == "finviz"
    assert args.resource == "etfs"
    assert args.file == "finviz.csv"


def test_parse_cli_args_resolves_prefixed_download_file_from_cfg(tmp_path, monkeypatch) -> None:
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir(exist_ok=True)
    expected_file = downloads_dir / "Finviz_export.csv"
    expected_file.write_text("Ticker,Price\nAAPL,185.5\n", encoding="utf-8")

    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "\n".join(
            [
                "cli:",
                f"  downloads_dir: '{downloads_dir}'",
                "  finviz_file_prefix: 'Finviz_'",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MOMENTUM_CFG_PATH", str(cfg_file))

    args = cli.parse_cli_args(["finviz", "-f", "export.csv"])

    assert args.file == str(expected_file.resolve())


def test_parse_cli_args_accepts_uploads_file_option_and_download_prefix(tmp_path, monkeypatch) -> None:
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir(exist_ok=True)
    expected_file = downloads_dir / "Holdings_xlk.xlsx"
    expected_file.write_text("placeholder", encoding="utf-8")

    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "\n".join(
            [
                "cli:",
                f"  downloads_dir: '{downloads_dir}'",
                "  holdings_file_prefix: 'Holdings_'",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MOMENTUM_CFG_PATH", str(cfg_file))
    monkeypatch.setattr(cli, "_today_iso_date", lambda: "2026-03-14")

    args = cli.parse_cli_args(["uploads", "-t", "sector", "-a", "XLK", "-f", "xlk.xlsx"])

    assert args.command == "uploads"
    assert args.file == str(expected_file.resolve())


def test_parse_cli_args_rejects_uploads_when_both_file_forms_are_provided() -> None:
    with pytest.raises(SystemExit):
        cli.parse_cli_args(["uploads", "-t", "sector", "-a", "XLK", "-f", "a.xlsx", "b.xlsx"])


def test_parse_cli_args_accepts_refresh_etfs() -> None:
    args = cli.parse_cli_args(["Actualiser", "etfs", "-s", "XLK,XLF"])

    assert args.command == "Actualiser"
    assert args.resource == "etfs"
    assert args.symbols == "XLK,XLF"
    assert args.source == "all"
    assert args.api_base == cli.DEFAULT_API_BASE_URL


def test_parse_cli_args_accepts_refresh_etfs_without_symbols() -> None:
    args = cli.parse_cli_args(["Actualiser", "etfs", "--source", "futu"])

    assert args.command == "Actualiser"
    assert args.resource == "etfs"
    assert args.symbols is None
    assert args.source == "futu"


def test_parse_cli_args_accepts_refresh_holdings_defaults_coverage() -> None:
    args = cli.parse_cli_args(["Actualiser", "holdings", "-s", "XLK,SOXX"])

    assert args.command == "Actualiser"
    assert args.resource == "holdings"
    assert args.symbols == "XLK,SOXX"
    assert args.coverage == "t-20"
    assert args.source == "all"


def test_parse_cli_args_accepts_refresh_source_choices() -> None:
    etf_args = cli.parse_cli_args(["Actualiser", "etfs", "-s", "XLK", "--source", "ibkr"])
    holdings_args = cli.parse_cli_args(["Actualiser", "holdings", "-s", "SOXX", "--source", "futu"])

    assert etf_args.source == "ibkr"
    assert holdings_args.source == "futu"


def test_cmd_refresh_etfs_posts_selected_source(monkeypatch, capsys) -> None:
    captured = {"calls": []}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["calls"].append((method, url, payload, timeout))
        if method == "GET":
            return [
                {"symbol": "XLK", "holdingsCount": 10},
                {"symbol": "XLF", "holdingsCount": 0},
            ]
        return {
            "job": {
                "id": 21,
                "status": "pending",
                "queue_position": 1,
                "message": "任务已进入队列",
            }
        }

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "etfs",
            "-s",
            "XLK,XLF",
            "--source",
            "ibkr",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["calls"][0] == ("GET", "http://127.0.0.1:8000/api/etfs", None, 10)
    assert captured["calls"][1][0] == "POST"
    assert captured["calls"][1][1] == "http://127.0.0.1:8000/api/refresh-jobs/etfs"
    assert captured["calls"][1][2] == {
        "symbols": ["XLK"],
        "source": "cli",
        "refresh_source": "ibkr",
    }
    assert captured["calls"][1][3] == 10
    stdout = capsys.readouterr().out
    assert "已跳过无 holdings 数据的 ETF: XLF" in stdout
    assert "Job ID: 21" in stdout


def test_cmd_refresh_etfs_keeps_unknown_symbols_when_filtering_holdings(monkeypatch, capsys) -> None:
    captured = {"calls": []}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["calls"].append((method, url, payload, timeout))
        if method == "GET":
            return [
                {"symbol": "XLK", "holdingsCount": 10},
                {"symbol": "XLF", "holdingsCount": 0},
            ]
        return {
            "job": {
                "id": 31,
                "status": "pending",
                "queue_position": 1,
                "message": "任务已进入队列",
            }
        }

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "etfs",
            "-s",
            "XLK,XLF,FAKE",
            "--source",
            "futu",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["calls"][1][2] == {
        "symbols": ["XLK", "FAKE"],
        "source": "cli",
        "refresh_source": "futu",
    }
    stdout = capsys.readouterr().out
    assert "已跳过无 holdings 数据的 ETF: XLF" in stdout
    assert "Job ID: 31" in stdout


def test_cmd_refresh_etfs_skips_submit_when_no_symbols_have_holdings(monkeypatch, capsys) -> None:
    captured = {"calls": []}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["calls"].append((method, url, payload, timeout))
        return [
            {"symbol": "XLF", "holdingsCount": 0},
        ]

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "etfs",
            "-s",
            "XLF",
            "--source",
            "ibkr",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["calls"] == [
        ("GET", "http://127.0.0.1:8000/api/etfs", None, 10),
    ]
    stdout = capsys.readouterr().out
    assert "已跳过无 holdings 数据的 ETF: XLF" in stdout
    assert "没有具备 holdings 数据的 ETF，跳过提交任务" in stdout


def test_cmd_refresh_etfs_fetches_all_symbols_when_omitted(monkeypatch, capsys) -> None:
    captured = {"calls": []}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["calls"].append((method, url, payload, timeout))
        if method == "GET":
            return [
                {"symbol": "XLK", "holdingsCount": 8},
                {"symbol": "XLF", "holdingsCount": 0},
                {"symbol": "SOXX", "holdingsCount": 12},
            ]
        return {
            "job": {
                "id": 22,
                "status": "pending",
                "queue_position": 1,
                "message": "任务已进入队列",
            }
        }

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "etfs",
            "--source",
            "futu",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["calls"][0] == ("GET", "http://127.0.0.1:8000/api/etfs", None, 10)
    assert captured["calls"][1][0] == "POST"
    assert captured["calls"][1][1] == "http://127.0.0.1:8000/api/refresh-jobs/etfs"
    assert captured["calls"][1][2] == {
        "symbols": ["XLK", "SOXX"],
        "source": "cli",
        "refresh_source": "futu",
    }
    stdout = capsys.readouterr().out
    assert "未提供 ETF 列表，已自动加载有 holdings 数据的 ETF: 2 个" in stdout
    assert "已跳过无 holdings 数据的 ETF: XLF" in stdout
    assert "Job ID: 22" in stdout


def test_cmd_refresh_etfs_fetches_all_symbols_for_all_source(monkeypatch, capsys) -> None:
    captured = {"calls": []}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["calls"].append((method, url, payload, timeout))
        if method == "GET":
            return [
                {"symbol": "XLK", "holdingsCount": 8},
                {"symbol": "XLF", "holdingsCount": 0},
                {"symbol": "SOXX", "holdingsCount": 12},
            ]
        return {
            "job": {
                "id": 32,
                "status": "pending",
                "queue_position": 1,
                "message": "任务已进入队列",
            }
        }

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "etfs",
            "--source",
            "all",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["calls"][1][2] == {
        "symbols": ["XLK", "XLF", "SOXX"],
        "source": "cli",
        "refresh_source": "all",
    }
    stdout = capsys.readouterr().out
    assert "未提供 ETF 列表，已自动加载全部 ETF: 3 个" in stdout
    assert "已跳过无 holdings 数据的 ETF" not in stdout
    assert "Job ID: 32" in stdout


def test_cmd_refresh_holdings_posts_background_job(monkeypatch, capsys) -> None:
    captured = {}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {
            "job": {
                "id": 12,
                "status": "pending",
                "queue_position": 1,
                "message": "任务已进入队列",
            }
        }

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)
    monkeypatch.setattr(cli, "_poll_refresh_job_until_terminal", lambda *args, **kwargs: None)

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "holdings",
            "-s",
            "XLK,SOXX",
            "-w",
            "all",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:8000/api/refresh-jobs/holdings"
    assert captured["payload"] == {
        "items": [
            {
                "symbol": "XLK",
                "coverage_type": "all",
                "coverage_value": 0,
                "related_etf_symbols": [],
            },
            {
                "symbol": "SOXX",
                "coverage_type": "all",
                "coverage_value": 0,
                "related_etf_symbols": [],
            },
        ],
        "source": "cli",
        "refresh_source": "all",
        "exclude_symbols": [],
    }
    assert captured["timeout"] == 10

    stdout = capsys.readouterr().out
    assert "Job ID: 12" in stdout
    assert "查询状态" in stdout


def test_cmd_refresh_holdings_posts_exclude_symbols(monkeypatch, capsys) -> None:
    captured = {}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {
            "job": {
                "id": 19,
                "status": "pending",
                "queue_position": 1,
                "message": "任务已进入队列",
            }
        }

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)
    monkeypatch.setattr(cli, "_poll_refresh_job_until_terminal", lambda *args, **kwargs: None)

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "holdings",
            "-s",
            "XTL",
            "--source",
            "futu",
            "--exclude-symbols",
            "UI,BRK.B",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["payload"] == {
        "items": [
            {
                "symbol": "XTL",
                "coverage_type": "top",
                "coverage_value": 20,
                "related_etf_symbols": [],
            },
        ],
        "source": "cli",
        "refresh_source": "futu",
        "exclude_symbols": ["UI", "BRK.B"],
    }
    stdout = capsys.readouterr().out
    assert "Job ID: 19" in stdout


def test_cmd_refresh_holdings_prints_immediate_failure_details(monkeypatch, capsys) -> None:
    captured = {}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {
            "job": {
                "id": 18,
                "status": "pending",
                "queue_position": 1,
                "message": "任务已进入队列",
            }
        }

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)
    monkeypatch.setattr(
        cli,
        "_poll_refresh_job_until_terminal",
        lambda *args, **kwargs: {
            "id": 18,
            "job_type": "holdings",
            "status": "completed",
            "progress_completed": 3,
            "progress_total": 3,
            "progress_failed": 3,
            "message": "任务完成，3 项全部失败",
            "result": {
                "summary_status": "failed",
                "items": [
                    {
                        "symbol": "SOXX",
                        "coverage": "weight75",
                        "status": "error",
                        "message": "缺少 MarketChameleon 数据: ASML, TSM",
                    }
                ],
            },
        },
    )

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "holdings",
            "-s",
            "SOXX,SMH,IGV",
            "-w",
            "75",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:8000/api/refresh-jobs/holdings"
    stdout = capsys.readouterr().out
    assert "后台任务快速返回错误:" in stdout
    assert "消息: 任务完成，3 项全部失败" in stdout
    assert "失败明细:" in stdout
    assert "- SOXX (weight75): 缺少 MarketChameleon 数据: ASML, TSM" in stdout


def test_poll_refresh_job_until_terminal_returns_running_job_when_failures_detected(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        calls["count"] += 1
        return {
            "id": 9,
            "job_type": "holdings",
            "status": "running",
            "progress_completed": 1,
            "progress_total": 3,
            "progress_failed": 1,
            "message": "已完成 1/3",
            "result": {
                "summary_status": "partial_success",
                "items": [
                    {
                        "symbol": "SOXX",
                        "coverage": "weight75",
                        "status": "error",
                        "message": "缺少 MarketChameleon 数据: ASML, TSM",
                    }
                ],
            },
        }

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)

    job = cli._poll_refresh_job_until_terminal(
        9,
        api_base="http://127.0.0.1:8000",
        timeout=10,
        max_wait_seconds=0.01,
        poll_interval_seconds=0.0,
    )

    assert calls["count"] >= 1
    assert job is not None
    assert job["status"] == "running"
    assert job["progress_failed"] == 1


def test_cmd_refresh_list_builds_query_params(monkeypatch, capsys) -> None:
    captured = {}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["method"] = method
        captured["url"] = url
        return {"items": []}

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "list",
            "--status",
            "running",
            "--limit",
            "5",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["method"] == "GET"
    assert captured["url"] == "http://127.0.0.1:8000/api/refresh-jobs?limit=5&status=running"
    assert "暂无刷新任务" in capsys.readouterr().out


def test_cmd_refresh_status_prints_failed_item_details(monkeypatch, capsys) -> None:
    captured = {}

    def fake_http_json_request(method: str, url: str, payload=None, timeout: int = 10):
        captured["method"] = method
        captured["url"] = url
        return {
            "id": 7,
            "job_type": "holdings",
            "status": "completed",
            "progress_completed": 3,
            "progress_total": 3,
            "progress_failed": 3,
            "message": "任务完成，3 项全部失败",
            "result": {
                "summary_status": "failed",
                "items": [
                    {
                        "symbol": "SOXX",
                        "coverage": "weight75",
                        "status": "error",
                        "message": "缺少 MarketChameleon 数据: ASML, TSM",
                    },
                    {
                        "symbol": "SMH",
                        "coverage": "weight75",
                        "status": "error",
                        "message": "缺少 MarketChameleon 数据: ASML",
                    },
                ],
            },
        }

    monkeypatch.setattr(cli, "_http_json_request", fake_http_json_request)

    args = cli.parse_cli_args(
        [
            "Actualiser",
            "status",
            "7",
            "--api-base",
            "http://127.0.0.1:8000",
        ]
    )
    args.func(args)

    assert captured["method"] == "GET"
    assert captured["url"] == "http://127.0.0.1:8000/api/refresh-jobs/7"
    stdout = capsys.readouterr().out
    assert "Job ID: 7" in stdout
    assert "失败明细:" in stdout
    assert "- SOXX (weight75): 缺少 MarketChameleon 数据: ASML, TSM" in stdout
    assert "- SMH (weight75): 缺少 MarketChameleon 数据: ASML" in stdout
