import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pawpal_backend.schemas import (
    Citation,
    GuidanceItem,
    PetInput,
    RAGScheduleResponse,
    ScheduleRequest,
    ScheduledTask,
    TaskInput,
)
from backend.pawpal_backend.services.validator import validate_response, CRITICAL_KEYWORDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cite(record_id="r1", section="medical_history", snippet="snip"):
    return Citation(record_id=record_id, section=section, snippet=snippet)


def _scheduled_task(
    pet="Buddy",
    day="Monday",
    time="08:00",
    title="Walk",
    duration_minutes=30,
    priority="high",
    reason="reason",
    citations=None,
):
    return ScheduledTask(
        pet=pet,
        day=day,
        time=time,
        title=title,
        duration_minutes=duration_minutes,
        priority=priority,
        reason=reason,
        citations=citations or [_cite()],
    )


def _guidance(title="Tip", detail="detail", citations=None):
    return GuidanceItem(title=title, detail=detail, citations=citations or [_cite()])


def _request(available_time=120, pet_name="Buddy", task_title="Walk"):
    return ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=available_time,
        pets=[
            PetInput(
                name=pet_name,
                species="dog",
                age=3,
                tasks=[TaskInput(title=task_title, duration_minutes=20, priority="high")],
            )
        ],
    )


def _response(schedule=None, guidance=None):
    return RAGScheduleResponse(
        schedule=schedule or [],
        guidance=guidance or [],
        model_provider="test",
        validation_status="valid",
    )


# ---------------------------------------------------------------------------
# Empty schedule
# ---------------------------------------------------------------------------

def test_empty_schedule_is_invalid():
    result = validate_response(_response(schedule=[]), request=_request())
    assert not result.valid
    assert any("empty" in e.lower() for e in result.errors)


def test_non_empty_schedule_does_not_trigger_empty_error():
    response = _response(schedule=[_scheduled_task()])
    request = _request()
    result = validate_response(response, request)
    empty_errors = [e for e in result.errors if "empty" in e.lower()]
    assert not empty_errors


# ---------------------------------------------------------------------------
# Missing citations on scheduled tasks
# ---------------------------------------------------------------------------

# Note: ScheduledTask requires at least one citation via Pydantic (min_length=1),
# so we can only verify that a task with citations passes the citation check.
def test_valid_schedule_has_no_citation_error():
    response = _response(schedule=[_scheduled_task(citations=[_cite()])])
    request = _request()
    result = validate_response(response, request)
    citation_errors = [e for e in result.errors if "citation" in e.lower() and "scheduled" in e.lower()]
    assert not citation_errors


# ---------------------------------------------------------------------------
# Missing citations on guidance items
# ---------------------------------------------------------------------------

def test_valid_guidance_has_no_citation_error():
    response = _response(
        schedule=[_scheduled_task()],
        guidance=[_guidance(citations=[_cite()])],
    )
    result = validate_response(response, request=_request())
    guidance_citation_errors = [
        e for e in result.errors if "guidance" in e.lower() and "citation" in e.lower()
    ]
    assert not guidance_citation_errors


# ---------------------------------------------------------------------------
# Daily time budget
# ---------------------------------------------------------------------------

def test_daily_budget_exceeded_produces_error():
    # Two tasks on same day, total 90 min, budget is 60
    response = _response(
        schedule=[
            _scheduled_task(day="Monday", duration_minutes=50),
            _scheduled_task(day="Monday", duration_minutes=40),
        ]
    )
    request = _request(available_time=60)
    result = validate_response(response, request)
    assert not result.valid
    budget_errors = [e for e in result.errors if "exceeded" in e.lower() or "minutes" in e.lower()]
    assert budget_errors


def test_daily_budget_exactly_at_limit_is_valid():
    # Two tasks on same day, total equals limit exactly
    response = _response(
        schedule=[
            _scheduled_task(day="Monday", duration_minutes=60),
        ]
    )
    request = _request(available_time=60)
    result = validate_response(response, request)
    budget_errors = [e for e in result.errors if "exceeded" in e.lower()]
    assert not budget_errors


