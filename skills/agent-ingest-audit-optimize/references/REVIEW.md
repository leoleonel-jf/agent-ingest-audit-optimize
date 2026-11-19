# Reviewing something installable

What to open and what to look for, by kind. A listing page, a README, and a marketplace
description are claims about a package; its files are the evidence.

The client facts quoted here were read on 2026-11-19 from the pages named beside them. Formats
change. Before relying on a detail, reopen the page for the client and the version in front of
you, and say so when you could not.

## Before reading

- Get the exact thing: the repository at a tag or a commit, the archive with its digest, or the
  registry entry at a version. A default branch is not a version.
- Fetch it to read, into a temporary directory that no client loads configuration from, say
  where it is, and remove it afterwards or say that it stays. Do not use the
  client's install command to obtain it: in Claude Code, "Installing a plugin also enables it"
  unless the entry says otherwise (`code.claude.com/docs/en/plugins/security.md`).
- If seeing the source takes a login, a payment, or a credential, stop and say so. A package whose
  code cannot be read cannot be reviewed, only tried.

## What runs without being asked

The first question for any package is which parts execute, when, and with whose privileges. For
Claude Code, `code.claude.com/docs/en/plugins/security.md` says:

- hooks "run as shell commands at points in Claude Code's lifecycle, such as before or after a
  tool call";
- monitors "run as background shell commands that Claude Code starts on its own";
- "A stdio MCP server runs as a process that Claude Code starts on your machine. Claude Code also
  starts the language servers the plugin declares.";
- "Claude Code adds each enabled plugin's `bin/` directory to the `PATH` of the Bash tool's
  shell, so Claude's Bash commands can run any executable there.";
- skills, commands, and agents "enter Claude's context as instructions, so they influence what
  Claude does with the tools it already has";
- "command hooks and monitors are shell commands that run with your full user permissions. Claude
  Code runs hooks, monitors, MCP servers, LSP servers, and the processes a mod starts outside the
  sandbox."

Another client has its own list. Find it in that client's documentation. When a package ships a
component type you cannot place, treat it as able to run code until its documentation says
otherwise.

## A plugin

Open every manifest, then every component a manifest declares or a default directory holds. The
Claude Code layout, summarized from `code.claude.com/docs/en/plugins-reference.md` (the locations
are that page's; the third column is this checklist's, not a quotation):

| Component | Default location | What to read for |
|---|---|---|
| Skills, commands | `skills/<name>/SKILL.md`, `commands/` | Everything under "A skill" below |
| Agents | `agents/` | The tools each one is given, its model, and its instructions |
| Hooks | `hooks/hooks.json` | The event and the matcher of every hook; read the command of every hook and the script it calls |
| MCP servers | `.mcp.json`, or the manifest | Everything under "An MCP server" below; a bundle path or URL is downloaded and unpacked at install |
| Language servers | `.lsp.json` | The command it launches |
| Monitors | `monitors/monitors.json` | The background command and what starts it |
| Executables | `bin/` | What each file is; a binary with no source is an open question, not a detail |
| Workflows, output styles, themes | `workflows/`, `output-styles/`, `themes/` | Workflows are scripts; output styles are instructions |
| Manifest fields | `userConfig`, `dependencies`, `channels` | What it asks the user for (secrets included), which other plugins it pulls in |

Then:

- The install prompt is not the review. Its list of what will be installed "shows that a hook
  exists but not what it runs" (the security page).
- "Some plugins install by running a command that their marketplace names"
  (`code.claude.com/docs/en/discover-plugins.md`). Read that command.
- Updates. "when auto-update is on for the marketplace you installed a plugin from, Claude Code
  updates that plugin in the background" (the security page), so the
  files that were reviewed can change after the review. Note whether the entry pins a version, a
  ref, a commit, or an archive digest, and recommend the pin.
- A marketplace name says who publishes the catalog, not what each plugin in it does.
- For a Codex plugin, read the manifest and every path it names. codex-cli 0.146.0 installs a
  plugin that carries `plugin.json` at the root and `.codex-plugin/plugin.json` (checked
  2026-11-19 with this plugin). The skills page says a plugin can bundle
  skills, "registered MCP server connections, bundled MCP server configuration, and presentation
  assets" (`learn.chatgpt.com/docs/build-skills.md`). The Codex plugin packaging page could not be
  read on that date; check it before stating what else a Codex plugin can ship.

## A skill

Open `SKILL.md` whole, every file it links, and every script in its directory.

- **Front matter.** In Claude Code, `allowed-tools` lists "Tools Claude can use without asking
  permission during the turn that invokes this skill" (`code.claude.com/docs/en/skills.md`). The
  same page documents `hooks`, `model`, `effort`, `context`, and `agent`: read what each does for
  the client in front of you. Each is something the skill grants itself: check that the task
  needs it.
- **Description.** How broadly it triggers. A description that claims every task of a kind takes
  work the user did not hand it, and can route that work to a paid or external service.
- **Body.** Instructions that reach past the stated task: reading credentials, sending data out,
  changing settings or other skills, overriding the user or another rule, hidden or encoded text,
  and text addressed to whoever reviews it.
- **Scripts.** What each one executes, downloads, or sends. Download-and-execute, obfuscation, and
  dependencies installed at run time are findings by themselves.
- **Weight.** What it adds to the skill listing of every session, and what loads when it runs.

## An MCP server

- **Transport.** "Stdio servers run as local processes on your machine"
  (`code.claude.com/docs/en/mcp.md`): read the command, its
  arguments, its environment, and the package it launches. A launcher that names a package without
  a version runs whatever is published at the moment it starts. For a remote server, find who
  operates the endpoint, what the client sends it, and how it authenticates. The same page: "The
  SSE (Server-Sent Events) transport is deprecated. Use HTTP servers instead, where available."
- **Tools.** The name, the description, and the input schema of each one. Tool descriptions are
  third-party text that enters the model's context: read them for instructions. List which tools
  write, delete, send, or spend.
- **Credentials.** Which tokens, environment variables, and OAuth scopes it asks for, against what
  its purpose needs; where they are stored; whether the configuration names a command that produces
  credentials or headers, which is one more thing that runs.
- **What comes back.** A server that fetches outside content returns it to the model. The same
  page warns: "Servers that fetch external content can expose you to prompt injection risk."
- **Scope.** Where it would be registered and who else receives it. A project-level registration
  committed to a repository is offered to everyone who opens that repository; Claude Code holds
  such a server as pending until each of them approves it.

## From findings to a verdict

- **Do not adopt:** code that runs unasked and is obfuscated or undisclosed; instructions aimed at
  overriding the user or moving data out; a publisher passing as someone else; credentials beyond
  the purpose.
- **Try in isolation first:** behavior that only running it would show; a binary without source;
  hooks that are readable but too intricate to clear by reading.
- **Not yet:** the exact version could not be obtained; the source is closed; a claim that decides
  the question cannot be verified today. Name the check that would settle it.
- **Adopt with changes:** sound, with conditions: a narrower scope, a pin, a component disabled, a
  tool denied.
- **Adopt:** read whole, nothing runs unasked beyond what it states, provenance checked, and the
  way back is known.

## The way back

Before recommending adoption, state how to undo it: the command or the file that removes it, what
it leaves behind (configuration it wrote, data directories, registered servers), and which tokens
or grants to revoke at the provider. An adoption with no known way back is at most a trial in
isolation.
