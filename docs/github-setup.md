# GitHub maintainer setup

The ZIP contains configuration only; GitHub account and repository settings must be configured by the owner.

## Before first public push

- Verify ownership and redistribution rights for all source and artwork. Apache-2.0 is included; confirm the copyright attribution in `NOTICE` and any third-party notices before public distribution. Review `DISCLAIMER.md` for the intended jurisdictions.
- Create an empty repository named `command-relay` (suggested name), with no generated README, license or ignore file. Start private if desired and inspect the staged file list before making it public.
- Suggested description: `Local Windows workbench for human-controlled AI-assisted development and structured command evidence.` Suggested topics: `python`, `pyside6`, `qt`, `windows`, `powershell`, `developer-tools`, `ai-assisted-development`, `local-first`.
- From the extracted repository root (replace OWNER with your GitHub login):

  ```powershell
  git init -b main
  git add .
  git status --short
  git commit -m "Prepare Command Relay for GitHub"
  git remote add origin https://github.com/OWNER/command-relay.git
  git push -u origin main
  ```

## Repository features

- Enable Issues, Discussions and optionally Projects for roadmap/triage. Issue forms and PR template are included. GitHub's default labels match most categories; create `security` if needed.
- In Settings → Rules → Rulesets, protect `main`: require pull requests, passing CI checks, resolved conversations, and block force pushes/deletion. Select the actual check names after the first CI run. For a solo maintainer, do not require an approval that you cannot obtain. Protect `v*` tags to restrict releases to trusted maintainers.
- Settings → Actions: use default read-only token permissions, permit required GitHub-owned actions, and do not allow Actions to create/approve PRs unless needed. The release job explicitly requests `contents: write` only to create a draft. No custom secrets required.
- Settings → Code security: enable the dependency graph, Dependabot alerts/security updates, secret scanning and push protection where available. Enable private vulnerability reporting. The supplied dependency review and CodeQL workflows run only on public repositories; dependency review requires the dependency graph; do not also enable conflicting CodeQL default setup. For an eligible private repository, adapt the visibility guard after enabling code scanning.
- Add a social preview and a GitHub Actions badge after the final repo URL is known. Optional GitHub Pages: select Deploy from a branch → `main` → `/docs`; `docs/index.md` provides the landing page. Pages availability depends on visibility and plan. No deployment happens from this ZIP alone.
- Consider requiring full commit-SHA pinning for actions once you have pinned and verified their official release SHAs. The supplied workflows use official major tags maintained by Dependabot; they are mutable references.

## Release process

1. Run unit tests and Windows smoke checks, including the example tasks manually. Confirm license and version in `command_relay/relay_version.py`.
2. Commit and merge, ensure CI passed, then tag the exact version (example for 4.2.0; do not reuse an existing tag):

   ```powershell
   git tag -a v4.2.0 -m "Command Relay 4.2.0"
   git push origin v4.2.0
   ```

3. The Release workflow retests, checks the tag against the application version, builds an allowlisted portable ZIP and SHA-256 file, and creates a **draft** GitHub Release with generated notes. Review its assets, notes and contents before publishing. A failed or duplicate release needs maintainer review; do not overwrite a published tag.
4. To verify a downloaded asset in Windows: `Get-FileHash .\command-relay-v4.2.0-windows.zip -Algorithm SHA256`. Compare the digest with the published `.sha256` file.

The release ZIP excludes local data, test code and GitHub metadata. The full repository source remains available in GitHub's generated source archive. The fixed ZIP layout is repeatable in the same Python/zlib environment; different compressor versions need not produce identical bytes. No signed binary, installer, PyPI package or artifact attestation is claimed.
