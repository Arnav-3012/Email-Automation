"""Executes Grafana panel queries via /api/ds/query and returns pandas DataFrames."""

import logging
from types import ModuleType
from typing import Any

import pandas as pd

from app.grafana_client import GrafanaConnectionError

logger = logging.getLogger(__name__)


def _is_debug() -> bool:
    try:
        from app import config_manager
        return bool(config_manager.get_debug_mode())
    except Exception:
        return False


def _dbg(msg: str) -> None:
    if _is_debug():
        logger.debug(msg)
        print(f"[DEBUG] {msg}", flush=True)


def fetch_panel_data(
    panel_meta: dict[str, Any],
    grafana_client: ModuleType,
    time_from: str = "now-24h",
    time_to: str = "now",
    credentials: dict = None,
) -> pd.DataFrame:
    """Query Grafana for a panel's data and return it as a DataFrame.

    Detects datasource type from the first target and routes to the
    appropriate fetch function. Raises ValueError for SQL panels with no
    valid query so the caller can fall back to a screenshot.
    """
    targets = panel_meta.get("targets", [])
    if not targets:
        return pd.DataFrame()

    ds_type = (
        panel_meta.get("datasource_type")
        or (panel_meta.get("targets", [{}])[0].get("datasource", {}).get("type", ""))
    ).lower()

    ds_uid = (
        panel_meta.get("datasource_uid")
        or (panel_meta.get("targets", [{}])[0].get("datasource", {}).get("uid", ""))
    )

    _dbg(f"fetch_panel_data: panel='{panel_meta.get('title')}' ds_type={ds_type!r} ds_uid={ds_uid!r}")
    print(f"[data_fetcher] Panel '{panel_meta.get('title')}' datasource: {ds_type}")

    if "testdata" in ds_type or ds_uid == "-- Grafana --":
        _dbg("fetch_panel_data: routing to TestData fetcher")
        return _fetch_testdata(panel_meta, grafana_client, time_from, time_to, credentials)

    _dbg("fetch_panel_data: routing to SQL fetcher")
    return _fetch_sql(panel_meta, grafana_client, time_from, time_to, credentials)


def _fetch_testdata(
    panel_meta: dict[str, Any],
    grafana_client: ModuleType,
    time_from: str,
    time_to: str,
    credentials: dict = None,
) -> pd.DataFrame:
    """Fetch data from Grafana TestData datasource."""
    targets = panel_meta.get("targets", [])
    all_frames = []

    ds_uid = panel_meta.get("datasource_uid", "-- Grafana --")
    for i, target in enumerate(targets):
        try:
            scenario = target.get("scenarioId", "random_walk")

            queries = [
                {
                    "datasource": {"uid": ds_uid, "type": "testdata"},
                    "scenarioId": scenario,
                    "refId": chr(65 + i),
                    "intervalMs": 60000,
                    "maxDataPoints": 500,
                    "alias": target.get("alias", ""),
                    "seriesCount": target.get("seriesCount", 1),
                    "stringInput": target.get("stringInput", ""),
                    "lines": target.get("lines", 10),
                }
            ]
            payload = {
                "queries": queries,
                "from": time_from,
                "to": time_to,
            }

            response = grafana_client.execute_ds_query(payload, credentials=credentials)
            df = _parse_response(response, queries)
            if not df.empty:
                all_frames.append(df)
        except Exception as e:
            _dbg(f"_fetch_testdata: target {i} scenario={scenario!r} failed: {e}")
            print(f"[data_fetcher] TestData target {i} failed: {e}")

    if not all_frames:
        return pd.DataFrame()
    return pd.concat(all_frames, ignore_index=True)


