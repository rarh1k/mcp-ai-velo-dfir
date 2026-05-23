"""
DFIR file transfer tools: download_file, upload_file.

download_file: pull a Velociraptor-collected file from the server filestore
               to the analyst machine using server-side VQL.

upload_file:   push a local file to the endpoint by base64-encoding it and
               passing it as an artifact parameter (max ~10 MB; gRPC limit).
"""
import base64
import hashlib
import logging
import os
import tempfile

from dfir_tools.api_adapter import (
    exec_artifact_sync,
    read_flow_results,
    run_server_vql,
)
from dfir_tools.helpers import audit_log, make_err, make_ok

logger = logging.getLogger("dfir_tools.transfer")

ARTIFACT_COLLECT_FILE = "Custom.DFIR.CollectSingleFile"
ARTIFACT_UPLOAD = "Custom.DFIR.UploadFile"

# Chunk size for reading files via server VQL.
# Keep under Velociraptor's gRPC message limit.
# Adjust if your server has a higher max_message_size configured.
_CHUNK_BYTES = 2 * 1_024 * 1_024   # 2 MB per chunk — base64 overhead ~2.67 MB, stays under 4 MB gRPC limit

# Max file size for inline upload via artifact parameter channel.
# Base64 of 10 MB = ~13.5 MB.  Velociraptor default gRPC max_message_size is often
# 4 MB or 80 MB depending on config.  If your server allows it, bump this.
_MAX_UPLOAD_BYTES = 10 * 1_024 * 1_024


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------

def download_file(
    client_id: str,
    flow_id: str,
    vfs_path: str = "",
    artifact: str = "",
    save_to_dir: str = "",
    case_id: str = "",
    reason: str = "",
    org_id: str = "",
) -> str:
    """
    Download Velociraptor-collected file(s) to the analyst machine.

    If vfs_path is given: download that single file directly (fast path).
    If vfs_path is empty: auto-detect artifact from flow metadata, read all
    upload rows, construct proper server VFS paths, download every file.

    VFS path formula (Velociraptor 0.72+):
        /clients/{client_id}/collections/{flow_id}/uploads/{accessor}/{client_path}

    TODO (files > 100 MB): replace _read_filestore() with HTTP streaming:
        GET /api/v1/DownloadVFSFile?client_id=...&vfs_path=...
        Header: {"X-Velociraptor-API-Key": "<key>"}
    """
    audit_log("download_file", client_id, case_id, reason,
              flow_id=flow_id, vfs_path=vfs_path)

    org = org_id or None

    # Fast path: caller supplied an explicit VFS path → single-file download
    if vfs_path:
        artifact_name = artifact or ARTIFACT_COLLECT_FILE
        return _download_one(
            client_id=client_id, flow_id=flow_id, vfs_path=vfs_path,
            artifact_name=artifact_name, save_to_dir=save_to_dir,
            case_id=case_id, org=org,
        )

    # Slow path: detect artifact and download all files from the flow

    # Step 1: detect which artifact the flow used (don't assume CollectSingleFile)
    artifact_name = artifact
    if not artifact_name:
        try:
            flow_rows = run_server_vql(
                vql=(
                    f"SELECT artifacts_with_results FROM flows("
                    f"client_id={_vapi_literal(client_id)}) "
                    f"WHERE session_id = {_vapi_literal(flow_id)}"
                ),
                org_id=org,
            )
            sources = flow_rows[0].get("artifacts_with_results", []) if flow_rows else []
            artifact_name = sources[0].split("/")[0] if sources else ARTIFACT_COLLECT_FILE
        except Exception as exc:
            logger.debug("artifact detection failed, defaulting: %s", exc)
            artifact_name = ARTIFACT_COLLECT_FILE

    # Step 2: read all upload rows from the flow
    try:
        rows = read_flow_results(
            client_id=client_id,
            artifact=artifact_name,
            flow_id=flow_id,
            org_id=org,
        )
    except Exception as exc:
        return make_err("download_file", f"read_flow_results failed: {exc}",
                        client_id=client_id, case_id=case_id, flow_id=flow_id)

    if not rows:
        return make_err(
            "download_file",
            f"No rows in flow results for artifact={artifact_name!r}. "
            "Collection may still be running or produced no output.",
            client_id=client_id, case_id=case_id, flow_id=flow_id,
        )

    # Step 3: construct proper VFS path for each row and download
    dest_dir = save_to_dir or tempfile.mkdtemp(prefix="velo_dl_")
    os.makedirs(dest_dir, exist_ok=True)

    downloaded: list[dict] = []
    errors: list[str] = []

    for row in rows:
        upload = row.get("Upload") or row.get("_Upload") or {}
        accessor = upload.get("Accessor") or "auto"
        raw_path = (
            upload.get("Path")
            or upload.get("StoredName")
            or str(row.get("OSPath", ""))
        )
        if not raw_path:
            continue

        # Build server-side VFS path (Velociraptor 0.72+ layout)
        norm = raw_path.replace("\\", "/")
        resolved_vfs = (
            f"/clients/{client_id}/collections/{flow_id}/uploads/{accessor}/{norm}"
        )

        result = _download_one(
            client_id=client_id, flow_id=flow_id, vfs_path=resolved_vfs,
            artifact_name=artifact_name, save_to_dir=dest_dir,
            case_id=case_id, org=org,
        )

        import json as _json
        parsed = _json.loads(result)
        if parsed.get("ok"):
            downloaded.extend(parsed.get("files", []))
        else:
            errors.append(f"{raw_path}: {parsed.get('error', 'unknown error')}")

    if not downloaded:
        detail = "; ".join(errors) if errors else "no upload rows with a valid path"
        return make_err(
            "download_file",
            f"No files downloaded from flow {flow_id}: {detail}",
            client_id=client_id, case_id=case_id, flow_id=flow_id,
        )

    return make_ok(
        tool="download_file",
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        artifact=artifact_name,
        files=downloaded,
        errors=errors or None,
    )


