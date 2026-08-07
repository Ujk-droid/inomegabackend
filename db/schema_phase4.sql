-- Omega Scales — Phase 4 schema (frontend build discovered these gaps; see
-- progress.md's "Phase 4 (frontend) discovered ... backend gaps" entries for
-- the full story of each). Incremental migration on top of db/schema.sql,
-- db/schema_phase2.sql, and db/schema_phase3.sql (all already applied to the
-- live Supabase project).
-- Run this file next: SQL editor, or psql "$DATABASE_URL" -f db/schema_phase4.sql

-- ── Party-specific negotiated rates (Section 5.4.J "Low Price") ─────────────
-- Copied verbatim from the PRD's own SQL. One row per (party, item) — the
-- Invoice Builder's "Low Price" dropdown reads this to offer a party's actual
-- negotiated rate for the selected item, alongside the flat "10% off" option.
CREATE TABLE party_item_rates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    party_id UUID REFERENCES parties(id) NOT NULL,
    item_code VARCHAR(100) REFERENCES inventory_items(item_code) NOT NULL,
    negotiated_rate DECIMAL(12,2) NOT NULL,
    UNIQUE(party_id, item_code)
);

-- ── Scan Slip's original image (Section 5.4.K) ──────────────────────────────
-- "The original scanned image is kept attached to that invoice ... as a
-- reference." One column, nullable — most invoices are never built from a
-- scanned slip at all.
ALTER TABLE customer_ledgers ADD COLUMN IF NOT EXISTS scan_slip_cloudinary_url TEXT;
