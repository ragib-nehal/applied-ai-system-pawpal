import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pawpal_backend.schemas import (
    Citation,
    PetInput,
    RAGScheduleResponse,
    RetrievalRecordInput,
    ScheduledTask,
    ScheduleRequest,
    TaskInput,
)
from backend.pawpal_backend.services.legacy_scheduler import DAYS
from backend.pawpal_backend.services import db as db_module
from backend.pawpal_backend.services import rag_pipeline as rag_module
from backend.pawpal_backend.services.rag_pipeline import (
    RAGPipeline,
    expand_daily_tasks_from_request,
)


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


class RecordingRetriever(FakeRetriever):
    def __init__(self):
        self.ingested_records = None
        self.retrieve_calls = []

    def ingest(self, records):
        self.ingested_records = records

    def retrieve(self, pet_name: str, query: str, top_k: int = 4):
        self.retrieve_calls.append((pet_name, query, top_k))
        return super().retrieve(pet_name, query, top_k)


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


class OverlappingDroppedClient:
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
                },
                {
                    "pet": "Buddy",
                    "day": "Monday",
                    "time": "08:10",
                    "title": "Morning walk",
                    "duration_minutes": 20,
                    "priority": "medium",
                    "reason": "Exercise if time allows.",
                    "citations": [
                        {
                            "record_id": "Buddy-ctx-1",
                            "section": "medical_history",
                            "snippet": "Buddy context snippet",
                        }
                    ],
                },
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
            "dropped_tasks": [
                {
                    "day": "Monday",
                    "pet": "Buddy",
                    "title": "Morning walk",
                    "time": "08:10",
                    "duration_minutes": 20,
                }
            ],
        }


class DistinctDroppedClient:
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
            "dropped_tasks": [
                {
                    "day": "Monday",
                    "pet": "Buddy",
                    "title": "Morning walk",
                    "time": "08:10",
                    "duration_minutes": 20,
                }
            ],
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


def test_rag_pipeline_removes_dropped_task_from_schedule_payload():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=OverlappingDroppedClient())
    result = pipeline.run(make_request())

    assert result.used_fallback is False
    assert result.validation_status == "valid"
    assert len(result.schedule) == 7
    assert {item.title for item in result.schedule} == {"Medication"}
    assert {item.day for item in result.schedule} == set(DAYS)
    assert result.dropped_tasks == [
        {
            "day": "Monday",
            "pet": "Buddy",
            "title": "Morning walk",
            "time": "08:10",
            "duration_minutes": 20,
        }
    ]


def test_rag_pipeline_preserves_distinct_scheduled_and_dropped_tasks():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=DistinctDroppedClient())
    result = pipeline.run(make_request())

    assert len(result.schedule) == 7
    assert {item.title for item in result.schedule} == {"Medication"}
    assert {item.day for item in result.schedule} == set(DAYS)
    assert [task["title"] for task in result.dropped_tasks] == ["Morning walk"]


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


def test_rag_pipeline_ingests_retrieval_records_when_present():
    retriever = RecordingRetriever()
    pipeline = RAGPipeline(retriever=retriever, llm_client=ValidClient())
    request = make_request()

    pipeline.run(request)

    assert retriever.ingested_records == request.retrieval_records


def test_rag_pipeline_retrieves_context_for_each_pet():
    retriever = RecordingRetriever()
    pipeline = RAGPipeline(retriever=retriever, llm_client=ValidClient())
    request = ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=60,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[TaskInput(title="Medication", duration_minutes=10, priority="high")],
            ),
            PetInput(
                name="Whiskers",
                species="Cat",
                age=5,
                tasks=[TaskInput(title="Play", duration_minutes=10, priority="low")],
            ),
        ],
    )

    pipeline.run(request)

    assert [call[0] for call in retriever.retrieve_calls] == ["Buddy", "Whiskers"]
    assert all(call[2] == 4 for call in retriever.retrieve_calls)


def test_build_generation_prompt_contains_request_context_and_schema():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    request = make_request()
    citations_by_pet = {"Buddy": [Citation(record_id="ctx", section="medical_history", snippet="daily meds")]}

    prompt = pipeline._build_generation_prompt(request, citations_by_pet)
    payload = json.loads(prompt)

    assert payload["owner_name"] == "Alex"
    assert payload["pets"][0]["name"] == "Buddy"
    assert payload["retrieval_context"]["Buddy"][0]["record_id"] == "ctx"
    assert "required_output_schema" in payload
    assert "rules" in payload["required_output_schema"]
    assert "citations" in payload["required_output_schema"]["schedule"][0]


def test_log_run_writes_pipeline_telemetry(monkeypatch, tmp_path):
    db_path = tmp_path / "pawpal.db"
    db_module.init_db(db_path)
    monkeypatch.setattr(rag_module, "init_db", lambda: None)
    monkeypatch.setattr(rag_module, "get_connection", lambda: db_module.get_connection(db_path))
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    response = pipeline.run(make_request())

    with db_module.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM pipeline_runs").fetchone()

    assert row["model_provider"] == response.model_provider
    assert row["validation_status"] == response.validation_status
    assert row["retrieval_context_count"] == response.retrieval_context_count


def test_parse_generated_response_dedupes_duplicate_schedule_rows():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    raw = ValidClient().generate_json("sys", "user")
    raw["schedule"].append(dict(raw["schedule"][0]))

    result = pipeline._parse_generated_response(raw, {"Buddy": []})

    assert len(result.schedule) == 1


