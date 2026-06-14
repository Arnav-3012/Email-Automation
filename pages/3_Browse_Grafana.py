"""Browse Grafana page — folder tree and panel picker for building jobs."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from app import grafana_client
from app.grafana_client import GrafanaConnectionError

st.set_page_config(page_title="Browse Grafana", page_icon="📂", layout="wide")
st.title("Browse Grafana")

if "selected_dashboard" not in st.session_state:
    st.session_state["selected_dashboard"] = None
if "job_draft_dashboards" not in st.session_state:
    st.session_state["job_draft_dashboards"] = []

seen_uids = set()
_btn = [0]

def render_dashboard_button(dash, folder_path):
    if dash["uid"] in seen_uids:
        return
    seen_uids.add(dash["uid"])
    key = f"btn_{_btn[0]}"
    _btn[0] += 1
    if st.button(f"📊 {dash['title']}", key=key, use_container_width=True):
        st.session_state["selected_dashboard"] = {
            "uid": dash["uid"],
            "title": dash["title"],
            "folder_path": folder_path,
        }
        st.rerun()

left_col, right_col = st.columns([2, 3], gap="large")

with left_col:
    st.subheader("Folders")
    try:
        folders = grafana_client.get_folders()
    except GrafanaConnectionError as e:
        st.error(f"{e}\n\nCheck your Grafana settings in the Settings page.")
        folders = []

    if not folders:
        st.info("No folders found, or Grafana is not configured. Check Settings.")
    else:
        for folder in folders:
            with st.expander(folder["title"]):
                try:
                    subfolders = grafana_client.get_subfolders(folder["uid"])
                except GrafanaConnectionError as e:
                    st.error(f"{e}")
                    subfolders = []

                for subfolder in subfolders:
                    with st.expander(f"  {subfolder['title']}"):
                        try:
                            sub_dashboards = grafana_client.get_dashboards_in_folder(subfolder["uid"])
                        except GrafanaConnectionError as e:
                            st.error(f"{e}")
                            sub_dashboards = []
                        for dash in sub_dashboards:
                            render_dashboard_button(dash, f"{folder['title']} / {subfolder['title']}")

                try:
                    direct_dashboards = grafana_client.get_dashboards_in_folder(folder["uid"])
                except GrafanaConnectionError as e:
                    st.error(f"{e}")
                    direct_dashboards = []

                for dash in direct_dashboards:
                    render_dashboard_button(dash, folder["title"])

with right_col:
    st.subheader("Panels")
    selected = st.session_state["selected_dashboard"]

    if selected is None:
        st.info("Select a dashboard from the left.")
    else:
        st.markdown(f"**{selected['title']}**")
        st.caption(selected["folder_path"])
        st.divider()

        try:
            dashboard_json = grafana_client.get_dashboard(selected["uid"])
            panels = grafana_client.get_panels(dashboard_json)
        except GrafanaConnectionError as e:
            st.error(f"{e}")
            panels = []

        if not panels:
            st.info("No panels found in this dashboard.")
        else:
            for panel in panels:
                st.checkbox(
                    f"{panel['title']} ({panel['type']})",
                    key=f"panel_{panel['id']}",
                )
            st.divider()
            if st.button("Add to Job", type="primary"):
                checked_ids = [
                    panel["id"]
                    for panel in panels
                    if st.session_state.get(f"panel_{panel['id']}", False)
                ]
                if not checked_ids:
                    st.warning("Select at least one panel.")
                else:
                    st.session_state["job_draft_dashboards"].append({
                        "uid": selected["uid"],
                        "title": selected["title"],
                        "folder_path": selected["folder_path"],
                        "panels": checked_ids,
                    })
                    st.success(
                        f"Added {len(checked_ids)} panel"
                        f"{'s' if len(checked_ids) != 1 else ''} "
                        f"from {selected['title']}."
                    )