"""Rebuild the bundled snapshots from the sources, with the standard library only.

    cbam-mcp refresh                     # all sources, into cbam_mcp/data/
    cbam-mcp refresh --check-oj          # also compare every value with the Official Journal text
    cbam-mcp refresh --data-dir DIR      # somewhere else (then set CBAM_MCP_DATA_DIR=DIR)

Each source is fetched, parsed and checked on its own. A source that cannot be
fetched or parsed leaves its previous file untouched; files are replaced
atomically, so a failed refresh never leaves half a file behind.
Exit codes: 0 all refreshed; 1 the Official Journal check found a difference;
2 a source could not be refreshed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import os
import socket
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__, legal, parsers

UA = f"cbam-mcp/{__version__} (+https://github.com/Keremozdemirra/cbam-mcp)"
SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
CELLAR = legal.CELLAR
# The consolidated text in use on 2026-09-24; used when the SPARQL lookup for a
# newer one fails.
PINNED_CONSOLIDATION = "02023R0956-20251020"
EXCEL_URL = "https://taxation-customs.ec.europa.eu/document/download/1c05d211-80cb-4aaa-8ef0-e08005a95d7e_en"
EXCEL_PAGE = "https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism/cbam-legislation-and-guidance_en"
OJ_VALUES_CELEX = "32026R1740"
CN_PREFIXES = ("25", "28", "31", "72", "73", "76", "2601", "2716")
CN_YEARS = (2026, 2025)

# Size limits chosen by this tool, well above the real files (2026-09-24:
# consolidated XHTML 0.5 MB, Excel 0.6 MB, SPARQL answers 0.9 MB, OJ XHTML 16 MB).
MAX_XHTML = 8 * 1024 * 1024
MAX_XLSX = 16 * 1024 * 1024
MAX_SPARQL = 16 * 1024 * 1024
MAX_OJ = 64 * 1024 * 1024

FILES = {"annex": "annex_i.json", "values": "default_values.json", "cn2026": "cn_2026.json", "cn2025": "cn_2025.json"}


class FetchError(RuntimeError):
    """A download that did not produce a usable body."""


class Fetched:
    def __init__(self, body: bytes, headers: dict, url: str):
        self.body, self.headers, self.url = body, headers, url


def fetch(url: str, *, accept: str = "*/*", data: bytes | None = None, timeout: float = 60,
          max_bytes: int = MAX_XHTML, attempts: int = 2, sleep=time.sleep) -> Fetched:
    """GET (or POST when `data` is given) with the failures that really happen turned into FetchError."""
    headers = {"User-Agent": UA, "Accept": accept, "Accept-Language": "eng"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    last = "no attempt made"
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read(max_bytes + 1)
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            if len(body) > max_bytes:
                raise FetchError(f"{url}: response larger than {max_bytes // (1024 * 1024)} MB, refused")
            # EUR-Lex answers 202 with an empty body to clients it does not serve.
            if status != 200:
                raise FetchError(f"{url}: HTTP {status} instead of 200")
            if not body.strip():
                raise FetchError(f"{url}: empty response body")
            return Fetched(body, resp_headers, url)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 429 or e.code >= 500:
                retry_after = (e.headers or {}).get("Retry-After", "") if e.headers else ""
                wait = int(retry_after) if retry_after.isdigit() and int(retry_after) <= 30 else 3
                if attempt + 1 < attempts:
                    sleep(wait)
                    continue
                if e.code == 429:
                    last = "HTTP 429 (rate limited)"
            raise FetchError(f"{url}: {last}") from None
        except FetchError:
            raise
        except urllib.error.URLError as e:
            last = f"network error ({e.reason})"
        except (socket.timeout, TimeoutError):
            last = f"timed out after {timeout:.0f} s"
        except (http.client.HTTPException, ConnectionError, ssl.SSLError, OSError) as e:
            last = f"connection failed ({type(e).__name__}: {e})"
        if attempt + 1 < attempts:
            sleep(3)
    raise FetchError(f"{url}: {last}")


def sparql(query: str, fetcher=fetch, what: str = "SPARQL") -> tuple[list[dict], Fetched]:
    body = urllib.parse.urlencode({"query": query}).encode()
    got = fetcher(SPARQL_ENDPOINT, accept="application/sparql-results+json", data=body, max_bytes=MAX_SPARQL)
    return parsers.sparql_rows(got.body, what), got


# ------------------------------------------------------------------ queries

Q_CONSOLIDATED = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?celex ?date WHERE {
  ?base cdm:resource_legal_id_celex "32023R0956"^^xsd:string .
  ?cons cdm:act_consolidated_consolidates_resource_legal ?base ;
        cdm:resource_legal_id_celex ?celex .
  OPTIONAL { ?cons cdm:act_consolidated_date ?date }
} ORDER BY DESC(?celex) LIMIT 5"""

