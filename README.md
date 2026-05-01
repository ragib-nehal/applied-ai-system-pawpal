# PawPal+ RAG

PawPal+ RAG is a local-first applied AI system for pet-care scheduling. It uses Retrieval-Augmented Generation (RAG) to ground schedule decisions in pet context (medical history, medications, constraints, behavior notes), enforces validation guardrails, and falls back safely to deterministic scheduling when needed.

## Core Applied-AI Features

- **Mandatory runtime RAG:** every schedule request runs retrieval + generation.
- **Citation-based outputs:** each schedule and guidance item includes at least one citation.
- **Validation guardrails:** blocks invalid outputs (missing citations, time-limit violations, missing critical medication tasks).
- **Auto-repair and fallback:** failed validation triggers one repair pass; second failure uses deterministic fallback.
- **Reliability metrics:** evaluation runner reports violation rate, citation coverage, critical-task recall, consistency, and fallback frequency.

## Architecture

- `backend/pawpal_backend/api_server.py`: FastAPI service entrypoint.
- `backend/pawpal_backend/services/retriever.py`: retrieval layer (Chroma-first, lexical fallback).
- `backend/pawpal_backend/services/rag_pipeline.py`: orchestration (retrieve -> generate -> validate -> repair/fallback).
- `backend/pawpal_backend/services/validator.py`: hard-rule validation.
- `backend/pawpal_backend/services/fallback_scheduler.py`: deterministic scheduler fallback.
- `backend/pawpal_backend/services/db.py`: SQLite persistence for retrieval records and pipeline run logs.
- `frontend/streamlit_app/app.py`: Streamlit frontend that calls FastAPI.
- `scripts/eval_runner.py`: reproducible reliability benchmark runner.

## Local Stack

- FastAPI + Uvicorn
- Ollama (`qwen2.5` + `nomic-embed-text`)
- ChromaDB (local vector index)
- SQLite file DB (no standalone DB server)
- Streamlit UI

## Setup

### 1. Python environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Install and start Ollama

Install Ollama from [ollama.com/download](https://ollama.com/download), or via Homebrew on macOS:

```bash
brew install ollama
```

Start the Ollama server (the desktop app does this automatically; for CLI-only installs run it in a dedicated terminal):

```bash
ollama serve
```

The server listens on `http://localhost:11434` by default. Verify it's reachable:

```bash
curl http://localhost:11434/api/tags
```

### 3. Pull the required models

```bash
ollama pull qwen2.5          # ~5 GB, used for schedule generation
ollama pull nomic-embed-text # ~275 MB, used for retrieval embeddings
```

> If Ollama is unavailable at runtime, PawPal+ logs the failure and falls back to the deterministic scheduler — the system stays functional but loses RAG-grounded output.

## Run the System

Start API:

```bash
uvicorn backend.pawpal_backend.api_server:app --reload
```

Start UI (new terminal):

```bash
streamlit run frontend/streamlit_app/app.py
```

Optional CLI run:

```bash
python scripts/main.py
```

## Reliability Evaluation

```bash
python scripts/eval_runner.py
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

- All persistent artifacts are local: `data/pawpal.db` and local Chroma directory.
- The system is designed to be reproducible on a single machine for demo/grading.

