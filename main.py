"""Grafana Reporter — Streamlit entry point. Run with: streamlit run main.py"""

import streamlit as st

from app import scheduler

st.set_page_config(
    page_title="Grafana Reporter",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Start scheduler exactly once across Streamlit reruns
# ---------------------------------------------------------------------------

if not st.session_state.get("scheduler_loaded", False):
    scheduler.load_jobs_from_config()
    st.session_state["scheduler_loaded"] = True

# Persist shared state across pages
if "job_draft_dashboards" not in st.session_state:
    st.session_state["job_draft_dashboards"] = []
if "selected_dashboard" not in st.session_state:
    st.session_state["selected_dashboard"] = None
st.session_state.setdefault("email_subject", "")
st.session_state.setdefault("email_message", "")
st.session_state.setdefault("panel_names", {})

# ---------------------------------------------------------------------------
# Sidebar — scheduler status
# ---------------------------------------------------------------------------

job_statuses = scheduler.get_all_job_statuses()
n_active = len(job_statuses)

if n_active > 0:
    st.sidebar.markdown(":green[🟢 Scheduler running]")
else:
    st.sidebar.markdown("⚪ No jobs scheduled")

st.sidebar.caption(f"{n_active} job{'s' if n_active != 1 else ''} active")
st.sidebar.caption("Use the pages above to manage jobs and contacts.")

# ---------------------------------------------------------------------------
# Home page content
# ---------------------------------------------------------------------------

st.title("Grafana Reporter")
st.write(
    "Automated PDF reports from Grafana dashboards, "
    "delivered via email on a schedule."
)

st.divider()

col_dash, col_browse, col_new = st.columns(3, gap="large")

with col_dash:
    st.markdown("### 📋 Dashboard")
    st.write("View all jobs, check last run status, and trigger runs manually.")

with col_browse:
    st.markdown("### 📂 Browse Grafana")
    st.write("Explore folders and dashboards, and pick panels to include in a report.")

with col_new:
    st.markdown("### ➕ New Job")
    st.write("Create a scheduled report job with selected dashboards and recipients.")

st.caption("Use the sidebar to navigate between pages.")
