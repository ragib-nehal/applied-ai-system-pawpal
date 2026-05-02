import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pawpal_backend.services.reset import reset_all, reset_chroma, reset_sqlite


def test_reset_sqlite_deletes_db_wal_and_shm_files(tmp_path):
    db_path = tmp_path / "pawpal.db"
    wal_path = tmp_path / "pawpal.db-wal"
    shm_path = tmp_path / "pawpal.db-shm"
    for path in (db_path, wal_path, shm_path):
        path.write_text("data")

    reset_sqlite(db_path)

    assert not db_path.exists()
    assert not wal_path.exists()
    assert not shm_path.exists()


def test_reset_sqlite_ignores_missing_files(tmp_path):
    reset_sqlite(tmp_path / "missing.db")


def test_reset_chroma_deletes_directory_tree(tmp_path):
    chroma_dir = tmp_path / "chroma"
    nested = chroma_dir / "collection" / "index.bin"
    nested.parent.mkdir(parents=True)
    nested.write_text("index")

    reset_chroma(chroma_dir)

    assert not chroma_dir.exists()


def test_reset_chroma_ignores_missing_directory(tmp_path):
    reset_chroma(tmp_path / "missing_chroma")


def test_reset_all_resets_sqlite_and_chroma(tmp_path):
    db_path = tmp_path / "pawpal.db"
    chroma_dir = tmp_path / "chroma"
    db_path.write_text("data")
    chroma_dir.mkdir()
    (chroma_dir / "file").write_text("index")

    reset_all(db_path=db_path, chroma_dir=chroma_dir)

    assert not db_path.exists()
    assert not chroma_dir.exists()
