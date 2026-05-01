from __future__ import annotations

import sqlite3
from pathlib import Path

from schemas import RetrievalRecordInput


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "pawpal.db"


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS retrieval_records (
                record_id TEXT PRIMARY KEY,
                pet_name TEXT NOT NULL,
                section TEXT NOT NULL,
                content TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                used_fallback INTEGER NOT NULL,
                validation_status TEXT NOT NULL,
                validation_errors TEXT NOT NULL,
                retrieval_context_count INTEGER NOT NULL
            )
            """
        )
        conn.commit()


def upsert_retrieval_records(
    records: list[RetrievalRecordInput], db_path: Path | str = DEFAULT_DB_PATH
) -> None:
    if not records:
        return
    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO retrieval_records (record_id, pet_name, section, content)
            VALUES (:record_id, :pet_name, :section, :content)
            ON CONFLICT(record_id) DO UPDATE SET
                pet_name=excluded.pet_name,
                section=excluded.section,
                content=excluded.content
            """,
            [r.model_dump() for r in records],
        )
        conn.commit()


def load_records_for_pet(
    pet_name: str, db_path: Path | str = DEFAULT_DB_PATH
) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT record_id, pet_name, section, content
            FROM retrieval_records
            WHERE pet_name = ?
            """,
            (pet_name,),
        ).fetchall()
    return [dict(row) for row in rows]


def load_all_records(db_path: Path | str = DEFAULT_DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT record_id, pet_name, section, content
            FROM retrieval_records
            """
        ).fetchall()
    return [dict(row) for row in rows]
