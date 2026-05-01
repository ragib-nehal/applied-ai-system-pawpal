# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run from the project root.

```bash
# Setup
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# One-time: install Ollama, then pull the local models
ollama pull qwen2.5
ollama pull nomic-embed-text

# Run the FastAPI backend (note the dotted module path)
uvicorn backend.pawpal_backend.api_server:app --reload

# Run the Streamlit UI in a separate terminal (talks to FastAPI)
streamlit run frontend/streamlit_app/app.py

# Standalone CLI smoke-test against the pipeline (no FastAPI, no UI)
python scripts/main.py
python scripts/main.py --reset    # wipe SQLite + Chroma first

# Reliability evaluation harness
python scripts/eval_runner.py
python scripts/eval_runner.py --repeats 5

# Tests
pytest test/
pytest test/test_validator.py::test_name   # single test
```

## Repository layout

```
backend/pawpal_backend/        # FastAPI app + RAG pipeline (importable Python package)
  api_server.py                #   FastAPI endpoints
  schemas.py                   #   Pydantic v2 request/response models
  services/
    rag_pipeline.py            #   Orchestration: retrieve → generate → validate → repair → fallback
    retriever.py               #   Chroma-first retriever, lexical SQLite fallback
    validator.py               #   Hard-rule validation
    fallback_scheduler.py      #   Bridge to legacy_scheduler (deterministic fallback)
    legacy_scheduler.py        #   Pre-RAG deterministic scheduler — invoked when validation fails twice
    ollama_client.py           #   Thin wrapper over POST /api/chat
    db.py                      #   SQLite schema + helpers (data/pawpal.db)
    reset.py                   #   Wipe SQLite + Chroma
frontend/streamlit_app/app.py  # Streamlit UI; calls FastAPI over HTTP
scripts/main.py                # CLI runner (sample request → pipeline)
scripts/eval_runner.py         # Reliability metrics harness
data/                          # Local artifacts: pawpal.db, chroma/
test/                          # Tests at project root; insert ".." into sys.path then import backend.pawpal_backend.*
```

### Import conventions

- **Inside the `backend.pawpal_backend` package:** relative imports (`from ..schemas import ...`, `from .db import ...`).
- **From `scripts/`, `frontend/`, `test/`:** absolute imports rooted at the project (`from backend.pawpal_backend.schemas import ...`). Tests prepend `..` to `sys.path` so they work whether pytest is invoked from the root or from `test/`.
- `DEFAULT_DB_PATH` and `DEFAULT_CHROMA_DIR` resolve via `Path(__file__).resolve().parents[3]` to keep `data/` at the project root regardless of import path. Don't move those files without updating the `parents[3]` count.

## Architecture

PawPal+ is a local-first RAG system for pet-care scheduling. Runtime path: **Streamlit UI → FastAPI → RAG pipeline → Ollama LLM + Chroma + SQLite**, with a deterministic fallback scheduler when the LLM output fails validation.

### Entry points

- `backend/pawpal_backend/api_server.py` — FastAPI app. Endpoints: `GET /health`, `POST /schedule` (runs the pipeline), `POST /admin/reset` (wipes SQLite + Chroma and rebuilds the pipeline singleton). The pipeline is a module-level singleton; `/admin/reset` reassigns `pipeline` after `reset_all()`.
- `frontend/streamlit_app/app.py` — Streamlit UI. Stateless w.r.t. the backend: builds a JSON payload from `st.session_state` and POSTs to the FastAPI base URL the user enters in the input box.
- `scripts/main.py` — constructs a sample `ScheduleRequest` and runs `RAGPipeline` directly (no FastAPI). `--reset` wipes local stores first.
- `scripts/eval_runner.py` — runs predefined scenarios `repeats` times, computes `ReliabilityMetrics` (violation_rate, citation_coverage_rate, critical_task_recall, consistency_rate, fallback_frequency), prints JSON.

### Schemas (`backend/pawpal_backend/schemas.py`)

Pydantic v2. Key types:
- Inputs: `ScheduleRequest` → `PetInput` → `TaskInput`, plus `RetrievalRecordInput` for context to embed.
- Outputs: `RAGScheduleResponse` containing `ScheduledTask[]`, `GuidanceItem[]`, `dropped_tasks`, retrieval count, `model_provider`, `validation_status` (`"valid" | "repaired" | "fallback"`), `validation_errors`, `used_fallback`.
- `ScheduledTask` and `GuidanceItem` declare `citations: ... Field(min_length=1)` — Pydantic itself rejects empty-citation outputs at construction time.

### RAG pipeline (`services/rag_pipeline.py`)

