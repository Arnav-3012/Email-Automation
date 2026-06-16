"""New Job page — build, save, and schedule a reporter job."""

import sys
import datetime
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import config_manager, contact_manager, scheduler
from app.auth_manager import require_auth

require_auth(page_title="New Job", page_icon="➕")

# ---------------------------------------------------------------------------
# Edit mode detection
# ---------------------------------------------------------------------------

_edit_mode = st.session_state.get("edit_mode", False)
_edit_job_id = st.session_state.get("edit_job_id", "")
_existing_job: dict = {}

if _edit_mode and _edit_job_id:
    _existing_job = config_manager.get_job(_edit_job_id) or {}
    st.title("Edit Job")
    # Initialise form state once per edit session (guard against repeated reruns)
    if st.session_state.get("edit_initialized_for") != _edit_job_id:
        st.session_state["job_draft_dashboards"] = list(_existing_job.get("dashboards", []))
        st.session_state["email_subject"] = _existing_job.get("email_subject", "")
        st.session_state["email_message"] = _existing_job.get("email_message", "")
        _saved_panel_names = _existing_job.get("panel_names", {})
        for _dash in _existing_job.get("dashboards", []):
            _dash_uid = _dash.get("uid", "")
            for _pid in _dash.get("panels", []):
                st.session_state[f"panel_name_{_dash_uid}_{_pid}"] = (
                    _saved_panel_names.get(f"{_dash_uid}_{_pid}", "")
                )
        st.session_state["edit_initialized_for"] = _edit_job_id
else:
    st.title("New Job")

# ---------------------------------------------------------------------------
# Job details
# ---------------------------------------------------------------------------

st.subheader("Job Details")

job_name = st.text_input("Job Name", value=_existing_job.get("name", ""))
pdf_title = st.text_input("PDF Title", value=_existing_job.get("pdf_title", ""))
st.caption("Use {date} for today's date — e.g. Finance Summary – {date}")

# Schedule row
st.subheader("Schedule")

col_freq, col_time, col_days = st.columns(3)

_saved_sched = _existing_job.get("schedule", {})
_freq_options = ["daily", "weekly", "monthly"]
_saved_freq = _saved_sched.get("frequency", "daily")

with col_freq:
    frequency = st.selectbox(
        "Frequency",
        options=_freq_options,
        index=_freq_options.index(_saved_freq) if _saved_freq in _freq_options else 0,
    )

_saved_time_str = _saved_sched.get("time", "08:30")
try:
    _th, _tm = map(int, _saved_time_str.split(":"))
    _saved_time = datetime.time(_th, _tm)
except Exception:
    _saved_time = datetime.time(8, 30)

with col_time:
    schedule_time = st.time_input("Schedule Time", value=_saved_time)

with col_days:
    day_options = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    _saved_days = _saved_sched.get("days", ["mon", "tue", "wed", "thu", "fri"])
    if frequency in ("daily", "weekly"):
        selected_days = st.multiselect(
            "Days",
            options=day_options,
            default=_saved_days if _saved_days else ["mon", "tue", "wed", "thu", "fri"],
        )
    else:
        st.text_input("Days", value="1st of each month", disabled=True)
        selected_days = []

st.divider()

# ---------------------------------------------------------------------------
# Dashboards & Panels
# ---------------------------------------------------------------------------

st.subheader("Dashboards & Panels")

draft_dashboards: list = st.session_state.get("job_draft_dashboards", [])

if not draft_dashboards:
    st.info("No dashboards added yet. Use Browse Grafana in the sidebar to pick panels.")
else:
    for entry in draft_dashboards:
        n = len(entry.get("panels", []))
        st.info(
            f"**{entry['title']}**  \n"
            f"{entry.get('folder_path', '')}  \n"
            f"{n} panel{'s' if n != 1 else ''} selected"
        )

    if st.button("Clear all"):
        st.session_state["job_draft_dashboards"] = []
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------

st.subheader("Recipients")

all_contacts = contact_manager.get_all()

if not all_contacts:
    st.info("No contacts found. Add recipients in the Contacts page first.")
    selected_contacts = []
