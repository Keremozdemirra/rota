# destroy-guard

**A Claude Code hook that makes `terraform destroy`, `kubectl delete`, `helm uninstall` and `git push --force` wait for a verified backup of exactly what they remove.**

When Claude is about to run one of these commands, destroy-guard looks for a fresh,
verified backup of that exact target: the same Terraform directory and workspace, the
same Kubernetes context, namespace, kind and name, the same Helm release, the same remote
and branch. If there is none, you get a permission prompt that says what the command
removes and names the one command that makes the backup. If there is one, destroy-guard
says nothing and your normal permission settings decide. It never approves anything on
its own, and it never blocks: you can always approve at the prompt.

## Why it exists

- On 2026-02-26 a Claude Code session deleted the production infrastructure of
  DataTalks.Club. The agent's own words, quoted in Alexey Grigorev's post-mortem: "I cannot
  do it. I will do a terraform destroy." The post's timeline: "A Terraform auto-approve
  command inadvertently wiped out all production infrastructure, including the Amazon
  Relational Database Service (RDS)", and "all automated snapshots were deleted too"
  ([post-mortem, 2026-03-06](https://aishippingblog.com/p/how-i-dropped-our-production-database);
  [Hacker News item 47278720](https://news.ycombinator.com/item?id=47278720), posted
  2026-03-06; both checked 2026-09-24). The post also says the agent had replaced the
  current state file with an older one, and that AWS support restored the database from a
  snapshot that was not visible in the console.
- Claude Code's rewind does not cover this: "Checkpointing does not track files modified
  by Bash commands" ([checkpointing docs](https://code.claude.com/docs/en/checkpointing),
  checked 2026-09-24), and a remote resource is not a file at all.
- Hooks that guard these commands exist. The READMEs of
  [claude-guard](https://github.com/hex/claude-guard) and
  [cc-safe-setup](https://github.com/yurukusa/cc-safe-setup) describe refusing such commands
  or redirecting them to a safer variant; neither makes a backup a precondition (checked
  2026-09-24). destroy-guard does not refuse. It asks, until the backup exists.

## A real run

2026-09-24, git 2.43.0, destroy-guard 0.1.0 installed from the built wheel, against a local
bare repository made for the check in a scratch directory (the long paths below are that
directory). A teammate has pushed `teammate: fix login`; this clone has not seen it and has
rewritten `v1`. The session:

```
$ git log --oneline -1 origin/main  (what this clone last saw)
22a1ba9 v1
$ git ls-remote origin main  (what the remote has now)
7f41f169719b3f2e94ca2380e7cf4639a68b3486	refs/heads/main

$ # the hook, as Claude Code calls it before: git push --force origin main
{
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "destroy-guard: `git push --force` overwrites refs/heads/main on origin (repository /tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/review-119/live119/app). No backup of it from the last 30 min. To make one, run `destroy-guard backup -- git push --force origin main` on its own first. The 30 min window is destroy-guard's own choice (DESTROY_GUARD_MAX_AGE_MINUTES changes it). Approving runs the command as it is.",
        "additionalContext": "(the same text, plus one sentence for Claude; shortened here)"
    }
}

$ destroy-guard backup -- git push --force origin main
git push --force overwrites refs/heads/main on origin (repository /tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/review-119/live119/app); backing it up
  refs/heads/main on origin was 7f41f169719b3f2e94ca2380e7cf4639a68b3486; kept as refs/destroy-guard/main-20260924T190214Z
  git-main.txt: 117 bytes, sha256 89b8f2d158feb993...
verified backup: /tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/review-119/live119/app/.destroy-guard/backups/20260924T190214Z-81cab2e55107
  counts for this exact target until 19:32:14 UTC (30 min, destroy-guard's own window)
  .destroy-guard/ is listed in /tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/review-119/live119/app/.git/info/exclude
Backups can hold secrets: Terraform state often contains passwords and keys, Kubernetes Secrets are only base64-encoded, Helm values often carry credentials. They stay on this machine, in a directory only you can read; destroy-guard never uploads or prints them.
exit 0

$ # the hook again, same command
(no output: the normal permission flow decides)

$ git push --force origin main
To /tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/review-119/live119/origin.git
 + 7f41f16...8725cc3 main -> main (forced update)
$ git log --oneline -1 --glob='refs/destroy-guard/main-*'
7f41f16 teammate: fix login
$ git status --porcelain  (the store is excluded)
(empty)
```

The teammate's commit survives the force push under `refs/destroy-guard/`. The backup
fetches with an empty `--refmap`, so `origin/main` stays where it was and a later
`git push --force-with-lease` still refuses on stale information; the test suite checks
this with the real git. Only the `additionalContext` value is shortened above; everything
else is the output as printed.

**Terraform, OpenTofu, kubectl and Helm were exercised only through fake executables** that
the tests write (they print recorded-shape state, objects and release text, or fail in the
ways the real tools fail). No cluster, cloud account or Terraform binary was available where
this was built.

## Install

### Claude Code plugin

```
/plugin marketplace add Keremozdemirra/destroy-guard
/plugin install destroy-guard@destroy-guard
```

That adds the hook (PreToolUse, one handler for the Bash and PowerShell tools) and a skill:
ask "make a backup before you delete this" or "why did destroy-guard ask?". The hook runs
`python3`, so Python 3.9 or later must be on your `PATH` as `python3`; on Windows, check that
`python3 --version` works in the shell Claude Code uses.

### Command line

```bash
uvx destroy-guard@0.1.0 backup -- terraform destroy          # make a backup
uvx destroy-guard@0.1.0 check -- kubectl delete ns staging    # what the hook would say
pipx run --spec destroy-guard==0.1.0 destroy-guard list       # the same with pipx
```

### As a hook, without the plugin

Install it once (`pipx install destroy-guard==0.1.0`), then in `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [{ "matcher": "Bash|PowerShell", "hooks": [
      { "type": "command", "command": "destroy-guard-hook", "timeout": 10 }
    ] }]
  }
}
```

Use the plugin or this, not both. "A plugin's or skill's copy of the same handler stays
separate" ([hooks docs](https://code.claude.com/docs/en/hooks), checked 2026-09-24), so
with both, two processes start for every Bash and PowerShell call. Only the first one to
claim the call answers. It claims the call with an empty file named after the
`tool_use_id`, created exclusively in a private temporary directory. Without the claim,
Claude would get the same text twice ("When several hooks return `additionalContext` for
the same event, Claude receives all of the values", same page).

There is one handler and no `if` rule, on purpose. An `if` rule matches one tool's calls,
and a Bash rule more specific than a command name still fires on any command with `$()`,
backticks or `$VAR` (same page), so the filtering happens inside the script. Every Bash
and PowerShell call starts Python once. Commands that name none of the tools return after
one regular expression, which also runs on the line with its quotes and backslashes
removed.

## Commands

| Command | What it does |
| --- | --- |
| `destroy-guard backup [--cwd DIR] -- <command>` | Works out the read-only export for `<command>`, runs it, checks the result and stores it with a manifest. Run it on its own, before the destructive command. |
| `destroy-guard check [--cwd DIR] [--json] -- <command>` | What the hook would say about `<command>`, per operation: covered, missing (with the newest backup's age), a target it cannot resolve, or no automatic backup. |
| `destroy-guard list [--cwd DIR] [--json]` | The backups in the store, with their checksums verified. |

The command after `--` may also be given as one quoted string, for instance
`destroy-guard backup -- "cd infra && terraform destroy"`.

Exit codes. `backup`: 0 verified backup written; 1 an export failed its checks (non-zero
exit, no output, output that is not JSON, the wrong object), nothing kept; 2 nothing to back
up (not a destructive command it knows, a target it cannot resolve, SQL, tool not
installed, bad arguments). `check`: 0 nothing destructive or everything covered; 1 at least
one target has no fresh backup; 2 bad arguments. `list`: 0 all intact; 1 a backup file is
missing or its checksum differs.

## What it detects, and what the backup is

The hook reads the command the way a shell would:
- separators: `;`, `&&`, `||`, `|`, newlines, and line continuations (`\` and PowerShell's backtick);
- quoting: quotes and backslashes inside a word (`terr''aform`), and bash's `$'...'`;
- prefixes: `VAR=value` and `export`, `sudo`, `env` (with `-S`), `timeout`, `nohup`, `nice`,
  `time`, `caffeinate`, `xargs`;
- directories: `cd` and subshells;
- shells and evaluation: `bash -c` / `sh -c` / `fish -c`, `eval`, `cmd /c`, `pwsh -Command`,
  `watch`, `flock`, `find -exec`;
- substitutions: `$(...)`, backticks and `<(...)`. Each one also runs as a command line of its
  own, including inside double quotes. In the line around it, its value is unknown, so a
  target that uses it is unresolved;
- heredocs and here-strings fed to a shell, directly or through `cat`;
- the Windows forms: `& 'C:\...\terraform.exe'`, `$env:TF_WORKSPACE = ...`, script blocks
  such as `ForEach-Object { ... }`, and `Start-Process`;
- credential programs: `aws-vault exec`, `doppler run`, `op run`, `infisical run`,
  `chamber exec`, `saml2aws exec`, `dotenvx run`, `teller run`, `berglas exec`,
  `direnv exec`, `dotenv` and `summon`. The printed backup command runs inside the same
  program, because the export needs the same credentials. Given the whole wrapped command,
  `destroy-guard backup` runs the export without the program and says so.

Text that is only printed or written to a file (`echo`, `grep`, a commit message, a heredoc
into `cat`) is not a command.

| Command | Backup (`destroy-guard backup`) | Checked | Target it must match |
| --- | --- | --- | --- |
| `terraform destroy`, `terraform apply -destroy` (also through `TF_CLI_ARGS` / `TF_CLI_ARGS_apply`), `terraform state rm`, `terraform state push`, `terraform workspace delete -force`, and `apply` of a plan made with `plan -destroy` on the same line; the same for `tofu` | `terraform state pull` in the target directory, with `TF_WORKSPACE` set to the target workspace and `TF_CLI_ARGS*` removed | JSON object, integer `serial`, non-empty `lineage`, at least one resource; stored byte for byte, ready for `terraform state push` | tool, real directory (after `cd`, `-chdir`), `TF_DATA_DIR` when set (it holds the backend configuration), workspace (`TF_WORKSPACE`, `workspace select` on the line, `.terraform/environment`, the workspace `workspace delete` names) |
| `kubectl delete <kind> <name>...`, `<kind>/<name>` | `kubectl get <kind> <name> -o json`, pinned with `--context` to the target's context | a JSON object of the expected kind and name | context (`--context`, else the kubeconfig's `current-context`), kubeconfig path, namespace (`-n`, all, or the namespace the kubeconfig sets for that context, `default` when it sets none), kind (aliases such as `deploy`, `po`, `svc` normalised), name |
| `kubectl delete namespace <ns>` | the Namespace object, plus every object of every listable namespaced type in it (`kubectl api-resources`, events left out) | both are valid JSON; the contents are a list | as above |
| `kubectl delete crd <name>` | the definition, plus every object of that type in all namespaces | as above | as above |
| `kubectl delete <kind> -l <selector>` / `--field-selector` / `--all` | `kubectl get` with the same selector | a non-empty list | the selector as written |
| `kubectl delete -f <file or dir>` / `-k <dir>` | `kubectl get -f ... -o json` | objects with kind and name | the path and a SHA-256 of the files' content: edit the manifest and the backup no longer matches. For a `-f` directory: its `.json`, `.yaml` and `.yml` files, subdirectories only with `-R`; for `-k`, every file under the directory (files a kustomization reads from outside it, such as `../base`, are not hashed). A URL is matched by its address only. A path that is missing, unreadable or over 2000 files / 64 MB leaves the target unresolved |
| `helm uninstall` (`delete`, `del`, `un`) `<release>...` | `helm get all <release>` | not empty, and names the release | kube context, namespace (`-n`, `HELM_NAMESPACE`, else the context's namespace as above), release |
| `git push --force`, `-f`, `--force-with-lease`, `+refspec`, `--delete`, `:branch` | `git ls-remote` for the remote tip, `git fetch --no-tags --refmap=` of that ref, then `refs/destroy-guard/<branch>-<utc>` created at the tip | the commit exists locally after the fetch, and the new ref resolves to it | repository, remote (name, or URL with credentials masked), destination ref (`push.default`, `branch.<name>.remote`, `pushRemote` from the repository's own config) |
| `DROP ...` / `TRUNCATE` through `psql -c`, `mysql -e`, a heredoc or an `echo ... |`; `dropdb`; `mysqladmin drop` | none in v1 | | the prompt says so, and that a dump with the database's own tool is the manual equivalent |

Also asked about, without an automatic backup: `git push --mirror`, `--prune`, `--all`,
`--tags` with force, and `push.default = matching`, which rewrite many refs at once.

When the target cannot be known from the command line, the hook asks and says why, and no
backup can match such a command. That is the case for:
- a `$VARIABLE`, or a `$(...)` or backtick value in a name or path;
- `cd -`;
- names read from standard input through `xargs` or `-f -`;
- `--raw`;
- a Terraform `-state=` file.

Not in scope, and not asked about:
- `git reset --hard` on a branch with unpushed commits. It changes nothing outside the
  clone, and `git reflog` still has the commits.
- Plain `terraform apply` (with or without `-replace`), which can also destroy resources.
- Terragrunt; `kubectl replace --force` and `kubectl apply --prune`; `oc` and `kubecolor`.
- A force or mirror set in the repository's config: a `+` refspec in `remote.<name>.push`,
  or `remote.<name>.mirror`.
- Commands inside scripts, Makefiles, aliases or shell functions.
- A command whose name is built at run time: `$TF destroy`, `"$(which terraform)" destroy`,
  `source <(...)`.
- Commands run through `ssh`, `docker run`, `kubectl exec`, `parallel` or `sops exec-env`.
- Shells nested more than four deep (`bash -c "sh -c '...'"` and so on).
- PowerShell `-EncodedCommand`.
- Other datastores.

## Freshness and the exact target

A backup counts for 30 minutes. That window is this tool's own choice, not a standard: long
enough to make a backup and then run the command, short enough that the target has probably
not changed in between. `DESTROY_GUARD_MAX_AGE_MINUTES` changes it; a value that is not a
number of minutes above 0 and up to 10080 (a week) falls back to 30. A manifest dated more
than 60 seconds in the future is not counted.

A backup counts only for the targets written in its manifest:
- A backup of workspace `staging` does not cover `prod`, nor another `TF_DATA_DIR`.
- A backup of `deployment/web` in namespace `prod` does not cover `staging` or another context.
- A backup of `origin/main` does not cover `origin/release`.
- A backup of several objects covers any of them.

With `-n` left out, the namespace is the one the kubeconfig sets for the context. So after
`kubens staging`, a backup made while the context pointed at `prod` no longer counts. In a
kubeconfig entry this reader does not follow (YAML anchors, for example), the target says
"the context's default namespace", and a switch in between goes unnoticed; `-n` pins it.

A manifest is ignored in any of these cases:
- its directory has any permission bit for group or others, or belongs to another user (a
  git checkout or a plain copy normally gives 0755);
- an exported file is missing, empty or has another size;
- the manifest is malformed.

## What it reads, runs and sends

- **The hook** reads the command and these files, and nothing else:
  - the manifests under `.destroy-guard/backups/`, each read once per call;
  - `.terraform/environment` (the selected workspace);
  - `.git/HEAD`, and from the repository's own `.git/config` it keeps only
    `branch.<name>.remote`, `branch.<name>.pushRemote`, `branch.<name>.merge`,
    `remote.pushDefault` and `push.default`;
  - from the kubeconfig, the `current-context` line and that context's `namespace`. It reads
    line by line and stops once it has both, so in kubectl's own layout (keys in alphabetical
    order) it never reaches the `users:` entries that hold credentials. A JSON kubeconfig is
    parsed whole, and only those two values are kept;
  - the manifest files a `kubectl delete -f` or `-k` names, to hash them.

  It opens only regular files. A named pipe or a device in one of these places would block
  until the hook's timeout, and a timed-out hook gives no answer: "The call continues through
  the normal permission flow" ([hooks docs](https://code.claude.com/docs/en/hooks), checked
  2026-09-24).

  Names taken from these files (workspace, context, namespace, branch, remote) are used only
  when they are plain names. Anything else leaves the target unresolved, so text a
  repository carries does not reach the prompt or Claude's context.

  From the environment it reads `TF_WORKSPACE`, `TF_DATA_DIR`, `TF_CLI_ARGS`,
  `TF_CLI_ARGS_<command>`, `KUBECONFIG`, `HELM_NAMESPACE`, `HELM_KUBECONTEXT`,
  `DESTROY_GUARD_DIR` and `DESTROY_GUARD_MAX_AGE_MINUTES`, plus `HOME` for `~`, `PATH` to name
  the backup command, and the temporary directory.

  It runs no command and sends nothing anywhere. The one file it writes, when it asks, is the
  claim for that tool call: an empty file named after the `tool_use_id`, in `destroy-guard-<uid>` (mode 0700)
  under the system temporary directory. Claims older than ten minutes are removed.

  On any internal error it lets the command through to the normal permission flow and writes
  one line to stderr. "Stderr from a hook that exits 0 goes to the debug log only" ([hooks
  docs](https://code.claude.com/docs/en/hooks), checked 2026-09-24). Its answer is written as
  ASCII JSON, so the code page of a Windows console cannot keep it from being printed.
- **`destroy-guard backup`** runs only the commands in the table above, plus
  `terraform version -json`, `kubectl version --client -o json`, `helm version --short` and
  `git --version` for the manifest. They run with the destructive command's own `VAR=value`
  prefixes, so the export reaches the same account and backend. It sets
  `CHECKPOINT_DISABLE=1` for Terraform, which turns off Terraform's version and security
  bulletin check against HashiCorp's Checkpoint service
  ([Terraform CLI docs](https://developer.hashicorp.com/terraform/cli/commands), checked
  2026-09-24), and `GIT_TERMINAL_PROMPT=0` for git. It removes `TF_CLI_ARGS` and
  `TF_CLI_ARGS_<command>` from the export's environment: Terraform adds those arguments to
  every command ([environment
  variables](https://developer.hashicorp.com/terraform/cli/config/environment-variables),
  checked 2026-09-24), and `-destroy` does not belong on `state pull`. The exports talk to
  what the destructive command talks to (the state backend, the cluster API, the git remote).
  destroy-guard itself sends nothing and uploads nothing.
- **Printed:** what was exported (serial, lineage and resource counts by type; kinds and
  names; release names; commit IDs), file sizes and checksums. Never the contents.
- **Hidden as `***`** in the prompt, the manifest and the CLI output: credentials in URLs,
  `--token`/`--password` values, `mysql -p...`, and `VAR=value` prefixes other than
  `TF_WORKSPACE`, `TF_DATA_DIR`, `KUBECONFIG`, `HELM_NAMESPACE`, `HELM_KUBECONTEXT`,
  `AWS_PROFILE`, `AWS_REGION` and `AWS_DEFAULT_REGION`. The backup command in the prompt
  quotes every word, a hidden one included, so the shell does not expand `***`. When a
  value is hidden, the prompt says that the backup needs the original value in its place.

No third-party data source is involved: destroy-guard reads your files and the output of
your own tools, so there is no data licence or attribution to carry.

## Backups can contain secrets

Terraform state often holds passwords, keys and connection strings; Kubernetes Secrets are
only base64-encoded; Helm values often carry credentials. So `destroy-guard backup`:

- keeps everything under `.destroy-guard/` at the top of the git work tree (or in the
  current directory outside git; `DESTROY_GUARD_DIR` puts it elsewhere), with the directories
  at mode 0700 and the files at 0600, tightening an existing directory that is looser;
- lists `/.destroy-guard/` in `.git/info/exclude` (in the main repository's git directory for
  a worktree) and puts a `.gitignore` containing `*` inside the store, so nothing in it is
  committed by accident;
- refuses to write through a symbolic link;
- removes a half-written backup when an export fails;
- prints the warning above after every backup, and never prints what it stored.

Old backups are never deleted automatically. Delete the directories under
`.destroy-guard/backups/` yourself when you no longer need them.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

Offline, standard library only. The suite covers:
- a table of real-world command lines. Positives include line continuations, substitutions in
  the middle of a command, quotes inside a name, xargs, credential programs and PowerShell
  script blocks. Negatives include `terraform plan`, `kubectl delete --dry-run=client`,
  `echo terraform destroy`, heredocs and commit messages;
- target resolution, including the kubeconfig's namespace for a context and `TF_DATA_DIR`;
- manifest matching: exact target, freshness, clock skew, tampering, permissions and malformed
  manifests;
- the backup CLI with fake `terraform`, `kubectl`, `helm` and `git` on `PATH`, including
  non-zero exits, empty output, invalid JSON, the wrong object and timeouts;
- `.git/info/exclude` handling;
- hook payloads, exit codes, one answer per tool call, and an answer on a non-UTF-8 stdout;
- the time a long line, a full store or crafted SQL takes;
- the backup command run through bash to check that nothing is globbed;
- the force-push flow with the real git when git is installed.

## What this is not

- **Not a backup of your data.** A Terraform state backup restores Terraform's record of the
  resources, not the rows in a database, the objects in a bucket or the files on a volume.
  In the incident above it would not have brought the database back; a provider snapshot
  did. For data, use the provider's own protection: deletion protection, final snapshots,
  retained volumes, versioned buckets, `prevent_destroy`.
- **Not a security boundary.** It guards against accidents. Anything that can write files in
  the project can write a manifest, and anything that can run a command can run it in a way
  the hook cannot read. For hard limits use Claude Code's permission rules and the
  permissions of the credentials the agent holds.
- **Not a refusal.** It asks; you decide. Where nobody can answer a prompt, an "ask" works as
  a refusal: the `dontAsk` mode "auto-denies every call that would otherwise prompt"
  ([permissions](https://code.claude.com/docs/en/permissions)), and in a `-p` run with no
  permission host such requests are denied
  ([headless](https://code.claude.com/docs/en/headless)); in auto mode a hook's "ask" still
  produces a prompt ([hooks](https://code.claude.com/docs/en/hooks)); all checked 2026-09-24.
- **Not a restore tool.** It keeps what was there. Putting it back (`terraform state push`,
  `kubectl apply -f`, `git push --force origin <backup ref>:<branch>`) is a decision it
  leaves to you.
