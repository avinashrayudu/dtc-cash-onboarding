# Changelog

Each version lists the commits it covers. Built by Avinash Rayudu.

## How commits are structured

From v1.2.0 on, every commit message starts with its type:

| Type | Used for |
|---|---|
| `feat:` | new behavior in the pipeline or the evals |
| `fix:` | a bug fix; the message names what was wrong |
| `freeze:` | hashes recorded before a holdout is written; nothing else in the commit |
| `data:` | new or regenerated synthetic data |
| `results:` | output of a run, committed as it came out; nothing else in the commit |
| `docs:` | README and docs only; no number changes without a matching `results:` commit |
| `chore:` | tooling and housekeeping |

A blind holdout is always three commits in this order: `freeze:`, then `data:`, then `results:`.

## v1.2.0 (2026-10-28)

- docs: the so-what at the top of the README; every threshold explained in plain language.
- docs: `docs/finance_concepts.md` (AP and AR, cash vs accrual, the three-way match, tied to the projects).
- docs: where the project fits at Highbeam; how it was built.
- docs: the Zacao note now cites the verified receivables reconciliation instead of unverified figures.

## v1.1.0 (2026-10-28): second blind holdout

- `45d791a` freeze: code and models frozen in `evals/FREEZE_v2.json` before holdout v2 existed.
- `a080c34` data: holdout v2, three brands with formats the pipeline had not seen.
- `91ec9d2` results: the holdout v2 blind run, untouched. 0 wrong labels; one brand blocked.
- `4724657` docs: controls table, a sample review item, holdout v2 results, why these numbers.
- `15de8f8` docs: the runbook says plainly which reviewer answers memory keeps (a holdout v2 finding).

## v1.0.0 (2026-10-27): first publication

- `2f2b8eb` the pipeline, 13 synthetic brands, holdout v1 (blind run kept in `evals/results/holdout_v1_frozen/`),
  the four fixes that followed it, 18 tests and the reports.
