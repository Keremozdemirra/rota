"""Every credential file parser: valid, empty, malformed, and in encodings real machines produce."""
import base64
import codecs
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, cr, synthetic, text_of  # noqa: E402

rand = synthetic.rand


class Yaml(unittest.TestCase):
    def test_kubectl_layout(self):
        text = ("apiVersion: v1\nclusters:\n- cluster:\n    server: https://h:6443\n  name: a\n"
                "contexts: []\ncurrent-context: a\npreferences: {}\nusers:\n- name: u\n  user:\n"
                "    exec:\n      args:\n      - x\n      - --flag\n      command: aws\n      env: null\n")
        d = cr.yaml_load(text)
        self.assertEqual(d["clusters"], [{"cluster": {"server": "https://h:6443"}, "name": "a"}])
        self.assertEqual(d["contexts"], [])
        self.assertEqual(d["preferences"], {})
        self.assertEqual(d["users"][0]["user"]["exec"], {"args": ["x", "--flag"], "command": "aws", "env": None})

    def test_quotes_comments_flow_and_block_scalars(self):
        text = ("# top comment\n'quoted key': \"a # not a comment\"  # a comment\nplain: it's here # c\n"
                "flow: [a, 'b c', {k: v}]\nmap: {x: 1, y: [2, 3]}\nblock: |\n  line one\n  key: not a key\n"
                "folded: first\n  second\nempty:\nnulls: ~\n")
        d = cr.yaml_load(text)
        self.assertEqual(d["quoted key"], "a # not a comment")
        self.assertEqual(d["plain"], "it's here")
        self.assertEqual(d["flow"], ["a", "b c", {"k": "v"}])
        self.assertEqual(d["map"], {"x": "1", "y": ["2", "3"]})
        self.assertEqual(d["block"], "line one\nkey: not a key")
        self.assertEqual(d["folded"], "first second")
        self.assertIsNone(d["empty"])
        self.assertIsNone(d["nulls"])

    def test_crlf_and_document_markers(self):
        self.assertEqual(cr.yaml_load("---\r\na: 1\r\nb:\r\n  c: 2\r\n...\r\n"), {"a": "1", "b": {"c": "2"}})
        self.assertEqual(cr.yaml_load("a: 1\n---\nb: 2\n"), {"a": "1"})  # only the first document

    def test_empty_is_none(self):
        self.assertIsNone(cr.yaml_load(""))
        self.assertIsNone(cr.yaml_load("# only a comment\n\n"))

    def test_malformed_raises_yaml_error(self):
        for bad in ("a:\n\tb: 1\n", "a: 'open\n", "a: [1, 2\n", "a: 1\n  b: 2\n c: 3\n", "just words\n",
                    "- a\nb: 1\n"):
            with self.assertRaises(cr.YamlError, msg=bad):
                cr.yaml_load(bad)


