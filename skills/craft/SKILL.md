---
name: craft
description: Produce the best version of any text, page, deck or UI, and refuse the AI-shaped one. Read before writing anything Kerem will see or publish. Sources read at source 2026-09-07: stop-slop (hardikpandya), de-ai-slop-ui tells (site-agent), awesome-design-md (VoltAgent).
---

# Craft

Kerem's rule, 2026-09-07: "sadece ai slop olmamak degil, direkt en iyi seyleri uretmek." Two halves: a list of things to refuse, and a description of the bar. Run `python3 ~/agents/rota/tools/slopcheck.py FILE` before anything ships; it catches the mechanical half and prints a score.

## Definitions by contrast (Kerem, 2026-09-08)

The most common slop in this network's own files was the sentence that defines a thing by what it is not: "measured, never estimated", "a receipt, not a report", a rule titled "read the files, not the filenames". On 2026-09-08 the board carried 46 of them and the hub tree 556, after every dash had already been removed once. Kerem: "this not this tanımlarıyla dolu her yer."

The fix is to write the positive half and stop. One trap in that: a hedged finding ("ownership not conclusively established") is a hedge, and its positive half is a hedge too ("ownership is unconfirmed"); the flat claim would be a new fact nobody established. research caught itself twice on 2026-09-08 turning an open question into an assertion while fixing style. Re-read every rewritten sentence that carried a doubt and check the doubt survived. "Measured with spend.py." "A receipt." "Read the file." The reader supplies what that rules out. When the excluded thing has to be named because someone keeps doing it, give it its own sentence with its own verb: "A filename is a label; read the file." The checker now fails on the pattern; the quoted examples in this file are exempt because quoted spans are stripped before matching.

## Prose: refuse

- Em dashes and en dashes. None. A period, a colon or a comma does the work.
- Definition by contrast: "not X, but Y", "isn't X, it's Y", "X, not Y", "X, never Y", "not just X". Write the Y.
- Throat-clearing: "Here's the thing", "It turns out", "The truth is", "Let me be clear", "This matters because", "Let that sink in".
- Adverbs: "really", "just", "actually", "genuinely", "truly", "simply", "fundamentally", "deeply", "crucially". All of them.
- Lazy extremes such as every, always, nobody, where a specific number exists.
- Triads for rhythm: "Fast. Simple. Powerful." Two items or one.
- Quotable closers. If a sentence sounds like a pull quote, rewrite it as a fact.
- False agency: "the data tells us", "the decision emerges", "the culture shifts". Name the person who did it.
- Passive voice that hides the actor: "mistakes were made".
- Wh- openers and paragraphs starting with "So".
- Three consecutive sentences of the same length.
- Meta-commentary: "In this section", "as we'll see", "I want to explore".
- Business jargon: "navigate", "unpack", "lean into", "landscape", "game-changer", "deep dive", "moving forward", "circle back".
- Vague declaratives: "the implications are significant", "the stakes are high". Name the implication.

## Prose: the bar

- The first sentence says the thing. A reader who stops there has the point.
- Every claim carries its number or its source, or it is cut. "872 tests" beats "thoroughly tested".
- Specific nouns and real verbs. "Keeps every task searchable in 20ms" beats "a second brain".
- The swap test: could a competitor put this sentence on their page unchanged? Then it says nothing.
- "You" over "people". The reader is in the room.
- Rhythm follows the content.
- Trust the reader: no softening, no permission-granting ("and that's okay"), no hand-holding.
- Score 1-10 on directness, rhythm, trust, authenticity, density. Under 35 of 50: rewrite.

## Design: refuse

- Purple-on-black, neon on dark, equal-weight pastels, rainbow gradient text, multi-stop diagonal gradients.
- Pure #ffffff on pure #000000. Move a few degrees off both.
- Inter/Geist/Space Grotesk as the whole voice. One workhorse body face plus one display face with character. Two families is the budget per page; seventeen tool pages each choosing one face for its trade is seventeen pages obeying it.
- Three equal cards with icon, three-word heading, two lines. Bento tiles that all hold an icon and a sentence.
- Radius that does not relate: 24px card, 8px button, round badge inside. One scale; nested elements get a smaller radius than their container.
- Shadow on everything. Use one or two levels; a card gets a 1px border.
- Glassmorphism, blurred glow blobs, dot-grid backgrounds, bouncing arrows, hover effects on things that are not clickable, sparkle icons, emoji as UI.
- Default Lucide rocket/zap/shield at 24px stroke.
- Invented testimonials, fake terminal windows, a product page with no real screenshot.
- Three-tier pricing invented to fill a section.
- Layout shift: images without dimensions, fonts that reflow.

## Design: the bar

- One accent, pulled from something real, used in one place per screen.
- Off-white paper, near-black ink, and a text size that is 14px or larger everywhere. Tap targets 44px.
- Asymmetry that reads as editing: the thing that matters is larger; the rest is a list.
- Motion only for state changes, and `prefers-reduced-motion` honoured.
- A real screenshot above the fold if the thing exists; an honest "not built yet" if it does not.
- Contrast 4.5:1 for body, 3:1 for large text, measured with a tool.
- `:focus-visible` on every interactive element.
- The swap test again: change the logo and the name. If the page still works, it is a template.
- Check the result at 390px before calling it done.

## A soft flag asks a question

Adverbs, Wh-openers, same-length runs, "rather than" and "instead of" are soft flags: the checker prints them
and still exits 0. Keep one when it carries meaning a reader would miss without it
("barcodes that actually scan" says the barcode was tested; "actually" as emphasis
says nothing). Before keeping one, try the specific verb: "barcodes that scan on a handheld"
beats "barcodes that actually scan". A keep needs the reason written beside it.

## The checker is the mechanical half

A file can score 10 of 10 and still carry a sentence that a scripted replacement
mangled into a fragment. setup, 2026-09-07: two such sentences in a charter, found
by reading, invisible to the script. After any bulk edit, read the changed lines.

## Before shipping anything

1. `python3 ~/agents/rota/tools/slopcheck.py FILE`. Zero dashes, zero banned phrases, zero contrast constructions, score printed.
2. Read it once as the reader it is for.
3. Every number traces to a command or a record. A number typed from memory is an assertion.
4. Deck or page: view at phone width. Prose: read the first sentence alone.
