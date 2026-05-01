import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pawpal_backend.schemas import Citation, PetInput, RetrievalRecordInput, ScheduleRequest, TaskInput
from backend.pawpal_backend.services.rag_pipeline import RAGPipeline


class FakeRetriever:
    def ingest(self, records):
        return None

    def retrieve(self, pet_name: str, query: str, top_k: int = 4):
        return [
            Citation(
                record_id=f"{pet_name}-ctx-1",
                section="medical_history",
                snippet=f"{pet_name} context snippet",
                score=0.9,
            )
        ]


class ValidClient:
    def generate_json(self, system_prompt: str, user_prompt: str):
        return {
            "schedule": [
                {
                    "pet": "Buddy",
                    "day": "Monday",
                    "time": "08:00",
                    "title": "Medication",
                    "duration_minutes": 10,
                    "priority": "high",
                    "reason": "Medication is critical and should be done first.",
                    "citations": [
                        {
                            "record_id": "Buddy-ctx-1",
                            "section": "medical_history",
                            "snippet": "Buddy context snippet",
                        }
                    ],
                }
            ],
            "guidance": [
                {
                    "pet": "Buddy",
                    "title": "Care tip for Buddy",
                    "detail": "Keep medication timing consistent.",
                    "citations": [
                        {
                            "record_id": "Buddy-ctx-1",
                            "section": "medical_history",
                            "snippet": "Buddy context snippet",
                        }
                    ],
                }
            ],
            "dropped_tasks": [],
        }


class InvalidClient:
    def __init__(self):
        self.calls = 0

    def generate_json(self, system_prompt: str, user_prompt: str):
        self.calls += 1
        if self.calls == 1:
            return {"schedule": []}
        return {"schedule": []}


def make_request():
    return ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=60,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                energy_level="high",
                tasks=[
                    TaskInput(
                        title="Medication",
                        duration_minutes=10,
                        priority="high",
                        frequency="daily",
                    )
                ],
            )
        ],
        retrieval_records=[
            RetrievalRecordInput(
                record_id="buddy-r1",
                pet_name="Buddy",
                section="medical_history",
                content="Medication is required daily in the morning.",
            )
        ],
    )


def test_rag_pipeline_valid_output_stays_non_fallback():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    result = pipeline.run(make_request())
    assert result.used_fallback is False
    assert result.validation_status in {"valid", "repaired"}
    assert result.schedule
    assert result.schedule[0].citations


def test_rag_pipeline_invalid_output_uses_fallback():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=InvalidClient())
    result = pipeline.run(make_request())
    assert result.used_fallback is True
    assert result.validation_status == "fallback"
    assert result.validation_errors


# ---------------------------------------------------------------------------
# Additional pipeline tests
# ---------------------------------------------------------------------------

class RepairClient:
    """Returns invalid output on first call, valid output on second (repair)."""

    def __init__(self):
        self.calls = 0

    def generate_json(self, system_prompt: str, user_prompt: str):
        self.calls += 1
        if self.calls == 1:
            # First call: missing critical task → will fail validation
            return {
                "schedule": [
                    {
                        "pet": "Buddy",
                        "day": "Monday",
                        "time": "09:00",
                        "title": "Walk",  # Not "Medication" — critical task missing
                        "duration_minutes": 30,
                        "priority": "low",
                        "reason": "exercise",
                        "citations": [
                            {
                                "record_id": "Buddy-ctx-1",
                                "section": "medical_history",
                                "snippet": "Buddy context snippet",
                            }
                        ],
                    }
                ],
                "guidance": [],
                "dropped_tasks": [],
            }
        # Second call (repair): include the critical task
        return {
            "schedule": [
                {
                    "pet": "Buddy",
                    "day": "Monday",
                    "time": "08:00",
                    "title": "Medication",
                    "duration_minutes": 10,
                    "priority": "high",
                    "reason": "critical medication",
                    "citations": [
                        {
                            "record_id": "Buddy-ctx-1",
                            "section": "medical_history",
                            "snippet": "Buddy context snippet",
                        }
                    ],
                }
            ],
            "guidance": [
                {
                    "pet": "Buddy",
                    "title": "Care tip for Buddy",
                    "detail": "Keep medication timing consistent.",
                    "citations": [
                        {
                            "record_id": "Buddy-ctx-1",
                            "section": "medical_history",
                            "snippet": "Buddy context snippet",
                        }
                    ],
                }
            ],
            "dropped_tasks": [],
        }


class ExceptionClient:
    """Always raises an exception to simulate Ollama being unavailable."""

    def generate_json(self, system_prompt: str, user_prompt: str):
        raise ConnectionError("Ollama is not running")


class MissingScheduleKeyClient:
    """Returns a dict without a 'schedule' key."""

    def generate_json(self, system_prompt: str, user_prompt: str):
        return {"guidance": [], "dropped_tasks": []}


class InvalidScheduleTypeClient:
    """Returns schedule as a non-list type."""

    def generate_json(self, system_prompt: str, user_prompt: str):
        return {"schedule": "not a list"}


