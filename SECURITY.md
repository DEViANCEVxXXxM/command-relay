# Security policy

## Scope

Command Relay runs user-reviewed PowerShell commands with the user's privileges. It is not a sandbox or an independent verifier of AI output. Task Inspector and protected-export masking are heuristic. Review imported tasks and any output before use or sharing. This includes AI-generated executable files, scripts, dependencies and child processes. The [disclaimer and acknowledgement](DISCLAIMER.md) describes these risks and the limits of liability under applicable law.

## Built-in automation permissions

The built-in automatic squash merge helper requires an explicit saved opt-in for the resolved workspace and GitHub repository plus confirmation of the reviewed task. Missing, malformed or revoked grants deny the operation. Authorization is re-read before the merge request; GitHub protections remain authoritative. Manual reviewed operations and arbitrary scripts are outside this permission boundary. Other built-in automatic actions are not implemented.

Use More > Settings > Safety settings to revoke grants and review the local bounded history. The history is not tamper-proof or a log of all operations. Keep `automation-permissions.json` private; do not commit it, share it, or copy grants to a new installation.

## Release signing (development)

Publisher verification uses a pinned Ed25519 public key and a detached signature over exact manifest bytes. A checksum alone is not publisher authentication. The production pin is intentionally not provisioned yet; signed-package verification fails closed. Installation is not implemented.

The maintainer-only `tools/sign_release.py` is not included in the portable package. Once the public key is independently reviewed and pinned, use it from a separately verified, clean release-tag checkout on a trusted offline signing machine. Supply the exact candidate ZIP, an encrypted Ed25519 PKCS8 PEM stored outside the repository, a new output directory, and the exact tag. The tool compares the candidate ZIP's file contents against the reviewed source build before signing, and binds the exact candidate ZIP bytes to the signed manifest. It does not establish the trustworthiness of the checkout itself. Keep the private key and password outside Git, CI, Command Relay tasks, reports and chat. Enter the password only in a standalone interactive terminal. Do not publish partial outputs. Review and independently verify both output files before any upload. Key recovery and rotation require a separate reviewed procedure.

## Reporting vulnerabilities

Use the repository's **Security → Report a vulnerability** private reporting feature when enabled. If it is unavailable, contact the repository owner privately; do not post exploit details, real credentials or raw evidence in a public issue. Include the affected version, minimal fictional reproduction, expected impact and safe mitigation suggestions.

## Handling local data

Reports, settings, scripts, startup logs and evidence archives may contain sensitive data. They are excluded from the standard release archive; `.gitignore` is only a convenience and does not remove already tracked data or protect arbitrary exports. Review staged files and every shared export. If a real credential has been exposed, revoke or rotate it rather than relying on deletion alone.

## Supported versions

The current development line is 4.2.x; consult published releases for the latest available package. No formal response-time or long-term support commitment has been established by the owner.
