"""
Shared utilities for all DFIR tools.
"""
import json
import logging
from typing import Any

logger = logging.getLogger("dfir_tools")


# ---------------------------------------------------------------------------
# Unified JSON envelope
#
# Every MCP tool returns this shape on success:
# {
#   "ok": true,
#   "tool": "run_shell",
#   "client_id": "C.xxx",
#   "case_id": "APT-001",
#   "flow_id": "F.xxx",
#   "artifact": "Custom.DFIR.RunShell",
#   "status": "FINISHED",
#   "rows": [...],
#   "files": [...],
#   "error": null,
#   ...tool-specific extra fields...
# }
#
# On error:
# {
#   "ok": false,
#   "tool": "run_shell",
#   "client_id": "C.xxx",
#   "case_id": "APT-001",
#   "flow_id": null,       ← may be present if collection started before error
#   "error": "message",
#   "rows": [],
#   "files": []
# }
# ---------------------------------------------------------------------------

def make_result(
    ok: bool,
    tool: str,
    client_id: str = "",
    case_id: str = "",
    flow_id: str = "",
    artifact: str = "",
    status: str = "",
    rows: list | None = None,
    files: list | None = None,
    error: str | None = None,
    **extra: Any,
) -> str:
    """Build the standard JSON envelope for all DFIR MCP tools."""
    envelope: dict[str, Any] = {
        "ok": ok,
        "tool": tool,
        "client_id": client_id,
        "case_id": case_id,
        "flow_id": flow_id or None,
        "artifact": artifact or None,
        "status": status or None,
        "rows": rows if rows is not None else [],
        "files": files if files is not None else [],
        "error": error,
    }
    envelope.update(extra)
    return json.dumps(envelope, default=str)


def make_ok(
    tool: str,
    client_id: str = "",
    case_id: str = "",
    flow_id: str = "",
    artifact: str = "",
    rows: list | None = None,
    files: list | None = None,
    **extra: Any,
) -> str:
    return make_result(
        ok=True,
        tool=tool,
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        artifact=artifact,
        status="FINISHED",
        rows=rows,
        files=files,
        **extra,
    )


def make_err(
    tool: str,
    error: str,
    client_id: str = "",
    case_id: str = "",
    flow_id: str = "",
) -> str:
    return make_result(
        ok=False,
        tool=tool,
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        error=error,
    )


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def audit_log(action: str, client_id: str, case_id: str, reason: str, **extra):
    entry = {
        "action": action,
        "client_id": client_id,
        "case_id": case_id or "UNSET",
        "reason": reason or "UNSET",
        **extra,
    }
    logger.info("DFIR_AUDIT %s", json.dumps(entry, default=str))


# ---------------------------------------------------------------------------
# execve output parser
# ---------------------------------------------------------------------------

def parse_exec_rows(rows: list[dict]) -> dict:
    """
    Velociraptor execve() streams output in chunks.
    Each row has Stdout/Stderr/ReturnCode fields.
    Concatenate and return the final merged output.
    """
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    return_code: int | None = None

    for row in rows or []:
        if row.get("Stdout"):
            stdout_parts.append(row["Stdout"])
        if row.get("Stderr"):
            stderr_parts.append(row["Stderr"])
        if row.get("ReturnCode") is not None:
            return_code = row["ReturnCode"]

    return {
        "stdout": "".join(stdout_parts),
        "stderr": "".join(stderr_parts),
        "return_code": return_code,
    }


# ---------------------------------------------------------------------------
# Hash extraction helper
# ---------------------------------------------------------------------------

def extract_sha256(hashes: Any) -> str:
    """Extract SHA256 from Velociraptor hash() result dict."""
    if isinstance(hashes, dict):
        return hashes.get("SHA256") or hashes.get("sha256") or ""
    return str(hashes or "")
