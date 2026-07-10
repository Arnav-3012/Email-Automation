"""Grafana REST API client — all HTTP calls to the Grafana instance live here."""

import logging
import requests

from app import config_manager

logger = logging.getLogger(__name__)


def _is_debug() -> bool:
    """Return True when debug_mode is enabled in config."""
    try:
        return bool(config_manager.get_debug_mode())
    except Exception:
        return False


def _dbg(msg: str) -> None:
    """Emit msg at DEBUG level when debug_mode is on."""
    if _is_debug():
        logger.debug(msg)
        print(f"[DEBUG] {msg}", flush=True)


def _warn(msg: str) -> None:
    """Always emit a WARNING — used for unexpected-but-non-fatal API responses."""
    logger.warning(msg)
    print(f"[WARNING] {msg}", flush=True)


class GrafanaConnectionError(Exception):
    """Raised when a Grafana API call fails or returns an unexpected response."""


def _get_session(credentials: dict = None, org_id: int = None) -> requests.Session:
    """Return a Session using Basic Auth and X-Grafana-Org-Id for cross-org access.

    If credentials dict is provided (keys: grafana_username, grafana_password),
    those are used instead of the global config.json credentials.
    """
    settings = config_manager.get_grafana_settings()
    if org_id is None:
        org_id = settings.get("org_id", 1)
    if credentials:
        username = credentials.get("grafana_username", "")
        password = credentials.get("grafana_password", "")
    else:
        username = settings.get("username", "")
        password = settings.get("password", "")
    session = requests.Session()
    session.auth = (username, password)
    session.headers.update({
        "X-Grafana-Org-Id": str(org_id),
        "Content-Type": "application/json",
    })
    return session


def _get(path: str, params: dict = None, credentials: dict = None, org_id: int = None) -> any:
    """GET {base_url}{path} and return parsed JSON. Raises GrafanaConnectionError on any failure.

    If the X-Grafana-Org-Id header is rejected (401/403) — which can happen against
    older Grafana 9.x servers — automatically retries once with ?orgId= as a query
    param before giving up.
    """
    settings = config_manager.get_grafana_settings()
    base_url = settings.get("url", "").rstrip("/")
    if org_id is None:
        org_id = settings.get("org_id", 1)
    session = _get_session(credentials, org_id=org_id)
    url = f"{base_url}{path}"
    _dbg(f"GET {url} | org_id={org_id} | params={params}")
    try:
        resp = session.get(url, params=params, timeout=10)
        _dbg(f"GET {url} → status={resp.status_code}")

        # If header-based org switching failed, retry with query param
        if resp.status_code in (401, 403) and org_id != 1:
            retry_params = dict(params) if params else {}
            retry_params["orgId"] = org_id
            _dbg(f"Retrying {url} with ?orgId={org_id} query param")
            resp = session.get(url, params=retry_params, timeout=10)
            _dbg(f"Retry {url} → status={resp.status_code}")

        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError as e:
        raise GrafanaConnectionError(f"Cannot reach Grafana at {base_url}: {e}")
    except requests.exceptions.HTTPError as e:
        raise GrafanaConnectionError(f"HTTP {resp.status_code} from {path}: {e}")
    except Exception as e:
        raise GrafanaConnectionError(f"Request failed: {e}")


def _post(path: str, payload: dict, credentials: dict = None) -> any:
    """POST {base_url}{path} with a JSON payload. Raises GrafanaConnectionError on any failure."""
    settings = config_manager.get_grafana_settings()
    base_url = settings.get("url", "").rstrip("/")
    session = _get_session(credentials)
    url = f"{base_url}{path}"
    _dbg(f"POST {url}")
    try:
        resp = session.post(url, json=payload, timeout=30)
        _dbg(f"POST {url} -> status={resp.status_code}")
        if resp.status_code == 400:
            _warn(
                f"HTTP 400 from {path}. Request body: {payload}. "
                f"Response: {resp.text[:500]}"
            )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError as e:
        raise GrafanaConnectionError(f"Cannot reach Grafana at {base_url}: {e}")
    except requests.exceptions.HTTPError as e:
        raise GrafanaConnectionError(
            f"HTTP {resp.status_code} from {path}: {e} — response body: {resp.text[:500]}"
        )
    except Exception as e:
        raise GrafanaConnectionError(f"Request failed: {e}")


def execute_ds_query(payload: dict, credentials: dict = None) -> dict:
    """POST to /api/ds/query and return the full response dict."""
    return _post("/api/ds/query", payload, credentials=credentials)


