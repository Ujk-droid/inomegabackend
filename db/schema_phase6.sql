-- Omega Scales — Phase 6 schema (Section 16's "Real-World Additions" — Rizwan
-- Bhai's operational feedback). Incremental migration on top of db/schema.sql
-- through db/schema_phase5.sql (all already applied to the live Supabase project).
-- Run this file next: SQL editor, or psql "$DATABASE_URL" -f db/schema_phase6.sql

-- ── 16.4 Activity Log (who did what) — built first since 16.1/16.2/16.3/16.6 ─
-- all write to it. Append-only: no soft-delete column, on purpose (Section
-- 16.4: "the one table where even Admin cannot soft-delete rows — an audit
-- log that could be erased isn't an audit log").
CREATE TABLE activity_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) NOT NULL,
    action VARCHAR(100) NOT NULL,
    target_description TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_activity_log_created_at ON activity_log (created_at DESC);

-- ── 16.2 Stock Adjustment (physical count reconciliation) ───────────────────
CREATE TABLE stock_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_code VARCHAR(100) REFERENCES inventory_items(item_code) NOT NULL,
    previous_qty INT NOT NULL,
    counted_qty INT NOT NULL,
    delta INT NOT NULL,
    reason VARCHAR(50) NOT NULL,     -- 'damaged' | 'lost' | 'count_correction' | 'other'
    note TEXT,
    adjusted_by UUID REFERENCES users(id) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ── 16.3 Sales Return ────────────────────────────────────────────────────────
CREATE TABLE sales_returns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    original_invoice_id UUID REFERENCES customer_ledgers(id) NOT NULL,
    item_code VARCHAR(100) REFERENCES inventory_items(item_code) NOT NULL,
    qty_returned INT NOT NULL,
    reason TEXT,
    ledger_credit_id UUID REFERENCES customer_ledgers(id),
    processed_by UUID REFERENCES users(id) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ── 16.5 Delivery Challan ────────────────────────────────────────────────────
CREATE TABLE delivery_challans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID REFERENCES customer_ledgers(id) NOT NULL,
    challan_no VARCHAR(50) UNIQUE,
    delivered_at DATE,
    pdf_cloudinary_url TEXT,
    created_by UUID REFERENCES users(id) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ── 16.6 Payment Correction ("Fix This Payment") ────────────────────────────
ALTER TABLE customer_ledgers ADD COLUMN IF NOT EXISTS payment_correction_of UUID REFERENCES customer_ledgers(id);
ALTER TABLE customer_ledgers ADD COLUMN IF NOT EXISTS payment_correction_reason TEXT;

-- Note: 16.1 (Credit Limit Enforcement) needs no schema change — parties.credit_limit
-- already exists (Section 5, Phase 1). It only writes to activity_log above when
-- an Admin overrides the block.
