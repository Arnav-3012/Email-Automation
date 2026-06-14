"""Settings page — Grafana connection and SMTP configuration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app import config_manager
from app.grafana_client import GrafanaConnectionError, test_connection

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
st.title("Settings")

grafana = config_manager.get_grafana_settings()
smtp = config_manager.get_smtp_settings()

# ---------------------------------------------------------------------------
# Grafana Settings
# ---------------------------------------------------------------------------

st.header("Grafana Settings")

grafana_url = st.text_input("Grafana Server URL", value=grafana["url"])
grafana_api_key = st.text_input("API Key", value=grafana["api_key"], type="password")
grafana_username = st.text_input("Username", value=grafana["username"])
grafana_password = st.text_input("Password", value=grafana["password"], type="password")

col_save, col_test = st.columns([1, 1], gap="small")

with col_save:
    if st.button("Save Grafana Settings", use_container_width=True):
        config_manager.update_grafana_settings(
            url=grafana_url,
            api_key=grafana_api_key,
            username=grafana_username,
            password=grafana_password,
        )
        st.success("Saved.")

with col_test:
    if st.button("Test Connection", use_container_width=True):
        config_manager.update_grafana_settings(
            url=grafana_url,
            api_key=grafana_api_key,
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
smtp_port = st.number_input("Port", value=smtp["port"], min_value=1, max_value=65535, step=1)
smtp_username = st.text_input("SMTP Username", value=smtp["username"])
smtp_password = st.text_input("SMTP Password", value=smtp["password"], type="password")

if st.button("Save SMTP Settings"):
    config_manager.update_smtp_settings(
        host=smtp_host,
        port=int(smtp_port),
        username=smtp_username,
        password=smtp_password,
    )
    st.success("Saved.")
