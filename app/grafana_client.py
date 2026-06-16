"""Grafana REST API client — all HTTP calls to the Grafana instance live here."""

import requests

from app import config_manager


class GrafanaConnectionError(Exception):
    """Raised when a Grafana API call fails or returns an unexpected response."""


def _get_session() -> requests.Session:
    """Return a Session using Basic Auth and X-Grafana-Org-Id for cross-org access."""
    settings = config_manager.get_grafana_settings()
    username = settings.get("username", "")
    password = settings.get("password", "")
    org_id = settings.get("org_id", 1)
    session = requests.Session()
    session.auth = (username, password)
    session.headers.update({
        "X-Grafana-Org-Id": str(org_id),
        "Content-Type": "application/json",
    })
    return session


def _get(path: str, params: dict = None) -> any:
    """GET {base_url}{path} and return parsed JSON. Raises GrafanaConnectionError on any failure.

    If the X-Grafana-Org-Id header is rejected (401/403) — which can happen against
    older Grafana 9.x servers — automatically retries once with ?orgId= as a query
    param before giving up.
    """
    settings = config_manager.get_grafana_settings()
    base_url = settings.get("url", "").rstrip("/")
    session = _get_session()
    org_id = settings.get("org_id", 1)
    try:
        resp = session.get(f"{base_url}{path}", params=params, timeout=10)

        # If header-based org switching failed, retry with query param
        if resp.status_code in (401, 403) and org_id != 1:
            retry_params = dict(params) if params else {}
            retry_params["orgId"] = org_id
            resp = session.get(
                f"{base_url}{path}", params=retry_params, timeout=10
            )

        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError as e:
        raise GrafanaConnectionError(f"Cannot reach Grafana at {base_url}: {e}")
    except requests.exceptions.HTTPError as e:
        raise GrafanaConnectionError(f"HTTP {resp.status_code} from {path}: {e}")
    except Exception as e:
        raise GrafanaConnectionError(f"Request failed: {e}")


