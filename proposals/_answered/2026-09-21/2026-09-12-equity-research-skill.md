# Proposal: rollingSirius/equity-research-skill

- **Repo:** https://github.com/rollingSirius/equity-research-skill
- **Source:** agent-vitals census, data/servers.json (2026-09-11 snapshot)
- **Stars:** 434 · **Forks:** 57 · **Open issues:** 0
- **Licence:** MIT (SPDX-identified)
- **Language:** Python
- **Created:** 2026-07-14 (60 days) · **Last push:** 2026-08-21 (21 days before census)
- **Archived:** no. **Fork:** no. First seen in this census 2026-09-04.

## What it claims to do (from its description and topics only)

The description calls it "possibly the deepest AI equity-research skill":
a nine-chapter single-stock report and an earnings report, "with
scripted DCF/EPV/EVA and reproducible valuation", covering US, Hong Kong
and A-share listings, with documentation in English and Chinese. The
topics are `agent-skills`, `dcf`, `equity-research`, `valuation`,
`stock-analysis`, `investing`.

Read together, that is an agent skill (a markdown procedure plus Python
scripts) that walks a model through a fixed research structure and hands
the valuation arithmetic to scripts rather than to the model. "Scripted"
and "reproducible" are the two words that make it worth a look: a DCF
whose numbers come from a script with visible inputs is the only kind
that passes `source-check`. Where the inputs come from is not stated in
the metadata.

Twenty-one days since the last push is inside the 30-day `active`
window, but it is the oldest push among the candidates this week, on a
repository only nine weeks old. That is a project that may have shipped
and stopped, or may be between releases; the metadata cannot tell.

Nothing here has been cloned, read or run. Everything above is metadata.

## Which derived gap it fills

`vetting.yaml` `domains` line 2 is `[finance, valuation, financial,
accounting, fundamentals, sec-filings]`, and `covered` names no finance
job at all. Within that line the specific gap is *building* a valuation:
`valuation-review` is a skill that takes apart a valuation somebody else
built and says in its own description that it is "not for building a
valuation from scratch". Yesterday's proposal, `JerBouma/FinanceToolkit`,
is a ratio and fundamentals library, the layer below a valuation. The
`finance` agent has the mandate but no scripted DCF behind it.

So the derived gap is narrow and real: a reproducible DCF procedure with
the arithmetic in code. Whether an equity-research skill written for
stock-picking is the right shape for ESG-adjacent and climate-finance
valuation work is the fit question, and that decision belongs to the
`setup` session.

## What would have to be true for it to be worth installing

- **The valuation scripts must be separable from the stock-picking
  frame.** The value here is the DCF/EPV/EVA code and the input
  discipline around it. If the scripts only run inside the full
  nine-chapter flow, the useful part is buried in a workflow nobody
  here needs.
- **Every input must be traceable.** Discount rate, terminal growth,
  share count and the statement figures must arrive from a named source
  at a named date, or be marked as assumptions. A script that hard-codes
  a market risk premium is the thing `valuation-review` exists to catch.
- **The data path must be free or already paid for.** "Covers US, HK and
  A-shares" implies a market-data dependency. If it is a vendor key on a
  paid plan, the subscription is the real decision; if it is `sec-edgar`
  or a free source, the skill can sit on what is already installed.
- **It must not overlap `FinanceToolkit` twice.** If both proposals
  survive, one computes fundamentals and the other consumes them.
  Installing two sources of the same margin is how numbers drift
  between a deck and its appendix.

## Checks a human must run before installing

1. Read the skill file and the scripts before anything runs. A skill is
   an instruction file the model executes; treat it as code, per
   `tool-vetting`, and read it as an execution path.
2. List every network call the scripts make and every credential they
   expect. Decide the data source before deciding the skill.
3. Take one valuation already built by hand for a listed company and
   run the DCF script on the same inputs. A different answer with no
   visible reason in the formula is a stop. Then hand the script's
   output to `valuation-review` and see whether it survives.
4. Check what happened between 2026-08-21 and today: read the commit
   log and the closed issues, and decide whether zero open issues on 57
   forks is a finished tool or an unanswered tracker.
5. Confirm the licence covers the scripts and the documentation alike,
   and that no bundled data carries a licence of its own.
6. Decide in writing which of `finance`, `FinanceToolkit` (if installed)
   and this skill owns the DCF, so the number has one home.
