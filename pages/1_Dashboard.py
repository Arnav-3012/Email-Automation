"""Dashboard page — job overview, run controls, and status."""

import sys
import threading
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import config_manager, contact_manager, scheduler
from app.auth_manager import require_auth
import runner

require_auth(page_title="Dashboard", page_icon="📋")
st.title("Dashboard")

jobs = config_manager.get_jobs()

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

if not jobs:
    st.info("No jobs yet. Use New Job in the sidebar to create one.")
else:
    for job in jobs:
        job_id = job["id"]

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
                b1, b2, b3, b4 = st.columns([1.2, 1.2, 1, 1])

                with b1:
                    if st.button("▶ Run", key=f"run_{job_id}",
                                 use_container_width=True, type="primary"):
                        threading.Thread(
                            target=runner.run_job,
                            args=(job_id,),
                            daemon=True,
                        ).start()
                        st.toast("Job started.")

                with b2:
                    if job.get("status") == "active":
                        if st.button("⏸ Pause", key=f"pause_{job_id}",
                                     use_container_width=True):
                            config_manager.upsert_job({**job, "status": "paused"})
                            scheduler.remove_job(job_id)
                            st.rerun()
                    else:
                        if st.button("▶ Resume", key=f"resume_{job_id}",
                                     use_container_width=True, type="primary"):
                            updated = {**job, "status": "active"}
                            config_manager.upsert_job(updated)
                            scheduler.add_or_update_job(updated)
                            st.rerun()

                with b3:
                    if st.button("✏ Edit", key=f"edit_{job_id}",
                                 use_container_width=True):
                        st.session_state["edit_job_id"] = job_id
                        st.session_state["edit_mode"] = True
                        st.switch_page("pages/4_New_Job.py")

                with b4:
                    if st.button("🗑 Del", key=f"del_{job_id}",
                                 use_container_width=True):
                        config_manager.delete_job(job_id)
                        scheduler.remove_job(job_id)
                        st.rerun()

                next_run = scheduler.get_next_run(job_id)
                st.caption(f"Next run: {next_run}")

        st.divider()