def _post(path: str, payload: dict) -> any:
    """POST {base_url}{path} with a JSON payload. Raises GrafanaConnectionError on any failure."""
    settings = config_manager.get_grafana_settings()
    base_url = settings.get("url", "").rstrip("/")
    session = _get_session()
    try:
        resp = session.post(f"{base_url}{path}", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError as e:
        raise GrafanaConnectionError(f"Cannot reach Grafana at {base_url}: {e}")
    except requests.exceptions.HTTPError as e:
        raise GrafanaConnectionError(f"HTTP {resp.status_code} from {path}: {e}")
    except Exception as e:
        raise GrafanaConnectionError(f"Request failed: {e}")


def execute_ds_query(payload: dict) -> dict:
    """POST to /api/ds/query and return the full response dict."""
    return _post("/api/ds/query", payload)


def test_connection() -> dict:
    """Ping /api/health, log the Grafana version, and return the response dict."""
    result = _get("/api/health")
    version = result.get("version", "unknown")
    print(f"[grafana_client] Connected — Grafana version: {version}")
    return result


def get_grafana_version() -> str:
    """Get Grafana server version for compatibility logging."""
    try:
        health = _get("/api/health")
        return health.get("version", "unknown")
    except Exception:
        return "unknown"


def get_organisations() -> list:
    """Return all orgs via Basic Auth; falls back to current org only."""
    settings = config_manager.get_grafana_settings()
    base_url = settings.get("url", "").rstrip("/")
    username = settings.get("username", "")
    password = settings.get("password", "")
    try:
        resp = requests.get(
            f"{base_url}/api/orgs",
            auth=(username, password),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        current = _get("/api/org")
        return [current]
    except Exception:
        try:
            current = _get("/api/org")
            return [current]
        except Exception:
            return []


def get_current_org_id() -> int:
    """Return the org_id currently stored in config."""
    return int(config_manager.get_grafana_settings().get("org_id", 1))


def get_folders() -> list:
    """Return all top-level Grafana folders, prepending General for root dashboards."""
    folders = _get("/api/folders")
    try:
        all_dash = _get_all_dashboards()
        if any(not d.get("folderUid") for d in all_dash):
            folders = [{"uid": "general", "title": "General (No Folder)"}] + folders
    except Exception:
        pass
    return folders


def get_subfolders(folder_uid: str) -> list:
    """Return child folders of a given folder, compatible with Grafana 8/9 and 10+.

    Tries GET /api/folders/{uid}/children first (Grafana 10+). On 404 falls back to
    GET /api/search?folderUid={uid}&type=dash-folder (Grafana 8/9), normalising the
    search results into the same {uid, title} shape. Any non-404 HTTP error raises
    GrafanaConnectionError. Returns [] for "sharedwithme" and "general" without any API call.
    """
    if folder_uid in ("sharedwithme", "general"):
        return []

    settings = config_manager.get_grafana_settings()
    base_url = settings.get("url", "").rstrip("/")
    session = _get_session()
    try:
        resp = session.get(
            f"{base_url}/api/folders/{folder_uid}/children", timeout=10
        )
    except requests.exceptions.ConnectionError as e:
        raise GrafanaConnectionError(f"Cannot reach Grafana at {base_url}: {e}")
    except requests.exceptions.Timeout:
        raise GrafanaConnectionError(
            f"Request timed out: {base_url}/api/folders/{folder_uid}/children"
        )
    except requests.exceptions.RequestException as e:
        raise GrafanaConnectionError(
            f"Request failed for /api/folders/{folder_uid}/children: {e}"
        )

    if resp.status_code == 200:
        result = resp.json()
        subfolders = result if isinstance(result, list) else []
        return [f for f in subfolders if f["uid"] != folder_uid]

    if resp.status_code == 404:
        results = _get("/api/search", params={"folderUid": folder_uid, "type": "dash-folder"})
        subfolders = [{"uid": item["uid"], "title": item["title"]} for item in results]
        return [f for f in subfolders if f["uid"] != folder_uid]

    raise GrafanaConnectionError(
        f"HTTP {resp.status_code} from /api/folders/{folder_uid}/children"
    )


_dashboard_cache: dict = {}


def _get_all_dashboards() -> list:
    """Fetch all dashboards once per org and cache by org_id."""
    global _dashboard_cache
    settings = config_manager.get_grafana_settings()
    org_id = settings.get("org_id", 1)
    if org_id not in _dashboard_cache:
        _dashboard_cache[org_id] = _get(
            "/api/search", params={"type": "dash-db", "limit": 5000}
        )
    return _dashboard_cache[org_id]


def clear_dashboard_cache() -> None:
    """Reset the dashboard cache for all orgs."""
    global _dashboard_cache
    _dashboard_cache = {}


def get_dashboards_in_folder(folder_uid: str) -> list:
    """Return dashboards inside the given folder, filtered client-side from a full fetch.

    Handles the special "general" uid for dashboards that have no folder.
    """
    all_dashboards = _get_all_dashboards()
    if folder_uid == "general":
        return [d for d in all_dashboards if not d.get("folderUid")]
    return [d for d in all_dashboards if d.get("folderUid") == folder_uid]


def get_dashboard(uid: str) -> dict:
    """Fetch and return the full dashboard JSON for the given UID."""
    return _get(f"/api/dashboards/uid/{uid}")


def get_panels(dashboard_json: dict) -> list:
    """Extract panel metadata from a dashboard JSON response.

    Returns a list of dicts with keys: id, title, type, datasource_uid,
    datasource_type, targets, fieldConfig.
    """
    panels = []
    dashboard = dashboard_json.get("dashboard", {})
    for panel in dashboard.get("panels", []):
        panel_ds = panel.get("datasource") or {}
        if not panel_ds and panel.get("targets"):
            panel_ds = panel["targets"][0].get("datasource") or {}

        panels.append({
            "id": panel.get("id"),
            "title": panel.get("title", "Untitled"),
            "type": panel.get("type", ""),
            "description": panel.get("description", ""),
            "datasource_uid": panel_ds.get("uid", ""),
            "datasource_type": panel_ds.get("type", ""),
            "targets": panel.get("targets", []),
            "fieldConfig": panel.get("fieldConfig", {}),
        })
    return panels


def get_datasources() -> list:
    """Return all configured datasources (used to resolve MySQL datasource UID)."""
    return _get("/api/datasources")
