from __future__ import annotations

import html
import os
import re
from pathlib import Path

import requests
import streamlit as st

try:
    from backend.pawpal_backend.services.validator import CRITICAL_KEYWORDS
except ImportError:
    CRITICAL_KEYWORDS = ("med", "medication", "insulin", "pill", "inhaler")

API_BASE = os.environ.get("FETCHPLAN_API_URL", "http://localhost:8000").rstrip("/")
ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo_v1_calendar_paw.svg"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_SHORT = {
    "Monday": "Mon",
    "Tuesday": "Tue",
    "Wednesday": "Wed",
    "Thursday": "Thu",
    "Friday": "Fri",
    "Saturday": "Sat",
    "Sunday": "Sun",
}

FREQUENCY_OPTIONS = ["daily", *(f"weekly:{day}" for day in DAYS), "once"]

_CRITICAL_TITLE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in CRITICAL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_critical_title(title: str) -> bool:
    return bool(_CRITICAL_TITLE_RE.search(title))


def priority_badge(priority: str) -> str:
    return {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(priority, "⚪")


def render_validation_guidance() -> None:
    keyword_list = ", ".join(f"`{k}`" for k in CRITICAL_KEYWORDS)
    with st.expander("Tips for a better schedule"):
        st.markdown(
            "Your inputs are checked against backend rules **after** the model "
            "generates a schedule. If checks fail twice (initial + one repair "
            "pass), the app falls back to a deterministic scheduler. The tips "
            "below help your inputs pass on the first try."
        )

        st.markdown("**1. Daily time budget**")
        st.markdown(
            "- Total scheduled minutes per weekday must not exceed "
            "**Available minutes/day**.\n"
            "- Many long *daily* tasks add up fast; raise the budget, shorten "
            "tasks, or move some to weekly frequency.\n"
            "- If the limit is exceeded, items may appear under **Dropped Tasks**."
        )

        st.markdown("**2. Critical / medication tasks**")
        st.markdown(
            f"- Task titles containing any of these whole words are treated as "
            f"**critical** and must appear on the generated schedule with the "
            f"same pet name and exact title: {keyword_list}.\n"
            "- Use clear, stable titles (for example, *Insulin injection*) so "
            "the model does not paraphrase them away.\n"
            "- Avoid these words in titles unless the task is truly mandatory."
        )

        st.markdown("**3. Non-empty schedule and citations**")
        st.markdown(
            "- The model must return at least one schedule item, and every "
            "schedule and guidance item must include a citation.\n"
            "- Add **retrieval context** per pet (medical history, "
            "medications, constraints, behavior notes) so the model has real "
            "records to cite. Empty or generic context increases the chance "
            "of malformed or empty outputs."
        )

        st.markdown("**4. Context length & retrieval limits**")
        st.markdown(
            "- Context records are stored in full, but only the **top 4 "
            "retrieved records per pet** are passed to the model on each run.\n"
            "- Each retrieved record contributes only its **first ~220 "
            "characters** as the citation snippet the model sees.\n"
            "- For best results, split long medical histories into multiple "
            "focused records (one topic each) and put the most important "
            "facts (diagnosis, medications, dosages, timings, constraints) "
            "**at the start** of each record so they fit inside the snippet."
        )

        st.markdown("**5. Reading the runtime status**")
        st.markdown(
            "- **valid** — model output passed all checks on the first try.\n"
            "- **repaired** — first attempt failed, the repair pass succeeded.\n"
            "- **fallback** — both attempts failed; a rule-based scheduler "
            "produced the plan. This usually means a budget overflow, a "
            "missing critical task, or missing citations — not always a lack "
            "of context."
        )


def render_settings_sidebar() -> None:
    with st.sidebar:
        st.header("Settings")
        with st.expander("Reset demo data", expanded=False):
            st.caption(
                "Wipes the local SQLite + Chroma stores so demos start "
                "from a clean slate. Destructive and irreversible."
            )
            if st.session_state.get("reset_confirm"):
                st.warning(
                    "This will permanently delete all retrieval records and "
                    "pipeline run history."
                )
                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("Confirm wipe", type="primary", key="reset_confirm_btn"):
                        try:
                            response = requests.post(
                                f"{API_BASE}/admin/reset", timeout=30
                            )
                            response.raise_for_status()
                            st.session_state.rag_result = None
                            st.session_state.reset_confirm = False
                            st.success(
                                response.json().get("message", "Reset complete.")
                            )
                        except Exception as exc:
                            st.session_state.reset_confirm = False
                            st.error(f"Reset failed: {exc}")
                with bc2:
                    if st.button("Cancel", key="reset_cancel_btn"):
                        st.session_state.reset_confirm = False
                        st.rerun()
            else:
                if st.button("Reset demo data", key="reset_arm_btn"):
                    st.session_state.reset_confirm = True
                    st.rerun()


def init_state() -> None:
    st.session_state.setdefault("pets", [])
    st.session_state.setdefault("tasks_per_pet", {})
    st.session_state.setdefault("records_per_pet", {})
    st.session_state.setdefault("rag_result", None)
    st.session_state.setdefault("current_step", 1)
    st.session_state.setdefault("owner_name", "Jordan")
    st.session_state.setdefault("available_time", 120)


def build_payload(owner_name: str, available_time: int) -> dict:
    pets_payload = []
    retrieval_records = []
    for pet in st.session_state.pets:
        pet_name = pet["name"]
        pets_payload.append(
            {
                "name": pet_name,
                "species": pet["species"],
                "age": pet["age"],
                "energy_level": pet["energy_level"],
                "special_needs": pet["special_needs"],
                "tasks": st.session_state.tasks_per_pet.get(pet_name, []),
            }
        )
        for idx, rec in enumerate(st.session_state.records_per_pet.get(pet_name, []), 1):
            retrieval_records.append(
                {
                    "record_id": f"{pet_name.lower()}-{idx}",
                    "pet_name": pet_name,
                    "section": rec["section"],
                    "content": rec["content"],
                }
            )
    return {
        "owner_name": owner_name,
        "available_time_per_day": int(available_time),
        "pets": pets_payload,
        "retrieval_records": retrieval_records,
    }


def _time_sort_key(row: dict) -> tuple[int, int]:
    raw = (row.get("time") or "").strip()
    match = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})", raw)
    if not match:
        return (99, 99)
    return (int(match.group(1)), int(match.group(2)))