def test_connection(credentials: dict = None) -> dict:
    """Ping /api/health, log the Grafana version, and return the response dict."""
    result = _get("/api/health", credentials=credentials)
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


def get_organisations(credentials: dict = None) -> list:
    """Return orgs this account belongs to via GET /api/user/orgs (works for all roles).

    GET /api/user/orgs returns only the orgs the authenticated user is a member of,
    regardless of whether they have Server Admin. Falls back to current org only if
    the call fails.
    """
    settings = config_manager.get_grafana_settings()
    base_url = settings.get("url", "").rstrip("/")
    if credentials:
        username = credentials.get("grafana_username", "")
        password = credentials.get("grafana_password", "")
    else:
        username = settings.get("username", "")
        password = settings.get("password", "")

    url = f"{base_url}/api/user/orgs"
    _dbg(f"GET {url} (listing orgs for authenticated user)")
    try:
        resp = requests.get(url, auth=(username, password), timeout=10)
        _dbg(f"GET {url} → status={resp.status_code}")
        if resp.status_code == 200:
            orgs = resp.json()
            # /api/user/orgs returns {orgId, name, role} — normalise to {id, name}
            normalised = [
                {"id": o.get("orgId", o.get("id")), "name": o.get("name", ""), "role": o.get("role", "")}
                for o in orgs
            ]
            _dbg(
                f"GET /api/user/orgs → {len(normalised)} org(s): "
                + ", ".join(f"{o['name']} (ID:{o['id']}, role:{o.get('role','')})" for o in normalised)
            )
            if len(normalised) == 0:
                _warn("Expected at least one org but /api/user/orgs returned 0 — check account permissions")
            elif len(normalised) == 1:
                _dbg("Only one org returned — org dropdown will show a single entry (no switching needed)")
            return normalised

        _warn(f"GET /api/user/orgs returned HTTP {resp.status_code} — falling back to current org")
    except Exception as e:
        _warn(f"GET /api/user/orgs failed with exception: {e} — falling back to current org")

    # Fallback: return just the current org so the UI always has something to show
    try:
        current = _get("/api/org", credentials=credentials)
        _dbg(f"Fallback: got current org via /api/org: {current}")
        return [{"id": current.get("id", 1), "name": current.get("name", "Default")}]
    except Exception as e:
        _warn(f"Fallback /api/org also failed: {e}")
        return []


def get_current_org_id() -> int:
    """Return the org_id currently stored in config."""
    return int(config_manager.get_grafana_settings().get("org_id", 1))


def get_folders(credentials: dict = None) -> list:
    """Return all top-level Grafana folders, prepending General for root dashboards."""
    folders = _get("/api/folders", credentials=credentials)
    _dbg(f"get_folders → {len(folders)} folder(s) returned")
    try:
        all_dash = _get_all_dashboards(credentials=credentials)
        if any(not d.get("folderUid") for d in all_dash):
            folders = [{"uid": "general", "title": "General (No Folder)"}] + folders
    except Exception:
        pass
    return folders


def get_subfolders(folder_uid: str, credentials: dict = None) -> list:
    """Return child folders of a given folder, compatible with Grafana 8/9 and 10+.

    For the special "sharedwithme" virtual folder:
      - /api/folders/{uid}/children always returns 404, so we fall back to
        /api/search?type=dash-folder&starred=false and return any folder-like
        groupings accessible to the user that aren't in their own top-level list.
    For "general": returns [] immediately.
    For real folders: tries /api/folders/{uid}/children (Grafana 10+), falls back
      to /api/search?folderUid={uid}&type=dash-folder (Grafana 8/9).
    """
    _dbg(f"get_subfolders called for folder_uid={folder_uid!r}")

    if folder_uid == "general":
        _dbg("get_subfolders: general folder — skipping, no subfolders")
        return []

    if folder_uid == "sharedwithme":
        return _get_shared_with_me_folders(credentials=credentials)

    settings = config_manager.get_grafana_settings()
    base_url = settings.get("url", "").rstrip("/")
    session = _get_session(credentials)
    url = f"{base_url}/api/folders/{folder_uid}/children"
    _dbg(f"GET {url}")
    try:
        resp = session.get(url, timeout=10)
        _dbg(f"GET {url} → status={resp.status_code}")
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
        filtered = [f for f in subfolders if f["uid"] != folder_uid]
        _dbg(f"get_subfolders: /children returned {len(filtered)} subfolder(s)")
        return filtered

    if resp.status_code == 404:
        _dbg(f"get_subfolders: /children 404 — falling back to /api/search?folderUid={folder_uid}&type=dash-folder")
        results = _get("/api/search", params={"folderUid": folder_uid, "type": "dash-folder"},
                       credentials=credentials)
        subfolders = [{"uid": item["uid"], "title": item["title"]} for item in results]
        filtered = [f for f in subfolders if f["uid"] != folder_uid]
        _dbg(f"get_subfolders: search fallback returned {len(filtered)} subfolder(s)")
        return filtered

    raise GrafanaConnectionError(
        f"HTTP {resp.status_code} from /api/folders/{folder_uid}/children"
    )


