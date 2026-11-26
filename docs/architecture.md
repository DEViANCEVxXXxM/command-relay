# Architecture

The portable runtime uses the `command_relay/` Python package with package-relative imports. No installation of the package or service is required. From the distribution root, `python -m command_relay` launches the same acknowledgement and workbench as `Start.pyw`.

| Module | Responsibility |
|---|---|
| `Start.pyw`, `Start.cmd`, `tools/Start-Debug.cmd` | Launch, startup diagnostics |
| `command_relay/relay_qt.py` | Qt widgets, explicit run, QProcess and worker orchestration |
| `command_relay/relay_core.py` | Paths, settings, script preparation, packet loading and report identity |
| `command_relay/relay_intelligence.py` | Evidence and assertions |
| `command_relay/relay_compare.py`, `command_relay/relay_session.py` | Comparison and session handoff |
| `command_relay/relay_privacy.py`, `command_relay/relay_export.py` | Inspection, masking and protected exports |
| `command_relay/relay_features.py` | Optional tools and evidence ZIPs |
| `command_relay/relay_view.py`, `command_relay/relay_windows.py` | Output/history bounds and native Windows integration |
| `command_relay/relay_permissions.py` | Scoped local automation grants and bounded audit history |
| `command_relay/relay_updates.py` | Signed release discovery, verification, staging, installation transactions, recovery and external updater launch |
| `command_relay/relay_version.py` | Canonical application and release version |
| `tests/`, `tools/` | Regression tests, packaging and Qt startup check |

The user imports input into the editor. Explicit Run prepares and executes the script in the selected workspace. Output is streamed to a local report, with a bounded view in Qt. Explicit Copy builds a result packet from the selected report and applies best-effort masking unless raw mode was selected. Reports (`reports/`), script library (`scripts/`), settings (`settings.json`) and startup logs stay in the distribution root, not inside the source package. They are not release inputs. Icons live in `command_relay/assets/`, examples in `examples/`, and documentation in `docs/`.

See the [AI guide](COMMAND_RELAY_AI_GUIDE.md) for the actual packet fields and limits. Do not interpret an assertion PASS as independent verification of a task's real effects.

Supported portable launchers hold a cooperative installation lock until the GUI exits. An external updater authenticated against the signed original uses the same lock, verifies both packages, and records transaction intent and backups before replacement. Pending recovery blocks normal startup; finalization verifies the selected signed tree and archives evidence. Explicit installation and restart consent are separate from ordinary task execution. See the AI guide and manual for compatibility limits.


## User extensions and the official distribution

The signed release is the maintained program tree, with exactly the existing 39 managed paths. Do not use AI tasks to patch that tree to add personal functionality. Source development and independent forks are legitimate, but a locally modified managed installation is not the verified official release; signed installation checks may refuse it. This is a supported extension contract, not OS-level protection from arbitrary commands running as the same account.

Personal Skills are independent of the installation. Windows uses `%LOCALAPPDATA%/CommandRelay/User/skills` (home AppData fallback); other systems use the absolute XDG data directory or `~/.local/share/CommandRelay/User/skills`. The existing portable settings, reports, scripts and scoped policy stay where they are for compatibility. They already lie outside the signed managed path set. A future migration must preserve them and be tested separately; do not silently relocate or reset grants. New user configuration should live under the per-account User root, not the official program tree.

`command-relay/skill-v1` is a bounded, declarative manifest containing an ID, integer revision, title, description, instructions and optionally a reviewed task-v1 template. The store is created lazily when accessed. Revisions coexist, imports are explicit, and same revision/different bytes is rejected. No native plugins, startup hooks, dynamic module imports, permission declarations, provider credentials, dependency installation or automatic execution. Invalid files are surfaced but not loaded. A user can select an older revision. All manifest content is untrusted, even if authored by AI or stored locally. Copy instructions is an explicit clipboard action; loading a task opens existing review, not execution. No skill can register or inherit an automation grant. A future extension system may add narrow, versioned declarative action interfaces subject to Safety Gate; never treat a skill as authority.

The updater must not traverse or replace personal data. Test preservation under successful and failed signed updates, separate installed versions, duplicate IDs, malformed manifests, unsupported schema revisions, interrupted import, inaccessible directories and path redirection. For migration, make a backup, validate first and keep old revisions; no automatic downgrade or deletion. The official updater and program remain independently verifiable.

## Universal workspace presentation

The full technical workbench is the only workspace. Navigation, editor, inspector, output and task state remain shared. File and clipboard imports route batch-v1 to explicit review, never execution. Ordinary manual Run is the authorization; high-risk approval and uncertain/failed history review remain separate. Semantic log colors are advisory, not assertion evaluation.

