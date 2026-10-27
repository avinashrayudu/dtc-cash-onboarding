"""
The standard every brand's files get mapped into.

Each source type lists its standard fields, what kind of values each field holds,
and the header names I have seen used for it. Header names alone are never
enough: the mapper also checks the values (dates parse, money parses, IDs are
distinct) before it accepts a column.

Built by Avinash Rayudu.
"""

F = lambda kind, syn, req=False: {"kind": kind, "syn": syn, "required": req}

SCHEMAS = {
    "bank": {
        "fields": {
            "date": F("date", ["posting date", "post date", "date", "transaction date", "date utc", "booking date",
                               "value date", "trans date"], True),
            "description": F("text", ["description", "memo", "transaction description", "bank description",
                                      "narrative", "details", "payee"], True),
            "amount": F("money", ["amount", "transaction amount", "amount usd", "amt", "value"]),
            "debit": F("money", ["debit", "debits", "withdrawals", "withdrawal amount", "money out", "paid out"]),
            "credit": F("money", ["credit", "credits", "deposits", "deposit amount", "money in", "paid in"]),
            "balance": F("money", ["balance", "running bal", "running balance", "ledger balance",
                                   "available balance"]),
            "account": F("any", ["account", "account number", "source account", "account name", "acct"]),
            "direction": F("enum", ["transaction type", "dr cr", "cr dr", "debit credit", "direction",
                                    "debit credit indicator", "type"]),
        },
        "one_of": [["amount"], ["debit", "credit"]],
        "tokens": ["balance", "running", "posting", "debit", "credit", "deposits", "withdrawals", "source account"],
    },
    "card": {
        "fields": {
            "date": F("date", ["transaction date", "date", "posted date", "post date", "trans date"], True),
            "description": F("text", ["description", "payee", "merchant", "merchant name", "details"], True),
            "amount": F("money", ["amount", "charge amount", "transaction amount", "amt"], True),
            "txn_type": F("enum", ["type", "transaction type"]),
        },
        "tokens": ["card member", "payee", "merchant", "category", "reference number", "card"],
    },
    "orders_list": {
        "fields": {
            "order_id": F("id", ["name", "order id", "order", "order number", "order name", "order no"], True),
            "created_at": F("date", ["created at", "order date", "created", "processed at", "date"], True),
            "total": F("money", ["total", "order total", "total price", "grand total"], True),
            "subtotal": F("money", ["subtotal", "order subtotal", "sub total"]),
            "shipping": F("money", ["shipping", "order shipping", "shipping price"]),
            "taxes": F("money", ["taxes", "tax", "order tax", "total tax"]),
            "discount": F("money", ["discount amount", "order discount", "discount"]),
            "currency": F("enum", ["currency"]),
        },
        "tokens": ["lineitem", "order", "subtotal", "sku", "qty", "financial status", "fulfillment"],
    },
    "sales_daily": {
        "fields": {
            "day": F("date", ["day", "date"], True),
            "orders": F("int", ["orders", "order count"]),
            "gross_sales": F("money", ["gross sales"], True),
            "discounts": F("money", ["discounts"]),
            "returns": F("money", ["returns", "refunds"]),
            "net_sales": F("money", ["net sales"]),
            "shipping": F("money", ["shipping"]),
            "taxes": F("money", ["taxes", "tax"]),
            "total_sales": F("money", ["total sales"], True),
        },
        "tokens": ["gross sales", "net sales", "total sales", "returns"],
    },
    "payouts": {
        "fields": {
            "payout_date": F("date", ["payout date", "date", "paid on", "deposit date"], True),
            "net": F("money", ["total", "net", "net amount", "payout amount"], True),
            "charges": F("money", ["charges", "gross", "gross amount", "sales", "amount"], True),
            "txn_type": F("enum", ["type", "transaction type"]),
            "refunds": F("money", ["refunds"]),
            "fees": F("money", ["fees", "fee"]),
            "adjustments": F("money", ["adjustments", "adjustment"]),
            "payout_id": F("id", ["payout id", "id"]),
            "status": F("enum", ["status"]),
            "currency": F("enum", ["currency"]),
        },
        "tokens": ["payout", "charges", "fees", "reserved funds", "retried"],
    },
    "amazon_flat": {
        "fields": {
            "settlement_id": F("id", ["settlement id"], True),
            "deposit_date": F("date", ["deposit date"], True),
            "total_amount": F("money", ["total amount"], True),
            "amount": F("money", ["amount"], True),
            "amount_description": F("text", ["amount description"]),
            "amount_type": F("enum", ["amount type"]),
            "transaction_type": F("enum", ["transaction type"]),
            "posted_date": F("date", ["posted date"]),
            "settlement_start": F("date", ["settlement start date"]),
            "settlement_end": F("date", ["settlement end date"]),
            "order_id": F("id", ["order id"]),
            "currency": F("enum", ["currency"]),
        },
        "tokens": ["settlement", "amount description", "deposit date", "posted date"],
    },
    "amazon_range": {
        "fields": {
            "date_time": F("date", ["date time", "date", "posted date"], True),
            "settlement_id": F("id", ["settlement id"], True),
            "type": F("enum", ["type", "transaction type"], True),
            "total": F("money", ["total"], True),
            "description": F("text", ["description"]),
            "order_id": F("id", ["order id"]),
            "product_sales": F("money", ["product sales"]),
            "selling_fees": F("money", ["selling fees"]),
            "fba_fees": F("money", ["fba fees"]),
            "other": F("money", ["other"]),
        },
        "tokens": ["settlement", "fba fees", "selling fees", "product sales", "marketplace"],
    },
    "faire": {
        "fields": {
            "order_number": F("id", ["order number", "order", "order id", "order no", "order number"]),
            "retailer": F("text", ["retailer", "store name", "store", "customer"]),
            "order_date": F("date", ["order date", "date placed", "placed on"]),
            "ship_date": F("date", ["ship date", "date shipped", "shipped on"]),
            "payout_date": F("date", ["payout date", "paid out on", "paid on"], True),
            "wholesale_total": F("money", ["wholesale total", "order value", "order total", "wholesale"]),
            "commission": F("money", ["commission", "faire fee", "commission amount"]),
            "payout_amount": F("money", ["payout", "net payout", "payout amount"], True),
        },
        "tokens": ["retailer", "commission", "faire", "wholesale", "store name", "paid out"],
    },
    "coa": {
        "fields": {
            "number": F("int", ["account number", "number", "acct no", "account code", "code", "no"]),
            "name": F("text", ["account name", "name", "full name", "account", "title"], True),
            "type": F("enum", ["type", "account type", "class"], True),
        },
        "tokens": ["account", "type", "detail type", "full name"],
    },
}

COA_TYPE_WORDS = {"bank", "income", "expense", "expenses", "cost of goods sold", "credit card", "equity",
                  "other current liabilities", "long term liabilities", "other expense", "other income",
                  "accounts receivable", "accounts payable", "fixed assets", "other current assets", "revenue",
                  "liability", "asset"}