class Kube(Isolated):
    CONFIG = """apiVersion: v1
clusters:
- cluster:
    server: https://user:pw@10.0.0.1:6443/path?token=abc
  name: prod
contexts:
- context:
    cluster: prod
    user: admin
  name: prod
- context:
    cluster: prod
    user: viewer
  name: view
current-context: prod
users:
- name: admin
  user:
    token: {token}
- name: viewer
  user:
    auth-provider:
      name: oidc
      config:
        id-token: {token}
- name: orphan
  user:
    exec:
      command: /usr/local/bin/kubelogin
"""

    def scan(self, **env):
        return cr.scan_kube(self.ctx(env={**os.environ, **env}))

    def test_contexts_users_and_no_values(self):
        token = rand(40)
        self.write(".kube/config", self.CONFIG.format(token=token))
        sec = self.scan()
        f = {x["item"]: x for x in sec.findings}
        self.assertEqual(f["context prod (current)"]["severity"], "high")
        self.assertIn("stored token", f["context prod (current)"]["detail"])
        self.assertIn("10.0.0.1:6443", f["context prod (current)"]["detail"])
        self.assertIn("auth-provider oidc with stored id-token", f["context view"]["detail"])
        self.assertIn("exec plugin kubelogin", f["user orphan"]["detail"])
        out = text_of(sec)
        for leak in (token, "pw@", "token=abc", "user:"):
            self.assertNotIn(leak, out)

    def test_json_kubeconfig(self):
        self.write(".kube/config", json.dumps({"contexts": [{"name": "c", "context": {"user": "u", "cluster": "k"}}],
                                               "users": [{"name": "u", "user": {"client-key": "/k.pem"}}]}))
        f = {x["item"]: x for x in self.scan().findings}
        self.assertIn("client certificate with key file", f["context c"]["detail"])

    def test_kubeconfig_env_lists_files_with_the_platform_separator(self):
        a = self.write("a.yaml", "users:\n- name: a\n  user:\n    token: x\n")
        b = self.write("b.yaml", "users:\n- name: b\n  user:\n    password: y\n")
        sec = self.scan(KUBECONFIG=f"{a}:{b}")
        self.assertEqual({x["item"] for x in sec.findings}, {"user a", "user b"})
        sec = cr.scan_kube(self.ctx(system="Windows", env={**os.environ, "KUBECONFIG": f"{a};{b}"}))
        self.assertEqual({x["item"] for x in sec.findings}, {"user a", "user b"})

    def test_empty_malformed_and_odd_files(self):
        self.write(".kube/config", "")
        sec = self.scan()
        self.assertFalse(sec.errors)
        self.assertTrue(sec.notes)
        self.write(".kube/config", "users:\n\t- name: x\n")
        self.assertIn("could not parse", self.scan().errors[0])
        self.write(".kube/config", "- just\n- a list\n")
        self.assertIn("not a kubeconfig", self.scan().errors[0])
        self.write(".kube/config", b"\x00\xff\xfe binary \x00")
        self.assertTrue(self.scan().errors)
        self.write(".kube/config", "users: 5\ncontexts: {a: b}\n")
        self.assertEqual(self.scan().findings, [])

    def test_bom_and_utf16(self):
        text = "users:\n- name: u\n  user:\n    token: t\n"
        self.write(".kube/config", codecs.BOM_UTF8 + text.encode())
        self.assertEqual(self.scan().findings[0]["severity"], "high")
        self.write(".kube/config", text.encode("utf-16"))
        self.assertEqual(self.scan().findings[0]["severity"], "high")


class Aws(Isolated):
    def scan(self, **env):
        return {f["item"]: f for f in cr.scan_aws(self.ctx(env={**os.environ, **env})).findings}

    def test_profiles_and_their_kinds(self):
        secret = rand(40)
        self.write(".aws/credentials", f"[default]\naws_access_key_id = AKIA{rand(16, synthetic.UPPER)}\n"
                                       f"aws_secret_access_key = {secret}\n[half]\naws_access_key_id = x\n")
        self.write(".aws/config", "[default]\nregion = x\n[profile sso]\nsso_start_url = https://a/start\n"
                                  "[profile r]\nrole_arn = arn:aws:iam::123456789012:role/Admin\n"
                                  "credential_source = Environment\n[profile p]\n"
                                  "credential_process = \"C:\\Program Files\\vault\\vault.exe\" exec x\n"
                                  "[sso-session s]\nsso_start_url = https://b\n[profile plain]\nregion = y\n")
        f = self.scan(AWS_PROFILE="r")
        self.assertEqual(f["profile default"]["severity"], "high")
        self.assertEqual(f["profile default"]["where"], "~/.aws/credentials")
        self.assertEqual(f["profile half"]["detail"], "access key ID without a secret key")
        self.assertIn("IAM Identity Center", f["profile sso"]["detail"])
        self.assertEqual(f["profile r (active)"]["detail"], "assumes role Admin in account 123456789012, via Environment")
        self.assertEqual(f["profile p"]["detail"], "credential_process runs vault.exe")
        self.assertEqual(f["profile plain"]["detail"], "settings only, no credentials")
        self.assertNotIn("profile s", f)
        self.assertNotIn(secret, json.dumps(f))

    def test_default_is_active_without_aws_profile(self):
        self.write(".aws/config", "[default]\nregion = x\n")
        self.assertIn("profile default (active)", self.scan())

    def test_temporary_keys_and_env_override(self):
        p = self.write("elsewhere/creds", "[t]\naws_access_key_id = ASIAxxx\naws_secret_access_key = y\n"
                                          "aws_session_token = z\n")
        f = self.scan(AWS_SHARED_CREDENTIALS_FILE=str(p))
        self.assertEqual(f["profile t"]["severity"], "medium")

    def test_malformed_empty_and_encodings(self):
        self.write(".aws/credentials", "aws_access_key_id = x\n")  # no section header
        sec = cr.scan_aws(self.ctx())
        self.assertIn("could not parse", sec.errors[0])
        self.write(".aws/credentials", "")
        self.assertEqual(cr.scan_aws(self.ctx()).errors, [])
        body = "[default]\naws_access_key_id = AKIAX\naws_secret_access_key = s\n"
        for data in (codecs.BOM_UTF8 + body.encode(), body.encode("utf-16"), body.replace("\n", "\r\n").encode(),
                     (body + "# caf\xe9\n").encode("latin-1")):
            self.write(".aws/credentials", data)
            self.assertEqual(self.scan()["profile default (active)"]["severity"], "high")

    def test_sso_cache_counts_valid_sessions_without_reading_tokens(self):
        token = rand(50)
        self.write(".aws/sso/cache/a.json", json.dumps({"accessToken": token, "expiresAt": "2099-01-01T00:00:00Z"}))
        self.write(".aws/sso/cache/b.json", json.dumps({"accessToken": token, "expiresAt": "2001-01-01T00:00:00UTC"}))
        self.write(".aws/cli/cache/c.json", json.dumps({"Credentials": {"Expiration": "2099-05-01T10:00:00+00:00"}}))
        self.write(".aws/sso/cache/d.json", "not json")
        f = self.scan()["SSO and role cache"]
        self.assertEqual(f["severity"], "medium")
        self.assertIn("4 cached session files, 2 not yet expired", f["detail"])
        self.assertNotIn(token, json.dumps(f))