### Optional Browser Bridge

AI Chat opens a lazy Qt WebEngine dock using the already installed PySide6 runtime; the normal startup does not import WebEngine. Its off-the-record profile does not persist browser credentials as a Relay profile. Enter an explicit HTTPS (or loopback HTTP) provider address. Authentication redirects may work; popups, local file selection, unknown schemes, browser permissions and certificate exceptions are denied. There is no JavaScript-to-native execution bridge. A provider may be incompatible; use the external browser and clipboard instead.

A same-origin JSON download (including a same-origin blob URL) is captured into a uniquely named system temporary directory, never Downloads. Only one transfer or pending task is accepted at a time; known oversize downloads are rejected, progress is monitored and final reads are bounded to 1 MB. Transfer completion validates task-v1 or batch-v1; the user must explicitly import into existing review. Navigation invalidates the pending task and cancels an active transfer. No task runs on download or review. The runtime does not promise strict disk quotas during a transfer or cleanup after an abnormal process termination. Return uses the existing masked AI export and manual clipboard paste/send or explicit reviewed draft insertion described below. Automatic DOM submission, persisted provider profiles and authenticated provider compatibility remain unsupported or unverified.

Browser shutdown explicitly destroys the view/page before the off-record profile, while Qt is alive. Renderer termination discards pending imports and offers external-browser fallback. The offscreen acceptance test uses software Chromium rendering; it does not establish hardware-rendering compatibility.


### Safety admission boundary

`SafetyGate` binds one-use high-risk approvals to immutable `DispatchReview` values and verifies workspace identity again before admission. The single-task Qt path checks editor, metadata and selected workspace after modal reviews; `BatchExecutionSession` checks each admission and halts on a missing grant. No persistent bypass, automatic approval from task content, dynamic containment, or unrestricted autonomy is provided. Built-in Git and update operations retain their own existing scoped controls.

Smart export compacts only recognized verbose success runs after evaluating full-source assertions/comparison, preserves original report hashes and line accounting, and masks against the original source. Detailed masked export retains the previous bounded view. Runtime diagnostics scans a bounded number of archive entries and checks the current PATH without launching tools. Recovery hints never issue a retry or delete a partial report.


### Workspace continuity and browser handoff (v4.4 development)

Recent reports are available on the History tab of the on-demand bottom utility dock, derived on demand from the existing bounded workspace session archive. The archive is the durable source of truth. No scan is required at startup; stale workspace results are discarded.

### Remaining acceptance and scope limits

Grand QA 123 verified 479 tests without skips on Windows and Linux, synthetic 17-locale layout at three scale factors, sampled native glyphs, disposable native batch, loopback browser and deterministic unsigned 39-file archive. Real provider authentication, actual native visual/DPI, independent translation/legal review and production signed-to-signed update remain open. No durable conversation-linked identity, generic contenteditable, delivery receipt, unrestricted autonomous execution, legacy data relocation, executable plugins, automatic PATH refresh or crash-resume guarantee is provided.

### Reviewed browser draft insertion

Optional Browser Bridge can prepare an exact masked Smart report as a draft without using the clipboard or an AI API. Select an empty visible HTML textarea, click Prepare chat draft, inspect the complete export and explicitly choose Insert draft. The browser receives the text at insertion, even before Send; masking is best effort. Relay does not click Send or submit. Site input handlers may react to inserted text; delivery is not asserted. A fixed isolated-world helper checks the exact page URL, one-use target reference, empty field and size; navigation, busy state, changed report/archive or changed focus invalidate the operation. No arbitrary DOM scripts, automatic retry, generic contenteditable support, credentials, persistent permissions or autonomous transfer. Unsupported providers and oversized or stale reports use the existing masked clipboard flow. Loopback acceptance checks cancellation, changed field, existing text, exact draft and untouched clipboard.

### Bounded local plan execution

`relay_features.ReviewedLocalPlan` accepts only a strict, small `plan-v1` packet containing distinct fixed metadata operation identifiers. It pins the workspace directory ancestry identities and exact packet digest; one-use execution checks scope before and after each operation. Fixed dispatch performs top-level metadata inventory, volume capacity, and fixed marker presence only; it never invokes a shell, opens file contents or modifies files. On Windows the selected path must be on a fixed drive and exclude reparse points. Scope checks are best-effort against concurrent same-account filesystem changes, not an OS security boundary. Cooperative time/cancel checks, at most three operations and 1000 inventory entries, stop on incomplete or unknown outcomes; blocked OS calls can delay cancellation. `LocalPlanDialog` runs this on a worker only after default-deny review, keeps the owner busy, and presents local protected JSON for manual export. The ordinary task and batch routes remain separate. No persistent authority, automatic browser transfer, AI-generated command autonomy, or isolation of arbitrary PowerShell.

