from __future__ import annotations

from collections import defaultdict

from schemas import RAGScheduleResponse, ScheduleRequest, ValidationResult


CRITICAL_KEYWORDS = ("med", "medication", "insulin", "pill", "inhaler")


def validate_response(response: RAGScheduleResponse, request: ScheduleRequest) -> ValidationResult:
    errors: list[str] = []

    if not response.schedule:
        errors.append("Schedule is empty.")

    for item in response.schedule:
        if not item.citations:
            errors.append(f"Missing citation for scheduled task '{item.title}' ({item.pet}).")

    for guide in response.guidance:
        if not guide.citations:
            errors.append(f"Missing citation for guidance item '{guide.title}'.")

    totals_by_day = defaultdict(int)
    for item in response.schedule:
        totals_by_day[item.day] += item.duration_minutes
    for day, total in totals_by_day.items():
        if total > request.available_time_per_day:
            errors.append(
                f"Daily minutes exceeded on {day}: {total} > {request.available_time_per_day}."
            )

    for pet in request.pets:
        critical_titles = [
            t.title for t in pet.tasks if any(k in t.title.lower() for k in CRITICAL_KEYWORDS)
        ]
        for title in critical_titles:
            if not any(s.pet == pet.name and s.title == title for s in response.schedule):
                errors.append(f"Critical task missing from schedule: {pet.name} - {title}.")

    return ValidationResult(valid=not errors, errors=errors)