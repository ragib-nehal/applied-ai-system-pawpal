import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from schemas import RetrievalRecordInput
from services.db import (
    get_connection,
    init_db,
    load_all_records,
    load_records_for_pet,
    upsert_retrieval_records,
)


@pytest.fixture
def tmp_db(tmp_path):
    """Return a path to a fresh temporary database for each test."""
    db_path = tmp_path / "test_pawpal.db"
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------

def test_get_connection_creates_parent_dirs(tmp_path):
    nested = tmp_path / "nested" / "deep" / "pawpal.db"
    conn = get_connection(nested)
    conn.close()
    assert nested.exists()


def test_get_connection_row_factory(tmp_db):
    conn = get_connection(tmp_db)
    conn.execute("INSERT INTO retrieval_records VALUES ('id1','pet','sec','content')")
    conn.commit()
    row = conn.execute("SELECT * FROM retrieval_records WHERE record_id='id1'").fetchone()
    # sqlite3.Row supports dict-style access
    assert row["record_id"] == "id1"
    conn.close()


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_db_creates_retrieval_records_table(tmp_db):
    conn = get_connection(tmp_db)
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert "retrieval_records" in tables


def test_init_db_creates_pipeline_runs_table(tmp_db):
    conn = get_connection(tmp_db)
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert "pipeline_runs" in tables


def test_init_db_idempotent(tmp_db):
    # Calling init_db twice should not raise or duplicate tables
    init_db(tmp_db)
    init_db(tmp_db)
    conn = get_connection(tmp_db)
    tables = [
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    conn.close()
    assert tables.count("retrieval_records") == 1
    assert tables.count("pipeline_runs") == 1


# ---------------------------------------------------------------------------
# upsert_retrieval_records
# ---------------------------------------------------------------------------

def _make_record(record_id="r1", pet_name="Buddy", section="medications", content="Take daily"):
    return RetrievalRecordInput(
        record_id=record_id,
        pet_name=pet_name,
        section=section,
        content=content,
    )


def test_upsert_inserts_new_records(tmp_db):
    records = [
        _make_record("r1", "Buddy", "medications", "Take daily"),
        _make_record("r2", "Whiskers", "medical_history", "Diabetes"),
    ]
    upsert_retrieval_records(records, tmp_db)
    all_recs = load_all_records(tmp_db)
    assert len(all_recs) == 2


def test_upsert_updates_existing_record(tmp_db):
    upsert_retrieval_records([_make_record("r1", "Buddy", "medications", "Old content")], tmp_db)
    upsert_retrieval_records([_make_record("r1", "Buddy", "medications", "New content")], tmp_db)
    all_recs = load_all_records(tmp_db)
    assert len(all_recs) == 1
    assert all_recs[0]["content"] == "New content"


def test_upsert_empty_list_is_no_op(tmp_db):
    upsert_retrieval_records([], tmp_db)
    assert load_all_records(tmp_db) == []


def test_upsert_updates_pet_name_on_conflict(tmp_db):
    upsert_retrieval_records([_make_record("r1", "Buddy", "medications", "content")], tmp_db)
    upsert_retrieval_records([_make_record("r1", "Rex", "medications", "content")], tmp_db)
    all_recs = load_all_records(tmp_db)
    assert all_recs[0]["pet_name"] == "Rex"


# ---------------------------------------------------------------------------
# load_records_for_pet
# ---------------------------------------------------------------------------

def test_load_records_for_pet_returns_only_matching_pet(tmp_db):
    upsert_retrieval_records(
        [
            _make_record("r1", "Buddy", "medications", "Buddy med"),
            _make_record("r2", "Whiskers", "medical_history", "Cat history"),
        ],
        tmp_db,
    )
    buddy_recs = load_records_for_pet("Buddy", tmp_db)
    assert len(buddy_recs) == 1
    assert buddy_recs[0]["pet_name"] == "Buddy"
    assert buddy_recs[0]["content"] == "Buddy med"


def test_load_records_for_pet_returns_empty_when_no_match(tmp_db):
    upsert_retrieval_records([_make_record("r1", "Buddy", "sec", "content")], tmp_db)
    result = load_records_for_pet("NonExistentPet", tmp_db)
    assert result == []


def test_load_records_for_pet_returns_dicts(tmp_db):
    upsert_retrieval_records([_make_record("r1", "Buddy", "sec", "content")], tmp_db)
    recs = load_records_for_pet("Buddy", tmp_db)
    assert isinstance(recs[0], dict)
    assert "record_id" in recs[0]
    assert "pet_name" in recs[0]
    assert "section" in recs[0]
    assert "content" in recs[0]


# ---------------------------------------------------------------------------
# load_all_records
# ---------------------------------------------------------------------------

def test_load_all_records_returns_all(tmp_db):
    upsert_retrieval_records(
        [
            _make_record("r1", "Buddy", "sec", "c1"),
            _make_record("r2", "Whiskers", "sec", "c2"),
            _make_record("r3", "Buddy", "behavior_notes", "c3"),
        ],
        tmp_db,
    )
    all_recs = load_all_records(tmp_db)
    assert len(all_recs) == 3


def test_load_all_records_returns_empty_on_fresh_db(tmp_db):
    assert load_all_records(tmp_db) == []


def test_load_all_records_returns_dicts(tmp_db):
    upsert_retrieval_records([_make_record()], tmp_db)
    recs = load_all_records(tmp_db)
    assert isinstance(recs[0], dict)