def _format_time(value: str | None) -> str:
    """Strip whitespace around the colon so '8 :00' renders as '8:00'."""
    if not value:
        return ""
    return re.sub(r"\s*:\s*", ":", value.strip())


_WEEKLY_BOARD_CSS = """
<style>
.weekly-board-scroll {
    overflow-x: auto;
    overflow-y: visible;
    padding: 4px 2px 14px 2px;
    margin-bottom: 0.5rem;
    -webkit-overflow-scrolling: touch;
}
.weekly-board {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(220px, 240px);
    gap: 12px;
    min-width: 100%;
}
.day-column {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
}
.day-column-header {
    font-weight: 600;
    font-size: 0.95rem;
    padding: 4px 6px 2px 6px;
    color: #1E1B4B;
}
.day-column-empty {
    font-size: 0.85rem;
    color: rgba(30, 27, 75, 0.55);
    padding: 6px;
}
.task-card {
    border: 1px solid rgba(30, 27, 75, 0.12);
    border-radius: 10px;
    padding: 10px 12px;
    background-color: #ffffff;
    box-shadow: 0 1px 2px rgba(30, 27, 75, 0.04);
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.task-title {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-weight: 600;
    font-size: 0.95rem;
    line-height: 1.3;
    color: #1E1B4B;
    word-break: break-word;
    overflow-wrap: anywhere;
}
.task-title .priority-dot {
    flex: 0 0 auto;
}
.task-meta {
    font-size: 0.8rem;
    color: rgba(30, 27, 75, 0.65);
    line-height: 1.35;
    word-break: break-word;
    overflow-wrap: anywhere;
}
.task-details {
    border-top: 1px solid rgba(30, 27, 75, 0.08);
    padding-top: 6px;
    margin-top: 2px;
    font-size: 0.85rem;
}
.task-details > summary {
    cursor: pointer;
    color: #6D28D9;
    font-weight: 500;
    list-style: none;
    user-select: none;
}
.task-details > summary::-webkit-details-marker { display: none; }
.task-details > summary::before {
    content: "\\25B8";
    display: inline-block;
    margin-right: 6px;
    color: #6D28D9;
}
.task-details[open] > summary::before {
    content: "\\25BE";
}
.task-details .reason {
    margin: 6px 0 4px 0;
    color: rgba(30, 27, 75, 0.85);
    word-break: break-word;
    overflow-wrap: anywhere;
}
.task-details .citations-label {
    font-weight: 600;
    margin-top: 6px;
    margin-bottom: 2px;
    color: rgba(30, 27, 75, 0.85);
}
.task-details ul.citations-list {
    margin: 0;
    padding-left: 18px;
    color: rgba(30, 27, 75, 0.75);
}
.task-details ul.citations-list li {
    margin: 2px 0;
    word-break: break-word;
    overflow-wrap: anywhere;
}
.task-details ul.citations-list code {
    background: rgba(139, 92, 246, 0.10);
    padding: 0 4px;
    border-radius: 4px;
    font-size: 0.8rem;
}
</style>
"""


