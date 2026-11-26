# Contributing

Discuss substantial changes in an issue first. Keep changes focused; preserve the explicit user review/run workflow, existing packet compatibility and local-only defaults. Do not introduce mandatory services or send data automatically.

1. Fork or branch from `main`.
2. Use a separate writable test workspace and fictional input data.
3. Work locally in coherent batches. Use `python tools/dev_test.py fast tests.test_terms` (substitute the affected modules/classes/methods) during development. Run `python tools/dev_test.py standard` once per integration batch, with `python tools/smoke_qt.py` for Qt changes. Full discovery and the existing CI matrix remain required for integration. The dev runner is source-only and never replaces the release checks.
4. For changes to execution or Windows behavior, manually run the two bundled example tasks following `docs/manual.txt`. Never use real secrets as fixtures.
5. Update the guide/manual, tests and changelog when behavior changes. Open a pull request using the provided template.

Unit tests use the standard library and Git. The default GUI smoke test mocks execution. Explicit `--native-batch` runs harmless disposable Windows tasks; `--browser-bridge` tests a local loopback provider. Routine checks are offscreen and save no screenshots; explicit native visual capture is opt-in. Application modules live in `command_relay/` and use package-relative imports. Keep local data paths anchored to the distribution root, not the package directory. Avoid bulk formatting changes in unrelated pull requests.

Contribute only material you have the right to submit under [Apache License 2.0](LICENSE). Preserve applicable attribution in [NOTICE](NOTICE) and identify modified files when redistributing. Do not weaken the startup risk acknowledgement or misrepresent its legal effect.

The runner reports per-module and slowest-test wall times (test-method timing includes per-test setup/teardown; class/module fixtures are counted in the residual). Use measured bottlenecks to guide optimizations, not to remove security coverage. FAST is an explicitly selected subset, never a full-regression verdict. Batch related local changes before opening a PR; do not bypass required checks.

For local integration, `python tools/dev_test.py standard --jobs 3` is an opt-in, bounded process-isolated alternative to sequential STANDARD. It validates the complete discovered test ID set and fails on missing, duplicate, skipped or failed tests. Only the audited updater module is split by class. Aggregate worker timings are not elapsed suite time. Start with two or three workers; investigate failures rather than silently retrying. Sequential STANDARD remains the default; required CI and release checks are unchanged.
