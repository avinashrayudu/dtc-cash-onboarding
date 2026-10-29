# The finance concepts behind these projects

A plain-language guide to the ideas the three projects and the Zacao Chocolate work rest on, with where each one
shows up. The same file is in all three repositories. Built by Avinash Rayudu.

| Concept | In plain language | Where it shows up |
|---|---|---|
| Cash basis | Record money when it moves: a deposit lands, a bill is paid. | The ledger in dtc-cash-onboarding and the forecast in forecast-health-monitor are both cash. |
| Accrual basis | Record revenue when it is earned and costs when they are owed, whether or not cash has moved. A P&L is accrual. | Fernwood's plan P&L ($8.4M revenue, about 5% operating margin) is accrual; the 13-week forecast turns it into cash dates. |
| Accounts receivable (AR) | Money customers owe the brand: an invoice sent but not yet paid. | Zacao: 106 open invoices, $12,171.47, reconciled; stores actually owed about $910. Wholesale receipts by retailer in forecast-health-monitor. |
| Accounts payable (AP) | Money the brand owes vendors: a bill received but not yet paid. | Bills with terms, due dates and early-pay discounts in forecast-health-monitor; a planted "AP bills not connected" gap in workflow-reliability-lab. |
| Three-way match | Pay a vendor only when the purchase order, the record of what arrived and the vendor's invoice agree. | Not built here; see the note below. |
| Reconciliation (tie-out) | Prove two independent records of the same money agree before trusting either. | Every gate check in dtc-cash-onboarding; payment trackers against Finaloop and bank deposits at Zacao. |
| Net payout | A processor deposits sales minus fees, refunds and reserves, not gross sales. | Shopify, Amazon and Faire payouts in dtc-cash-onboarding. |
| Sales tax | Collected for the state; it is a liability, not revenue. | Inside receipts on a cash ledger; remittance is its own label. |
| Credit line | Borrow when cash dips, repay when it recovers; interest accrues only while drawn. | The $125,000 week-0 draw and the $225,000 Nov 16 draw for Fernwood. |
| Early-pay discount | "2/10 net 30" means 2% off if paid in 10 days instead of 30. | ShipNest 3PL's $69,211 invoice: paying early saves $1,384. |

## Cash vs accrual, and why the gap matters

A brand can be profitable on its P&L and still run out of cash. Inventory is paid for months before it sells, Shopify
pays out a few days after the sale, wholesale customers pay on net 30 or later, and a P&L shows none of that timing.
Fernwood is the example: a 5% operating margin on the plan, and closing cash that still falls to $194,498 in the week
of Nov 16, $105,502 under its $300,000 buffer, because a $520K inventory balance and $95K of freight land in the
same week as payroll and the card bill.

The two cash projects stay on a cash basis on purpose. A cash ledger can be proven against the bank to the cent;
accrual entries such as a receivable or a reserve owed to the brand cannot be seen in a bank file. What a cash
ledger does not show is written down in [accounting_treatment.md](https://github.com/avinashrayudu/dtc-cash-onboarding/blob/main/docs/accounting_treatment.md).

## AR: what is owed to the brand

On a cash ledger an unpaid invoice is invisible until the money lands. That is why receivables need their own
reconciliation, and it is the real work behind the [Zacao case study](https://www.avinashrayudu.com/work/zacao-receivables/): 106 open invoices totaling $12,171.47 looked
like unpaid revenue, but after matching invoices to deliveries, the payment trackers and bank deposits, stores owed
only about $910. The rest had been collected but not marked paid, was never delivered, or was refused at delivery.

In forecast-health-monitor, wholesale receipts are forecast by retailer and terms, so "a retailer paying late" is a
driver the monitor can name.

## AP: what the brand owes

Bills carry terms. The decision is when to pay each one: on the due date, early for a discount, or never late for a
vendor who would stop shipping. A 2/10 net 30 discount is worth about 37% a year (2% for paying 20 days early,
2/98 x 365/20), so borrowing at 11% to take it pays. With only $50K of credit headroom it stops paying: always paying
early pushed Fernwood's worst unplanned dip under the buffer to $140,937, while paying by the forecast held it to
$67,629 by giving up $9,894 of discounts.

## The three-way match

Before paying a vendor, three records should agree: the purchase order (what was ordered, at what price), the
receiving record (what arrived), and the vendor's invoice (what they are billing). A price or quantity mismatch
holds the payment.

None of the three projects builds a three-way match: they see payments after they happen. The closest thing in the
real Zacao work is on the receivables side, a match of invoice, delivery, payment tracker and bank deposit, where an
invoice for an order that never arrived was voided instead of chased. On the payables side the Zacao records show
bills created from email and an email-against-Finaloop check that found 4 bank lines in the wrong category ($9,843.47)
and 5 purchases missing, but no bill reconciliation.
