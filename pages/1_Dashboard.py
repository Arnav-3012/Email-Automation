"""Dashboard page — job overview, run controls, and status."""

import sys
import threading
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
st.title("📋 Dashboard")

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
                            st.toast("Job started.")

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
                            config_manager.delete_job(job_id)
                            scheduler.remove_job(job_id)
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
