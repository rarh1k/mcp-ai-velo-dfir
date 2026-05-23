"""
dfir_tools – DFIR/Threat Hunting extensions for mcp-velociraptor.

Integration into mcp_velociraptor_bridge.py:

    # 1. Add near the top (after existing imports):
    from dfir_tools import register_dfir_tools

    # 2. Add right after: mcp = FastMCP("velociraptor-mcp")
    register_dfir_tools(mcp)

    # The rest of the bridge file is unchanged.

Tool names registered (exact, no prefix):
    run_shell, run_powershell, run_vql_raw,
    collect_arbitrary_file, recursive_collect,
    download_file, upload_file

IMPORTANT: Imports use _impl aliases to avoid shadowing by inner @mcp.tool()
functions that share the same names.
"""

# Import implementation functions under private aliases to prevent shadowing.
# Without this, defining `async def run_shell(...)` inside register_dfir_tools
# would shadow the imported `run_shell`, causing infinite recursion.
from dfir_tools.collection import collect_arbitrary_file as _collect_file_impl
from dfir_tools.collection import recursive_collect as _recursive_collect_impl
from dfir_tools.execution import run_powershell as _run_powershell_impl
from dfir_tools.execution import run_shell as _run_shell_impl
from dfir_tools.execution import run_vql_raw as _run_vql_raw_impl
from dfir_tools.transfer import download_file as _download_file_impl
from dfir_tools.transfer import upload_file as _upload_file_impl


def register_dfir_tools(mcp) -> None:
    """Register all 7 DFIR MCP tools with a FastMCP instance."""

    # ------------------------------------------------------------------
    # 1. run_shell
    # ------------------------------------------------------------------
    @mcp.tool()
    async def run_shell(
        client_id: str,
        command: str,
        timeout_seconds: int = 60,
        case_id: str = "",
        reason: str = "",
        org_id: str = "",
    ) -> str:
        """
        Execute a shell command on the endpoint via Velociraptor.

        Auto-detects platform: Windows uses cmd.exe /c, Linux uses /bin/sh -c.
        Artifact: Custom.DFIR.RunShell

        Returns JSON: {ok, tool, client_id, case_id, flow_id, artifact, status,
                        command, stdout, stderr, return_code, rows[], error}.
        """
        return _run_shell_impl(
            client_id=client_id,
            command=command,
            timeout_seconds=timeout_seconds,
            case_id=case_id,
            reason=reason,
            org_id=org_id,
        )

    # ------------------------------------------------------------------
    # 2. run_powershell
    # ------------------------------------------------------------------
    @mcp.tool()
    async def run_powershell(
        client_id: str,
        script: str,
        timeout_seconds: int = 120,
        case_id: str = "",
        reason: str = "",
        org_id: str = "",
    ) -> str:
        """
        Execute a PowerShell script on a Windows endpoint via Velociraptor.

        Runs with -NoProfile -NonInteractive -ExecutionPolicy Bypass.
        Artifact: Custom.DFIR.RunPowerShell

        Returns JSON: {ok, flow_id, stdout, stderr, return_code, rows[]}.
        """
        return _run_powershell_impl(
            client_id=client_id,
            script=script,
            timeout_seconds=timeout_seconds,
            case_id=case_id,
            reason=reason,
            org_id=org_id,
        )

    # ------------------------------------------------------------------
    # 3. run_vql_raw
    # ------------------------------------------------------------------
    @mcp.tool()
    async def run_vql_raw(
        client_id: str,
        query: str,
        timeout_seconds: int = 120,
        case_id: str = "",
        reason: str = "",
        org_id: str = "",
    ) -> str:
        """
        Execute raw client-side VQL on the endpoint via Velociraptor.

        Artifact: Custom.DFIR.RunClientVQL
        Executes query via: SELECT * FROM query(vql=Query)

        Example: "SELECT Pid, Name, Exe FROM pslist() LIMIT 20"

        Returns JSON: {ok, flow_id, row_count, rows[]}.
        """
        return _run_vql_raw_impl(
            client_id=client_id,
            query=query,
            timeout_seconds=timeout_seconds,
            case_id=case_id,
            reason=reason,
            org_id=org_id,
        )

    # ------------------------------------------------------------------
    # 4. collect_arbitrary_file
    # ------------------------------------------------------------------
    @mcp.tool()
    async def collect_arbitrary_file(
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

        Artifact: Custom.DFIR.CollectSingleFile

        Returns JSON: {ok, flow_id, files[{path, size, sha256, stored_name}]}.
        Pass files[n].stored_name to download_file(vfs_path=...) to retrieve bytes.
        """
        return _collect_file_impl(
            client_id=client_id,
            path=path,
            max_size_mb=max_size_mb,
            timeout_seconds=timeout_seconds,
            case_id=case_id,
            reason=reason,
            org_id=org_id,
        )

    # ------------------------------------------------------------------
    # 5. recursive_collect
    # ------------------------------------------------------------------
    @mcp.tool()
    async def recursive_collect(
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

        Artifact: Custom.DFIR.RecursiveCollect
        include_globs: glob pattern, e.g. "**" or "**/*.exe"
        exclude_globs: regex pattern for exclusion, e.g. ".*\\.log$"

        Returns JSON: {ok, flow_id, file_count, total_size_mb, files[]}.
        Use download_file(vfs_path=files[n].stored_name) per file.
        """
        return _recursive_collect_impl(
            client_id=client_id,
            root_path=root_path,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            max_files=max_files,
            max_total_mb=max_total_mb,
            timeout_seconds=timeout_seconds,
            case_id=case_id,
            reason=reason,
            org_id=org_id,
        )

    # ------------------------------------------------------------------
    # 6. download_file
    # ------------------------------------------------------------------
    @mcp.tool()
    async def download_file(
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
        Download a Velociraptor-collected file to the analyst machine.

        Pass flow_id from collect_arbitrary_file or recursive_collect.
        Optionally pass vfs_path (= stored_name from collection result) directly.

        Returns JSON: {ok, flow_id, files[{local_path, sha256, size_bytes}]}.
        """
        return _download_file_impl(
            client_id=client_id,
            flow_id=flow_id,
            vfs_path=vfs_path,
            artifact=artifact,
            save_to_dir=save_to_dir,
            case_id=case_id,
            reason=reason,
            org_id=org_id,
        )

    # ------------------------------------------------------------------
    # 7. upload_file
    # ------------------------------------------------------------------
    @mcp.tool()
    async def upload_file(
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
        Upload a local file to the endpoint via Velociraptor.

        Artifact: Custom.DFIR.UploadFile
        File is base64-encoded and sent via artifact parameter channel.
        Max file size: ~10 MB (governed by Velociraptor gRPC max_message_size).

        Returns JSON: {ok, flow_id, files[{remote_path, local_sha256, hash_validated}]}.
        """
        return _upload_file_impl(
            client_id=client_id,
            local_path=local_path,
            remote_path=remote_path,
            expected_sha256=expected_sha256,
            timeout_seconds=timeout_seconds,
            case_id=case_id,
            reason=reason,
            org_id=org_id,
        )
