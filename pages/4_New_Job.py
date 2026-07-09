"""New Job page — build, save, and schedule a reporter job."""

import sys
import datetime
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import config_manager, contact_manager, grafana_client, scheduler
from app.auth_manager import get_grafana_credentials, get_user, require_auth
from app.ui_helpers import show_logo

show_logo()
require_auth(page_title="New Job", page_icon="➕")

current_user: str = st.session_state.current_user
current_role: str = (get_user(current_user) or {}).get("role", "user")
is_admin = current_role == "admin"

_creds = get_grafana_credentials(current_user) if current_user else None


# ---------------------------------------------------------------------------
# Display-name pre-fill helpers
# ---------------------------------------------------------------------------

def _initial_panel_name(dash_uid: str, panel_id: int, saved_names: dict) -> str:
    """Pre-fill value for one panel's display-name field."""
    composite_key = f"{dash_uid}_{panel_id}"
    if composite_key in saved_names:
        return saved_names[composite_key]

    cached_titles = st.session_state.get("selected_panel_titles", {})
    if composite_key in cached_titles:
        return cached_titles[composite_key]

    try:
        return grafana_client.get_panel_title(dash_uid, panel_id, credentials=_creds)
    except Exception:
        return f"Panel {panel_id}"


def _initial_dashboard_name(dash_uid: str, fallback_title: str, saved_names: dict) -> str:
    """Pre-fill value for one dashboard's PDF header-name field."""
    if dash_uid in saved_names:
        return saved_names[dash_uid]
    return fallback_title or dash_uid


# ---------------------------------------------------------------------------
# Edit mode detection
# ---------------------------------------------------------------------------

_edit_mode = st.session_state.get("edit_mode", False)
_edit_job_id = st.session_state.get("edit_job_id", "")
_existing_job: dict = {}

if _edit_mode and _edit_job_id:
    _existing_job = config_manager.get_job(_edit_job_id) or {}

    _job_owner = _existing_job.get("created_by", "")
    if _existing_job and not is_admin and _job_owner != current_user:
        st.error("🚫 You can only edit your own jobs.")
        st.stop()

    st.title("✏️ Edit Job")
    if st.session_state.get("edit_initialized_for") != _edit_job_id:
        st.session_state["job_draft_dashboards"] = list(_existing_job.get("dashboards", []))
        st.session_state["email_subject"] = _existing_job.get("email_subject", "")
        st.session_state["email_message"] = _existing_job.get("email_message", "")
        _saved_panel_names = _existing_job.get("panel_names", {})
        _saved_dashboard_names = _existing_job.get("dashboard_names", {})
        for _dash in _existing_job.get("dashboards", []):
            _dash_uid = _dash.get("uid", "")
            st.session_state[f"dash_display_name_{_dash_uid}"] = _initial_dashboard_name(
                _dash_uid, _dash.get("title", _dash_uid), _saved_dashboard_names
            )
            for _pid in _dash.get("panels", []):
                st.session_state[f"panel_name_{_dash_uid}_{_pid}"] = _initial_panel_name(
                    _dash_uid, _pid, _saved_panel_names
                )
        st.session_state["edit_initialized_for"] = _edit_job_id
else:
    st.title("➕ New Job")

# ---------------------------------------------------------------------------
# Job details
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("Job Details")

    _default_job_name = _existing_job.get("name", "") or st.session_state.get(
        "selected_dashboard_title", ""
    )
    job_name = st.text_input("Job Name", value=_default_job_name)
    pdf_title = st.text_input("PDF Title", value=_existing_job.get("pdf_title", ""))
    st.caption("Use {date} for today's date — e.g. Finance Summary – {date}")

    time_range_options = {
        "Last 1 hour":   {"from": "now-1h",  "to": "now"},
        "Last 6 hours":  {"from": "now-6h",  "to": "now"},
        "Last 24 hours": {"from": "now-24h", "to": "now"},
        "Last 7 days":   {"from": "now-7d",  "to": "now"},
        "Last 30 days":  {"from": "now-30d", "to": "now"},
        "Today":         {"from": "now/d",   "to": "now"},
        "This week":     {"from": "now/w",   "to": "now"},
        "This month":    {"from": "now/M",   "to": "now"},
    }

    _saved_range = _existing_job.get("time_range", {"from": "now-24h", "to": "now"})
    _saved_range_label = next(
        (k for k, v in time_range_options.items() if v == _saved_range),
        "Last 24 hours",
    )

    selected_range_label = st.selectbox(
        "Time Range",
        options=list(time_range_options.keys()),
        index=list(time_range_options.keys()).index(_saved_range_label),
        help=(
            "Grafana data time range for this report. "
            "Match this to where your dashboard data lives."
        ),
    )

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

with st.container(border=True):
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

