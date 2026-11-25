# Changelog

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
