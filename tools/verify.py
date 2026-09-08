#!/usr/bin/env python3
"""Verification primitives that four lanes each rebuilt on 2026-09-06..08.

Every function here exists because someone got a wrong answer without it.
Read-only. Prints digests and verdicts; never a credential value.

    python3 verify.py creds  [PATH ...]     credentials, encoding-immune
    python3 verify.py id     STRING ...     IBAN / German VAT / EORI checksums
    python3 verify.py fake   STRING ...     does this token look synthetic
    python3 verify.py host   NAME ...       does a domain actually resolve
"""
import hashlib, pathlib, re, socket, sys

CRED = re.compile(rb'ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}'
                  rb'|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}')
SKIP = {'objects', 'node_modules', '.next'}
# Compiled binaries produce AKIA-shaped runs by chance: a 121 MB Electron build
# yielded five. Vendor bundles are excluded, and named when they are.
VENDOR = ('.app/', '/Uygulamalar/', '/site-packages/', '/Frameworks/')


def kind_of(tok):
    for pre, name in ((b'ghp_', 'github classic'), (b'github_pat_', 'github fine'),
                      (b'xox', 'slack'), (b'AKIA', 'aws')):
        if tok.startswith(pre):
            return name
    return 'unknown'


def creds(roots):
    """Read bytes. grep and rg decode a UTF-16 BOM and then find nothing in the
    file, exiting 1 exactly as a clean file does, so no exit status tells you
    which you got. Measured 2026-09-08: FF FE or FE FF at offset 0 hides an
    ASCII token from grep, grep -a, rg and rg -a alike."""
    hits = {}
    for root in roots:
        p = pathlib.Path(root).expanduser()
        for f in ([p] if p.is_file() else p.rglob('*')):
            if not f.is_file() or f.is_symlink() or SKIP & set(f.parts):
                continue
            if any(v in str(f) for v in VENDOR):
                continue
            try:
                if f.stat().st_size > 400 * 1024 * 1024:
                    continue
                b = f.read_bytes()
            except Exception:
                continue
            for m in CRED.finditer(b):
                hits.setdefault(m.group(0), set()).add(str(f))
    for tok, files in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        # The token itself is never printed. A prefix is still a piece of a key.
        print(f"#{hashlib.sha256(tok).hexdigest()[:12]}  {kind_of(tok):<15} "
              f"{len(files):>3} file(s)  {looks_fake(tok.decode(errors='replace'))}")
        for fl in sorted(files)[:4]:
            print(f"    {fl}")
    print(f"{len(hits)} distinct")
    return hits


def looks_fake(tok):
    """Two of R-001's four 'credentials' were placeholders: one a single
    repeated character, one sequential. Rotating a placeholder wastes the
    attention the real one needs."""
    body = tok.split('_', 1)[-1]
    uniq = len(set(body))
    run = max((len(r) for r in re.findall(r'(.)\1*', body)), default=0)
    seq = any(x in body for x in ('123456', 'ABCDEF', 'abcdef'))
    return "looks synthetic" if (uniq < 12 or run >= 6 or seq) else "looks real"


def iban(v):
    v = v.replace(' ', '').upper()
    if not re.fullmatch(r'[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}', v):
        return "not IBAN-shaped"
    r = v[4:] + v[:4]
    n = int(''.join(str(int(c, 36)) for c in r))
    return "valid" if n % 97 == 1 else "INVALID checksum, fabricated"


def ustid(v):
    """German USt-IdNr, ISO 7064 MOD 11,10."""
    d = v[2:]
    if not (v[:2] == 'DE' and len(d) == 9 and d.isdigit()):
        return "not a German VAT id"
    P = 10
    for c in d[:8]:
        M = (int(c) + P) % 10 or 10
        P = (2 * M) % 11
    chk = 11 - P
    return "valid" if (0 if chk == 10 else chk) == int(d[8]) else "INVALID checksum, fabricated"


def host(name):
    try:
        socket.getaddrinfo(name, None)
        return "RESOLVES, treat as a real party"
    except socket.gaierror:
        return "does not resolve"


if __name__ == "__main__":
    cmd, args = (sys.argv[1:] or ["creds"])[0], sys.argv[2:]
    if cmd == "creds":
        creds(args or ["~/.claude", "~/agents", "~/Desktop"])
    elif cmd == "id":
        for a in args:
            print(f"  {a}: {iban(a) if not a.startswith('DE') or len(a) > 11 else ustid(a)}")
    elif cmd == "fake":
        for a in args:
            print(f"  {looks_fake(a)}")
    elif cmd == "host":
        for a in args:
            print(f"  {a}: {host(a)}")
    else:
        print(__doc__)
