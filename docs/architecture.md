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
| `command_relay/relay_version.py` | Canonical application and release version |
| `tests/`, `tools/` | Regression tests, packaging and Qt startup check |

The user imports input into the editor. Explicit Run prepares and executes the script in the selected workspace. Output is streamed to a local report, with a bounded view in Qt. Explicit Copy builds a result packet from the selected report and applies best-effort masking unless raw mode was selected. Reports (`reports/`), script library (`scripts/`), settings (`settings.json`) and startup logs stay in the distribution root, not inside the source package. They are not release inputs. Icons live in `command_relay/assets/`, examples in `examples/`, and documentation in `docs/`.

See the [AI guide](COMMAND_RELAY_AI_GUIDE.md) for the actual packet fields and limits. Do not interpret an assertion PASS as independent verification of a task's real effects.
