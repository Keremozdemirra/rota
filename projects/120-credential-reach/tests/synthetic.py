"""A home directory and a project full of fake credentials, made at run time.

Every secret here is generated when the builder runs, so no token-shaped text
exists in this repository (secret scanners and push protection would stop it).
The tests plant these values as canaries and check that none of them appears in
any output. The README example comes from `python3 tests/synthetic.py --run`,
which builds this home in a temporary directory and runs credential-reach there
with a clean environment, so it never sees the real home directory.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
from pathlib import Path

ALNUM = string.ascii_letters + string.digits
UPPER = string.ascii_uppercase + string.digits
DASHES = "-" * 5


def rand(n: int, alphabet: str = ALNUM) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


def pem(label: str, body: str, headers: str = "") -> str:
    """A PEM block; the armour is assembled here so that no key header is written out in the source."""
    return f"{DASHES}BEGIN {label}{DASHES}\n{headers}{body}\n{DASHES}END {label}{DASHES}\n"


def _wrap(data: bytes) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return "\n".join(b64[i:i + 70] for i in range(0, len(b64), 70))


def _s(b: bytes) -> bytes:
    return len(b).to_bytes(4, "big") + b


def openssh_key(cipher: str = "none", key_type: str = "ssh-ed25519", private: bytes | None = None) -> str:
    """An openssh-key-v1 file with the layout of PROTOCOL.key and random key material."""
    pub = _s(key_type.encode()) + _s(secrets.token_bytes(32))
    kdf, opts = (b"none", b"") if cipher == "none" else (b"bcrypt", _s(secrets.token_bytes(16)) + (16).to_bytes(4, "big"))
    blob = (b"openssh-key-v1\x00" + _s(cipher.encode()) + _s(kdf) + _s(opts) + (1).to_bytes(4, "big") + _s(pub)
            + _s(private if private is not None else secrets.token_bytes(64)))
    return pem("OPENSSH PRIVATE KEY", _wrap(blob))


def pkcs8_ed25519() -> str:
    der = bytes.fromhex("302e020100300506032b657004220420") + secrets.token_bytes(32)
    return pem("PRIVATE KEY", _wrap(der))


def pem_rsa(encrypted: bool) -> str:
    headers = f"Proc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,{secrets.token_hex(16).upper()}\n\n" if encrypted else ""
    return pem("RSA PRIVATE KEY", _wrap(secrets.token_bytes(600)), headers)


def canaries() -> dict:
    """One fresh fake secret of every kind the builder plants."""
    return {
        "gh_classic": "ghp_" + rand(36),
        "gh_fine": "github_pat_" + rand(22) + "_" + rand(59),
        "gh_oauth": "gho_" + rand(36),
        "gh_gitcred": "ghp_" + rand(36),
        "gitlab": "glpat-" + rand(20),
        "aws_id": "AKIA" + rand(16, UPPER),
        "aws_secret": rand(40, ALNUM + "/+"),
        "aws_temp_secret": rand(40, ALNUM + "/+"),
        "aws_session": rand(120),
        "sso_access": rand(64),
        "anthropic": "sk-ant-api03-" + rand(80, ALNUM + "_-"),
        "openai": "sk-proj-" + rand(48),
        "stripe": "sk_live_" + rand(24),
        "db_password": rand(18),
        "kube_token": rand(48),
        "kube_key": rand(40),
        "docker_password": rand(24),
        "npm": "npm_" + rand(36),
        "pypi": "pypi-" + "AgEIcHlwaS5vcmc" + rand(70, ALNUM + "_-"),
        "netrc_password": rand(20),
        "terraform": rand(14) + ".atlasv1." + rand(60),
        "gcloud_refresh": "1//" + rand(60),
        "gcloud_secret": rand(24),
        "azure_refresh": rand(80),
        "ssh_private": rand(48),
        "env_file_token": "ghp_" + rand(36),
        "transcript_password": rand(16),
    }


def write(path: Path, content, mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="")
    if mode is not None:
        os.chmod(path, mode)
    return path


def transcript_lines(c: dict) -> list:
    key_block = openssh_key(private=c["ssh_private"].encode())
    return [
        {"type": "user", "message": {"role": "user", "content": "Deploy it. The token is " + c["gh_classic"]},
         "cwd": "/work/app"},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "export AWS_ACCESS_KEY_ID=" + c["aws_id"]}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "cat ~/.ssh/deploy\n" + key_block}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": "Grüße: connected to postgres://app:"
                                          + c["transcript_password"] + "@db.internal:5432/app"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "Nothing secret in this line."}},
    ]


def build(root: Path, git: bool = True) -> dict:
    """Build root/home and root/project. Returns home, project, the environment to run with, and the canaries."""
    c = canaries()
    home, project = root / "home", root / "project"
    home.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)

    write(home / ".aws" / "credentials",
          f"[default]\naws_access_key_id = {c['aws_id']}\naws_secret_access_key = {c['aws_secret']}\n\n"
          f"[ci-temp]\naws_access_key_id = ASIA{rand(16, UPPER)}\naws_secret_access_key = {c['aws_temp_secret']}\n"
          f"aws_session_token = {c['aws_session']}\n", 0o600)
    write(home / ".aws" / "config",
          "[default]\nregion = eu-central-1\n\n"
          "[profile prod]\nsso_session = corp\nsso_account_id = 123456789012\nsso_role_name = AdministratorAccess\n\n"
          "[sso-session corp]\nsso_start_url = https://corp-example.awsapps.com/start\nsso_region = eu-central-1\n\n"
          "[profile deploy]\nrole_arn = arn:aws:iam::123456789012:role/Deploy\nsource_profile = default\n\n"
          "[profile vault]\ncredential_process = aws-vault export --format=json dev\n")
    write(home / ".aws" / "sso" / "cache" / (secrets.token_hex(20) + ".json"),
          json.dumps({"accessToken": c["sso_access"], "expiresAt": "2099-01-01T00:00:00Z",
                      "region": "eu-central-1", "startUrl": "https://corp-example.awsapps.com/start"}))

    gcloud = home / ".config" / "gcloud"
    write(gcloud / "active_config", "default\n")
    write(gcloud / "configurations" / "config_default", "[core]\naccount = dev@example.com\nproject = demo-project\n")
    write(gcloud / "credentials.db", b"SQLite format 3\x00" + secrets.token_bytes(64))
    write(gcloud / "application_default_credentials.json", json.dumps({
        "type": "authorized_user", "client_id": rand(20) + ".apps.googleusercontent.com",
        "client_secret": c["gcloud_secret"], "refresh_token": c["gcloud_refresh"]}), 0o600)

    profile = {"subscriptions": [
        {"id": secrets.token_hex(16), "name": "Production", "isDefault": True, "tenantId": secrets.token_hex(16),
         "user": {"name": "dev@example.com", "type": "user"}},
        {"id": secrets.token_hex(16), "name": "CI", "isDefault": False, "tenantId": secrets.token_hex(16),
         "user": {"name": secrets.token_hex(16), "type": "servicePrincipal"}}]}
    write(home / ".azure" / "azureProfile.json", b"\xef\xbb\xbf" + json.dumps(profile).encode("utf-8"))
    write(home / ".azure" / "msal_token_cache.json", json.dumps({"RefreshToken": {"x": {"secret": c["azure_refresh"]}}}))

    write(home / ".kube" / "config", f"""apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: {base64.b64encode(secrets.token_bytes(48)).decode()}
    server: https://203.0.113.10:6443
  name: prod
