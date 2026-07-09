"""Dashboard page — job overview, run controls, and status."""

import json
import sys
import threading
import time
import datetime
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import config_manager, contact_manager, scheduler
from app.auth_manager import get_user, list_users, require_auth
from app.ui_helpers import show_logo
import runner

show_logo()
require_auth(page_title="Dashboard", page_icon="📋")

_title_col, _refresh_col = st.columns([4, 1])
with _title_col:
    st.title("📋 Dashboard")
with _refresh_col:
    st.markdown("")  # vertical spacer to align button with title
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()


def _get_run_progress(events: list[dict]) -> tuple[int, str]:
    """Map the latest log event to a coarse (percent, label) progress estimate."""
    if not events:
        return 5, "⏳ Starting job..."
    msg = events[-1].get("message", "").lower()
    if "no grafana credentials" in msg or "failed" in msg:
        return 100, "❌ Failed"
    if "login" in msg:
        return 10, "🔐 Logging into Grafana..."
    if "fetching dashboard" in msg:
        return 25, "📊 Fetching dashboard data..."
    if "full dashboard" in msg:
        return 35, "📸 Capturing full dashboard..."
    if "panel screenshot" in msg or "screenshot" in msg:
        return 55, "📸 Capturing panel screenshots..."
    if "table panel" in msg or "mysql" in msg or "sql" in msg:
        return 65, "📊 Fetching table data..."
    if "pdf built" in msg:
        return 80, "📄 Building PDF report..."
    if "email sent" in msg:
        return 90, "📧 Sending email..."
    if "completed" in msg:
        return 100, "✅ Complete!"
    return 15, "⏳ Processing..."

current_user: str = st.session_state.current_user
current_role: str = (get_user(current_user) or {}).get("role", "user")
is_admin = current_role == "admin"

jobs = config_manager.get_jobs_for_user(current_user, current_role)

if not is_admin:
    jobs = [j for j in jobs if not j.get("creator_deleted", False)]

if "job_draft_dashboards" not in st.session_state:
    st.session_state["job_draft_dashboards"] = []

# ---------------------------------------------------------------------------
# Metrics row
# ---------------------------------------------------------------------------

today_str = datetime.date.today().isoformat()

active_count = sum(1 for j in jobs if j.get("status") == "active")
total_count = len(jobs)
success_today = sum(
    1 for j in jobs
    if j.get("last_status") == "success"
    and isinstance(j.get("last_run"), str)
    and j["last_run"].startswith(today_str)
)

m1, m2, m3 = st.columns(3)
m1.metric("Active Jobs", active_count)
m2.metric("Total Jobs", total_count)
m3.metric("Successful Today", success_today)

st.divider()

# ---------------------------------------------------------------------------
# Search + status filter
# ---------------------------------------------------------------------------

_search_col, _filter_col = st.columns([3, 1])
with _search_col:
    _search_term = st.text_input(
        "Search", placeholder="Search jobs...", label_visibility="collapsed"
    )
with _filter_col:
    _status_filter = st.selectbox(
        "Filter",
        ["All", "Active", "Paused", "Failed"],
        label_visibility="collapsed",
    )

if _search_term:
    jobs = [j for j in jobs if _search_term.lower() in j.get("name", "").lower()]
if _status_filter == "Active":
    jobs = [j for j in jobs if j.get("status") == "active"]
elif _status_filter == "Paused":
    jobs = [j for j in jobs if j.get("status") == "paused"]
elif _status_filter == "Failed":
    jobs = [j for j in jobs if j.get("last_status") == "failed"]

# Background jobs (e.g. scheduler-triggered) still in progress — keep the
# page refreshing on its own so status updates without a manual click.
if any(j.get("last_status") == "running" for j in jobs) and not any(
    st.session_state.get(f"running_{j.get('id')}") for j in jobs
):
    time.sleep(10)
    st.rerun()

# ---------------------------------------------------------------------------
# Jobs list
# ---------------------------------------------------------------------------

all_users = list_users()
all_usernames = {u["username"] for u in all_users}

if not jobs:
    st.info("No jobs yet. Use **New Job** in the sidebar to create one.")
