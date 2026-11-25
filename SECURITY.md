# Security policy

## Scope

Command Relay runs user-reviewed PowerShell commands with the user's privileges. It is not a sandbox or an independent verifier of AI output. Task Inspector and protected-export masking are heuristic. Review imported tasks and any output before use or sharing. This includes AI-generated executable files, scripts, dependencies and child processes. The [disclaimer and acknowledgement](DISCLAIMER.md) describes these risks and the limits of liability under applicable law.

## Built-in automation permissions

The built-in automatic squash merge helper requires an explicit saved opt-in for the resolved workspace and GitHub repository plus confirmation of the reviewed task. Missing, malformed or revoked grants deny the operation. Authorization is re-read before the merge request; GitHub protections remain authoritative. Manual reviewed operations and arbitrary scripts are outside this permission boundary. Other built-in automatic actions are not implemented.

Use More > Settings > Safety settings to revoke grants and review the local bounded history. The history is not tamper-proof or a log of all operations. Keep `automation-permissions.json` private; do not commit it, share it, or copy grants to a new installation.

## Reporting vulnerabilities

Use the repository's **Security → Report a vulnerability** private reporting feature when enabled. If it is unavailable, contact the repository owner privately; do not post exploit details, real credentials or raw evidence in a public issue. Include the affected version, minimal fictional reproduction, expected impact and safe mitigation suggestions.

## Handling local data

Reports, settings, scripts, startup logs and evidence archives may contain sensitive data. They are excluded from the standard release archive; `.gitignore` is only a convenience and does not remove already tracked data or protect arbitrary exports. Review staged files and every shared export. If a real credential has been exposed, revoke or rotate it rather than relying on deletion alone.

## Supported versions

The current development line is 4.2.x; consult published releases for the latest available package. No formal response-time or long-term support commitment has been established by the owner.
