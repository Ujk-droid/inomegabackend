-- Omega Scales — Phase 2 schema (PRD Sections 5.0, 5.1, 5.3, 5.4.B/C/D/E)
-- Incremental migration on top of db/schema.sql (already applied to the live
-- Supabase project in Phase 1). Run this file next, in the SQL editor or via
-- psql "$DATABASE_URL" -f db/schema_phase2.sql — it does not re-run Phase 1's DDL.
--
-- v2 — corrects a real bug in v1 of this file: customer_ledgers/purchases had
-- item_code/qty/rate as single columns, meaning one invoice could only ever
-- hold one item. The PRD's Section 5 was updated to fix this: customer_ledgers
-- and purchases are now HEADER rows only; the line items live in two new
-- tables, invoice_line_items and purchase_line_items (one row per product per
-- invoice/purchase, matching the real Sale/Purchase form's "Add To List" table).
-- If v1 of this file was already run against a live project, drop and recreate
-- customer_ledgers/purchases (they're new, empty tables at this point in the
-- build — Phase 3 hasn't started sending real invoices yet) before re-running.
--
-- Design decisions made where the PRD's schema text is still ambiguous (see
-- progress.md for the full rationale):
--   1. payment_method (Section 5.0) is replaced by particular_id, per Section
--      5.4.F's explicit instruction that payment_method's fixed ENUM is
--      superseded by the particulars master table.
--   2. received_at_sale (Section 5.4.D) does not net into the current_balance
--      running-balance chain — that chain follows Section 5.0's literal formula
--      (previous_balance +/- total_amount by txn_type only). received_at_sale is
--      used only for this invoice's own Received-column display and its
--      invoice_status calculation, consistent with Section 5.3's own "honest
--      note" that a payment isn't formally linked to one invoice.
--   3. discount_amount applies once per invoice/purchase (header-level), not
--      per line item — this is explicit in the PRD text now ("applies once per
--      invoice, not per line") and matches Section 2.3's single "Special
--      Discount" field on the printed invoice.
--   4. A Correction Entry ("Fix This Invoice") does not get its own
--      invoice_line_items rows — its total_amount is a signed delta applied to
--      the balance chain (Section 5.1), with correction_reason carrying the
--      human-readable explanation of what changed. The corrected line items (if
--      any were given) are used only to compute that delta, not persisted as a
--      second line-item set.
--   5. Purchases keep their own balance chain per supplier party_id, separate
--      from customer_ledgers — the PRD gives purchases its own previous_balance/
--      current_balance columns rather than reusing customer_ledgers, so a party
--      acting as both customer and supplier currently has two independent
--      balances, not one unified figure.
--   6. Stock adjusts per line item on write (decrement on Sale finalize,
--      increment on Purchase create) — one adjust_stock call per line, not one
--      per invoice/purchase.

CREATE TYPE transaction_type AS ENUM ('sale', 'receiving');
CREATE TYPE invoice_status AS ENUM ('unpaid', 'partial', 'paid', 'overdue');
CREATE TYPE quote_status AS ENUM ('pending', 'approved', 'rejected');

CREATE TABLE customer_ledgers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    party_id UUID REFERENCES parties(id) ON DELETE RESTRICT,
    invoice_no VARCHAR(50) UNIQUE,
    invoice_state VARCHAR(20) DEFAULT 'draft',              -- 'draft' | 'finalized' (Section 5.1)
    correction_of UUID REFERENCES customer_ledgers(id),      -- set only on a Correction Entry row
    correction_reason TEXT,                                  -- required when correction_of is set
    due_date DATE,
    invoice_status invoice_status DEFAULT 'unpaid',
    txn_type transaction_type NOT NULL DEFAULT 'sale',        -- 'sale' = Debit, 'receiving' = Credit
    particular_id UUID REFERENCES particulars(id),            -- payment method, replaces the old ENUM (5.4.F)
    bank_account_id UUID REFERENCES bank_accounts(id),        -- Section 5.4.E
    payment_reference VARCHAR(100),                            -- cheque no. / transaction ID
    payment_note TEXT,
    transaction_date DATE NOT NULL,
    discount_amount DECIMAL(12,2) DEFAULT 0.00,                -- once per invoice, not per line (Section 2.3)
    total_amount DECIMAL(12,2) NOT NULL,                       -- SUM(invoice_line_items.line_total) - discount_amount
    received_at_sale DECIMAL(12,2) DEFAULT 0.00,               -- Section 5.4.D
    previous_balance DECIMAL(12,2) DEFAULT 0.00,
    current_balance DECIMAL(12,2) NOT NULL,
    pdf_cloudinary_url TEXT,
    approval_status quote_status DEFAULT 'approved',           -- 'pending' if above Human Gate threshold
    deleted_by UUID REFERENCES users(id),
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ledgers_party_date ON customer_ledgers (party_id, created_at DESC);
CREATE INDEX idx_ledgers_invoice_state ON customer_ledgers (invoice_state);

-- Fixes the real bug: one invoice can now hold many items. A 'receiving'
-- (payment) row has zero rows here — line items only exist for 'sale' rows.
CREATE TABLE invoice_line_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ledger_id UUID REFERENCES customer_ledgers(id) ON DELETE CASCADE NOT NULL,
    item_code VARCHAR(100) REFERENCES inventory_items(item_code) NOT NULL,
    qty INT NOT NULL,
    rate DECIMAL(12,2) NOT NULL,
    line_total DECIMAL(12,2) NOT NULL,       -- qty * rate for this one line
    line_number INT NOT NULL,                 -- display order, matches the "Sno" column (Section 2.3)
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_line_items_ledger ON invoice_line_items (ledger_id, line_number);

-- ── Purchases (Section 5.4.B — mirror of Sale, buyer's side) ───────────────────
CREATE TABLE purchases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    purchase_bill_no VARCHAR(50) UNIQUE,           -- auto-numbered, same rule as Section 5.3
    party_id UUID REFERENCES parties(id) NOT NULL,
    transaction_date DATE NOT NULL,
    discount_amount DECIMAL(12,2) DEFAULT 0.00,
    total_amount DECIMAL(12,2) NOT NULL,            -- SUM(purchase_line_items.line_total) - discount_amount
    received_amount DECIMAL(12,2) DEFAULT 0.00,     -- what WE have paid the supplier so far
    previous_balance DECIMAL(12,2) DEFAULT 0.00,
    current_balance DECIMAL(12,2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_purchases_party_date ON purchases (party_id, created_at DESC);

CREATE TABLE purchase_line_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    purchase_id UUID REFERENCES purchases(id) ON DELETE CASCADE NOT NULL,
    item_code VARCHAR(100) REFERENCES inventory_items(item_code) NOT NULL,
    qty INT NOT NULL,
    rate DECIMAL(12,2) NOT NULL,
    line_total DECIMAL(12,2) NOT NULL,
    line_number INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_purchase_line_items_purchase ON purchase_line_items (purchase_id, line_number);

-- ── Expenses (Section 5.4.C) ────────────────────────────────────────────────────
CREATE TABLE expenses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    serial_number SERIAL,
    expense_date DATE NOT NULL,
    party_id UUID REFERENCES parties(id),           -- optional; not every expense has a party
    description TEXT,
    amount DECIMAL(12,2) NOT NULL,
    particular_id UUID REFERENCES particulars(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_expenses_date ON expenses (expense_date DESC);

-- Section 5.2's harness deny-rule reminder: bulk DELETE/TRUNCATE on customer_ledgers
-- is denied at the harness level (.claude/settings.json) — that rule was already
-- added preemptively in Phase 1 and needs no change now that the table exists.