def _fetch_sql(
    panel_meta: dict[str, Any],
    grafana_client: ModuleType,
    time_from: str,
    time_to: str,
    credentials: dict = None,
) -> pd.DataFrame:
    """Fetch data from SQL datasource (MySQL, PostgreSQL etc)."""
    targets = panel_meta.get("targets", [])
    queries = _build_queries(
        targets,
        panel_meta.get("datasource_uid", ""),
        panel_meta.get("datasource_type", ""),
    )

    if not queries:
        raise ValueError(
            f"No SQL query found in panel '{panel_meta.get('title')}'. "
            f"Datasource may not be supported."
        )

    payload = {
        "queries": queries,
        "from": time_from,
        "to": time_to,
    }

    try:
        _dbg(f"_fetch_sql: posting {len(queries)} query/queries to /api/ds/query")
        response = grafana_client.execute_ds_query(payload, credentials=credentials)
        result = _parse_response(response, queries)
        _dbg(f"_fetch_sql: got DataFrame shape={result.shape}")
        if result.empty:
            # 200 OK but no frames — either Grafana rejected the query per-refId
            # (error embedded in the results object, not the HTTP status) or the
            # query genuinely returned zero rows. Surface whichever it is instead
            # of silently returning empty, so the caller can log the real cause.
            per_ref_errors = _extract_result_errors(response, queries)
            if per_ref_errors:
                raise ValueError(
                    f"Grafana query error for panel '{panel_meta.get('title')}': "
                    f"{'; '.join(per_ref_errors)}"
                )
            _dbg(f"_fetch_sql: query executed but returned 0 rows. Raw response: {response}")
            print(
                f"[data_fetcher] Panel '{panel_meta.get('title')}' query returned 0 rows. "
                f"Raw response: {response}"
            )
            result.attrs["zero_row_diagnostic"] = (
                f"Grafana returned HTTP 200 with 0 rows for refId(s) "
                f"{[q['refId'] for q in queries]}. Raw results keys: "
                f"{list(response.get('results', {}).keys())}. "
                f"Query sent: {queries}"
            )
        return result
    except GrafanaConnectionError as e:
        # Re-raise so runner.py logs the real Grafana error (e.g. HTTP 400
        # with response body) instead of silently treating this as "no data".
        raise
    except ValueError:
        raise
    except Exception as e:
        _dbg(f"_fetch_sql: failed: {e}")
        print(f"[data_fetcher] SQL fetch failed: {e}")
        return pd.DataFrame()


def _extract_result_errors(
    response: dict[str, Any],
    queries: list[dict[str, Any]],
) -> list[str]:
    """Pull per-refId error messages out of a 200 OK /api/ds/query response.

    Grafana can return HTTP 200 with an error embedded in results[refId].error
    (e.g. bad SQL syntax caught by the plugin, not the HTTP layer). These never
    raise HTTPError, so they'd otherwise look identical to "zero rows".
    """
    results = response.get("results", {})
    errors = []
    for query in queries:
        ref_id = query["refId"]
        ref_result = results.get(ref_id, {})
        err = ref_result.get("error") or ref_result.get("errorSource")
        if err:
            errors.append(f"[{ref_id}] {err}")
    return errors


def _build_queries(
    targets: list[dict[str, Any]],
    datasource_uid: str,
    datasource_type: str = "",
) -> list[dict[str, Any]]:
    """Build the queries list for the /api/ds/query payload from panel targets."""
    queries: list[dict[str, Any]] = []
    for i, target in enumerate(targets):
        raw_sql = (
            target.get("rawSql")
            or target.get("rawQuery")
            or (target.get("sql") or {}).get("rawSql")
            or target.get("query")
            or ""
        )
        target_ds = target.get("datasource") or {}
        ds_uid = (
            target_ds.get("uid")
            or target.get("datasourceUid")
            or datasource_uid
            or ""
        )
        ds_type = target_ds.get("type") or datasource_type or ""
        if not raw_sql or not ds_uid:
            continue
        datasource: dict[str, Any] = {"uid": ds_uid}
        if ds_type:
            datasource["type"] = ds_type
        queries.append({
            "datasource": datasource,
            "rawSql": raw_sql,
            "format": "table",
            "refId": chr(65 + i),
            "intervalMs": 60000,
            "maxDataPoints": 500,
        })
    return queries


def _parse_response(
    response: dict[str, Any],
    queries: list[dict[str, Any]],
) -> pd.DataFrame:
    """Parse the /api/ds/query response into a single DataFrame.

    Iterates over each refId in the response, converts each frame to a
    DataFrame, and concatenates them. Returns an empty DataFrame if
    there are no frames or the response is malformed.
    """
    results = response.get("results", {})
    frames: list[pd.DataFrame] = []

    for query in queries:
        ref_id = query["refId"]
        ref_result = results.get(ref_id, {})
        for frame in ref_result.get("frames", []):
            df = _frame_to_dataframe(frame)
            if not df.empty:
                frames.append(df)

    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)


def _frame_to_dataframe(frame: dict[str, Any]) -> pd.DataFrame:
    """Convert a single Grafana data frame dict to a pandas DataFrame.

    Grafana frames carry column names in schema.fields and parallel value
    arrays in data.values. Timestamps (type=="time") are converted from
    Unix milliseconds to pandas datetime.
    """
    fields: list[dict[str, Any]] = frame.get("schema", {}).get("fields", [])
    values: list[list[Any]] = frame.get("data", {}).get("values", [])

    if not fields or not values or len(fields) != len(values):
        return pd.DataFrame()

    col_data = {
        field.get("name", f"col_{i}"): values[i]
        for i, field in enumerate(fields)
    }

    df = pd.DataFrame(col_data)

    # Convert time columns (millisecond Unix timestamps) to datetime
    for i, field in enumerate(fields):
        col_name = field.get("name", f"col_{i}")
        if field.get("type") == "time" and col_name in df.columns:
            df[col_name] = pd.to_datetime(df[col_name], unit="ms", errors="coerce")

    return df
