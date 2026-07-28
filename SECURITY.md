# Security Policy

## Supported version

Security fixes are applied to the latest published version.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

## Reporting a vulnerability

Do not include secrets, personal data, private source material, or working exploit details in a public issue.

Use [GitHub private vulnerability reporting](https://github.com/leoleonel-jf/agent-ingest-audit-optimize/security/advisories/new) when it is available. If private reporting is unavailable, open a minimal public issue requesting a private contact channel without disclosing the vulnerability.

Include:

- affected version and client;
- impact and prerequisites;
- a minimal reproduction or proof of concept;
- suggested remediation, if known.

The maintainer will assess reports on a best-effort basis. No response-time commitment is offered.

## Security boundaries

This is a skills-only plugin with no publisher-operated backend, authentication system, telemetry, or runtime dependency installation. Its workflow treats external material as untrusted evidence, requires explicit authorization for persistent implementation, and defines stop conditions for destructive, irreversible, costly, or public actions.