def test_tasks_on_different_days_do_not_trigger_budget_error():
    response = _response(
        schedule=[
            _scheduled_task(day="Monday", duration_minutes=50),
            _scheduled_task(day="Tuesday", duration_minutes=50),
        ]
    )
    request = _request(available_time=60)
    result = validate_response(response, request)
    budget_errors = [e for e in result.errors if "exceeded" in e.lower()]
    assert not budget_errors


# ---------------------------------------------------------------------------
# Critical task recall
# ---------------------------------------------------------------------------

def test_critical_task_missing_from_schedule_produces_error():
    # "Medication" contains "med" - it's critical
    request = _request(task_title="Medication")
    response = _response(schedule=[_scheduled_task(pet="Buddy", title="Walk")])
    result = validate_response(response, request)
    assert not result.valid
    critical_errors = [e for e in result.errors if "critical" in e.lower()]
    assert critical_errors


def test_critical_task_present_in_schedule_passes():
    request = _request(task_title="Medication")
    response = _response(
        schedule=[_scheduled_task(pet="Buddy", title="Medication")]
    )
    result = validate_response(response, request)
    critical_errors = [e for e in result.errors if "critical" in e.lower()]
    assert not critical_errors


def test_insulin_is_a_critical_keyword():
    request = _request(task_title="Insulin shot")
    response = _response(schedule=[_scheduled_task(pet="Buddy", title="Walk")])
    result = validate_response(response, request)
    assert not result.valid
    critical_errors = [e for e in result.errors if "critical" in e.lower()]
    assert critical_errors


def test_pill_is_a_critical_keyword():
    request = _request(task_title="Give pill")
    response = _response(schedule=[_scheduled_task(pet="Buddy", title="Walk")])
    result = validate_response(response, request)
    critical_errors = [e for e in result.errors if "critical" in e.lower()]
    assert critical_errors


def test_inhaler_is_a_critical_keyword():
    request = _request(task_title="Inhaler treatment")
    response = _response(schedule=[_scheduled_task(pet="Buddy", title="Walk")])
    result = validate_response(response, request)
    critical_errors = [e for e in result.errors if "critical" in e.lower()]
    assert critical_errors


def test_non_critical_task_not_flagged():
    # "Walk" does not match any CRITICAL_KEYWORDS
    request = _request(task_title="Walk")
    response = _response(schedule=[_scheduled_task(pet="Buddy", title="Bath")])
    result = validate_response(response, request)
    critical_errors = [e for e in result.errors if "critical" in e.lower()]
    assert not critical_errors


# ---------------------------------------------------------------------------
# Fully valid response
# ---------------------------------------------------------------------------

def test_fully_valid_response_returns_no_errors():
    request = ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=120,
        pets=[
            PetInput(
                name="Buddy",
                species="dog",
                age=3,
                tasks=[TaskInput(title="Walk", duration_minutes=20, priority="low")],
            )
        ],
    )
    response = _response(
        schedule=[_scheduled_task(pet="Buddy", title="Walk", day="Monday", duration_minutes=20)],
        guidance=[_guidance()],
    )
    result = validate_response(response, request)
    assert result.valid
    assert result.errors == []


# ---------------------------------------------------------------------------
# Multiple errors can coexist
# ---------------------------------------------------------------------------

def test_multiple_violations_all_reported():
    # Empty schedule + critical task missing
    request = _request(available_time=10, task_title="Medication")
    response = _response(schedule=[])
    result = validate_response(response, request)
    assert not result.valid
    # Should have "Schedule is empty" error
    assert any("empty" in e.lower() for e in result.errors)
    # Critical keyword won't trigger since schedule empty and title "Medication" in request
    # but critical check looks through schedule items (empty), so yes it triggers
    assert any("critical" in e.lower() for e in result.errors)
