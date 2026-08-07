-- Omega Scales — Phase 1 schema (PRD Section 5, scoped to Section 13.0 Phase 1 tables)
-- Tables built now: parties, users, units, categories_1, categories_2, particulars,
-- bank_accounts, inventory_items.
--
-- Ordering note: the PRD's Phase 1 bullet lists these tables as
-- "parties, users, inventory_items, units, categories_1, categories_2, particulars, bank_accounts".
-- Section 5.4.F/G later ALTERs inventory_items to add category_1_id/category_2_id/unit as
-- foreign keys once those master tables exist. Since this is a fresh build (not a migration
-- replay of the PRD's draft history), those master tables are created directly here, before
-- inventory_items, so inventory_items can reference them from the start instead of via a
-- later ALTER TABLE. Run this file once, top to bottom, against a fresh Supabase project.
--
-- customer_ledgers, purchases, expenses, party_item_rates, inbox_messages, login_requests
-- are Phase 2/3 (Sections 5.0/5.1/5.4/9.1/3.1) and are NOT part of this file.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Parties (Section 5, generalized customers+suppliers per 5.4.A) ─────────────
CREATE TYPE party_type AS ENUM ('customer', 'supplier', 'both');

CREATE TABLE parties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    party_name VARCHAR(255) UNIQUE NOT NULL,
    party_type party_type DEFAULT 'customer',
    phone VARCHAR(50),
    email VARCHAR(255),
    address TEXT,
    credit_limit DECIMAL(12,2),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ── Users (Section 5 / Section 3 RBAC) ──────────────────────────────────────────
CREATE TYPE user_role AS ENUM ('admin', 'staff');

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role user_role DEFAULT 'staff',
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ── Units master with conversion factor (Section 5.4.G) ────────────────────────
CREATE TABLE units (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(20) UNIQUE NOT NULL,           -- 'pcs', 'box', 'carton', 'KG', 'Grms'
    conversion_factor DECIMAL(10,4) DEFAULT 1.0000
);

-- ── Configurable Category 1 / Category 2 / Particular lists (Section 5.4.F) ───
CREATE TABLE categories_1 (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE categories_2 (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE particulars (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) UNIQUE NOT NULL
);

-- ── Bank accounts (Section 5.4.E) ───────────────────────────────────────────────
CREATE TABLE bank_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bank_name VARCHAR(100) NOT NULL,   -- e.g. 'Meezan Bank', 'HBL', 'MCB', 'Cash Received'
    account_note TEXT,
    is_active BOOLEAN DEFAULT TRUE
);

-- ── Inventory items (Section 5 base + Section 5.4.F/G final column set) ────────
CREATE TABLE inventory_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_code VARCHAR(100) UNIQUE NOT NULL,      -- e.g. 'P-16-S-A-MK'
    item_name TEXT NOT NULL,
    category_1_id UUID REFERENCES categories_1(id),
    category_2_id UUID REFERENCES categories_2(id),
    unit UUID REFERENCES units(id),
    rate DECIMAL(12,2) NOT NULL,
    quantity_in_stock INT DEFAULT 0,
    min_threshold INT DEFAULT 5,
    cloudinary_image_url TEXT,
    cloudinary_public_id TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_inventory_item_name ON inventory_items USING gin (to_tsvector('english', item_name));
CREATE INDEX idx_inventory_category_1 ON inventory_items (category_1_id);
CREATE INDEX idx_inventory_category_2 ON inventory_items (category_2_id);

-- ── Seed data (values given explicitly in Section 5.4.F/G comments) ────────────
INSERT INTO categories_1 (name) VALUES
    ('All'), ('Indicator'), ('Load Cell'), ('Plat Form'),
    ('Key Pad'), ('Crane Scales'), ('Top Loading Scale')
ON CONFLICT (name) DO NOTHING;

INSERT INTO particulars (name) VALUES
    ('Cash'), ('Cheque'), ('Online'), ('Bank Transfer'), ('Discount')
ON CONFLICT (name) DO NOTHING;

INSERT INTO units (name, conversion_factor) VALUES
    ('pcs', 1.0000), ('box', 1.0000), ('carton', 1.0000),
    ('KG', 1.0000), ('Grms', 1.0000)
ON CONFLICT (name) DO NOTHING;

INSERT INTO bank_accounts (bank_name, account_note) VALUES
    ('Cash Received', 'Cash-in-hand pseudo-bank row, matches the real system''s own list')
ON CONFLICT DO NOTHING;
