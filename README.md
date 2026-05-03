# FetchPlan 

Portfolio readme for FetchPlan — a local-first applied-AI pet-care scheduler with RAG, validation, repair, and a deterministic fallback (FastAPI · Streamlit · Ollama · Chroma · SQLite).

---

## Original project 

- **Original project name:** PawPal
- **Summary:** PawPal was originally created to be a regular schedular that allows an owner to add pets and tasks for each pet. The owner also adds a daily availibility limit in minutes. Once these parameters are satisfied, the scheduler generates a weekly schedule for the owner. Some of the features included dropping tasks automatically when daily time is exceeded and filtering tasks by pet, completion status, and priority. 

---

## Title and summary

**FetchPlan** is a **local-first** applied AI system that turns pet-care context (medications, notes, constraints) into actionable daily schedules. It uses **retrieval-augmented generation (RAG)** so the model’s proposals are grounded in stored context, then **validated** with explicit rules before anything is shown to a user—if generation still fails validation, the system **falls back to a deterministic scheduler** so the demo stays usable.

**Why it matters:** Schedules tied to animal health carry real stakes. That matters especially for **busy people who own pets** and still shoulder daily care—small slips (missed meds, skipped walks) add up when time is tight. Grounding schedules in retrievable records, requiring **citations**, and measuring **violations / recall / fallback frequency** mirrors how cautious teams ship LLM features: helpful when the model behaves, bounded when it does not.

---

## Architecture overview

At a high level, the **Streamlit UI** sends a structured schedule request to a **FastAPI** API. The **RAG pipeline** always runs retrieval against **Chroma** (with lexical fallback when needed), calls **Ollama** for embeddings and completion, parses JSON, validates, optionally **repairs once**, then falls back if needed. **SQLite** persists retrieval rows and pipeline run metadata; **Chroma** holds the vector index. Everything runs on one machine for reproducible demos.

![FetchPlan system architecture](assets/Pet%20Management%20RAGPipeline-2026-05-03-003255.png)

*System diagram: pet management flow, RAG pipeline, validation/repair, and local services (Chroma, SQLite, Ollama).*

---

## Setup instructions

**Prerequisite:** Python 3.10+ recommended; macOS/Linux examples below.

### 1. Repository and virtual environment

```bash
cd applied-ai-system-pawpal
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run all commands (`uvicorn`, `streamlit`, `pytest`) from **`applied-ai-system-pawpal`** so imports like `backend.pawpal_backend` resolve.

### 2. Ollama install and daemon

Install from [ollama.com/download](https://ollama.com/download), or on macOS with Homebrew:

```bash
brew install ollama
```

Start the server (the desktop app can do this; otherwise):

```bash
ollama serve
```

Default endpoint: `http://localhost:11434`. Quick check:

```bash
curl http://localhost:11434/api/tags
```

### 3. Pull models

```bash
ollama pull qwen2.5          # generation (~5 GB)
ollama pull nomic-embed-text # embeddings (~275 MB)
```

If Ollama is down at runtime, the service **logs the failure** and uses the **deterministic fallback**—the app keeps working without RAG-grounded citations.

### 4. Run the backend and frontend

Terminal A — API:

```bash
uvicorn backend.pawpal_backend.api_server:app --reload
```

Terminal B — UI:

```bash
streamlit run frontend/streamlit_app/app.py
```

The UI reads **`FETCHPLAN_API_URL`** (defaults to `http://localhost:8000`).

Optional CLI:

```bash
python scripts/main.py
```

### 5. Reliability benchmark (optional)

```bash
python scripts/eval_runner.py
```

Output includes JSON-style metrics such as **`violation_rate`**, **`citation_coverage_rate`**, **`critical_task_recall`**, **`consistency_rate`**, **`fallback_frequency`**.

### 6. Clean re-run / reset demo data

In the Streamlit **Settings** sidebar, use **Reset demo data** before a fresh graded demo so **SQLite + Chroma** do not accumulate stale retrieval context.

---

## Sample interactions

Screenshots from two Streamlit demo runs:

`Run 1`
![FetchPlan sample interaction — run 1](assets/Run%201.png)
`Run 2`
![FetchPlan sample interaction — run 2](assets/Run%202.png)

---

## Demo recording

Short screen recording of FetchPlan in use:

