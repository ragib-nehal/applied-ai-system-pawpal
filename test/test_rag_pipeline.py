import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import Citation, PetInput, RetrievalRecordInput, ScheduleRequest, TaskInput
from services.rag_pipeline import RAGPipeline


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