class Gcloud(Isolated):
    def test_active_account_adc_and_logins(self):
        secret = rand(30)
        self.write(".config/gcloud/active_config", "work\n")
        self.write(".config/gcloud/configurations/config_work", "[core]\naccount = a@example.com\nproject = p1\n")
        self.write(".config/gcloud/credentials.db", b"SQLite")
        self.write(".config/gcloud/application_default_credentials.json",
                   json.dumps({"type": "service_account", "private_key": secret}))
        sec = cr.scan_gcloud(self.ctx())
        f = {x["item"]: x for x in sec.findings}
        self.assertIn("configuration work: account a@example.com, project p1", f["gcloud login"]["detail"])
        self.assertEqual(f["application-default credentials"]["severity"], "high")
        self.assertNotIn(secret, text_of(sec))

    def test_windows_uses_appdata(self):
        self.write("AppData/Roaming/gcloud/application_default_credentials.json", json.dumps({"type": "authorized_user"}))
        sec = cr.scan_gcloud(self.ctx(system="Windows"))
        self.assertEqual(sec.paths, ["~\\AppData\\Roaming\\gcloud"])
        self.assertIn("application-default credentials", {x["item"] for x in sec.findings})
        self.assertEqual(cr.scan_gcloud(self.ctx(system="Linux")).findings, [])

    def test_malformed_and_env_pointer(self):
        self.write(".config/gcloud/application_default_credentials.json", "{not json")
        self.write(".config/gcloud/configurations/config_default", "no header\n")
        sec = cr.scan_gcloud(self.ctx())
        self.assertIn("type unparseable", {x["item"]: x for x in sec.findings}["application-default credentials"]["detail"])
        self.assertTrue(sec.errors)
        key = self.write("keys/sa.json", json.dumps([1, 2]))
        sec = cr.scan_gcloud(self.ctx(env={**os.environ, "GOOGLE_APPLICATION_CREDENTIALS": str(key)}))
        self.assertIn("type unparseable", {x["item"]: x for x in sec.findings}["GOOGLE_APPLICATION_CREDENTIALS"]["detail"])
        sec = cr.scan_gcloud(self.ctx(env={**os.environ, "GOOGLE_APPLICATION_CREDENTIALS": str(self.tmp / "gone")}))
        self.assertIn("missing", sec.findings[-1]["detail"])