Q_LATER_ACTS = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?base ?celex ?date ?rel WHERE {
  VALUES ?base { "32023R0956"^^xsd:string "32025R2621"^^xsd:string }
  ?b cdm:resource_legal_id_celex ?base .
  { ?act cdm:resource_legal_amends_resource_legal ?b . BIND("amends" AS ?rel) }
  UNION { ?act cdm:resource_legal_corrects_resource_legal ?b . BIND("corrects" AS ?rel) }
  ?act cdm:resource_legal_id_celex ?celex .
  OPTIONAL { ?act cdm:work_date_document ?date }
} ORDER BY DESC(?date)"""


def q_cn(year: int) -> str:
    cond = " || ".join(f'STRSTARTS(?id, "{p}")' for p in CN_PREFIXES)
    return f"""PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xkos: <http://rdf-vocabulary.ddialliance.org/xkos#>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
SELECT ?id ?notation ?label ?note ?parent ?depth WHERE {{
  ?c skos:inScheme <http://data.europa.eu/xsp/cn{year}/cn{year}> ;
     dc:identifier ?id .
  FILTER({cond})
  OPTIONAL {{ ?c skos:notation ?notation }}
  OPTIONAL {{ ?c skos:altLabel ?label FILTER(lang(?label) = "en") }}
  OPTIONAL {{ ?c skos:scopeNote ?note FILTER(lang(?note) = "en") }}
  OPTIONAL {{ ?c skos:broader ?b . ?b dc:identifier ?parent }}
  OPTIONAL {{ ?c xkos:depth ?depth }}
}}"""


def q_cn_ids(year: int, ids) -> str:
    values = " ".join(f'"{i}"' for i in sorted(ids) if i.isdigit())
    return f"""PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xkos: <http://rdf-vocabulary.ddialliance.org/xkos#>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