- cluster:
    insecure-skip-tls-verify: true
    server: https://dev.k8s.example.com
  name: dev
- cluster:
    server: https://ABCDEF.gr7.eu-central-1.eks.amazonaws.com
  name: eks
contexts:
- context:
    cluster: prod
    namespace: default
    user: prod-admin
  name: prod
- context:
    cluster: dev
    user: dev-user
  name: dev
- context:
    cluster: eks
    user: eks-user
  name: eks
current-context: prod
kind: Config
preferences: {{}}
users:
- name: prod-admin
  user:
    token: {c['kube_token']}
- name: dev-user
  user:
    client-certificate-data: {base64.b64encode(secrets.token_bytes(48)).decode()}
    client-key-data: {base64.b64encode(c['kube_key'].encode()).decode()}
- name: eks-user
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: aws
      args:
      - eks
      - get-token
      - --cluster-name
      - eks
      env: null
""", 0o600)

    write(home / ".docker" / "config.json", json.dumps({
        "auths": {"https://index.docker.io/v1/": {"auth": base64.b64encode(("dev:" + c["docker_password"]).encode()).decode()},
                  "ghcr.io": {}},
        "credHelpers": {"123456789012.dkr.ecr.eu-central-1.amazonaws.com": "ecr-login"},
        "credsStore": "pass"}, indent=1))

    write(home / ".npmrc", f"//registry.npmjs.org/:_authToken={c['npm']}\n@corp:registry=https://npm.corp.example.com/\n"
                           "//npm.corp.example.com/:_authToken=${CORP_NPM_TOKEN}\n")
    write(home / ".pypirc", f"[distutils]\nindex-servers =\n    pypi\n    private\n\n[pypi]\nusername = __token__\n"
                            f"password = {c['pypi']}\n\n[private]\nrepository = https://pypi.corp.example.com/\n"
                            "username = dev\n")
    write(home / ".netrc", f"machine api.heroku.com\n  login dev@example.com\n  password {c['netrc_password']}\n"
                           "machine example.org login anonymous\n", 0o600)
    write(home / ".git-credentials", f"https://dev:{c['gh_gitcred']}@github.com\nhttps://oauth2:{c['gitlab']}@gitlab.com\n",
          0o600)
    write(home / ".gitconfig", "[user]\n\tname = Dev\n[credential]\n\thelper = store\n"
                               "[credential \"https://dev.azure.com\"]\n\thelper = manager\n")
    write(home / ".config" / "gh" / "hosts.yml", f"""github.com:
    users:
        dev:
            oauth_token: {c['gh_oauth']}
    git_protocol: https
    oauth_token: {c['gh_oauth']}
    user: dev
