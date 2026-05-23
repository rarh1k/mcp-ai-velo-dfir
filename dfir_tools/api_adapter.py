"""
Compatibility adapter that wraps velociraptor_api.py.

WHY THIS FILE EXISTS
--------------------
velociraptor_api.py has non-obvious return types and signatures:

  start_collection()  → list[dict]   (NOT a flow_id string)
  get_flow_status()   → str           "FINISHED" | "RUNNING"   (NOT a dict)
                        requires artifact parameter (NOT just flow_id + client_id)
  realtime_collection() → list[dict]  has NO timeout parameter

Every public function here hides these quirks behind stable interfaces.
All DFIR tool modules import ONLY from this adapter, never from velociraptor_api directly.

ADDING NEW API METHODS
----------------------
If a new method is needed, add it here with the same pattern:
  - call the underlying velociraptor_api function
  - convert the result to a Python-friendly type
  - document the underlying method used
"""

import logging
import time

import velociraptor_api as _vapi

logger = logging.getLogger("dfir_tools.api_adapter")

_POLL_INTERVAL_S = 3


# ---------------------------------------------------------------------------
# start_artifact_collection  →  flow_id: str
# ---------------------------------------------------------------------------

def start_artifact_collection(
    client_id: str,
    artifact: str,
    parameters: dict | None = None,
    timeout: int | None = None,
    org_id: str | None = None,
) -> str:
    """
    Start a collection flow on the client.
    Returns: flow_id string.

    Underlying API: velociraptor_api.start_collection()
    That function returns list[dict] like:
        [{"flow_id": "F.xxx", "artifacts": [...], "timeout": N, "specs": {...}}]
    We extract flow_id from result[0]["flow_id"].
    """
    result = _vapi.start_collection(
        client_id=client_id,
        artifact=artifact,
        parameters=parameters,
        timeout=timeout,
        org_id=org_id,
    )

    if not result or not isinstance(result, list):
        raise RuntimeError(
            f"start_collection returned unexpected result for {artifact}: {result!r}"
        )

    flow_id = result[0].get("flow_id", "")
    if not flow_id:
        raise RuntimeError(
            f"start_collection result missing flow_id for {artifact}: {result[0]!r}"
        )

    logger.debug("Started collection %s → flow_id=%s", artifact, flow_id)
    return flow_id


# ---------------------------------------------------------------------------
# poll_flow_until_done  →  ("FINISHED" | "TIMEOUT" | "ERROR", backtrace_or_None)
# ---------------------------------------------------------------------------

def poll_flow_until_done(
    client_id: str,
    artifact: str,
    flow_id: str,
    timeout: int = 300,
    org_id: str | None = None,
) -> tuple[str, str | None]:
    """
    Poll until the flow completes or the timeout expires.

    Returns: (state_str, backtrace_or_None)
      state_str  in {"FINISHED", "TIMEOUT", "ERROR"}
      backtrace is set when state=="ERROR"

    Underlying API: velociraptor_api.get_flow_status()
    That function returns the string "FINISHED" or "RUNNING".
    We supplement it with a direct VQL flow state check for error detection.
    """
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        # Primary check: completion message in flow logs
        status_str = _vapi.get_flow_status(
            client_id=client_id,
            flow_id=flow_id,
            artifact=artifact,
            org_id=org_id,
        )
        if status_str == "FINISHED":
            return "FINISHED", None

        # Secondary: check flow state for error detection
        # (get_flow_status only knows about completion messages, not error states)
        err_state, backtrace = _check_flow_error(client_id, flow_id, org_id)
        if err_state:
            return "ERROR", backtrace

        remaining = deadline - time.monotonic()
        time.sleep(min(_POLL_INTERVAL_S, max(1.0, remaining)))

    return "TIMEOUT", None