def _get_shared_with_me_folders(credentials: dict = None) -> list:
    """Return virtual subfolder groupings for the 'Shared with me' folder.

    /api/folders/sharedwithme/children always 404s, so we query
    /api/search?type=dash-db for all accessible dashboards and group them
    by folderTitle for entries whose folderUid differs from any top-level
    folder the user owns — those belong to 'Shared with me'.
    """
    _dbg("_get_shared_with_me_folders: fetching shared dashboards via /api/search")
    try:
        all_dashboards = _get(
            "/api/search",
            params={"type": "dash-db", "limit": 5000},
            credentials=credentials,
        )
        _dbg(f"_get_shared_with_me_folders: /api/search returned {len(all_dashboards)} dashboard(s)")
    except GrafanaConnectionError as e:
        _warn(f"_get_shared_with_me_folders: search failed: {e}")
        return []

    # Fetch the user's own top-level folder UIDs so we can exclude them
    try:
        own_folders = _get("/api/folders", credentials=credentials)
        own_folder_uids = {f["uid"] for f in own_folders}
        _dbg(f"_get_shared_with_me_folders: user's own folder UIDs: {own_folder_uids}")
    except Exception:
        own_folder_uids = set()

    # Dashboards shared with this user live in folders they don't own
    seen_uids: set = set()
    subfolders: list = []
    for dash in all_dashboards:
        folder_uid = dash.get("folderUid", "")
        folder_title = dash.get("folderTitle", "")
        if not folder_uid or folder_uid in own_folder_uids:
            continue
        if folder_uid not in seen_uids:
            seen_uids.add(folder_uid)
            subfolders.append({"uid": folder_uid, "title": folder_title or folder_uid})

    _dbg(
        f"_get_shared_with_me_folders: found {len(subfolders)} shared subfolder(s): "
        + ", ".join(f"{s['title']} ({s['uid']})" for s in subfolders)
    )
    return subfolders


_dashboard_cache: dict = {}


def _get_all_dashboards(credentials: dict = None) -> list:
    """Fetch all dashboards once per org and cache by org_id."""
    global _dashboard_cache
    settings = config_manager.get_grafana_settings()
    org_id = settings.get("org_id", 1)
    if org_id not in _dashboard_cache:
        _dbg(f"_get_all_dashboards: cache miss for org_id={org_id}, fetching from API")
        _dashboard_cache[org_id] = _get(
            "/api/search", params={"type": "dash-db", "limit": 5000},
            credentials=credentials,
        )
        _dbg(f"_get_all_dashboards: cached {len(_dashboard_cache[org_id])} dashboard(s) for org_id={org_id}")
    else:
        _dbg(f"_get_all_dashboards: cache hit for org_id={org_id} ({len(_dashboard_cache[org_id])} dashboards)")
    return _dashboard_cache[org_id]


def clear_dashboard_cache() -> None:
    """Reset the dashboard cache for all orgs."""
    global _dashboard_cache
    _dashboard_cache = {}
    _dbg("clear_dashboard_cache: dashboard cache cleared")


def get_dashboards_in_folder(folder_uid: str, credentials: dict = None) -> list:
    """Return dashboards inside the given folder, filtered client-side from a full fetch.

    For "sharedwithme": returns dashboards whose folderUid is not in the user's own folders.
    For "general": returns dashboards with no folderUid.
    For real folders: returns dashboards whose folderUid matches.
    """
    _dbg(f"get_dashboards_in_folder: folder_uid={folder_uid!r}")

    if folder_uid == "sharedwithme":
        return _get_shared_with_me_dashboards(credentials=credentials)

    all_dashboards = _get_all_dashboards(credentials=credentials)
    if folder_uid == "general":
        result = [d for d in all_dashboards if not d.get("folderUid")]
    else:
        result = [d for d in all_dashboards if d.get("folderUid") == folder_uid]
    _dbg(f"get_dashboards_in_folder: found {len(result)} dashboard(s) for folder_uid={folder_uid!r}")
    return result


