# dtc-cash-onboarding

Every brand sends different files. This project maps a consumer brand's Shopify, Amazon, Faire, bank, card and
chart-of-accounts exports into one cash ledger, and **accepts the result only when independent records of the same
money agree**. What it cannot prove, it sends to a person instead of guessing.

Built by Avinash Rayudu. All data is synthetic.

```
make install
make demo        # about 2 minutes: onboards 13 brands twice, runs every eval, writes reports/
```

Open `reports/index.html` for the overview, or read [`evals/results/results.md`](evals/results/results.md).

---

## The problem

Mapping columns is the easy part; tools like Flatfile and OneSchema already do it. The hard part is that a column
can be mapped correctly and the money can still be wrong:

- A Shopify payout is net of fees and refunds. Counting it as revenue next to the orders counts sales twice.
- An Amazon settlement report spreads one deposit across dozens of fee rows, and the date-range report ends each
  settlement with a negative "Transfer" row that *is* the deposit.
- A transfer back from savings, a credit line draw and a vendor refund all look like income in a bank CSV.
- Paying the card bill from the bank and listing the ad charges on the card counts the same ad spend twice.
- Exports overlap: the second bank download repeats the last week of the first.
- Some order exports repeat the order total on every line item. Summing them overstates sales.

In this project's synthetic data, simply adding up every deposit overstated customer receipts by 0.1% to 90%
depending on the brand and upload.

## The approach

```
read  ->  recognize and map  ->  standard tables  ->  TIE-OUTS (the gate)  ->  label each line  ->  decide
```

1. **Read** CSV, tab-separated, semicolon or Excel files, and find the real header under summary or definition lines.
2. **Recognize and map** each file. A column is accepted only when the header *and* the values agree. Header text
   alone never maps a column.
3. **Build standard tables.** Resolve sign conventions, day-first vs month-first dates, decimal commas, line-item
   order exports, transaction-level payout exports, and rows repeated from an earlier upload.