def _download_one(
    client_id: str,
    flow_id: str,
    vfs_path: str,
    artifact_name: str,
    save_to_dir: str,
    case_id: str,
    org,
) -> str:
    """Download a single file by explicit VFS path."""
    try:
        content_bytes = _read_filestore(vfs_path, org)
    except Exception as exc:
        return make_err("download_file", f"Filestore read failed: {exc}",
                        client_id=client_id, case_id=case_id, flow_id=flow_id)

    if not content_bytes:
        return make_err(
            "download_file",
            f"Empty content for vfs_path={vfs_path!r}. "
            "Check that the file was actually uploaded and the path is correct.",
            client_id=client_id, case_id=case_id, flow_id=flow_id,
        )

    dest_dir = save_to_dir or tempfile.mkdtemp(prefix="velo_dl_")
    os.makedirs(dest_dir, exist_ok=True)
    filename = os.path.basename(vfs_path.rstrip("/\\")) or "downloaded_file"
    local_path = os.path.join(dest_dir, filename)

    try:
        with open(local_path, "wb") as fh:
            fh.write(content_bytes)
    except OSError as exc:
        return make_err("download_file", f"Write to {local_path!r} failed: {exc}",
                        client_id=client_id, case_id=case_id, flow_id=flow_id)

    sha256 = hashlib.sha256(content_bytes).hexdigest()
    size = len(content_bytes)

    return make_ok(
        tool="download_file",
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        artifact=artifact_name,
        files=[{
            "vfs_path": vfs_path,
            "local_path": local_path,
            "sha256": sha256,
            "size_bytes": size,
            "truncated": size >= _CHUNK_BYTES,
        }],
    )


def _vapi_literal(value: str) -> str:
    """Inline wrapper — avoids importing velociraptor_api at module level in this helper."""
    import velociraptor_api as _v
    return _v.vql_literal(value)