def _get_shared_with_me_dashboards(credentials: dict = None) -> list:
    """Return all dashboards accessible via sharing (not in user's own folders)."""
    _dbg("_get_shared_with_me_dashboards: fetching shared dashboards")
    try:
        all_dashboards = _get(
            "/api/search",
            params={"type": "dash-db", "limit": 5000},
            credentials=credentials,
        )
    except GrafanaConnectionError as e:
        _warn(f"_get_shared_with_me_dashboards: search failed: {e}")
        return []

    try:
        own_folders = _get("/api/folders", credentials=credentials)
        own_folder_uids = {f["uid"] for f in own_folders}
    except Exception:
        own_folder_uids = set()

    result = [d for d in all_dashboards if d.get("folderUid") and d.get("folderUid") not in own_folder_uids]
    _dbg(f"_get_shared_with_me_dashboards: found {len(result)} shared dashboard(s)")
    return result


def get_dashboard(uid: str, credentials: dict = None) -> dict:
    """Fetch and return the full dashboard JSON for the given UID."""
    _dbg(f"get_dashboard: uid={uid!r}")
    return _get(f"/api/dashboards/uid/{uid}", credentials=credentials)


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
            "title": panel.get("title") or f"Panel {panel.get('id')}",
            "type": panel.get("type", ""),
            "description": panel.get("description", ""),
            "datasource_uid": panel_ds.get("uid", ""),
            "datasource_type": panel_ds.get("type", ""),
            "targets": panel.get("targets", []),
            "fieldConfig": panel.get("fieldConfig", {}),
        })
    return panels


def get_datasources(credentials: dict = None) -> list:
    """Return all configured datasources (used to resolve MySQL datasource UID)."""
    return _get("/api/datasources", credentials=credentials)


# ---------------------------------------------------------------------------
# Title lookups — used to pre-fill display-name fields in the job form
# ---------------------------------------------------------------------------

def get_dashboard_title(dashboard_uid: str, credentials: dict = None) -> str:
    """Return a dashboard's Grafana title, falling back to its UID if untitled."""
    dashboard_json = get_dashboard(dashboard_uid, credentials=credentials)
    title = dashboard_json.get("dashboard", {}).get("title", "")
    return title or dashboard_uid


def get_panel_title(dashboard_uid: str, panel_id: int, credentials: dict = None) -> str:
    """Return a single panel's title, falling back to 'Panel {id}' if untitled or not found."""
    panels = get_panels(get_dashboard(dashboard_uid, credentials=credentials))
    panel = next((p for p in panels if p["id"] == panel_id), None)
    return panel["title"] if panel else f"Panel {panel_id}"


def get_dashboard_variables(dashboard_uid: str, credentials: dict = None) -> dict:
    """Extract current template variable values from dashboard JSON for use in screenshot URLs.

    Works for dashboards with variables (returns a populated dict) and without
    (returns {} safely). Never raises — a variable-fetch problem should never
    block a screenshot, so any error also returns {}.

    Returns: {var_name: var_value}, e.g. {"region": "us-east", "server": "prod"}.
    Multi-value variables are joined with "|". "All"/$__all selections and
    datasource/interval variables are skipped (not meaningful as URL params).
    """
    try:
        dashboard_json = get_dashboard(dashboard_uid, credentials=credentials)
        templating = dashboard_json.get("dashboard", {}).get("templating", {}).get("list", [])

        variables = {}
        for var in templating:
            var_name = var.get("name", "")
            var_type = var.get("type", "")
            current = var.get("current", {})

            if var_type in ("datasource", "interval"):
                continue

            value = current.get("value", "")

            if isinstance(value, list):
                filtered = [str(v) for v in value if v != "$__all" and v != "All"]
                if filtered:
                    value = "|".join(filtered)
                else:
                    continue

            if not value or value == "$__all" or value == "All":
                continue

            if var_name:
                variables[var_name] = str(value)

        return variables
    except Exception as e:
        _warn(f"Could not fetch template variables for {dashboard_uid}: {e}")
        return {}


# ---------------------------------------------------------------------------
# Variable option lists — for the "Dashboard Variables" job-config UI
# ---------------------------------------------------------------------------

# Only SQL-family datasources support re-running the variable's raw query
# through /api/ds/query (same mechanism app/data_fetcher.py uses for panels).
# Other datasource types (Prometheus, InfluxDB, etc.) each need their own
# query-building rules, so they're reported as fetch_failed instead of
# guessed at.
_SQL_DATASOURCE_TYPES = {"mysql", "postgres", "postgresql", "mssql"}


