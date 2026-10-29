# How the money is treated

What the code does today with the items a finance reviewer asks about first. This is a **cash ledger**: every
line is a movement of money in the bank or on the card, labeled by what it is. It does not produce an accrual P&L.
Built by Avinash Rayudu.

| Item | What the code does | What it does not do |
|---|---|---|
| **Shopify payouts (net of fees and refunds)** | A payout is one deposit. It is matched to the bank to the cent within 3 days and labeled `processor_payout`. Separately, order charges are compared with payout *charges* (before fees) at the brand's payout lag, within 0.5%, which proves the orders export is complete. Customer receipts for the DTC channel are the sum of payout deposits. | It does not split a payout into gross sales, processing fees and refunds as separate ledger lines. Gross charges and the net deposit are both read, so the fee is the difference, but it is not booked as its own line. |
| **Sales tax collected** | Collected tax rides inside the order totals and the payout charges, so it is inside customer receipts. Tax remitted to the state is its own label, `sales_tax`. | It does not carve collected tax out of receipts or track a tax liability. A revenue figure would need tax removed using the orders export. |
| **Refunds and chargebacks** | They reduce the payout they are netted in, so the deposit already reflects them. The payouts export is read at the grain it comes in; transaction-level exports are rolled up to payouts first. | It does not move a refund back to the period of the original sale. Timing follows the payout date, which is the cash view. |
| **Amazon settlements and the reserve** | The deposit is the settlement's transfer amount, matched to the bank within 5 days and labeled `marketplace_payout`. For flat settlement files, the detail rows are checked to sum to the settlement total. A held reserve simply makes that deposit smaller; a released reserve makes a later one larger. | The reserve is not tracked as money owed to the brand. A brand with a large reserve would see receipts move between weeks, correctly in cash terms, with no receivable shown. |
| **Faire** | Payout deposits are matched within 3 days and labeled `wholesale_payout`. Where the export has wholesale totals and commission, each row is checked so that payout equals wholesale total minus commission. | Commission is not booked as its own expense line. |
| **Direct wholesale customers** | Their payments are labeled `wholesale_receipt` and count as wholesale receipts. There is no export to prove them, so a new customer usually goes to review. | No accounts receivable: an unpaid invoice is invisible until the cash lands. |
| **Card spend and the card bill** | Card charges carry the spend. The bank payment of the card bill is matched to the card's payment rows and labeled `card_payment`, which is excluded from spend so ad spend is not counted twice. | Card spend is recognized when charged on the card, not when the bill is paid. |
| **Transfers, loan draws, vendor refunds, interest** | Labeled separately and kept out of customer receipts. Transfers between the brand's own accounts are identified by account digits from the kickoff call and must net to zero across accounts. | Loan draws are not tracked as a liability balance. |

## The three-way match, and where this project stops

Accounts payable is usually controlled by matching purchase order, receiving and vendor invoice before paying. This
project does not see purchase orders or invoices; it sees the payment after it happens and labels it, for example as
`inventory_purchase` or `fulfillment_3pl`. A three-way match has to happen before money moves, from the purchase
order, receiving and invoice records. The concepts are laid out in [finance_concepts.md](finance_concepts.md).
