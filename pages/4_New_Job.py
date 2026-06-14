"""New Job page — build, save, and schedule a reporter job."""

import sys
import datetime
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import config_manager, contact_manager, scheduler

st.set_page_config(page_title="New Job", page_icon="➕", layout="wide")
st.title("New Job")

# ---------------------------------------------------------------------------
# Job details
# ---------------------------------------------------------------------------

st.subheader("Job Details")

job_name = st.text_input("Job Name")
pdf_title = st.text_input("PDF Title")
st.caption("Use {date} for today's date — e.g. Finance Summary – {date}")

# Schedule row
st.subheader("Schedule")

col_freq, col_time, col_days = st.columns(3)

with col_freq:
    frequency = st.selectbox("Frequency", options=["daily", "weekly", "monthly"])

with col_time:
    schedule_time = st.time_input("Schedule Time", value=datetime.time(8, 30))

with col_days:
    day_options = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if frequency in ("daily", "weekly"):
        selected_days = st.multiselect(
            "Days",
            options=day_options,
            default=["mon", "tue", "wed", "thu", "fri"],
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
    selected_contacts = st.multiselect(
        "Recipients",
        options=all_contacts,
        format_func=lambda c: f"{c['name']} ({c['email']})",
    )

st.divider()

# ---------------------------------------------------------------------------
# Save & Schedule
# ---------------------------------------------------------------------------

if st.button("Save & Schedule", type="primary"):
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
        job: dict = {
            "id": f"job_{uuid.uuid4().hex[:6]}",
            "name": job_name.strip(),
            "pdf_title": pdf_title.strip() or job_name.strip(),
            "status": "active",
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
            "last_run": None,
            "last_status": None,
        }

        config_manager.upsert_job(job)
        scheduler.add_or_update_job(job)
        st.session_state["job_draft_dashboards"] = []
        st.success(f"Job '{job['name']}' saved and scheduled.")
        st.rerun()
