"""Executes Grafana panel queries via /api/ds/query and returns pandas DataFrames."""

from types import ModuleType
from typing import Any

import pandas as pd

from app.grafana_client import GrafanaConnectionError


def fetch_panel_data(
    panel_meta: dict[str, Any],
    grafana_client: ModuleType,
    time_from: str = "now-24h",
    time_to: str = "now",
) -> pd.DataFrame:
    """Query Grafana for a panel's data and return it as a DataFrame.

    Builds a /api/ds/query payload from the panel's targets, posts it via
    grafana_client.execute_ds_query(), and parses the response frames.
    Returns an empty DataFrame on any error or when the panel has no data.
    Never raises — all failures produce an empty DataFrame.
    """
    queries = _build_queries(panel_meta)
    if not queries:
        return pd.DataFrame()

    payload: dict[str, Any] = {
        "queries": queries,
        "from": time_from,
        "to": time_to,
    }

    try:
        response = grafana_client.execute_ds_query(payload)
    except GrafanaConnectionError:
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    return _parse_response(response, queries)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_queries(panel_meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the queries list for the /api/ds/query payload from panel metadata.

    Each target with a non-empty rawSql becomes one query entry.
    The datasource uid is taken from the target first, then falls back to
    the panel-level datasource_uid.
    """
    queries: list[dict[str, Any]] = []
    panel_ds_uid = panel_meta.get("datasource_uid")

    for target in panel_meta.get("targets", []):
        raw_sql = target.get("rawSql", "").strip()
        if not raw_sql:
            continue
        ds_uid = target.get("datasource_uid") or panel_ds_uid
        if not ds_uid:
            continue
        queries.append({
            "datasource": {"uid": ds_uid},
            "rawSql": raw_sql,
            "format": target.get("format", "time_series"),
            "refId": target.get("refId", "A"),
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
