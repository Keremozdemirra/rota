"""The command detector against real-world command lines: what is destructive, and what only looks like it."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated  # noqa: E402

# (shell, command line, labels destroy-guard must report)
POSITIVE = [
    ("bash", "terraform destroy", ["terraform destroy"]),
    ("bash", "terraform destroy -auto-approve", ["terraform destroy"]),
    ("bash", "terraform -chdir=infra/prod destroy -auto-approve", ["terraform destroy"]),
    ("bash", "terraform apply -destroy -auto-approve", ["terraform apply -destroy"]),
    ("bash", "terraform apply --destroy", ["terraform apply -destroy"]),
    ("bash", "terraform apply -destroy=true -var-file=prod.tfvars", ["terraform apply -destroy"]),
    ("bash", "tofu destroy", ["tofu destroy"]),
    ("bash", "tofu apply -destroy -auto-approve", ["tofu apply -destroy"]),
    ("bash", "terraform state rm aws_instance.web", ["terraform state rm"]),
    ("bash", "terraform state rm -lock=false 'module.db.aws_db_instance.main'", ["terraform state rm"]),
    ("bash", "terraform plan -destroy -out=destroy.tfplan && terraform apply destroy.tfplan", ["terraform apply"]),
    ("bash", "cd infra && terraform destroy", ["terraform destroy"]),
    ("bash", "cd infra; terraform destroy -target=aws_instance.web", ["terraform destroy"]),
    ("bash", "TF_WORKSPACE=prod terraform destroy", ["terraform destroy"]),
    ("bash", "export TF_WORKSPACE=prod && terraform destroy", ["terraform destroy"]),
    ("bash", "sudo terraform destroy", ["terraform destroy"]),
    ("bash", "sudo -u deploy -E terraform destroy -auto-approve", ["terraform destroy"]),
    ("bash", "env TF_LOG=debug terraform destroy", ["terraform destroy"]),
    ("bash", "timeout 600 terraform destroy -auto-approve", ["terraform destroy"]),
    ("bash", "nohup terraform destroy -auto-approve > destroy.log 2>&1 &", ["terraform destroy"]),
    ("bash", 'bash -c "terraform destroy -auto-approve"', ["terraform destroy"]),
    ("bash", "sh -c 'cd /srv/infra && terraform destroy'", ["terraform destroy"]),
    ("bash", "bash -lc 'terraform destroy'", ["terraform destroy"]),
    ("bash", "bash -o pipefail -c 'terraform destroy | tee log'", ["terraform destroy"]),
    ("bash", "/usr/local/bin/terraform destroy", ["terraform destroy"]),
    ("bash", "echo start; terraform destroy; echo done", ["terraform destroy"]),
    ("bash", "terraform init&&terraform destroy", ["terraform destroy"]),
    ("bash", "terraform init || terraform destroy", ["terraform destroy"]),
    ("bash", "terraform destroy | tee destroy.log", ["terraform destroy"]),
    ("bash", "(cd infra && terraform destroy)", ["terraform destroy"]),
    ("bash", "if terraform plan; then terraform destroy -auto-approve; fi", ["terraform destroy"]),
    ("bash", "for d in a b; do (cd $d && terraform destroy -auto-approve); done", ["terraform destroy"]),
    ("bash", 'echo "result: $(terraform destroy -auto-approve)"', ["terraform destroy"]),
    ("bash", "echo `terraform destroy -auto-approve`", ["terraform destroy"]),
    ("bash", "bash <<'EOF'\nterraform destroy -auto-approve\nEOF", ["terraform destroy"]),
    ("bash", "sh <<EOF\ncd infra\nterraform destroy\nEOF\necho done", ["terraform destroy"]),
    ("bash", 'bash <<< "terraform destroy"', ["terraform destroy"]),
    ("bash", 'echo "terraform destroy -auto-approve" | bash', ["terraform destroy"]),
    ("bash", 'eval "terraform destroy"', ["terraform destroy"]),
    ("bash", "cat <<EOF\n$(terraform destroy -auto-approve)\nEOF", ["terraform destroy"]),
    ("bash", "kubectl delete pod web-1", ["kubectl delete"]),
    ("bash", "kubectl delete deployment web -n prod", ["kubectl delete"]),
    ("bash", "kubectl -n prod delete deploy/web svc/web", ["kubectl delete"]),
    ("bash", "kubectl delete pods,services web", ["kubectl delete"]),
    ("bash", "kubectl delete pods -l app=web", ["kubectl delete"]),
    ("bash", "kubectl delete pods --selector='app in (web,api)' -n prod", ["kubectl delete"]),
    ("bash", "kubectl delete pods --all -n staging", ["kubectl delete"]),
    ("bash", "kubectl delete pods --field-selector=status.phase=Failed -A", ["kubectl delete"]),
    ("bash", "kubectl delete -f k8s/app.yaml", ["kubectl delete"]),
    ("bash", "kubectl delete -k overlays/prod", ["kubectl delete"]),
    ("bash", "kubectl delete ns prod", ["kubectl delete"]),
    ("bash", "kubectl delete crd widgets.example.com", ["kubectl delete"]),
    ("bash", "kubectl --context prod delete pod x", ["kubectl delete"]),
    ("bash", "kubectl delete pod x --dry-run=none", ["kubectl delete"]),
    ("bash", "kubectl delete pod x --namespace=prod --grace-period=0 --force", ["kubectl delete"]),
    ("bash", "KUBECONFIG=~/.kube/prod kubectl delete pod x", ["kubectl delete"]),
    ("bash", "kubectl get pods -o name | xargs kubectl delete", ["kubectl delete"]),
    ("bash", "kubectl delete pvc data-db-0 -n prod --wait=false", ["kubectl delete"]),
    ("bash", "helm uninstall web", ["helm uninstall"]),
    ("bash", "helm uninstall web -n prod", ["helm uninstall"]),
    ("bash", "helm delete web --namespace prod", ["helm delete"]),
    ("bash", "helm un web api", ["helm un"]),
    ("bash", "helm --kube-context prod uninstall web --wait", ["helm uninstall"]),
    ("bash", "helm uninstall web --dry-run=false", ["helm uninstall"]),
    ("bash", "git push --force", ["git push --force"]),
    ("bash", "git push -f origin main", ["git push --force"]),
    ("bash", "git push --force-with-lease", ["git push --force"]),
    ("bash", "git push --force-with-lease=main:abc123 origin main", ["git push --force"]),
    ("bash", "git push origin +main", ["git push --force"]),
    ("bash", "git push origin +feature:main", ["git push --force"]),
    ("bash", "git push -fu origin feature", ["git push --force"]),
    ("bash", "git push origin --delete old-branch", ["git push --delete"]),
    ("bash", "git push origin :old-branch", ["git push --delete"]),
    ("bash", "git -C sub push --force", ["git push --force"]),
    ("bash", "git push --force origin HEAD", ["git push --force"]),
    ("bash", "git push --mirror", ["git push --force"]),
    ("bash", "git add -A && git commit -m wip && git push -f", ["git push --force"]),
    ("bash", 'psql -c "DROP TABLE users"', ["psql DROP TABLE"]),
    ("bash", "psql \"$DATABASE_URL\" -c 'TRUNCATE orders'", ["psql TRUNCATE"]),
    ("bash", 'psql -c "alter table t drop column c"', ["psql DROP COLUMN"]),
    ("bash", 'mysql -u root -e "DROP DATABASE shop"', ["mysql DROP DATABASE"]),
    ("bash", "mysql -e'drop table t'", ["mysql DROP TABLE"]),
    ("bash", 'echo "DROP TABLE t;" | psql', ["psql DROP TABLE"]),
    ("bash", "psql <<EOF\nDROP TABLE t;\nEOF", ["psql DROP TABLE"]),
    ("bash", "dropdb shop", ["dropdb"]),
    ("bash", "mysqladmin -u root drop shop", ["mysqladmin drop"]),
    ("powershell", "terraform destroy -auto-approve", ["terraform destroy"]),
    ("powershell", r"cd C:\infra; terraform destroy", ["terraform destroy"]),
    ("powershell", r"& 'C:\tools\terraform.exe' destroy", ["terraform destroy"]),
    ("powershell", '$env:TF_WORKSPACE = "prod"; terraform destroy', ["terraform destroy"]),
    ("powershell", 'Invoke-Expression "terraform destroy"', ["terraform destroy"]),
    ("powershell", "kubectl delete pod x -n prod | Out-Null", ["kubectl delete"]),
    ("bash", 'pwsh -Command "kubectl delete pod x"', ["kubectl delete"]),
    ("bash", 'powershell -NoProfile -Command terraform destroy', ["terraform destroy"]),
    ("bash", 'cmd /c "helm uninstall web"', ["helm uninstall"]),
    ("bash", "cmd.exe /s /c terraform destroy", ["terraform destroy"]),
    ("bash", "terraform destroy -auto-approve && kubectl delete ns prod && helm uninstall web",
     ["terraform destroy", "kubectl delete", "helm uninstall"]),
    # line continuations
    ("bash", "kubectl delete \\\n  ns prod", ["kubectl delete"]),
    ("bash", "git push \\\n  --force origin main", ["git push --force"]),
    ("bash", "terraform -chdir=infra \\\n  destroy -auto-approve", ["terraform destroy"]),
    ("powershell", "terraform `\n  destroy -auto-approve", ["terraform destroy"]),
    # a substitution in the middle of a command keeps the command whole
    ("bash", "git push origin $(git branch --show-current) --force", ["git push --force"]),
    ("bash", "terraform -chdir=$(pwd)/infra destroy", ["terraform destroy"]),
    ("bash", "kubectl delete $(kubectl get pods -o name)", ["kubectl delete"]),
    ("bash", "kubectl --kubeconfig <(cat cfg) delete ns prod", ["kubectl delete"]),
    ("powershell", "git push origin $(git branch --show-current) --force", ["git push --force"]),
    ("bash", 'kubectl delete "$RES"', ["kubectl delete"]),
    # names from standard input
    ("bash", "helm list -q | xargs helm uninstall", ["helm uninstall"]),
    ("bash", "git branch -r --merged | xargs git push origin --delete", ["git push --delete"]),
    # quoting and escaping inside a name
    ("bash", "terr''aform destroy", ["terraform destroy"]),
    ("bash", "ku\\bectl delete ns prod", ["kubectl delete"]),
    ("bash", 'g"i"t push --force', ["git push --force"]),
    ("bash", "$'terraform' destroy", ["terraform destroy"]),
    ("bash", "kubectl $'\\x64elete' ns prod", ["kubectl delete"]),
    ("bash", "psql -Xc 'DROP TABLE users'", ["psql DROP TABLE"]),
    # programs that run the command
    ("bash", "aws-vault exec prod -- terraform destroy", ["terraform destroy"]),
    ("bash", "doppler run -- kubectl delete ns prod", ["kubectl delete"]),
    ("bash", "op run --env-file=.env -- helm uninstall web", ["helm uninstall"]),
    ("bash", "direnv exec . terraform destroy", ["terraform destroy"]),
    ("bash", "env -S 'terraform destroy -auto-approve'", ["terraform destroy"]),
    ("bash", "watch -n 5 kubectl delete pod x", ["kubectl delete"]),
    ("bash", "caffeinate -i terraform destroy", ["terraform destroy"]),
    ("bash", "flock /tmp/tf.lock terraform destroy", ["terraform destroy"]),
    ("bash", "find k8s -name '*.yaml' -exec kubectl delete -f {} \\;", ["kubectl delete"]),
    ("bash", "cat <<'EOF' | bash\nterraform destroy\nEOF", ["terraform destroy"]),
    ("bash", "bash -c -- 'terraform destroy'", ["terraform destroy"]),
    ("bash", "fish -c 'terraform destroy'", ["terraform destroy"]),
    # Terraform forms that change or replace state
    ("bash", "TF_CLI_ARGS_apply=-destroy terraform apply -auto-approve", ["terraform apply -destroy"]),
    ("bash", "terraform state push -force old.tfstate", ["terraform state push"]),
    ("bash", "terraform workspace delete -force staging", ["terraform workspace delete -force"]),
    # PowerShell script blocks and Start-Process
    ("powershell", "Get-Content pods.txt | ForEach-Object { kubectl delete pod $_ }", ["kubectl delete"]),
    ("powershell", "Invoke-Command -ScriptBlock { terraform destroy }", ["terraform destroy"]),
    ("bash", 'pwsh -Command "& {terraform destroy}"', ["terraform destroy"]),
    ("powershell", "Start-Process terraform -ArgumentList 'destroy','-auto-approve' -Wait", ["terraform destroy"]),
]

NEGATIVE = [
    ("bash", "terraform plan"),
    ("bash", "terraform plan -destroy"),
    ("bash", "terraform plan -destroy -out=destroy.tfplan"),
    ("bash", "terraform apply"),
    ("bash", "terraform apply -destroy=false"),
    ("bash", "terraform apply plan.tfplan"),
    ("bash", "terraform state list"),
    ("bash", "terraform state rm -dry-run aws_instance.web"),
    ("bash", "terraform destroy -help"),
    ("bash", "terraform -version"),
    ("bash", "terraform output -json"),
    ("bash", "echo terraform destroy"),
    ("bash", 'echo "terraform destroy"'),
    ("bash", "echo 'kubectl delete ns prod' > runbook.txt"),
    ("bash", 'grep -rn "terraform destroy" docs/'),
    ("bash", 'git commit -m "document terraform destroy"'),
    ("bash", 'git log --grep="push --force"'),
    ("bash", "printf 'kubectl delete pod x\\n'"),
    ("bash", "cat <<'EOF' > notes.md\nterraform destroy\nkubectl delete ns prod\nEOF"),
    ("bash", "cat > notes.md <<EOF\ngit push --force\nEOF\ngit status"),
    ("bash", "git commit -m \"$(cat <<'EOF'\nExplain terraform destroy and \"git push --force\"\n\nCo-Authored-By: x\nEOF\n)\""),
    ("bash", "# terraform destroy"),
    ("bash", "ls -la # ; terraform destroy"),
    ("bash", "kubectl get pods"),
    ("bash", "kubectl delete pod x --dry-run=client"),
    ("bash", "kubectl delete pod x --dry-run=server -o yaml"),
    ("bash", "kubectl delete pod x --dry-run"),
    ("bash", "kubectl delete --help"),
    ("bash", "kubectl delete pods"),
    ("bash", "kubectl delete"),
    ("bash", "kubectl describe deployment web"),
    ("bash", "kubectl logs deploy/web | grep delete"),
    ("bash", "helm list -A"),
    ("bash", "helm uninstall web --dry-run"),
    ("bash", "helm uninstall"),
    ("bash", "helm upgrade --install web chart/"),
    ("bash", "git push"),
    ("bash", "git push origin main"),
    ("bash", "git push -u origin feature"),
    ("bash", "git push --dry-run --force"),
    ("bash", "git push -n -f origin main"),
    ("bash", "git push --follow-tags"),
    ("bash", "git push --force-if-includes origin main"),
    ("bash", "git push --all"),
    ("bash", "git fetch --force"),
    ("bash", "git reset --hard HEAD~3"),
    ("bash", "git branch -D old"),
    ("bash", "psql -c \"SELECT 'DROP TABLE x'\""),
    ("bash", "psql -c 'SELECT 1 -- DROP TABLE x'"),
    ("bash", "psql -c 'SELECT $$drop table x$$'"),
    ("bash", "psql -f migrate.sql"),
    ("bash", 'mysql -e "SELECT * FROM dropped_tables"'),
    ("bash", "terraform destroy '"),
    ("bash", "vim main.tf"),
    ("bash", ""),
    ("powershell", 'Write-Output "terraform destroy"'),
    ("powershell", "# terraform destroy"),
    ("powershell", 'Get-Content x.txt | Select-String "helm uninstall"'),
    ("powershell", "$labels = @{ Name = 'kubectl delete' }"),
    ("bash", "terraform workspace delete staging"),  # without -force Terraform refuses a workspace with resources
    ("bash", "TF_CLI_ARGS_plan=-destroy terraform plan"),
    ("bash", "op item get db --fields username"),
    ("bash", "aws-vault exec prod -- aws s3 ls"),
    ("bash", "find . -name '*.log' -delete"),
    ("bash", "echo $'terraform destroy'"),
    ("bash", "git commit -m 'wip' \\\n  -m 'about terraform destroy'"),
    ("bash", "cat <<'EOF' | grep destroy\nterraform destroy\nEOF"),
    ("bash", "mysql -pe2eDROP -e 'SELECT 1'"),
]


class Detector(Isolated):
    def test_positive_table(self):
        for shell, cmd, labels in POSITIVE:
            with self.subTest(cmd=cmd, shell=shell):
                self.assertEqual([o["label"] for o in self.ops(cmd, shell)], labels)

    def test_negative_table(self):
        for shell, cmd in NEGATIVE:
            with self.subTest(cmd=cmd, shell=shell):
                self.assertEqual([o["label"] for o in self.ops(cmd, shell)], [])

    def test_tables_are_large(self):
        self.assertGreaterEqual(len(POSITIVE), 90)
        self.assertGreaterEqual(len(NEGATIVE), 55)

    def test_not_text(self):
        import destroy_guard as dg
        for value in (None, 5, ["terraform", "destroy"]):
            self.assertEqual(dg.analyse(value), [])

    def test_deep_nesting_stops(self):
        cmd = "terraform destroy"
        for _ in range(8):
            cmd = "bash -c " + __import__("shlex").quote(cmd)
        self.assertEqual(self.ops(cmd), [])  # past MAX_DEPTH the line is not followed

    def test_huge_line_is_fast(self):
        import time
        cmd = " && ".join(["echo hello world"] * 4000) + " && terraform destroy"
        t = time.monotonic()
        self.assertEqual([o["label"] for o in self.ops(cmd)], ["terraform destroy"])
        self.assertLess(time.monotonic() - t, 5)

    def test_unicode_names(self):
        ops = self.ops("kubectl delete configmap café-配置 -n prod")
        self.assertEqual(ops[0]["targets"][0]["name"], "café-配置")

    def test_what_a_substitution_names_stays_unresolved(self):
        for cmd in ("git push origin $(git branch --show-current) --force", "terraform -chdir=$(pwd)/infra destroy",
                    "kubectl delete $(kubectl get pods -o name)", "helm list -q | xargs helm uninstall",
                    "git branch -r --merged | xargs git push origin --delete", 'kubectl delete "$RES"'):
            with self.subTest(cmd=cmd):
                self.git_repo()
                [op] = self.ops(cmd)
                self.assertTrue(op["problem"])
                self.assertEqual(op["targets"], [])

    def test_nested_substitutions_cost_linear_time(self):
        # three times the nesting may cost about three times the time, not nine; absolute times vary by machine
        import time

        def cost(n, closed):
            cmd = "terraform destroy; echo " + "$(" * n + (")" * n if closed else "")
            t = time.monotonic()
            self.assertEqual([o["label"] for o in self.ops(cmd)], ["terraform destroy"])
            return time.monotonic() - t

        for closed in (True, False):
            with self.subTest(closed=closed):
                small = min(cost(6000, closed) for _ in range(2))
                self.assertLess(cost(18000, closed), 5 * small + 0.1)

    def test_sql_scan_costs_linear_time(self):
        import time
        import destroy_guard as dg
        for text in (" ".join(f"$t{i}$" for i in range(20000)) + " DROP TABLE t", "/*" * 50000 + " DROP TABLE t",
                     "'" + "''" * 50000 + " DROP TABLE t"):
            t = time.monotonic()
            dg.sql_destructive(text)
            self.assertLess(time.monotonic() - t, 1)
        self.assertEqual(dg.sql_destructive("SELECT $a$ DROP TABLE x $a$; DROP TABLE y"), {"DROP TABLE"})
        self.assertEqual(dg.sql_destructive("SELECT 'it''s DROP TABLE x' /* DROP TABLE z */"), set())


if __name__ == "__main__":
    unittest.main()
