"""Shared UI helpers — call these at the top of every page."""

import os
import streamlit as st


def show_logo() -> None:
    """Display the company logo in the sidebar. Safe to call before authentication."""
    _logo_path = os.path.join(os.path.dirname(__file__), "..", "assets", "company_logo.png")
    _logo_path = os.path.normpath(_logo_path)
    if os.path.exists(_logo_path):
        try:
            st.logo(_logo_path, size="large")
        except Exception:
            st.sidebar.image(_logo_path, width=220)
    else:
        st.sidebar.markdown("## 📈 Grafana Reporter")
