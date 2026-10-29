# Holdout v2, blind run

Run once on 2026-10-29T02:23:58+00:00 against the code and models recorded in `evals/FREEZE_v2.json`. Nothing in this folder is edited after the run.

| brand | upload | first-pass status | failed checks | auto-labeled | precision | wrong labels | review items | final status |
|---|---|---|---|---|---|---|---|---|
| fieldnote-paper | upload_1 | ties out, items open | - | 94.7% | 100.0% | 0 | 13 | accepted |
| fieldnote-paper | upload_2 | ties out, items open | - | 98.6% | 100.0% | 0 | 4 | accepted |
| harbor-and-hive | upload_1 | blocked | shopify_payouts_to_bank, amazon_to_bank, faire_to_bank | 46.3% | 100.0% | 0 | 6 | blocked (rows_read, shopify_payouts_to_bank, amazon_to_bank, faire_to_bank) |
| harbor-and-hive | upload_2 | blocked | rows_read, shopify_payouts_to_bank, amazon_to_bank, faire_to_bank | 48.2% | 100.0% | 0 | 1 | blocked (rows_read, shopify_payouts_to_bank, amazon_to_bank, faire_to_bank) |
| vale-street-tea | upload_1 | ties out, items open | - | 99.4% | 100.0% | 0 | 3 | ties out, items open |
| vale-street-tea | upload_2 | ties out, items open | - | 95.4% | 100.0% | 0 | 7 | accepted |

## All three brands

| upload | lines | auto-labeled | precision | wrong labels | review items per brand | blocked on first pass | accepted after review |
|---|---|---|---|---|---|---|---|
| upload_1 | 621 | 78.1% | 100.0% | 0 | 7.3 | 1 | 1/3 |
| upload_2 | 559 | 79.8% | 100.0% | 0 | 4.0 | 1 | 2/3 |
