"""
Broker connection config loading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)

_CONFIG_ENV_VAR = "MOMENTUM_CFG_PATH"
_DEFAULT_CLI_DOWNLOADS_DIR = str(Path.home() / "Downloads")


@dataclass(frozen=True)
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 3
    timeout: int = 30


@dataclass(frozen=True)
class FutuConfig:
    host: str = "127.0.0.1"
    port: int = 11111
    market: str = "US"


@dataclass(frozen=True)
class RefreshConfig:
    etf_cooldown_minutes: int = 15
    holdings_cooldown_minutes: int = 60
    serial_gap_seconds: int = 2


@dataclass(frozen=True)
class CLIConfig:
    downloads_dir: str = _DEFAULT_CLI_DOWNLOADS_DIR
    file_prefix: str = ""
    finviz_file_prefix: str = ""
    mc_file_prefix: str = ""
    holdings_file_prefix: str = ""


@dataclass(frozen=True)
class BrokerConfig:
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    futu: FutuConfig = field(default_factory=FutuConfig)
    refresh: RefreshConfig = field(default_factory=RefreshConfig)
    cli: CLIConfig = field(default_factory=CLIConfig)
    config_path: Optional[str] = None
    loaded_from_file: bool = False


def _project_root() -> Path:
    # backend/app/core/broker_config.py -> project root
    return Path(__file__).resolve().parents[3]


def _resolve_config_path(config_path: Optional[str] = None) -> Optional[Path]:
    candidates = []

    if config_path:
        candidates.append(Path(config_path).expanduser())

    env_path = os.getenv(_CONFIG_ENV_VAR)
    if env_path:
        candidates.append(Path(env_path).expanduser())

    candidates.append(_project_root() / "cfg.yaml")
    candidates.append(Path.cwd() / "cfg.yaml")

    for candidate in candidates:
        resolved = candidate if candidate.is_absolute() else (_project_root() / candidate)
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """
    Best-effort fallback parser for simple key/value YAML.
    Supports exactly the subset used in cfg.yaml.
    """
    result: Dict[str, Any] = {}
    section: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if line.lstrip() == line:
            # top-level key
            if line.endswith(":"):
                section = line[:-1].strip()
                if section:
                    result.setdefault(section, {})
                continue
            key, sep, value = line.partition(":")
            if not sep:
                continue
            result[key.strip()] = _parse_scalar(value.strip())
            section = None
            continue

        if section is None:
            continue
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        sec = result.setdefault(section, {})
        if isinstance(sec, dict):
            sec[key.strip()] = _parse_scalar(value.strip())
    return result


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]

    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False

    try:
        return int(value)
    except Exception:
        return value


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
        logger.warning("cfg_yaml_not_mapping", path=str(path))
        return {}
    except Exception as exc:
        logger.warning("cfg_yaml_parse_failed", path=str(path), error=str(exc))
        try:
            return _parse_simple_yaml(path.read_text(encoding="utf-8"))
        except Exception as fallback_exc:
            logger.warning("cfg_yaml_fallback_parse_failed", path=str(path), error=str(fallback_exc))
            return {}


def _to_str(value: Any, default: str) -> str:
    if isinstance(value, str):
        clean = value.strip()
        return clean if clean else default
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _to_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        if parsed <= 0:
            return default
        return parsed
    except Exception:
        return default


def load_broker_config(config_path: Optional[str] = None) -> BrokerConfig:
    path = _resolve_config_path(config_path=config_path)
    if path is None:
        logger.info("broker_cfg_not_found_use_defaults")
        return BrokerConfig()

    payload = _load_yaml(path)
    ibkr_payload = payload.get("ibkr", {}) if isinstance(payload.get("ibkr"), dict) else {}
    futu_payload = payload.get("futu", {}) if isinstance(payload.get("futu"), dict) else {}
    refresh_payload = payload.get("refresh", {}) if isinstance(payload.get("refresh"), dict) else {}
    cli_payload = payload.get("cli", {}) if isinstance(payload.get("cli"), dict) else {}

    config = BrokerConfig(
        ibkr=IBKRConfig(
            host=_to_str(ibkr_payload.get("host"), IBKRConfig.host),
            port=_to_int(ibkr_payload.get("port"), IBKRConfig.port),
            client_id=_to_int(ibkr_payload.get("client_id"), IBKRConfig.client_id),
            timeout=_to_int(ibkr_payload.get("timeout"), IBKRConfig.timeout),
        ),
        futu=FutuConfig(
            host=_to_str(futu_payload.get("host"), FutuConfig.host),
            port=_to_int(futu_payload.get("port"), FutuConfig.port),
            market=_to_str(futu_payload.get("market"), FutuConfig.market),
        ),
        refresh=RefreshConfig(
            etf_cooldown_minutes=_to_int(
                refresh_payload.get("etf_cooldown_minutes"),
                RefreshConfig.etf_cooldown_minutes,
            ),
            holdings_cooldown_minutes=_to_int(
                refresh_payload.get("holdings_cooldown_minutes"),
                RefreshConfig.holdings_cooldown_minutes,
            ),
            serial_gap_seconds=_to_int(
                refresh_payload.get("serial_gap_seconds"),
                RefreshConfig.serial_gap_seconds,
            ),
        ),
        cli=CLIConfig(
            downloads_dir=_to_str(cli_payload.get("downloads_dir"), _DEFAULT_CLI_DOWNLOADS_DIR),
            file_prefix=_to_str(cli_payload.get("file_prefix"), CLIConfig.file_prefix),
            finviz_file_prefix=_to_str(
                cli_payload.get("finviz_file_prefix"),
                CLIConfig.finviz_file_prefix,
            ),
            mc_file_prefix=_to_str(
                cli_payload.get("mc_file_prefix"),
                CLIConfig.mc_file_prefix,
            ),
            holdings_file_prefix=_to_str(
                cli_payload.get("holdings_file_prefix"),
                CLIConfig.holdings_file_prefix,
            ),
        ),
        config_path=str(path),
        loaded_from_file=True,
    )
    logger.info(
        "broker_cfg_loaded",
        path=str(path),
        ibkr_host=config.ibkr.host,
        ibkr_port=config.ibkr.port,
        futu_host=config.futu.host,
        futu_port=config.futu.port,
        etf_cooldown_minutes=config.refresh.etf_cooldown_minutes,
        holdings_cooldown_minutes=config.refresh.holdings_cooldown_minutes,
        serial_gap_seconds=config.refresh.serial_gap_seconds,
        cli_downloads_dir=config.cli.downloads_dir,
    )
    return config


def broker_defaults(config: Optional[BrokerConfig] = None) -> Dict[str, Dict[str, Any]]:
    effective = config or load_broker_config()
    return {
        "ibkr": {
            "host": effective.ibkr.host,
            "port": effective.ibkr.port,
            "client_id": effective.ibkr.client_id,
            "timeout": effective.ibkr.timeout,
        },
        "futu": {
            "host": effective.futu.host,
            "port": effective.futu.port,
            "market": effective.futu.market,
        },
    }
