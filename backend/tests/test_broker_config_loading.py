from __future__ import annotations

from pathlib import Path

from app.core.broker_config import load_broker_config


def test_load_broker_config_from_custom_path(tmp_path: Path) -> None:
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "\n".join(
            [
                "ibkr:",
                "  host: '10.0.0.3'",
                "  port: 4999",
                "  client_id: 9",
                "  timeout: 45",
                "futu:",
                "  host: '10.0.0.8'",
                "  port: 21111",
                "  market: 'HK'",
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_broker_config(str(cfg_file))

    assert cfg.loaded_from_file is True
    assert cfg.config_path == str(cfg_file)
    assert cfg.ibkr.host == "10.0.0.3"
    assert cfg.ibkr.port == 4999
    assert cfg.ibkr.client_id == 9
    assert cfg.ibkr.timeout == 45
    assert cfg.futu.host == "10.0.0.8"
    assert cfg.futu.port == 21111
    assert cfg.futu.market == "HK"


def test_load_broker_config_falls_back_to_defaults_on_invalid_values(tmp_path: Path) -> None:
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "\n".join(
            [
                "ibkr:",
                "  host: ''",
                "  port: -1",
                "  client_id: 0",
                "  timeout: wrong",
                "futu:",
                "  host: null",
                "  port: -100",
                "  market: ''",
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_broker_config(str(cfg_file))

    assert cfg.ibkr.host == "127.0.0.1"
    assert cfg.ibkr.port == 4002
    assert cfg.ibkr.client_id == 3
    assert cfg.ibkr.timeout == 30
    assert cfg.futu.host == "127.0.0.1"
    assert cfg.futu.port == 11111
    assert cfg.futu.market == "US"
