<p align="center"><img src="command_relay/assets/relay-icon.png" alt="Command Relay icon" width="88"></p>
<h1 align="center">Command Relay</h1>
<p align="center">A local-first Windows workbench for human-controlled AI-assisted development.</p>
<p align="center">
  <a href="https://github.com/DEViANCEVxXXxM/command-relay/actions/workflows/ci.yml"><img src="https://github.com/DEViANCEVxXXxM/command-relay/actions/workflows/ci.yml/badge.svg?branch=main&amp;event=push" alt="CI"></a>
  <a href="https://github.com/DEViANCEVxXXxM/command-relay/actions/workflows/codeql.yml"><img src="https://github.com/DEViANCEVxXXxM/command-relay/actions/workflows/codeql.yml/badge.svg?branch=main&amp;event=push" alt="CodeQL"></a>
  <a href="https://github.com/DEViANCEVxXXxM/command-relay/releases"><img src="https://img.shields.io/github/v/release/DEViANCEVxXXxM/command-relay" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache 2.0"></a>
</p>
<p align="center"><a href="https://deviancevxxxxm.github.io/command-relay/">Documentation</a> &middot; <a href="https://github.com/DEViANCEVxXXxM/command-relay/releases">Releases</a> &middot; <a href="CHANGELOG.md">Changelog</a> · <a href="docs/COMMAND_RELAY_AI_GUIDE.md">AI operating guide</a> · <a href="docs/manual.txt">Full manual</a> · <a href="SECURITY.md">Security</a></p>

> [!WARNING]
> **Run code at your own risk.** Command Relay is not a sandbox. The maintainers and contributors do not guarantee or accept responsibility for AI-generated or other third-party scripts, executables or code run through the application, to the extent permitted by law. Read the [full disclaimer and acknowledgement](DISCLAIMER.md) before use.

## What it does

Command Relay bridges an AI chat and a local development workspace without granting the AI direct access to your computer. Import a structured task or PowerShell script, review the exact commands and workspace, explicitly run them, and copy a structured result back to the chat.

**Import → Review → Run → Copy**

- Qt Workbench: script editor, live terminal, step outline, script library and history.
- Task, result and session JSON packets for structured collaboration and handoff.
- Evidence extraction, declared assertions, comparisons and read-only Git dashboard tools.
- Local report archives and evidence ZIP exports; best-effort secret masking in protected exports.
- No mandatory API key, account, telemetry or cloud connection. Commands may access the network if you explicitly run such commands.

## Quick start

1. Download the portable Windows ZIP from [Releases](https://github.com/DEViANCEVxXXxM/command-relay/releases), or clone the repository if a release is not yet available.
2. Extract into a new writable folder. Install Python 3.10–3.14 (64-bit recommended), PowerShell and optionally Git for Git features.
3. In that folder, install the GUI dependency:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Open `Start.pyw` (or `Start.cmd`); use `tools/Start-Debug.cmd` if startup fails. Read the startup disclaimer and explicitly agree to continue. Declining or closing the dialog exits without opening the workbench.
5. Choose your workspace, import [`examples/example-ai-task.json`](examples/example-ai-task.json), review it, click **Run commands**, then **Copy**. The fictional smoke task should report PASS.

The portable ZIP includes Python source and launchers, not Python itself or a compiled executable. Windows is the supported application target; Linux CI covers platform-independent logic only. CI tests Python 3.10, 3.12, 3.13 and 3.14 on Windows and Linux, with Windows Qt smoke checks on Python 3.12 and 3.14. Python 3.11 is not currently included in the CI matrix.

## How the workflow fits together

| Step | You control | Command Relay provides |
| --- | --- | --- |
| Import | Which task enters the editor | Structured JSON or a PowerShell script |
| Review | Workspace, commands and risks | Editable script and heuristic warnings |
| Run | When execution starts or stops | Local execution and live output |
| Copy | What evidence is shared | Structured results and best-effort protected exports |

## Work with an AI chat

Attach [the AI operating guide](docs/COMMAND_RELAY_AI_GUIDE.md) to your chat. Ask the assistant to produce `command-relay/task-v1` JSON, import it, review the commands, and send back `command-relay/result-v1` using Copy. Use **More → Copy session context** to resume in another chat.

## Safety and privacy

Relay executes commands under your own account permissions. It is not a sandbox. Task Inspector is heuristic, not a complete security boundary. Protected exports mask recognizable secrets on a best-effort basis, not all sensitive information. Raw reports, raw Copy, evidence ZIPs and local scripts can expose credentials and private paths. Always review before running or sharing. Never commit local reports, settings or script libraries. See [SECURITY.md](SECURITY.md).

## Development

Use the full GitHub repository checkout for these commands; the portable runtime ZIP intentionally omits developer tooling.

```shell
python -m unittest discover -v
python tools/build_release.py
```

With PySide6 installed, run `python tools/smoke_qt.py` for a non-executing GUI construction check. See [CONTRIBUTING.md](CONTRIBUTING.md), [architecture](docs/architecture.md) and [maintainer setup](docs/github-setup.md).

## Compatibility

Version 4.0.3 reorganizes the source tree into `command_relay/`, `docs/`, `examples/` and `tools/`. The `task-v1`, `result-v1` and `session-v1` schemas, example contents, startup acknowledgement and local data locations are unchanged. The root `Start.pyw` and `Start.cmd` launchers remain; diagnostic launch is now `tools/Start-Debug.cmd` (or `python -m command_relay` from the distribution root). Extract new releases into a new folder; do not overlay old versions. Move old `reports/`, `scripts/` and `settings.json` only after making a backup, as described in the [manual](docs/manual.txt).

## License

Command Relay is distributed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution. The license permits commercial use, modification and distribution, including proprietary derivatives, subject to its terms. Preserve applicable notices, supply the license and identify modified files when distributing derivative works. Third-party dependencies are separately licensed; see their upstream terms. The portable archive does not bundle Python, PowerShell or PySide6.

The [disclaimer](DISCLAIMER.md) describes execution risks and is not an amendment to the license.

## Attribution

If you use this project, parts of it, or draw on it as a reference or inspiration, please credit Command Relay and link to the original GitHub repository. Attribution for inspiration alone is a request, not an additional license requirement.
