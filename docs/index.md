---
title: Command Relay
layout: relay-home
---

<p class="eyebrow">Local-first · Windows · Human-controlled</p>
<h1>Command Relay</h1>
<p class="lead">A local workbench for AI-assisted development. Bring tasks from an AI chat into your own workspace, review them, run them yourself and share structured evidence back.</p>
<div class="actions">
  <a class="button primary" href="{{ site.github.repository_url }}/releases">View releases</a>
  <a class="button" href="{{ site.github.repository_url }}#quick-start">Quick start</a>
  <a class="button" href="{{ site.github.repository_url }}/blob/main/docs/COMMAND_RELAY_AI_GUIDE.md">AI operating guide</a>
</div>
<div class="warning" role="note">
  <p><strong>Run code at your own risk.</strong> Command Relay is not a sandbox. Review every script and export. AI-generated and third-party code may be incorrect or harmful. Maintainers disclaim liability to the extent permitted by applicable law.</p>
  <p><a href="{{ '/disclaimer.html' | relative_url }}">Read the disclaimer and startup acknowledgement</a>.</p>
</div>

## Your workflow, your control

<div class="grid">
  <article class="tile"><span class="number">01 / IMPORT</span><h3>Bring a task</h3><p>Import a structured JSON task or PowerShell script. The AI has no direct access to your computer through Command Relay.</p></article>
  <article class="tile"><span class="number">02 / REVIEW</span><h3>Inspect the plan</h3><p>Choose a workspace, read the commands and consider heuristic warnings before running anything.</p></article>
  <article class="tile"><span class="number">03 / RUN</span><h3>Execute locally</h3><p>Explicitly start execution, view live output and retain local reports and history.</p></article>
  <article class="tile"><span class="number">04 / COPY</span><h3>Share evidence</h3><p>Choose what to share. Structured results, assertions and best-effort masking help communicate evidence.</p></article>
</div>

## Built for practical development

- Qt workbench with script editor, live terminal, task outline and history.
- Structured task, result and session packets for AI-assisted workflows.
- Local evidence archives, comparisons and Git context tools.
- No mandatory AI API key, account, telemetry or cloud connection. Commands can access the network if you run such commands.

## Workflow Intelligence — 4.1.0

- Matching-run confirmation and improved indirect-operation warnings.
- Optional GitHub PR dashboard and reviewed CI-to-squash-merge tasks.
- Actionable session handoff, protected status exports and keyboard accessibility.

GitHub features require an authenticated GitHub CLI. Remote writes require explicit user approval of the operation or task; GitHub branch protection still applies. Review every task and export. The application is not a sandbox.

## Getting started

Windows, PowerShell and Python are required. The portable ZIP contains Python source and launchers, not a bundled Python runtime or compiled executable. See the [repository quick start]({{ site.github.repository_url }}#quick-start) for setup.

Python 3.10–3.14 is the intended range. CI covers 3.10, 3.12, 3.13 and 3.14 on Windows and Linux; Windows Qt smoke checks cover 3.12 and 3.14. Python 3.11 is not currently included in the CI matrix. Linux CI covers platform-independent logic only.

## Documentation

- [Disclaimer and execution risks](disclaimer.md)
- [Architecture](architecture.md)
- [GitHub maintainer setup](github-setup.md)
- [AI operating guide]({{ site.github.repository_url }}/blob/main/docs/COMMAND_RELAY_AI_GUIDE.md)
- [Full manual]({{ site.github.repository_url }}/blob/main/docs/manual.txt)
- [Repository source and releases]({{ site.github.repository_url }})

## License and attribution

Command Relay is distributed under [Apache 2.0]({{ site.github.repository_url }}/blob/main/LICENSE). See [NOTICE]({{ site.github.repository_url }}/blob/main/NOTICE) for attribution. The disclaimer does not amend the license.