`RAGPipeline.run(request)`:
1. **Ingest** any `retrieval_records` from the request via `Retriever.ingest` (writes both SQLite and Chroma).
2. **Retrieve** per pet — `Retriever.retrieve(pet_name, query, top_k=4)` returns `Citation[]`. The result `citations_by_pet` is what the pipeline uses as the canonical pool of citations to fall back to when the LLM provides bad/empty ones.
3. **Generate** — calls `OllamaClient.generate_json` with `SYSTEM_PROMPT` plus a JSON payload containing the request, retrieval context per pet, and the required output schema. Uses Ollama `format: "json"`.
4. **Parse** model output back into `RAGScheduleResponse`. `_build_citations` accepts any `Citation`-shaped dicts the model returns; if none parse, it substitutes the first retrieved citation for that pet, or a `"missing"` placeholder.
5. **Validate** with `validate_response`. If valid → log run → return.
6. **Repair** — on failure, append the validation errors to the prompt and retry once. If the repair passes validation, return with `validation_status="repaired"` and `validation_errors` set to the **original** failure list (kept around for telemetry).
7. **Fallback** — if repair also fails, call `build_deterministic_fallback`. The combined `validation.errors + repaired_validation.errors` are attached for diagnostics.
8. Every run logs to the `pipeline_runs` table via `_log_run`.

If `OllamaClient.generate_json` raises, `_try_generate` returns `{"error": ...}`, `_parse_generated_response` returns an empty schedule with `validation_status="fallback"`, validation fails on the empty schedule, and the fallback engages. This is the intended "Ollama unreachable" path.

### Validation rules (`services/validator.py`)

Hard rules — any violation triggers repair → fallback:
- Schedule must be non-empty.
- Every `ScheduledTask` and `GuidanceItem` must have at least one citation.
- Sum of `duration_minutes` per day (across all pets) must not exceed `request.available_time_per_day`.
- Every "critical" task — title matches `\b(med|medication|insulin|pill|inhaler)\b`, case-insensitive — from the request must appear in the schedule for the same pet.

### Retrieval (`services/retriever.py`)

Chroma-first with lexical fallback. Both branches are wrapped in try/except — if `chromadb` isn't installed, the dir doesn't exist, or Ollama embeddings fail, the retriever silently falls back to a SQLite lexical scan (term-overlap count). Chroma collection: `pawpal_pet_context`, persisted at `data/chroma/`. Filter: `where={"pet_name": pet_name}`.

### Persistence (`services/db.py`, `services/reset.py`)

SQLite at `data/pawpal.db`. Two tables, both auto-created by `init_db`:
- `retrieval_records (record_id PK, pet_name, section, content)` — upserted on `record_id`.
- `pipeline_runs (id, created_at, model_provider, used_fallback, validation_status, validation_errors, retrieval_context_count)`.

`reset_all()` deletes the SQLite file (+ wal/shm) and rmtree's `data/chroma`. Surfaced via `python scripts/main.py --reset`, `POST /admin/reset`, and the Streamlit "Danger zone" expander.

### LLM client (`services/ollama_client.py`)

Thin wrapper over `POST /api/chat` on `http://localhost:11434` with `format: "json"`, `stream: false`. Defaults: `model="qwen2.5"`, 180 s timeout. Raises on HTTP errors; the pipeline catches and treats as a generation failure (see "RAG pipeline" step 7-8 chain above).

### Deterministic fallback (`services/fallback_scheduler.py`)

Bridges the new pipeline to the legacy `legacy_scheduler.py` scheduler:
- Builds `Owner` / `Pet` / `Task` from the request, runs `OwnerScheduler.generate_consolidated_schedule()` which greedily fits tasks across days respecting `available_time_per_day`.
- Converts the output back into `RAGScheduleResponse` with `model_provider="deterministic-fallback"`, `validation_status="fallback"`, `used_fallback=True`. Citations come from `citations_by_pet` (first hit per pet) or a `fallback-none` placeholder.

### Legacy module (`services/legacy_scheduler.py`)

Original pre-RAG scheduler. **Still load-bearing** as the fallback engine — do not delete. Lives in `backend/pawpal_backend/services/` next to its only Python consumer, `fallback_scheduler.py`, which imports it via `from .legacy_scheduler import Owner, OwnerScheduler, Pet, Task`. Tests import it via `from backend.pawpal_backend.services.legacy_scheduler import ...`.

It also contains a tracked "Tier B" cleanup backlog of soft-deactivated methods (raise `NotImplementedError`) that are referenced by `docs/Mermaid.js`. Read the header comment in the file before removing any of them: `docs/Mermaid.js` must be updated in the same change.

### Tests (`test/`)

One `test_*.py` per service plus `test_pawpal.py` for the legacy scheduler and `test_eval_runner.py` for the metrics harness. Each test file prepends `..` to `sys.path` and imports via `backend.pawpal_backend.*` — so tests run identically whether pytest is invoked from the project root or from `test/`. Ollama is stubbed in pipeline tests with a fake `OllamaClient`; no live Ollama needed for `pytest test/`.

## Conventions

- `from __future__ import annotations` at the top of new modules (matches the rest of the codebase).
- Pydantic v2 (`model_dump`, `model_copy`, `Field(min_length=...)`).
- Citations are **mandatory** outputs, not best-effort. Empty citations get rejected by the schema itself; that's how the validation/fallback chain stays honest. Don't disable it.
- Keep `data/pawpal.db` and `data/chroma/` out of git. Regenerate via `init_db()` (auto on pipeline construction) or `reset_all()`.