def get_dashboard_variable_options(dashboard_uid: str, credentials: dict = None) -> dict:
    """Fetch all selectable options for each template variable in a dashboard.

    Always resolved fresh (dashboard JSON +, where possible, a live query) —
    never cached — so options reflect current Grafana state.

    Resolution per variable type:
      - custom/constant: values are static text already in the variable
        definition — parsed directly, no extra API call.
      - query, backed by a SQL datasource (MySQL/Postgres/MSSQL): the
        variable's raw SQL is re-executed via /api/ds/query for live values.
      - query on any other datasource, or on any error: options can't be
        reliably resolved. Reported with fetch_failed=True rather than a
        possibly-stale or empty list, so callers can show a "data failed to
        load" state and fall back to the dashboard's current value.

    Returns {var_name: {label, options, has_all, current, type, fetch_failed}}.
    Returns {} if the dashboard has no user-selectable variables, or on any
    unrecoverable error. Never raises.
    """
    try:
        dashboard_json = get_dashboard(dashboard_uid, credentials=credentials)
        templating = dashboard_json.get("dashboard", {}).get("templating", {}).get("list", [])
        if not templating:
            return {}

        result = {}
        for var in templating:
            var_name = var.get("name", "")
            if not var_name:
                continue
            var_type = var.get("type", "")
            if var_type in ("datasource", "interval", "textbox"):
                continue

            var_label = var.get("label", "") or var_name
            include_all = bool(var.get("includeAll", False))
            current = var.get("current", {})
            current_value = current.get("value", "")
            if isinstance(current_value, list):
                current_value = current_value[0] if current_value else ""

            options: list = []
            fetch_failed = False

            if var_type in ("custom", "constant"):
                options = _parse_static_variable_options(var)
            elif var_type == "query":
                try:
                    options = _fetch_sql_variable_options(var, credentials=credentials)
                    if not options:
                        fetch_failed = True
                except Exception as e:
                    _warn(
                        f"get_dashboard_variable_options: query resolution failed "
                        f"for {dashboard_uid}/{var_name}: {e}"
                    )
                    options = []
                    fetch_failed = True
            else:
                # Unknown/unsupported variable type — nothing safe to offer.
                fetch_failed = True

            result[var_name] = {
                "label": var_label,
                "options": options,
                "has_all": include_all,
                "current": str(current_value),
                "type": var_type,
                "fetch_failed": fetch_failed,
            }

        return result
    except Exception as e:
        _warn(f"Could not fetch variable options for {dashboard_uid}: {e}")
        return {}


def _parse_static_variable_options(var: dict) -> list:
    """Parse a custom/constant variable's comma-separated value list.

    Each entry may be "text : value" (Grafana's custom-variable shorthand)
    or a bare value.
    """
    raw = var.get("query", "")
    if isinstance(raw, dict):
        raw = raw.get("query", "")
    raw = str(raw or "")

    options = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        text = part.split(":", 1)[0].strip() if ":" in part else part
        if text and text not in options:
            options.append(text)
    return options


def _fetch_sql_variable_options(var: dict, credentials: dict = None) -> list:
    """Re-run a query-type variable's raw SQL via /api/ds/query for live options.

    Only supported for SQL-family datasources — returns [] (caller treats
    this as fetch_failed) if the datasource isn't SQL-family, has no query
    text, or the query yields no rows.
    """
    datasource = var.get("datasource") or {}
    if not isinstance(datasource, dict):
        return []
    ds_type = (datasource.get("type") or "").lower()
    ds_uid = datasource.get("uid") or ""
    if ds_type not in _SQL_DATASOURCE_TYPES or not ds_uid:
        return []

    raw_query = var.get("query", "")
    if isinstance(raw_query, dict):
        sql_text = raw_query.get("rawSql") or raw_query.get("query") or raw_query.get("sql", "")
    else:
        sql_text = str(raw_query or "")
    if not sql_text:
        return []

    payload = {
        "queries": [{
            "datasource": {"uid": ds_uid},
            "rawSql": sql_text,
            "format": "table",
            "refId": "A",
            "intervalMs": 60000,
            "maxDataPoints": 1000,
        }],
        "from": "now-5y",
        "to": "now",
    }
    response = execute_ds_query(payload, credentials=credentials)
    frames = response.get("results", {}).get("A", {}).get("frames", [])
    if not frames:
        return []

    values = frames[0].get("data", {}).get("values", [])
    if not values:
        return []

    seen = []
    for v in values[0]:
        s = str(v)
        if s and s not in seen:
            seen.append(s)
    return seen