def _read_filestore(vfs_path: str, org_id) -> bytes:
    """
    Read file from server filestore using server-side VQL.

    Uses read_file() with accessor='fs' which gives direct filestore access.
    Reads in chunks of _CHUNK_BYTES to handle large files.

    TODO: If your Velociraptor uses a non-default filestore accessor,
    change 'fs' to the correct accessor name ('file' or 'auto').
    """
    # Normalise path: backslash → forward slash, escape single quotes
    safe = vfs_path.replace("\\", "/").replace("'", "\\'")
    chunks: list[bytes] = []
    offset = 0

    while True:
        vql = (
            f"SELECT base64encode("
            f"  string=read_file(filename='{safe}', accessor='fs', "
            f"                   offset={offset}, length={_CHUNK_BYTES})"
            f") AS Chunk FROM scope()"
        )
        rows = run_server_vql(vql=vql, org_id=org_id)

        if not rows or not rows[0].get("Chunk"):
            break

        chunk_bytes = base64.b64decode(rows[0]["Chunk"])
        chunks.append(chunk_bytes)

        if len(chunk_bytes) < _CHUNK_BYTES:
            break   # last chunk (EOF)

        offset += len(chunk_bytes)

    return b"".join(chunks)


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------

def upload_file(
    client_id: str,
    local_path: str,
    remote_path: str,
    expected_sha256: str = "",
    timeout_seconds: int = 120,
    case_id: str = "",
    reason: str = "",
    org_id: str = "",
) -> str:
    """
    Upload a local file to the endpoint via Custom.DFIR.UploadFile artifact.

    The file is base64-encoded and passed as an artifact parameter.
    The artifact uses tempfile() on the client to avoid command-line size limits,
    then decodes and writes the file, echoing the remote SHA256 for validation.

    Hard limit: _MAX_UPLOAD_BYTES (default 10 MB) due to gRPC message size.
    If your Velociraptor server has max_message_size set to 80+ MB in the config,
    you can raise _MAX_UPLOAD_BYTES accordingly.

    TODO (> 10 MB / gRPC limit):
    Alternative approach for large files:
        1. POST file to Velociraptor server via /api/v1/UploadTool or file store API
        2. Run Custom.DFIR.FetchFromServer artifact with the resulting server URL
        3. Client pulls via http_client() VQL plugin
    """
    audit_log("upload_file", client_id, case_id, reason,
              local_path=local_path, remote_path=remote_path)

    org = org_id or None

    if not os.path.isfile(local_path):
        return make_err("upload_file", f"Local file not found: {local_path!r}",
                        client_id=client_id, case_id=case_id)

    file_size = os.path.getsize(local_path)
    if file_size > _MAX_UPLOAD_BYTES:
        return make_err(
            "upload_file",
            f"File too large: {file_size:,} bytes > {_MAX_UPLOAD_BYTES:,} byte limit. "
            "See TODO in transfer.py for large-file workaround.",
            client_id=client_id, case_id=case_id,
        )

    with open(local_path, "rb") as fh:
        content_bytes = fh.read()

    local_sha256 = hashlib.sha256(content_bytes).hexdigest()

    if expected_sha256 and local_sha256.lower() != expected_sha256.lower():
        return make_err(
            "upload_file",
            f"Local file SHA256 mismatch. Expected={expected_sha256} Got={local_sha256}",
            client_id=client_id, case_id=case_id,
        )

    content_b64 = base64.b64encode(content_bytes).decode("ascii")

    flow_id, rows, error = exec_artifact_sync(
        client_id=client_id,
        artifact=ARTIFACT_UPLOAD,
        parameters={
            "RemotePath": remote_path,
            "ContentBase64": content_b64,
            "ExpectedSHA256": local_sha256,
        },
        timeout=timeout_seconds,
        org_id=org,
    )

    if error:
        return make_err("upload_file", error,
                        client_id=client_id, case_id=case_id, flow_id=flow_id)

    # Collect stdout from execve rows to find the remote SHA256 echo
    remote_stdout = " ".join(r.get("Stdout", "") for r in (rows or [])).strip()
    hash_validated = local_sha256.lower() in remote_stdout.lower()

    return make_ok(
        tool="upload_file",
        client_id=client_id,
        case_id=case_id,
        flow_id=flow_id,
        artifact=ARTIFACT_UPLOAD,
        files=[{
            "local_path": local_path,
            "remote_path": remote_path,
            "local_sha256": local_sha256,
            "size_bytes": file_size,
            "remote_output": remote_stdout,
            "hash_validated": hash_validated,
        }],
    )
