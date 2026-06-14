"""Grafana REST API client — all HTTP calls to the Grafana instance live here."""

import requests
from typing import Any

from app.config_manager import get_grafana_settings


class GrafanaConnectionError(Exception):
    """Raised when a Grafana API call fails or returns an unexpected response."""


def _get_session() -> tuple[str, requests.Session]:
    """Build a requests.Session pre-loaded with the Bearer token header.

    Returns a (base_url, session) tuple. Raises GrafanaConnectionError if
    the config has no URL or API key.
    """
    settings = get_grafana_settings()
    url = settings.get("url", "").rstrip("/")
    api_key = settings.get("api_key", "")
    if not url:
        raise GrafanaConnectionError("Grafana URL is not configured. Go to Settings.")
    if not api_key:
        raise GrafanaConnectionError("Grafana API key is not configured. Go to Settings.")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}"})
    return url, session


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET {base_url}{path} and return parsed JSON. Raises GrafanaConnectionError on any failure."""
    base_url, session = _get_session()
    try:
        resp = session.get(f"{base_url}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError as e:
        raise GrafanaConnectionError(f"Cannot reach Grafana at {base_url}: {e}") from e
    except requests.exceptions.Timeout:
        raise GrafanaConnectionError(f"Request timed out: {base_url}{path}")
    except requests.exceptions.HTTPError as e:
        raise GrafanaConnectionError(f"HTTP {resp.status_code} from {path}: {e}") from e
    except requests.exceptions.RequestException as e:
        raise GrafanaConnectionError(f"Request failed for {path}: {e}") from e


def _post(path: str, payload: dict[str, Any]) -> Any:
    """POST {base_url}{path} with a JSON payload. Raises GrafanaConnectionError on any failure."""
    base_url, session = _get_session()
    try:
        resp = session.post(f"{base_url}{path}", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError as e:
        raise GrafanaConnectionError(f"Cannot reach Grafana at {base_url}: {e}") from e
    except requests.exceptions.Timeout:
        raise GrafanaConnectionError(f"Request timed out: {base_url}{path}")
    except requests.exceptions.HTTPError as e:
        raise GrafanaConnectionError(f"HTTP {resp.status_code} from {path}: {e}") from e
    except requests.exceptions.RequestException as e:
        raise GrafanaConnectionError(f"Request failed for {path}: {e}") from e


def execute_ds_query(payload: dict[str, Any]) -> dict[str, Any]:
    """POST to /api/ds/query and return the full response dict.

    payload must follow the MySQL ds/query format described in CLAUDE.md.
    Raises GrafanaConnectionError on network or HTTP failure.
    """
    return _post("/api/ds/query", payload)


def test_connection() -> dict[str, str]:
    """Ping /api/health and return the response dict.

    Raises GrafanaConnectionError if the server is unreachable or returns an error.
    """
    return _get("/api/health")


def get_folders() -> list[dict[str, Any]]:
    """Return all top-level Grafana folders.

    Each item has at minimum: uid, title, id.
    """
    return _get("/api/folders")


def get_subfolders(folder_uid: str) -> list[dict[str, Any]]:
    """Return child folders of a given folder, compatible with Grafana 8/9 and 10+.

    Tries GET /api/folders/{uid}/children first (Grafana 10+). On 404 falls back to
    GET /api/search?folderUid={uid}&type=dash-folder (Grafana 8/9), normalising the
    search results into the same {uid, title} shape. Any non-404 HTTP error raises
    GrafanaConnectionError. Returns [] for "sharedwithme" without any API call.
    """
    if folder_uid == "sharedwithme":
        return []

    base_url, session = _get_session()
    try:
        resp = session.get(
            f"{base_url}/api/folders/{folder_uid}/children", timeout=10
        )
    except requests.exceptions.ConnectionError as e:
        raise GrafanaConnectionError(f"Cannot reach Grafana at {base_url}: {e}") from e
    except requests.exceptions.Timeout:
        raise GrafanaConnectionError(
            f"Request timed out: {base_url}/api/folders/{folder_uid}/children"
        )
    except requests.exceptions.RequestException as e:
        raise GrafanaConnectionError(
            f"Request failed for /api/folders/{folder_uid}/children: {e}"
        ) from e

    if resp.status_code == 200:
        result = resp.json()
        subfolders = result if isinstance(result, list) else []
        # Filter out the parent folder if the API erroneously returns it as its own child
        return [f for f in subfolders if f["uid"] != folder_uid]

    if resp.status_code == 404:
        # Grafana 8/9 fallback: search for nested folders by parent uid
        results = _get("/api/search", params={"folderUid": folder_uid, "type": "dash-folder"})
        subfolders = [{"uid": item["uid"], "title": item["title"]} for item in results]
        return [f for f in subfolders if f["uid"] != folder_uid]

    raise GrafanaConnectionError(
        f"HTTP {resp.status_code} from /api/folders/{folder_uid}/children"
    )


_dashboard_cache: list[dict[str, Any]] | None = None


def _get_all_dashboards() -> list[dict[str, Any]]:
    """Fetch all dashboards once and cache the result for the current page render."""
    global _dashboard_cache
    if _dashboard_cache is None:
        _dashboard_cache = _get("/api/search", params={"type": "dash-db", "limit": 5000})
    return _dashboard_cache


def clear_dashboard_cache() -> None:
    """Reset the dashboard cache — call at the top of each page render."""
    global _dashboard_cache
    _dashboard_cache = None


def get_dashboards_in_folder(folder_uid: str) -> list[dict[str, Any]]:
    """Return dashboards inside the given folder, filtered client-side from a full fetch.

    /api/search?folderUid= does not filter reliably on all Grafana versions, so we
    fetch all dashboards once (cached) and filter by folderUid here.
    """
    return [d for d in _get_all_dashboards() if d.get("folderUid") == folder_uid]


def get_dashboard(uid: str) -> dict[str, Any]:
    """Fetch and return the full dashboard JSON for the given UID.

    The returned dict has keys: dashboard (panel definitions + queries), meta.
    Raises GrafanaConnectionError if the dashboard is not found.
    """
    return _get(f"/api/dashboards/uid/{uid}")


def get_panels(dashboard_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract panel metadata from a dashboard JSON response.

    Accepts the full response from get_dashboard(). Returns a list of dicts,
    one per panel, with keys: id, title, type, targets, datasource_uid.
    Panels with no targets are included with an empty targets list.
    """
    dashboard = dashboard_json.get("dashboard", {})
    raw_panels = dashboard.get("panels", [])
    panels: list[dict[str, Any]] = []
    for panel in raw_panels:
        panels.append({
            "id": panel.get("id"),
            "title": panel.get("title", "Untitled"),
            "type": panel.get("type", "unknown"),
            "datasource_uid": (panel.get("datasource") or {}).get("uid"),
            "targets": [
                {
                    "refId": t.get("refId", "A"),
                    "rawSql": t.get("rawSql", ""),
                    "format": t.get("format", "time_series"),
                    "datasource_uid": (t.get("datasource") or {}).get("uid"),
                }
                for t in panel.get("targets", [])
            ],
        })
    return panels


def get_datasources() -> list[dict[str, Any]]:
    """Return all configured datasources (used to resolve MySQL datasource UID)."""
    return _get("/api/datasources")
