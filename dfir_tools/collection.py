"""
DFIR collection tools: collect_arbitrary_file, recursive_collect.

Both start a Velociraptor flow, wait for completion, and return file metadata.
Use transfer.download_file() after collection to pull bytes to the analyst machine.
"""
import logging

from dfir_tools.api_adapter import (
    exec_artifact_sync,
    poll_flow_until_done,
    read_flow_results,
    start_artifact_collection,
)
from dfir_tools.helpers import (
    audit_log,
    extract_sha256,
    make_err,
    make_ok,
    make_result,
)

logger = logging.getLogger("dfir_tools.collection")

ARTIFACT_COLLECT_FILE = "Custom.DFIR.CollectSingleFile"
ARTIFACT_RECURSIVE = "Custom.DFIR.RecursiveCollect"


# ---------------------------------------------------------------------------
# collect_arbitrary_file
# ---------------------------------------------------------------------------

def collect_arbitrary_file(
    client_id: str,
    path: str,
    max_size_mb: int = 100,
    timeout_seconds: int = 300,
    case_id: str = "",
    reason: str = "",
    org_id: str = "",
) -> str:
    """
    Collect a single file from the endpoint into Velociraptor server storage.

    Returns file metadata including stored_name (VFS path on server).
    Pass stored_name to download_file(vfs_path=...) to retrieve content.
    """
    audit_log("collect_arbitrary_file", client_id, case_id, reason,
              path=path, max_size_mb=max_size_mb)

    org = org_id or None

    # Start the flow
    try:
        flow_id = start_artifact_collection(
            client_id=client_id,
            artifact=ARTIFACT_COLLECT_FILE,
            parameters={"Path": path, "MaxSizeMb": str(max_size_mb)},
            timeout=timeout_seconds,
            org_id=org,
        )
    except Exception as exc:
        return make_err("collect_arbitrary_file", f"start_artifact_collection: {exc}",
                        client_id=client_id, case_id=case_id)

    # Wait
    state, backtrace = poll_flow_until_done(
        client_id=client_id,
        artifact=ARTIFACT_COLLECT_FILE,
        flow_id=flow_id,
        timeout=timeout_seconds + 120,
        org_id=org,
    )

    if state == "ERROR":
        return make_err("collect_arbitrary_file",
                        f"Flow error: {backtrace or 'unknown'}",
                        client_id=client_id, case_id=case_id, flow_id=flow_id)

    if state == "TIMEOUT":
        # Return partial result — caller can poll manually
        return make_result(
            ok=True,
            tool="collect_arbitrary_file",
            client_id=client_id,
            case_id=case_id,
            flow_id=flow_id,
            artifact=ARTIFACT_COLLECT_FILE,
            status="RUNNING",
            files=[],
            note="Flow still running. Use get_collection_results or download_file(flow_id=...) later.",
        )

    # Fetch results
    try:
        rows = read_flow_results(
            client_id=client_id,
            artifact=ARTIFACT_COLLECT_FILE,
            flow_id=flow_id,
            org_id=org,
        )
    except Exception as exc:
        logger.warning("read_flow_results failed for %s: %s", flow_id, exc)
        rows = []

    files = [_normalise_file_row(r, client_id=client_id, flow_id=flow_id) for r in rows]

    return make_ok(
        tool="collect_arbitrary_file",
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        artifact=ARTIFACT_COLLECT_FILE,
        files=files,
        file_count=len(files),
    )


# ---------------------------------------------------------------------------
# recursive_collect
# ---------------------------------------------------------------------------

