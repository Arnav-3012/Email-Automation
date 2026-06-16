"""Grafana Reporter — Streamlit entry point. Run with: streamlit run main.py"""

import streamlit as st

from app import scheduler
from app.auth_manager import (
    initialize_users,
    log_event,
    render_user_sidebar,
    users_file_exists,
    validate_password,
    verify_login,
)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None

# ---------------------------------------------------------------------------
# Setup wizard — first run only (no app_users.json yet)
# ---------------------------------------------------------------------------

if not users_file_exists():
    st.set_page_config(page_title="Grafana Reporter - Setup", page_icon="⚙️", layout="centered")
    st.title("⚙️ Grafana Reporter - First Setup")
    st.markdown("Create your admin account to get started.")

    with st.form("setup_form"):
        username = st.text_input("Username", placeholder="admin")
        password = st.text_input("Password", type="password")
        confirm = st.text_input("Confirm Password", type="password")
        submit = st.form_submit_button("Create Admin & Continue", use_container_width=True)

        if submit:
            password_error = validate_password(password)
            if not username or not password:
                st.error("❌ Username and password required")
            elif password != confirm:
                st.error("❌ Passwords don't match")
            elif password_error:
                st.error(f"❌ {password_error}")
            else:
                initialize_users(username, password)
                st.session_state.authenticated = True
                st.session_state.current_user = username
                st.success("✅ Admin account created! Redirecting...")
                st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Login gate
# ---------------------------------------------------------------------------

if not st.session_state.authenticated:
    st.set_page_config(page_title="Grafana Reporter - Login", page_icon="🔐", layout="centered")
    st.title("🔐 Grafana Reporter Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login", use_container_width=True)

        if submit:
            if verify_login(username, password):
                st.session_state.authenticated = True
                st.session_state.current_user = username
                log_event("login_success", username)
                st.rerun()
            else:
                log_event("login_failed", username, "invalid_credentials")
                st.error("❌ Invalid username or password")
    st.stop()

# ---------------------------------------------------------------------------
# Authenticated — rest of the app
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Grafana Reporter",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Start scheduler exactly once across Streamlit reruns
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
# Sidebar — scheduler status + logout
# ---------------------------------------------------------------------------

job_statuses = scheduler.get_all_job_statuses()
n_active = len(job_statuses)

if n_active > 0:
    st.sidebar.markdown(":green[🟢 Scheduler running]")
else:
    st.sidebar.markdown("⚪ No jobs scheduled")

st.sidebar.caption(f"{n_active} job{'s' if n_active != 1 else ''} active")
st.sidebar.caption("Use the pages above to manage jobs and contacts.")

render_user_sidebar()

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
