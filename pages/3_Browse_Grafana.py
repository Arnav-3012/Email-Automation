"""Browse Grafana — cascading selector for large folder trees."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from app import grafana_client, config_manager
from app.auth_manager import get_grafana_credentials, require_auth
from app.grafana_client import GrafanaConnectionError
from app.ui_helpers import show_logo

show_logo()
require_auth(page_title="Browse Grafana", page_icon="📂")
st.title("📂 Browse Grafana")

# Resolve credentials for the currently logged-in user (personal → fallback to global).
_current_user: str = st.session_state.get("current_user", "")
_creds = get_grafana_credentials(_current_user) if _current_user else None
if not _creds or not _creds.get("grafana_username"):
    st.warning(
        "Please set your Grafana credentials in **Settings** before browsing dashboards."
    )
    st.stop()

st.session_state.setdefault("selected_dashboard", None)
st.session_state.setdefault("job_draft_dashboards", [])

left_col, right_col = st.columns([1, 1], gap="large")

with left_col:

    # ── Organisation selector ────────────────────────────
    with st.container(border=True):
        st.markdown("#### 🏢 Organisation")
        try:
            orgs = grafana_client.get_organisations(credentials=_creds)
        except Exception as e:
            st.warning(f"Could not load organisations: {e}")
            orgs = []

        if not orgs:
            st.caption("No organisations returned — check Grafana credentials in Settings.")
        else:
            org_options = {
                f"{o['name']} (ID: {o['id']})": o["id"]
                for o in orgs
            }
            current_stored_org = grafana_client.get_current_org_id()

            default_label = next(
                (label for label, oid in org_options.items() if oid == current_stored_org),
                list(org_options.keys())[0],
            )
            default_index = list(org_options.keys()).index(default_label)

            selected_org_label = st.selectbox(
                "Organisation",
                options=list(org_options.keys()),
                index=default_index,
                key="browse_org_select",
                label_visibility="collapsed",
                help="Select the Grafana organisation to browse",
            )
            selected_org_id = org_options[selected_org_label]

            if selected_org_id != current_stored_org:
                settings = config_manager.get_grafana_settings()
                settings["org_id"] = selected_org_id
                config_manager.update_grafana_settings(**settings)
                grafana_client.clear_dashboard_cache()
                st.rerun()

    # Build breadcrumb path as we go — updated at each step
    _breadcrumb_parts = []

    # ── Step 1: Folder ───────────────────────────────────
    with st.container(border=True):
        st.markdown("#### 📁 Step 1 — Folder")
        try:
            folders = grafana_client.get_folders(credentials=_creds)
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

        _breadcrumb_parts.append(f"📁 {selected_folder_title}")

    # ── Step 2: Subfolder ────────────────────────────────
    if selected_folder_uid == "general":
        st.caption("📁 General folder — no subfolders.")
        folder_path = "General (No Folder)"
        active_folder_uid = "general"
        _breadcrumb_parts.append("General")
    elif selected_folder_uid == "sharedwithme":
        with st.container(border=True):
            st.markdown("#### 📁 Step 2 — Subfolder")
            try:
                subfolders = grafana_client.get_subfolders("sharedwithme", credentials=_creds)
            except GrafanaConnectionError as e:
                st.error(f"{e}")
                subfolders = []

            if subfolders:
                subfolder_options = {"— None (use shared root) —": None}
                subfolder_options.update({s["title"]: s["uid"] for s in subfolders})
                selected_subfolder_title = st.selectbox(
                    "Subfolder",
                    options=list(subfolder_options.keys()),
                    key="browse_subfolder_select",
                    label_visibility="collapsed",
                    help="Type to search shared subfolders",
                )
                selected_subfolder_uid = subfolder_options[selected_subfolder_title]
                if selected_subfolder_uid:
                    folder_path = f"Shared with me / {selected_subfolder_title}"
                    active_folder_uid = selected_subfolder_uid
                    _breadcrumb_parts.append(f"📁 {selected_subfolder_title}")
                else:
                    folder_path = "Shared with me"
                    active_folder_uid = "sharedwithme"
            else:
                st.caption("No shared subfolders found.")
                folder_path = "Shared with me"
                active_folder_uid = "sharedwithme"
    else:
        with st.container(border=True):
            st.markdown("#### 📁 Step 2 — Subfolder")
            try:
                subfolders = grafana_client.get_subfolders(selected_folder_uid, credentials=_creds)
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
                    _breadcrumb_parts.append(f"📁 {selected_subfolder_title}")
                else:
                    folder_path = selected_folder_title
                    active_folder_uid = selected_folder_uid
            else:
                st.caption("No subfolders — using folder directly.")
                folder_path = selected_folder_title
                active_folder_uid = selected_folder_uid

    # ── Step 3: Dashboard ────────────────────────────────
    with st.container(border=True):
        st.markdown("#### 📊 Step 3 — Dashboard")
        try:
            dashboards = grafana_client.get_dashboards_in_folder(active_folder_uid, credentials=_creds)
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

        _breadcrumb_parts.append(f"📊 {selected_dash_title}")

    # Breadcrumb display
    if _breadcrumb_parts:
        st.caption(" › ".join(_breadcrumb_parts))

    st.session_state["selected_dashboard"] = {
        "uid": selected_dash_uid,
        "title": selected_dash_title,
        "folder_path": folder_path,
    }

with right_col:
    # ── Step 4: Panels ───────────────────────────────────
    st.markdown("#### 🔲 Step 4 — Select Panels")

    selected = st.session_state.get("selected_dashboard")

    if not selected or not selected.get("uid"):
        st.info("Complete Steps 1–3 to see panels.")
    else:
        with st.container(border=True):
            st.markdown(f"**📊 {selected['title']}**")
            st.caption(f"📁 {selected['folder_path']}")
            st.divider()

            try:
                dashboard_json = grafana_client.get_dashboard(selected["uid"], credentials=_creds)
                panels = grafana_client.get_panels(dashboard_json)
            except GrafanaConnectionError as e:
                st.error(f"{e}")
                panels = []

            if not panels:
                st.info("No panels found in this dashboard.")
            else:
                # Panel type → display icon mapping
                _type_icons = {
                    "graph": "📈",
                    "timeseries": "📈",
                    "barchart": "📊",
                    "bargauge": "📊",
                    "gauge": "🎯",
                    "stat": "🔢",
                    "table": "📋",
                    "text": "📝",
                    "piechart": "🥧",
                    "heatmap": "🗺️",
                    "logs": "📄",
                    "news": "📰",
                    "alertlist": "🔔",
                    "dashlist": "📂",
                    "canvas": "🎨",
                    "geomap": "🗺️",
                    "nodeGraph": "🕸️",
                }

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
                    _ptype = panel.get("type", "unknown")
                    _picon = _type_icons.get(_ptype, "▪️")
                    st.checkbox(
                        f"{_picon} {panel['title']}",
                        key=panel_key,
                        help=f"Type: {_ptype} · ID: {panel['id']}",
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

                        st.session_state["selected_dashboard_title"] = selected["title"]
                        panel_titles = st.session_state.get("selected_panel_titles", {})
                        for panel in panels:
                            if panel["id"] in checked_ids:
                                panel_titles[f"{selected['uid']}_{panel['id']}"] = panel["title"]
                        st.session_state["selected_panel_titles"] = panel_titles

                        st.success(
                            f"Added {len(checked_ids)} panel"
                            f"{'s' if len(checked_ids) != 1 else ''} "
                            f"from **{selected['title']}**. "
                            f"Go to **New Job** to continue."
                        )
