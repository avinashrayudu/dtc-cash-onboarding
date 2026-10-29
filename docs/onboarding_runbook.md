# Onboarding runbook

How I would use this on a new brand, start to finish. Built by Avinash Rayudu.

## Before the first upload: the kickoff call

Capture three things in `data/raw/<brand>/brand.yaml`:

- **Legal brand name.** Bank memos repeat it, and the classifier replaces it with a placeholder.
- **Reporting currency.**
- **Last digits of the brand's own accounts** (operating, savings, card). This is how transfers between the
  brand's own accounts are told apart from customer money.

Then ask for:

| export | where | why |
|---|---|---|
| Bank statement CSV, every account | bank portal | everything ties to this; the gate blocks without it |
| Card activity CSV | card portal | ad spend and software live here |
| Shopify orders export or Sales over time report | Shopify admin | proves payout charges |
| Shopify Payments payouts | Shopify admin | ties to bank deposits |
| Amazon settlement reports or date range report | Seller Central | ties to bank deposits |
| Faire payouts | Faire brand portal | ties to bank deposits |
| Chart of accounts | QuickBooks or Xero | maps their categories to the standard ones |

Ask for any other processor the brand uses (PayPal, Stripe, Shop Pay Installments). Deposits from a processor with no
export will be flagged.

## First upload

```
python onboard/run.py data/raw/<brand> upload_1
```

Read the status line first.

| status | meaning | what to do |
|---|---|---|
| `blocked` | a tie-out failed | read the failing check's detail; it names the missing export or the file that did not read |
| `ties out, items open` | the money agrees; some lines or files need a person | work `review_queue.csv` |
| `accepted` | everything tied out and every line is labeled | commit it |

Common blocks and their fixes:

- **`deposits_without_source`**: deposits look like payouts, but no export accounts for them. Ask for that export.
  If the source has no importer yet (PayPal today), confirm the deposits as an exception. The check keeps showing the
  confirmed total.
- **`shopify_payouts_to_bank` below 98%**: usually a missing week, a second bank account, or a payout export at a
  different grain. The unmatched payouts are listed by date and amount.
- **`orders_to_payouts`**: order totals do not match payout charges. This usually means an order export that repeats
  totals per line, or a subtotal column mapped as the total.
- **`rows_read`**: the mapping could not read part of a file. Check the date and number formats.
- **`bank_rows_present`**: no bank rows were read. Nothing can be accepted until there are.

## Working the review queue

Every item shows the model's guess and its confidence. Answer it once and the brand's memory keeps the answer for
the next upload, for lines whose words recur in the upload. A counterparty seen only once is not remembered yet;
holdout v2 caught this (product ask 5). Two rules:

1. **Never confirm a payout deposit without an export when the export exists.** Ask for the file instead.
   Confirmation is for sources the pipeline cannot import yet.
2. **When memory disagrees with itself** (two answers for one kind of line), it stops answering and asks again.
   Look at why: often it is two vendors whose memos differ only by an ID.

## Commit and repeat

```
python onboard/run.py data/raw/<brand> upload_1 --commit
```

Committing saves the accepted layouts and fingerprints every line, so the next export's overlap is dropped. The
second upload should need far fewer answers; on the development brands it went from 7.0 to 1.3 items per brand.

## What to log as product feedback

Any time a check blocks for a reason that is not the brand's fault (a new export format, a processor with no importer,
a date style), add it to `docs/product_asks.md` with the brand count. Patterns across brands are what turn into
product work.