else:
    _saved_recipient_ids = set(_existing_job.get("recipient_ids", []))
    _default_contacts = [c for c in all_contacts if c["id"] in _saved_recipient_ids]
    selected_contacts = st.multiselect(
        "Recipients",
        options=all_contacts,
        default=_default_contacts,
        format_func=lambda c: f"{c['name']} ({c['email']})",
    )

st.divider()

# ---------------------------------------------------------------------------
# Email Options
# ---------------------------------------------------------------------------

st.subheader("Email Options")

st.session_state.setdefault("email_subject", "")
st.session_state.setdefault("email_message", "")

st.text_input(
    "Custom email subject (optional)",
    placeholder="Leave blank to use: <Job Name> – DD Mon YYYY",
    key="email_subject",
)

st.text_area(
    "Custom message (optional)",
    placeholder="Add a note to appear in the email body...",
    key="email_message",
    height=100,
)

st.caption("Custom panel names (optional) — rename panels as they appear in the email and PDF")

for dash_entry in draft_dashboards:
    panel_ids = dash_entry.get("panels", [])
    dash_uid = dash_entry.get("uid", "")
    if panel_ids:
        st.write(f"*{dash_entry['title']}*")
        for panel_id in panel_ids:
            unique_key = f"panel_name_{dash_uid}_{panel_id}"
            st.session_state.setdefault(unique_key, "")
            st.text_input(
                f"Panel {panel_id} display name",
                placeholder="Leave blank to use Grafana panel title",
                key=unique_key,
            )

st.divider()

# ---------------------------------------------------------------------------
# Save & Schedule / Update & Reschedule
# ---------------------------------------------------------------------------

save_label = "Update & Reschedule" if _edit_mode else "Save & Schedule"

if st.button(save_label, type="primary"):
    errors = []
    if not job_name.strip():
        errors.append("Job name is required.")
    if not draft_dashboards:
        errors.append("Add at least one dashboard.")
    if not selected_contacts:
        errors.append("Select at least one recipient.")

    for err in errors:
        st.error(err)

    if not errors:
        panel_names: dict = {}
        for dash_entry in draft_dashboards:
            dash_uid = dash_entry.get("uid", "")
            for panel_id in dash_entry.get("panels", []):
                unique_key = f"panel_name_{dash_uid}_{panel_id}"
                custom = st.session_state.get(unique_key, "").strip()
                if custom:
                    panel_names[f"{dash_uid}_{panel_id}"] = custom

        shared_fields = {
            "name": job_name.strip(),
            "pdf_title": pdf_title.strip() or job_name.strip(),
            "dashboards": [
                {
                    "uid": d["uid"],
                    "title": d["title"],
                    "folder_path": d.get("folder_path", ""),
                    "panels": d.get("panels", []),
                }
                for d in draft_dashboards
            ],
            "recipient_ids": [c["id"] for c in selected_contacts],
            "schedule": {
                "frequency": frequency,
                "time": schedule_time.strftime("%H:%M"),
                "days": selected_days,
            },
            "email_subject": st.session_state.get("email_subject", "").strip(),
            "email_message": st.session_state.get("email_message", "").strip(),
            "panel_names": panel_names,
        }

        if _edit_mode and _edit_job_id:
            job = {**_existing_job, **shared_fields}
        else:
            job = {
                "id": f"job_{uuid.uuid4().hex[:6]}",
                "status": "active",
                "last_run": None,
                "last_status": None,
                **shared_fields,
            }

        config_manager.upsert_job(job)
        if job.get("status") == "active":
            scheduler.add_or_update_job(job)

        # Clear edit mode session state
        for _key in ("edit_mode", "edit_job_id", "edit_initialized_for"):
            st.session_state.pop(_key, None)

        # Clear draft and email option state
        st.session_state["job_draft_dashboards"] = []
        for key in list(st.session_state.keys()):
            if key in ("email_subject", "email_message") or key.startswith("panel_name_"):
                del st.session_state[key]

        verb = "updated" if _edit_mode else "saved and scheduled"
        st.success(f"Job '{job['name']}' {verb}.")
        st.rerun()
