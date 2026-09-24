---
name: credential-reach
description: List the credentials an agent session on this machine could use (environment variables, AWS/gcloud/Azure CLI logins, kubeconfig contexts, Docker/npm/PyPI/Terraform tokens, netrc, git and gh credentials, SSH keys, the project's .env files, secrets in Claude Code transcripts) without printing any value. Use when the user asks what their agent can reach or touch, wants to audit credentials before letting an agent run unattended, asks about the blast radius of a mistake, or wants to find secrets left in transcripts.
---

# credential-reach

`credential_reach.py` in this plugin reads the standard credential locations of this
machine and the current project and reports names, locations, hosts, profiles, lengths
and presence. It never prints a secret value, and its JSON output contains none.

## Run it

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/credential_reach.py" --json
```

Run it from the project directory, or add `--project DIR`. The environment section is the
environment this Bash tool gives to commands, which is what an agent session inherits.

## Rules while doing this

- Report from the tool's output only. Do not open, `cat`, `grep` or `Read` any of the files
  it lists, and do not run `env`, `printenv`, `echo $VAR`, `aws configure list`,
  `gh auth token` or anything else that would print a credential into this conversation.
- `--probe` sends each GitHub token it finds for github.com to `GET https://api.github.com/user`,
  once, to read the token's scopes. That uses the token. Run it only after the user says yes
  to exactly that.
- `--redact` rewrites Claude Code transcripts and asks for a confirmation typed at a terminal,
  so it refuses to run from here. Give the user the command to run themselves:
  `python3 "${CLAUDE_PLUGIN_ROOT}/credential_reach.py" --redact`. Say that it copies each file
  to a backup directory first and that the backup still holds the secrets.

## Reporting back

- Lead with `blast_radius`: what an agent running as the user could use, `high` first.
  Group by service (GitHub, AWS, Kubernetes, registries, SSH, project files, transcripts) and
  say in plain words what each one reaches, using the `detail` text.
- `high` means a usable credential sits in plain text (a file, a variable, a transcript) or
  a probe confirmed a powerful scope. `medium` means a logged-in CLI, a credential helper or an
  agent socket the agent can use through that program. `info` is configuration without a
  stored credential. These levels are this tool's own classification, not a standard.
- Mention `not_visible` notes where they matter: macOS Keychain, Windows Credential Manager,
  credential helpers and ssh-agent can hold more than the tool can see.
- Transcript findings are copies of secrets that passed through earlier sessions; suggest
  rotating those credentials as well as `--redact`, since a redacted transcript does not
  un-expose a token that was already used or shared.
- Offer concrete, reversible steps the user can choose from: move a token from the shell
  profile to a tool that asks for it, prefer fine-grained or short-lived tokens, add a
  passphrase to a key, git-ignore a `.env` file, or set `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`
  so Claude Code strips the credentials it recognises from the environment of its tools.
  Do not change any of their files or settings yourself unless they ask.
- `--markdown` gives a report they can paste into a note or an issue, if they ask. It has
  no secret values, but it does name hosts, profiles and accounts, so it is theirs to share.