else:
    for job in jobs:
        job_id = job.get("id")
        if not job_id:
            # Legacy job predating the id field — assign and persist one now
            # so the buttons below (keyed by job_id) work on this and every
            # subsequent render.
            job_id = str(uuid.uuid4())
            job["id"] = job_id
            config_manager.upsert_job(job)
        can_manage = config_manager.can_manage_job(job, current_user, current_role)
        owner = job.get("created_by", "")
        is_orphaned = job.get("creator_deleted", False)
        job_status = job.get("status", "paused")

        # Choose border colour class via container
        with st.container(border=True):
            left, right = st.columns([2, 1.5])

            # ---- Left column ------------------------------------------------
            with left:
                if is_orphaned:
                    st.markdown(
                        f"### ⚠️ {job['name']}"
                    )
                    st.markdown(":orange[**Deleted user's job — paused until reassigned**]")
                else:
                    if job_status == "active":
                        status_badge = "🟢 Active"
                        status_color = "green"
                    else:
                        status_badge = "⏸ Paused"
                        status_color = "orange"

                    st.markdown(f"### {job['name']}")
                    st.markdown(f":{status_color}[**{status_badge}**]")

                dash_count = len(job.get("dashboards", []))
                recip_count = len(job.get("recipient_ids", []))
                sched = job.get("schedule", {})
                freq = sched.get("frequency", "daily")
                time_str = sched.get("time", "")
                days = sched.get("days", [])

                if freq == "monthly":
                    sched_summary = f"monthly at {time_str}"
                elif days:
                    sched_summary = f"{freq} ({', '.join(days)}) at {time_str}"
                else:
                    sched_summary = f"{freq} at {time_str}"

                st.caption(
                    f"📊 {dash_count} dashboard{'s' if dash_count != 1 else ''} · "
                    f"👥 {recip_count} recipient{'s' if recip_count != 1 else ''} · "
                    f"🕐 {sched_summary}"
                )

                if is_admin:
                    if is_orphaned:
                        st.caption(f"👤 Created by: {owner} *(account deleted — reassign to unlock)*")
                    elif owner and owner in all_usernames:
                        st.caption(f"👤 Created by: {owner}")
                    elif owner:
                        st.caption(f"👤 Created by: {owner} (account deleted)")
                    else:
                        st.caption("👤 Created by: — (legacy job, no owner)")

                last_run = job.get("last_run")
                last_status = job.get("last_status")
                if last_run is None:
                    st.markdown("*Never run*")
                else:
                    try:
                        run_dt = datetime.datetime.fromisoformat(last_run)
                        run_label = run_dt.strftime("%d %b %Y %H:%M")
                    except (ValueError, TypeError):
                        run_label = str(last_run)

                    if last_status == "success":
                        st.markdown(f"Last run: {run_label} — :green[✅ success]")
                    elif last_status == "running":
                        st.markdown(f"Last run: {run_label} — :blue[🔄 running...]")
                    else:
                        st.markdown(
                            f"Last run: {run_label} — "
                            f":red[❌ {last_status or 'unknown'}]"
                        )

            # ---- Right column -----------------------------------------------
            with right:
                deny_reason = "" if can_manage else "You can only manage jobs you created."
                orphan_reason = "Reassign this job to a new owner before running or resuming." if is_orphaned else ""

                # Next run shown at the top of the right column
                next_run = scheduler.get_next_run(job_id)
                st.caption(f"⏭ Next run: {next_run}")

                st.markdown("")  # small spacer

                b1, b2 = st.columns(2)
                b3, b4 = st.columns(2)

                with b1:
                    run_blocked = not can_manage or is_orphaned
                    run_tip = orphan_reason or deny_reason
                    if st.button("▶️ Run Now", key=f"run_{job_id}",
                                 use_container_width=True, type="primary",
                                 disabled=run_blocked, help=run_tip):
                        if can_manage and not is_orphaned:
                            threading.Thread(
                                target=runner.run_job,
                                args=(job_id,),
                                daemon=True,
                            ).start()
                            st.session_state[f"running_{job_id}"] = True
                            st.session_state[f"run_poll_count_{job_id}"] = 0
                            st.session_state[f"run_last_run_before_{job_id}"] = job.get("last_run")
                            st.toast("Job started.")
                            st.rerun()

                with b2:
                    if job_status == "active":
                        if st.button("⏸️ Pause", key=f"pause_{job_id}",
                                     use_container_width=True,
                                     disabled=not can_manage, help=deny_reason):
                            if can_manage:
                                config_manager.upsert_job({**job, "status": "paused"})
                                scheduler.remove_job(job_id)
                                st.rerun()
                    else:
                        resume_blocked = not can_manage or is_orphaned
                        resume_tip = orphan_reason or deny_reason
                        if st.button("▶️ Resume", key=f"resume_{job_id}",
                                     use_container_width=True, type="primary",
                                     disabled=resume_blocked, help=resume_tip):
                            if can_manage and not is_orphaned:
                                updated = {**job, "status": "active"}
                                config_manager.upsert_job(updated)
                                scheduler.add_or_update_job(updated)
                                st.rerun()

                with b3:
                    if st.button("✏️ Edit", key=f"edit_{job_id}",
                                 use_container_width=True,
                                 disabled=not can_manage, help=deny_reason):
                        if can_manage:
                            st.session_state["edit_job_id"] = job_id
                            st.session_state["edit_mode"] = True
                            st.switch_page("pages/4_New_Job.py")

                with b4:
                    if st.button("🗑️ Delete", key=f"del_{job_id}",
                                 use_container_width=True,
                                 disabled=not can_manage, help=deny_reason):
                        if can_manage:
                            st.session_state[f"confirm_delete_{job_id}"] = True
                            st.rerun()

                if st.session_state.get(f"confirm_delete_{job_id}", False):
                    st.warning(f"Delete '{job.get('name', '')}'? This cannot be undone.")
                    col_yes, col_no = st.columns(2)
                    with col_yes:
                        if st.button("Yes, Delete", key=f"confirm_yes_{job_id}",
                                     type="primary", use_container_width=True):
                            config_manager.delete_job(job_id)
                            scheduler.remove_job(job_id)
                            from app.auth_manager import log_event as _log_delete
                            _log_delete("job_deleted", current_user, job_id)
                            st.session_state.pop(f"confirm_delete_{job_id}", None)
                            st.success("Job deleted successfully.")
                            time.sleep(1)
                            st.rerun()
                    with col_no:
                        if st.button("Cancel", key=f"confirm_no_{job_id}",
                                     use_container_width=True):
                            st.session_state.pop(f"confirm_delete_{job_id}", None)
                            st.rerun()

                # Admin-only: reassign orphaned jobs OR legacy jobs with no owner.
                show_reassign = is_admin and (is_orphaned or not owner or owner not in all_usernames)
                if show_reassign:
                    active_usernames = sorted(
                        u["username"] for u in all_users
                        if not u.get("creator_deleted", False)
                    )
                    with st.expander("🔄 Reassign owner"):
                        if is_orphaned:
                            st.caption(
                                "Reassigning will re-activate this job and clear the deleted-user lock."
                            )
                        new_owner = st.selectbox(
                            "Assign this job to",
                            options=active_usernames,
                            key=f"reassign_select_{job_id}",
                        )
                        if st.button("Assign", key=f"reassign_btn_{job_id}", type="primary"):
                            config_manager.set_job_owner(job_id, new_owner)
                            if is_orphaned:
                                updated_job = config_manager.get_job(job_id)
                                if updated_job and updated_job.get("status") == "active":
                                    scheduler.add_or_update_job(updated_job)
                                try:
                                    from app.auth_manager import log_event as _log_reassign
                                    _log_reassign("job_reassigned", current_user, f"{job_id} → {new_owner}")
                                except Exception:
                                    pass
                            st.rerun()

            # ---- Live progress + log viewer while this job is running ------
            if st.session_state.get(f"running_{job_id}"):
                _poll_count = st.session_state.get(f"run_poll_count_{job_id}", 0)
                _before_run = st.session_state.get(f"run_last_run_before_{job_id}")
                _fresh_job = config_manager.get_job(job_id) or job
                _log_path = _fresh_job.get("last_log_file", "")

                _prog_bar = st.progress(0, text="⏳ Starting...")
                _log_box = st.empty()

                _events = []
                if _log_path and Path(_log_path).exists():
                    try:
                        with open(_log_path, encoding="utf-8") as f:
                            _events = json.load(f).get("events", [])
                    except Exception:
                        _events = []

                _pct, _label = _get_run_progress(_events)
                _prog_bar.progress(_pct, text=_label)

                if _events:
                    with _log_box.container():
                        st.caption("Live updates:")
                        for _ev in _events[-5:]:
                            _icon = {"success": "✅", "warning": "⚠️", "error": "❌"}.get(
                                _ev.get("type", "info"), "ℹ️"
                            )
                            st.markdown(f"`{_ev.get('time', '')}` {_icon} {_ev.get('message', '')}")

                _finished = (
                    _fresh_job.get("last_run") != _before_run
                    and _fresh_job.get("last_status") in ("success", "failed")
                )

                if _finished:
                    _prog_bar.empty()
                    _log_box.empty()
                    if _fresh_job.get("last_status") == "success":
                        st.success("✅ Job completed successfully!")
                    else:
                        st.error("❌ Job failed. See 'View Last Run Log' below.")
                    st.session_state.pop(f"running_{job_id}", None)
                    st.session_state.pop(f"run_poll_count_{job_id}", None)
                    st.session_state.pop(f"run_last_run_before_{job_id}", None)
                    time.sleep(2)
                    st.rerun()
                else:
                    _next_poll_count = _poll_count + 1
                    st.session_state[f"run_poll_count_{job_id}"] = _next_poll_count
                    if _next_poll_count > 20:
                        # After ~1 minute of tight polling, back off to a
                        # slower cadence so a long report doesn't pin this
                        # session in a fast refresh loop indefinitely.
                        st.warning("⏳ Still running. Auto-refreshing every 10 seconds.")
                        time.sleep(10)
                    else:
                        time.sleep(3)
                    st.rerun()

            # ---- Inline "View Last Run Log" (always available, collapsed) --
            _log_path_for_view = job.get("last_log_file", "")
            with st.expander("📋 View Last Run Log"):
                if not _log_path_for_view or not Path(_log_path_for_view).exists():
                    st.caption("No logs yet. Run the job first.")
                else:
                    try:
                        with open(_log_path_for_view, encoding="utf-8") as f:
                            _view_log = json.load(f)
                        st.caption(
                            f"Started: {_view_log.get('started_at', '')} | "
                            f"Finished: {_view_log.get('finished_at', '') or '—'}"
                        )
                        for _ev in _view_log.get("events", []):
                            _icon = {"success": "✅", "warning": "⚠️", "error": "❌"}.get(
                                _ev.get("type", "info"), "ℹ️"
                            )
                            st.markdown(f"`{_ev.get('time', '')}` {_icon} {_ev.get('message', '')}")
                    except Exception as e:
                        st.caption(f"Could not load log: {e}")
