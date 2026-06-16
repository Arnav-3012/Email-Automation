"""Dashboard page — job overview, run controls, and status."""

import sys
import threading
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import config_manager, contact_manager, scheduler
from app.auth_manager import get_user, list_users, require_auth
import runner

require_auth(page_title="Dashboard", page_icon="📋")
st.title("Dashboard")

# Current user + role drive both which jobs are shown and which action
# buttons are usable below — regular users only ever see/manage their own.
current_user: str = st.session_state.current_user
current_role: str = (get_user(current_user) or {}).get("role", "user")
is_admin = current_role == "admin"

jobs = config_manager.get_jobs_for_user(current_user, current_role)

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

all_usernames = {u["username"] for u in list_users()}

if not jobs:
    st.info("No jobs yet. Use New Job in the sidebar to create one.")
else:
    for job in jobs:
        job_id = job["id"]
        can_manage = config_manager.can_manage_job(job, current_user, current_role)
        owner = job.get("created_by", "")

        with st.container():
            left, right = st.columns([2, 1.5])

            # ---- Left column ------------------------------------------------
            with left:
                status_badge = "🟢" if job.get("status") == "active" else "⏸"
                st.markdown(f"**{status_badge} {job['name']}**")

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
                    f"{dash_count} dashboard{'s' if dash_count != 1 else ''} · "
                    f"{recip_count} recipient{'s' if recip_count != 1 else ''} · "
                    f"{sched_summary}"
                )

                # Admins manage jobs from every user, so label whose job this
                # is; regular users only ever see their own, so it'd be noise.
                if is_admin:
                    if owner and owner in all_usernames:
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
                        st.markdown(f"Last run: {run_label} — :green[success]")
                    else:
                        st.markdown(
                            f"Last run: {run_label} — "
                            f":red[{last_status or 'unknown'}]"
                        )

            # ---- Right column -----------------------------------------------
            with right:
                # can_manage is re-checked at every single action below, not
                # just once for the row. In normal use this is always True
                # here: get_jobs_for_user() only ever hands a regular user
                # their own jobs, so every button a regular user sees is
                # fully live — same as an admin's, just scoped to fewer
                # cards. The per-button check exists as defense in depth
                # (so a mutating action can never fire without its own
                # permission check, regardless of how the row got rendered)
                # and degrades gracefully to a disabled, explained button
                # rather than a missing one if it's ever False.
                deny_reason = "" if can_manage else "You can only manage jobs you created."

                b1, b2, b3, b4 = st.columns([1.2, 1.2, 1, 1])

                with b1:
                    if st.button("▶ Run", key=f"run_{job_id}",
                                 use_container_width=True, type="primary",
                                 disabled=not can_manage, help=deny_reason):
                        if can_manage:
                            threading.Thread(
                                target=runner.run_job,
                                args=(job_id,),
                                daemon=True,
                            ).start()
                            st.toast("Job started.")

                with b2:
                    if job.get("status") == "active":
                        if st.button("⏸ Pause", key=f"pause_{job_id}",
                                     use_container_width=True,
                                     disabled=not can_manage, help=deny_reason):
                            if can_manage:
                                config_manager.upsert_job({**job, "status": "paused"})
                                scheduler.remove_job(job_id)
                                st.rerun()
                    else:
                        if st.button("▶ Resume", key=f"resume_{job_id}",
                                     use_container_width=True, type="primary",
                                     disabled=not can_manage, help=deny_reason):
                            if can_manage:
                                updated = {**job, "status": "active"}
                                config_manager.upsert_job(updated)
                                scheduler.add_or_update_job(updated)
                                st.rerun()

                with b3:
                    if st.button("✏ Edit", key=f"edit_{job_id}",
                                 use_container_width=True,
                                 disabled=not can_manage, help=deny_reason):
                        if can_manage:
                            st.session_state["edit_job_id"] = job_id
                            st.session_state["edit_mode"] = True
                            st.switch_page("pages/4_New_Job.py")

                with b4:
                    if st.button("🗑 Del", key=f"del_{job_id}",
                                 use_container_width=True,
                                 disabled=not can_manage, help=deny_reason):
                        if can_manage:
                            config_manager.delete_job(job_id)
                            scheduler.remove_job(job_id)
                            st.rerun()

                next_run = scheduler.get_next_run(job_id)
                st.caption(f"Next run: {next_run}")

                # Admin-only: claim/reassign jobs with no owner (pre-feature
                # legacy jobs) or whose owner account has since been deleted.
                if is_admin and (not owner or owner not in all_usernames):
                    with st.expander("Reassign owner"):
                        new_owner = st.selectbox(
                            "Assign this job to",
                            options=sorted(all_usernames),
                            key=f"reassign_select_{job_id}",
                        )
                        if st.button("Assign", key=f"reassign_btn_{job_id}"):
                            config_manager.set_job_owner(job_id, new_owner)
                            st.rerun()

        st.divider()
