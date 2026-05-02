from __future__ import annotations

import os
import re

import requests
import streamlit as st

try:
    from backend.pawpal_backend.services.validator import CRITICAL_KEYWORDS
except ImportError:
    CRITICAL_KEYWORDS = ("med", "medication", "insulin", "pill", "inhaler")

API_BASE = os.environ.get("FETCHPLAN_API_URL", "http://localhost:8000").rstrip("/")

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

        st.markdown("**4. Reading the runtime status**")
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


st.set_page_config(page_title="FetchPlan", page_icon="🐾", layout="centered")
st.title("🐾 FetchPlan")
st.caption("Personalized weekly care schedules for your pets.")
init_state()
render_settings_sidebar()

st.subheader("Your details")
col1, col2 = st.columns(2)
with col1:
    owner_name = st.text_input("Owner name", value="Jordan")
with col2:
    available_time = st.number_input(
        "Available minutes/day", min_value=10, max_value=480, value=120
    )

st.divider()
st.subheader("Add a Pet")
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
        "Special needs (comma-separated)", value="", placeholder="e.g. arthritis, allergies"
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
                    "special_needs": [s.strip() for s in special_needs.split(",") if s.strip()],
                }
            )
            st.session_state.tasks_per_pet[pet_name] = []
            st.session_state.records_per_pet[pet_name] = []
            st.success(f"Added pet {pet_name}.")

if st.session_state.pets:
    st.caption("Pets: " + ", ".join(p["name"] for p in st.session_state.pets))

st.divider()
st.subheader("Add Task")
if st.session_state.pets:
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
                ["daily", "weekly:Monday", "weekly:Wednesday", "weekly:Friday", "once"],
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
else:
    st.info("Add at least one pet before tasks.")

if st.session_state.tasks_per_pet:
    for pet_name, tasks in st.session_state.tasks_per_pet.items():
        if tasks:
            st.markdown(f"**{pet_name} tasks**")
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

st.divider()
st.subheader("Add Retrieval Context")
if st.session_state.pets:
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
            placeholder="Example: Diabetes history, insulin schedule, avoid late-night feeding.",
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
else:
    st.info("Add at least one pet before context records.")

for pet_name, records in st.session_state.records_per_pet.items():
    if records:
        st.markdown(f"**{pet_name} retrieval records**")
        for rec in records:
            st.write(f"- `{rec['section']}`: {rec['content'][:120]}")

st.divider()
st.subheader("Generate Schedule")

if st.button("Generate Schedule"):
    payload = build_payload(owner_name, int(available_time))
    all_tasks = [t for p in payload["pets"] for t in p["tasks"]]
    if not payload["pets"]:
        st.error("Add at least one pet.")
    elif not all_tasks:
        st.error("Add at least one task.")
    else:
        try:
            response = requests.post(f"{API_BASE}/schedule", json=payload, timeout=240)
            response.raise_for_status()
            st.session_state.rag_result = response.json()
            st.success("Schedule generated.")
        except Exception as exc:
            st.error(f"Failed to call API: {exc}")

result = st.session_state.rag_result
if result:
    st.markdown("### Runtime Status")
    c1, c2, c3 = st.columns(3)
    c1.metric("Validation", result.get("validation_status", "unknown"))
    c2.metric("Fallback Used", str(result.get("used_fallback", False)))
    c3.metric("Retrieved Chunks", str(result.get("retrieval_context_count", 0)))

    if result.get("validation_errors"):
        st.warning("Validation issues:\n- " + "\n- ".join(result["validation_errors"]))

    st.markdown("### Schedule")
    schedule_rows = result.get("schedule", [])
    if schedule_rows:
        st.table(
            [
                {
                    "pet": row["pet"],
                    "day": row["day"],
                    "time": row["time"],
                    "task": row["title"],
                    "priority": f"{priority_badge(row['priority'])} {row['priority']}",
                    "duration": row["duration_minutes"],
                }
                for row in schedule_rows
            ]
        )
        for row in schedule_rows:
            with st.expander(f"Why: {row['pet']} - {row['title']} ({row['day']} {row['time']})"):
                st.write(row["reason"])
                st.markdown("**Citations**")
                for cite in row.get("citations", []):
                    st.write(
                        f"- `{cite['record_id']}` [{cite['section']}] {cite['snippet']}"
                    )
    else:
        st.info("No schedule items returned.")

    st.markdown("### Guidance")
    for item in result.get("guidance", []):
        st.markdown(f"**{item['title']}**")
        st.write(item["detail"])
        for cite in item.get("citations", []):
            st.write(f"- `{cite['record_id']}` [{cite['section']}] {cite['snippet']}")

    dropped = result.get("dropped_tasks", [])
    st.markdown("### Dropped Tasks")
    if dropped:
        st.table(dropped)
    else:
        st.success("No dropped tasks.")

st.divider()
render_validation_guidance()
