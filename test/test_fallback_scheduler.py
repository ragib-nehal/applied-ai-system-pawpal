import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pawpal_backend.schemas import Citation, PetInput, ScheduleRequest, TaskInput
from backend.pawpal_backend.services.fallback_scheduler import build_deterministic_fallback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cite(record_id="r1"):
    return Citation(record_id=record_id, section="medical_history", snippet="context snippet")


def _request(available_time=120, pets=None):
    pets = pets or [
        PetInput(
            name="Buddy",
            species="Dog",
            age=3,
            energy_level="high",
            tasks=[
                TaskInput(title="Morning Walk", duration_minutes=30, priority="high", frequency="daily"),
                TaskInput(title="Medication", duration_minutes=10, priority="high", frequency="daily"),
            ],
        )
    ]
    return ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=available_time,
        pets=pets,
    )


# ---------------------------------------------------------------------------
# Return type and flags
# ---------------------------------------------------------------------------

def test_returns_rag_schedule_response():
    from backend.pawpal_backend.schemas import RAGScheduleResponse
    request = _request()
    citations_by_pet = {"Buddy": [_cite()]}
    result = build_deterministic_fallback(request, citations_by_pet, validation_errors=[])
    assert isinstance(result, RAGScheduleResponse)


def test_used_fallback_is_true():
    request = _request()
    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])
    assert result.used_fallback is True


def test_validation_status_is_fallback():
    request = _request()
    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])
    assert result.validation_status == "fallback"


def test_model_provider_is_deterministic_fallback():
    request = _request()
    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])
    assert result.model_provider == "deterministic-fallback"


def test_validation_errors_are_preserved():
    request = _request()
    errors = ["Error one", "Error two"]
    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, errors)
    assert result.validation_errors == errors


# ---------------------------------------------------------------------------
# Schedule items
# ---------------------------------------------------------------------------

def test_schedule_contains_items_for_daily_tasks():
    request = _request()
    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])
    # Daily tasks should appear on multiple days
    assert len(result.schedule) > 0


def test_schedule_items_reference_correct_pet():
    request = _request()
    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])
    for item in result.schedule:
        assert item.pet == "Buddy"


def test_schedule_items_have_citations():
    request = _request()
    result = build_deterministic_fallback(request, {"Buddy": [_cite("r1")]}, [])
    for item in result.schedule:
        assert len(item.citations) >= 1


def test_schedule_items_use_provided_citations():
    request = _request()
    citations_by_pet = {"Buddy": [_cite("buddy-med-1")]}
    result = build_deterministic_fallback(request, citations_by_pet, [])
    for item in result.schedule:
        assert item.citations[0].record_id == "buddy-med-1"


def test_schedule_falls_back_citation_when_none_provided():
    request = _request()
    # Pass empty citations for Buddy
    result = build_deterministic_fallback(request, {}, [])
    for item in result.schedule:
        assert item.citations[0].record_id == "fallback-none"


def test_schedule_item_reason_mentions_fallback():
    request = _request()
    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])
    for item in result.schedule:
        assert "fallback" in item.reason.lower()


# ---------------------------------------------------------------------------
# Guidance
# ---------------------------------------------------------------------------

def test_guidance_has_one_item_per_pet():
    request = _request()
    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])
    assert len(result.guidance) == 1
    assert result.guidance[0].title == "Care guidance for Buddy"


def test_guidance_has_citations():
    request = _request()
    result = build_deterministic_fallback(request, {"Buddy": [_cite("r1")]}, [])
    assert result.guidance[0].citations[0].record_id == "r1"


def test_guidance_falls_back_citation_when_none_for_pet():
    request = _request()
    result = build_deterministic_fallback(request, {}, [])
    assert result.guidance[0].citations[0].record_id == "fallback-none"


# ---------------------------------------------------------------------------
# Multi-pet request
# ---------------------------------------------------------------------------

def test_multi_pet_schedule_includes_both_pets():
    request = ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=120,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[TaskInput(title="Walk", duration_minutes=30, priority="high", frequency="daily")],
            ),
            PetInput(
                name="Whiskers",
                species="Cat",
                age=5,
                tasks=[TaskInput(title="Feeding", duration_minutes=10, priority="medium", frequency="daily")],
            ),
        ],
    )
    citations_by_pet = {"Buddy": [_cite("b1")], "Whiskers": [_cite("w1")]}
    result = build_deterministic_fallback(request, citations_by_pet, [])
    pet_names_in_schedule = {item.pet for item in result.schedule}
    assert "Buddy" in pet_names_in_schedule
    assert "Whiskers" in pet_names_in_schedule
    assert len(result.guidance) == 2


# ---------------------------------------------------------------------------
# Dropped tasks appear when budget is tight
# ---------------------------------------------------------------------------

def test_dropped_tasks_populated_when_over_budget():
    request = ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=5,  # Very tight budget
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[
                    TaskInput(title="Walk", duration_minutes=30, priority="low", frequency="daily"),
                    TaskInput(title="Medication", duration_minutes=10, priority="high", frequency="daily"),
                ],
            )
        ],
    )
    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])
    assert isinstance(result.dropped_tasks, list)
    assert {task["title"] for task in result.dropped_tasks} == {"Walk", "Medication"}


def test_completed_tasks_are_not_scheduled():
    request = ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=120,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[
                    TaskInput(
                        title="Already Done",
                        duration_minutes=10,
                        priority="high",
                        frequency="daily",
                        completed=True,
                    ),
                    TaskInput(title="Still Due", duration_minutes=10, priority="medium", frequency="daily"),
                ],
            )
        ],
    )

    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])

    scheduled_titles = {item.title for item in result.schedule}
    assert "Already Done" not in scheduled_titles
    assert "Still Due" in scheduled_titles


def test_preferred_times_influence_schedule_order():
    request = ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=120,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[
                    TaskInput(
                        title="Late Care",
                        duration_minutes=10,
                        priority="high",
                        frequency="daily",
                        preferred_time="18:00",
                    ),
                    TaskInput(
                        title="Early Care",
                        duration_minutes=10,
                        priority="low",
                        frequency="daily",
                        preferred_time="07:00",
                    ),
                ],
            )
        ],
    )

    result = build_deterministic_fallback(request, {"Buddy": [_cite()]}, [])
    monday_titles = [item.title for item in result.schedule if item.day == "Monday"]

    assert monday_titles[:2] == ["Early Care", "Late Care"]


def test_multi_pet_schedule_respects_shared_daily_budget():
    request = ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=60,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[TaskInput(title="Walk", duration_minutes=40, priority="high", frequency="daily")],
            ),
            PetInput(
                name="Whiskers",
                species="Cat",
                age=5,
                tasks=[TaskInput(title="Play", duration_minutes=40, priority="low", frequency="daily")],
            ),
        ],
    )

    result = build_deterministic_fallback(
        request,
        {"Buddy": [_cite("b1")], "Whiskers": [_cite("w1")]},
        [],
    )

    monday_total = sum(item.duration_minutes for item in result.schedule if item.day == "Monday")
    monday_dropped = [task for task in result.dropped_tasks if task["day"] == "Monday"]
    assert monday_total <= 60
    assert monday_dropped == [
        {"day": "Monday", "pet": "Whiskers", "title": "Play", "duration_minutes": 40}
    ]


def test_retrieval_context_count_reflects_citations():
    request = _request()
    citations_by_pet = {"Buddy": [_cite("r1"), _cite("r2")]}
    result = build_deterministic_fallback(request, citations_by_pet, [])
    assert result.retrieval_context_count == 2