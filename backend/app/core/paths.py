"""
Backend storage path management and legacy SQLite migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional
import os
import shutil
import sqlite3
import subprocess


MOMENTUM_DATA_DIR_ENV = "MOMENTUM_DATA_DIR"
MOMENTUM_MAIN_DB_PATH_ENV = "MOMENTUM_MAIN_DB_PATH"
MOMENTUM_FUTU_OI_CACHE_DB_PATH_ENV = "MOMENTUM_FUTU_OI_CACHE_DB_PATH"


@dataclass(frozen=True)
class BackendStoragePaths:
    backend_root: Path
    data_dir: Path
    runtime_dir: Path
    cache_dir: Path
    main_db: Path
    futu_oi_cache_db: Path
    legacy_main_db: Path
    legacy_main_db_wal: Path
    legacy_main_db_shm: Path
    legacy_futu_oi_cache_db: Path


def _resolve_configured_path(raw_value: Optional[str], *, base_dir: Path, default: Path) -> Path:
    if not raw_value:
        return default
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def resolve_backend_storage_paths(
    *,
    backend_root: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> BackendStoragePaths:
    env_map = os.environ if env is None else env
    resolved_backend_root = (
        Path(backend_root).expanduser().resolve()
        if backend_root is not None
        else Path(__file__).resolve().parents[2]
    )
    data_dir = _resolve_configured_path(
        env_map.get(MOMENTUM_DATA_DIR_ENV),
        base_dir=resolved_backend_root,
        default=resolved_backend_root / "data",
    )
    runtime_dir = data_dir / "runtime"
    cache_dir = data_dir / "cache"
    main_db = _resolve_configured_path(
        env_map.get(MOMENTUM_MAIN_DB_PATH_ENV),
        base_dir=resolved_backend_root,
        default=runtime_dir / "momentum_radar.db",
    )
    futu_oi_cache_db = _resolve_configured_path(
        env_map.get(MOMENTUM_FUTU_OI_CACHE_DB_PATH_ENV),
        base_dir=resolved_backend_root,
        default=cache_dir / "futu_oi_cache.db",
    )
    return BackendStoragePaths(
        backend_root=resolved_backend_root,
        data_dir=data_dir,
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        main_db=main_db,
        futu_oi_cache_db=futu_oi_cache_db,
        legacy_main_db=resolved_backend_root / "momentum_radar.db",
        legacy_main_db_wal=resolved_backend_root / "momentum_radar.db-wal",
        legacy_main_db_shm=resolved_backend_root / "momentum_radar.db-shm",
        legacy_futu_oi_cache_db=resolved_backend_root / "futu_oi_cache.db",
    )


def ensure_backend_storage_dirs(paths: Optional[BackendStoragePaths] = None) -> BackendStoragePaths:
    resolved = paths or resolve_backend_storage_paths()
    for directory in {resolved.data_dir, resolved.runtime_dir, resolved.cache_dir, resolved.main_db.parent, resolved.futu_oi_cache_db.parent}:
        directory.mkdir(parents=True, exist_ok=True)
    return resolved


def detect_open_files_with_lsof(paths: Iterable[Path]) -> list[Path]:
    existing_paths = [path for path in paths if path.exists()]
    if not existing_paths:
        return []
    try:
        result = subprocess.run(
            ["lsof", *[str(path) for path in existing_paths]],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode not in (0, 1):
        raise RuntimeError(f"lsof failed while checking SQLite files: {output or result.returncode}")

    return [path for path in existing_paths if str(path) in output]


def checkpoint_sqlite_database(db_path: Path) -> None:
    if not db_path.exists():
        return
    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute("PRAGMA wal_checkpoint(FULL)")
    finally:
        connection.close()


def migrate_legacy_backend_storage(
    *,
    paths: Optional[BackendStoragePaths] = None,
    open_file_detector: Optional[Callable[[Iterable[Path]], list[Path]]] = None,
    checkpoint_fn: Optional[Callable[[Path], None]] = None,
) -> BackendStoragePaths:
    resolved = ensure_backend_storage_dirs(paths)
    detect_open_files = open_file_detector or detect_open_files_with_lsof
    checkpoint = checkpoint_fn or checkpoint_sqlite_database

    same_main_path = resolved.main_db == resolved.legacy_main_db
    same_cache_path = resolved.futu_oi_cache_db == resolved.legacy_futu_oi_cache_db

    legacy_candidates = []
    if not same_main_path:
        legacy_candidates.extend(
            [
                resolved.legacy_main_db,
                resolved.legacy_main_db_wal,
                resolved.legacy_main_db_shm,
            ]
        )
    if not same_cache_path:
        legacy_candidates.append(resolved.legacy_futu_oi_cache_db)

    open_files = detect_open_files(legacy_candidates)
    if open_files:
        joined = ", ".join(str(path) for path in open_files)
        raise RuntimeError(f"Legacy SQLite files are still in use: {joined}")

    if not same_main_path and resolved.main_db.exists() and resolved.legacy_main_db.exists():
        raise RuntimeError(
            "Both legacy and canonical main database files exist; "
            "resolve manually before continuing."
        )

    if not same_main_path and resolved.legacy_main_db.exists() and not resolved.main_db.exists():
        checkpoint(resolved.legacy_main_db)
        shutil.move(str(resolved.legacy_main_db), str(resolved.main_db))

    for stale_path in (
        resolved.legacy_main_db_wal,
        resolved.legacy_main_db_shm,
    ):
        if not same_main_path and stale_path.exists():
            stale_path.unlink()

    if not same_cache_path and resolved.legacy_futu_oi_cache_db.exists():
        resolved.legacy_futu_oi_cache_db.unlink()

    return resolved
