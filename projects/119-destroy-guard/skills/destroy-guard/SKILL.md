---
name: destroy-guard
description: Make a verified backup before a destructive infrastructure command, and explain why destroy-guard asked for permission. Use when the user wants a backup before terraform destroy, tofu destroy, terraform state rm, kubectl delete, helm uninstall or git push --force; when destroy-guard asked for permission and the user asks why or what to do next; or before you run one of those commands yourself.
---

# destroy-guard

The destroy-guard hook reads every Bash and PowerShell command before it runs. For
`terraform destroy`, `terraform apply -destroy`, `terraform state rm` (and the `tofu`
equivalents), `kubectl delete`, `helm uninstall` and `git push --force` / `--delete`, it
looks for a fresh, verified backup of exactly the target the command hits. If there is
none, the person gets a permission prompt that names the command which makes one. If
there is one, the hook says nothing and the normal permission flow decides. It never
approves anything itself.

## Make a backup before you delete

Run the backup on its own, in the same directory the destructive command will run in,
with the destructive command after `--`, exactly as you will run it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/destroy_guard.py" backup -- terraform destroy -auto-approve
python3 "${CLAUDE_PLUGIN_ROOT}/destroy_guard.py" backup -- kubectl delete deployment web -n prod
python3 "${CLAUDE_PLUGIN_ROOT}/destroy_guard.py" backup -- git push --force origin main
```

- It runs only read-only exports: `terraform state pull`, `kubectl get ... -o json`,
  `helm get all`, `git ls-remote` + `git fetch` (and a local `refs/destroy-guard/...` ref).
- Exit 0 and a line starting `verified backup:` mean the backup exists. Exit 1 means an
  export failed its checks (tool error, empty or invalid output); nothing was written.
  Exit 2 means there is nothing it can back up (not a destructive command, a target it
  cannot resolve, SQL, or the tool is not installed). Report the message as it is.
- Then run the destructive command as a separate step. Do not put the backup and the
  destructive command on one line: the hook checks the whole line before any of it runs.
- A backup counts for 30 minutes (the tool's own window; `DESTROY_GUARD_MAX_AGE_MINUTES`
  changes it) and only for the same target: same directory and workspace, same kube
  context, namespace, kind and name, same Helm release, same remote and branch.

## Why did destroy-guard ask?

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/destroy_guard.py" check -- <the command>
python3 "${CLAUDE_PLUGIN_ROOT}/destroy_guard.py" list
```

`check` prints, per destructive operation, what it removes and whether a fresh backup
covers it (`--json` for fields). Explain it in plain words: no backup yet, the newest one
is too old, it was made for another target (workspace, namespace, context, branch), or the
target cannot be known from the command (a shell variable, a `cd` into `$DIR`, names read
from stdin). For SQL (`DROP`, `TRUNCATE` through psql or mysql) there is no automatic
backup in this version: suggest a dump with the database's own tool before the person
approves.

## Rules

- Never print, read out or summarise the contents of files under `.destroy-guard/`.
  Terraform state often holds passwords and keys; Kubernetes Secrets are only
  base64-encoded; Helm values often carry credentials. Quote only what the CLI printed.
- Never add `.destroy-guard/` to git. The CLI lists it in `.git/info/exclude`.
- Never reword a command to get past the prompt (variables, scripts, aliases, encoding).
  The person decides at the prompt; destroy-guard only makes sure a backup was offered.
- Say plainly that a backup holds state and object definitions, not the data inside
  databases, volumes or buckets. For those, the provider's snapshots are the backup.
- Restoring is the person's decision. If they ask: `terraform state push <file>`,
  `kubectl apply -f <file>` (after removing `resourceVersion`, `uid` and `status`), the
  manifest and values in the Helm text, or `git push --force origin <backup-ref>:refs/heads/<branch>`
  (itself a force push, so destroy-guard asks again).
