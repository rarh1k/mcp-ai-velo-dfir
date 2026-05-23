# mcp-ai-velo-dfir

Lab PoC: AI-assisted DFIR through Velociraptor + MCP, and the dual-use risk
of the same primitives.

This repo contains six custom Velociraptor artifacts and a Python add-on for
[mgreen27/mcp-velociraptor](https://github.com/mgreen27/mcp-velociraptor)
(or any compatible MCP bridge) that exposes them as MCP tools. Together they
let an LLM client (Claude Desktop, Claude Code, etc.) drive live triage and
file transfer on Velociraptor-managed endpoints.

> **Lab PoC. Not production-safe. No support. Patches welcome.**
> Runs in my owned lab against test endpoints. Anyone who hooks this up to
> a real Velociraptor deployment is on their own — review the code, the
> artifacts, and the threat model first.

## What this demonstrates

- LLM-orchestrated DFIR triage through MCP tools on top of Velociraptor.
- The same primitives expressed as a research target: shell execution, raw
  client-side VQL, arbitrary file collection, and file upload to endpoints —
  all reachable from a chat interface.
- A new trust boundary in AI-assisted IR: **prompt injection via endpoint
  artifacts**. When an LLM reads logs, filenames, registry values, or
  command-line strings during triage, an attacker who controls any of those
  controls input to the model. The MCP tools below treat all collected
  content as untrusted data, but the consuming LLM still has to be hardened
  against it.

## Tools

### Execution (high risk)
- `run_shell` — `cmd.exe /c` or `/bin/sh -c` on the endpoint
- `run_powershell` — PowerShell with `-NoProfile -NonInteractive -ExecutionPolicy Bypass`
- `run_vql_raw` — client-side VQL evaluation

### Collection (medium/high risk)
- `collect_arbitrary_file` — single file → server VFS
- `recursive_collect` — glob/regex-scoped directory collection

### Transfer (high risk)
- `download_file` — server VFS → analyst workstation
- `upload_file` — local file → endpoint (base64 channel, ≈10 MB limit)

Every tool takes `case_id` and `reason` (currently optional — should be
required before any real-world use). Calls are audit-logged.

## Layout

```
artifacts/        Velociraptor artifact YAMLs — import these on your server
dfir_tools/       Python add-on for the MCP bridge
```

## Setup (sketch)

1. Have a working MCP-velociraptor bridge (e.g. `mgreen27/mcp-velociraptor`)
   with `api_client.yaml` configured against your **lab** Velociraptor server.
2. Upload all six YAMLs from `artifacts/` to your Velociraptor server
   (GUI: *Artifacts → Add an Artifact*, or via API).
3. Drop the `dfir_tools/` package next to `mcp_velociraptor_bridge.py`.
4. In the bridge entry point, register the new tools:
   ```python
   from dfir_tools import register_dfir_tools
   register_dfir_tools(mcp)
   ```
5. Point your MCP client at the bridge.

Code is published **as-is**. The published copy has a few known issues
(VQL injection in `_read_filestore`, no `remote_path` validation in
`upload_file`, `MaxFiles`/`MaxTotalMb` not enforced, optional `case_id`).
Fix before connecting to anything you care about.

## Why this matters — Velociraptor abuse in the wild

Velociraptor itself has been used as a living-off-the-land tool in
ransomware operations during 2025. Useful primary sources:

- **Sophos CTU**, *Velociraptor incident response tool abused for remote access* (Aug 2025)
  <https://news.sophos.com/en-us/2025/08/26/velociraptor-incident-response-tool-abused-for-remote-access/>
- **Cisco Talos**, *Velociraptor leveraged in ransomware attacks* — Storm-2603 / Warlock / LockBit / Babuk on VMware ESXi (Oct 2025)
  <https://blog.talosintelligence.com/velociraptor-leveraged-in-ransomware-attacks/>
- **Rapid7**, *Identifying and Mitigating Potential Velociraptor Abuse* — detection guidance, Sigma/Yara rules (Oct 2025)
  <https://www.rapid7.com/blog/post/pt-identifying-and-mitigating-potential-velociraptor-abuse/>
- **CISA KEV**, CVE-2025-6264 (Velociraptor remote-upgrade privilege escalation, added Oct 2025)

This PoC layers an LLM on top of the same primitives those campaigns
relied on. The point is to make that capability inspectable in a lab, not
to ship a polished offensive tool.

## Author

[@rarh1k](https://github.com/rarh1k)

## License

No explicit license. Default copyright applies. If you want to fork or
reuse, open an issue.
