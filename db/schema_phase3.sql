-- Omega Scales — Phase 3 schema (PRD Sections 3.1, 9.1, 12.1's Human Gate
-- threshold requirement). Incremental migration on top of db/schema.sql and
-- db/schema_phase2.sql (both already applied to the live Supabase project).
-- Run this file next: SQL editor, or psql "$DATABASE_URL" -f db/schema_phase3.sql
--
-- Design decisions made where the PRD's schema/text are still ambiguous:
--   1. PRD Section 3 says "Framework: Supabase Auth", but the users table built
--      in Phase 1 (db/schema.sql) is a plain custom table (password_hash,
--      user_role enum) with no Supabase Auth/GoTrue integration anywhere in the
--      code. Migrating to real Supabase Auth now would mean dropping/rebuilding
--      an already-applied, already-live table for no functional gain at this
--      scale (8-10 users). This migration continues the plain-password_hash
--      path instead: passlib/bcrypt for hashing, a self-issued JWT (python-jose)
--      delivered via an HTTP-only cookie. See progress.md for the full note.
--   2. app_settings is new, not in the PRD's literal schema text — added because
--      Section 12.1 requires the Human Gate threshold to be "Admin-editable...
--      actually changes gate behavior when saved," which a hardcoded .env value
--      can't do. Single-row table, seeded from AGENT_HUMAN_GATE_THRESHOLD.
--   3. login_requests and inbox_messages below are copied verbatim from the
--      PRD's own SQL (Sections 3.1 and 9.1 respectively) — no changes needed.

-- ── Login Approval Gate (Section 3.1) ───────────────────────────────────────
CREATE TYPE login_request_status AS ENUM ('pending', 'approved', 'rejected', 'expired');

CREATE TABLE login_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) NOT NULL,       -- the Staff member trying to log in
    status login_request_status DEFAULT 'pending',
    requested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID REFERENCES users(id),              -- which Admin (Bhai or the user) acted
    ip_address VARCHAR(50),
    note TEXT,
    deleted_at TIMESTAMPTZ                               -- soft delete, Section 5.2 rule
);

CREATE INDEX idx_login_requests_status ON login_requests (status, requested_at);

-- ── Auth support columns on the existing Phase 1 users table (Section 3) ───
-- Lockout (5 failed attempts -> 15 min lock) and Forgot Password (Screen 1,
-- Section 6) both need state that didn't exist in db/schema.sql's users table.
ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires TIMESTAMPTZ;

-- ── Gmail Inbox (Section 9.1) ────────────────────────────────────────────────
CREATE TABLE inbox_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    gmail_message_id VARCHAR(255) UNIQUE NOT NULL,
    gmail_thread_id VARCHAR(255) NOT NULL,
    from_email VARCHAR(255) NOT NULL,
    party_id UUID REFERENCES parties(id),                -- matched if the sender is a known party
    related_invoice_no VARCHAR(50),                       -- matched from thread/subject if possible
    subject TEXT,
    snippet TEXT,
    received_at TIMESTAMPTZ NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,                     -- soft delete, mirrors Gmail Trash
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_inbox_received ON inbox_messages (received_at DESC);

-- ── App Settings (new — Section 12.1's Admin-editable Human Gate threshold) ─
CREATE TABLE app_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    human_gate_threshold DECIMAL(12,2) NOT NULL DEFAULT 100000.00,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_by UUID REFERENCES users(id)
);

INSERT INTO app_settings (human_gate_threshold)
SELECT 100000.00
WHERE NOT EXISTS (SELECT 1 FROM app_settings);

-- ── Harness deny-rule note (Section 5.2's pattern, extended) ────────────────
-- Add to .claude/settings.json's deny list alongside the existing
-- customer_ledgers rules — login_requests and inbox_messages are both
-- soft-delete-only tables, same retention philosophy:
-- Bash(psql *DELETE FROM login_requests*)   -> deny
-- Bash(psql *TRUNCATE login_requests*)      -> deny
-- Bash(psql *DELETE FROM inbox_messages*)   -> deny
-- Bash(psql *TRUNCATE inbox_messages*)      -> deny
