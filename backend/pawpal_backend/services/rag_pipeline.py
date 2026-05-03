from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from ..schemas import (
    Citation,
    GuidanceItem,
    RAGScheduleResponse,
    ScheduledTask,
    ScheduleRequest,
)
from .db import get_connection, init_db
from .fallback_scheduler import build_deterministic_fallback
from .legacy_scheduler import DAYS
from .ollama_client import OllamaClient
from .retriever import Retriever
from .validator import (
    _normalize_task_key_part,
    scheduled_task_key,
    scheduled_task_matches_dropped_task,
    validate_response,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are PawPal's scheduling assistant. Return strict JSON only. "
    "You must provide citations for each schedule item and guidance item. "
    "Each schedule item's \"day\" must be exactly one of Monday through Sunday; "
    "for tasks that recur on multiple days, output one JSON object per day "
    "(do not put ranges, commas, or prose in \"day\")."
)


def canonical_days_from_day_field(raw: object) -> list[str]:
    """Map a model-produced day string to canonical weekday names used by the UI and validator.

    Order of checks matters: e.g. \"Monday to Friday (as per daily task)\" must match
    as Mon–Fri before a bare \\bdaily\\b heuristic could apply.
    """
    if raw is None:
        return ["Monday"]
    s = str(raw).strip()
    if not s:
        return ["Monday"]
    lower = s.lower()

    if (
        re.search(r"\bmonday\s*(?:[-–—]|through|to)\s*friday\b", lower)
        or re.search(r"\bmon\s*[-–—]\s*fri\b", lower)
        or re.search(r"\bweekdays?\b", lower)
        or re.search(r"\bbusiness\s+days?\b", lower)
    ):
        return DAYS[:5]

    collapsed = " ".join(lower.split())
    if collapsed in {"daily", "every day", "each day", "all week", "all 7 days", "7 days"}:
        return list(DAYS)

    if re.search(r"\bweekends?\b", lower):
        return ["Saturday", "Sunday"]

    for day in DAYS:
        if lower == day.lower():
            return [day]

    abbrevs = {
        "mon": "Monday",
        "tue": "Tuesday",
        "wed": "Wednesday",
        "thu": "Thursday",
        "thur": "Thursday",
        "fri": "Friday",
        "sat": "Saturday",
        "sun": "Sunday",
    }
    if collapsed in abbrevs:
        return [abbrevs[collapsed]]

    return [s]


def _matching_schedule_rows_for_task(
    rows: list[ScheduledTask], pet_norm: str, title_norm: str
) -> list[ScheduledTask]:
    return [
        s
        for s in rows
        if _normalize_task_key_part(s.pet) == pet_norm and _normalize_task_key_part(s.title) == title_norm
    ]


def _append_missing_daily_days(rows: list[ScheduledTask], template: ScheduledTask, filled_days: set[str]) -> None:
    for day in DAYS:
        if day in filled_days:
            continue
        filled_days.add(day)
        rows.append(
            ScheduledTask(
                pet=template.pet,
                day=day,
                time=template.time,
                title=template.title,
                duration_minutes=template.duration_minutes,
                priority=template.priority,
                reason=template.reason,
                citations=list(template.citations),
            )
        )


def expand_daily_tasks_from_request(
    schedule: list[ScheduledTask], request: ScheduleRequest
) -> list[ScheduledTask]:
    """When the client marked a task as ``daily``, ensure one row per weekday.

    Matches model output rows by normalized pet name and title (same rules as the
    validator). If no row exists for that task yet, skips it so missing critical
    tasks still fail validation downstream.
    """
    out = list(schedule)
    for pet in request.pets:
        pn = _normalize_task_key_part(pet.name)
        for task_input in pet.tasks:
            if task_input.frequency != "daily":
                continue
            tn = _normalize_task_key_part(task_input.title)
            matches = _matching_schedule_rows_for_task(out, pn, tn)
            if not matches:
                continue
            filled_days = {s.day for s in matches}
            _append_missing_daily_days(out, matches[0], filled_days)
    return out


