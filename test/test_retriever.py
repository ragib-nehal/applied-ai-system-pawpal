import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from backend.pawpal_backend.schemas import Citation, RetrievalRecordInput
from backend.pawpal_backend.services.retriever import Retriever


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record(record_id, pet_name, section, content):
    return RetrievalRecordInput(
        record_id=record_id, pet_name=pet_name, section=section, content=content
    )


def _row(record_id, pet_name, section, content):
    return {"record_id": record_id, "pet_name": pet_name, "section": section, "content": content}


# ---------------------------------------------------------------------------
# _lexical_query via retrieve (Chroma returns empty, falls back to lexical)
# ---------------------------------------------------------------------------

class TestLexicalQuery:
    """Tests for _lexical_query through the retrieve() public API.

    We patch _try_chroma_query to return [] to force the lexical path,
    and patch load_all_records to control the data source.
    """

    def _make_retriever(self):
        r = Retriever()
        return r

    def test_returns_citation_matching_query_term(self):
        retriever = self._make_retriever()
        rows = [_row("r1", "Buddy", "medications", "Buddy needs insulin daily")]
        with patch("backend.pawpal_backend.services.retriever.load_all_records", return_value=rows), \
             patch.object(retriever, "_try_chroma_query", return_value=[]):
            results = retriever.retrieve(pet_name="Buddy", query="insulin", top_k=4)
        assert len(results) == 1
        assert results[0].record_id == "r1"

    def test_filters_by_pet_name(self):
        retriever = self._make_retriever()
        rows = [
            _row("r1", "Buddy", "medications", "Buddy insulin"),
            _row("r2", "Whiskers", "medications", "Whiskers insulin"),
        ]
        with patch("backend.pawpal_backend.services.retriever.load_all_records", return_value=rows), \
             patch.object(retriever, "_try_chroma_query", return_value=[]):
            results = retriever.retrieve(pet_name="Buddy", query="insulin", top_k=4)
        assert all(r.record_id == "r1" for r in results)
        assert len(results) == 1

    def test_returns_empty_when_no_terms_match(self):
        retriever = self._make_retriever()
        rows = [_row("r1", "Buddy", "medications", "Buddy eats food")]
        with patch("backend.pawpal_backend.services.retriever.load_all_records", return_value=rows), \
             patch.object(retriever, "_try_chroma_query", return_value=[]):
            results = retriever.retrieve(pet_name="Buddy", query="insulin diabetes", top_k=4)
        assert results == []

    def test_returns_empty_when_no_records_for_pet(self):
        retriever = self._make_retriever()
        rows = [_row("r1", "Whiskers", "medications", "medication content")]
        with patch("backend.pawpal_backend.services.retriever.load_all_records", return_value=rows), \
             patch.object(retriever, "_try_chroma_query", return_value=[]):
            results = retriever.retrieve(pet_name="Buddy", query="medication", top_k=4)
        assert results == []

    def test_top_k_limits_results(self):
        retriever = self._make_retriever()
        rows = [
            _row(f"r{i}", "Buddy", "medications", f"medication content {i}")
            for i in range(10)
        ]
        with patch("backend.pawpal_backend.services.retriever.load_all_records", return_value=rows), \
             patch.object(retriever, "_try_chroma_query", return_value=[]):
            results = retriever.retrieve(pet_name="Buddy", query="medication", top_k=3)
        assert len(results) == 3

    def test_results_sorted_by_score_descending(self):
        retriever = self._make_retriever()
        rows = [
            _row("r1", "Buddy", "medications", "medication"),  # 1 term hit
            _row("r2", "Buddy", "medications", "medication insulin daily"),  # 3 term hits
            _row("r3", "Buddy", "medications", "medication insulin"),  # 2 term hits
        ]
        with patch("backend.pawpal_backend.services.retriever.load_all_records", return_value=rows), \
             patch.object(retriever, "_try_chroma_query", return_value=[]):
            results = retriever.retrieve(pet_name="Buddy", query="medication insulin daily", top_k=3)
        assert results[0].record_id == "r2"
        assert results[1].record_id == "r3"
        assert results[2].record_id == "r1"

    def test_snippet_truncated_to_220_chars(self):
        retriever = self._make_retriever()
        long_content = "medication " + "x" * 300
        rows = [_row("r1", "Buddy", "medications", long_content)]
        with patch("backend.pawpal_backend.services.retriever.load_all_records", return_value=rows), \
             patch.object(retriever, "_try_chroma_query", return_value=[]):
            results = retriever.retrieve(pet_name="Buddy", query="medication", top_k=4)
        assert len(results) == 1
        assert len(results[0].snippet) <= 220

    def test_citation_fields_are_correct(self):
        retriever = self._make_retriever()
        rows = [_row("r1", "Buddy", "medical_history", "Buddy has diabetes")]
        with patch("backend.pawpal_backend.services.retriever.load_all_records", return_value=rows), \
             patch.object(retriever, "_try_chroma_query", return_value=[]):
            results = retriever.retrieve(pet_name="Buddy", query="diabetes", top_k=4)
        c = results[0]
        assert c.record_id == "r1"
        assert c.section == "medical_history"
        assert isinstance(c.score, float)
        assert c.score > 0


# ---------------------------------------------------------------------------
# retrieve prefers chroma over lexical
# ---------------------------------------------------------------------------

def test_retrieve_returns_chroma_results_when_available():
    retriever = Retriever()
    chroma_citation = Citation(record_id="chroma-1", section="medications", snippet="chroma result", score=0.95)
    with patch.object(retriever, "_try_chroma_query", return_value=[chroma_citation]):
        results = retriever.retrieve(pet_name="Buddy", query="medication", top_k=4)
    assert results == [chroma_citation]


def test_retrieve_falls_back_to_lexical_when_chroma_empty():
    retriever = Retriever()
    rows = [_row("r1", "Buddy", "medications", "medication daily")]
    with patch.object(retriever, "_try_chroma_query", return_value=[]), \
         patch("backend.pawpal_backend.services.retriever.load_all_records", return_value=rows):
        results = retriever.retrieve(pet_name="Buddy", query="medication", top_k=4)
    assert results[0].record_id == "r1"


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def test_ingest_calls_upsert_and_chroma(tmp_path):
    retriever = Retriever(chroma_dir=tmp_path / "chroma")
    records = [_record("r1", "Buddy", "medications", "content")]
    with patch("backend.pawpal_backend.services.retriever.upsert_retrieval_records") as mock_upsert, \
         patch.object(retriever, "_try_chroma_upsert") as mock_chroma:
        retriever.ingest(records)
    mock_upsert.assert_called_once_with(records)
    mock_chroma.assert_called_once_with(records)


def test_ingest_empty_list_still_calls_upsert(tmp_path):
    retriever = Retriever(chroma_dir=tmp_path / "chroma")
    with patch("backend.pawpal_backend.services.retriever.upsert_retrieval_records") as mock_upsert, \
         patch.object(retriever, "_try_chroma_upsert"):
        retriever.ingest([])
    mock_upsert.assert_called_once_with([])


# ---------------------------------------------------------------------------
# _try_chroma_query returns empty when chroma dir does not exist
# ---------------------------------------------------------------------------

def test_try_chroma_query_returns_empty_if_dir_missing(tmp_path):
    retriever = Retriever(chroma_dir=tmp_path / "nonexistent_chroma")
    # Since the dir doesn't exist, _try_chroma_query should return []
    result = retriever._try_chroma_query(pet_name="Buddy", query="medication", top_k=4)
    assert result == []