def test_rag_pipeline_repair_path_returns_repaired_status():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=RepairClient())
    result = pipeline.run(make_request())
    assert result.validation_status == "repaired"
    assert result.used_fallback is False


def test_rag_pipeline_repair_path_schedule_not_empty():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=RepairClient())
    result = pipeline.run(make_request())
    assert len(result.schedule) > 0


def test_rag_pipeline_repair_path_preserves_first_validation_errors():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=RepairClient())
    result = pipeline.run(make_request())
    # repaired result should carry validation errors from the first pass
    assert result.validation_errors


def test_rag_pipeline_llm_exception_triggers_fallback():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ExceptionClient())
    result = pipeline.run(make_request())
    assert result.used_fallback is True
    assert result.validation_status == "fallback"


def test_rag_pipeline_missing_schedule_key_triggers_fallback():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=MissingScheduleKeyClient())
    result = pipeline.run(make_request())
    # missing schedule key → empty schedule → validation fails → fallback
    assert result.used_fallback is True


def test_rag_pipeline_invalid_schedule_type_triggers_fallback():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=InvalidScheduleTypeClient())
    result = pipeline.run(make_request())
    assert result.used_fallback is True


def test_rag_pipeline_valid_result_has_model_provider_set():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    result = pipeline.run(make_request())
    assert result.model_provider


def test_rag_pipeline_retrieval_context_count_reflects_hits():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    result = pipeline.run(make_request())
    # FakeRetriever returns 1 citation per pet, request has 1 pet
    assert result.retrieval_context_count == 1


def test_rag_pipeline_run_without_retrieval_records():
    """Pipeline should handle a request with no retrieval_records gracefully."""
    from backend.pawpal_backend.schemas import ScheduleRequest, PetInput, TaskInput

    request_no_records = ScheduleRequest(
        owner_name="Bob",
        available_time_per_day=60,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[
                    TaskInput(title="Medication", duration_minutes=10, priority="high", frequency="daily")
                ],
            )
        ],
        retrieval_records=[],
    )

    class NoIngestRetriever(FakeRetriever):
        def ingest(self, records):
            # Should not be called since retrieval_records is empty
            raise AssertionError("ingest should not be called with empty records")

    pipeline = RAGPipeline(retriever=NoIngestRetriever(), llm_client=ValidClient())
    # Should not raise
    result = pipeline.run(request_no_records)
    assert result is not None


# ---------------------------------------------------------------------------
# request_pet_from_title helper
# ---------------------------------------------------------------------------

def test_request_pet_from_title_finds_pet_by_name_in_title():
    from backend.pawpal_backend.services.rag_pipeline import request_pet_from_title

    citations_by_pet = {"Buddy": [], "Whiskers": []}
    assert request_pet_from_title("Care tip for Buddy", citations_by_pet) == "Buddy"


def test_request_pet_from_title_case_insensitive():
    from backend.pawpal_backend.services.rag_pipeline import request_pet_from_title

    citations_by_pet = {"Buddy": []}
    assert request_pet_from_title("care tip for buddy", citations_by_pet) == "Buddy"


def test_request_pet_from_title_returns_first_pet_when_no_match():
    from backend.pawpal_backend.services.rag_pipeline import request_pet_from_title

    citations_by_pet = {"Buddy": [], "Whiskers": []}
    result = request_pet_from_title("Generic tip about weather", citations_by_pet)
    assert result in {"Buddy", "Whiskers"}


def test_request_pet_from_title_returns_unknown_for_empty_dict():
    from backend.pawpal_backend.services.rag_pipeline import request_pet_from_title

    result = request_pet_from_title("some title", {})
    assert result == "Unknown"


# ---------------------------------------------------------------------------
# _build_citations helper
# ---------------------------------------------------------------------------

def test_build_citations_returns_parsed_citations_when_valid():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    raw = [{"record_id": "r1", "section": "medications", "snippet": "snip"}]
    fallback = [
        Citation(record_id="fallback-r", section="system", snippet="fallback snip")
    ]
    result = pipeline._build_citations(raw, fallback)
    assert result[0].record_id == "r1"


def test_build_citations_uses_fallback_when_raw_is_empty():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    fallback = [Citation(record_id="fb", section="system", snippet="fallback")]
    result = pipeline._build_citations([], fallback)
    assert result[0].record_id == "fb"


def test_build_citations_uses_fallback_when_raw_is_none():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    fallback = [Citation(record_id="fb", section="system", snippet="fallback")]
    result = pipeline._build_citations(None, fallback)
    assert result[0].record_id == "fb"


def test_build_citations_hardcoded_missing_when_both_empty():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    result = pipeline._build_citations([], [])
    assert result[0].record_id == "missing"
    assert "missing" in result[0].snippet.lower()


def test_build_citations_skips_invalid_raw_entries():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    raw = [
        {"record_id": "r1", "section": "sec", "snippet": "valid"},
        {"record_id": "r2"},  # missing section and snippet → invalid
    ]
    fallback = [Citation(record_id="fb", section="sys", snippet="fb snip")]
    result = pipeline._build_citations(raw, fallback)
    # Valid entry should be parsed; invalid skipped
    assert result[0].record_id == "r1"