class RAGPipeline:
    def __init__(self, retriever: Retriever | None = None, llm_client: OllamaClient | None = None):
        self.retriever = retriever or Retriever()
        self.llm_client = llm_client or OllamaClient()
        init_db()

    def run(self, request: ScheduleRequest) -> RAGScheduleResponse:
        if request.retrieval_records:
            self.retriever.ingest(request.retrieval_records)

        citations_by_pet: dict[str, list[Citation]] = {}
        for pet in request.pets:
            query = self._build_retrieval_query(pet_name=pet.name, request=request)
            hits = self.retriever.retrieve(pet_name=pet.name, query=query, top_k=4)
            citations_by_pet[pet.name] = hits
            logger.info("retrieval pet=%s hits=%d", pet.name, len(hits))

        user_prompt = self._build_generation_prompt(request, citations_by_pet)
        ai_response = self._try_generate(user_prompt)
        parsed = self._parse_generated_response(ai_response, citations_by_pet)
        parsed.schedule = expand_daily_tasks_from_request(parsed.schedule, request)
        parsed.schedule = self._reconcile_schedule_items(parsed.schedule, parsed.dropped_tasks)

        validation = validate_response(parsed, request)
        if validation.valid:
            parsed.validation_status = "valid"
            parsed.validation_errors = []
            self._log_run(parsed)
            return parsed

        logger.warning("validation_failed errors=%s", validation.errors)
        repair_prompt = self._build_repair_prompt(user_prompt, validation.errors)
        repaired_raw = self._try_generate(repair_prompt)
        repaired = self._parse_generated_response(repaired_raw, citations_by_pet)
        repaired.schedule = expand_daily_tasks_from_request(repaired.schedule, request)
        repaired.schedule = self._reconcile_schedule_items(repaired.schedule, repaired.dropped_tasks)
        repaired_validation = validate_response(repaired, request)
        if repaired_validation.valid:
            repaired.validation_status = "repaired"
            repaired.validation_errors = validation.errors
            self._log_run(repaired)
            return repaired

        fallback = build_deterministic_fallback(
            request=request,
            citations_by_pet=citations_by_pet,
            validation_errors=validation.errors + repaired_validation.errors,
        )
        self._log_run(fallback)
        return fallback

    def _try_generate(self, user_prompt: str) -> dict:
        try:
            return self.llm_client.generate_json(SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            logger.exception("ollama_generation_failed")
            return {"error": str(exc)}

    def _parse_generated_response(
        self, raw: dict, citations_by_pet: dict[str, list[Citation]]
    ) -> RAGScheduleResponse:
        if "schedule" not in raw or not isinstance(raw.get("schedule"), list):
            return RAGScheduleResponse(
                schedule=[],
                guidance=[],
                dropped_tasks=[],
                retrieval_context_count=sum(len(v) for v in citations_by_pet.values()),
                model_provider="ollama-qwen2.5",
                validation_status="fallback",
                validation_errors=["Model output missing schedule array."],
                used_fallback=False,
            )

        schedule_items: list[ScheduledTask] = []
        for entry in raw.get("schedule", []):
            schedule_items.extend(self._parse_schedule_item(entry, citations_by_pet))
        dropped_tasks = [
            task for task in raw.get("dropped_tasks", []) if isinstance(task, dict)
        ]
        schedule_items = self._reconcile_schedule_items(schedule_items, dropped_tasks)
        guidance_items = [
            guide
            for g in raw.get("guidance", [])
            if (guide := self._parse_guidance_item(g, citations_by_pet)) is not None
        ]

        return RAGScheduleResponse(
            schedule=schedule_items,
            guidance=guidance_items,
            dropped_tasks=dropped_tasks,
            retrieval_context_count=sum(len(v) for v in citations_by_pet.values()),
            model_provider="ollama-qwen2.5",
            validation_status="valid",
            validation_errors=[],
            used_fallback=False,
        )

    def _reconcile_schedule_items(
        self, schedule_items: list[ScheduledTask], dropped_tasks: list[dict]
    ) -> list[ScheduledTask]:
        reconciled: list[ScheduledTask] = []
        seen: set[tuple[str, str, str, str, int]] = set()
        for item in schedule_items:
            if any(scheduled_task_matches_dropped_task(item, dropped) for dropped in dropped_tasks):
                continue

            key = scheduled_task_key(item)
            if key in seen:
                continue
            seen.add(key)
            reconciled.append(item)
        return reconciled

    def _parse_schedule_item(
        self, item: object, citations_by_pet: dict[str, list[Citation]]
    ) -> list[ScheduledTask]:
        if not isinstance(item, dict):
            return []
        pet_name = item.get("pet", "Unknown")
        raw_citations = item.get("citations")
        citations = self._build_citations(
            raw_citations if isinstance(raw_citations, list) else [],
            citations_by_pet.get(pet_name, []),
        )
        try:
            duration_minutes = max(int(item.get("duration_minutes", 15)), 1)
        except (TypeError, ValueError):
            duration_minutes = 15
        raw_day = item.get("day", "Monday")
        if isinstance(raw_day, str):
            day_field = raw_day
        else:
            day_field = str(raw_day) if raw_day is not None else "Monday"

        canonical_days = canonical_days_from_day_field(day_field)
        time_val = item.get("time", "08:00")
        title_val = item.get("title", "Untitled")
        priority_val = item.get("priority", "medium")
        reason_val = item.get("reason", "No reason provided.")

        tasks: list[ScheduledTask] = []
        for day in canonical_days:
            tasks.append(
                ScheduledTask(
                    pet=pet_name,
                    day=day,
                    time=time_val,
                    title=title_val,
                    duration_minutes=duration_minutes,
                    priority=priority_val,
                    reason=reason_val,
                    citations=citations,
                )
            )
        return tasks

    def _parse_guidance_item(
        self, g: object, citations_by_pet: dict[str, list[Citation]]
    ) -> GuidanceItem | None:
        if not isinstance(g, dict):
            return None
        raw_title = g.get("title", "")
        safe_title = raw_title if isinstance(raw_title, str) else ""
        pet_name = g.get("pet") or request_pet_from_title(safe_title, citations_by_pet)
        raw_citations = g.get("citations")
        citations = self._build_citations(
            raw_citations if isinstance(raw_citations, list) else [],
            citations_by_pet.get(pet_name, []),
        )
        return GuidanceItem(
            title=safe_title or "General Guidance",
            detail=g.get("detail", ""),
            citations=citations,
        )

    def _build_retrieval_query(self, pet_name: str, request: ScheduleRequest) -> str:
        return (
            f"pet {pet_name} medication timing constraints medical history behavior "
            f"owner time budget {request.available_time_per_day}"
        )

    def _build_generation_prompt(self, request: ScheduleRequest, citations_by_pet: dict[str, list[Citation]]) -> str:
        payload = {
            "owner_name": request.owner_name,
            "available_time_per_day": request.available_time_per_day,
            "pets": [p.model_dump() for p in request.pets],
            "retrieval_context": {
                pet: [c.model_dump() for c in cites] for pet, cites in citations_by_pet.items()
            },
            "required_output_schema": {
                "rules": [
                    'Each schedule item\'s "day" must be exactly one of: Monday, Tuesday, '
                    "Wednesday, Thursday, Friday, Saturday, Sunday.",
                    "For tasks recurring on multiple days, emit one schedule object per day "
                    '(same title/time/duration repeated with different "day" values).',
                    'Never use ranges or free text in "day" (e.g. not "Monday–Friday").',
                ],
                "schedule": [
                    {
                        "pet": "string",
                        "day": "Monday | Tuesday | Wednesday | Thursday | Friday | Saturday | Sunday",
                        "time": "HH:MM",
                        "title": "string",
                        "duration_minutes": 30,
                        "priority": "high|medium|low",
                        "reason": "string",
                        "citations": [
                            {"record_id": "string", "section": "string", "snippet": "string", "score": 0.0}
                        ],
                    }
                ],
                "guidance": [
                    {
                        "pet": "string",
                        "title": "string",
                        "detail": "string",
                        "citations": [
                            {"record_id": "string", "section": "string", "snippet": "string", "score": 0.0}
                        ],
                    }
                ],
                "dropped_tasks": [{"day": "string", "pet": "string", "title": "string"}],
            },
        }
        return json.dumps(payload, indent=2)

    def _build_repair_prompt(self, base_prompt: str, validation_errors: list[str]) -> str:
        return (
            f"{base_prompt}\n\n"
            "REPAIR INSTRUCTIONS:\n"
            "Return valid JSON and fix these errors exactly:\n"
            + "\n".join(f"- {e}" for e in validation_errors)
        )

    def _build_citations(self, raw_citations: list[dict] | None, fallback: list[Citation]) -> list[Citation]:
        citations: list[Citation] = []
        for rc in raw_citations or []:
            if not isinstance(rc, dict):
                continue
            try:
                citations.append(Citation(**rc))
            except Exception:
                continue
        if citations:
            return citations
        if fallback:
            return fallback[:1]
        return [Citation(record_id="missing", section="unknown", snippet="Citation missing from model output.")]

    def _log_run(self, response: RAGScheduleResponse) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO pipeline_runs (
                    created_at, model_provider, used_fallback, validation_status,
                    validation_errors, retrieval_context_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    response.model_provider,
                    1 if response.used_fallback else 0,
                    response.validation_status,
                    json.dumps(response.validation_errors),
                    response.retrieval_context_count,
                ),
            )
            conn.commit()


def request_pet_from_title(title: str, citations_by_pet: dict[str, list[Citation]]) -> str:
    lowered = title.lower()
    for pet_name in citations_by_pet.keys():
        if pet_name.lower() in lowered:
            return pet_name
    return next(iter(citations_by_pet.keys()), "Unknown")
