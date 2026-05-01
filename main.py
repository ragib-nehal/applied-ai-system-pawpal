import argparse
from pprint import pprint

from schemas import PetInput, RetrievalRecordInput, ScheduleRequest, TaskInput
from services.rag_pipeline import RAGPipeline
from services.reset import reset_all


def build_sample_request() -> ScheduleRequest:
    return ScheduleRequest(
        owner_name="Alex",
        available_time_per_day=120,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                energy_level="high",
                special_needs=["Joint support"],
                tasks=[
                    TaskInput(
                        title="Morning Meds",
                        duration_minutes=10,
                        priority="high",
                        frequency="daily",
                        description="Administer joint supplement",
                        preferred_time="08:00",
                    ),
                    TaskInput(
                        title="Morning Walk",
                        duration_minutes=30,
                        priority="high",
                        frequency="daily",
                        description="Exercise",
                        preferred_time="08:30",
                    ),
                ],
            ),
            PetInput(
                name="Whiskers",
                species="Cat",
                age=5,
                energy_level="low",
                tasks=[
                    TaskInput(
                        title="Insulin medication",
                        duration_minutes=10,
                        priority="high",
                        frequency="daily",
                        description="Morning dose",
                        preferred_time="09:15",
                    ),
                    TaskInput(
                        title="Feeding",
                        duration_minutes=20,
                        priority="medium",
                        frequency="daily",
                        description="Wet food",
                        preferred_time="09:30",
                    ),
                ],
            ),
        ],
        retrieval_records=[
            RetrievalRecordInput(
                record_id="buddy-med-1",
                pet_name="Buddy",
                section="medications",
                content="Buddy takes morning joint supplement at 08:00 and should not skip doses.",
            ),
            RetrievalRecordInput(
                record_id="whiskers-med-1",
                pet_name="Whiskers",
                section="medical_history",
                content="Whiskers has diabetes and needs insulin at consistent morning time.",
            ),
        ],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the PawPal RAG pipeline against a sample request.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe local SQLite + Chroma stores before running (destructive, local demo only).",
    )
    args = parser.parse_args()

    if args.reset:
        reset_all()
        print("[reset] Local SQLite + Chroma stores wiped.")

    pipeline = RAGPipeline()
    result = pipeline.run(build_sample_request())
    print("\n=== PawPal RAG Output ===")
    pprint(result.model_dump())