def _check_flow_error(
    client_id: str,
    flow_id: str,
    org_id: str | None,
) -> tuple[bool, str | None]:
    """
    Check if the flow has entered an error or cancelled state via server VQL.
    Returns: (is_error: bool, backtrace_or_None)
    """
    try:
        rows = _vapi.run_vql_query(
            vql=(
                f"SELECT state, backtrace FROM flows("
                f"client_id={_vapi.vql_literal(client_id)}) "
                f"WHERE session_id = {_vapi.vql_literal(flow_id)}"
            ),
            org_id=org_id,
        )
        if rows:
            state = str(rows[0].get("state", "")).upper()
            if state in ("ERROR", "CANCELLED"):
                return True, rows[0].get("backtrace", "")
    except Exception as exc:
        logger.debug("_check_flow_error VQL failed (non-fatal): %s", exc)
    return False, None


# ---------------------------------------------------------------------------
# read_flow_results  →  list[dict]
# ---------------------------------------------------------------------------

def read_flow_results(
    client_id: str,
    artifact: str,
    flow_id: str,
    fields: str = "*",
    org_id: str | None = None,
) -> list[dict]:
    """
    Retrieve result rows from a completed flow.

    Velociraptor named sources require the full artifact/SourceName path.
    We query artifacts_with_results from the flow to discover actual source
    names, then read from each matching source and concatenate results.
    """
    base_artifact = artifact.split("/")[0]

    # Discover which sources actually have results for this flow
    try:
        flow_rows = _vapi.run_vql_query(
            vql=(
                f"SELECT artifacts_with_results FROM flows("
                f"client_id={_vapi.vql_literal(client_id)}) "
                f"WHERE session_id = {_vapi.vql_literal(flow_id)}"
            ),
            org_id=org_id,
        )
        sources = flow_rows[0].get("artifacts_with_results", []) if flow_rows else []
        matching = [s for s in sources if s.startswith(base_artifact)]
    except Exception as exc:
        logger.debug("artifacts_with_results lookup failed (non-fatal): %s", exc)
        matching = []

    # Fall back to the supplied artifact name if no sources found
    if not matching:
        matching = [artifact]

    all_rows: list[dict] = []
    for source in matching:
        rows = _vapi.get_flow_results(
            client_id=client_id,
            flow_id=flow_id,
            artifact=source,
            fields=fields,
            org_id=org_id,
        )
        all_rows.extend(rows or [])

    return all_rows


# ---------------------------------------------------------------------------
# exec_artifact_sync  →  (flow_id, rows, error_str)
# ---------------------------------------------------------------------------

def exec_artifact_sync(
    client_id: str,
    artifact: str,
    parameters: dict | None = None,
    timeout: int = 120,
    org_id: str | None = None,
) -> tuple[str, list[dict] | None, str | None]:
    """
    Full synchronous artifact execution:
        start → poll → fetch results

    Returns: (flow_id, rows, error_str)
      If error_str is not None, rows is None.
      flow_id is always returned if collection started.
    """
    # 1. Start
    try:
        flow_id = start_artifact_collection(
            client_id=client_id,
            artifact=artifact,
            parameters=parameters,
            timeout=timeout,
            org_id=org_id,
        )
    except Exception as exc:
        return "", None, f"start_artifact_collection failed: {exc}"

    # 2. Poll
    state, backtrace = poll_flow_until_done(
        client_id=client_id,
        artifact=artifact,
        flow_id=flow_id,
        timeout=timeout + 60,
        org_id=org_id,
    )

    if state == "ERROR":
        return flow_id, None, f"Flow error: {backtrace or 'unknown'}"
    if state == "TIMEOUT":
        return flow_id, None, f"Flow did not complete within {timeout}s"

    # 3. Fetch results
    try:
        rows = read_flow_results(
            client_id=client_id,
            artifact=artifact,
            flow_id=flow_id,
            org_id=org_id,
        )
    except Exception as exc:
        return flow_id, None, f"read_flow_results failed: {exc}"

    return flow_id, rows, None


# ---------------------------------------------------------------------------
# run_server_vql  →  list[dict]
# ---------------------------------------------------------------------------

def run_server_vql(vql: str, org_id: str | None = None) -> list[dict]:
    """
    Execute server-side VQL and return rows.

    Underlying API: velociraptor_api.run_vql_query()
    """
    return _vapi.run_vql_query(vql=vql, org_id=org_id) or []
