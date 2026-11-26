# Changelog

## Unreleased — 4.4.0 Unified Experience Update

- One full-width workbench with top navigation, a resizable command editor and terminal, and optional bottom utilities. Ordinary manual Run needs no second confirmation; high-risk and failed/uncertain repeat review remains.
- Reviewed dependency-aware task batches: explicit workspaces, sequential by default, opt-in bounded parallel workers for independent tasks. No sandbox or unattended arbitrary PowerShell.
- Personal Skills, bounded read-only metadata plans, runtime diagnostics, recent reports and structured session handoff.
- Optional off-record AI Chat (Qt WebEngine), reviewed same-origin JSON import and masked draft insertion into a supported empty textarea. No automatic Send, provider API requirement or guaranteed provider compatibility.
- Smart masked JSON, Detailed masked JSON, protected text and unmasked RAW export. Plain click = Smart; Shift+click = protected text; Ctrl+click = RAW (Ctrl wins). Review exports before sharing.
- 17 selectable interface languages: English/Russian and 15 translation previews; Arabic RTL chrome, LTR commands, paths and reports. Preview translations are not independently certified.
- One-use exact Safety Gate review, separate scoped Git/update grants, no implicit authority on import.
- Automated Grand QA: 479/479 Windows and Linux, no skips; 17-language offscreen scale matrix, sampled fonts, native disposable batch, loopback browser and deterministic unsigned 39-file archive. Actual native visual/DPI, authenticated provider, independent linguistic/legal review and production signed-to-signed update remain unverified.
- No new mandatory dependencies or managed release paths. The runtime version remains 4.3.0 until release preparation.

## 4.3.0 — Automatic Updates

- Added explicit update discovery and signed-package download/verification in More > Settings > Updates. No background polling or unattended installation.
- Added Ed25519 publisher authentication with a pinned public key, bounded download and archive validation, external updater preparation and isolated launch. SHA-256 alone is not publisher authentication.
- Added default-denied application-local update permission, separate terminal confirmation, cooperative installation lock, transactional backup, rollback and startup recovery gate. Finalization preserves evidence outside the installation.
- Added guarded restart after commit with separate consent; process launch does not establish GUI readiness.
- Independent-process integration tests cover disposable signed install, interrupted replacement, recovery and inert restart. The pre-version-bump audit also opened and closed the actual extracted Qt workbench offscreen. Production signed-to-signed GUI updating is not yet demonstrated.
- The first signed release requires manual extraction into a fresh directory. Keep the original four signed release assets for future update/recovery. Do not copy automation grants or overlay the old installation. Existing caches, unexpected program entries, modified files, changed dependencies or changed program layout are denied. Recovery may require manual intervention.
- Task, result and session packet schemas remain unchanged; no sandbox, unattended update, expanded localization or parallel execution is introduced.

## 4.2.0 — Safety & Control Center

- Built-in automatic squash merge now defaults to denied and requires explicit opt-in for the resolved workspace and exact GitHub repository, in addition to task review. Authorization is rechecked during CI waiting and immediately before the write; GitHub branch protection still applies.
- Added local Safety settings with scope preview, explicit confirmation, selected/all revocation and a bounded 128-event permission history. Legacy general settings do not grant permissions; malformed policy fails closed. The policy is separate from general settings and must not be shared.
- Consolidated safety and display preferences under More > Settings. Adaptive action rows wrap long labels when needed, including RTL, without adding controls to the normal workbench.
- Verified 178 regression tests, Windows Qt smoke, six offscreen DPI/style probes at 100%, 150% and 200%, and the 38-file portable build during candidate audits. Offscreen checks are not full visual acceptance or comparative performance certification.
- Other built-in automatic actions (unattended execution, push, PR creation, branch deletion, update installation and parallel execution) are not implemented. Reviewed arbitrary scripts still run with user privileges and are outside the permission boundary. No sandbox, unattended execution, automatic update installation or expanded localization is introduced.
- Packet schemas and startup acknowledgement remain unchanged. Fresh installs have no automation grants.

## 4.1.0 — Workflow Intelligence

- Added bounded history lookup and explicit confirmation before rerunning a matching task.
- Extended heuristic Task Inspector coverage for indirect Git, GitHub CLI and process operations.
- Added optional GitHub PR manager with background queries, CI status, explicit SHA-bound squash merge and protected JSON export.
- Added task-level CI waiting and verified squash merge for reviewed tasks; importing a task never starts execution.
- Preserved standalone GitHub Actions secret-reference expressions in protected text while retaining best-effort secret masking.
- Documented safe retry and partial failure recovery; expanded session handoff with current project context and continuation hints.
- Improved workbench keyboard focus, accessible control names, step navigation and discoverability of report copy modes.
- Preserved task-v1, result-v1 and session-v1 compatibility, startup risk acknowledgement and local data layout.
- Validated 157 regression tests, extended Windows Qt smoke tests and a repeatable 37-file portable build before the version bump.
- GitHub CLI remains optional. Automatic update installation, expanded localization, permission settings and parallel execution are future work.

## 4.0.3 — first public release

- Moved runtime modules into `command_relay/` with package-relative imports and a module entry point.
- Grouped icons, examples and manuals into dedicated directories; relocated diagnostic launcher to `tools/`.
- Standardized dependency file as `requirements.txt`; updated CI, release allowlist and documentation.
- Preserved portable root launchers, local data locations, packet schemas and startup acknowledgement. Extract into a new directory rather than overlaying older releases.

- Fixed archive cache invalidation so changes in directory membership are detected even when directory timestamps do not change; bounded the archive scan and preserved explicit exports.
- Fixed Windows launcher and extracted-package test path comparisons and isolated native error dialogs during automated testing.
- Raised the minimum PySide6 version to 6.12.0 (below 7).
- Qualified Python 3.14 in Windows and Linux unit-test CI; Windows Qt smoke checks cover Python 3.12 and 3.14. Python 3.11 is not currently in the CI matrix.
- Updated GitHub Actions checkout, setup-python and dependency-review actions; improved README navigation, status badges and the GitHub Pages homepage.
- Verified 118 regression tests and Qt startup acknowledgement scenarios locally on Windows with Python 3.14.4 and Qt 6.12.0.

## 4.0.2 — licensing and execution-risk acknowledgement

- Added the standard Apache License 2.0, attribution notice, and bilingual operational disclaimer.
- Added a startup acknowledgement before workbench construction; declining or closing exits normally.
- Updated repository, Pages, security and AI documentation, and required legal files in portable releases.
- No intended changes to command execution, packet schemas, local storage or workbench layout.

## 4.0.1 — repository preparation

- Centralized application version and replaced wildcard imports from `relay_core` with explicit imports.
- Organized regression tests under `tests/`; added archive allowlist, checksum and repeat-build tests.
- Added GitHub CI, Windows Qt smoke check, CodeQL, dependency review, Dependabot, issue forms and draft release automation.
- Added repository documentation, contribution and security guidance, and exclusion rules for local artifacts.
- No intended changes to task execution, UI layout, packet schemas, report storage or privacy behavior.

## 4.0 — Qt Workbench / Clean Edition

- Reject malformed JSON task imports and read report identity from the header only.
- Bound terminal output and restore history asynchronously; prevent a new run during explicit Copy.
- Preserve the Import → Run → Copy workflow and existing packet schemas.
- See the full historical notes in [README.txt](docs/manual.txt) and the [AI guide](docs/COMMAND_RELAY_AI_GUIDE.md).