ghe.corp.example.com:
    users:
        dev:
    git_protocol: ssh
    user: dev
""")

    ssh = home / ".ssh"
    write(ssh / "id_ed25519", openssh_key(private=c["ssh_private"].encode()), 0o600)
    write(ssh / "id_ed25519.pub", "ssh-ed25519 " + base64.b64encode(secrets.token_bytes(51)).decode() + " dev@laptop\n")
    write(ssh / "work_rsa", openssh_key("aes256-ctr", "ssh-rsa"), 0o600)
    write(ssh / "legacy.pem", pem_rsa(encrypted=True), 0o600)
    write(ssh / "known_hosts", "github.com ssh-ed25519 " + base64.b64encode(secrets.token_bytes(51)).decode() + "\n")
    write(ssh / "config", "Host *\n  UseKeychain yes\n  AddKeysToAgent yes\n")

    write(home / ".terraform.d" / "credentials.tfrc.json",
          json.dumps({"credentials": {"app.terraform.io": {"token": c["terraform"]}}}, indent=2))

    sessions = home / ".claude" / "projects" / "-work-app"
    lines = transcript_lines(c)
    write(sessions / (secrets.token_hex(16) + ".jsonl"),
          "".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in lines))
    write(sessions / (secrets.token_hex(16) + ".jsonl"),
          json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n")

    write(project / ".env", f"GITHUB_TOKEN={c['env_file_token']}\nSTRIPE_SECRET_KEY={c['stripe']}\n"
                            f"DATABASE_URL=postgres://app:{c['db_password']}@db.internal:5432/app\nDEBUG=true\n")
    write(project / ".env.example", "GITHUB_TOKEN=\nSTRIPE_SECRET_KEY=your-key-here\nDEBUG=false\n")
    write(project / "config" / ".env.local", f"OPENAI_API_KEY={c['openai']}\n")
    write(project / "certs" / "server.key", pkcs8_ed25519())
    write(project / "certs" / "ca.pem", pem("CERTIFICATE", _wrap(secrets.token_bytes(300))))
    write(project / "deploy" / "terraform.tfstate", json.dumps({"version": 4, "resources": []}))
    write(project / "node_modules" / "pkg" / ".env", "NPM_TOKEN=" + c["npm"] + "\n")
    write(project / ".gitignore", "config/.env.local\nnode_modules/\n")
    write(project / "app.py", "print('hello')\n")
    if git and shutil.which("git"):
        run = dict(cwd=project, capture_output=True, env=clean_env(home))
        subprocess.run(["git", "init", "-q"], **run)
        subprocess.run(["git", "add", "app.py", ".gitignore", "certs/ca.pem"], **run)

    env = clean_env(home)
    env.update({"GITHUB_TOKEN": c["gh_classic"], "ANTHROPIC_API_KEY": c["anthropic"], "AWS_PROFILE": "prod",
                "AWS_REGION": "eu-central-1", "DATABASE_URL": f"postgres://app:{c['db_password']}@db.internal/app",
                "SSH_AUTH_SOCK": str(ssh / "agent.sock"), "CORP_NPM_TOKEN": "", "TOKENIZERS_PARALLELISM": "false"})
    return {"home": home, "project": project, "env": env, "canaries": c}


def clean_env(home: Path) -> dict:
    """What a run sees instead of the real environment: this home, and PATH to find git."""
    env = {"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData" / "Roaming"),
           "XDG_CONFIG_HOME": str(home / ".config"), "PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8",
           "GIT_CONFIG_NOSYSTEM": "1"}
    for k in ("SYSTEMROOT", "TMP", "TEMP"):  # Windows needs these to start processes
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def main(argv: list) -> int:
    """python3 tests/synthetic.py [--run] [DIR] [-- credential-reach options]"""
    run = "--run" in argv
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    args = [a for a in (argv[:argv.index("--")] if "--" in argv else argv) if a != "--run"]
    root = Path(args[0]).resolve() if args else Path(tempfile.mkdtemp(prefix="credential-reach-demo-"))
    built = build(root)
    if not run:
        print(f"synthetic home: {built['home']}\nsynthetic project: {built['project']}")
        return 0
    tool = Path(__file__).resolve().parent.parent / "credential_reach.py"
    proc = subprocess.run([sys.executable, str(tool), "--project", str(built["project"])] + rest,
                          cwd=built["project"], env=built["env"])
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