def _render_task_card_html(row: dict) -> str:
    """Render one schedule task as a self-contained HTML card.

    All model/user-supplied strings are HTML-escaped because the parent
    container is rendered with unsafe_allow_html=True.
    """
    title = html.escape(str(row.get("title", "")))
    pet = html.escape(str(row.get("pet", "")))
    time_str = html.escape(_format_time(row.get("time")) or "—")
    duration = html.escape(str(row.get("duration_minutes", "—")))
    badge = priority_badge(row.get("priority", ""))
    reason = html.escape(str(row.get("reason") or "—"))

    citations = row.get("citations") or []
    citation_html = ""
    if citations:
        items = []
        for cite in citations:
            record_id = html.escape(str(cite.get("record_id", "")))
            section = html.escape(str(cite.get("section", "")))
            snippet = html.escape(str(cite.get("snippet", "")))
            items.append(
                f"<li><code>{record_id}</code> [{section}] {snippet}</li>"
            )
        citation_html = (
            '<div class="citations-label">Citations</div>'
            f'<ul class="citations-list">{"".join(items)}</ul>'
        )

    return (
        '<div class="task-card">'
        '<div class="task-title">'
        f'<span class="priority-dot">{badge}</span>'
        f'<span>{title}</span>'
        '</div>'
        f'<div class="task-meta">{pet} &middot; {time_str} &middot; {duration} min</div>'
        '<details class="task-details">'
        '<summary>Why &amp; sources</summary>'
        f'<div class="reason">{reason}</div>'
        f'{citation_html}'
        '</details>'
        '</div>'
    )


def render_weekly_board(rows: list[dict]) -> None:
    by_day: dict[str, list[dict]] = {d: [] for d in DAYS}
    other_rows: list[dict] = []
    for row in rows:
        day = (row.get("day") or "").strip()
        if day in by_day:
            by_day[day].append(row)
        else:
            other_rows.append(row)
    for day in DAYS:
        by_day[day].sort(key=_time_sort_key)

    st.markdown(_WEEKLY_BOARD_CSS, unsafe_allow_html=True)

    day_columns_html = []
    for day in DAYS:
        tasks = by_day[day]
        if tasks:
            cards_html = "".join(_render_task_card_html(row) for row in tasks)
        else:
            cards_html = '<div class="day-column-empty">—</div>'
        day_columns_html.append(
            '<div class="day-column">'
            f'<div class="day-column-header">{html.escape(DAY_SHORT[day])}</div>'
            f'{cards_html}'
            '</div>'
        )

    board_html = (
        '<div class="weekly-board-scroll">'
        '<div class="weekly-board">'
        f'{"".join(day_columns_html)}'
        '</div>'
        '</div>'
    )
    st.markdown(board_html, unsafe_allow_html=True)

    if other_rows:
        st.caption(
            "Items without a recognized day name (Mon-Sun) are listed below:"
        )
        for row in other_rows:
            st.write(
                f"- **{row.get('day', 'unknown')}** {_format_time(row.get('time'))}  "
                f"· {row['pet']} — {row['title']} "
                f"({row['duration_minutes']} min)"
            )


