# Privacy Policy

Effective date: July 28, 2026

Agent Ingest, Audit & Optimize is a Skill plugin. The publisher does not operate a backend service for the plugin and does not independently collect, transmit, sell, or retain user data.

## Information processed

The plugin provides instructions and local resources to the AI agent host selected by the user. Material supplied to the plugin, agent conversation data, tool calls, and generated results may therefore be processed by that host and by any tools or connectors the user authorizes. Their respective privacy policies and account settings govern that processing.

The plugin bundles one executable: the ledger validator, `assets/scripts/dashboard.py`. It runs locally, makes no network request, and reads only the paths passed to it on the command line. The repository's packaging and evaluation scripts are development tooling used to build and test releases; they are excluded from both distributed archives and never reach a user's installation.

## External material and tools

The workflow may recommend consulting websites, documentation, repositories, files, or connected services. Access occurs only through the capabilities and permissions available in the user's agent environment. The plugin does not receive a separate copy of credentials or connected-service data.

## Ledger data

The ledger, its records, and its backups are local files created in the user's own
environment. The plugin never transmits them. Backups may contain configuration values and are
always written to the global scope, never inside a project directory, so they are not
committed by accident.

## Data retention

The publisher does not maintain plugin-specific user accounts or a plugin-specific data store. Local files, host conversation history, logs, and connected-service records remain subject to the user's environment and the applicable service provider.

## Security and sensitive information

Users should not place secrets or sensitive personal information in public issues. Security concerns should be reported according to [SECURITY.md](SECURITY.md).

## Changes

Material changes to this policy will be documented in the repository history and release notes.

## Contact

Questions about this policy may be submitted through the project's [GitHub issue tracker](https://github.com/leoleonel-jf/agent-ingest-audit-optimize/issues).
