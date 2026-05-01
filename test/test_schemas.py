import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pydantic import ValidationError

from backend.pawpal_backend.schemas import (
    Citation,
    GuidanceItem,
    PetInput,
    RAGScheduleResponse,
    ReliabilityMetrics,
    RetrievalRecordInput,
    ScheduleRequest,
    ScheduledTask,
    TaskInput,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------

def test_citation_valid():
    c = Citation(record_id="r1", section="medical_history", snippet="some text", score=0.9)
    assert c.record_id == "r1"
    assert c.score == 0.9


def test_citation_score_optional():
    c = Citation(record_id="r1", section="medications", snippet="text")
    assert c.score is None


def test_citation_snippet_empty_string_rejected():
    with pytest.raises(ValidationError):
        Citation(record_id="r1", section="sec", snippet="")


# ---------------------------------------------------------------------------
# GuidanceItem
# ---------------------------------------------------------------------------

def _make_citation(**kwargs):
    defaults = {"record_id": "r1", "section": "s", "snippet": "snip"}
    defaults.update(kwargs)
    return Citation(**defaults)


def test_guidance_item_valid():
    g = GuidanceItem(title="Tip", detail="Details here", citations=[_make_citation()])
    assert g.title == "Tip"
    assert len(g.citations) == 1


def test_guidance_item_requires_at_least_one_citation():
    with pytest.raises(ValidationError):
        GuidanceItem(title="Tip", detail="Detail", citations=[])


# ---------------------------------------------------------------------------
# ScheduledTask
# ---------------------------------------------------------------------------

def test_scheduled_task_valid():
    task = ScheduledTask(
        pet="Buddy",
        day="Monday",
        time="08:00",
        title="Walk",
        duration_minutes=30,
        priority="high",
        reason="Exercise",
        citations=[_make_citation()],
    )
    assert task.pet == "Buddy"
    assert task.priority == "high"


def test_scheduled_task_zero_duration_rejected():
    with pytest.raises(ValidationError):
        ScheduledTask(
            pet="Buddy",
            day="Monday",
            time="08:00",
            title="Walk",
            duration_minutes=0,
            priority="high",
            reason="Exercise",
            citations=[_make_citation()],
        )


def test_scheduled_task_negative_duration_rejected():
    with pytest.raises(ValidationError):
        ScheduledTask(
            pet="Buddy",
            day="Monday",
            time="08:00",
            title="Walk",
            duration_minutes=-5,
            priority="high",
            reason="Exercise",
            citations=[_make_citation()],
        )


def test_scheduled_task_invalid_priority_rejected():
    with pytest.raises(ValidationError):
        ScheduledTask(
            pet="Buddy",
            day="Monday",
            time="08:00",
            title="Walk",
            duration_minutes=10,
            priority="urgent",  # not a valid Literal
            reason="Exercise",
            citations=[_make_citation()],
        )


def test_scheduled_task_requires_at_least_one_citation():
    with pytest.raises(ValidationError):
        ScheduledTask(
            pet="Buddy",
            day="Monday",
            time="08:00",
            title="Walk",
            duration_minutes=10,
            priority="low",
            reason="Exercise",
            citations=[],
        )


# ---------------------------------------------------------------------------
# TaskInput
# ---------------------------------------------------------------------------

def test_task_input_defaults():
    t = TaskInput(title="Feed", duration_minutes=15)
    assert t.priority == "medium"
    assert t.frequency == "daily"
    assert t.completed is False
    assert t.description == ""
    assert t.preferred_time == ""


def test_task_input_zero_duration_rejected():
    with pytest.raises(ValidationError):
        TaskInput(title="Feed", duration_minutes=0)


def test_task_input_invalid_priority_rejected():
    with pytest.raises(ValidationError):
        TaskInput(title="Feed", duration_minutes=10, priority="critical")


# ---------------------------------------------------------------------------
# PetInput
# ---------------------------------------------------------------------------

def test_pet_input_defaults():
    p = PetInput(name="Mochi", species="cat", age=3)
    assert p.energy_level == "medium"
    assert p.special_needs == []
    assert p.tasks == []


def test_pet_input_with_tasks():
    p = PetInput(
        name="Buddy",
        species="dog",
        age=2,
        tasks=[TaskInput(title="Walk", duration_minutes=20)],
    )
    assert len(p.tasks) == 1


# ---------------------------------------------------------------------------
# RetrievalRecordInput
# ---------------------------------------------------------------------------

def test_retrieval_record_valid():
    r = RetrievalRecordInput(
        record_id="r1",
        pet_name="Buddy",
        section="medications",
        content="Insulin daily",
    )
    assert r.record_id == "r1"


def test_retrieval_record_empty_content_rejected():
    with pytest.raises(ValidationError):
        RetrievalRecordInput(record_id="r1", pet_name="Buddy", section="sec", content="")


# ---------------------------------------------------------------------------
# ScheduleRequest
# ---------------------------------------------------------------------------

def test_schedule_request_valid():
    req = ScheduleRequest(owner_name="Alex", available_time_per_day=120)
    assert req.pets == []
    assert req.retrieval_records == []


def test_schedule_request_zero_time_rejected():
    with pytest.raises(ValidationError):
        ScheduleRequest(owner_name="Alex", available_time_per_day=0)


def test_schedule_request_negative_time_rejected():
    with pytest.raises(ValidationError):
        ScheduleRequest(owner_name="Alex", available_time_per_day=-10)


# ---------------------------------------------------------------------------
# RAGScheduleResponse
# ---------------------------------------------------------------------------

def test_rag_schedule_response_defaults():
    r = RAGScheduleResponse(
        model_provider="test",
        validation_status="valid",
    )
    assert r.schedule == []
    assert r.guidance == []
    assert r.dropped_tasks == []
    assert r.retrieval_context_count == 0
    assert r.used_fallback is False
    assert r.validation_errors == []


def test_rag_schedule_response_invalid_status_rejected():
    with pytest.raises(ValidationError):
        RAGScheduleResponse(
            model_provider="test",
            validation_status="unknown_status",
        )


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

def test_validation_result_valid():
    vr = ValidationResult(valid=True)
    assert vr.errors == []


def test_validation_result_with_errors():
    vr = ValidationResult(valid=False, errors=["error one", "error two"])
    assert not vr.valid
    assert len(vr.errors) == 2


# ---------------------------------------------------------------------------
# ReliabilityMetrics
# ---------------------------------------------------------------------------

def test_reliability_metrics_valid():
    m = ReliabilityMetrics(
        total_runs=10,
        violation_rate=0.1,
        citation_coverage_rate=0.9,
        critical_task_recall=1.0,
        consistency_rate=0.8,
        fallback_frequency=0.2,
    )
    assert m.total_runs == 10
    assert m.fallback_frequency == 0.2