STEP_LABELS = {
    1: "Owner",
    2: "Pet",
    3: "Tasks",
    4: "Context",
    5: "Schedule",
}


def step_is_unlocked(step: int) -> bool:
    if step <= 2:
        return True
    has_pet = bool(st.session_state.pets)
    if step in (3, 4):
        return has_pet
    if step == 5:
        any_task = any(
            tasks for tasks in st.session_state.tasks_per_pet.values()
        )
        return has_pet and any_task
    return True


def render_progress_bar() -> None:
    cols = st.columns(5, gap="small")
    current = st.session_state.current_step
    for idx, (step, label) in enumerate(STEP_LABELS.items()):
        with cols[idx]:
            unlocked = step_is_unlocked(step)
            is_current = step == current
            prefix = "●" if step < current and unlocked else str(step)
            btn_label = f"{prefix}. {label}" + ("" if unlocked else " 🔒")
            if st.button(
                btn_label,
                key=f"step_pill_{step}",
                type=("primary" if is_current else "secondary"),
                disabled=(not unlocked) or is_current,
                use_container_width=True,
            ):
                st.session_state.current_step = step
                st.rerun()


def render_nav_buttons() -> None:
    step = st.session_state.current_step
    back_col, _spacer, next_col = st.columns([1, 3, 1])
    with back_col:
        if st.button(
            "← Back",
            key="wizard_back_btn",
            disabled=(step == 1),
            use_container_width=True,
        ):
            st.session_state.current_step = step - 1
            st.rerun()
    with next_col:
        next_step = step + 1
        can_advance = step < 5 and step_is_unlocked(next_step)
        if st.button(
            "Next →",
            key="wizard_next_btn",
            type="primary",
            disabled=not can_advance,
            use_container_width=True,
        ):
            st.session_state.current_step = next_step
            st.rerun()


def render_header() -> None:
    logo_col, title_col = st.columns([1, 5], vertical_alignment="center")
    with logo_col:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=120)
    with title_col:
        st.markdown(
            "<h1 style='white-space:nowrap;margin:0;'>FetchPlan</h1>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Personalized weekly care schedules for your pets — "
            "grounded in your own retrieval context."
        )


def render_step_owner() -> None:
    st.subheader("Step 1 — Owner profile")
    st.caption(
        "Who is the schedule for, and how many minutes per day are realistic?"
    )
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Owner name", key="owner_name")
    with col2:
        st.number_input(
            "Available minutes/day",
            min_value=10,
            max_value=480,
            key="available_time",
        )


def render_step_pet() -> None:
    st.subheader("Step 2 — Add a pet")
    st.caption("Each pet you add can receive its own tasks and context records.")
    with st.form("add_pet_form", clear_on_submit=True):
        pc1, pc2, pc3, pc4 = st.columns(4)
        with pc1:
            pet_name = st.text_input("Pet name", value="", placeholder="e.g. Mochi")
        with pc2:
            species = st.selectbox("Species", ["dog", "cat", "other"])
        with pc3:
            age = st.number_input("Age", min_value=0, max_value=30, value=2)
        with pc4:
            energy = st.selectbox("Energy", ["low", "medium", "high"], index=1)
        special_needs = st.text_input(
            "Special needs (comma-separated)",
            value="",
            placeholder="e.g. arthritis, allergies",
        )
        add_pet_submitted = st.form_submit_button("Add Pet")

    if add_pet_submitted:
        pet_name = pet_name.strip()
        if not pet_name:
            st.warning("Please enter a pet name.")
        else:
            names = {p["name"] for p in st.session_state.pets}
            if pet_name in names:
                st.warning("Pet already exists.")
            else:
                st.session_state.pets.append(
                    {
                        "name": pet_name,
                        "species": species,
                        "age": int(age),
                        "energy_level": energy,
                        "special_needs": [
                            s.strip() for s in special_needs.split(",") if s.strip()
                        ],
                    }
                )
                st.session_state.tasks_per_pet[pet_name] = []
                st.session_state.records_per_pet[pet_name] = []
                st.success(f"Added pet {pet_name}.")

    if st.session_state.pets:
        st.caption("Pets: " + ", ".join(p["name"] for p in st.session_state.pets))


