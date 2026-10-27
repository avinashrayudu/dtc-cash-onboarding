# Product asks from building and testing this

Patterns I would bring to a product team, each with the evidence from this project. These are synthetic brands, so
the counts show where to look, not how common each pattern is in real customers. Built by Avinash Rayudu.

## 1. "Not applicable" must never count as "passed"

**What happened.** In the blind holdout run, two of three brands were accepted although none of their bank data was
read: one because of an unsupported date format, one because its bank file was taken for a card statement. Every bank
check returned "not applicable", and a gate that only looks for failures let them through. Their customer receipts
were wrong by 100%.

**Ask.** Any acceptance gate should require positive evidence: at least one bank source read, every revenue export
tied to it, and no file silently losing rows. Absence of failure is not evidence.

**Success metric.** Zero brands accepted with receipts more than 1% off. After the fix: 0 of 13 brands, and 0 of 51
injected errors silently accepted.

## 2. A format profile library, not one-off parsers

**What happened.** Three of the four holdout failures were formats, not meaning:

- day-month-year dates with dashes;
- unsigned amounts with a DR/CR column;
- payouts exported one row per transaction.

Each took a small change, and each would recur across every brand using the same bank or export setting.

**Ask.** Keep a shared library of known export profiles: date style, sign convention, grain, delimiter, decimal mark.
Map each new brand's file to a profile first, and to columns second. Record which profile each brand used so a new
format is spotted once, not once per brand.

**Success metric.** Share of new brands whose files all match an existing profile on the first upload.

## 3. Processors without an importer need a first-class exception path

**What happened.** One holdout brand had PayPal deposits and no PayPal export. The gate flagged them, correctly. The
only way to accept the brand was a reviewer confirming those deposits as an exception, shown on the check with the
total.

**Ask.** Track confirmed exceptions per brand and source, and prioritize importers by how much confirmed money flows
through each unsupported source across customers.

**Success metric.** Confirmed-without-export dollars as a share of total customer receipts, trending down.

## 4. Memory should match on what is stable, not on what is similar

**What happened.** The first version of reviewer memory matched lines by word overlap. It labeled a freight
forwarder's invoice as a 3PL invoice because the two memos differed only by company name (2 wrong of 14 recalls on
development brands). Matching exactly on stable words fixed it: 37 of 37 recalls correct across development and
holdout brands. Stable words are the ones that recur across the upload; one-off reference IDs drop out.

**Ask.** Any "remember this answer" feature should key on the fields that identify the counterparty. When two
remembered answers conflict, it should go quiet rather than pick one.

**Success metric.** Precision of remembered answers on the next upload (here 100%) alongside the share of review
items they remove.
