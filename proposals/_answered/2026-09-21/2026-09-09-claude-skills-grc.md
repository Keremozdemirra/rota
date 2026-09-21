# Proposal: Sushegaad/Claude-Skills-Governance-Risk-and-Compliance

- **Repo:** https://github.com/Sushegaad/Claude-Skills-Governance-Risk-and-Compliance
- **Source:** agent-vitals census, data/servers.json (2026-09-08 snapshot)
- **Stars:** 886 · **Forks:** 180 · **Open issues:** 7
- **Licence:** MIT (SPDX-identified)
- **Language:** HTML
- **Created:** 2026-03-16 (177 days) · **Last push:** 2026-09-05 (3 days before census)
- **Archived:** no. **Fork:** no. First seen in this census 2026-09-04.

## What it claims to do (from its description and topics only)

A bundle of Claude skills that give framework-specific compliance guidance
across a long list of regimes. The description names ISO 27001, SOC 2,
FedRAMP, GDPR, HIPAA, NIST CSF, PCI DSS, the EU AI Act, ISO 42001, ISO 27701,
DORA, **CSRD**, India's DPDPA, CMMC 2.0, NIST AI RMF, SWIFT and CCPA/CPRA. It
advertises a benchmark of 93% with the skills against 74% without; the
benchmark is its own, and its construction is not stated in the metadata.
Topics: `claude-skills`, `compliance`, `csrd`, `data-privacy`, `dpdpa-2023`,
`eu-ai-act`, `fedramp`, `gdpr`, `governance`, `grc`, `hipaa`.

Nothing here has been cloned, read or run. Everything above is metadata.

## Which derived gap it fills

`vetting.yaml` `domains` line 1 is `[esg, climate, emissions, carbon,
sustainability, cbam, csrd]`. Nothing in `covered` answers any of it. That
makes it the largest wholly uncovered domain in the file, and it is the domain
the work itself sits in. The repository carries `csrd` as a declared topic, so
the overlap is stated by the author rather than inferred from prose.

The nearest installed thing is the `double-materiality-assessment` skill,
which covers one step of CSRD: deciding which ESRS topics are material. The
rest of the regime is uncovered, and the skill is absent from `covered`.

## What would have to be true for it to be worth installing

- **The CSRD/ESRS portion must be substantive.** Seventeen regimes in one
  repository is a wide claim, and CSRD is one item in a description whose
  centre of gravity is plainly infosec and privacy: ISO 27001, SOC 2,
  FedRAMP, HIPAA. If the ESRS coverage is a paragraph, this fills nothing,
  and the other sixteen frameworks fall outside every domain in
  `vetting.yaml`.
- **Every requirement it asserts must cite the instrument and its version.**
  This is the load-bearing condition. CLAUDE.md §5 requires a primary source
  and a date for any published threshold, and `source-check` exists to enforce
  it. A skill that states an ESRS datapoint or a reporting threshold without
  naming the delegated act and its date produces exactly the class of claim
  that has to be re-verified by hand, which costs more than writing it fresh.
  CSRD's scope thresholds and phase-in dates have been amended, so undated
  guidance is worse than silence.
- **It must not ship standard text.** ISO 27001, ISO 42001 and ISO 27701 are
  copyrighted and are not redistributable. An MIT repository may lawfully
  contain original paraphrase. It may not contain the clauses. If the ISO
  material is reproduced rather than described, the repository's licence does
  not make it distributable, and installing it puts non-redistributable text
  on disk. This is the "avukat sorusu" case in CLAUDE.md §6, and it is
  answerable by reading two files.
- **It must stay advisory.** A skill that reads a document and advises is a
  reference. One that runs a scan, writes a register, or claims an
  attestation is asserting a compliance conclusion, and nobody here is in a
  position to stand behind that.
- **The benchmark carries no weight.** A self-reported 93% against 74%, with
  no stated question set, grader or baseline, is a marketing number. It should
  move the decision in neither direction.

## Checks a human must run before installing

1. Read the CSRD/ESRS skill files first and alone. If they do not survive on
   their own merits, stop. The other sixteen frameworks are not the reason
   this is being considered.
2. Pick three concrete assertions from the ESRS material: a scope threshold, a
   phase-in date, a datapoint requirement. Check each against the consolidated
   Directive text and the ESRS delegated act. Whether they cite their source
   is a separate and more important question than whether they happen to be
   right.
3. Grep the ISO 27001 / 42001 / 27701 material for verbatim clause text. Any
   substantial reproduction is a stop, whatever the MIT licence says.
4. Read `SKILL.md` and any install command as an execution path, per
   `tool-vetting`: what runs, when, and with what permissions. `HTML` as the
   detected language on a skills repository is worth understanding before
   anything is fetched.
5. Check for conflict with `double-materiality-assessment`. Two skills
   answering the same materiality question by different methods is worse than
   either one alone.
6. Confirm the licence file is the MIT the API reports, and check whether the
   skill content is licensed separately from the code.