class Azure(Isolated):
    def test_profile_with_bom_and_cache_files(self):
        self.write(".azure/azureProfile.json", codecs.BOM_UTF8 + json.dumps({"subscriptions": [
            {"user": {"name": "a@example.com", "type": "user"}}, {"user": {"name": "b", "type": "servicePrincipal"}}]}
        ).encode())
        self.write(".azure/msal_token_cache.json", "{}")
        self.write(".azure/service_principal_entries.json", "[]")
        f = {x["item"]: x for x in cr.scan_azure(self.ctx()).findings}
        self.assertEqual(f["profile"]["detail"], "2 subscriptions, 2 accounts (servicePrincipal, user)")
        self.assertNotIn("a@example.com", json.dumps(f))
        self.assertEqual(f["service_principal_entries.json"]["severity"], "high")
        self.assertEqual(f["msal_token_cache.json"]["severity"], "medium")

    def test_malformed_profile(self):
        self.write(".azure/azureProfile.json", "[]")
        self.assertTrue(cr.scan_azure(self.ctx()).errors)
        self.write(".azure/azureProfile.json", json.dumps({"subscriptions": 7}))
        f = {x["item"]: x for x in cr.scan_azure(self.ctx()).findings}
        self.assertEqual(f["profile"]["severity"], "info")

    def test_config_dir_override(self):
        d = self.tmp / "az"
        self.write("az/accessTokens.json", "[]", base=self.tmp)
        sec = cr.scan_azure(self.ctx(env={**os.environ, "AZURE_CONFIG_DIR": str(d)}))
        self.assertEqual(sec.findings[0]["item"], "accessTokens.json")


class Docker(Isolated):
    def test_registries_auth_and_helpers(self):
        pw = rand(20)
        self.write(".docker/config.json", json.dumps({
            "auths": {"https://index.docker.io/v1/": {"auth": base64.b64encode(f"u:{pw}".encode()).decode()},
                      "ghcr.io": {}, "https://user:pw@evil.example/x": {"identitytoken": "t"}},
            "credHelpers": {"gcr.io": "gcloud"}, "credsStore": "osxkeychain"}))
        sec = cr.scan_docker(self.ctx())
        f = {x["item"]: x for x in sec.findings}
        self.assertEqual(f["index.docker.io"]["severity"], "high")
        self.assertIn("osxkeychain (macOS Keychain)", f["ghcr.io"]["detail"])
        self.assertIn("docker-credential-gcloud", f["gcr.io"]["detail"])
        self.assertIn("evil.example", f)
        self.assertIn("osxkeychain", sec.store_note)
        out = text_of(sec)
        self.assertNotIn(pw, out)
        self.assertNotIn("user:pw", out)

    def test_no_store_note_and_malformed(self):
        self.write(".docker/config.json", json.dumps({"auths": {"r.example": {}}}))
        sec = cr.scan_docker(self.ctx())
        self.assertEqual(sec.findings[0]["severity"], "info")
        self.assertIn("base64", sec.store_note)
        for bad in ("{", "[]", "null", ""):
            self.write(".docker/config.json", bad)
            self.assertTrue(cr.scan_docker(self.ctx()).errors, bad)

    def test_docker_config_env(self):
        self.write("d/config.json", json.dumps({"auths": {"r.example": {"auth": "eA=="}}}), base=self.tmp)
        sec = cr.scan_docker(self.ctx(env={**os.environ, "DOCKER_CONFIG": str(self.tmp / "d")}))
        self.assertEqual(sec.findings[0]["severity"], "high")


