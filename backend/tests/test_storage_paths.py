from pathlib import Path

import pytest

from app.core.paths import (
    MOMENTUM_DATA_DIR_ENV,
    MOMENTUM_FUTU_OI_CACHE_DB_PATH_ENV,
    MOMENTUM_MAIN_DB_PATH_ENV,
    migrate_legacy_backend_storage,
    resolve_backend_storage_paths,
)


def test_resolve_backend_storage_paths_uses_default_layout(tmp_path: Path) -> None:
    paths = resolve_backend_storage_paths(backend_root=tmp_path, env={})

    assert paths.data_dir == tmp_path / "data"
    assert paths.runtime_dir == tmp_path / "data" / "runtime"
    assert paths.cache_dir == tmp_path / "data" / "cache"
    assert paths.main_db == tmp_path / "data" / "runtime" / "momentum_radar.db"
    assert paths.futu_oi_cache_db == tmp_path / "data" / "cache" / "futu_oi_cache.db"


def test_resolve_backend_storage_paths_honors_env_overrides(tmp_path: Path) -> None:
    env = {
        MOMENTUM_DATA_DIR_ENV: "storage",
        MOMENTUM_MAIN_DB_PATH_ENV: "storage/custom/main.db",
        MOMENTUM_FUTU_OI_CACHE_DB_PATH_ENV: "storage/custom/cache.db",
    }

    paths = resolve_backend_storage_paths(backend_root=tmp_path, env=env)

    assert paths.data_dir == tmp_path / "storage"
    assert paths.main_db == tmp_path / "storage" / "custom" / "main.db"
    assert paths.futu_oi_cache_db == tmp_path / "storage" / "custom" / "cache.db"


def test_migrate_legacy_backend_storage_moves_main_db_and_deletes_legacy_artifacts(tmp_path: Path) -> None:
    legacy_main_db = tmp_path / "momentum_radar.db"
    legacy_main_db.write_text("main-db", encoding="utf-8")
    (tmp_path / "momentum_radar.db-wal").write_text("wal", encoding="utf-8")
    (tmp_path / "momentum_radar.db-shm").write_text("shm", encoding="utf-8")
    (tmp_path / "futu_oi_cache.db").write_text("cache", encoding="utf-8")

    checkpointed: list[Path] = []
    paths = migrate_legacy_backend_storage(
        paths=resolve_backend_storage_paths(backend_root=tmp_path, env={}),
        open_file_detector=lambda items: [],
        checkpoint_fn=lambda db_path: checkpointed.append(db_path),
    )

    assert checkpointed == [legacy_main_db]
    assert paths.main_db.read_text(encoding="utf-8") == "main-db"
    assert not legacy_main_db.exists()
    assert not (tmp_path / "momentum_radar.db-wal").exists()
    assert not (tmp_path / "momentum_radar.db-shm").exists()
    assert not (tmp_path / "futu_oi_cache.db").exists()


def test_migrate_legacy_backend_storage_fails_when_both_main_dbs_exist(tmp_path: Path) -> None:
    legacy_main_db = tmp_path / "momentum_radar.db"
    legacy_main_db.write_text("legacy", encoding="utf-8")
    canonical_main_db = tmp_path / "data" / "runtime" / "momentum_radar.db"
    canonical_main_db.parent.mkdir(parents=True, exist_ok=True)
    canonical_main_db.write_text("canonical", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Both legacy and canonical main database files exist"):
        migrate_legacy_backend_storage(
            paths=resolve_backend_storage_paths(backend_root=tmp_path, env={}),
            open_file_detector=lambda items: [],
            checkpoint_fn=lambda _db_path: None,
        )


def test_migrate_legacy_backend_storage_fails_when_legacy_files_are_open(tmp_path: Path) -> None:
    legacy_main_db = tmp_path / "momentum_radar.db"
    legacy_main_db.write_text("legacy", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Legacy SQLite files are still in use"):
        migrate_legacy_backend_storage(
            paths=resolve_backend_storage_paths(backend_root=tmp_path, env={}),
            open_file_detector=lambda items: [legacy_main_db],
            checkpoint_fn=lambda _db_path: None,
        )