def render_step_tasks() -> None:
    st.subheader("Step 3 — Add tasks")
    st.caption(
        "Assign care tasks to a specific pet. Frequency, duration and priority "
        "shape how the scheduler fits them into the week."
    )
    if not st.session_state.pets:
        st.info("Add at least one pet before tasks.")
        return

    with st.form("add_task_form", clear_on_submit=True):
        selected_pet = st.selectbox(
            "Assign to pet",
            [p["name"] for p in st.session_state.pets],
            key="task_pet",
        )
        tc1, tc2, tc3, tc4 = st.columns(4)
        with tc1:
            task_title = st.text_input(
                "Task title", value="", placeholder="e.g. Morning walk"
            )
        with tc2:
            duration = st.number_input(
                "Duration (min)", min_value=1, max_value=240, value=20
            )
        with tc3:
            priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)
        with tc4:
            frequency = st.selectbox(
                "Frequency",
                FREQUENCY_OPTIONS,
            )
        preferred_time = st.text_input(
            "Preferred time (HH:MM optional)", value="", placeholder="e.g. 08:00"
        )
        description = st.text_input(
            "Description", value="", placeholder="optional notes"
        )
        st.caption(
            "Tip: titles containing "
            + ", ".join(f"*{k}*" for k in CRITICAL_KEYWORDS)
            + " are treated as **critical** by the validator and must appear "
            "on the schedule for the assigned pet, or the run falls back."
        )
        add_task_submitted = st.form_submit_button("Add Task")

    if add_task_submitted:
        task_title = task_title.strip()
        if not task_title:
            st.warning("Please enter a task title.")
        else:
            st.session_state.tasks_per_pet[selected_pet].append(
                {
                    "title": task_title,
                    "duration_minutes": int(duration),
                    "priority": priority,
                    "frequency": frequency,
                    "description": description,
                    "preferred_time": preferred_time,
                    "completed": False,
                }
            )
            st.success(f"Added task '{task_title}' to {selected_pet}.")

    if st.session_state.tasks_per_pet:
        for pet_name, tasks in st.session_state.tasks_per_pet.items():
            if tasks:
                with st.expander(f"{pet_name} — {len(tasks)} task(s)", expanded=True):
                    st.table(
                        [
                            {
                                "priority": f"{priority_badge(t['priority'])} {t['priority']}",
                                "title": t["title"],
                                "duration": t["duration_minutes"],
                                "frequency": t["frequency"],
                                "time": t["preferred_time"] or "n/a",
                            }
                            for t in tasks
                        ]
                    )


def render_step_context() -> None:
    st.subheader("Step 4 — Add retrieval context")
    st.caption(
        "Context records ground the model with concrete facts to cite. Without "
        "them, the run is much more likely to fall back to the rule-based scheduler."
    )
    if not st.session_state.pets:
        st.info("Add at least one pet before context records.")
        return

    with st.form("add_context_form", clear_on_submit=True):
        context_pet = st.selectbox(
            "Pet for context",
            [p["name"] for p in st.session_state.pets],
            key="context_pet",
        )
        section = st.selectbox(
            "Section",
            ["medical_history", "medications", "constraints", "behavior_notes"],
        )
        content = st.text_area(
            "Context content",
            placeholder=(
                "Example: Diabetes history, insulin schedule, avoid late-night feeding."
            ),
        )
        add_context_submitted = st.form_submit_button("Add Context Record")

    if add_context_submitted:
        if content.strip():
            st.session_state.records_per_pet[context_pet].append(
                {"section": section, "content": content.strip()}
            )
            st.success("Context record added.")
        else:
            st.warning("Context content cannot be empty.")

    for pet_name, records in st.session_state.records_per_pet.items():
        if records:
            with st.expander(
                f"{pet_name} — {len(records)} retrieval record(s)", expanded=False
            ):
                for rec in records:
                    st.write(f"- `{rec['section']}`: {rec['content'][:160]}")


