# Same Tool, Two Hats: AI-Assisted DFIR via Velociraptor + MCP

Lab PoC exploring LLM-orchestrated DFIR through a Velociraptor MCP bridge -
and the dual-use risk that comes with the same primitives.

> **Lab PoC. Not production-safe. No support. Patches welcome.**
> Runs in my owned lab against test endpoints. Anyone who hooks this up to
> a real Velociraptor deployment is on their own - review the code, the
> artifacts, and the threat model first.






## Background

LLM-operated operations keep showing up in real-world reports: a human sets
a goal, the LLM helps drive - picking the next step, interpreting tool
output, making tactical decisions. This PoC is an attempt to show what
that looks like in practice on top of a real DFIR tool.

The starting point is [mgreen27/mcp-velociraptor](https://github.com/mgreen27/mcp-velociraptor) -
an MCP wrapper over the Velociraptor API. Its original goal is to let a
DFIR analyst work with Velociraptor through Claude. I looked at the same
plumbing from the other side: if an LLM can help a defender investigate an
endpoint, the same primitives work just as well for adversary emulation.

(Partly inspired by [this post](https://t.me/s0ld13r_ch/82).)

## Why Velociraptor

Velociraptor sits in the dual-use sweet spot: a legitimate agent, signed
binary, TLS traffic to a centralised server, and a powerful artifact
language. In a defensive scenario, that combination accelerates IR. In an
offensive model, the same setup becomes a controlled channel for
reconnaissance, command execution, and scoped file collection.

This is not theoretical - see the references at the bottom for documented
2025 ransomware campaigns abusing Velociraptor as a living-off-the-land
tool.

## What's in this repo

The original `mgreen27/mcp-velociraptor` bridge lets an LLM **see** an
endpoint through DFIR artifacts. The wrappers in this repo let an LLM
**initiate actions** through the Velociraptor API.

### Execution
- `run_shell`- `cmd.exe /c` or `/bin/sh -c` on the endpoint
- `run_powershell` - PowerShell with `-NoProfile -NonInteractive -ExecutionPolicy Bypass`
- `run_vql_raw` - client-side VQL evaluation

### Collection
- `collect_arbitrary_file` - single file → server VFS
- `recursive_collect` - glob/regex-scoped directory collection

### Transfer
- `download_file` - server VFS → analyst workstation
- `upload_file` - local file → endpoint, SHA256-verified, base64 channel (≈10 MB limit)

Every tool takes `case_id` and `reason` (currently optional - should be
required before any real-world use). Calls are audit-logged.

## Defensive workflow (the way I use it in my lab)

An IR analyst connects their own Velociraptor server, deploys the agent to
the machine under investigation, and runs triage through Claude Desktop or
Claude Code. Processes, network connections, services, scheduled tasks,
Sysmon Event ID 1/3, Event ID 7045, Amcache, Shimcache, and filesystem
artifacts - all read through one MCP interface.

## The hard problem: prompt injection in AI-assisted IR

If the attacker leaves a payload in logs, file names, command-line strings,
or staged notes, the DFIR analyst - through the LLM - reads
attacker-controlled content. At that moment any single artifact can derail
the investigation: the LLM may be steered toward wrong conclusions, ignore
real signals, or - when paired with action-capable tools like the ones in
this repo - be nudged into doing something it shouldn't.

AI-assisted IR therefore needs an explicit analytic contour: how the LLM
reads artifacts, where data is separated from instructions, which actions
require confirmation, and how tool calls are logged.

## Layout

```
artifacts/    Velociraptor artifact YAMLs - import on your server
dfir_tools/   Python add-on for the MCP bridge
```

## Setup (sketch)

1. Have a working [mgreen27/mcp-velociraptor](https://github.com/mgreen27/mcp-velociraptor)
   bridge with `api_client.yaml` configured against your **lab** Velociraptor server.
2. Upload all six YAMLs from `artifacts/` to your Velociraptor server
   (GUI: *Artifacts → Add an Artifact*, or via API).
3. Drop the `dfir_tools/` package next to `mcp_velociraptor_bridge.py`.
4. In the bridge entry point, register the new tools:
   ```python
   from dfir_tools import register_dfir_tools
   register_dfir_tools(mcp)
   ```
5. Point your MCP client at the bridge.

Code is published **as-is**. Known issues: VQL injection in
`_read_filestore`, no `remote_path` validation in `upload_file`,
`MaxFiles`/`MaxTotalMb` not enforced, optional `case_id`. Fix before
connecting to anything you care about.

## Demo

_(video link goes here)_

## References

Velociraptor abuse in the wild during 2025:

- **Solar 4RAYS** - [Velociraptor abuse research](https://rt-solar.ru/solar-4rays/blog/4559/)
- **Sophos CTU** (Aug 2025) — [Velociraptor incident response tool abused for remote access](https://news.sophos.com/en-us/2025/08/26/velociraptor-incident-response-tool-abused-for-remote-access/)
- **Cisco Talos** (Oct 2025) — [Velociraptor leveraged in ransomware attacks](https://blog.talosintelligence.com/velociraptor-leveraged-in-ransomware-attacks/) - Storm-2603 / Warlock / LockBit / Babuk on VMware ESXi
- **Rapid7** (Oct 2025) — [Identifying and Mitigating Potential Velociraptor Abuse](https://www.rapid7.com/blog/post/pt-identifying-and-mitigating-potential-velociraptor-abuse/) - detection guidance, Sigma/Yara rules
- **CISA KEV** — CVE-2025-6264 (Velociraptor remote-upgrade privilege escalation, added Oct 2025)

## Author

[@rarh1k](https://github.com/rarh1k) · 🦔 THF https://t.me/ThreatHuntingFather/

## License

MIT — see [LICENSE](LICENSE).
