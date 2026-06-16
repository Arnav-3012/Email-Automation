"""Browse Grafana — cascading selector for large folder trees."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from app import grafana_client, config_manager
from app.auth_manager import require_auth
from app.grafana_client import GrafanaConnectionError

require_auth(page_title="Browse Grafana", page_icon="📂")
st.title("Browse Grafana")
st.caption("Select org → folder → subfolder → dashboard → panels.")

st.session_state.setdefault("selected_dashboard", None)
st.session_state.setdefault("job_draft_dashboards", [])

left_col, right_col = st.columns([1, 1], gap="large")

with left_col:

    # ── Organisation selector ────────────────────────────
    st.subheader("Organisation")
    try:
        orgs = grafana_client.get_organisations()
    except Exception:
        orgs = []

    if len(orgs) > 1:
        org_options = {
            f"{o['name']} (ID: {o['id']})": o["id"]
            for o in orgs
        }
        selected_org_label = st.selectbox(
            "Organisation",
            options=list(org_options.keys()),
            key="browse_org_select",
            label_visibility="collapsed",
            help="Type to search organisations",
        )
        selected_org_id = org_options[selected_org_label]
        current_org = grafana_client.get_current_org_id()
        if selected_org_id != current_org:
            settings = config_manager.get_grafana_settings()
            settings["org_id"] = selected_org_id
            config_manager.update_grafana_settings(**settings)
            grafana_client.clear_dashboard_cache()
            st.rerun()
    else:
        if orgs:
            st.caption(
                f"Organisation: {orgs[0].get('name', 'Default')} "
                f"(ID: {orgs[0].get('id', 1)})"
            )
        else:
            st.caption("Default organisation")

    st.divider()

    # ── Step 1: Folder ───────────────────────────────────
    st.subheader("Step 1 — Folder")
    try:
        folders = grafana_client.get_folders()
    except GrafanaConnectionError as e:
        if "401" in str(e) or "403" in str(e):
            st.warning(
                "You don't have access to this organisation. "
                "Please select a different one."
            )
        else:
            st.error(f"{e} — Check Settings page.")
        st.stop()

    if not folders:
        st.info("No folders found. Check Grafana settings.")
        st.stop()

    folder_options = {"— Select a folder —": None}
    folder_options.update({f["title"]: f["uid"] for f in folders})

    selected_folder_title = st.selectbox(
        "Folder",
        options=list(folder_options.keys()),
        key="browse_folder_select",
        label_visibility="collapsed",
        help="Type to search folders",
    )
    selected_folder_uid = folder_options[selected_folder_title]

    if selected_folder_uid is None:
        st.stop()

    # ── Step 2: Subfolder ────────────────────────────────
    if selected_folder_uid == "general":
        st.caption("General folder — no subfolders.")
        folder_path = "General (No Folder)"
        active_folder_uid = "general"
    else:
        st.subheader("Step 2 — Subfolder")
        try:
            subfolders = grafana_client.get_subfolders(selected_folder_uid)
        except GrafanaConnectionError as e:
            if "401" in str(e) or "403" in str(e):
                st.warning("No access to this resource.")
            else:
                st.error(f"{e}")
            subfolders = []

        if subfolders:
            subfolder_options = {"— None (use folder directly) —": None}
            subfolder_options.update({s["title"]: s["uid"] for s in subfolders})
            selected_subfolder_title = st.selectbox(
                "Subfolder",
                options=list(subfolder_options.keys()),
                key="browse_subfolder_select",
                label_visibility="collapsed",
                help="Type to search subfolders",
            )
            selected_subfolder_uid = subfolder_options[selected_subfolder_title]
            if selected_subfolder_uid:
                folder_path = f"{selected_folder_title} / {selected_subfolder_title}"
                active_folder_uid = selected_subfolder_uid
            else:
                folder_path = selected_folder_title
                active_folder_uid = selected_folder_uid
        else:
            st.caption("No subfolders — using folder directly.")
            folder_path = selected_folder_title
            active_folder_uid = selected_folder_uid

    # ── Step 3: Dashboard ────────────────────────────────
    st.subheader("Step 3 — Dashboard")
    try:
        dashboards = grafana_client.get_dashboards_in_folder(active_folder_uid)
    except GrafanaConnectionError as e:
        if "401" in str(e) or "403" in str(e):
            st.warning("No access to this resource.")
        else:
            st.error(f"{e}")
        dashboards = []

    if not dashboards:
        st.info("No dashboards in this folder.")
        st.stop()

    dash_options = {"— Select a dashboard —": None}
    dash_options.update({d["title"]: d["uid"] for d in dashboards})

    selected_dash_title = st.selectbox(
        "Dashboard",
        options=list(dash_options.keys()),
        key="browse_dashboard_select",
        label_visibility="collapsed",
        help="Type to search dashboards",
    )
    selected_dash_uid = dash_options[selected_dash_title]

    if selected_dash_uid is None:
        st.stop()

    st.session_state["selected_dashboard"] = {
        "uid": selected_dash_uid,
        "title": selected_dash_title,
        "folder_path": folder_path,
    }

with right_col:
    # ── Step 4: Panels ───────────────────────────────────
    st.subheader("Step 4 — Select Panels")

    selected = st.session_state.get("selected_dashboard")

    if not selected or not selected.get("uid"):
        st.info("Complete Steps 1-3 to see panels.")
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
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✓ Select all", use_container_width=True):
                    for panel in panels:
                        st.session_state[
                            f"panel_{selected['uid']}_{panel['id']}"
                        ] = True
                    st.rerun()
            with col_b:
                if st.button("✗ Deselect all", use_container_width=True):
                    for panel in panels:
                        st.session_state[
                            f"panel_{selected['uid']}_{panel['id']}"
                        ] = False
                    st.rerun()

            st.divider()

            for panel in panels:
                panel_key = f"panel_{selected['uid']}_{panel['id']}"
                st.session_state.setdefault(panel_key, False)
                st.checkbox(
                    f"{panel['title']}",
                    key=panel_key,
                    help=(
                        f"Type: {panel.get('type', 'unknown')} "
                        f"· ID: {panel['id']}"
                    ),
                )

            st.divider()

            if st.button("Add to Job →", type="primary", use_container_width=True):
                checked_ids = [
                    panel["id"]
                    for panel in panels
                    if st.session_state.get(
                        f"panel_{selected['uid']}_{panel['id']}", False
                    )
                ]

                if not checked_ids:
                    st.warning("Select at least one panel.")
                else:
                    existing = [
                        d for d in st.session_state["job_draft_dashboards"]
                        if d["uid"] != selected["uid"]
                    ]
                    existing.append({
                        "uid": selected["uid"],
                        "title": selected["title"],
                        "folder_path": selected["folder_path"],
                        "panels": checked_ids,
                    })
                    st.session_state["job_draft_dashboards"] = existing
                    st.success(
                        f"Added {len(checked_ids)} panel"
                        f"{'s' if len(checked_ids) != 1 else ''} "
                        f"from {selected['title']}. "
                        f"Go to New Job to continue."
                    )
