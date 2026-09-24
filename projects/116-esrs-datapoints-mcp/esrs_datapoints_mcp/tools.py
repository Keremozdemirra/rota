"""The six questions the server and the CLI answer, over the indexed workbooks.

Every answer carries a `source` block: which file version it came from, that the
content is EFRAG's and was read from the user's own copy, and which legal act
holds the binding text. Workbook strings are shown through text.py: identifiers
as they are, everything else wrapped as remote text.
"""
from __future__ import annotations

import difflib
import os

from . import sources
from .parse import STANDARDS, standard_code, subject_to_phase_in
from .store import ENV_FILES, Store, env_paths
from .text import clean, data_type, fold, ident, reference, remote
from .text import dr_code as show_dr

MAX_LIMIT = 200
# Name-similarity pairing threshold for diff_versions: this tool's choice, not a
# standard. At 0.85 a pair differs by a few words at most.
DEFAULT_MIN_SIMILARITY = 0.85


class ToolError(Exception):
    """A request the tool cannot answer; the message says what to do."""


# ------------------------------------------------------------------ helpers

def _version_view(ix: dict) -> dict:
    return {"version": ix["key"], "title": ix["title"], "list_date": ix.get("list_date"),
            "file": clean(ix["file"]["name"], 300), "sha256": ix["file"]["sha256"],
            "official_file": bool(ix.get("official"))}


def source_block(indexes: list) -> dict:
    acts = []
    for layout in sorted({ix["layout"] for ix in indexes}):
        act = sources.binding_act(layout)
        if act and act not in acts:
            acts.append(act)
    return {
        "versions": [_version_view(ix) for ix in indexes],
        "content": ("Datapoint content is EFRAG's (c) EFRAG" + (
            "" if all(ix.get("official") for ix in indexes) else " where the file is EFRAG's workbook")
            + ", read from your own copy of the workbook on this machine. This tool does not distribute it and "
              "is not affiliated with EFRAG."),
        "status": ("EFRAG describes these lists as non-authoritative support material. The binding text is the "
                   "act below. Information, not legal advice."),
        "binding_text": acts or [sources.binding_act("revised")],
    }


def present(dp: dict, ix: dict, brief: bool = False) -> dict:
    out = {"id": ident(dp["id"]), "version": ix["key"], "standard": dp.get("standard"),
           "dr": show_dr(dp.get("dr")), "paragraph": reference(dp.get("paragraph")),
           "name": remote(dp.get("name")), "data_type": data_type(dp.get("data_type")),
           "voluntary": dp.get("voluntary"), "phase_in": subject_to_phase_in(dp),
           "conditional": dp.get("conditional")}
    if brief:
        return {k: v for k, v in out.items() if v is not None}
    out["related_guidance"] = reference(dp.get("related"))
    if dp.get("phase_in"):
        out["phase_in_detail"] = {k: remote(v) for k, v in dp["phase_in"].items()}
    if dp.get("eu_legislation"):
        out["eu_legislation"] = dp["eu_legislation"]
    for field, key in (("eu_legislation_other", "eu_legislation_other"), ("disaggregations", "disaggregations"),
                       ("section_note", "applies_when"), ("voluntary_raw", "voluntary_raw"),
                       ("conditional_raw", "conditional_raw")):
        if dp.get(field):
            out[key] = remote(dp[field])
    if dp.get("condition_ref"):
        out["condition_defined_in"] = reference(dp["condition_ref"])
    if dp.get("ig3_mapping"):
        out["ig3_mapping"] = [ident(i) for i in dp["ig3_mapping"]]
    if dp.get("ig3_reference"):
        ref = dp["ig3_reference"]
        out["ig3_reference"] = {"standard": standard_code(ref.get("standard")) or remote(ref.get("standard")),
                                "dr": show_dr(ref.get("dr")), "paragraph": reference(ref.get("paragraph")),
                                "related_guidance": reference(ref.get("related"))}
    out["sheet"] = remote(dp.get("sheet")) if dp.get("sheet") else None
    out["row"] = dp.get("row")
    return {k: v for k, v in out.items() if v is not None}


def _norm_standard(value):
    if value is None or value == "":
        return None
    code = standard_code(value)
    if not code:
        raise ToolError(f"unknown standard {clean(value, 40)!r}; use one of: {', '.join(STANDARDS)}")
    return code


def _norm_code(value) -> str:
    return "".join(clean(value, 120).split()).casefold()