class Npm(Isolated):
    def test_tokens_env_references_and_masked_paths(self):
        token = "npm_" + rand(36)
        path_key = rand(30)
        self.write(".npmrc", f"; comment\n//registry.npmjs.org/:_authToken={token}\n"
                             "//npm.corp.example/:_authToken=${CORP_TOKEN}\n"
                             f"//npm.fury.example/{path_key}/:_auth=\"eA==\"\n//empty.example/:_authToken=\n"
                             "@corp:registry=https://npm.corp.example/\nalways-auth=true\n")
        sec = cr.scan_npm(self.ctx())
        f = {x["item"]: x for x in sec.findings}
        self.assertEqual(f["registry.npmjs.org"]["severity"], "high")
        self.assertEqual(f["npm.corp.example"]["detail"], "token taken from $CORP_TOKEN")
        self.assertEqual(f["npm.fury.example/***"]["severity"], "high")
        self.assertEqual(f["empty.example"]["detail"], "_authToken empty")
        self.assertNotIn(token, text_of(sec))
        self.assertNotIn(path_key, text_of(sec))

    def test_empty_file_and_userconfig_env(self):
        self.write(".npmrc", "")
        self.assertEqual(cr.scan_npm(self.ctx()).findings[0]["detail"], "no registry credentials")
        p = self.write("other/npmrc", "_authToken=abc\n")
        sec = cr.scan_npm(self.ctx(env={**os.environ, "npm_config_userconfig": str(p)}))
        self.assertEqual(sec.findings[0]["item"], "default registry")


class Pypirc(Isolated):
    def test_repositories(self):
        pw = rand(20)
        self.write(".pypirc", f"[distutils]\nindex-servers = pypi corp\n[pypi]\nusername = __token__\npassword = {pw}\n"
                              "[corp]\nrepository = https://u:p@pypi.corp.example/simple\nusername = me\n")
        sec = cr.scan_pypirc(self.ctx())
        f = {x["item"]: x for x in sec.findings}
        self.assertEqual(f["pypi"]["detail"], "upload.pypi.org: API token stored in the file")
        self.assertEqual(f["corp"]["detail"], "pypi.corp.example: no password stored")
        self.assertNotIn(pw, text_of(sec))

    def test_malformed(self):
        self.write(".pypirc", "password = x\n")
        self.assertTrue(cr.scan_pypirc(self.ctx()).errors)


class Netrc(Isolated):
    def test_hosts_macdef_and_default(self):
        pw = rand(16)
        self.write(".netrc", f"# comment\nmachine a.example login me password {pw}\nmachine b.example login me\n"
                             "macdef init\ncd /\nmachine fake.example password x\n\ndefault login anon password y\n")
        sec = cr.scan_netrc(self.ctx())
        f = {x["item"]: x for x in sec.findings}
        self.assertEqual(f["a.example"]["severity"], "high")
        self.assertEqual(f["b.example"]["severity"], "info")
        self.assertNotIn("fake.example", f)
        self.assertIn("default (any other host)", f)
        self.assertNotIn(pw, text_of(sec))

    def test_windows_name_and_netrc_env(self):
        self.write("_netrc", "machine w.example password x\n")
        p = self.write("custom/netrc", "machine c.example password x\n")
        sec = cr.scan_netrc(self.ctx(env={**os.environ, "NETRC": str(p)}))
        self.assertEqual({x["item"] for x in sec.findings}, {"w.example", "c.example"})

    def test_empty(self):
        self.write(".netrc", "\n")
        sec = cr.scan_netrc(self.ctx())
        self.assertEqual(sec.findings, [])
        self.assertTrue(sec.notes)


class Git(Isolated):
    def test_git_credentials_and_helpers(self):
        tok = rand(30)
        self.write(".git-credentials", f"https://me:{tok}@github.com\nhttps://gitlab.example\nnot a url [\n"
                                       f"https://me:{tok}@github.com/org/repo\n")
        self.write(".config/git/credentials", "https://x:y@bitbucket.org\n")
        self.write(".gitconfig", "[credential]\n\thelper = osxkeychain\n[credential \"https://dev.azure.com\"]\n"
                                 "  helper = /usr/lib/git-core/git-credential-manager --opt\n[alias]\n  helper = no\n"
                                 "[credential]\n  helper =\n  helper = !f() { echo x; }; f\n")
        sec = cr.scan_git(self.ctx())
        f = {x["item"]: x for x in sec.findings}
        self.assertEqual(f["github.com"]["detail"], "2 stored credentials")
        self.assertEqual(f["gitlab.example"]["severity"], "info")
        self.assertEqual(f["bitbucket.org"]["severity"], "high")
        self.assertIn("macOS Keychain", f["credential.helper osxkeychain"]["detail"])
        self.assertIn("Git Credential Manager", f["credential.helper manager"]["detail"])
        self.assertIn("credential.helper a shell command", f)
        self.assertNotIn("credential.helper no", f)
        self.assertNotIn(tok, text_of(sec))

    def test_helpers_function(self):
        self.assertEqual(cr.git_helpers("[credential]\nhelper = store --file x\n"), ["store"])
        self.assertEqual(cr.git_helpers("[core]\nhelper = x\n"), [])