### Workspace visual hierarchy

The identity header is separate from navigation and task controls.
The full workspace uses resizable editor/output panes and a theme-aware status strip. Visual acceptance is opt-in; normal tests check layout and glyphs without saving images.

### Product shell and typography (119)

The single workspace uses adaptive horizontal navigation at every window width. The editor and terminal occupy the entire work surface; Steps, Scripts and recent History are available through Tools → Show workspace utilities, an optional bottom dock closed by default. Old sidebar preferences are discarded. Navigation never executes a task.

Qt platform/system fonts are preferred over a forced QSS family. A bounded Latin/Cyrillic glyph probe selects UI and code fonts, with process-local registration of known installed Windows font files only when necessary. No fonts are shipped, downloaded or installed. This is not proof of all script coverage. The visual acceptance tool captures synthetic fixtures in a separate native Windows Qt process, verifies glyph coverage and layout, and requires visual review of the generated images. Offscreen smoke remains separate; production DPI, provider compatibility, all dialog aesthetics and EN/RU copy review remain pending.


### Canonical English/Russian UI copy

Use short action verbs and sentence-case UI copy. Canonical terminology: workspace / рабочая папка; task / задача; session / сессия; skill / навык; task batch / пакет задач; AI / ИИ; review / проверка; approval / разрешение; report / отчёт; exit code / код выхода; masked / с маскированием. The full workbench is the only workspace. Never infer safety from an absent risk match or test success from exit zero. Keep raw scripts, protocol keys, IDs, original reports and machine verdicts unchanged; localize only UI-owned presentation. Keep explicit review, exact scope and no automatic transfer statements. Only offer additional locales as clearly labelled development previews until linguistic/legal review and native layout acceptance are complete. Known legacy untranslated dialogs and technical detail remain for audit; this is not a claim of complete localization.


The legacy AI context chooser, local-tool titles and completion/error messages, export mode presentation, file filters and close/update messages now use EN/RU catalog IDs. The source-level guard covers the context chooser, not every widget. Raw process output, user text, exception details, external provider UI and OS/native standard controls are not translated by this catalog. Full language acceptance includes a human review of remaining dialogs and native controls; do not infer it from catalog parity.


### Localization and visual acceptance

The single workspace retains 528 active UI keys per locale. English and Russian are canonical; 15 additional selectable locales are explicitly labelled previews. Each preview notice includes all six translated paragraphs and the original English source. Format-field parity and notice source digests do not constitute linguistic/legal approval. Arabic chrome and dialogs use RTL; commands, paths and report editors remain LTR. Raw output, user text, external provider UI and OS-native controls remain outside catalog coverage.

The former mode chooser, Casual dashboard and persistent sidebar are removed. Legacy mode/sidebar settings are discarded without changing other preferences. The optional bottom utility dock is closed by default. Layout tokens use 16 px outer margins, 12 px section gaps, 8 px control gaps, aligned rows and shared pane header heights. System fonts and fallback shaping are sampled; no fonts are shipped.

Routine Qt tests use offscreen geometry and a separate native Windows font-only probe, no visible native windows or PNGs. Explicit Windows visual acceptance uses `tools/smoke_qt.py --visual-only` with `QT_QPA_PLATFORM=windows`; saving synthetic PNGs additionally requires `--capture-visual` and an explicit existing empty-of-PNGs `RELAY_VISUAL_DIR`. The path variable alone never enables capture. Actual native DPI and subjective visual acceptance remain separate.

### Pre-integration review hardening

Single and built-in Run decline while a local tool is active, including after a modal review. Browser pending transfers and report-copy approval are invalidated when a new load begins, including same-URL reloads. Untrusted status/path/error labels are plain text. Limitations in logs are presented as warnings, not failure verdicts. These checks do not establish isolation, complete linguistic review, or provider compatibility.

### Report copy gestures

The main report-copy button uses the activating mouse release modifiers: plain click copies masked AI JSON, Shift copies masked text, and Ctrl copies unmasked RAW (Ctrl takes precedence). Keyboard activation and programmatic button clicks default to AI JSON. Explicit report menu actions remain available. The localized tooltip and accessible description disclose the RAW behavior. Native Qt event tests exercise all four combinations and subsequent unmodified activation with mocked export.
