"""The environment scan: which names count, what is printed (name and length), what never is (the value)."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, cr, synthetic  # noqa: E402

rand = synthetic.rand


class EnvScan(Isolated):
    def scan(self, **env):
        return cr.scan_env(self.ctx(env={**os.environ, **env}))

    def test_credential_names_and_shapes(self):
        values = {"GITHUB_TOKEN": "ghp_" + rand(36), "GH_TOKEN": rand(40, "0123456789abcdef"),
                  "ANTHROPIC_API_KEY": "sk-ant-api03-" + rand(60), "OPENAI_API_KEY": "sk-proj-" + rand(40),
                  "MY_SERVICE_PASSWORD": rand(12), "DB_PASS": rand(9), "PGPASSWORD": rand(9),
                  "TF_TOKEN_app_terraform_io": rand(30), "SLACK_WEBHOOK_URL": "https://hooks.example/" + rand(30),
                  "UNRELATED_NAME": "ghp_" + rand(36), "DATABASE_URL": f"postgres://u:{rand(10)}@db/x",
                  "HTTPS_PROXY": f"http://me:{rand(10)}@proxy:3128", "AWS_ACCESS_KEY_ID": "AKIA" + rand(16, synthetic.UPPER),
                  "AWS_SECRET_ACCESS_KEY": rand(40), "AWS_REGION": "eu-west-1"}
        sec = self.scan(**values)
        f = {x["item"]: x for x in sec.findings}
        for name in values:
            self.assertIn(name, f, name)
        self.assertEqual(f["GITHUB_TOKEN"]["detail"], "40 chars, GitHub personal access token (classic)")
        self.assertEqual(f["GITHUB_TOKEN"]["length"], 40)
        self.assertEqual(f["UNRELATED_NAME"]["looks_like"], "github-classic-pat")
        self.assertEqual(f["DATABASE_URL"]["looks_like"], "url-password")
        self.assertEqual(f["HTTPS_PROXY"]["severity"], "high")
        self.assertIn("long-term", f["AWS_ACCESS_KEY_ID"]["detail"])
        self.assertEqual((f["AWS_REGION"]["kind"], f["AWS_REGION"]["severity"]), ("setting", "info"))
        self.assertIn("account can access", f["GITHUB_TOKEN"]["reach"])
        out = json.dumps(sec.as_dict())
        for v in values.values():
            if len(v) > 8:
                self.assertNotIn(v, out)

    def test_names_that_are_not_credentials(self):
        sec = self.scan(PWD="/x", OLDPWD="/y", TOKENIZERS_PARALLELISM="false", SSH_AUTH_SOCK="/tmp/s",
                        KUBECONFIG="/k", HISTCONTROL="ignoredups", LESSKEY="/l", BYPASS_CACHE="1")
        self.assertEqual(sec.findings, [])
        self.assertFalse(sec.found)

    def test_empty_placeholder_and_path_values(self):
        key = self.write("keys/sa.json", "{}")
        sec = self.scan(EMPTY_TOKEN="", TEMPLATE_SECRET="<your-secret>", REF_PASSWORD="${OTHER}",
                        GOOGLE_APPLICATION_CREDENTIALS=str(key), AWS_WEB_IDENTITY_TOKEN_FILE="/nonexistent/x")
        f = {x["item"]: x for x in sec.findings}
        self.assertEqual(f["EMPTY_TOKEN"]["detail"], "empty")
        self.assertIn("placeholder", f["TEMPLATE_SECRET"]["detail"])
        self.assertIn("placeholder", f["REF_PASSWORD"]["detail"])
        self.assertEqual(f["GOOGLE_APPLICATION_CREDENTIALS"]["severity"], "medium")
        self.assertEqual(f["AWS_WEB_IDENTITY_TOKEN_FILE"]["severity"], "info")
        self.assertNotIn(str(key), json.dumps(sec.as_dict()))  # a path in the environment is a value too

    def test_odd_names_are_cleaned(self):
        sec = self.scan(**{"EVIL\x1b[31m_TOKEN": rand(20)})
        self.assertNotIn("\x1b", json.dumps(sec.as_dict()))

    def test_claude_code_note(self):
        sec = self.scan(CLAUDECODE="1", X_TOKEN=rand(20))
        self.assertIn("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 strips", sec.notes[0])
        sec = self.scan(CLAUDECODE="1", CLAUDE_CODE_SUBPROCESS_ENV_SCRUB="1")
        self.assertIn("after CLAUDE_CODE_SUBPROCESS_ENV_SCRUB removed", sec.notes[0])

    def test_tokens_are_kept_only_for_probe(self):
        tok = "ghp_" + rand(36)
        ctx = self.ctx(env={**os.environ, "GITHUB_TOKEN": tok})
        cr.scan_env(ctx)
        self.assertEqual(ctx.github_tokens, {})
        ctx = self.ctx(env={**os.environ, "GITHUB_TOKEN": tok, "GH_ENTERPRISE_TOKEN": "ghp_" + rand(36),
                            "GH_TOKEN": "not a token\r\nX-Injected: 1"}, probe=True)
        cr.scan_env(ctx)
        self.assertEqual(list(ctx.github_tokens), [tok])


class Shapes(unittest.TestCase):
    def test_every_shape_is_recognised_and_labelled(self):
        samples = {
            "private-key": synthetic.openssh_key(), "anthropic-api-key": "sk-ant-api03-" + rand(40),
            "openai-api-key": "sk-" + rand(48), "github-classic-pat": "ghp_" + rand(36),
            "github-fine-grained-pat": "github_pat_" + rand(22) + "_" + rand(59),
            "aws-access-key-id": "ASIA" + rand(16, synthetic.UPPER), "replicate-api-token": "r8_" + rand(37),
            "github-oauth-token": "gho_" + rand(36),
            "github-app-token": "ghs_12345_" + "eyJ" + rand(20) + "." + rand(30) + "." + rand(30),
            "aws-secret-access-key": "aws_secret_access_key = " + rand(40),
            "slack-token": "xoxb-" + rand(30), "gitlab-token": "glpat-" + rand(20), "google-api-key": "AIza" + rand(35),
            "stripe-secret-key": "rk_live_" + rand(30), "npm-token": "npm_" + rand(36),
            "pypi-token": "pypi-" + "AgEIcHlwaS5vcmc" + rand(60), "huggingface-token": "hf_" + rand(34),
            "jwt": "eyJ" + rand(20) + ".eyJ" + rand(20) + "." + rand(20),
            "url-password": "https://me:" + rand(10) + "@host.example/", "bearer-token": "Bearer " + rand(30),
        }
        self.assertEqual(set(samples), {n for n, _ in cr.SECRET_PATTERNS})
        self.assertEqual(set(samples), set(cr.SECRET_LABELS))
        for name, text in samples.items():
            self.assertEqual(cr.looks_like(text), name, name)
            self.assertTrue(cr.triggered(json.dumps({"x": "a " + text}).encode()), name)  # the first pass lets it through
            self.assertTrue(cr.triggered(("a " + text.upper() if name == "bearer-token" else text).encode()), name)
            new, counts = cr.redact_text("before " + text + " after")
            self.assertEqual(counts, {name: 1}, name)
            self.assertIn(f"[REDACTED:{name}]", new)

    def test_first_pass_skips_lines_without_candidates(self):
        for text in ("plain words", "the task-runner and disk-cache", "email me@example.com", "https://example.com/x@y"):
            self.assertFalse(cr.triggered(text.encode()), text)

    def test_word_edges_and_references(self):
        for text in ("task-" + rand(40), "mask_live_" + rand(30), "https://u:${PASSWORD}@h/", "https://u:***@h/",
                     "Bearer <token>", "Bearer $TOKEN", "ASIAN food", "https://git@github.com/o/r"):
            self.assertIsNone(cr.looks_like(text), text)

    def test_redaction_is_idempotent(self):
        text = ("Bearer " + "eyJ" + rand(20) + ".eyJ" + rand(20) + "." + rand(20) + " postgres://u:" + rand(9)
                + "@db/x https://x:ghp_" + rand(36) + "@github.com aws_secret_access_key=" + rand(40))
        once, counts = cr.redact_text(text)
        self.assertEqual(sum(counts.values()), 4)
        self.assertEqual(cr.redact_text(once), (once, {}))


if __name__ == "__main__":
    unittest.main()
