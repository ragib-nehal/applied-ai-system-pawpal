import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import (
    Citation,
    PetInput,
    RAGScheduleResponse,
    ScheduledTask,
    ScheduleRequest,
    TaskInput,
)
from services.validator import _is_critical_title, validate_response


def _citation() -> Citation:
    return Citation(
        record_id="rec-1",
        section="medical_history",
        snippet="snippet",
        score=1.0,
    )


def _task(title: str) -> TaskInput:
    return TaskInput(
        title=title,
        duration_minutes=10,
        priority="high",
        frequency="daily",
    )


def _scheduled(pet: str, title: str, day: str = "Monday", duration: int = 10) -> ScheduledTask:
    return ScheduledTask(
        pet=pet,
        day=day,
        time="08:00",
        title=title,
        duration_minutes=duration,
        priority="high",
        reason="r",
        citations=[_citation()],
    )


def _request(task_titles: list[str]) -> ScheduleRequest:
    return ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=120,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[_task(t) for t in task_titles],
            )
        ],
    )


def test_is_critical_title_matches_standalone_med():
    assert _is_critical_title("Med") is True
    assert _is_critical_title("Morning med dose") is True


def test_is_critical_title_does_not_match_meditation():
    assert _is_critical_title("Meditation") is False
    assert _is_critical_title("guided meditation session") is False


def test_is_critical_title_matches_full_keywords():
    assert _is_critical_title("Medication") is True
    assert _is_critical_title("Insulin shot") is True
    assert _is_critical_title("Take pill") is True
    assert _is_critical_title("Inhaler dose") is True


def test_validator_flags_missing_med_task():
    request = _request(["Med"])
    response = RAGScheduleResponse(
        schedule=[_scheduled("Buddy", "Walk")],
        guidance=[],
        model_provider="test",
        validation_status="valid",
    )
    result = validate_response(response, request)
    assert any("Med" in e for e in result.errors)


def test_validator_does_not_flag_meditation_as_critical():
    request = _request(["Meditation"])
    response = RAGScheduleResponse(
        schedule=[_scheduled("Buddy", "Walk")],
        guidance=[],
        model_provider="test",
        validation_status="valid",
    )
    result = validate_response(response, request)
    assert not any("Meditation" in e and "Critical" in e for e in result.errors)
