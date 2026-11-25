# Contributing

Discuss substantial changes in an issue first. Keep changes focused; preserve the explicit user review/run workflow, existing packet compatibility and local-only defaults. Do not introduce mandatory services or send data automatically.

1. Fork or branch from `main`.
2. Use a separate writable test workspace and fictional input data.
3. Run `python -m unittest discover -v` from the repository root. With PySide6 installed, run `python tools/smoke_qt.py`.
4. For changes to execution or Windows behavior, manually run the two bundled example tasks following `docs/manual.txt`. Never use real secrets as fixtures.
5. Update the guide/manual, tests and changelog when behavior changes. Open a pull request using the provided template.

Unit tests use the standard library and Git. The GUI smoke test does not execute PowerShell. Application modules live in `command_relay/` and use package-relative imports. Keep local data paths anchored to the distribution root, not the package directory. Avoid bulk formatting changes in unrelated pull requests.

Contribute only material you have the right to submit under [Apache License 2.0](LICENSE). Preserve applicable attribution in [NOTICE](NOTICE) and identify modified files when redistributing. Do not weaken the startup risk acknowledgement or misrepresent its legal effect.