- **[Watch on Loom](https://www.loom.com/share/a3259c8cd307444db7c988b264430396)**

---

## Design decisions

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| Mandatory RAG on every schedule path | Reduces unsupported claims by forcing retrieval-backed context before generation. | Retrieval quality and ingestion become part of correctness; stale notes hurt relevance. |
| Citations plus strict validation | Makes “show your work” checkable by code (`validator.py`), not vibes. | Parsing/JSON rigidness fights creative model wording; repairs add latency. |
| Single repair, then deterministic fallback | Balances autonomy with a predictable floor for demos and tests. | Fallback schedules ignore nuanced LLM phrasing—they are safe, not optimally personalized. |
| Local stack (Ollama + Chroma + SQLite) | No cloud keys needed; reproducible on one laptop for coursework and portfolios. | Heavier downloads; throughput and model choice limited to local hardware. |

### What went right

The decision to use a local model was more complex than I expected. Using a frontier model like OpenAI was my initial thought since it would have done most of the heavy lifting for me. However, using qwen2.5 through Ollama allowed me to own the entire RAG stack. It is also worth mentioning that sensitive data such as medical records may be involved in a real RAG system. FetchPlan is meant to enforce the best practices for the usage of RAG. Local models protect sensitive data for the users and it's free! One thing I would change if I were to reproduce this project is the runtime. The RAG system has quite a bit of latency when it produces the schedules and it's not ideal for users.

---

## Testing summary

The suite lives under **`test/`** and is run from the repo root:

```bash
python -m pytest test/
```

| Area | What tests exercise (high level) |
|------|-----------------------------------|
| `test_rag_pipeline.py` | Pipeline orchestration, citations, validation/repair paths, edge cases touching generation contracts. |
| `test_validator.py` | Rule-based validation (`CRITICAL_KEYWORDS`, citation/time constraints). |
| `test_retriever.py` | Chroma/embedding wiring and lexical fallback behavior (often with mocks/fixtures). |
| `test_fallback_scheduler.py` | Deterministic schedule construction when AI path is unavailable or rejected. |
| `test_db.py`, `test_reset.py` | SQLite/Chroma persistence and admin reset semantics. |
| `test_api_server.py` | FastAPI `/health`, `/schedule`, `/admin/reset` contracts. |
| `test_ollama_client.py` | Integration expectations around the local model client (where applicable). |
| `test_eval_runner.py` | Reliability runner outputs and regression-friendly metrics snapshot behavior. |
| `test_schemas.py` | Pydantic shapes for requests/responses. |
| `test_pawpal.py` | Original scheduling domain (`legacy_scheduler`): tasks, pets, owners, completeness—continuity from earlier milestones. |

### What repeatedly broke while building

Retrieval snippets had to stay in a usable size range—too little text and the model had nothing concrete to cite; too chunky or fuzzy and schedules drifted. When context was thin or retrieval missed, generation often failed validation or the pipeline leaned on the **deterministic fallback**, so iterating on ingestion, queries, and guardrails mattered as much as the prompt. Separately, nailing the **weekly schedule layout** in Streamlit took many passes before it matched how people skim a calendar. Automated tests around the validator, pipeline, and API contracts reduced regressions whenever those pieces moved.

---

## Reflection

Working with RAG taught me the valuable lesson of **GIGO** (garbage in, garbage out). The quality of the retrieved context is essential for accurate results. LLMs can sometimes be experts at giving the wrong answer when provided with the wrong context. The two tries plus fallback pattern suggests that there is likely an issue from the user's inputs or the RAG system. Unit testing was essential to ensure RAG system compliance and accurate results. Fallback guardrails prevent endless repair loops that may lead to failure. What made this system work is the existence of an already decent scheduler. The UI refactor was a bit challenging due to buggy sections and portions of the interface but ultimately worth the cleaner and more user-friendly look. Lastly, validation and user-input accuracy was enhanced due to easy-to-follow steps on proper use of the RAG system (on the bottom of the web page). 

---

## Quick reference — core Applied-AI features

- Mandatory runtime **RAG** on schedule requests  
- **Citation-bearing** schedules and guidance where the pipeline succeeds  
- **Validation guardrails** (citations present, constraints, critical medication coverage)  
- **Auto-repair** once, then **deterministic fallback**  
- **`scripts/eval_runner.py`** for reproducible violation/citation/recall/consistency metrics  

## Stack

- FastAPI + Uvicorn  
- Streamlit  
- Ollama (`qwen2.5`, `nomic-embed-text`)  
- ChromaDB + SQLite  

Persistent artifacts stay under **`data/`** (SQLite DB and local Chroma data) unless reset.