def render_runtime_status(result: dict) -> None:
    st.markdown("#### Runtime status")
    c1, c2, c3 = st.columns(3)
    c1.metric("Validation", result.get("validation_status", "unknown"))
    c2.metric("Fallback used", str(result.get("used_fallback", False)))
    c3.metric("Retrieved chunks", str(result.get("retrieval_context_count", 0)))

    if result.get("validation_errors"):
        st.warning(
            "Validation issues:\n- " + "\n- ".join(result["validation_errors"])
        )


def render_step_generate() -> None:
    st.subheader("Step 5 — Generate & review schedule")
    st.caption(
        "Submit your inputs to the RAG pipeline. The runtime status, weekly "
        "board, guidance and dropped tasks all appear below the button."
    )

    if st.button("Generate Schedule", type="primary"):
        payload = build_payload(
            st.session_state.owner_name, int(st.session_state.available_time)
        )
        all_tasks = [t for p in payload["pets"] for t in p["tasks"]]
        if not payload["pets"]:
            st.error("Add at least one pet.")
        elif not all_tasks:
            st.error("Add at least one task.")
        else:
            with st.status(
                "Running RAG schedule generation...", expanded=True
            ) as status:
                try:
                    st.write("Building request payload...")
                    pet_count = len(payload["pets"])
                    record_count = len(payload.get("retrieval_records", []))
                    st.write(
                        f"Submitting {pet_count} pet(s), {len(all_tasks)} task(s) "
                        f"and {record_count} context record(s) to the backend."
                    )

                    st.write(
                        "Calling RAG pipeline (retrieval + generation + "
                        "validation)..."
                    )
                    response = requests.post(
                        f"{API_BASE}/schedule", json=payload, timeout=240
                    )
                    response.raise_for_status()

                    st.write("Parsing response...")
                    result = response.json()
                    st.session_state.rag_result = result

                    validation_status = result.get("validation_status", "unknown")
                    used_fallback = result.get("used_fallback", False)
                    summary = (
                        f"Schedule generated (status: {validation_status}"
                        f"{', fallback' if used_fallback else ''})."
                    )
                    status.update(label=summary, state="complete", expanded=False)
                except Exception as exc:
                    status.update(
                        label="Schedule generation failed.",
                        state="error",
                        expanded=True,
                    )
                    st.error(f"Failed to call API: {exc}")

    result = st.session_state.rag_result
    if not result:
        return

    render_runtime_status(result)

    st.markdown("#### Weekly schedule")
    schedule_rows = result.get("schedule", [])
    if schedule_rows:
        render_weekly_board(schedule_rows)
    else:
        st.info("No schedule items returned.")

    st.markdown("#### Guidance")
    guidance = result.get("guidance", [])
    if guidance:
        for item in guidance:
            with st.container(border=True):
                st.markdown(f"**{item['title']}**")
                st.write(item["detail"])
                citations = item.get("citations", [])
                if citations:
                    with st.expander("Sources"):
                        for cite in citations:
                            st.write(
                                f"- `{cite['record_id']}` "
                                f"[{cite['section']}] {cite['snippet']}"
                            )
    else:
        st.caption("No guidance items returned.")

    st.markdown("#### Dropped tasks")
    dropped = result.get("dropped_tasks", [])
    if dropped:
        st.table(dropped)
    else:
        st.success("No dropped tasks.")


st.set_page_config(page_title="FetchPlan", page_icon="🐾", layout="centered")
init_state()
render_settings_sidebar()
render_header()

st.divider()
render_progress_bar()
st.divider()

step = st.session_state.current_step
if step == 1:
    render_step_owner()
elif step == 2:
    render_step_pet()
elif step == 3:
    render_step_tasks()
elif step == 4:
    render_step_context()
elif step == 5:
    render_step_generate()

st.divider()
render_nav_buttons()

st.divider()
render_validation_guidance()
