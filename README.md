# dtc-cash-onboarding

**What it is.** It maps a consumer brand's Shopify, Amazon, Faire, bank, card and chart-of-accounts exports into one
cash ledger. It accepts the upload only when independent records of the same money agree, and sends what it cannot
prove to a person instead of guessing.
**Best result.** On a second blind holdout (three new brands, run once on frozen code), it labeled about 79% of 1,180
lines on its own with no wrong labels. The one brand it could not tie out was blocked with the failing checks named.
**See it.** [Rendered onboarding report](https://avinashrayudu.github.io/dtc-cash-onboarding/reports/) ·
[case study](https://www.avinashrayudu.com/work/dtc-cash-onboarding/) ·
[how I'd onboard a brand](docs/onboarding_runbook.md) · [what I'd ask Product for](docs/product_asks.md) ·
[how the money is treated](docs/accounting_treatment.md)

Built by Avinash Rayudu. All data is synthetic.

```
make install
make demo        # about 2 minutes: onboards 13 brands twice, runs every eval, writes reports/
```

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
4. **Tie out.** This is the gate (see [Controls](#controls)).
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

## Controls

Each check in `onboard/tieout.py`, and the mistake it stops from reaching the ledger.

| Check | What has to agree | Error it prevents | Passes when |
|---|---|---|---|
| `shopify_payouts_to_bank` | each Shopify payout and a bank deposit, to the cent, within 3 days | a missing or wrong payouts export; payouts counted as revenue twice | 98% of payouts found |
| `amazon_to_bank` | each Amazon settlement transfer and a bank deposit, to the cent, within 5 days | a missing settlement report; fee rows read as deposits | 98% found |
| `faire_to_bank` | each Faire payout day and a bank deposit, to the cent, within 3 days | a missing Faire export | 98% found |
| `orders_to_payouts` | daily order charges and payout charges, at the brand's payout lag (1 to 3 business days, found from the data) | line-item totals summed; subtotal mapped as total; an incomplete orders export | within 0.5% |
| `card_payments_to_bank` | payment rows on the card and card-bill debits in the bank | the same ad spend counted on the card and again as the bank payment | 98% found |
| `card_statement_balance` | each card payment and the charges in its statement cycle (close day found from the data) | dropped or repeated card rows | every full statement |
| `own_account_transfers` | money leaving one of the brand's accounts and arriving in another | a transfer from savings counted as income | no loose transfers |
| `bank_balance_continuity` | the running balance and the amounts | flipped signs, dropped rows, a misread date order | 99% of rows |
| `deposits_without_source` | every payout-looking deposit and an export behind it | receipts from a processor with no export (PayPal, for example) accepted unproven | none, unless a reviewer confirms the exception |
| `bank_rows_present` | at least one readable bank statement | "not applicable" read as a pass (bug found by holdout v1) | more than 0 rows |
| `rows_read` | every row of every bank and card file parsed | rows silently dropped by a date format (bug found by holdout v1) | 0 dropped |

Faults injected into clean uploads: 51 in total, 49 blocked, 2 held for review, none silently accepted. Thirteen
bank files with flipped signs were repaired automatically from the payout matches.

## What the brand sees

The review queue is what reaches the brand. This item is from holdout v2 (the blind run, Vale Street Tea, first
upload). Everything else in that upload tied out; the queue held this line and two account categories.

| file | line | amount | model's best guess | confidence |
|---|---|---|---|---|
| `bank_operating_1.csv` | "payment received from old mill market", Aug 31 | $4,405.34 | `card_payment_received` | 0.17 |

The guess is wrong and the confidence is far under the 0.49 threshold, so the line was not labeled. The note I would
send the founder:

> On Aug 31 your bank shows $4,405.34 from Old Mill Market. Is that a wholesale customer paying an invoice? If so,
> I'll record it as wholesale revenue. Everything else in this upload matched your Shopify and Amazon exports, so
> this and two account categories are all I need from you.

On the next upload the same customer paid three more times and was asked about again. That is a gap, written up as
ask 5 in [`docs/product_asks.md`](docs/product_asks.md).

## Results

From `make demo`, first pass, before any review. Numbers are from the run committed in `evals/results/`.

| brands | upload | lines | auto-labeled | precision | sent to review | review items per brand |
|---|---|---|---|---|---|---|
| 3 development brands (never trained on) | 1st | 630 | 97.1% | 100% (0 wrong) | 18 | 7.0 |
| same brands | 2nd | 557 | 99.3% | 100% (0 wrong) | 4 | 1.3 |
| 3 holdout v1 brands, **blind run** | 1st | 618 | 46.9% | 84.5% (45 wrong) | 122 | 47.3 |
| 3 holdout v1 brands, after fixes (**not blind**) | 1st | 618 | 95.2% | 99.7% (2 wrong) | 30 | 15.7 |
| same brands, after fixes | 2nd | 578 | 97.9% | 99.8% (1 wrong) | 12 | 4.3 |
| 3 holdout v2 brands, **blind run on the current code** | 1st | 621 | 78.1% | 100% (0 wrong) | 15 | 7.3 |
| same brands | 2nd | 559 | 79.8% | 100% (0 wrong) | 10 | 4.0 |

- **Memory works for counterparties that recur.** On the second upload, all 22 development files were recognized
  from memory and all 58 rows repeated from the first upload were dropped with no false flags. Review items fell
  from 7.0 to 1.3 per brand.
- **Receipts after review match the truth exactly** for every brand that was accepted, because every receipt line
  was either matched to a payout record or confirmed by a reviewer.
- **Model.** Logistic regression on character and word n-grams, trained on 2,606 lines from 7 brands. In
  leave-one-brand-out cross-validation it is 96.2% accurate without abstaining. At the chosen threshold of 0.49 it is
  99.4% precise and labels 91.1% of lines.

Training brands are in-sample and appear in `results.md` only for completeness.

### Holdout v1: what the first blind run found

The three v1 holdout brands were written after the code and model were frozen. Hashes are in `evals/FREEZE.json`;
the blind run is kept unchanged in `evals/results/holdout_v1_frozen/`. It exposed four real problems:

1. **A hole in the gate.** Two brands ended *accepted* although their bank data never tied out. Every bank check
   came back "not applicable", and the gate read that as a pass. Now an upload with no readable bank rows, or a
   file whose mapping silently drops rows, is blocked.
2. **Dates written `01-07-2026`** (day-month-year with dashes) did not parse. Even a correct column mapping read
   zero rows from that brand's bank and card files.
3. **Unsigned amounts with a separate DR/CR column.** With no negative numbers, the bank file was taken for a card
   statement and accepted under the wrong type.
4. **Shopify payouts exported one row per transaction.** The gate correctly refused this brand. The pipeline now
   rolls transactions up to payouts.

I fixed all four after seeing the holdout, so the v1 "after fixes" rows are not a blind test.

### Holdout v2: a blind number for the current code

Because the v1 fixes came after seeing v1, the current code had no blind number. So I froze the code and models
again (`evals/FREEZE_v2.json`, committed on its own), then wrote three new brands with formats the pipeline had not
seen (`data/holdout_v2/generate_holdout_v2.py`), committed them, and ran `evals/run_holdout_v2.py` once. The runner
refuses to run if the code differs from the freeze or if a result already exists. The output in
`evals/results/holdout_v2_blind/` is untouched, and the commit order shows freeze, then data, then result.

| brand | what was new | upload 1 | upload 2 |
|---|---|---|---|
| Fieldnote Paper Co | fintech export with both accounts and no running balance, dates like "Oct 7, 2026", short coded memos | ties out, accepted after review | ties out, accepted after review |
| Vale Street Tea | newest-first bank export, ISO dates, plain-English memos, transaction-level payouts, a credit line, a direct wholesale customer | ties out with open items | ties out, accepted after review |
| Harbor & Hive | "Withdrawals" / "Deposits" columns with year-first dates (2026/07/01); a card export with Debit and Credit columns | **blocked**: payouts, Amazon and Faire not found in the bank | **blocked**: the same checks, plus rows not read |

Across the three brands, nothing was labeled wrong. The lines Harbor & Hive could not read count in the totals as
not labeled, which is why coverage is about 79%. Vale Street Tea's first upload ended with items open, its receipts
0.6% short of the truth until they are answered; every upload that was accepted matches the truth exactly. Three gaps came out of it, all still open, because fixing them
now would make this run stop being blind for the fixed code:

1. **Year-first dates were not read.** Harbor & Hive's real bank file was never mapped, so no deposit could be
   matched and the gate blocked the brand. Blocking was right; not reading the file is the gap.
2. **A card export with Debit and Credit columns was read as a bank statement**, in both uploads (2 of 44 file reads
   on the wrong source type). I knew the card schema had a single amount column when I wrote this brand; real card
   exports do this, so it is in the test.
3. **A customer seen once is not remembered.** See "What the brand sees" above.

Each is written up as a product ask in [`docs/product_asks.md`](docs/product_asks.md) (asks 5 and 6).

## Why these numbers

| Setting | Value | Where it comes from |
|---|---|---|
| Line model threshold | 0.49 | The lowest confidence at which leave-one-brand-out predictions reach 99% precision on the brand left out (`evals/train.py`, `TARGET_PRECISION = 0.99`). Below it, the line goes to a person. |
| Match rate to pass a tie-out | 98% | A source passes if at most about 1 record in 50 is not found. Requiring 100% would block a brand over one deposit delayed past the window; a lower bar would let a missing export through. |
| Match window | 3 days (Shopify, Faire), 5 days (Amazon) | Amazon deposits land later after a settlement closes than Shopify or Faire payouts. Amounts must still match to the cent. |
| Orders vs payout charges | within 0.5% | Wide enough for timing at the edges of the window, narrow enough that summed line items or a subtotal mapped as total (both several percent off) fail. |
| Balance continuity | 99% of rows | A single rounding or ordering artifact does not block; a flipped sign or a dropped block of rows does. |

## Repository

```
schema/cash_ledger.yaml   the standard ledger, labels and source types
data/
  sim.py                   true money movements for one synthetic brand
  render.py                turns the truth into exports the way each platform and bank writes them
  generate_brands.py       10 brands: 7 training, 3 development
  holdout/                 holdout v1: 3 brands written after the first freeze
  holdout_v2/              holdout v2: 3 brands written after the second freeze
onboard/                   the pipeline (never reads ground truth; a test checks this)
  readers.py  parse.py  schemas.py  map_columns.py  detect_source.py  transform.py
  tieout.py  classify_lines.py  memory.py  pipeline.py  run.py  llm_fallback.py
review/
  resolve.py               simulated reviewer: answers review items from ground truth
  report.py                results.md and the HTML reports
evals/
  train.py                 trains, picks thresholds by leave-one-brand-out, saves models/
  freeze.py                records hashes before a holdout; --check compares
  run_evals.py             the full evaluation and fault injection
  run_holdout_v2.py        runs holdout v2 once, blind
  results/                 results.json, results.md, holdout_v1_frozen/, holdout_v2_blind/
models/                    line_model.joblib, coa_model.joblib, frozen.json
reports/                   index.html and one page per brand (served by GitHub Pages)
tests/                     18 tests
docs/                      onboarding_runbook.md, product_asks.md, accounting_treatment.md
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

| target | what it does |
|---|---|
| `make test` | runs the tests |
| `make data` / `make holdout` / `make holdout-v2-data` | regenerates the synthetic brands |
| `make train` | retrains the models (deterministic: same file hashes every time) |
| `make freeze-check` | compares the code with the first freeze |

Tested with Python 3.13, pandas 3.0, scikit-learn 1.9. The saved models need the scikit-learn version in
`requirements.txt`. With another version, run `make train` first; it takes about 15 seconds.

## Limits

- **Synthetic data, designed by me.** I wrote the generators, the pipeline and both holdouts. Accuracy on quirks I
  designed overstates accuracy on real exports; the holdouts show by how much on formats I had not built for.
- **The reviewer is simulated** from ground truth. Review counts measure how often a person is asked, not how long
  each answer takes.
- **A cash ledger, not an accrual P&L.** See [`docs/accounting_treatment.md`](docs/accounting_treatment.md) for how
  payouts, sales tax, refunds, the Amazon reserve and the card bill are treated, and what is not done.
- **Not supported yet:** PayPal, Stripe and Shopify Capital exports, 3PL invoices, multi-currency within one brand,
  year-first bank dates, card exports with separate Debit and Credit columns. The gate blocks rather than guesses
  when it meets them.

## Why I built this

At Zacao Chocolate, a consumer products brand in Brooklyn that sells through 150+ retail stores across New York plus
Shopify and Amazon, I work across four sales channels. I built a PO-to-invoice matching agent there that cut the
payment cycle by 15 days. The lesson from that work is the core of this project: a match you can prove beats a label
you can only predict.