4. **Tie out.** This is the gate. The upload is accepted only if:
   - Shopify payouts, Amazon settlements and Faire payouts appear in the bank to the cent, within a few days;
   - order totals equal payout charges (the brand's payout lag is found, not assumed);
   - card payments appear as bank debits, and each statement equals the sum of its charges (the close day is found);
   - the running balance agrees with the amounts, which also proves the sign convention;
   - every bank or card file was read without dropping rows, and there is a bank statement to tie to at all.
5. **Label each line** by what the money actually is (payout, transfer, payroll, inventory, ad spend and 20 more):
   - first by proof: a deposit that equals a payout is labeled by the tie-out, not by a model;
   - then by memory: answers a reviewer already gave for this brand;
   - then by a model, only above a threshold picked for 99% precision on brands the model never saw.
   Anything below the threshold goes to the review queue.
6. **Decide.** The upload is *accepted*, *ties out with open items*, or *blocked* with the failing check named.

Each brand gets a memory: file layouts, reviewer answers, and fingerprints of ingested lines. The second upload is
recognized without questions, and overlapping rows are dropped.

The design follows a principle Highbeam has published for its Luma platform: run deterministic code against
structured data instead of letting a language model read raw financial records. The optional language-model
fallback here (`onboard/llm_fallback.py`, off by default and not used in any number below) sees only headers and
value shapes such as `9999-99-99`, never a row. Its suggestions are re-checked against the values and still have
to pass the tie-outs. This project is not affiliated with Highbeam.

## Results

From `make demo`, first pass, before any review. Numbers are from the run committed in `evals/results/`.

| brands | upload | lines | auto-labeled | precision | sent to review | review items per brand |
|---|---|---|---|---|---|---|
| 3 development brands (never trained on) | 1st | 630 | 97.1% | 100% (0 wrong) | 18 | 7.0 |
| same brands | 2nd | 557 | 99.3% | 100% (0 wrong) | 4 | 1.3 |
| 3 holdout brands, **blind run** | 1st | 618 | 46.9% | 84.5% (45 wrong) | 122 | 47.3 |
| 3 holdout brands, after fixes (**not blind**) | 1st | 618 | 95.2% | 99.7% (2 wrong) | 30 | 15.7 |
| same brands, after fixes | 2nd | 578 | 97.9% | 99.8% (1 wrong) | 12 | 4.3 |

- **Memory works.** On the second upload, all 22 development files were recognized from memory, and all 58 rows
  repeated from the first upload were dropped with no false flags. Review items fell from 7.0 to 1.3 per brand.
- **The gate catches mistakes.** I injected 51 errors:
  - summed line-item totals, subtotals mapped as totals, day and month swapped, missing Shopify, Amazon or Faire exports;
  - 49 were blocked and 2 were held in the review queue;
  - none was silently accepted;
  - 13 bank files with flipped signs were all repaired automatically from the payout matches.
- **Receipts after review match the truth exactly** for every brand, because every receipt line was either matched
  to a payout record or confirmed by a reviewer.
- **Model.** Logistic regression on character and word n-grams, trained on 2,606 lines from 7 brands. In
  leave-one-brand-out cross-validation it is 96.2% accurate without abstaining. At the chosen threshold of 0.49 it is
  99.4% precise and labels 91.1% of lines.

Training brands are in-sample and appear in `results.md` only for completeness.

### What the blind holdout found

The three holdout brands were written after the code and model were frozen. Hashes of every `onboard/*.py` and
model file are in `evals/FREEZE.json`; the blind run is kept unchanged in `evals/results/holdout_v1_frozen/`.
It exposed four real problems:

1. **A hole in the gate.** Two brands ended *accepted* although their bank data never tied out. Every bank check
   came back "not applicable", and the gate read that as a pass. Now an upload with no readable bank rows, or a
   file whose mapping silently drops rows, is blocked.
2. **Dates written `01-07-2026`** (day-month-year with dashes) did not parse. Even a correct column mapping read
   zero rows from that brand's bank and card files.
3. **Unsigned amounts with a separate DR/CR column.** With no negative numbers, the bank file was taken for a card
   statement and accepted under the wrong type.
4. **Shopify payouts exported one row per transaction.** The gate correctly refused this brand. The pipeline now
   rolls transactions up to payouts. The same brand's PayPal deposits have no export, so they are flagged until a
   reviewer confirms them; the confirmation is shown on the check, not hidden.

I fixed all four after seeing the holdout, so the "after fixes" rows are not a blind test. `make demo` prints which
files changed after the freeze, so this is visible in every run.

## Repository

```
schema/cash_ledger.yaml   the standard ledger, labels and source types
data/
  sim.py                   true money movements for one synthetic brand
  render.py                turns the truth into exports the way each platform and bank writes them
  generate_brands.py       10 brands: 7 training, 3 development
  holdout/generate_holdout.py   3 holdout brands, written after the freeze
  raw/<brand>/brand.yaml   what a kickoff call captures: name, currency, own account numbers
  raw/<brand>/upload_1|2/  the files a brand hands over
onboard/                   the pipeline (never reads ground truth; a test checks this)
  readers.py  parse.py  schemas.py  map_columns.py  detect_source.py  transform.py
  tieout.py  classify_lines.py  memory.py  pipeline.py  run.py  llm_fallback.py
review/
  resolve.py               simulated reviewer: answers review items from ground truth
  report.py                results.md and the HTML reports
evals/
  train.py                 trains, picks thresholds by leave-one-brand-out, saves models/
  freeze.py                records hashes before the holdout; --check compares
  run_evals.py             the full evaluation and fault injection
  ground_truth/            truth for the 10 development brands
  ground_truth_holdout/    truth for the 3 holdout brands
  results/                 results.json, results.md, holdout_v1_frozen/
models/                    line_model.joblib, coa_model.joblib, frozen.json
reports/                   index.html and one page per brand (works on GitHub Pages)
tests/                     18 tests
docs/                      onboarding_runbook.md, product_asks.md
```

## Run it on one brand

```
python onboard/run.py data/raw/quillon-coffee upload_1
```

This prints the status and every tie-out, and writes `out/quillon-coffee/upload_1/` with three files:

- `ledger.csv`: every line with its label, method and confidence;
- `review_queue.csv`;
- `result.json`.

Add `--commit` to record the upload in the brand's memory.

Other targets:

| target | what it does |
|---|---|
| `make test` | runs the tests |
| `make data` / `make holdout` | regenerates the synthetic brands |
| `make train` | retrains the models (deterministic: same file hashes every time) |
| `make freeze-check` | compares the code with the pre-holdout freeze |

Tested with Python 3.13, pandas 3.0, scikit-learn 1.9. The saved models need the scikit-learn version in
`requirements.txt`. With another version, run `make train` first; it takes about 15 seconds.

## Limits

- **Synthetic data, designed by me.** I wrote both the generator and the pipeline. Accuracy on quirks I designed
  overstates accuracy on real exports, and the blind holdout shows by how much.
- **The reviewer is simulated** from ground truth. Review counts measure how often a person is asked, not how long
  each answer takes.
- **Not supported yet:** PayPal, Stripe and Shopify Capital exports, 3PL invoices, multi-currency within one brand.
  The gate blocks rather than guesses when it meets them.
- **Detection rules were tuned on development brands.** The holdout is the honest measure of how they generalize.

## Why I built this

At Zacao Chocolate, a consumer products brand that sells through about 150 stores plus Shopify and Amazon, I work
across four sales channels. I built a PO-to-invoice matching agent there that cut the payment cycle by 15 days.
The lesson from that work is the core of this project: a match you can prove beats a label you can only predict.
