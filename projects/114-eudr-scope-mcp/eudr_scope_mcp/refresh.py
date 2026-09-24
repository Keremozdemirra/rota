"""Rebuild the data snapshot from CELLAR (standard library only).

What it does, in order:

1. asks the SPARQL endpoint for the latest consolidated version of Regulation
   (EU) 2023/1115 and for every act that amends it;
2. reads Annex I, Articles 1, 2, 37 and 38 from the consolidated text;
3. applies amending acts that are not yet in the consolidated text, when they
   amend Annex I in the wording this parser understands; if one touches
   Article 37 or 38, the dates are marked unverified instead of guessed;
4. reads the history of Article 38 from the original act and each amendment;
5. reads the country list of Implementing Regulation (EU) 2025/1093 and maps
   its names to ISO codes through the EU 'Countries and territories' table;
6. writes the JSON files, manifest.json and SOURCES.md, all or nothing.

Any parse or network failure stops the run with exit code 2 and leaves the
previous snapshot untouched.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from . import __version__, annex, cellar, countries, legal, xhtml
from .lookup import attribution

BASE = "32023R1115"
COUNTRY_ACT = "32025R1093"
NAL = "http://publications.europa.eu/resource/authority/country"

_PREFIX = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""
_EN = "<http://publications.europa.eu/resource/authority/language/ENG>"


def q_work(celex: str) -> str:
    cellar.check_celex(celex)
    return _PREFIX + f"""SELECT ?p ?o WHERE {{
  ?w cdm:resource_legal_id_celex "{celex}"^^xsd:string .
  {{ ?w ?p ?o .
     VALUES ?p {{ cdm:resource_legal_in-force cdm:resource_legal_date_entry-into-force cdm:work_date_document
                 cdm:resource_legal_eli cdm:official-journal-act_date_publication }} }}
  UNION
  {{ ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language {_EN} ; cdm:expression_title ?o .
     BIND(cdm:expression_title AS ?p) }}
}}"""


def q_consolidated(celex: str) -> str:
    cellar.check_celex(celex)
    return _PREFIX + f"""SELECT DISTINCT ?celex ?date WHERE {{
  ?base cdm:resource_legal_id_celex "{celex}"^^xsd:string .
  ?cons cdm:act_consolidated_consolidates_resource_legal ?base ;
        cdm:resource_legal_id_celex ?celex ;
        cdm:act_consolidated_date ?date .
}} ORDER BY DESC(?date)"""


def q_related(celex: str) -> str:
    cellar.check_celex(celex)
    return _PREFIX + f"""SELECT DISTINCT ?rel ?celex ?date ?eif ?title ?adopted WHERE {{
  ?base cdm:resource_legal_id_celex "{celex}"^^xsd:string .
  {{ ?act cdm:resource_legal_amends_resource_legal ?base . BIND("amends" AS ?rel) }}
  UNION {{ ?act cdm:resource_legal_repeals_resource_legal ?base . BIND("repeals" AS ?rel) }}
  UNION {{ ?act cdm:resource_legal_implicitly_repeals_resource_legal ?base . BIND("repeals" AS ?rel) }}
  UNION {{ ?act cdm:resource_legal_proposes_to_amend_resource_legal ?base . BIND("proposes_to_amend" AS ?rel) }}
  ?act cdm:resource_legal_id_celex ?celex .
  OPTIONAL {{ ?act cdm:work_date_document ?date }}
  OPTIONAL {{ ?act cdm:resource_legal_date_entry-into-force ?eif }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?act ; cdm:expression_uses_language {_EN} ;
              cdm:expression_title ?title }}
  OPTIONAL {{ ?adopting cdm:resource_legal_adopts_resource_legal ?act ;
              cdm:resource_legal_id_celex ?adopted }}
}}"""


def q_corrigenda(celexes: list) -> str:
    values = " ".join(f'"{cellar.check_celex(c)}"^^xsd:string' for c in celexes)
    return _PREFIX + f"""SELECT DISTINCT ?target ?celex ?date ?lang WHERE {{
  VALUES ?target {{ {values} }}
  ?t cdm:resource_legal_id_celex ?target .
  ?c cdm:resource_legal_corrects_resource_legal ?t ; cdm:resource_legal_id_celex ?celex .
  OPTIONAL {{ ?c cdm:work_date_document ?date }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?c ; cdm:expression_uses_language ?lang }}
}}"""


Q_NAL = """PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX euvoc: <http://publications.europa.eu/ontology/euvoc#>
SELECT ?c ?a2 ?a3 ?pref ?status ?broader ?territory WHERE {
  GRAPH <http://publications.europa.eu/resource/authority/country> {
    ?c skos:notation ?n2 .
    FILTER(datatype(?n2) = euvoc:ISO_3166_1_ALPHA_2)
    OPTIONAL { ?c skos:notation ?n3 . FILTER(datatype(?n3) = euvoc:ISO_3166_1_ALPHA_3) }
    ?c skos:prefLabel ?pref . FILTER(lang(?pref) = "en")
    OPTIONAL { ?c euvoc:status ?status }
    OPTIONAL { ?c skos:broader ?broader }
    OPTIONAL { ?c skos:topConceptOf ?territory .
               FILTER(?territory = <http://publications.europa.eu/resource/authority/country/0003>) }
  }
  BIND(STR(?n2) AS ?a2) BIND(STR(?n3) AS ?a3)
} ORDER BY ?a2"""

Q_NAL_ALT = """PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX skosxl: <http://www.w3.org/2008/05/skos-xl#>
SELECT DISTINCT ?c ?alt WHERE {
  GRAPH <http://publications.europa.eu/resource/authority/country> {
    { ?c skos:altLabel ?alt } UNION { ?c skosxl:altLabel ?xl . ?xl skosxl:literalForm ?alt }
    FILTER(lang(?alt) = "en")
  }
}"""

Q_NAL_VERSION = """PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT ?v WHERE { <http://publications.europa.eu/resource/authority/country> owl:versionInfo ?v }"""


# The authority table has about 250 current countries and territories; far
# fewer means a truncated answer, not a smaller world. Tests lower it.
MIN_COUNTRIES = 200


class RefreshError(RuntimeError):
    pass


def _http_date(value) -> str | None:
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def _date(value: str) -> str:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", value or "")
    if not m:
        raise RefreshError(f"not a date: {str(value)[:30]!r}")
    return m.group(1)


def work_meta(celex: str) -> dict:
    rows = cellar.sparql(q_work(celex))
    if not rows:
        raise RefreshError(f"{celex}: CELLAR returned no metadata")
    meta = {"celex": celex, "in_force": None, "entry_into_force": [], "date": None, "eli": None,
            "published": None, "title": None}
    for r in rows:
        p, o = r.get("p", ""), r.get("o", "")
        if p.endswith("#resource_legal_in-force"):
            meta["in_force"] = o in ("1", "true")
        elif p.endswith("#resource_legal_date_entry-into-force"):
            meta["entry_into_force"].append(_date(o))
        elif p.endswith("#work_date_document"):
            meta["date"] = _date(o)
        elif p.endswith("#resource_legal_eli") and o.startswith("http://data.europa.eu/eli/"):
            meta["eli"] = o
        elif p.endswith("#official-journal-act_date_publication"):
            meta["published"] = _date(o)
        elif p.endswith("#expression_title"):
            meta["title"] = xhtml.clean(o)[:600]
    meta["entry_into_force"] = sorted(set(meta["entry_into_force"]))
    return meta


def related(celex: str) -> list:
    out: dict = {}
    for r in cellar.sparql(q_related(celex)):
        c = r.get("celex", "")
        if not cellar.CELEX.match(c):
            continue
        key = (r["rel"], c)
        item = out.setdefault(key, {"rel": r["rel"], "celex": c, "date": None, "entry_into_force": [], "title": None,
                                    "adopted_as": None})
        if r.get("adopted") and cellar.CELEX.match(r["adopted"]):
            item["adopted_as"] = r["adopted"]
        if r.get("date"):
            item["date"] = _date(r["date"])
        if r.get("eif"):
            d = _date(r["eif"])
            if d not in item["entry_into_force"]:
                item["entry_into_force"].append(d)
        if r.get("title"):
            item["title"] = xhtml.clean(r["title"])[:600]
    items = sorted(out.values(), key=lambda x: (x["date"] or "", x["celex"]))
    for i in items:
        i["entry_into_force"].sort()
    return items


def consolidated(celex: str) -> list:
    rows = cellar.sparql(q_consolidated(celex))
    out = []
    prefix = "0" + celex[1:] + "-"
    for r in rows:
        c = r.get("celex", "")
        if c.startswith(prefix) and cellar.CELEX.match(c):
            out.append((c, _date(r["date"])))
    return sorted(set(out), key=lambda x: x[1], reverse=True)


def corrigenda(celexes: list) -> list:
    """Corrigenda of the given acts, with the languages they exist in."""
    out: dict = {}
    for r in cellar.sparql(q_corrigenda(celexes)):
        c = r.get("celex", "")
        if not cellar.CELEX.match(c):
            continue
        item = out.setdefault(c, {"celex": c, "corrects": r.get("target"), "date": None, "english": False})
        if r.get("date"):
            item["date"] = _date(r["date"])
        if r.get("lang", "").endswith("/ENG"):
            item["english"] = True
    return sorted(out.values(), key=lambda x: (x["date"] or "", x["celex"]))


def _doc(celex: str, role: str, documents: list):
    record = cellar.xhtml(celex)
    documents.append({k: record.get(k) for k in ("celex", "url", "final_url", "sha256", "bytes", "content_type",
                                                  "etag", "last_modified")} | {"role": role})
    root = xhtml.parse(cellar.text_of(record))
    return root


def build(today: str | None = None, log=lambda msg: None) -> dict:
    """Everything the snapshot contains, built in memory. Raises on any failure."""
    today = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
    documents: list = []

    log("SPARQL: Regulation (EU) 2023/1115 and its consolidated versions")
    base = work_meta(BASE)
    if base["in_force"] is not True:
        raise RefreshError(f"{BASE} is not recorded as in force")
    # A consolidation dated after today describes the text as it will read
    # later; the base must be the text in force now.
    versions = [v for v in consolidated(BASE) if v[1] <= today]
    if not versions:
        raise RefreshError(f"no consolidated version of {BASE} dated on or before {today} in CELLAR")
    cons_celex, cons_date = versions[0]

    log(f"XHTML: consolidated text {cons_celex}")
    root = _doc(cons_celex, "consolidated text", documents)
    head = " ".join(root.lines()[:60])
    ref = re.search(r"0\d{4}R\d{4} " + chr(0x2014) + r" EN " + chr(0x2014) + r" [\d.]+ " + chr(0x2014) + r" [\d.]+", head)
    if not ref:
        raise RefreshError(f"{cons_celex}: no English consolidated-text reference line")
    if "has no legal effect" not in head:
        raise RefreshError(f"{cons_celex}: consolidated-text disclaimer not found")
    in_text = annex.amended_by(root)
    table = annex.parse_consolidated_annex(root)
    a38_paras = legal.paragraphs(legal.article_lines(root, "38"))
    a38 = legal.read_article_38(a38_paras)
    a37_paras = legal.paragraphs(legal.article_lines(root, "37"))
    a37 = legal.read_article_37(a37_paras)
    a1 = legal.paragraphs(legal.article_lines(root, "1"))
    defs = legal.definitions(legal.article_lines(root, "2"))
    published = legal.oj_publication(head)
    if not published:
        raise RefreshError(f"{cons_celex}: OJ reference of the basic act not found")
    eif_base = legal.entry_into_force(a38["entry_into_force_rule"], published)

    entries = []
    for i, e in enumerate(table["entries"], start=1):
        # A later consolidation will carry "(This provision shall apply from ...)"
        # inside the entry; that date, not the consolidation, is when it applies.
        valid_from = e.pop("applies_from", None)
        entries.append({"id": f"B{i:02d}", **e, "valid_from": valid_from, "valid_to": None,
                        "source": {"celex": cons_celex, "provision": "Annex I"}})

    log("SPARQL: acts that amend, correct or propose to amend 2023/1115")
    rel = related(BASE)
    amending = [r for r in rel if r["rel"] == "amends"]
    status, reasons, warnings = "verified", [], []
    annex_status, annex_reasons = "verified", []
    applied, notes, unconsolidated = [], [], []

    log("XHTML: original act (Article 38 history)")
    orig = _doc(BASE, "original act (Article 38 history)", documents)
    orig38 = legal.read_article_38(legal.paragraphs(legal.article_lines(orig, "38")))
    history = [{"celex": BASE, "provision": "Article 38 (original text)", "published": published,
                "p2_date": orig38["p2_date"], "p3_date": orig38["p3_date"],
                "p3_established_by": orig38["p3_established_by"]}]

    for act in amending:
        log(f"XHTML: amending act {act['celex']}")
        act_root = _doc(act["celex"], "amending act", documents)
        pub = legal.oj_header_date(act_root)
        rule = legal.act_entry_into_force_rule(act_root)
        if not pub or not rule:
            raise RefreshError(f"{act['celex']}: publication date or entry-into-force clause not found")
        eif = legal.entry_into_force(rule, pub)
        if act["entry_into_force"] and eif not in act["entry_into_force"]:
            raise RefreshError(f"{act['celex']}: entry into force read from the text ({eif}) is not in CELLAR's "
                               f"metadata ({', '.join(act['entry_into_force'])})")
        act.update({"published": pub, "entry_into_force_text": eif, "touches": legal.touched_provisions(act_root)})
        replaced = legal.replacement_of_article_38(act_root)
        if replaced:
            dates = legal.read_article_38({"1": a38_paras["1"], **replaced["paragraphs"]})
            history.append({"celex": act["celex"], "provision": f"Article 1, point {replaced['point']}",
                            "published": pub, "entry_into_force": eif, "p2_date": dates["p2_date"],
                            "p3_date": dates["p3_date"], "p3_established_by": dates["p3_established_by"]})
        if act["celex"] in in_text:
            continue
        # Not yet in the consolidated text: apply what we can read, flag the rest.
        unconsolidated.append({"celex": act["celex"], "title": act["title"], "published": pub,
                               "entry_into_force": eif, "touches": act["touches"]})
        if not act["touches"]:
            status, annex_status = "unverified", "unverified"
            reasons.append(f"{act['celex']} amends the Regulation after the consolidated version and its changes "
                           "could not be identified")
            annex_reasons.append(reasons[-1])
            continue
        if "Annex I" in act["touches"]:
            ops = annex.parse_instructions(annex.amendment_points(act_root))
            if not ops:
                raise RefreshError(f"{act['celex']}: says it amends Annex I but no instructions were found")
            entries, new_notes, oplog = annex.apply_instructions(
                entries, ops, {"celex": act["celex"], "title": act["title"]}, eif)
            notes.extend(new_notes)
            applied.append({"celex": act["celex"], "title": act["title"], "published": pub,
                            "entry_into_force": eif, "operations": len(ops), "log": oplog})
        for art in ("Article 37", "Article 38"):
            if art in act["touches"]:
                status = "unverified"
                reasons.append(f"{art} is amended by {act['celex']}, which is not yet in the consolidated text")
        if "Article 2" in act["touches"]:
            warnings.append(f"Article 2 definitions are amended by {act['celex']}; quoted definitions may be outdated")

    # The dates read from the text must be the ones CELLAR records for the act.
    cellar_dates = set(base["entry_into_force"])
    for label, d in (("Article 38(1)", eif_base), ("Article 38(2)", a38["p2_date"]), ("Article 38(3)", a38["p3_date"])):
        if d not in cellar_dates:
            status = "unverified"
            reasons.append(f"{label}: {d} read from the consolidated text is not among CELLAR's dates for "
                           f"{BASE} ({', '.join(sorted(cellar_dates))})")
    last = history[-1]
    if (last["p2_date"], last["p3_date"]) != (a38["p2_date"], a38["p3_date"]):
        status = "unverified"
        reasons.append("the last act that replaced Article 38 does not state the dates in the consolidated text")

    # Corrigenda of every act this snapshot rests on. Only English ones change
    # the text read here; one the consolidated text may not include, or one of
    # an act applied by this tool, means the result can no longer be vouched for.
    log("SPARQL: corrigenda of 2023/1115 and of every amending act")
    corr = corrigenda([BASE] + [a["celex"] for a in amending])
    cons_doc = next(d for d in documents if d["role"] == "consolidated text")
    cons_seen = _http_date(cons_doc.get("last_modified")) or cons_date
    applied_celex = {a["celex"] for a in applied}
    for c in corr:
        if not c["english"]:
            continue
        if c["corrects"] in applied_celex:
            annex_status = "unverified"
            annex_reasons.append(f"{c['celex']} corrects {c['corrects']} in English; this tool applies "
                                 f"{c['corrects']} and does not apply corrigenda")
        elif (c["date"] or "9999") > cons_seen:
            status = annex_status = "unverified"
            reasons.append(f"{c['celex']} corrects {c['corrects']} in English after the consolidated text "
                           f"was last updated ({cons_seen})")
            annex_reasons.append(reasons[-1])
    # A proposal is pending until CELLAR records an act that adopts it.
    proposals = [r for r in rel if r["rel"] == "proposes_to_amend"]
    pending = [p for p in proposals if not p.get("adopted_as")]

    log("SPARQL + XHTML: Implementing Regulation (EU) 2025/1093 (country list)")
    cmeta = work_meta(COUNTRY_ACT)
    crel = related(COUNTRY_ACT)
    cversions = [v for v in consolidated(COUNTRY_ACT) if v[1] <= today]
    c_status, c_reasons = "verified", []
    if cmeta["in_force"] is not True:
        c_status, c_reasons = "unverified", [f"{COUNTRY_ACT} is not recorded as in force"]
    changes = [r for r in crel if r["rel"] in ("amends", "repeals")]
    c_corr = [c for c in corrigenda([COUNTRY_ACT]) if c["english"]]
    source_celex = COUNTRY_ACT
    if changes or c_corr:
        if cversions and cversions[0][1] >= max((r["date"] or "") for r in changes + c_corr):
            source_celex = cversions[0][0]
        else:
            c_status = "unverified"
            c_reasons.append("the country list has been amended, repealed or corrected in English and no "
                             "consolidated version covers it: " + ", ".join(r["celex"] for r in changes + c_corr))
    croot = _doc(source_celex, "country list", documents)
    cannex = countries.parse_annex(croot)
    art1 = legal.paragraphs(legal.article_lines(croot, "1"))
    pub_c = legal.oj_header_date(croot) if source_celex == COUNTRY_ACT else cmeta["published"]
    rule_c = legal.act_entry_into_force_rule(croot)
    eif_c = legal.entry_into_force(rule_c, pub_c) if (rule_c and pub_c) else None
    if eif_c and cmeta["entry_into_force"] and eif_c not in cmeta["entry_into_force"]:
        c_status = "unverified"
        c_reasons.append(f"entry into force read from the text ({eif_c}) differs from CELLAR's metadata")

    log("SPARQL: EU 'Countries and territories' authority table")
    nal_rows = cellar.sparql(Q_NAL)
    nal_alt = cellar.sparql(Q_NAL_ALT)
    nal_version = next((r["v"] for r in cellar.sparql(Q_NAL_VERSION) if r.get("v")), None)
    country_list = countries.build_countries(nal_rows, nal_alt)
    if len(country_list) < MIN_COUNTRIES:
        raise RefreshError(f"authority table returned only {len(country_list)} countries")
    by_iso3 = {c["iso3"]: c for c in country_list}

    def classify(names):
        return [{"annex_name": n, "iso2": by_iso3[iso3]["iso2"], "iso3": iso3, "matched_by": how}
                for n, iso3, how in countries.map_annex_names(names, country_list)]

    low, high = classify(cannex["low"]), classify(cannex["high"])
    if {x["iso3"] for x in low} & {x["iso3"] for x in high}:
        raise RefreshError("a country is listed as both low and high risk")

    consolidated_info = {"celex": cons_celex, "date": cons_date, "reference": ref.group(0),
                         "amended_by": in_text, "url": cellar.resource_url(cons_celex),
                         "disclaimer": "This text is meant purely as a documentation tool and has no legal effect."}
    deferred: dict = {}
    for e in entries:
        if e["valid_from"] and e["valid_from"] > today:
            deferred.setdefault(e["valid_from"], []).append(e["label"])
    set_by = next((h for h in reversed(history)
                   if (h["p2_date"], h["p3_date"]) == (a38["p2_date"], a38["p3_date"])), None)

    return {
        "retrieved": today,
        "annex_i": {
            "dataset": "Annex I to Regulation (EU) 2023/1115: relevant commodities and relevant products",
            "retrieved": today, "status": annex_status, "status_reasons": annex_reasons,
            "consolidated": consolidated_info, "amendments_applied": applied,
            "intro": table["intro"], "table_notes": notes, "entries": entries,
        },
        "application_dates": {
            "dataset": "Dates of application of Regulation (EU) 2023/1115",
            "retrieved": today, "status": status, "status_reasons": reasons, "warnings": warnings,
            "consolidated": consolidated_info,
            "basic_act": {"celex": BASE, "title": base["title"], "published": published, "eli": base["eli"],
                          "cellar_entry_into_force_dates": base["entry_into_force"]},
            "article_38": {"paragraphs": a38_paras, "entry_into_force": eif_base, **a38,
                           "set_by": set_by and {"celex": set_by["celex"], "provision": set_by["provision"]}},
            "article_37": {"paragraphs": a37_paras, **a37},
            "article_1_2": a1.get("2"),
            "definitions": {k: defs[k] for k in ("15", "15a", "15b", "17", "30") if k in defs},
            "history": history,
            "annex_i_deferred": [{"applies_from": d, "entries": labels} for d, labels in sorted(deferred.items())],
            "unconsolidated_amendments": unconsolidated,
            "amending_acts": [{k: a.get(k) for k in ("celex", "title", "date", "published", "entry_into_force_text",
                                                     "touches")} for a in amending],
            "corrigenda": corr, "proposals": proposals, "pending_proposals": pending,
        },
        "country_risk": {
            "dataset": "Country classification under Article 29 of Regulation (EU) 2023/1115",
            "retrieved": today, "status": c_status, "status_reasons": c_reasons,
            "corrigenda_in_english": c_corr,
            "act": {"celex": COUNTRY_ACT, "title": cmeta["title"], "date": cmeta["date"], "published": pub_c,
                    "entry_into_force": eif_c, "eli": cmeta["eli"], "source_text": source_celex,
                    "url": cellar.resource_url(source_celex), "related": crel,
                    "consolidated_versions": [c for c, _ in cversions]},
            "article_1": art1, "annex_heading": cannex["heading"],
            "low": low if c_status == "verified" else [],
            "high": high if c_status == "verified" else [],
        },
        "countries": {
            "dataset": "EU 'Countries and territories' authority table (ISO 3166-1 codes, English labels)",
            "retrieved": today, "authority_table": NAL, "version": nal_version,
            "countries": country_list,
        },
        "documents": documents,
    }


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def write(result: dict, out_dir: Path) -> dict:
    """Write every file to a temporary name first, then move them all in."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {name: _dump(result[key]) for name, key in (
        ("annex_i.json", "annex_i"), ("application_dates.json", "application_dates"),
        ("country_risk.json", "country_risk"), ("countries.json", "countries"))}
    manifest = {
        "tool": "eudr-scope-mcp", "tool_version": __version__, "retrieved": result["retrieved"],
        "sparql_endpoint": cellar.SPARQL, "documents": result["documents"],
        "files": {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in files.items()},
        "counts": _counts(result),
    }
    files["manifest.json"] = _dump(manifest)
    files["SOURCES.md"] = sources_md(result, manifest)
    staged = []
    try:
        for name, text in files.items():
            fd, tmp = tempfile.mkstemp(prefix=f".{name}.", dir=out_dir)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            os.chmod(tmp, 0o644)  # mkstemp creates 0600; the snapshot is meant to be read by anyone
            staged.append((tmp, out_dir / name))
        for tmp, final in staged:
            os.replace(tmp, final)
    finally:
        for tmp, _ in staged:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return manifest


def _counts(result: dict) -> dict:
    entries = result["annex_i"]["entries"]
    today = result["retrieved"]
    live = [e for e in entries if (e["valid_from"] or "") <= today and (e["valid_to"] is None or e["valid_to"] >= today)]
    return {
        "annex_i_entries_total": len(entries),
        "annex_i_entries_in_force_on_retrieval": len(live),
        "annex_i_entries_later": sum(1 for e in entries if (e["valid_from"] or "") > today),
        "annex_i_entries_removed": sum(1 for e in entries if e["valid_to"] is not None),
        "table_notes": len(result["annex_i"]["table_notes"]),
        "low_risk_countries": len(result["country_risk"]["low"]),
        "high_risk_countries": len(result["country_risk"]["high"]),
        "authority_table_countries": len(result["countries"]["countries"]),
    }


def sources_md(result: dict, manifest: dict) -> str:
    a, d, c = result["annex_i"], result["application_dates"], result["country_risk"]
    cons = a["consolidated"]
    counts = manifest["counts"]
    lines = [
        "# Data sources",
        "",
        f"Snapshot retrieved {result['retrieved']} by `eudr-scope-mcp refresh` (version {__version__}).",
        "Regenerate with `python -m eudr_scope_mcp refresh --out data`.",
        "",
        "## Legal acts",
        "",
        "| CELEX | Act | Used for | Status |",
        "| --- | --- | --- | --- |",
        f"| {cons['celex']} | Consolidated text of Regulation (EU) 2023/1115 ({cons['reference']}) | Annex I, "
        f"Articles 1, 2, 37, 38 | {a['status']} |",
        f"| {BASE} | Regulation (EU) 2023/1115, original text (OJ of {d['basic_act']['published']}) | Article 38 history | read |",
    ]
    for act in d["amending_acts"]:
        used = "applied to Annex I (not yet consolidated)" if any(x["celex"] == act["celex"] for x in a["amendments_applied"]) \
            else "in the consolidated text; Article 38 history"
        lines.append(f"| {act['celex']} | {act['title']} (in force {act['entry_into_force_text']}) | {used} | read |")
    lines.append(f"| {c['act']['celex']} | {c['act']['title']} (in force {c['act']['entry_into_force']}) | "
                 f"country classification | {c['status']} |")
    lines += [
        "",
        "Every date in `application_dates.json` is read from the article text and checked against CELLAR's",
        "`resource_legal_date_entry-into-force` metadata for the act.",
        "",
        "## Raw files",
        "",
        "| Role | CELEX | URL | SHA-256 | Bytes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for doc in manifest["documents"]:
        lines.append(f"| {doc['role']} | {doc['celex']} | {doc['final_url']} | `{doc['sha256']}` | {doc['bytes']} |")
    lines += [
        "",
        f"Country names are matched to ISO 3166-1 codes through the EU authority table {NAL}",
        f"(version {result['countries']['version']}), queried at {cellar.SPARQL}.",
        "",
        "## Row counts",
        "",
    ]
    lines += [f"- {k.replace('_', ' ')}: {v}" for k, v in counts.items()]
    lines += ["", "## Corrigenda and proposals", ""]
    for corr in d["corrigenda"]:
        lines.append(f"- {corr['celex']} ({corr['date']}) corrects {corr['corrects']}: "
                     + ("has an English version" if corr["english"] else "no English version, so the English text is unaffected"))
    for prop in d["proposals"]:
        lines.append(f"- {prop['celex']} ({prop['date']}): " + (f"adopted as {prop['adopted_as']}" if prop["adopted_as"]
                     else "pending (no adopting act in CELLAR), not law and not applied") + f": {prop['title']}")
    fixes = [x for x in c["low"] + c["high"] if x["matched_by"].startswith("fixed")]
    moved = [x for x in c["low"] + c["high"] if "qualifier" in x["matched_by"]]
    lines += [
        "",
        "## Choices made by this tool",
        "",
        "- Annex I is the consolidated text plus the amending acts listed as applied above, applied by",
        "  `eudr_scope_mcp/annex.py`. The result is derived; it is not an official consolidated version.",
        "- Names written 'Name (qualifier)' in the Annex are matched with the qualifier moved to the front: "
        + (", ".join(f"{x['annex_name']} = {x['iso3']}" for x in moved) or "none") + ".",
        "- " + (", ".join(f"'{x['annex_name']}' is read as {x['iso3']}" for x in fixes) or "No fixed mappings")
        + " (the Annex spells the name that way; no other country matches).",
        "- Entries of the authority table recorded as part of another country (skos:broader) are reported",
        "  as not determined when the Annex does not name them.",
        "",
        "## Licence and attribution",
        "",
        "EUR-Lex legal notice, https://eur-lex.europa.eu/content/legal-notice/legal-notice.html. From this sandbox",
        "eur-lex.europa.eu answered HTTP 202 with an empty body and web.archive.org reset the connection on",
        "2026-09-24, so the sentences below are quoted from the archived copy of 2026-09-22",
        "(https://web.archive.org/web/20260922160312/https://eur-lex.europa.eu/content/legal-notice/legal-notice.html)",
        "as given in this project's build notes, not re-read by this tool:",
        "",
        "- 'Unless otherwise specified, you can re-use the legal documents published in EUR-Lex for commercial or",
        "  non-commercial purposes.'",
        "- Creative Commons Attribution 4.0 covers 'the editorial content of this website, the summaries of EU",
        "  legislation and the consolidated texts'.",
        "",
        "Commission Decision 2011/833/EU on the reuse of Commission documents (http://data.europa.eu/eli/dec/2011/833/oj),",
        "read from CELLAR on 2026-09-24: Article 4, 'All documents shall be available for reuse: (a) for commercial or",
        "non-commercial purposes under the conditions laid down in Article 6'; Article 6(2) conditions may include",
        "'(a) the obligation for the reuser to acknowledge the source of the documents; (b) the obligation not to",
        "distort the original meaning or message of the documents'.",
        "",
        "| Data | Basis |",
        "| --- | --- |",
        f"| Consolidated text {cons['celex']} (Annex I base, Articles 1, 2, 37, 38) | CC BY 4.0 (EUR-Lex legal notice, consolidated texts); changes indicated: Annex I is derived |",
        "| Regulations (EU) 2023/1115, 2024/3234, 2025/2650 as published in the OJ (European Parliament and Council) | EUR-Lex legal notice, re-use of legal documents published in EUR-Lex |",
        f"| Commission acts as published in the OJ ({', '.join(x['celex'] for x in a['amendments_applied'])}, {c['act']['celex']}) | EUR-Lex legal notice, plus Decision 2011/833/EU Articles 4 and 6(2) |",
        "| CELLAR metadata (SPARQL) and the 'Countries and territories' authority table | Commission reuse notice, Decision 2011/833/EU, per https://data.europa.eu/data/datasets/sparql-cellar-of-the-publications-office and https://data.europa.eu/data/datasets/country |",
        "",
        "Attribution lines carried by the answers:",
        "",
        f"- scope and commodity answers: {attribution(result['retrieved'], 'annex', bool(a['amendments_applied']))}",
        f"- date answers: {attribution(result['retrieved'], 'dates')}",
        f"- country answers: {attribution(result['retrieved'], 'country', table_version=result['countries']['version'])}",
        "",
        "Only the texts published in the Official Journal of the European Union are authentic. The consolidated",
        "text says of itself: 'This text is meant purely as a documentation tool and has no legal effect.'",
        "",
    ]
    return "\n".join(lines)


def run(out_dir: str, today: str | None = None, dry_run: bool = False, log=print) -> int:
    try:
        result = build(today=today, log=log)
    except (cellar.FetchError, RefreshError, annex.AnnexError, legal.LegalTextError, countries.CountryError) as e:
        log(f"refresh failed, nothing written: {e}")
        return 2
    counts = _counts(result)
    for k, v in counts.items():
        log(f"  {k.replace('_', ' ')}: {v}")
    for key in ("annex_i", "application_dates", "country_risk"):
        part = result[key]
        log(f"  {key}: {part['status']}" + ("" if not part["status_reasons"] else " - " + "; ".join(part["status_reasons"])))
    unverified = any(result[k]["status"] != "verified" for k in ("annex_i", "application_dates", "country_risk"))
    if dry_run:
        log("dry run: nothing written")
        return 1 if unverified else 0
    manifest = write(result, Path(out_dir))
    log(f"wrote {len(manifest['files']) + 2} files to {out_dir}")
    # 1: written, but some answers will say "unverified" until the texts are reviewed.
    return 1 if unverified else 0
