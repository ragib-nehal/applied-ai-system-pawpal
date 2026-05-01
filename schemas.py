from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    record_id: str
    section: str
    snippet: str = Field(min_length=1)
    score: float | None = None


class GuidanceItem(BaseModel):
    title: str
    detail: str
    citations: list[Citation] = Field(default_factory=list, min_length=1)


class ScheduledTask(BaseModel):
    pet: str
    day: str
    time: str
    title: str
    duration_minutes: int = Field(gt=0)
    priority: Literal["high", "medium", "low"]
    reason: str
    citations: list[Citation] = Field(default_factory=list, min_length=1)


class RAGScheduleResponse(BaseModel):
    schedule: list[ScheduledTask] = Field(default_factory=list)
    guidance: list[GuidanceItem] = Field(default_factory=list)
    dropped_tasks: list[dict] = Field(default_factory=list)
    retrieval_context_count: int = 0
    model_provider: str
    validation_status: Literal["valid", "repaired", "fallback"]
    validation_errors: list[str] = Field(default_factory=list)
    used_fallback: bool = False


class TaskInput(BaseModel):
    title: str
    duration_minutes: int = Field(gt=0)
    priority: Literal["high", "medium", "low"] = "medium"
    frequency: str = "daily"
    description: str = ""
    preferred_time: str = ""
    completed: bool = False


class PetInput(BaseModel):
    name: str
    species: str
    age: int
    energy_level: str = "medium"
    special_needs: list[str] = Field(default_factory=list)
    tasks: list[TaskInput] = Field(default_factory=list)


class RetrievalRecordInput(BaseModel):
    record_id: str
    pet_name: str
    section: str
    content: str = Field(min_length=1)


class ScheduleRequest(BaseModel):
    owner_name: str
    available_time_per_day: int = Field(gt=0)
    pets: list[PetInput] = Field(default_factory=list)
    retrieval_records: list[RetrievalRecordInput] = Field(default_factory=list)


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class ReliabilityMetrics(BaseModel):
    total_runs: int
    violation_rate: float
    citation_coverage_rate: float
    critical_task_recall: float
    consistency_rate: float
    fallback_frequency: float