class Gh(Isolated):
    HOSTS = "github.com:\n    users:\n        me:\n            oauth_token: {t}\n    user: me\nghe.example:\n    user: you\n"

    def test_plaintext_and_keyring_hosts(self):
        t = "gho_" + rand(36)
        self.write(".config/gh/hosts.yml", self.HOSTS.format(t=t))
        sec = cr.scan_gh(self.ctx())
        f = {x["item"]: x for x in sec.findings}
        self.assertEqual((f["github.com"]["severity"], f["ghe.example"]["severity"]), ("high", "medium"))
        self.assertIn("user me", f["github.com"]["detail"])
        self.assertNotIn(t, text_of(sec))

    def test_config_dir_order(self):
        self.write("AppData/Roaming/GitHub CLI/hosts.yml", "github.com:\n    user: w\n")
        env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        sec = cr.scan_gh(self.ctx(system="Windows", env=env))
        self.assertEqual(sec.paths, ["~\\AppData\\Roaming\\GitHub CLI\\hosts.yml"])
        self.assertEqual(sec.findings[0]["item"], "github.com")
        sec = cr.scan_gh(self.ctx(env={**os.environ, "GH_CONFIG_DIR": str(self.tmp / "g")}))
        self.assertEqual(sec.findings, [])

    def test_malformed_and_empty(self):
        self.write(".config/gh/hosts.yml", "github.com:\n  user: [unclosed\n")
        self.assertTrue(cr.scan_gh(self.ctx()).errors)
        self.write(".config/gh/hosts.yml", "- a\n")
        self.assertTrue(cr.scan_gh(self.ctx()).errors)
        self.write(".config/gh/hosts.yml", "")
        self.assertEqual(cr.scan_gh(self.ctx()).findings, [])


class Ssh(Isolated):
    def keys(self):
        return {f["item"].rsplit("/", 1)[-1]: f for f in cr.scan_ssh(self.ctx()).findings}

    def test_formats_and_passphrases(self):
        self.write(".ssh/plain", synthetic.openssh_key())
        self.write(".ssh/locked", synthetic.openssh_key("aes256-ctr", "ssh-rsa"))
        self.write(".ssh/hw", synthetic.openssh_key(key_type="sk-ssh-ed25519@openssh.com"))
        self.write(".ssh/old_open.pem", synthetic.pem_rsa(False))
        self.write(".ssh/old_locked.pem", synthetic.pem_rsa(True))
        self.write(".ssh/p8", synthetic.pkcs8_ed25519())
        self.write(".ssh/p8enc", synthetic.pem("ENCRYPTED PRIVATE KEY", "AAAA"))
        self.write(".ssh/putty.ppk", "PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: none\nComment: x\n")
        self.write(".ssh/putty2.ppk", "PuTTY-User-Key-File-2: ssh-rsa\nEncryption: aes256-cbc\n")
        self.write(".ssh/id_x.pub", synthetic.openssh_key())
        self.write(".ssh/notes.txt", "hello")
        self.write(".ssh/authorized_keys", synthetic.openssh_key())
        k = self.keys()
        self.assertEqual(k["plain"]["detail"], "OpenSSH ssh-ed25519, no passphrase")
        self.assertEqual(k["plain"]["severity"], "high")
        self.assertEqual(k["locked"]["detail"], "OpenSSH ssh-rsa, passphrase-protected")
        self.assertEqual(k["hw"]["severity"], "medium")
        self.assertEqual((k["old_open.pem"]["severity"], k["old_locked.pem"]["severity"]), ("high", "info"))
        self.assertEqual(k["p8"]["detail"], "PKCS#8 ed25519, no passphrase")
        self.assertTrue(k["p8enc"]["passphrase"])
        self.assertEqual((k["putty.ppk"]["severity"], k["putty2.ppk"]["severity"]), ("high", "info"))
        for skipped in ("id_x.pub", "notes.txt", "authorized_keys"):
            self.assertNotIn(skipped, k)

    def test_truncated_and_garbled_keys(self):
        whole = synthetic.openssh_key()
        self.write(".ssh/cut", whole[:120])
        self.write(".ssh/garbled", synthetic.pem("OPENSSH PRIVATE KEY", "!!!notbase64!!!"))
        k = self.keys()
        self.assertEqual(k["cut"]["detail"], "OpenSSH unknown type, passphrase status unknown")
        self.assertEqual(k["garbled"]["severity"], "medium")

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
    def test_keys_made_by_ssh_keygen(self):
        d = self.home / ".ssh"
        d.mkdir()
        run = lambda *a: subprocess.run(["ssh-keygen", "-q", *a], capture_output=True, check=True)  # noqa: E731
        run("-t", "ed25519", "-N", "", "-f", str(d / "k1"), "-C", "")
        run("-t", "ecdsa", "-N", rand(12), "-f", str(d / "k2"), "-C", "")
        run("-t", "rsa", "-b", "2048", "-m", "PEM", "-N", "", "-f", str(d / "k3"), "-C", "")
        k = self.keys()
        self.assertEqual(k["k1"]["detail"], "OpenSSH ssh-ed25519, no passphrase")
        self.assertEqual(k["k2"]["detail"], "OpenSSH ecdsa-sha2-nistp256, passphrase-protected")
        self.assertEqual(k["k3"]["detail"], "PEM rsa, no passphrase")

    def test_agent_and_keychain(self):
        self.write(".ssh/config", "Host *\n    usekeychain YES\n")
        sec = cr.scan_ssh(self.ctx(env={**os.environ, "SSH_AUTH_SOCK": "/tmp/agent"}))
        self.assertEqual({x["item"] for x in sec.findings}, {"UseKeychain yes", "ssh-agent"})


