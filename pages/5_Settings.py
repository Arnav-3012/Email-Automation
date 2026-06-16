"""Settings page — Grafana connection and SMTP configuration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import config_manager
from app.auth_manager import (
    change_password,
    create_user,
    delete_user,
    get_user,
    list_users,
    log_event,
    reset_password,
    require_auth,
    validate_password,
)
from app.grafana_client import GrafanaConnectionError, test_connection

require_auth(page_title="Settings", page_icon="⚙️")
st.title("Settings")

grafana = config_manager.get_grafana_settings()
smtp = config_manager.get_smtp_settings()

# ---------------------------------------------------------------------------
# Grafana Settings
# ---------------------------------------------------------------------------

st.header("Grafana Settings")

st.info(
    "Authentication uses your Grafana username and password. "
    "The user must have Admin role to access all organisations."
)

grafana_url = st.text_input("Grafana Server URL", value=grafana["url"])
grafana_username = st.text_input("Username", value=grafana["username"])
grafana_password = st.text_input("Password", value=grafana["password"], type="password")

col_save, col_test = st.columns([1, 1], gap="small")

with col_save:
    if st.button("Save Grafana Settings", use_container_width=True):
        config_manager.update_grafana_settings(
            url=grafana_url,
            username=grafana_username,
            password=grafana_password,
        )
        st.success("Saved.")

with col_test:
    if st.button("Test Connection", use_container_width=True):
        config_manager.update_grafana_settings(
            url=grafana_url,
            username=grafana_username,
            password=grafana_password,
        )
        try:
            test_connection()
            st.success("Connected — Grafana reachable.")
        except GrafanaConnectionError as e:
            st.error(str(e))

st.divider()

# ---------------------------------------------------------------------------
# SMTP Settings
# ---------------------------------------------------------------------------

st.header("SMTP Settings")
st.info("Only used on Mac for testing. Ignored on Windows — Outlook is used instead.")

smtp_host = st.text_input("SMTP Host", value=smtp["host"])

smtp_port_col, smtp_tls_col = st.columns(2)
with smtp_port_col:
    smtp_port = st.number_input("Port", value=smtp["port"], min_value=1, max_value=65535, step=1)
with smtp_tls_col:
    tls_options = ["starttls", "ssl", "none"]
    tls_idx = tls_options.index(smtp["tls_mode"]) if smtp["tls_mode"] in tls_options else 0
    smtp_tls_mode = st.selectbox(
        "TLS Mode",
        options=tls_options,
        index=tls_idx,
        format_func=lambda x: {
            "starttls": "STARTTLS (works with any port, requires auth)",
            "ssl": "SSL/TLS (works with any port, requires auth)",
            "none": "None (open relay, no auth required)",
        }[x],
    )

smtp_username = st.text_input("SMTP Username", value=smtp["username"])
smtp_password = st.text_input("SMTP Password", value=smtp["password"], type="password")

if st.button("Save SMTP Settings"):
    config_manager.update_smtp_settings(
        host=smtp_host,
        port=int(smtp_port),
        username=smtp_username,
        password=smtp_password,
        tls_mode=smtp_tls_mode,
    )
    st.success("Saved.")

st.divider()

# ---------------------------------------------------------------------------
# Change Password
# ---------------------------------------------------------------------------

st.header("🔑 Change Password")

with st.form("change_password_form"):
    current_pwd = st.text_input("Current Password", type="password")
    new_pwd = st.text_input("New Password", type="password")
    confirm_pwd = st.text_input("Confirm Password", type="password")
    submit_pwd = st.form_submit_button("Change Password")

    if submit_pwd:
        password_error = validate_password(new_pwd)
        if not current_pwd or not new_pwd:
            st.error("All fields required")
        elif new_pwd != confirm_pwd:
            st.error("New passwords don't match")
        elif password_error:
            st.error(password_error)
        elif change_password(st.session_state.current_user, current_pwd, new_pwd):
            log_event("password_changed", st.session_state.current_user, "self")
            st.success("✅ Password changed")
        else:
            st.error("❌ Current password incorrect")

# ---------------------------------------------------------------------------
# User Management (admin only)
# ---------------------------------------------------------------------------

current_user_record = get_user(st.session_state.current_user)

if current_user_record and current_user_record.get("role") == "admin":
    st.divider()
    st.header("👥 User Management (Admin Only)")

    st.write("**Current Users:**")
    for user in list_users():
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.write(f"{user['username']} ({user['role']})")
        with col2:
            if st.button("Reset", key=f"reset_{user['username']}", use_container_width=True):
                st.session_state[f"show_reset_{user['username']}"] = True
        with col3:
            if user["username"] != st.session_state.current_user:
                if st.button("Delete", key=f"delete_{user['username']}", use_container_width=True):
                    if delete_user(user["username"]):
                        log_event("user_deleted", st.session_state.current_user, user["username"])
                        st.success(f"✅ {user['username']} deleted")
                        st.rerun()
                    else:
                        st.error("❌ Cannot delete the last remaining admin account")

    # Reset password — shown inline below the list once requested
    for user in list_users():
        if st.session_state.get(f"show_reset_{user['username']}", False):
            st.markdown(f"**Reset password for {user['username']}:**")
            with st.form(f"reset_form_{user['username']}"):
                new_pwd_admin = st.text_input(
                    "New Password", type="password", key=f"new_pwd_{user['username']}"
                )
                confirm_admin = st.text_input(
                    "Confirm", type="password", key=f"confirm_{user['username']}"
                )
                if st.form_submit_button("Set Password"):
                    reset_error = validate_password(new_pwd_admin)
                    if new_pwd_admin != confirm_admin:
                        st.error("Passwords don't match")
                    elif reset_error:
                        st.error(reset_error)
                    else:
                        reset_password(user["username"], new_pwd_admin)
                        log_event(
                            "password_reset", st.session_state.current_user, user["username"]
                        )
                        st.success("✅ Password updated")
                        st.session_state[f"show_reset_{user['username']}"] = False
                        st.rerun()

    st.markdown("**Create New User:**")
    with st.form("create_user_form"):
        new_username = st.text_input("Username")
        new_password = st.text_input("Password", type="password")
        new_role = st.selectbox("Role", ["user", "admin"])
        if st.form_submit_button("Create User"):
            create_error = validate_password(new_password)
            if not new_username or not new_password:
                st.error("Username and password required")
            elif create_error:
                st.error(create_error)
            elif create_user(new_username, new_password, new_role):
                log_event("user_created", st.session_state.current_user, new_username)
                st.success(f"✅ User {new_username} created")
                st.rerun()
            else:
                st.error("Username already exists")
