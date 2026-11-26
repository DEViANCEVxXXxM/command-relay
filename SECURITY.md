# Security policy

## Scope

Command Relay runs user-reviewed PowerShell commands with the user's privileges. It is not a sandbox or an independent verifier of AI output. Task Inspector and protected-export masking are heuristic. Review imported tasks and any output before use or sharing. This includes AI-generated executable files, scripts, dependencies and child processes. The [disclaimer and acknowledgement](DISCLAIMER.md) describes these risks and the limits of liability under applicable law.

## Built-in automation permissions

The built-in automatic squash merge helper requires an explicit saved opt-in for the resolved workspace and GitHub repository plus confirmation of the reviewed task. Missing, malformed or revoked grants deny the operation. Authorization is re-read before the merge request; GitHub protections remain authoritative. Manual reviewed operations and arbitrary scripts are outside this permission boundary. Signed update installation has a separate default-denied application-local grant and explicit terminal confirmation. No unrestricted unattended PowerShell is implemented.

In 4.4.0 use Settings > Safety settings (More > Settings in 4.3) to revoke grants and review the local bounded history. The history is not tamper-proof or a log of all operations. Keep `automation-permissions.json` private; do not commit it, share it, or copy grants to a new installation.

## 4.4 execution and browser boundaries

Explicit ordinary Run authorizes the reviewed script. High-risk heuristic matches require a separate one-use approval tied to exact prepared commands and workspace; unknown/failed repeat outcomes require review. The absence of a match is not proof of safety. Batch execution requires review and explicit approval, and parallel workspaces must be distinct and non-overlapping. Job Objects and cancellation are not sandboxing or rollback. Fixed read-only local plans have bounded scope and cooperative cancellation, not protection from concurrent same-account changes.

Personal Skills contain untrusted declarative data; they do not grant authority or execute on import. Optional off-record Browser Bridge validates same-origin task downloads, requires explicit import, and never runs commands or sends chat messages automatically. Inserting a reviewed masked draft shares text with the page before Send. External providers may be incompatible; prefer the clipboard fallback. Protected masking is best effort; Ctrl+click and RAW exports can disclose sensitive data. Preview translations are not independent legal or linguistic review; the original English notice accompanies translated preview notices.

## Release signing and update safety

Publisher verification uses a pinned Ed25519 public key and a detached signature over exact manifest bytes. A checksum alone is not publisher authentication. The reviewed production public key is pinned in the application. Its SHA-256 fingerprint (raw 32-byte Ed25519 key) is `f3d92fd2e380dcb0640eb087c96a0da699ec66ca35dc902f97559192ead62e99`. Missing or invalid signatures fail closed. The standalone installer requires authenticated original and target packages, exact approved layout, unchanged dependencies, a separate grant and terminal consent. Pending transaction state blocks normal startup; preserve recovery evidence. Cooperative locks are not hostile same-user or power-loss protection. Key possession and production signing are verified separately; production signed-to-signed GUI acceptance has not been demonstrated.

The maintainer-only `tools/sign_release.py` is not included in the portable package. Use it from a separately verified, clean release-tag checkout on a trusted offline signing machine. Supply the exact candidate ZIP, an encrypted Ed25519 PKCS8 PEM stored outside the repository, a new output directory, and the exact tag. The tool compares the candidate ZIP's file contents against the reviewed source build before signing, and binds the exact candidate ZIP bytes to the signed manifest. It does not establish the trustworthiness of the checkout itself. Keep the private key and password outside Git, CI, Command Relay tasks, reports and chat. Enter the password only in a standalone interactive terminal. Do not publish partial outputs. Review and independently verify both output files before any upload. Key recovery and rotation require a separate reviewed procedure.

## Reporting vulnerabilities

Use the repository's **Security → Report a vulnerability** private reporting feature when enabled. If it is unavailable, contact the repository owner privately; do not post exploit details, real credentials or raw evidence in a public issue. Include the affected version, minimal fictional reproduction, expected impact and safe mitigation suggestions.

## Handling local data

Reports, settings, scripts, startup logs and evidence archives may contain sensitive data. They are excluded from the standard release archive; `.gitignore` is only a convenience and does not remove already tracked data or protect arbitrary exports. Review staged files and every shared export. If a real credential has been exposed, revoke or rotate it rather than relying on deletion alone.

## Supported versions

This source version is 4.4.0; consult published releases for the latest available signed package. No formal response-time or long-term support commitment has been established by the owner.