def recursive_collect(
    client_id: str,
    root_path: str,
    include_globs: str = "**",
    exclude_globs: str = "",
    max_files: int = 100,
    max_total_mb: int = 500,
    timeout_seconds: int = 600,
    case_id: str = "",
    reason: str = "",
    org_id: str = "",
) -> str:
    """
    Recursively collect files from a directory on the endpoint.

    include_globs: glob pattern appended to root_path (e.g. "**" or "**/*.exe")
    exclude_globs: regex pattern used to exclude matching paths
                   NOTE: the artifact uses VQL regex (=~), not glob syntax.
                   Example: ".*\\.log$"  excludes all .log files.

    After collection, use download_file(flow_id=..., vfs_path=files[n].stored_name)
    to pull individual files.
    """
    audit_log("recursive_collect", client_id, case_id, reason,
              root_path=root_path, include_globs=include_globs,
              max_files=max_files, max_total_mb=max_total_mb)

    org = org_id or None

    try:
        flow_id = start_artifact_collection(
            client_id=client_id,
            artifact=ARTIFACT_RECURSIVE,
            parameters={
                "RootPath": root_path,
                "IncludeGlob": include_globs,
                "ExcludeRegex": exclude_globs,    # artifact param renamed from ExcludeGlob
                "MaxFiles": str(max_files),
                "MaxTotalMb": str(max_total_mb),
            },
            timeout=timeout_seconds,
            org_id=org,
        )
    except Exception as exc:
        return make_err("recursive_collect", f"start_artifact_collection: {exc}",
                        client_id=client_id, case_id=case_id)

    state, backtrace = poll_flow_until_done(
        client_id=client_id,
        artifact=ARTIFACT_RECURSIVE,
        flow_id=flow_id,
        timeout=timeout_seconds + 180,
        org_id=org,
    )

    if state == "ERROR":
        return make_err("recursive_collect",
                        f"Flow error: {backtrace or 'unknown'}",
                        client_id=client_id, case_id=case_id, flow_id=flow_id)

    if state == "TIMEOUT":
        return make_result(
            ok=True,
            tool="recursive_collect",
            client_id=client_id,
            case_id=case_id,
            flow_id=flow_id,
            artifact=ARTIFACT_RECURSIVE,
            status="RUNNING",
            files=[],
            note="Collection still running. Poll manually with get_collection_results.",
        )

    try:
        rows = read_flow_results(
            client_id=client_id,
            artifact=ARTIFACT_RECURSIVE,
            flow_id=flow_id,
            org_id=org,
        )
    except Exception as exc:
        logger.warning("read_flow_results failed for %s: %s", flow_id, exc)
        rows = []

    files = [_normalise_file_row(r, client_id=client_id, flow_id=flow_id) for r in rows]
    total_bytes = sum(f.get("size", 0) for f in files)

    return make_ok(
        tool="recursive_collect",
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        artifact=ARTIFACT_RECURSIVE,
        files=files,
        file_count=len(files),
        total_size_bytes=total_bytes,
        total_size_mb=round(total_bytes / (1024 * 1024), 2),
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _normalise_file_row(row: dict, client_id: str = "", flow_id: str = "") -> dict:
    """
    Convert a raw Velociraptor flow result row to a stable dict.

    In Velociraptor 0.76+, Upload.StoredName is the original client path, not the
    server VFS path.  The actual server-side path for the 'fs' accessor is:
        /clients/{client_id}/collections/{flow_id}/uploads/{accessor}/{path}
    We construct this when client_id and flow_id are supplied.
    """
    upload = row.get("Upload") or row.get("_Upload") or {}
    accessor = upload.get("Accessor") or "auto"
    raw_path = upload.get("Path") or upload.get("StoredName") or str(row.get("OSPath", ""))
    # Normalize backslashes → forward slashes for VFS path construction
    norm_path = raw_path.replace("\\", "/")

    if client_id and flow_id and norm_path:
        stored_name = f"/clients/{client_id}/collections/{flow_id}/uploads/{accessor}/{norm_path}"
    else:
        stored_name = raw_path

    return {
        "path": str(row.get("OSPath", "")),
        "size": int(row.get("Size") or 0),
        "sha256": extract_sha256(row.get("Hashes", {})),
        "mtime": str(row.get("Mtime", "")),
        "stored_name": stored_name,
        "upload_meta": upload,
    }
