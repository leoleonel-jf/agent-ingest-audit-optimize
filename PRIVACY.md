# Privacy Policy

Effective date: July 28, 2026

Agent Ingest, Audit & Optimize is a Skill plugin. The publisher does not operate a backend service for the plugin and does not independently collect, transmit, sell, or retain user data.

## Information processed

The plugin provides instructions and local resources to the AI agent host selected by the user. Material supplied to the plugin, agent conversation data, tool calls, and generated results may therefore be processed by that host and by any tools or connectors the user authorizes. Their respective privacy policies and account settings govern that processing.

The plugin bundles one executable, `assets/scripts/dashboard.py`. It runs locally and makes no network request. Its `verify` command reads only the paths passed to it on the command line. Its `scan` command reads the configuration files a client adapter names, which is described in the next section. Its `drift` and `rollback-preview` commands re-read those files and the ledger's recorded backups, and are described below as well. The repository's packaging and evaluation scripts are development tooling used to build and test releases; they are excluded from both distributed archives and never reach a user's installation.

## What the `scan` command reads

`scan` records what an agent client has configured. It opens the files listed by the adapter selected for that client, beneath configuration roots resolved from the environment and from the paths given on its command line, computes a SHA-256 digest of each file's bytes, and parses the JSON and TOML documents among them. It executes nothing: a configuration key whose value is a shell command is recorded as text and never run. It writes nothing at all — no file, no directory, no ledger entry — and prints the resulting baseline to standard output for the user or the agent to review before anything is saved.

Redaction matches on key names and never on values. A key whose **name** matches one of the adapter's `sensitive_key_patterns` — tokens, keys, secrets, passwords, credentials, argument lists, URL-bearing keys, and environment and header blocks — is redacted whatever the type of the value beneath it. The key name is kept and the value is replaced by a digest, and the walk stops there: nothing beneath a redacted value is read or recorded, so an entire environment block is reduced to one digest without its variable names being enumerated. Every object and array whose key matched nothing is walked in turn, to the bottom of the document.

Because the match is on the name, a secret carried inside a value whose own key matches no pattern is copied into the baseline in full: a credential passed as a positional command-line argument, a token sitting in the query string of a URL, a secret whose only unusual property is the name someone gave it. The shipped client adapters redact `args` and every key containing `url` precisely because those are the two shapes where this was found to happen, but the patterns are data rather than code and they cannot anticipate a key name this project has never seen. A user whose configuration puts a secret somewhere else should add a pattern for that key to their own adapter, at `<user-config>/agent-ingest-audit-optimize/adapters/local.json`, and scan with that.

A parsed value that does **not** match one of those patterns is copied into the baseline verbatim. A baseline can therefore contain absolute local filesystem paths, account and user names, project names, and any other content of a configuration file that is not secret-shaped. A single Codex configuration key produced thirteen absolute local paths in this project's own first real run of the command. The anchoring rules that keep a stored path portable apply to an item's recorded location, not to a parsed value: the value is whatever the file said.

A baseline is a local file like any other in the ledger, and it is never transmitted. Treat it as personally identifying: review it before pasting it into an issue, a chat, or a repository, and keep it out of a directory that is committed.

## What the `drift` and `rollback-preview` commands read

`drift` and `rollback-preview` read the same files `scan` reads — the configuration files the selected adapter names — plus the ledger passed on the command line and, for `rollback-preview`, the backup files a run recorded. Both recompute SHA-256 digests and compare them with what the ledger recorded; neither executes anything. Both write nothing: no file, no directory, no ledger entry — each prints one JSON report to standard output and everything else to standard error.

Their reports carry digests, classification states, and data the ledger already recorded — never a configuration value read from the environment. A report still names recorded anchors, item names, and record identifiers, so review it like any other ledger content before pasting it anywhere public.

## What the `build` command does

`build` reads one ledger and writes exactly one local HTML file — `dashboard.html` next to the ledger by default, or the path given with `--out` — and nothing else. It makes no network request and transmits nothing; the file is meant to be opened directly in a browser from disk. It also reads the same configuration files `drift` and `rollback-preview` read, to compute the drift and rollback-preview data the dashboard embeds.

The generated dashboard contains ledger data verbatim — record titles, evidence sources, backlog reasons, file anchors, and everything else `ledger.json` holds — rendered as inert text, never as executable content. Treat it exactly as you would treat the ledger itself: at project scope, it belongs in `.gitignore` alongside the rest of what a project ledger excludes. `.agent-audit/.gitignore` is written to cover `dashboard.html` specifically (see [references/LEDGER.md](skills/agent-ingest-audit-optimize/references/LEDGER.md)), because unlike the ledger's records, a generated dashboard is disposable: it can always be regenerated from the ledger and carries no information the ledger itself lacks.

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