SELECT ?id ?notation ?label ?note ?parent ?depth WHERE {{
  VALUES ?id {{ {values} }}
  ?c skos:inScheme <http://data.europa.eu/xsp/cn{year}/cn{year}> ;
     dc:identifier ?id .
  OPTIONAL {{ ?c skos:notation ?notation }}
  OPTIONAL {{ ?c skos:altLabel ?label FILTER(lang(?label) = "en") }}
  OPTIONAL {{ ?c skos:scopeNote ?note FILTER(lang(?note) = "en") }}
  OPTIONAL {{ ?c skos:broader ?b . ?b dc:identifier ?parent }}
  OPTIONAL {{ ?c xkos:depth ?depth }}
}}"""


# ------------------------------------------------------------------ writing

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def dump_json(doc: dict, big_keys: tuple = ()) -> str:
    """JSON with one table row per line, so a refresh shows up as a readable diff."""
    parts = []
    for key, value in doc.items():
        if key in big_keys and isinstance(value, dict):
            inner = []
            for k, v in value.items():
                if isinstance(v, dict):
                    rows = ",\n".join(f"  {json.dumps(rk, ensure_ascii=False)}: {json.dumps(rv, ensure_ascii=False)}"
                                      for rk, rv in v.items())
                    inner.append(f" {json.dumps(k, ensure_ascii=False)}: {{\n{rows}\n }}")
                else:
                    inner.append(f" {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}")
            parts.append(f"{json.dumps(key)}: {{\n" + ",\n".join(inner) + "\n}")
        elif key in big_keys and isinstance(value, list):
            rows = ",\n".join(" " + json.dumps(v, ensure_ascii=False) for v in value)
            parts.append(f"{json.dumps(key)}: [\n{rows}\n]")
        else:
            parts.append(f"{json.dumps(key)}: {json.dumps(value, ensure_ascii=False, indent=1)}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ steps

def later_acts(fetcher=fetch) -> dict:
    rows, _ = sparql(Q_LATER_ACTS, fetcher, "later-acts query")
    out: dict = {"32023R0956": [], "32025R2621": []}
    for r in rows:
        base = r.get("base")
        if base in out and r.get("celex"):
            out[base].append({"celex": r["celex"], "date": r.get("date"), "relation": r.get("rel")})
    return out


def refresh_annex(today: str, fetcher=fetch) -> dict:
    notes = []
    celex, cons_date = PINNED_CONSOLIDATION, "2025-10-20"
    try:
        rows, _ = sparql(Q_CONSOLIDATED, fetcher, "consolidated-versions query")
        found = sorted((r for r in rows if (r.get("celex") or "").startswith("02023R0956-")),
                       key=lambda r: r.get("date") or "", reverse=True)
        if found:
            celex, cons_date = found[0]["celex"], found[0].get("date") or cons_date
        else:
            notes.append("SPARQL listed no consolidated version; used the pinned one")
    except (FetchError, parsers.ParseError) as e:
        notes.append(f"latest consolidated version not checked ({e}); used the pinned one")
    url = CELLAR + celex
    got = fetcher(url, accept="application/xhtml+xml", max_bytes=MAX_XHTML)
    parsed = parsers.parse_regulation_xhtml(got.body)
    meta = {
        "source": "Consolidated text of Regulation (EU) 2023/956 (CBAM Regulation)",
        "celex": celex, "consolidation_date": cons_date, "reference": parsed["reference"], "url": url,
        "retrieved": today, "sha256": sha256(got.body), "bytes": len(got.body),
        "amendments": parsed["amendments"], "disclaimer": parsed["disclaimer"],
        "annex_i_lines": len(parsed["annex_i"]), "annex_ii_lines": len(parsed["annex_ii"]), "notes": notes,
    }
    doc = {"meta": meta, "annex_i_intro": parsed["annex_i_intro"], "annex_i": parsed["annex_i"],
           "annex_ii": parsed["annex_ii"], "annex_iii_point_1": parsed["annex_iii_point_1"], "quotes": parsed["quotes"]}
    return doc


def compare_with_oj(values: dict, oj: dict) -> dict:
    tables, rows_cmp, rows_same, diffs = 0, 0, 0, []
    for name, rows in values["tables"].items():
        other = oj["tables"].get(name.replace("’", "'"))
        if other is None:
            diffs.append({"table": name, "problem": "table not found in the Official Journal text"})
            continue
        tables += 1
        for code in sorted(set(rows) | set(other)):
            rows_cmp += 1
            if rows.get(code) == other.get(code):
                rows_same += 1
            elif len(diffs) < 50:
                diffs.append({"table": name, "line": code, "excel": rows.get(code), "official_journal": other.get(code)})
    a4 = values["annex_iv"]
    a4_codes = sorted(set(a4) | set(oj["annex_iv"]))
    a4_same = sum(1 for c in a4_codes if a4.get(c) == oj["annex_iv"].get(c))
    for c in a4_codes:
        if a4.get(c) != oj["annex_iv"].get(c) and len(diffs) < 50:
            diffs.append({"table": "Annex IV", "line": c, "excel": a4.get(c), "official_journal": oj["annex_iv"].get(c)})
    missing_tables = sorted(set(oj["tables"]) - {n.replace("’", "'") for n in values["tables"]})
    text = oj["text"]
    quotes = {}
    for name in ("RULE_NOT_LISTED", "RULE_NO_VALUE", "NO_ROUTE", "DIRECT_INDIRECT_FOR_INFORMATION"):
        quotes[name] = getattr(legal, name)["quote"] in text
    return {"tables_compared": tables, "rows_compared": rows_cmp, "rows_identical": rows_same,
            "annex_iv_compared": len(a4_codes), "annex_iv_identical": a4_same,
            "tables_only_in_official_journal": missing_tables, "differences": diffs, "quotes_found": quotes}


def refresh_values(data_dir: Path, today: str, fetcher=fetch, check_oj: bool = False, excel_url: str = EXCEL_URL,
                   log=print) -> tuple[dict, bool]:
    got = fetcher(excel_url, accept="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
                  max_bytes=MAX_XLSX)
    parsed = parsers.parse_default_values_xlsx(got.body)
    digest = sha256(got.body)
    disposition = got.headers.get("content-disposition", "")
    filename = None
    if "filename=" in disposition:
        filename = disposition.split("filename=", 1)[1].strip().strip('"')
    latest = max(parsed["versions"], key=lambda v: int(v["version"])) if parsed["versions"] else {}
    tables = {name: {code: "|".join(row) for code, row in rows.items()} for name, rows in parsed["tables"].items()}
    annex_iv = {code: "|".join(row) for code, row in parsed["annex_iv"].items()}
    meta = {
        "source": "European Commission, DG TAXUD: Default values definitive period (Excel format)",
        "url": excel_url, "page": EXCEL_PAGE, "filename": filename, "retrieved": today, "sha256": digest,
        "bytes": len(got.body), "version": latest.get("version"), "version_date": latest.get("date"),
        "version_note": latest.get("note"), "versions": parsed["versions"], "disclaimer": parsed["disclaimer"],
        "sheets": parsed["sheet_count"], "tables": len(tables), "rows": sum(len(t) for t in tables.values()),
        "lines": len(parsed["order"]), "annex_iv_rows": len(annex_iv), "oj_check": None,
    }
    found_difference = False
    if check_oj:
        oj_got = fetcher(CELLAR + OJ_VALUES_CELEX, accept="application/xhtml+xml", max_bytes=MAX_OJ, timeout=180)
        oj = parsers.parse_oj_default_values(oj_got.body)
        result = compare_with_oj(parsed, oj)
        result.update({"checked": today, "celex": OJ_VALUES_CELEX, "url": CELLAR + OJ_VALUES_CELEX,
                       "sha256": sha256(oj_got.body), "bytes": len(oj_got.body)})
        meta["oj_check"] = result
        found_difference = bool(result["differences"]) or not all(result["quotes_found"].values())
    else:
        previous = load_json(data_dir / FILES["values"])
        prev_meta = (previous or {}).get("meta") or {}
        # A check made on a byte-identical file still holds; on any other file it does not.
        if prev_meta.get("sha256") == digest and prev_meta.get("oj_check"):
            meta["oj_check"] = prev_meta["oj_check"]
    lines = [[c, parsed["lines"][c]["display"], parsed["lines"][c]["description"], parsed["lines"][c]["category"]]
             for c in parsed["order"]]
    doc = {"meta": meta, "other_table": parsed["other_table"], "lines": lines, "tables": tables, "annex_iv": annex_iv}
    return doc, found_difference


def refresh_cn(year: int, today: str, fetcher=fetch) -> dict:
    rows, got = sparql(q_cn(year), fetcher, f"CN {year} query")
    concepts = parsers.parse_cn_rows(rows)
    hashes = [sha256(got.body)]
    # Chapters 26 and 27 and their section are only needed as ancestors of 2601 and 2716.
    for _ in range(3):
        missing = {c[4] for c in concepts.values() if c[4] and c[4] not in concepts}
        if not missing:
            break
        more, got = sparql(q_cn_ids(year, missing), fetcher, f"CN {year} ancestors query")
        hashes.append(sha256(got.body))
        concepts.update(parsers.parse_cn_rows(more))
    # Floor chosen by this tool: the 2025 and 2026 answers have about 1,600 concepts.
    if len(concepts) < 500:
        raise parsers.ParseError(f"CN {year}: only {len(concepts)} concepts returned; refusing to replace the snapshot")
    meta = {
        "source": f"Combined Nomenclature {year}, EU Vocabularies (Publications Office of the European Union)",
        "year": year, "scheme": f"http://data.europa.eu/xsp/cn{year}/cn{year}", "endpoint": SPARQL_ENDPOINT,
        "dataset": legal.CN_DATASET[year], "legal_basis": legal.CN_BINDING_SOURCE[year],
        "subset": "Chapters 25, 28, 31, 72, 73 and 76 in full; headings 2601 and 2716 with their chapters",
        "retrieved": today, "sha256_of_responses": hashes, "concepts": len(concepts),
    }
    return {"meta": meta, "concepts": dict(sorted(concepts.items()))}


# ------------------------------------------------------------------ SOURCES.md

def render_sources(annex: dict | None, values: dict | None, cn: dict, acts: dict | None, today: str) -> str:
    out = ["# Sources of the bundled data", "",
           "Generated by `cbam-mcp refresh`; edit the code, not this file. Dates are retrieval dates (UTC).", ""]
    if annex:
        m = annex["meta"]
        out += ["## annex_i.json: CBAM scope (Annexes I, II and III of Regulation (EU) 2023/956)", "",
                f"- Source: {m['source']}, CELEX {m['celex']} ({m.get('reference') or ''})",
                f"- URL: {m['url']} (CELLAR, content negotiation `Accept: application/xhtml+xml`, `Accept-Language: eng`)",
                f"- Retrieved: {m['retrieved']}; {m['bytes']} bytes; SHA-256 `{m['sha256']}`",
                f"- Rows: {m['annex_i_lines']} Annex I lines, {m['annex_ii_lines']} Annex II lines, "
                f"{len((annex.get('annex_iii_point_1') or {}).get('countries', []))} Annex III countries, "
                f"{len((annex.get('annex_iii_point_1') or {}).get('territories', []))} Annex III territories",
                f"- Amended by: {', '.join(f'{k} = {v}' for k, v in m.get('amendments', {}).items()) or 'none'}",
                f"- Legal status: the consolidated text says: \"{m.get('disclaimer') or ''}\"",
                f"- Licence: {legal.LICENCES['eurlex']['name']}. Terms: {legal.LICENCES['eurlex']['terms']}: "
                f"\"{legal.LICENCES['eurlex']['quote']}\"",
                "- Attribution: © European Union, https://eur-lex.europa.eu. Changes: table extracted from the "
                "XHTML (codes, descriptions, gases, exceptions); amendment markers kept as `amended_by`.", ""]
        for n in m.get("notes") or []:
            out.append(f"- Note: {n}")
    if values:
        m = values["meta"]
        out += ["## default_values.json: default values (Commission Excel)", "",
                f"- Source: {m['source']}",
                f"- URL: {m['url']} (file name `{m.get('filename')}`), listed on {m['page']}",
                f"- Retrieved: {m['retrieved']}; {m['bytes']} bytes; SHA-256 `{m['sha256']}`",
                f"- Version: {m.get('version')} of {m.get('version_date')} (sheet 'Version History': "
                f"\"{m.get('version_note')}\")",
                f"- Rows: {m['sheets']} sheets; {m['tables']} tables (countries plus 'Other countries and "
                f"territories'); {m['rows']} country lines over {m['lines']} CN/TARIC lines; "
                f"{m['annex_iv_rows']} Annex IV lines",
                f"- Legal status: \"{legal.EXCEL_NOTICE['quote']}\" ({legal.EXCEL_NOTICE['source']}). The file "
                f"itself says: \"{m.get('disclaimer')}\"",
                f"- Licence: {legal.LICENCES['commission']['name']}. Terms: {legal.LICENCES['commission']['terms']}: "
                f"\"{legal.LICENCES['commission']['quote']}\"",
                "- Attribution: Source: European Commission, DG TAXUD. Changes: values kept as published "
                "(decimal comma); answers convert them to numbers (derived).", ""]
        check = m.get("oj_check")
        if check:
            out += [f"- Checked against the Official Journal on {check['checked']}: {check['url']} "
                    f"(SHA-256 `{check['sha256']}`): {check['rows_identical']} of {check['rows_compared']} country "
                    f"lines in {check['tables_compared']} tables and {check['annex_iv_identical']} of "
                    f"{check['annex_iv_compared']} Annex IV lines identical; quoted rules found: "
                    f"{', '.join(k for k, v in check['quotes_found'].items() if v) or 'none'}.", ""]
        else:
            out += ["- Not checked against the Official Journal text for this file (run `cbam-mcp refresh --check-oj`).", ""]
    for year in sorted(cn, reverse=True):
        m = cn[year]["meta"]
        out += [f"## cn_{year}.json: Combined Nomenclature {year} (subset)", "",
                f"- Source: {m['source']}; dataset {m['dataset']}; scheme {m['scheme']}",
                f"- Endpoint: {m['endpoint']} (SPARQL; the queries are in `cbam_mcp/refresh.py`)",
                f"- Retrieved: {m['retrieved']}; {m['concepts']} concepts ({m['subset']}); SHA-256 of the "
                f"responses: {', '.join(f'`{h}`' for h in m['sha256_of_responses'])}",
                f"- Legally binding text: {m['legal_basis']}",
                f"- Licence: {legal.LICENCES['cn']['name']}. Terms: {legal.LICENCES['cn']['terms']}. "
                f"{legal.LICENCES['cn']['quote']}",
                "- Attribution: Source: Publications Office of the European Union, EU Vocabularies. Changes: English "
                "labels only; leading dashes turned into an indent number.", ""]
    if acts and isinstance(acts.get("acts"), dict):
        out += [f"## Later acts (CELLAR SPARQL, checked {acts.get('checked')})", ""]
        for base, rows in acts["acts"].items():
            listed = "; ".join(f"{r['celex']} {r.get('relation')} {r.get('date')}" for r in rows) or "none"
            out.append(f"- Acts amending or correcting {base}: {listed}")
        out.append("")
    out += ["## Not bundled", "",
            "- Annexes II and III to Implementing Regulation (EU) 2025/2621 (emission factors for indirect "
            "emissions and default values for electricity). The Excel does not contain them, and the regulation "
            f"says: \"{legal.IEA_NOTICE['quote']}\".", ""]
    return "\n".join(out)


# ------------------------------------------------------------------ driver

def run(data_dir: Path, *, only=None, check_oj: bool = False, excel_url: str = EXCEL_URL, fetcher=fetch,
        today: str | None = None, log=print) -> int:
    today = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
    data_dir = Path(data_dir)
    wanted = set(only or ("annex", "values", "cn"))
    failures: list[str] = []
    found_difference = False

    def step(name, fn):
        try:
            return fn()
        except (FetchError, parsers.ParseError, KeyError, ValueError, TypeError) as e:
            failures.append(f"{name}: {e}")
            log(f"FAILED {name}: {e}; previous file kept")
            return None

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        log(f"cannot write to {data_dir}: {e}. Use --data-dir and set CBAM_MCP_DATA_DIR to it.")
        return 2

    if "annex" in wanted:
        doc = step("annex", lambda: refresh_annex(today, fetcher))
        if doc:
            write_atomic(data_dir / FILES["annex"], dump_json(doc, ("annex_i", "annex_ii")))
            log(f"annex_i.json: {doc['meta']['celex']}, {doc['meta']['annex_i_lines']} Annex I lines")
    if "values" in wanted:
        res = step("values", lambda: refresh_values(data_dir, today, fetcher, check_oj, excel_url, log))
        if res:
            doc, found_difference = res
            write_atomic(data_dir / FILES["values"], dump_json(doc, ("lines", "tables", "annex_iv")))
            m = doc["meta"]
            log(f"default_values.json: version {m['version']} of {m['version_date']}, {m['rows']} lines in {m['tables']} tables")
            if m.get("oj_check"):
                c = m["oj_check"]
                log(f"Official Journal check: {c['rows_identical']}/{c['rows_compared']} lines and "
                    f"{c['annex_iv_identical']}/{c['annex_iv_compared']} Annex IV lines identical")
    if "cn" in wanted:
        for year in CN_YEARS:
            doc = step(f"cn{year}", lambda y=year: refresh_cn(y, today, fetcher))
            if doc:
                write_atomic(data_dir / FILES[f"cn{year}"], dump_json(doc, ("concepts",)))
                log(f"cn_{year}.json: {doc['meta']['concepts']} concepts")
    # Informational: a failure here is reported but does not fail the refresh,
    # and the previous answer (with its own date) stays.
    acts_doc = load_json(data_dir / "later_acts.json")
    try:
        acts_doc = {"checked": today, "acts": later_acts(fetcher)}
        write_atomic(data_dir / "later_acts.json", json.dumps(acts_doc, indent=1) + "\n")
    except (FetchError, parsers.ParseError) as e:
        log(f"later-acts check not done ({e}); previous result kept")

    annex = load_json(data_dir / FILES["annex"])
    values = load_json(data_dir / FILES["values"])
    cn = {}
    for year in CN_YEARS:
        doc = load_json(data_dir / FILES[f"cn{year}"])
        if doc:
            cn[year] = doc
    write_atomic(data_dir / "SOURCES.md", render_sources(annex, values, cn, acts_doc, today))
    if failures:
        return 2
    return 1 if found_difference else 0
