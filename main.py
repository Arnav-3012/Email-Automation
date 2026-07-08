"""Grafana Reporter — Streamlit entry point. Run with: streamlit run main.py"""

import streamlit as st

from app import config_manager, scheduler
from app.auth_manager import (
    has_users,
    initialize_users,
    log_event,
    render_user_sidebar,
    validate_password,
    verify_login,
)
from app.ui_helpers import show_logo

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None

# ---------------------------------------------------------------------------
# Setup wizard — first run only (no users yet, whether app_users.json is
# missing entirely or exists with an empty "users" list)
# ---------------------------------------------------------------------------

if not has_users():
    st.set_page_config(page_title="Grafana Reporter - Setup", page_icon="⚙️", layout="centered")
    show_logo()
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
    show_logo()
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

# One-time migration: give any legacy job missing an "id" a fresh uuid4,
# before the scheduler (or any page) does an id-keyed lookup on it.
if not st.session_state.get("jobs_migrated", False):
    config_manager.migrate_jobs_add_missing_ids()
    st.session_state["jobs_migrated"] = True

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
# Sidebar — logo + scheduler status + logout
# ---------------------------------------------------------------------------

show_logo()
st.sidebar.markdown("---")

job_statuses = scheduler.get_all_job_statuses()
n_active = len(job_statuses)

if n_active > 0:
    st.sidebar.markdown(":green[🟢 Scheduler running]")
else:
    st.sidebar.markdown("⚪ No jobs scheduled")

st.sidebar.caption(f"{n_active} job{'s' if n_active != 1 else ''} active")

render_user_sidebar()

# ---------------------------------------------------------------------------
# Home page content
# ---------------------------------------------------------------------------

st.title("Grafana Reporter")
st.write(
    "Automated PDF reports from Grafana dashboards, "
    "delivered via email on a schedule."
)

# Stats banner
_total_active = n_active
_banner_col1, _banner_col2, _banner_col3 = st.columns(3)
with _banner_col1:
    if _total_active > 0:
        st.success(f"🟢 {_total_active} job{'s' if _total_active != 1 else ''} active")
    else:
        st.info("⚪ No jobs scheduled")

st.divider()

# Clickable navigation cards — CSS forces equal height across all three columns
# so short descriptions don't make one card shorter than its neighbours.
_card_css = """
<style>
/* Make all three card containers the same height by stretching to the row's
   tallest child. The Streamlit column wrapper uses flex already; we just
   need each data-testid="stVerticalBlock" inside a column to fill it. */
[data-testid="column"] > div:first-child {
    height: 100%;
}
[data-testid="column"] > div:first-child > [data-testid="stVerticalBlock"] {
    height: 100%;
}
/* The bordered container itself should expand to fill the column height
   and push its button to the bottom with flex layout. */
[data-testid="column"] [data-testid="stVerticalBlockBorderWrapper"] {
    height: 100%;
}
[data-testid="column"] [data-testid="stVerticalBlockBorderWrapper"] > div {
    height: 100%;
    display: flex;
    flex-direction: column;
}
[data-testid="column"] [data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {
    flex: 1;
    display: flex;
    flex-direction: column;
}
/* Push the nav button to the bottom of each card */
[data-testid="column"] [data-testid="stVerticalBlockBorderWrapper"] .stButton {
    margin-top: auto;
}
</style>
"""
st.markdown(_card_css, unsafe_allow_html=True)

col_dash, col_browse, col_new = st.columns(3, gap="large")

with col_dash:
    with st.container(border=True):
        st.markdown("## 📋")
        st.markdown("### Dashboard")
        st.write("View all jobs, check last run status, pause or resume, and trigger a manual run.")
        if st.button("Go to Dashboard →", key="nav_dashboard", use_container_width=True, type="primary"):
            st.switch_page("pages/1_Dashboard.py")

with col_browse:
    with st.container(border=True):
        st.markdown("## 📂")
        st.markdown("### Browse Grafana")
        st.write("Explore folders and dashboards, and pick panels to include in a report.")
        if st.button("Go to Browse Grafana →", key="nav_browse", use_container_width=True, type="primary"):
            st.switch_page("pages/3_Browse_Grafana.py")

with col_new:
    with st.container(border=True):
        st.markdown("## ➕")
        st.markdown("### New Job")
        st.write("Create a scheduled report job with selected dashboards and recipients.")
        if st.button("Go to New Job →", key="nav_new_job", use_container_width=True, type="primary"):
            st.switch_page("pages/4_New_Job.py")

st.caption("Use the sidebar to navigate between pages.")
