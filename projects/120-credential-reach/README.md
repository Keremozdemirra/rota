# credential-reach

**Lists the credentials an AI agent running as you on this machine could use, without printing a single secret.**

An agent that runs commands in your shell inherits your environment variables, your
cloud CLI logins, your kubeconfig, your registry tokens, your SSH keys and whatever
sits in the project's `.env` files. Whatever it can read, it can use.

On 2026-04-25 the founder of PocketOS described how a coding agent working on a
staging task hit a credential mismatch, went looking for an API token, and found one
"in a file completely unrelated to the task it was working on". The token had been
created to add and remove custom domains through the Railway CLI, but it had
"blanket authority across the entire Railway GraphQL API". The agent used it to
delete a production volume, and the volume-level backups went with it
([post](https://twitter.com/lifeof_jer/status/2048103471019434248), discussed as
[Hacker News item 47911524](https://news.ycombinator.com/item?id=47911524) on
2026-04-26; both checked 2026-09-24).

`credential-reach` answers the question to ask before that happens: if my agent went
wrong, what could it touch? It reads the standard credential locations on this machine
and in the current project and reports names, locations, hosts, profiles, lengths and
presence, grouped into a blast-radius summary. Values are parsed only to tell what kind
of credential sits where, and never printed, logged or sent.

```
credential-reach 0.1.0: what an agent running as you here can reach
checked 2026-09-24T13:53:20Z on Linux · home /tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/cr-demo/home · project ~/work/app
No secret values are shown: names, locations, hosts, profiles, lengths and presence only.

Blast radius
  high    Environment: ANTHROPIC_API_KEY holds an Anthropic API key
  high    Environment: DATABASE_URL holds a URL with an embedded password
  high    Environment: GITHUB_TOKEN holds a GitHub personal access token (classic); a classic token reaches every repository the account can access
  high    AWS: long-term access keys for profile default (~/.aws/credentials)
  high    Google Cloud: application-default credentials (authorized_user), used by every Google client library on this machine
  high    Kubernetes: context prod reaches cluster prod (203.0.113.10:6443) as prod-admin with stored token
  high    Kubernetes: context dev reaches cluster dev (dev.k8s.example.com) as dev-user with client certificate with inline key
  high    Docker: push and pull as you on index.docker.io; credentials stored in ~/.docker/config.json
  high    npm: publish and install as you on registry.npmjs.org; token stored in ~/.npmrc
  high    PyPI: upload as you to upload.pypi.org (pypi in ~/.pypirc)
  high    netrc: a password for api.heroku.com in ~/.netrc
  high    Git: push and pull as you on github.com; credentials stored in ~/.git-credentials
  high    Git: push and pull as you on gitlab.com; credentials stored in ~/.git-credentials
  high    GitHub CLI: signed in to github.com as dev; token in plain text in ~/.config/gh/hosts.yml
  high    SSH: ~/.ssh/id_ed25519 (ssh-ed25519) has no passphrase; it opens every host and repository that trusts its public key
  high    Terraform: an API token for app.terraform.io in ~/.terraform.d/credentials.tfrc.json
  high    Project: .env holds 3 credential-like values (GITHUB_TOKEN, STRIPE_SECRET_KEY, DATABASE_URL), not git-ignored
  high    Project: certs/server.key: private key: PKCS#8 ed25519, no passphrase, not git-ignored
  high    Project: config/.env.local holds 1 credential-like value (OPENAI_API_KEY), git-ignored
  high    Claude Code transcripts: 4 secret-shaped strings (github-classic-pat 1, aws-access-key-id 1, private-key 1, url-password 1) in 1 file under ~/.claude/projects, readable by any process running as you
  medium  AWS: temporary access keys for profile ci-temp, until they expire
  medium  AWS: profile deploy assumes role Deploy in account 123456789012, via default
  medium  AWS: profile prod signs in through IAM Identity Center; usable while a cached SSO session is valid
  medium  AWS: profile vault gets credentials from aws-vault
  medium  AWS: 1 cached SSO or role session still valid
  ... and 11 more below

Environment variables
  high    ANTHROPIC_API_KEY  93 chars, Anthropic API key
  high    DATABASE_URL       49 chars, URL with an embedded password
  high    GITHUB_TOKEN       40 chars, GitHub personal access token (classic)
[...]
Kubernetes (kubeconfig)  (~/.kube/config)
  high    context prod (current)  cluster prod (203.0.113.10:6443), user prod-admin: stored token
  high    context dev             cluster dev (dev.k8s.example.com, TLS verification off), user dev-user: client certificate with inline key
  medium  context eks             cluster eks (abcdef.gr7.eu-central-1.eks.amazonaws.com), user eks-user: exec plugin aws (credentials from that program at run time)
  not visible here: Exec plugins and auth providers get credentials from another program at run time (a cloud CLI, kubelogin), which may use macOS Keychain or Windows Credential Manager; what they return is not visible here.
[...]
SSH keys  (~/.ssh)
  high    ~/.ssh/id_ed25519  OpenSSH ssh-ed25519, no passphrase
  medium  UseKeychain yes    ~/.ssh/config lets macOS supply key passphrases from the Keychain
  medium  ssh-agent          SSH_AUTH_SOCK is set: keys loaded into the agent work without their passphrase (the agent was not queried)
  info    ~/.ssh/legacy.pem  PEM rsa, passphrase-protected
  info    ~/.ssh/work_rsa    OpenSSH ssh-rsa, passphrase-protected
  not visible here: macOS can keep a key's passphrase in the Keychain (UseKeychain), and a running ssh-agent holds unlocked keys; neither is queried, so a passphrase-protected key may still be usable.
[...]
Claude Code transcripts  (~/.claude/projects)
  high    ~/.claude/projects/-home-dev-work-app/7f0d1ba1f658fa7f79534401927f77e7.jsonl  aws-access-key-id 1 in 1 line, github-classic-pat 1 in 1 line, private-key 1 in 1 line, url-password 1 in 1 line
  note: 4 secret-shaped strings in 1 of 2 files (github-classic-pat 1, aws-access-key-id 1, private-key 1, url-password 1). They are plaintext copies of what passed through a tool; `credential-reach --redact` replaces them after a confirmation and a backup.

GitHub probe  (GET https://api.github.com/user, one request per token)
  info    $GITHUB_TOKEN: personal access token (classic): rejected (401): revoked, expired or not a valid token
  info    ~/.git-credentials: personal access token (classic): rejected (401): revoked, expired or not a valid token
  info    ~/.config/gh/hosts.yml: OAuth token: rejected (401): revoked, expired or not a valid token

20 high · 16 medium · 10 info
Not read: macOS Keychain, Windows Credential Manager, browser sessions, and MCP server settings; programs the agent can run may still use what they hold.
```

This is real output from 2026-09-24, abridged where it says `[...]`, of
`python3 tests/synthetic.py --run cr-demo -- --probe`. That command builds a
**synthetic** home directory and project filled with fake credentials generated at run
time, then runs `credential-reach --probe` there with `HOME` pointed at it and a clean
environment. None of these credentials exist. The probe was live: the three fake GitHub
tokens went to api.github.com, which rejected each with 401.

## Install

### Claude Code plugin

```
/plugin marketplace add Keremozdemirra/credential-reach
/plugin install credential-reach@credential-reach
```

That adds a skill, no hook. Ask "what can my agent reach?" or "audit my credentials
before I let an agent run" and Claude runs the audit, reads the JSON (which holds no
values) and explains it. The skill tells Claude not to open the files it lists, not to
run `--probe` without your yes, and to leave `--redact` to you, since it needs a
confirmation typed at a terminal.

### Command line

No install, standard library only, Python 3.9 or newer:

```bash
# the newest code on main
curl -sL https://raw.githubusercontent.com/Keremozdemirra/credential-reach/main/credential_reach.py | python3 -
# or a fixed release
curl -sL https://raw.githubusercontent.com/Keremozdemirra/credential-reach/v0.1.0/credential_reach.py | python3 -
```

Or from PyPI, pinned to a release:

```bash
uvx credential-reach@0.1.0                     # audit this machine and the current directory
uvx credential-reach@0.1.0 --project ~/code/app --markdown
pipx run --spec credential-reach==0.1.0 credential-reach --json
```

`uvx credential-reach` without a version installs the newest release the first time and
reuses uv's cached copy after that; `uvx credential-reach@latest` refreshes it.

Run it the way your agent runs: from the project directory, in the same shell, so it sees
the same environment. Inside Claude Code (through the skill, or `!credential-reach` at the
prompt) it sees exactly the environment Claude Code's Bash tool passes to commands.

| Option | What it does |
| --- | --- |
| `--json` | JSON. It carries no secret value; the tests check this with planted canaries. |
| `--markdown` | A Markdown report, for a note or an issue. |
| `--project DIR` | The project to check for `.env` and secret-named files (default: the current directory). A path that is not a directory is an error (exit 2). |
| `--no-transcripts` | Skip the Claude Code transcript scan. |
| `--strict` | Exit 1 on any `high` finding, else 2 if a check could not complete, else 0. |
| `--probe` | Send each GitHub token found for github.com to `GET https://api.github.com/user`, once, to read its scopes. **This uses the token.** Off by default. |
| `--redact` | Replace secret-shaped strings in Claude Code transcripts with `[REDACTED:<type>]`, after a typed confirmation and a backup copy. |

Exit codes: without `--strict`, 0 (2 for a bad `--project`). With `--strict`: 1 when a
finding is `high`; else 2 when a file could not be read or parsed, or a probe could not
reach GitHub; else 0. With `--redact`: 0 done or nothing to do, 1 not confirmed, 2 stdin
is not a terminal, or a transcript could not be read or rewritten.

### Severity

The levels are this tool's own classification, not a standard:

- **high**: a credential sits where any process running as you can read it and use it as
  it is (a variable, a plain file, an unencrypted key, a transcript), or `--probe`
  confirmed a powerful scope.
- **medium**: a login or helper the agent can use through its program without seeing a
  secret (an SSO session, gcloud or Azure CLI login, gh with its token in the system
  store, a Docker or git credential helper, a kubeconfig exec plugin, an ssh-agent), or a
  key whose protection could not be read.
- **info**: configuration without a stored credential.

## What it reads

Environment variables of the process it runs in, and these files where they exist
(Linux and macOS paths; the Windows paths follow each tool's own rules, such as
`%APPDATA%\gcloud`, `%AppData%\GitHub CLI`, `%APPDATA%\terraform.d` and `_netrc`):

| Source | Files | Reported |
| --- | --- | --- |
| Environment | the process environment | names that look like credentials (`*_TOKEN`, `*_KEY`, `*_SECRET`, `*_PASSWORD`, `AWS_*`, ...), any value with a known token shape, URLs with an embedded password: name, length, kind |
| AWS CLI | `~/.aws/credentials`, `~/.aws/config` (or `AWS_SHARED_CREDENTIALS_FILE`, `AWS_CONFIG_FILE`), `~/.aws/sso/cache`, `~/.aws/cli/cache` | profiles; long-term or temporary keys, SSO, role, `credential_process`; cached sessions counted by expiry only |
| gcloud | `~/.config/gcloud` (or `CLOUDSDK_CONFIG`), `GOOGLE_APPLICATION_CREDENTIALS` | active configuration, account, project; stored logins by presence; the `type` of application-default credentials |
| Azure CLI | `~/.azure` (or `AZURE_CONFIG_DIR`) | subscription and account counts; which token cache files exist |
| Kubernetes | `~/.kube/config` (or every file in `KUBECONFIG`) | contexts, clusters (server host), users; token, token file, client key, password, auth provider or exec plugin |
| Docker | `~/.docker/config.json` (or `DOCKER_CONFIG`) | registries with stored auth yes/no, `credsStore`, `credHelpers` |
| npm | `~/.npmrc` (or `NPM_CONFIG_USERCONFIG`) | registries with `_authToken`, `_auth` or `_password`, or the variable a `${VAR}` names |
| PyPI | `~/.pypirc` | repositories, host, password stored yes/no |
| netrc | `~/.netrc`, `~/_netrc`, `NETRC` | hosts, login and password yes/no |
| Git | `~/.git-credentials`, `~/.config/git/credentials`, `credential.helper` in `~/.gitconfig` and `~/.config/git/config` | hosts with stored credentials; the helpers named |
| gh | `hosts.yml` in `GH_CONFIG_DIR`, `$XDG_CONFIG_HOME/gh` or `~/.config/gh` | hosts, user, token in the file or in the system store |
| SSH | `~/.ssh/*` except `*.pub`, `known_hosts`, `authorized_keys`, `config`; `UseKeychain` in `~/.ssh/config`; `SSH_AUTH_SOCK` | private key files: format, key type, passphrase yes/no, read from the unencrypted header (OpenSSH `PROTOCOL.key`, PEM `Proc-Type`, PKCS#8, PuTTY) without decrypting |
| Terraform | `~/.terraform.d/credentials.tfrc.json`, `~/.terraformrc` (or `TF_CLI_CONFIG_FILE`) | hosts with a token; a `credentials_helper` |
| Project | `.env`, `.env.*`, `*.env`, `.envrc` and secret-named files (`*.pem`, `*.key`, `id_rsa`, `*.tfstate`, `credentials.json`, `.npmrc`, ...) under `--project`, skipping `.git`, `node_modules` and virtual environments | variable names, which are credential-like with a value, and git status (`tracked`, `ignored`, `not ignored`) from `git ls-files` and `git check-ignore` |
| Transcripts | `~/.claude/projects/**/*.jsonl` and set-aside `*.jsonl.superseded-*` (or under `CLAUDE_CONFIG_DIR`) | per file, the count of secret-shaped strings and of lines per type |

Secret shapes in transcripts are the seven that `ship.sh` scans every commit for
(Anthropic and OpenAI keys, classic and fine-grained GitHub tokens, AWS access key IDs,
private key blocks, Replicate tokens) plus GitHub OAuth and App tokens, AWS secret keys
next to their name, Slack, GitLab, Google API, Stripe, npm, PyPI and Hugging Face tokens,
JWTs, passwords inside URLs and bearer tokens.

Git runs with `core.fsmonitor=false`, so that a repository's own configuration cannot make
it start a program. FIFOs and devices are never opened, and a credential file larger than
4 MB is not parsed; transcripts are read line by line, whatever their size.

## What it sends

Nothing, unless you pass `--probe`. Then, for each distinct GitHub token it found for
github.com (in `GITHUB_TOKEN` or `GH_TOKEN`, another variable holding a GitHub-shaped
token whose name does not mention an enterprise host, gh's `hosts.yml` for `github.com`,
or `~/.git-credentials` and `~/.netrc` entries for `github.com`), it sends one
`GET https://api.github.com/user` with that token and reads:

- `X-OAuth-Scopes`, which "lists the scopes your token has authorized"
  ([GitHub docs](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps), checked 2026-09-24).
  Fine-grained tokens have permissions chosen per token instead of scopes, and this
  endpoint does not list them, so the report says so.
- the account's `login`, and the `GitHub-Authentication-Token-Expiration` date when the
  response carries one.

A string goes out only if it matches GitHub's token formats (`ghp_`, `github_pat_`,
`gho_`, `ghu_`, `ghs_`, `ghr_`, [GitHub docs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github#githubs-token-formats),
checked 2026-09-24), or is a 40-character hex token in `GITHUB_TOKEN`, `GH_TOKEN` or a
github.com entry. Tokens for
GitHub Enterprise hosts are never sent to github.com. Using a token for this request is a
use of it; GitHub may record it, for example in the token's last-used date.

If `HTTPS_PROXY` is set, the request goes through that proxy, and the report says so
without printing the proxy's address. A proxy that inserts its own GitHub credentials
changes the answer: in the hosted sandbox this tool was built in, requests to
api.github.com sent through its proxy came back as the sandbox's own account, whatever
token they carried. The live check above ran without the proxy variables.

There is no other network code in the tool.

## What it changes

Nothing, unless you pass `--redact` and type `redact` at the prompt. Then each transcript
with secret-shaped strings is:

1. rewritten to a temporary file next to it, with every match replaced by
   `[REDACTED:<type>]`. A line that was valid JSON stays valid JSON: the in-place text
   replacement is kept only if it decodes to exactly the JSON-level replacement, and
   otherwise the line is written again from the parsed value;
2. checked: the same number of valid JSON lines, and no secret shape left;
3. copied, as it was, to `~/.claude/credential-reach-backups/<UTC time>/` (a directory
   only you can read). **That copy still holds the secrets.** Delete it once you have
   checked the result;
4. put in place of the original, unless the file changed on disk in the meantime (a
   session writing to it), in which case it is left as it was. Close Claude Code sessions
   before you redact.

Running it again finds nothing and changes nothing. A redacted transcript does not
un-expose a credential that already passed through a session: rotate those as well.

Claude Code keeps transcripts because it needs them: "Claude Code clients store session
transcripts locally in plaintext under `~/.claude/projects/` for 30 days by default to
enable session resumption" ([data usage](https://code.claude.com/docs/en/data-usage), checked 2026-09-24),
and "anything that passes through a tool is written to a transcript on disk: file
contents, command output, pasted text" ([the .claude directory](https://code.claude.com/docs/en/claude-directory), checked 2026-09-24).

## What each tool keeps where

The `not visible here` lines come from these sources, all checked 2026-09-24:

- **gh**: "an authentication token will be stored securely in the system credential store.
  If a credential store is not found or there is an issue using it gh will fallback to
  writing the token to a plain text file" ([gh auth login](https://cli.github.com/manual/gh_auth_login)).
- **Docker**: "If you don't configure a credential store, Docker stores credentials in the
  config.json file in a base64-encoded format" ([docker login](https://docs.docker.com/reference/cli/docker/login/)).
- **Azure CLI**: "The MSAL token cache and service principal entries are saved as
  encrypted files on Windows, and plaintext files on Linux and macOS"
  ([MSAL-based Azure CLI](https://learn.microsoft.com/en-us/cli/azure/msal-based-azure-cli)).
- **gcloud**: `gcloud auth login` "stores credentials in the gcloud CLI configuration
  directory" ([Authorize the gcloud CLI](https://cloud.google.com/sdk/docs/authorizing));
  application-default credentials live at `$HOME/.config/gcloud/application_default_credentials.json`,
  or `%APPDATA%\gcloud\...` on Windows ([ADC](https://cloud.google.com/docs/authentication/application-default-credentials)).
- **AWS**: access key IDs starting with `AKIA` are access keys, `ASIA` temporary STS keys
  ([IAM identifiers](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html));
  `AWS_CONFIG_FILE` and `AWS_SHARED_CREDENTIALS_FILE` move the files
  ([AWS CLI files](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html)).
- **Terraform**: `terraform login` saves the API token "in plain text in a local CLI
  configuration file called credentials.tfrc.json" ([terraform login](https://developer.hashicorp.com/terraform/cli/commands/login)).
- **Git Credential Manager**: "The default credential stores on macOS and Windows are the
  macOS Keychain and the Windows Credential Manager"
  ([GCM credential stores](https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/credstores.md)).
- **twine**: "Twine allows storing a username and password securely using keyring"
  ([twine docs](https://twine.readthedocs.io/en/stable/)).
- **GitHub classic tokens**: a personal access token (classic) "will grant access to all
  repositories within the organizations that you have access to, as well as all personal
  repositories in your personal account" ([GitHub docs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)).
- **Claude Code**: `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` strips "Anthropic and cloud provider
  credentials, any other variable that Claude Code recognizes as a credential" from the
  environment of the Bash tool, hooks and MCP stdio servers ([environment variables](https://code.claude.com/docs/en/env-vars)).

## Data source

None. Everything comes from files and variables on the machine it runs on. The only
remote answer it ever reads is GitHub's reply about your own token under `--probe`, which
is subject to the [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service).

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests never read the real home directory or environment: each one runs with `HOME`,
`USERPROFILE`, `APPDATA` and `XDG_CONFIG_HOME` pointed at a temporary directory, with the
process environment replaced, and with the network replaced by a stand-in that fails on
any request nobody prepared. Every fake secret is generated at run time, so this
repository contains no token-shaped text (one test checks that). One test plants a canary
in every file and variable the tool reads, runs every output format, `--probe` and
`--redact`, and fails if any canary, or any 12-character piece of one, appears in what it
printed.

Licence: MIT.

## What this is not

It is not a secret scanner for your code, and it does not decide whether a credential is
too powerful. It lists what is reachable from the standard places, so that you can decide
what an agent should run with. It does not read macOS Keychain, Windows Credential
Manager, Secret Service, browser sessions, MCP server `env` blocks, Claude Code's own
login, or credentials that programs fetch at run time; the report says where those can
exist. A clean report means none of the listed places holds a credential, not that the
machine holds none.
