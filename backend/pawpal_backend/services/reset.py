from __future__ import annotations

import shutil
from pathlib import Path

from .db import DEFAULT_DB_PATH

DEFAULT_CHROMA_DIR = Path(__file__).resolve().parents[3] / "data" / "chroma"


def reset_sqlite(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    path = Path(db_path)
    for candidate in (
        path,
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    ):
        if candidate.exists() and candidate.is_file():
            candidate.unlink()


def reset_chroma(chroma_dir: Path | str) -> None:
    path = Path(chroma_dir)
    if path.exists() and path.is_dir():
        shutil.rmtree(path)


def reset_all(
    db_path: Path | str = DEFAULT_DB_PATH,
    chroma_dir: Path | str = DEFAULT_CHROMA_DIR,
) -> None:
    reset_sqlite(db_path)
    reset_chroma(chroma_dir)