def _dr_matches(dp_dr: str, wanted: str) -> bool:
    d = _norm_code(dp_dr)
    return bool(d) and (d == wanted or d.endswith("." + wanted))


def _limit(value, default=25) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LIMIT:
        raise ToolError(f"limit must be an integer from 1 to {MAX_LIMIT}")
    return value


def _terms(text: str):
    """(code terms, word terms): 'E1-6' style tokens match IDs and DR codes, words match names."""
    codes, words = [], []
    for raw in clean(text, 300).split():
        if any(ch.isdigit() for ch in raw) and any(ch in "-_." for ch in raw.strip("-_.")):
            codes.append(raw.strip(".,;").casefold())
        else:
            words.extend(fold(raw).split())
    return codes, words


def _word_hit(term: str, tokens: list) -> bool:
    if term.isdigit() or len(term) < 3:
        return term in tokens
    return any(t == term or t.startswith(term) for t in tokens)


# ------------------------------------------------------------------ service

class Service:
    def __init__(self, store=None, env_value=None):
        self.store = store or Store()
        self.env_value = env_value
        self._indexes = None
        self._stamp = None

    def indexes(self) -> list:
        stamp = self.store.stamp()
        if self._indexes is None or stamp != self._stamp:
            self._indexes = self.store.load(self.env_value)
            self._stamp = self.store.stamp()
        return self._indexes

    def _require(self) -> list:
        ixs = self.indexes()
        if not ixs:
            problems = "; ".join(f"{p['path']}: {p['error']}" for p in self.store.problems)
            pages = "; ".join(p["page"] for p in sources.download_pages())
            raise ToolError(
                "No ESRS datapoint workbook is indexed on this machine. Download the official Excel file from "
                f"EFRAG ({pages}), then set {ENV_FILES} to its path or run: esrs-datapoints-mcp index PATH."
                + (f" Problems: {problems}" if problems else ""))
        return ixs

    def select(self, version=None) -> list:
        """The indexes a query runs over: one named version, or one file per list (mapping variant preferred)."""
        ixs = self._require()
        if version not in (None, "", "all"):
            hit = [ix for ix in ixs if ix["key"] == version]
            if not hit:
                raise ToolError(f"unknown version {clean(version, 80)!r}; indexed: "
                                + ", ".join(ix["key"] for ix in ixs))
            return hit
        if version == "all":
            return ixs
        best = {}
        for ix in ixs:
            group = (ix["layout"], ix.get("list_date") or ix["key"])
            cur = best.get(group)
            if cur is None or (ix.get("variant") == "mapping" and cur.get("variant") != "mapping"):
                best[group] = ix
        return [ix for ix in ixs if ix in best.values()]

    # -------------------------------------------------------------- tools

    def index_status(self) -> dict:
        ixs = self.indexes()
        indexed = []
        for ix in ixs:
            counts = {}
            for dp in ix["datapoints"]:
                counts[dp.get("standard") or "unknown"] = counts.get(dp.get("standard") or "unknown", 0) + 1
            indexed.append({
                **_version_view(ix), "layout": ix["layout"], "variant": ix.get("variant"),
                "path": clean(ix["file"]["path"], 1000), "source_file_present": ix.get("source_present", True),
                "origin": ix.get("origin"), "parsed_at": ix.get("parsed_at"),
                "datapoints": len(ix["datapoints"]), "by_standard": counts,
                "columns_missing": ix.get("columns_missing", []), "phase_in_columns": ix.get("phase_in_columns", []),
                "skipped_sheets": [{"sheet": remote(s["sheet"]), "reason": s["reason"]}
                                   for s in ix.get("skipped_sheets", [])],
                "rows_without_id": ix.get("rows_without_id", 0), "duplicate_ids": len(ix.get("duplicate_ids", [])),
            })
        return {
            "indexed": indexed,
            "problems": [{"path": clean(p["path"], 1000), "error": clean(p["error"], 1000)}
                         for p in self.store.problems],
            "cache_dir": str(self.store.dir),
            "env": {ENV_FILES: env_paths(self.env_value) or None},
            "supported_files": [{k: f.get(k) for k in ("title", "layout", "variant", "list_date", "page", "url",
                                                       "sha256", "checked")} for f in sources.OFFICIAL_FILES],
            "how_to_index": (f"Download a workbook from EFRAG, then set {ENV_FILES} to its path (several paths "
                             f"separated by {os.pathsep!r}) or run: esrs-datapoints-mcp index PATH"),
            "source": source_block(ixs),
        }

    def search(self, text="", standard=None, disclosure_requirement=None, data_type=None, voluntary=None,
               phase_in=None, version=None, limit=25) -> dict:
        limit = _limit(limit)
        std = _norm_standard(standard)
        dr = _norm_code(disclosure_requirement) if disclosure_requirement else None
        dtype = fold(data_type) if data_type else None
        for name, value in (("voluntary", voluntary), ("phase_in", phase_in)):
            if value is not None and not isinstance(value, bool):
                raise ToolError(f"{name} must be true or false")
        codes, words = _terms(text or "")
        if not (codes or words or std or dr or dtype or voluntary is not None or phase_in is not None):
            raise ToolError("give search text or at least one filter (standard, disclosure_requirement, "
                            "data_type, voluntary, phase_in)")
        phrase = " ".join(words)
        ixs = self.select(version)
        hits, notes = [], []
        for ix in ixs:
            if voluntary is not None and "voluntary" in ix.get("columns_missing", []):
                notes.append(f"{ix['key']} has no voluntary ('May [V]') column, so the voluntary filter "
                             "leaves its datapoints out")
                continue
            if phase_in is not None and "phase_in" in ix.get("columns_missing", []):
                notes.append(f"{ix['key']} has no phase-in column, so the phase_in filter leaves its datapoints out")
                continue
            for order, dp in enumerate(ix["datapoints"]):
                if std and dp.get("standard") != std:
                    continue
                if dr and not _dr_matches(dp.get("dr", ""), dr):
                    continue
                if dtype and dtype not in fold(dp.get("data_type", "")):
                    continue
                if voluntary is not None and dp.get("voluntary") is not voluntary:
                    continue
                if phase_in is not None and subject_to_phase_in(dp) is not phase_in:
                    continue
                idc, drc = dp["id"].casefold(), _norm_code(dp.get("dr", ""))
                if any(not (c == idc or c == drc or idc.startswith(c + "_") or drc.endswith("." + c))
                       for c in codes):
                    continue
                name = fold(dp.get("name", "")) + " " + fold(dp.get("disaggregations", ""))
                tokens = name.split()
                if not all(_word_hit(w, tokens) for w in words):
                    continue
                exact = sum(1 for w in words if w in tokens)
                hits.append(((-(phrase in name) if phrase else 0), -exact, ixs.index(ix), order, dp, ix))
        hits.sort(key=lambda h: h[:4])
        return {
            "query": {"text": clean(text or "", 300), "standard": std, "disclosure_requirement": dr and clean(
                disclosure_requirement, 60), "data_type": dtype, "voluntary": voluntary, "phase_in": phase_in,
                "version": version or "one file per list"},
            "matches": len(hits), "returned": min(limit, len(hits)),
            "datapoints": [present(dp, ix, brief=True) for *_k, dp, ix in hits[:limit]],
            "notes": notes,
            "source": source_block(ixs),
        }

    def datapoint(self, id, version=None) -> dict:
        want = clean(id, 120)
        if not want:
            raise ToolError("give a datapoint ID, e.g. E1-6_04")
        ixs = self.select(version)
        every = self.indexes()
        found, referenced_by = [], []
        for ix in ixs:
            for dp in ix["datapoints"]:
                if dp["id"].casefold() == want.casefold():
                    rec = present(dp, ix)
                    mapped = []
                    for other in every:
                        if other is ix or not dp.get("ig3_mapping") or other["layout"] != "ig3":
                            continue
                        for odp in other["datapoints"]:
                            if odp["id"] in dp["ig3_mapping"]:
                                mapped.append({"id": ident(odp["id"]), "version": other["key"],
                                               "name": remote(odp.get("name"))})
                    if mapped:
                        rec["ig3_mapped_datapoints"] = mapped
                    found.append(rec)
        for ix in every:
            for dp in ix["datapoints"]:
                if any(m.casefold() == want.casefold() for m in dp.get("ig3_mapping", [])):
                    referenced_by.append({"id": ident(dp["id"]), "version": ix["key"], "dr": show_dr(dp.get("dr")),
                                          "name": remote(dp.get("name"))})
        out = {"id": ident(want), "found": bool(found), "datapoints": found}
        if referenced_by:
            out["listed_in_ig3_mapping_of"] = referenced_by
        if not found:
            ids = [dp["id"] for ix in ixs for dp in ix["datapoints"]]
            out["close_matches"] = [ident(i) for i in difflib.get_close_matches(want, ids, n=5, cutoff=0.6)]
        out["source"] = source_block(ixs)
        return out

    def disclosure_requirement(self, dr_code, version=None) -> dict:
        raw = dr_code
        want = _norm_code(raw)
        if not want:
            raise ToolError("give a disclosure requirement code, e.g. E1-6 or GOV-1")
        ixs = self.select(version)
        per_version = []
        for ix in ixs:
            dps = [dp for dp in ix["datapoints"] if _dr_matches(dp.get("dr", ""), want)]
            if not dps:
                continue
            act = sources.binding_act(ix["layout"])
            per_version.append({
                "version": ix["key"],
                "dr_codes": sorted({show_dr(dp.get("dr")) for dp in dps}),
                "counts": {"datapoints": len(dps),
                           "voluntary": sum(1 for dp in dps if dp.get("voluntary") is True),
                           "conditional": sum(1 for dp in dps if dp.get("conditional")),
                           "phase_in": sum(1 for dp in dps if subject_to_phase_in(dp))},
                "legal_text": act,
                "datapoints": [present(dp, ix, brief=True) for dp in dps],
            })
        out = {"disclosure_requirement": show_dr(raw), "found": bool(per_version), "versions": per_version,
               "note": "The datapoint lists carry DR codes, not DR titles; the title and full text are in the act."}
        if not per_version:
            codes = sorted({dp.get("dr", "") for ix in ixs for dp in ix["datapoints"] if dp.get("dr")})
            out["close_matches"] = [show_dr(c) for c in difflib.get_close_matches(clean(raw, 60), codes, n=8,
                                                                                  cutoff=0.5)]
        out["source"] = source_block(ixs)
        return out

    def diff_versions(self, standard, from_version=None, to_version=None,
                      min_similarity=DEFAULT_MIN_SIMILARITY, limit=100) -> dict:
        std = _norm_standard(standard)
        if not std:
            raise ToolError(f"give a standard: one of {', '.join(STANDARDS)}")
        limit = _limit(limit, 100)
        if isinstance(min_similarity, bool) or not isinstance(min_similarity, (int, float)) \
                or not 0.5 <= min_similarity <= 1.0:
            raise ToolError("min_similarity must be a number from 0.5 to 1.0")
        ixs = self._require()
        old = self.select(from_version)[0] if from_version else None
        new = self.select(to_version)[0] if to_version else None
        default = self.select(None)
        if old is None:
            old = default[0]
        if new is None:
            new = next((ix for ix in reversed(default) if ix is not old), None)
        if new is None or new is old:
            raise ToolError("diff_versions needs two indexed versions; indexed: "
                            + ", ".join(ix["key"] for ix in ixs) + ". Download the other list from EFRAG ("
                            + "; ".join(p["page"] for p in sources.download_pages()) + ").")
        a = [dp for dp in old["datapoints"] if dp.get("standard") == std]
        b = [dp for dp in new["datapoints"] if dp.get("standard") == std]
        pairs, used_a, used_b, paired = [], set(), set(), set()

        def pair(x, y, method, score=None):
            changed = _changed(x, y)
            rec = {"method": method, "old_id": ident(x["id"]), "new_id": ident(y["id"]), "changed_fields": changed}
            if score is not None:
                rec["score"] = round(score, 3)
            if x.get("standard") != std:
                rec["old_standard"] = x.get("standard")
            if y.get("standard") != std:
                rec["new_standard"] = y.get("standard")
            if method != "id" or changed:
                rec["old_name"] = remote(x.get("name"))
                rec["new_name"] = remote(y.get("name"))
            pairs.append(rec)
            paired.add((id(x), id(y)))
            used_a.add(id(x))
            used_b.add(id(y))

        by_id = {dp["id"]: dp for dp in b}
        for x in a:
            y = by_id.get(x["id"])
            if y is not None:
                pair(x, y, "id")
        missing_mapped = []
        if old["layout"] == "ig3" and any(dp.get("ig3_mapping") for dp in new["datapoints"]):
            old_by_id = {dp["id"]: dp for dp in old["datapoints"]}
            for y in new["datapoints"]:
                for mid in y.get("ig3_mapping", []):
                    x = old_by_id.get(mid)
                    if x is None:
                        if y.get("standard") == std:
                            missing_mapped.append(mid)
                        continue
                    if (x.get("standard") == std or y.get("standard") == std) and (id(x), id(y)) not in paired:
                        pair(x, y, "efrag_mapping")
        rest_a = [x for x in a if id(x) not in used_a]
        rest_b = [y for y in b if id(y) not in used_b]
        cands = []
        for i, x in enumerate(rest_a):
            fx = fold(x.get("name", ""))
            if not fx:
                continue
            for j, y in enumerate(rest_b):
                fy = fold(y.get("name", ""))
                if not fy:
                    continue
                sm = difflib.SequenceMatcher(None, fx, fy, autojunk=False)
                if sm.real_quick_ratio() < min_similarity or sm.quick_ratio() < min_similarity:
                    continue
                r = sm.ratio()
                if r >= min_similarity:
                    cands.append((-r, i, j))
        taken_a, taken_b = set(), set()
        for negr, i, j in sorted(cands):
            if i in taken_a or j in taken_b:
                continue
            taken_a.add(i)
            taken_b.add(j)
            pair(rest_a[i], rest_b[j], "name_similarity", -negr)
        removed = [x for x in a if id(x) not in used_a]
        added = [y for y in b if id(y) not in used_b]
        methods = {}
        for p in pairs:
            methods[p["method"]] = methods.get(p["method"], 0) + 1
        brief = lambda dp, ix: present(dp, ix, brief=True)  # noqa: E731
        listed = [p for p in pairs if p["method"] != "id" or p["changed_fields"]]
        out = {
            "standard": std, "from_version": old["key"], "to_version": new["key"],
            "summary": {"old_datapoints": len(a), "new_datapoints": len(b), "pairs_by_method": methods,
                        "pairs_changed": sum(1 for p in pairs if p["changed_fields"]),
                        "pairs_unchanged": sum(1 for p in pairs if not p["changed_fields"]),
                        "removed": len(removed), "added": len(added)},
            "methods": {"id": "same datapoint ID in both files",
                        "efrag_mapping": ("the newer file's own 'Mapping with 2024 IG 3' column names the older "
                                          "ID (only when the mapping version of the 2026 list is indexed)"),
                        "name_similarity": (f"datapoint names at least {min_similarity:.2f} similar "
                                            "(difflib ratio on normalised names; the threshold is this tool's "
                                            "choice, pairs are one-to-one, best score first)")},
            "pairs": listed[:limit],
            "removed": [brief(x, old) for x in removed[:limit]],
            "added": [brief(y, new) for y in added[:limit]],
            "truncated": any(len(v) > limit for v in (listed, removed, added)),
            "source": source_block([old, new]),
        }
        if missing_mapped:
            out["mapping_ids_not_in_old_file"] = sorted(set(missing_mapped))
        return out

    def sources(self) -> dict:
        return {
            "official_files": sources.OFFICIAL_FILES,
            "other_files": ("Other workbooks are read on a best-effort basis when a sheet has a header row with "
                            "an 'ID' and a 'Name' column; they are labelled as not byte-identical to an official "
                            "file."),
            "download_pages": sources.download_pages(),
            "efrag_terms": {"url": sources.EFRAG_DISCLAIMER_URL, "checked": sources.CHECKED,
                            "says": ("copying, adapting or otherwise exploiting the site's content "
                                     f"'{sources.EFRAG_DISCLAIMER_FRAGMENT}'"),
                            "consequence": ("This package contains no EFRAG text or file. You download the "
                                            "workbook from EFRAG yourself; the tool indexes your copy locally.")},
            "legal_acts": sources.LEGAL_ACTS,
            "eu_reuse": sources.COMMISSION_REUSE,
            "not_affiliated": "This tool is not affiliated with or endorsed by EFRAG or the European Commission.",
        }


def _changed(x: dict, y: dict) -> list:
    out = []
    if fold(x.get("name", "")) != fold(y.get("name", "")):
        out.append("name")
    if _norm_code(x.get("dr", "")) != _norm_code(y.get("dr", "")):
        out.append("dr")
    if fold(x.get("paragraph", "")) != fold(y.get("paragraph", "")):
        out.append("paragraph")
    if fold(x.get("data_type", "")) != fold(y.get("data_type", "")):
        out.append("data_type")
    if x.get("conditional") != y.get("conditional"):
        out.append("conditional")
    # None means the file has no such column: unknown, not a change.
    if None not in (x.get("voluntary"), y.get("voluntary")) and x.get("voluntary") != y.get("voluntary"):
        out.append("voluntary")
    px, py = subject_to_phase_in(x), subject_to_phase_in(y)
    if None not in (px, py) and px != py:
        out.append("phase_in")
    if sorted(x.get("eu_legislation", [])) != sorted(y.get("eu_legislation", [])):
        out.append("eu_legislation")
    return out
