from __future__ import annotations

import json
import logging
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
from .ollama_client import OllamaClient
from .retriever import Retriever
from .validator import validate_response

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are PawPal's scheduling assistant. Return strict JSON only. "
    "You must provide citations for each schedule item and guidance item."
)


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

        schedule_items = [
            task
            for item in raw.get("schedule", [])
            if (task := self._parse_schedule_item(item, citations_by_pet)) is not None
        ]
        guidance_items = [
            guide
            for g in raw.get("guidance", [])
            if (guide := self._parse_guidance_item(g, citations_by_pet)) is not None
        ]

        return RAGScheduleResponse(
            schedule=schedule_items,
            guidance=guidance_items,
            dropped_tasks=raw.get("dropped_tasks", []),
            retrieval_context_count=sum(len(v) for v in citations_by_pet.values()),
            model_provider="ollama-qwen2.5",
            validation_status="valid",
            validation_errors=[],
            used_fallback=False,
        )

    def _parse_schedule_item(
        self, item: object, citations_by_pet: dict[str, list[Citation]]
    ) -> ScheduledTask | None:
        if not isinstance(item, dict):
            return None
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
        return ScheduledTask(
            pet=pet_name,
            day=item.get("day", "Monday"),
            time=item.get("time", "08:00"),
            title=item.get("title", "Untitled"),
            duration_minutes=duration_minutes,
            priority=item.get("priority", "medium"),
            reason=item.get("reason", "No reason provided."),
            citations=citations,
        )

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
                "schedule": [
                    {
                        "pet": "string",
                        "day": "Monday|...|Sunday",
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
