# PawPal+ RAG

PawPal+ RAG is a local-first applied AI system for pet-care scheduling. It uses Retrieval-Augmented Generation (RAG) to ground schedule decisions in pet context (medical history, medications, constraints, behavior notes), enforces validation guardrails, and falls back safely to deterministic scheduling when needed.

## Core Applied-AI Features

- **Mandatory runtime RAG:** every schedule request runs retrieval + generation.
- **Citation-based outputs:** each schedule and guidance item includes at least one citation.
- **Validation guardrails:** blocks invalid outputs (missing citations, time-limit violations, missing critical medication tasks).
- **Auto-repair and fallback:** failed validation triggers one repair pass; second failure uses deterministic fallback.
- **Reliability metrics:** evaluation runner reports violation rate, citation coverage, critical-task recall, consistency, and fallback frequency.

## Architecture

- `api_server.py`: FastAPI service entrypoint.
- `services/retriever.py`: retrieval layer (Chroma-first, lexical fallback).
- `services/rag_pipeline.py`: orchestration (retrieve -> generate -> validate -> repair/fallback).
- `services/validator.py`: hard-rule validation.
- `services/fallback_scheduler.py`: deterministic scheduler fallback.
- `services/db.py`: SQLite persistence for retrieval records and pipeline run logs.
- `app.py`: Streamlit frontend that calls FastAPI.
- `eval_runner.py`: reproducible reliability benchmark runner.

## Local Stack

- FastAPI + Uvicorn
- Ollama (`qwen2.5` + `nomic-embed-text`)
- ChromaDB (local vector index)
- SQLite file DB (no standalone DB server)
- Streamlit UI

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pull local models:

```bash
ollama pull qwen2.5
ollama pull nomic-embed-text
```

## Run the System

Start API:

```bash
uvicorn api_server:app --reload
```

Start UI (new terminal):

```bash
streamlit run app.py
```

Optional CLI run:

```bash
python main.py
```

## Reliability Evaluation

```bash
python eval_runner.py
```

The script prints a metrics JSON object containing:
- `violation_rate`
- `citation_coverage_rate`
- `critical_task_recall`
- `consistency_rate`
- `fallback_frequency`

## Tests

Run full test suite:

```bash
python -m pytest test/
```

## Notes

- If Ollama is unavailable, the pipeline logs failures and falls back to deterministic scheduling.
- All persistent artifacts are local: `data/pawpal.db` and local Chroma directory.
- The system is designed to be reproducible on a single machine for demo/grading.

## Tests

Run full test suite:

```bash
python -m pytest test/
```

## Notes

- If Ollama is unavailable, the pipeline logs failures and falls back to deterministic scheduling.
- All persistent artifacts are local: `data/pawpal.db` and local Chroma directory.
- The system is designed to be reproducible on a single machine for demo/grading.

