from __future__ import annotations

from fastapi import FastAPI

from .schemas import RAGScheduleResponse, ScheduleRequest
from .services.rag_pipeline import RAGPipeline
from .services.reset import reset_all

app = FastAPI(title="PawPal RAG API", version="0.1.0")
pipeline = RAGPipeline()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/schedule", response_model=RAGScheduleResponse)
def create_schedule(payload: ScheduleRequest) -> RAGScheduleResponse:
    return pipeline.run(payload)


@app.post("/admin/reset")
def admin_reset() -> dict:
    global pipeline
    reset_all()
    pipeline = RAGPipeline()
    return {"status": "ok", "message": "Local SQLite + Chroma stores wiped."}
