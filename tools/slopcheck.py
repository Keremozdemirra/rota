#!/usr/bin/env python3
"""Mechanical half of the craft skill. Reports dashes, banned phrases, adverbs,
contrast constructions, triads, Wh-openers and monotone rhythm. Exit 1 if any
hard rule fails. Usage: slopcheck.py FILE [FILE ...]  (md, txt, html)"""
import re, sys, html

BANNED = [r"here'?s the thing", r"it turns out", r"the truth is", r"let me be clear", r"this matters because",
          r"let that sink in", r"make no mistake", r"at the end of the day", r"in today's", r"it'?s worth noting",
          r"game[- ]changer", r"deep dive", r"lean into", r"moving forward", r"circle back", r"unpack",
          r"seamlessly", r"effortlessly", r"supercharge", r"revolutioni[sz]e", r"unlock(?:s|ing)?\b",
          r"the implications are", r"the stakes are high", r"plot twist", r"spoiler:", r"(?:^|[.!?]\s+)full stop\.", r"(?:^|[.!?]\s+)period\."]
ADVERBS = ["really","just","actually","genuinely","truly","simply","fundamentally","deeply","crucially",
           "honestly","literally","importantly","interestingly","inevitably","inherently"]
CONTRAST = [r"\bnot (?:just|only|merely) [^.]{1,60}?\b(?:but|it'?s)\b", r"\bisn'?t (?:the )?[^.]{1,40}?\. ?[^.]{1,40}? is\b",
            r"\bnot because [^.]{1,60}?\. because\b", r"\bit'?s not [^.]{1,40}?\. it'?s\b", r"\bthe (?:answer|question) isn'?t\b",
            r"\b(?:this|that|it) is not (?:a |an |the )?[^.]{1,40}?, (?:it|this|that) is\b",
            # "not X, but Y" after a copula or a comma; "could not break there, but" is plain narrative
            r"(?<!could )(?<!would )(?<!should )(?<!did )(?<!do )(?<!does )(?<!can)(?<!will )(?<!must )(?<!may )(?<!might )\bnot (?:a |an |the )?[^.]{1,40}?, (?:but |it is |it'?s )",
            # definition by contrast: "X is Y, not Z" / "X, not Y" / "X, never Y" / a rule title "X are Y not Z"
            r"\b(?:is|are|was|were|means|stays|counts as|becomes|remains|gets?)\b[^.;:\n]{0,60}?,\s*not\b",
            r",\s*not\s+(?:a|an|the|his|her|its|their|your|our|what|how|because|from|by|on|in|to|of|for|with|every|one|nine|eight)\b",
            r",\s*never\b",
            r"\*\*[^*\n]*\b(?:is|are)\s+[\w'-]+\s+not\s+[\w'-]+[^*\n]*\*\*"]
# softer contrast: worth a reason, rarely worth keeping
SOFT_CONTRAST = [r"\brather than\b", r"\binstead of\b", r"\byerine\b"]
# Turkish form of the same habit: "X değil, Y" / "X değil Y" / "X değil de Y" (sentence-final "değil." and "değil mi" pass)
CONTRAST += [r"\bde[gğ]il,\s", r"\bde[gğ]il\s+(?!m[iıuü]\b)[a-zçğıöşüâîû]{2,}"]

def text_of(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    if path.endswith((".html", ".htm")):
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = html.unescape(raw)
    return html.unescape(raw)

def check(path):
    t = text_of(path)
    # verbatim material is exempt: fenced blocks and markdown blockquotes (statute, OJ text,
    # source quotes) exist to be exact, so they are removed before any pattern runs
    t = re.sub(r"(?ms)^[ \t]*```[^\n]*$.*?^[ \t]*```[^\n]*$", " ", t)  # fences open and close at a line start; an inline ``` in prose is text
    t = re.sub(r"(?m)^[ \t]*>.*$", " ", t)
    # quoted spans are examples, not usage: "not X, but Y" inside quotes is a citation
    t = re.sub(r'"[^"\n]{1,80}"', '"…"', t)
    t = re.sub(r"`[^`\n]{1,80}`", "`…`", t)
    low = t.lower(); out = []; hard = 0
    # numeric ranges (0.0–1.0, 9–11) are not prose dashes
    tt = re.sub(r"(?<=\d)[—–](?=\d)", "-", t)
    em = tt.count("—"); en = tt.count("–")
    if em or en: out.append(f"  dashes: em {em}, en {en}"); hard += em + en
    for b in BANNED:
        n = len(re.findall(b, low))
        if n: out.append(f"  banned phrase /{b}/ x{n}"); hard += n
    for c in CONTRAST:
        n = len(re.findall(c, low))
        if n: out.append(f"  contrast construction /{c}/ x{n}"); hard += n
    softc = sum(len(re.findall(c, low)) for c in SOFT_CONTRAST)
    if softc: out.append(f"  rather than / instead of: {softc}")
    adv = {a: len(re.findall(rf"\b{a}\b", low)) for a in ADVERBS}
    adv = {k: v for k, v in adv.items() if v}
    if adv: out.append("  adverbs: " + ", ".join(f"{k} x{v}" for k, v in adv.items()))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if len(s.strip()) > 20]
    wh = sum(1 for s in sents if re.match(r"(what|when|where|which|who|why|how)\b", s, re.I))
    if wh: out.append(f"  Wh- openers: {wh}")
    tri = len(re.findall(r"\b[A-Z][a-z]+\. [A-Z][a-z]+\. [A-Z][a-z]+\.", t))
    if tri: out.append(f"  one-word triads: {tri}")
    mono = 0
    for i in range(len(sents) - 2):
        a, b, c = (len(sents[i].split()), len(sents[i+1].split()), len(sents[i+2].split()))
        if max(a, b, c) - min(a, b, c) <= 2: mono += 1
    if mono: out.append(f"  three same-length sentences in a row: {mono} place(s)")
    words = len(t.split())
    soft = sum(adv.values()) + wh + tri + mono + softc
    score_hits = hard + soft
    density = max(0, 10 - round(score_hits * 100 / max(words, 1)))
    print(f"{path}: {words} words, hard failures {hard}, soft flags {soft}, mechanical density {density}/10")
    for o in out: print(o)
    return hard

if __name__ == "__main__":
    fails = sum(check(p) for p in sys.argv[1:])
    sys.exit(1 if fails else 0)
