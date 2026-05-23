"""
DFIR execution tools: run_shell, run_powershell, run_vql_raw.

Execution flow for all three:
    api_adapter.exec_artifact_sync()
        → start_artifact_collection()   [extracts flow_id from list[dict] result]
        → poll_flow_until_done()        [handles "FINISHED"/"RUNNING" str from get_flow_status]
        → read_flow_results()
    parse output rows
    return make_ok/make_err envelope
"""
import logging

from dfir_tools.api_adapter import exec_artifact_sync
from dfir_tools.helpers import audit_log, make_err, make_ok, parse_exec_rows

logger = logging.getLogger("dfir_tools.execution")

ARTIFACT_RUN_SHELL = "Custom.DFIR.RunShell"
ARTIFACT_RUN_POWERSHELL = "Custom.DFIR.RunPowerShell"
ARTIFACT_RUN_VQL = "Custom.DFIR.RunClientVQL"

# Source name suffix appended by Velociraptor when querying multi-source artifacts.
# Custom.DFIR.RunShell has source name "ShellOutput", so the full artifact ref is:
#   "Custom.DFIR.RunShell/ShellOutput"
# This is needed when calling get_flow_results.
_SOURCE_SHELL = "Custom.DFIR.RunShell/ShellOutput"
_SOURCE_PS = "Custom.DFIR.RunPowerShell/PowerShellOutput"
_SOURCE_VQL = "Custom.DFIR.RunClientVQL/VQLResults"


# ---------------------------------------------------------------------------
# run_shell
# ---------------------------------------------------------------------------

def run_shell(
    client_id: str,
    command: str,
    timeout_seconds: int = 60,
    case_id: str = "",
    reason: str = "",
    org_id: str = "",
) -> str:
    """
    Execute a shell command on the endpoint (Windows cmd.exe or Linux /bin/sh).

    The artifact detects the OS and picks the appropriate shell.
    The Timeout artifact parameter is informational — the actual flow timeout
    is enforced by Velociraptor via start_collection(timeout=timeout_seconds).
    """
    audit_log("run_shell", client_id, case_id, reason, command=command)

    flow_id, rows, error = exec_artifact_sync(
        client_id=client_id,
        artifact=ARTIFACT_RUN_SHELL,
        parameters={"Command": command},
        timeout=timeout_seconds,
        org_id=org_id or None,
    )

    if error:
        return make_err("run_shell", error, client_id=client_id, case_id=case_id,
                        flow_id=flow_id)

    exec_out = parse_exec_rows(rows)
    return make_ok(
        tool="run_shell",
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        artifact=ARTIFACT_RUN_SHELL,
        rows=rows,
        command=command,
        stdout=exec_out["stdout"],
        stderr=exec_out["stderr"],
        return_code=exec_out["return_code"],
    )


# ---------------------------------------------------------------------------
# run_powershell
# ---------------------------------------------------------------------------

def run_powershell(
    client_id: str,
    script: str,
    timeout_seconds: int = 120,
    case_id: str = "",
    reason: str = "",
    org_id: str = "",
) -> str:
    """
    Execute a PowerShell script on a Windows endpoint.
    Runs: powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command <script>
    """
    audit_log("run_powershell", client_id, case_id, reason,
              script_preview=script[:200])

    flow_id, rows, error = exec_artifact_sync(
        client_id=client_id,
        artifact=ARTIFACT_RUN_POWERSHELL,
        parameters={"Script": script},
        timeout=timeout_seconds,
        org_id=org_id or None,
    )

    if error:
        return make_err("run_powershell", error, client_id=client_id,
                        case_id=case_id, flow_id=flow_id)

    exec_out = parse_exec_rows(rows)
    return make_ok(
        tool="run_powershell",
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        artifact=ARTIFACT_RUN_POWERSHELL,
        rows=rows,
        script_preview=script[:200],
        stdout=exec_out["stdout"],
        stderr=exec_out["stderr"],
        return_code=exec_out["return_code"],
    )


# ---------------------------------------------------------------------------
# run_vql_raw
# ---------------------------------------------------------------------------

def run_vql_raw(
    client_id: str,
    query: str,
    timeout_seconds: int = 120,
    case_id: str = "",
    reason: str = "",
    org_id: str = "",
) -> str:
    """
    Execute arbitrary client-side VQL.

    The artifact wraps the query in:
        SELECT * FROM query(vql=Query)

    The query() VQL plugin evaluates the string as client-side VQL.
    Example: "SELECT Pid, Name, Exe, Username FROM pslist()"
    """
    audit_log("run_vql_raw", client_id, case_id, reason, query=query)

    flow_id, rows, error = exec_artifact_sync(
        client_id=client_id,
        artifact=ARTIFACT_RUN_VQL,
        parameters={"Query": query},
        timeout=timeout_seconds,
        org_id=org_id or None,
    )

    if error:
        return make_err("run_vql_raw", error, client_id=client_id,
                        case_id=case_id, flow_id=flow_id)

    return make_ok(
        tool="run_vql_raw",
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        artifact=ARTIFACT_RUN_VQL,
        rows=rows,
        query=query,
        row_count=len(rows),
    )