# ---------------------------------------------------------------------------
# Dashboards & Panels
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("Dashboards & Panels")

    draft_dashboards: list = st.session_state.get("job_draft_dashboards", [])
    _saved_dashboard_names = _existing_job.get("dashboard_names", {})

    if not draft_dashboards:
        st.info("No dashboards added yet. Use **Browse Grafana** in the sidebar to pick panels.")
    else:
        for entry in draft_dashboards:
            n = len(entry.get("panels", []))
            dash_uid = entry.get("uid", "")
            with st.container(border=True):
                st.markdown(f"**📊 {entry['title']}**")
                st.caption(f"📁 {entry.get('folder_path', '')} · {n} panel{'s' if n != 1 else ''} selected")

                try:
                    _vars_detected = grafana_client.get_dashboard_variables(dash_uid, credentials=_creds)
                    if _vars_detected:
                        st.info(
                            f"📊 This dashboard has template variables: "
                            f"{', '.join(_vars_detected.keys())}. "
                            f"Current Grafana values will be used automatically in screenshots."
                        )
                except Exception:
                    pass

                dash_name_key = f"dash_display_name_{dash_uid}"
                st.session_state.setdefault(
                    dash_name_key,
                    _initial_dashboard_name(dash_uid, entry.get("title", dash_uid), _saved_dashboard_names),
                )
                st.text_input(
                    "Header name in PDF (pre-filled from Grafana — edit or clear for no header line)",
                    key=dash_name_key,
                )

        if st.button("🗑️ Clear all dashboards"):
            st.session_state["job_draft_dashboards"] = []
            st.rerun()

# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.subheader("Recipients")

    all_contacts = contact_manager.get_all()

    if not all_contacts:
        st.info("No contacts found. Add recipients in the **Contacts** page first.")
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

# ---------------------------------------------------------------------------
# Email Options
# ---------------------------------------------------------------------------

with st.container(border=True):
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

# ---------------------------------------------------------------------------
# Panel Display Names
# ---------------------------------------------------------------------------

_saved_panel_names = _existing_job.get("panel_names", {})

if draft_dashboards:
    with st.container(border=True):
        st.subheader("Panel Display Names")
        st.caption(
            "Pre-filled from Grafana — as they'll appear in the email and PDF. "
            "Edit any of them, or clear one for no header label on that panel."
        )
        for dash_entry in draft_dashboards:
            panel_ids = dash_entry.get("panels", [])
            dash_uid = dash_entry.get("uid", "")
            if panel_ids:
                st.markdown(f"*📊 {dash_entry['title']}*")
                for panel_id in panel_ids:
                    unique_key = f"panel_name_{dash_uid}_{panel_id}"
                    st.session_state.setdefault(
                        unique_key, _initial_panel_name(dash_uid, panel_id, _saved_panel_names)
                    )
                    st.text_input(
                        f"Panel {panel_id} display name",
                        key=unique_key,
                    )

st.divider()

# ---------------------------------------------------------------------------
# Save & Schedule / Update & Reschedule
# ---------------------------------------------------------------------------

save_label = "💾 Update & Reschedule" if _edit_mode else "💾 Save & Schedule"

if st.button(save_label, type="primary", use_container_width=True):
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
        dashboard_names: dict = {}
        for dash_entry in draft_dashboards:
            dash_uid = dash_entry.get("uid", "")
            dashboard_names[dash_uid] = st.session_state.get(
                f"dash_display_name_{dash_uid}", dash_entry.get("title", dash_uid)
            ).strip()
            for panel_id in dash_entry.get("panels", []):
                unique_key = f"panel_name_{dash_uid}_{panel_id}"
                panel_names[f"{dash_uid}_{panel_id}"] = st.session_state.get(unique_key, "").strip()

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
            "time_range": time_range_options[selected_range_label],
            "schedule": {
                "frequency": frequency,
                "time": schedule_time.strftime("%H:%M"),
                "days": selected_days,
            },
            "email_subject": st.session_state.get("email_subject", "").strip(),
            "email_message": st.session_state.get("email_message", "").strip(),
            "panel_names": panel_names,
            "dashboard_names": dashboard_names,
        }

        if _edit_mode and _edit_job_id:
            job = {**_existing_job, **shared_fields}
        else:
            job = {
                "id": str(uuid.uuid4()),
                "status": "active",
                "last_run": None,
                "last_status": None,
                "created_by": current_user,
                **shared_fields,
            }

        config_manager.upsert_job(job)
        if job.get("status") == "active":
            scheduler.add_or_update_job(job)

        for _key in ("edit_mode", "edit_job_id", "edit_initialized_for"):
            st.session_state.pop(_key, None)

        st.session_state["job_draft_dashboards"] = []
        for key in list(st.session_state.keys()):
            if (
                key in ("email_subject", "email_message")
                or key.startswith("panel_name_")
                or key.startswith("dash_display_name_")
            ):
                del st.session_state[key]

        verb = "updated" if _edit_mode else "saved and scheduled"
        st.success(f"✅ Job '{job['name']}' {verb}.")
        st.rerun()
