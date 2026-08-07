-- Omega Scales — Phase 5 schema. Incremental migration on top of db/schema.sql,
-- db/schema_phase2.sql, db/schema_phase3.sql, and db/schema_phase4.sql (all
-- already applied to the live Supabase project).
-- Run this file next: SQL editor, or psql "$DATABASE_URL" -f db/schema_phase5.sql

-- ── Notification Preferences (Screen 10 Settings) ───────────────────────────
-- Per-user, one row per user, created lazily on first read/write (the service
-- layer returns all-on defaults if no row exists yet, so existing users don't
-- need a backfill). Three toggles only — the ones actually wired to a real
-- send path: the daily digest (low stock + overdue), the Human Gate pending
-- notification, and the Staff login-approval-request notification.
CREATE TABLE notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    low_stock_digest BOOLEAN NOT NULL DEFAULT TRUE,
    human_gate_approval BOOLEAN NOT NULL DEFAULT TRUE,
    login_approval_request BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