def test_parse_generated_response_skips_non_dict_schedule_and_guidance_rows():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    raw = ValidClient().generate_json("sys", "user")
    raw["schedule"].append("not a dict")
    raw["guidance"].append(["not", "a", "dict"])

    result = pipeline._parse_generated_response(raw, {"Buddy": []})

    assert [item.title for item in result.schedule] == ["Medication"]
    assert [guide.title for guide in result.guidance] == ["Care tip for Buddy"]


def test_canonical_days_from_day_field_weekday_range_with_daily_suffix():
    from backend.pawpal_backend.services.rag_pipeline import canonical_days_from_day_field

    assert canonical_days_from_day_field("Monday to Friday (as per daily task)") == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    ]
    assert canonical_days_from_day_field("Mon–Fri") == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    ]
    assert canonical_days_from_day_field("on weekdays please") == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    ]


def test_canonical_days_from_day_field_daily_and_every_day_mean_all_week():
    from backend.pawpal_backend.services.legacy_scheduler import DAYS
    from backend.pawpal_backend.services.rag_pipeline import canonical_days_from_day_field

    assert canonical_days_from_day_field("daily") == list(DAYS)
    assert canonical_days_from_day_field("every day") == list(DAYS)
    assert canonical_days_from_day_field("all week") == list(DAYS)


def test_canonical_days_from_weekend():
    from backend.pawpal_backend.services.rag_pipeline import canonical_days_from_day_field

    assert canonical_days_from_day_field("weekend walks") == ["Saturday", "Sunday"]


def test_canonical_days_unknown_passthrough():
    from backend.pawpal_backend.services.rag_pipeline import canonical_days_from_day_field

    assert canonical_days_from_day_field("next quarter") == ["next quarter"]


def test_parse_generated_response_expands_monday_through_friday_to_five_tasks():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    raw = ValidClient().generate_json("sys", "user")
    raw["schedule"][0]["day"] = "Monday to Friday (as per daily task)"
    cites = {"Buddy": []}

    result = pipeline._parse_generated_response(raw, cites)

    assert len(result.schedule) == 5
    assert {item.day for item in result.schedule} == {
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    }
    base = raw["schedule"][0]
    for item in result.schedule:
        assert item.pet == base["pet"]
        assert item.time == base["time"]
        assert item.title == base["title"]
        assert item.duration_minutes == base["duration_minutes"]


def test_parse_generated_response_expands_daily_to_seven_tasks():
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    raw = ValidClient().generate_json("sys", "user")
    raw["schedule"][0]["day"] = "daily"
    cites = {"Buddy": []}

    result = pipeline._parse_generated_response(raw, cites)

    assert len(result.schedule) == 7
    assert {item.day for item in result.schedule} == set(DAYS)


def test_expand_daily_tasks_from_request_fills_sparse_model_days():
    cite = [Citation(record_id="c1", section="medical_history", snippet="context")]
    schedule = [
        ScheduledTask(
            pet="Buddy",
            day="Monday",
            time="08:30",
            title="Medication",
            duration_minutes=10,
            priority="high",
            reason="daily med",
            citations=cite,
        )
    ]
    req = ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=120,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
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
        retrieval_records=[],
    )
    out = expand_daily_tasks_from_request(schedule, req)
    assert len(out) == 7
    assert {item.day for item in out} == set(DAYS)
    assert all(item.time == "08:30" for item in out)


def test_expand_daily_tasks_from_request_already_seven_no_duplicates():
    cite = [Citation(record_id="c1", section="medical_history", snippet="context")]
    schedule = [
        ScheduledTask(
            pet="Buddy",
            day=day,
            time="07:15",
            title="Walk",
            duration_minutes=20,
            priority="medium",
            reason="Exercise",
            citations=cite,
        )
        for day in DAYS
    ]
    req = ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=60,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[TaskInput(title="Walk", duration_minutes=20, frequency="daily", priority="medium")],
            )
        ],
        retrieval_records=[],
    )
    pipeline = RAGPipeline(retriever=FakeRetriever(), llm_client=ValidClient())
    expanded = expand_daily_tasks_from_request(schedule, req)
    deduped = pipeline._reconcile_schedule_items(expanded, [])
    assert len(deduped) == 7


def test_expand_daily_then_validate_daily_budget_overflow():
    from backend.pawpal_backend.services.validator import validate_response

    cite = [Citation(record_id="r1", section="behavior_notes", snippet="Brush coat daily.")]
    schedule = [
        ScheduledTask(
            pet="Zoe",
            day="Wednesday",
            time="10:00",
            title="Brushing",
            duration_minutes=40,
            priority="low",
            reason="coat care",
            citations=cite,
        )
    ]
    req = ScheduleRequest(
        owner_name="Sam",
        available_time_per_day=30,
        pets=[
            PetInput(
                name="Zoe",
                species="cat",
                age=4,
                tasks=[
                    TaskInput(
                        title="Brushing",
                        duration_minutes=40,
                        priority="low",
                        frequency="daily",
                    )
                ],
            )
        ],
        retrieval_records=[],
    )
    expanded = expand_daily_tasks_from_request(schedule, req)
    response = RAGScheduleResponse(
        schedule=expanded,
        guidance=[],
        dropped_tasks=[],
        retrieval_context_count=0,
        model_provider="test",
        validation_status="valid",
        validation_errors=[],
    )
    vr = validate_response(response, req)
    assert vr.valid is False
    assert any("exceeded" in e.lower() for e in vr.errors)


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