class Terraform(Isolated):
    def test_tokens_rc_and_windows(self):
        tok = rand(40)
        self.write(".terraform.d/credentials.tfrc.json", json.dumps({"credentials": {
            "app.terraform.io": {"token": tok}, "tfe.example": {}}}))
        self.write(".terraformrc", 'credentials "tfe2.example" {\n  token = "x"\n}\ncredentials_helper "kc" {}\n')
        sec = cr.scan_terraform(self.ctx())
        f = {x["item"]: x for x in sec.findings}
        self.assertEqual(f["app.terraform.io"]["severity"], "high")
        self.assertEqual(f["tfe.example"]["severity"], "info")
        self.assertEqual(f["tfe2.example"]["severity"], "high")
        self.assertIn("terraform-credentials-kc", f["credentials_helper"]["detail"])
        self.assertNotIn(tok, text_of(sec))
        self.write("AppData/Roaming/terraform.d/credentials.tfrc.json", json.dumps({"credentials": {"w.example": {"token": "t"}}}))
        sec = cr.scan_terraform(self.ctx(system="Windows"))
        self.assertIn("~\\AppData\\Roaming\\terraform.d\\credentials.tfrc.json", sec.paths)
        self.assertIn("w.example", {x["item"] for x in sec.findings})

    def test_malformed(self):
        for bad in ("{", "[]", json.dumps({"credentials": []})):
            self.write(".terraform.d/credentials.tfrc.json", bad)
            self.assertTrue(cr.scan_terraform(self.ctx()).errors, bad)


class EnvFiles(unittest.TestCase):
    def test_parse(self):
        text = ("\ufeff# c\nexport A=1\nB = 'two words' # comment\nC=\"multi\nline\"\nD=plain # tail\nE=\n"
                "not an assignment\n  F=x=y\n#G=hidden\n")
        self.assertEqual(cr.parse_env_file(text), [("A", "1"), ("B", "two words"), ("C", "multi\nline"),
                                                   ("D", "plain"), ("E", ""), ("F", "x=y")])

    def test_placeholders(self):
        for v in ("", "<token>", "${X}", "$X", "%X%", "xxxx", "****", "changeme", "your-key-here", "[REDACTED:jwt]"):
            self.assertTrue(cr.is_placeholder(v) or not v, v)
        for v in ("hunter2", "password", "abc123"):
            self.assertFalse(cr.is_placeholder(v), v)


if __name__ == "__main__":
    unittest.main()
