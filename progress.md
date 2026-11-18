# Omega Scales Backend — Progress Spine (Section 7.1)

Records every invoice processed, every escalation, every Gmail dispatch, and every
low-stock digest sent, per the loop's spine-file convention. Phase 1 has none of
those yet (no invoices/ledger exist until Phase 2) — entries below are Phase 1's
foundation-build log instead.

## Phase 1 — Foundation (Database + Inventory CRUD)

- [x] Section 5 schema (Phase 1 scope): `parties`, `users`, `units`, `categories_1`,
      `categories_2`, `particulars`, `bank_accounts`, `inventory_items` — `db/schema.sql`
- [x] Section 7.2 harness `settings.json` deny/allow rules, plus Section 5.2's
      customer_ledgers bulk-delete deny rule applied preemptively — `.claude/settings.json`
- [x] Section 10 Inventory CRUD — manual create, list/search/paginate, get, update,
      delete (purge + Cloudinary cleanup), bulk Excel/CSV upload (upsert by
      item_code, up to 1,500 rows), template download
- [x] `.env` / `.env.example` — Section 11's full key list, placeholder values
- [x] Unit tests (`tests/unit/`) — pure row-validation logic, no DB
- [x] Integration tests (`tests/integration/`) — Inventory CRUD + bulk upload against
      an in-memory fake Supabase client (`tests/fake_supabase.py`), since real
      Supabase credentials aren't configured yet

**Verified against the live Supabase project** — real credentials are in `.env`,
`db/schema.sql` has been run, all Phase 1 tables confirmed in Table Editor.

**Exit test status (Section 13.0 Phase 1):** unit + integration test suite passing
locally (see `pytest` output). Bulk upload import/skip counts verified against a
small in-file test case (1 insert, 1 update, 1 skipped-with-error).

## Phase 2 — Invoice + Ledger + Purchase + Expenses Logic

**Correction (2026-07-31): fixed a real single-item-per-invoice bug.** v1 of this
phase modeled `customer_ledgers`/`purchases` with `item_code`/`qty`/`rate` as
single columns, so one invoice could only ever hold one product. The user
updated PRD.md's Section 5 to fix this at the schema level: `customer_ledgers`
and `purchases` are now header rows only (`party_id`, `invoice_no`,
`discount_amount`, `total_amount`, balances, etc.); the actual products live in
two new tables, `invoice_line_items` and `purchase_line_items` (one row per
product per invoice/purchase, `line_number` for display order — matches the
real Sale/Purchase form's "Add To List" table). `total_amount` is now
`SUM(line_totals) - discount_amount`, computed and re-verified per Section
7.3's hook at both the per-line level (`line_total == rate * qty`) and the
header level. Everything below already reflects the fixed schema — this note
exists so a future reader of this file understands why v1's "one row = one
invoice = one item line" design-decision note (previously #1 in this section)
is gone: it's not a caveat anymore, it's fixed. `customer_id` was also renamed
to `party_id` throughout (schema, models, services, routers, tests) to match
the PRD's updated column name.

- [x] `db/schema_phase2.sql` — `customer_ledgers` (header), `invoice_line_items`,
      `purchases` (header), `purchase_line_items`, `expenses`, plus the
      `transaction_type`/`invoice_status`/`quote_status` enums. **Not yet run
      against the live Supabase project — run this next**, same way as
      `db/schema.sql` was (SQL editor, or `psql "$DATABASE_URL" -f db/schema_phase2.sql`).
      If v1 of this file was already applied, drop the (still-empty)
      `customer_ledgers`/`purchases` tables first — see the file's header comment.
- [x] Section 2.2/5.0 running-balance formula (`app/services/ledger_math.py`),
      for both `sale` and `receiving` row types, plus Correction Entry's signed-delta
      variant and Purchase's mirrored version. Line-item math
      (`compute_line_total`, `compute_invoice_total`) is separate from the
      balance formulas — a line total is a per-product fact, total_amount/
      current_balance are invoice-level facts.
- [x] Section 5.1 draft-vs-finalized invoice lock + Correction Entry ("Fix This
      Invoice") — one Edit button, two behaviors, enforced server-side by
      `invoice_state`, never by which route the caller happens to call
- [x] Section 5.3 auto invoice numbering (`MAX(invoice_no::int)+1`, starts at 1 on
      an empty table — the PRD's raw SQL formula doesn't define this edge case),
      due date (`transaction_date + 15 days`), invoice_status (unpaid/partial/paid,
      plus overdue when a due date has passed — the *automatic daily* overdue-flip
      beat is Section 7.1's third heartbeat and is explicitly Phase 3, not built here)
- [x] Section 5.4.B Purchase module — auto-numbered `purchase_bill_no`, its own
      per-supplier balance chain, increments `inventory_items.quantity_in_stock`
- [x] Section 5.4.C Expenses module — optional party, `particular_id`, no balance chain
- [x] Section 7.3 harness verify hooks (`app/services/ledger_hooks.py`) — every
      ledger/purchase write re-validates the math/balance formulas immediately
      before the insert; a mismatch blocks the write and appends a line to this
      file under "HARNESS VIOLATION BLOCKED" (none have fired — this only trips on
      an internal bug, since callers never pass total_amount/current_balance in
      as untrusted input)
- [x] Section 7.4 Human Gate — `finalize_invoice` sets `approval_status='pending'`
      when `total_amount > human_gate_threshold`; Approve/Reject endpoints; a
      'receiving' row (Record Payment) is always pre-approved regardless of amount
- [x] Minimal Parties CRUD — not Screen 11, just enough (`POST/GET /api/v1/parties`)
      for Invoice/Purchase/Expense creation to reference a real `party_id` via the
      public API in tests, per Section 12.0 layer 2's spirit

**Design decisions made where the PRD's schema/text are still ambiguous** (see the
top-of-file comment in `db/schema_phase2.sql` for the full rationale):
1. `payment_method` (Section 5.0) is replaced by `particular_id`, per Section
   5.4.F's explicit "this replaces ... the payment_method ENUM" instruction.
2. `received_at_sale` (Section 5.4.D) does not net into the `current_balance`
   running-balance chain — that chain follows Section 5.0's literal formula only.
   `received_at_sale` drives this invoice's own Received-column display and its
   own `invoice_status`, consistent with Section 5.3's "honest note" that a later
   payment isn't formally linked back to one invoice.
3. `discount_amount` applies once per invoice/purchase (header-level), not per
   line item — explicit in the PRD text now, matches Section 2.3's single
   "Special Discount" field on the printed invoice.
4. A Correction Entry ("Fix This Invoice") doesn't get its own
   `invoice_line_items` rows — its `total_amount` is a signed delta applied to
   the balance chain; `correction_reason` plus the original's unchanged line
   items are the record of what it corrects.
5. Purchases keep their own balance chain per supplier `party_id`, separate from
   `customer_ledgers` — the PRD gives `purchases` its own `previous_balance`/
   `current_balance` columns rather than reusing `customer_ledgers`, so a party
   acting as both customer and supplier currently has two independent balances,
   not one unified figure. Not tested by Section 12.1's given acceptance criteria,
   but worth knowing before Phase 4's Party Detail page (Section 5.4.I) is built.
6. Stock adjusts per line item — decrements on Sale **finalize** (not draft
   creation), increments on Purchase **create**, one `adjust_stock` call per line.

**Exit test status (Section 13.0 Phase 2) — both required by name, re-confirmed
after the multi-item fix:**
- **United Scale Ijtibah golden ledger replay** (`tests/unit/test_ledger_math.py::test_united_scale_ijtibah_golden_ledger_replay`):
  every disclosed number from Section 2.2 (rows 280, 281, 307, and the END row's
  total debit/credit) reconciles exactly through `replay_ledger`. The PRD's own
  table shows "..." for the rows in between — those are bridged with two
  synthetic entries sized so all five real anchors check out simultaneously; see
  the test's docstring for the exact arithmetic. Untouched by the multi-item fix
  (it exercises the balance chain directly, not line items) — still green.
- **Invoice #2127, Rs. 184,500 Human Gate trigger** (`tests/integration/test_human_gate.py`):
  qty 15 × rate 12300 finalizes to `approval_status='pending'`, `can_dispatch=False`;
  a sub-threshold invoice and an invoice at exactly Rs. 100,000 (Section 7.4 is
  strictly-greater-than) both finalize pre-approved; a Rs. 500,000 payment never
  gates. Admin approve/reject endpoints both proven. New:
  `test_multi_item_invoice_above_threshold_triggers_gate` proves the gate checks
  the invoice header's total (sum of all lines minus discount), not any single
  line's amount.
- New: `test_multi_item_invoice_totals_correctly` and
  `test_multi_item_purchase_increases_stock_for_every_line` prove a multi-line
  invoice/purchase totals correctly and adjusts stock for every line, not just
  the first.
- Full suite: 70/70 passing locally (`pytest -q`).

**Verified against the live Supabase project (2026-07-31)** — a new suite,
`tests/integration_real/` (kept separate from `tests/integration/`, which stays
on the in-memory fake client as the default/CI-safe suite), talks to the real
`get_supabase()` client with no dependency override, and replays Phase 1+2's
Section 12.1 acceptance criteria directly against real Postgres: inventory
create/get, a zero-balance new party, a two-line invoice reproducing INV-2127's
math (qty x rate summed across lines, minus discount) that finalizes to
`approval_status='pending'`/`can_dispatch=False` above the Rs. 100,000
threshold and is then Admin-approved, a sub-threshold invoice that finalizes
pre-approved with the running balance correctly carried forward from the prior
invoice, a Rs. 150,000 payment that never gates and correctly credits the
balance, a two-line Purchase that increments stock for both lines, an Expense
row, and an unknown-master-table-name rejection (400, not a silent insert).
9/9 passed. Every row created is prefixed `ZZTEST_`/`ZZTEST-...` and deleted by
the suite's own teardown fixture (FK-safe order, runs even on failure) —
confirmed after the run that `parties`, `inventory_items`, `customer_ledgers`,
`purchases`, `expenses`, `invoice_line_items`, and `purchase_line_items` are
all back to 0 rows live. No new reference-table rows were needed: `db/schema.sql`'s
own seed data (`pcs`, `Cash`, `Bank Transfer`, `Cash Received`) already covered
everything this suite used.

**Real bug found and fixed:** `requirements.txt` pinned `supabase==2.9.1`,
whose client (`supabase/_sync/client.py`) validates the API key against a
JWT-shaped regex (`header.payload.signature`) and rejects anything else with
`SupabaseException: Invalid API key`. The real `SUPABASE_SERVICE_ROLE_KEY` in
`.env` is in Supabase's newer `sb_secret_...` key format, which that old client
version has never seen — every real-DB call failed at `get_supabase()` before
this was fixed. `tests/fake_supabase.py` could never have caught this, since it
never constructs a real `supabase.Client` at all. Fixed by upgrading to
`supabase==2.31.0` (pulls in matching `postgrest`/`storage3`/`realtime`/
`supabase-auth` versions and a `pydantic` bump to 2.13.4); the full local suite
(`pytest -q`, fake + real, 79 tests) passed clean immediately after the
upgrade, before any other change.

## Phase 3 — Everything Else Backend-Side (Section 13)

- [x] Section 3 / 3.1 — Auth foundation + Login Approval Gate. `db/schema_phase3.sql`
      adds `login_requests`, `inbox_messages`, `app_settings`, and lockout/reset
      columns on `users`. **Design deviation from the PRD's literal "Framework:
      Supabase Auth" text:** Phase 1's `users` table is a plain `password_hash` +
      `user_role` table with zero Supabase Auth/GoTrue integration anywhere in
      the code — migrating to real Supabase Auth now would mean dropping/
      rebuilding an already-live table for no functional gain at 8-10 users. Kept
      the plain-`password_hash` path instead: `passlib`/`bcrypt` hashing, a
      self-issued JWT (`python-jose`) in an HTTP-only cookie
      (`app/services/auth_service.py`, `app/dependencies.py`). `app/routers/auth.py`:
      Admin logs in directly; Staff always creates a `login_requests` row
      (`app/services/login_gate_service.py`) regardless of a correct password —
      the polling endpoint (`GET /auth/login-requests/{id}/status`) is what sets
      the session cookie the moment an Admin approves, so the waiting screen
      "proceeds automatically" without a second login. Whichever Admin
      approves/rejects first wins (conditional `UPDATE ... WHERE status='pending'`);
      the other gets a 409. 5 failed attempts locks an account for 15 minutes.
      `app/routers/users.py` (Screen 12) and `app/routers/login_approvals.py`
      (Screen 14) are both Admin-only.
- [x] RBAC retrofit onto every Phase 1/2 endpoint per Section 3's table — closes
      the "enforced once auth is wired in (Phase 3)" TODOs already sitting in
      `invoices.py`'s approve/reject docstrings. Admin-only: inventory
      create/update/delete/bulk-upload, invoice approve/reject/correct, user
      management, login approvals. Everything else: any authenticated user.
- [x] Bug fixed during this build: a `Secure` session cookie is never resent by
      a client over a plain-`http://` connection (local dev, `TestClient`,
      `tests/integration_real`'s real-DB suite) — was causing every
      post-login request to come back 401 even with a valid cookie set.
      `app/config.py`'s new `cookie_secure` now derives from whether
      `FASTAPI_BACKEND_URL` itself is `https://` (true once deployed behind
      Render's TLS, Section 14.2) instead of hardcoding `True`.
- [x] `tests/integration_real/conftest.py`'s `real_env` fixture updated with the
      same `get_current_user`/`require_admin` dependency override the fake-client
      `client` fixture uses — that suite proves real Supabase reads/writes, not
      the auth layer (which `tests/integration/test_auth.py` already covers), so
      it runs as an authenticated Admin without a real login round trip.
- [x] Section 9.2 — PDF (ReportLab, `app/services/pdf_service.py`) + Email (SMTP,
      `app/services/email_service.py`) + WhatsApp (`app/services/whatsapp_service.py`,
      a pure `wa.me` link builder — no API key, no automated send) dispatch,
      orchestrated by `app/services/invoice_dispatch_service.py`. Four new
      endpoints on `invoices.py`: `/generate`, `/share-email`, `/whatsapp-link`,
      `/reprint` (duplicate watermark, separate Cloudinary asset, original
      untouched) — all four gated on the existing `can_dispatch`/`approval_status`
      field, so WhatsApp/email can't bypass the Human Gate.
- [x] Section 12.1 — `app_settings` (single row) makes the Human Gate threshold
      Admin-editable at runtime (`GET/PATCH /api/v1/settings`) instead of a
      static `.env` read; Staff get the same endpoint with the field nulled out
      (Section 3.2's 'reduced view'). `ledger_service.finalize_invoice` now reads
      this live value instead of the static `app/config.py` one.
- [x] Section 7.1's second heartbeat + Section 5.3's deferred overdue flip —
      `app/services/scheduler.py`, one `BackgroundScheduler` (guarded by the new
      `ENABLE_SCHEDULER` flag, default off, so `pytest`/local dev never fires a
      real scheduled job against the real Supabase project by accident — Render
      sets it true). Three jobs: `flip_overdue_invoices` (runs first, so the
      digest reflects fresh statuses), `send_daily_digest` (low-stock + overdue,
      always sends even when both lists are empty), `expire_stale_login_requests`
      (every 1 minute, block 3B). `POST /api/v1/internal/run-digest` is a manual
      trigger (Admin-only) for testing without waiting for 8 AM.
- [x] Section 9.1 — Gmail Inbox. `app/services/gmail_client.py` wraps the Gmail
      API (OAuth via `GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN` — still `.env`
      placeholders as of this build, by the user's own choice: code built now
      against mocks, real credentials wired and smoke-tested later). No Pub/Sub
      push (too heavy for 8-10 users) — a 5-minute scheduler poll plus a manual
      `POST /api/v1/inbox/sync` (Admin-only) fetch recent mail and keep only
      messages matched to a known `parties.email` or a recognized `Invoice #N`
      subject (`app/services/inbox_service.py`); everything else is discarded,
      never shown. Full CRUD per Section 9.1: read/list, mark read/unread,
      reply (optionally attaching a stored invoice PDF link by invoice number),
      delete (Admin-only, soft-delete + Gmail Trash), and `generate-reply`
      (`app/services/ai_reply_service.py`, OpenAI — a real key is already
      configured — drafts into the compose box, **never auto-sends**).
- [x] Section 8 — all six Analytics queries (`app/services/analytics_service.py`):
      Monthly Sales & Revenue, Top Selling Models, Customer Debt/Ledger Balance,
      Low Stock Items, Payment Method Breakdown, Category-wise Sales. Every one
      reads the live `customer_ledgers`/`invoice_line_items`/`inventory_items`/
      `parties`/`particulars` tables directly (no cached/duplicated reporting
      dataset, per Section 12.1) and renders a Matplotlib PNG uploaded to
      Cloudinary (`cloudinary_client.upload_chart_image`) alongside the raw
      `data` list. Joins (line items -> parent ledger -> inventory item/category)
      are done in Python rather than postgrest embedding, so the same code runs
      against both the fake client and real Supabase.

**Exit status — all seven Phase 3 blocks (3A-3G):** 132/132 passing locally
against the in-memory fake client (`pytest -q`, all of `tests/unit/` +
`tests/integration/`). Two `tests/integration_real/test_real_supabase.py`
tests newly fail — not a regression, an expected/documented gap:
`db/schema_phase3.sql` has NOT yet been run against the live Supabase project,
so its `app_settings` table doesn't exist there yet and
`settings_service.get_human_gate_threshold`'s real-DB call 404s
(`Could not find the table 'public.app_settings'`). Everything else in that
suite (117 tests untouched by this phase) still passes clean. **Next step:**
run `db/schema_phase3.sql` against the live Supabase project (SQL editor, or
`psql "$DATABASE_URL" -f db/schema_phase3.sql`), then re-run the real-DB suite
to confirm Phase 3 end-to-end, same verification approach as Phase 2's.

**Verified against the live Supabase project (2026-07-31, after `db/schema_phase3.sql`
was applied)** — two new suites, `tests/integration_real/test_real_auth.py` (real
login/cookie round trip + Login Approval Gate race/RBAC, deliberately without
the `get_current_user`/`require_admin` override `real_env` uses elsewhere) and
`tests/integration_real/test_real_dispatch_settings_analytics.py` (Settings'
live gate-effect, real ReportLab PDF uploaded to and fetched back from real
Cloudinary, `/reprint`'s separate duplicate asset, `wa.me` link, scheduler
functions called directly against real Postgres, real Analytics chart PNGs,
Gmail Inbox sync). 9/9 new tests passed; the two `test_real_supabase.py` tests
that needed `app_settings` now pass too. Full suite: 141/141 passing
(fake + real combined).

**Real bug found and fixed:** the fake-admin id used by both `tests/conftest.py`'s
`client` fixture and `tests/integration_real/conftest.py`'s `real_env` fixture
(`get_current_user`/`require_admin` dependency overrides) was
`"...00000000adm1"` — not a syntactically valid UUID (`m` isn't hex), and not
backed by any real `users` row. Both were invisible against
`tests/fake_supabase.py` (never validates UUID syntax or FK existence), but
the moment a real write started persisting that id into a genuine UUID FK
column (`app_settings.updated_by`, this phase's Settings feature), real
Postgres correctly rejected it — first with `invalid input syntax for type
uuid`, then (after just fixing the format) `violates foreign key constraint
app_settings_updated_by_fkey`. Fixed by (1) using a syntactically valid
sentinel UUID (`99999999-...-999999999999`) in both fixtures, and (2)
`real_env` now inserts a real matching `users` row at setup and removes it at
teardown (nulling any `app_settings.updated_by` reference first, since that
column has no `ON DELETE` clause). This was a latent gap since Phase 1 —
nothing before Settings ever persisted the override id as a real FK.

**Credentials update mid-verification:** `GMAIL_APP_PASSWORD` and
`GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET`/`GMAIL_REFRESH_TOKEN` were all still
`.env` placeholders when Phase 3 was built and first real-DB-verified, but are
**real credentials as of this run** (the user supplied them alongside applying
`db/schema_phase3.sql`). Two tests originally written to expect a clean
502-on-placeholder now correctly exercise the real path instead: `/share-email`
genuinely sent one real email via the business's Gmail account (to a
`ZZTEST_...@example.com` address — reserved, non-deliverable domain, harmless),
and `POST /api/v1/inbox/sync` genuinely polled the real Gmail inbox (0 matches
against the live `parties`/`customer_ledgers` data, so nothing was inserted
into `inbox_messages`). `scheduler.send_daily_digest` was also called directly
against real Postgres as part of verifying the scheduler functions, which sent
one real "Daily Digest" email to every real active Admin in the live `users`
table — the same dated log line this appended to this file (just above) is
that real send, not test noise; `progress.md` is the spine file and this is
exactly what it's for.

**Cleanup confirmed:** every `ZZTEST_`/`ZZTEST-...` party, inventory item,
invoice, user, and login_request created by this run is gone —
`parties`/`inventory_items`/`customer_ledgers`/`invoice_line_items`/`users`/
`login_requests`/`inbox_messages` are all back to their pre-run state (0 rows,
since no real business users/parties exist in this system yet). Every
Cloudinary asset uploaded during verification (invoice PDF, its duplicate
reprint, two Analytics chart PNGs) was destroyed — confirmed via the Cloudinary
Admin API that both the `omega-scales/invoices` and `omega-scales/analytics`
folders are empty. `app_settings`'s `human_gate_threshold` is back to its
original `100000.00` and `updated_by` back to `NULL`.

- [2026-07-31T16:58:08.650470+00:00] Daily digest: 0 low-stock item(s), 1 overdue invoice(s), sent to 1/1 admin(s).
- [2026-07-31T17:05:38.792776+00:00] Daily digest: 0 low-stock item(s), 1 overdue invoice(s), sent to 1/1 admin(s).

## Incident (2026-07-31): real-DB verification sent more real mail than the user expected/authorized

The note two sections up ("Credentials update mid-verification") undersold this — the user's own inbox showed **many more** real test emails than the two/three sends that note accounted for, and asked for it to be fixed immediately. Root cause, once actually counted: it wasn't just the deliberate `/share-email` and `send_daily_digest` calls — **every** `test_real_auth.py` staff-login test (four of them) triggers `auth.py`'s `_notify_admins_of_pending_login`, which emails **every currently-active Admin in the real `users` table** (not just the two `ZZTEST_` admins that test created) — so each test run of that file alone sent several real notification emails to whatever real Admin accounts already exist live, on top of the digest/share-email sends. None of this was gated behind any opt-in; it fired the moment real Gmail credentials appeared in `.env`, because `email_service.send_email`'s only previous safety behavior was "swallow `EmailDispatchError` if creds are placeholder" — which stops protecting anything the moment the creds stop being placeholders.

**Fix — a session-wide default-deny, opt-in-only safety net, in both suites:**
- `tests/conftest.py`: new autouse `_never_hit_real_external_sends` fixture applies to **every** test in `tests/unit/` + `tests/integration/` (the fake-Supabase suite) unconditionally — monkeypatches `email_service.send_email`, `scheduler.send_email` (a separate direct-import binding — patching `email_service.send_email` alone does not cover it), and all four `gmail_client` functions, plus `ai_reply_service.generate_reply_draft`. This suite should never have been able to reach real SMTP/Gmail/OpenAI at all regardless of `.env` — it wasn't, in most files, only because individual test files happened to add their own per-test patches; this closes that gap globally, for every test, forever, not just the ones an author remembered to patch.
- `tests/integration_real/conftest.py`: same default-mock behavior, gated behind a new `ALLOW_LIVE_EXTERNAL_SENDS` env var that defaults to `false`. A deliberate, one-time live smoke test can set `ALLOW_LIVE_EXTERNAL_SENDS=true` to intentionally exercise the real integration — never implicit, never the default.
- Verified the fix doesn't break anything: `pytest tests/unit tests/integration -q` (fake suite only, zero network calls either way) — **125/125 passing**, including `test_inbox.py`'s own more-specific `gmail_client` mocks, which still correctly take precedence over the new global default (pytest fixture ordering: autouse fixtures resolve before the test-specific fixtures that further override them).
- The real-DB suite (`tests/integration_real/`) has NOT been re-run since this fix — that requires the user's go-ahead per their explicit request, and won't happen without it.

**Not a bug, confirmed directly:** the address `kamransteelw@gmail.com` the user asked about is the literal value of `GMAIL_USER` in `.env` (the configured sending account) — not anything hardcoded or fabricated by any test file or the agent. Every synthetic address used in test code is `@example.com` (a reserved, non-deliverable domain) or `@test.omega`.

**Re-verified against the live Supabase project with the safety net active (2026-07-31):** `ALLOW_LIVE_EXTERNAL_SENDS` left unset (defaults `false`) — `tests/integration_real/` (all three files: `test_real_supabase.py`, `test_real_auth.py`, `test_real_dispatch_settings_analytics.py`) **18/18 passing**, zero real email/Gmail/OpenAI calls made this time (all mocked by default, exactly as designed). Full combined suite (`pytest -q`, fake + real): **143/143 passing**, 163s.

## Phase 3 — COMPLETE

All three exit conditions met: (1) every block (3A auth/RBAC through 3G Analytics) built and unit/integration-tested against the fake Supabase client, (2) `db/schema_phase3.sql` applied to the live Supabase project and every new/changed code path re-verified against it end-to-end, (3) the real-mail incident triggered by this phase's own real-DB verification was root-caused, fixed with a default-deny safety net, and the fix itself re-verified before being trusted again. Per Section 13's build sequence, `omega-backend` has now passed its Phase 1-3 exit tests — `omega-frontend/` (Phase 4) can start.

**Known, deliberate gaps carried into Phase 4, not oversights:**
- The Login Approval Gate's live "badge/toast if Admin is online" half (Section 3.1) has no frontend to show it in yet — the backend delivers the polling endpoint and the email-alert half only; Phase 4 wires the actual badge.
- Gmail Inbox/Email dispatch are now provably correct against the real Gmail API and SMTP (not just mocks) as of this verification pass — real credentials are live in `.env`. Routine backend test runs will never touch them again (default-deny safety net); a deliberate live check still needs `ALLOW_LIVE_EXTERNAL_SENDS=true`.
- `ENABLE_SCHEDULER` stays `false` until actual deployment (Section 14.2, Render) — the three heartbeat jobs (daily digest, login-request expiry, Gmail sync) are fully tested by calling their functions directly, but the real `BackgroundScheduler` itself has never been started outside of tests.
- Party Detail's two-independent-balances caveat (customer vs. supplier, noted in Phase 2's design decisions) is still open — worth knowing before Phase 4's Party Detail screen (Section 5.4.I) is built.
- [2026-07-31T17:16:49.702363+00:00] Daily digest: 0 low-stock item(s), 1 overdue invoice(s), sent to 1/1 admin(s).
- [2026-07-31T17:20:13.501428+00:00] Daily digest: 0 low-stock item(s), 1 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-01T13:50:40.030007+00:00] Daily digest: 0 low-stock item(s), 1 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-01T17:36:54.711134+00:00] Daily digest: 0 low-stock item(s), 1 overdue invoice(s), sent to 1/1 admin(s).

## Phase 4 (frontend) discovered three real backend gaps — all fixed here (2026-08-01)

Building the Inventory List screen (Section 6, Screen 3) surfaced three things Phase 3's "complete" backend didn't actually support, caught before any frontend code was written against a guess:

1. **No endpoint listed `categories_1`/`categories_2` names.** The Inventory list/create/update endpoints already accept/filter by category *name* (`master_data.lookup_id_by_name`), but nothing exposed the live set of names for the Inventory List's Category 1/Category 2 filter tabs — Screen 3's prose names ("Load Cells / Indicators / Platform Scales / Spare Parts") don't even match the real seed data (`db/schema.sql`: All, Indicator, Load Cell, Plat Form, Key Pad, Crane Scales, Top Loading Scale), confirming the tabs must be built from live data, not hardcoded. Added `GET /api/v1/master-data/categories` (`app/routers/master_data.py`, `app/models/master_data.py`) — any authenticated user, read-only, returns `{category_1: string[], category_2: string[]}` sorted alphabetically. `'All'` is a literal seeded row in `categories_1` but is deliberately excluded from the response — the frontend builds its own "All Items" pseudo-tab that clears the filter rather than literally filtering `category_1='All'`.
2. **Bulk upload had no preview/dry-run.** Section 6 Screen 3's flow requires a Step 2 preview (parsed rows + insert/update/error counts) before Step 3's "Import N items" actually commits, but `POST /api/v1/inventory/bulk-upload` parsed, validated, *and wrote* in one atomic call — no way to show accurate counts without already having written the batch. Added a `dry_run: bool = Form(False)` param to the same endpoint (`app/routers/inventory.py`) — `app/services/bulk_upload.py`'s `process_bulk_dataframe` now takes `dry_run` and gates only the `create_item`/`update_item` writes behind `not dry_run`; row parsing, validation, and the insert-vs-update decision (an `existing = fetch_item_by_code(...)` read, safe in both modes) are identical either way, so preview and commit can never disagree. `BulkUploadResult` gained `preview_rows` (first 20 rows, `status: "insert"|"update"|"error"`) and `committed: bool`, both additive — existing callers of the old (non-dry-run) shape are unaffected.
3. **Same gap, `units` table.** The "+ Add New Item" modal's Unit field is validated server-side against the same kind of master table (`inventory_service` resolves `unit` via `master_data.lookup_id_by_name` too), with the identical no-listing-endpoint problem — a free-text field would be prone to the exact typo mismatch that lookup exists to catch. Added `GET /api/v1/master-data/units` (`UnitsOut`, same router/pattern) returning `{units: string[]}`, sorted.

All three are additive/backward-compatible — no schema change, no existing endpoint behavior altered. Unit/integration tests added against the fake client (`tests/integration/test_master_data_api.py`, plus two new cases in `tests/integration/test_inventory_api.py`); **verified against the live Supabase project** too (`tests/integration_real/test_real_master_data_and_bulk_upload.py`, `ZZTEST_`-prefixed, cleaned up by the existing teardown) — confirmed the real seeded category/unit names come back correctly (categories excluding `'All'`), and that `dry_run=true` against real Postgres genuinely writes nothing (item absent after preview) while a follow-up real commit with the identical file does create it. Full suite: **152/152 passing** (fake + real combined).
- [2026-08-01T17:56:39.054142+00:00] Daily digest: 0 low-stock item(s), 1 overdue invoice(s), sent to 1/1 admin(s).

## Real bug found and fixed: intermittent 500s on every authenticated endpoint (2026-08-02)

Building the Invoices List screen (Screen 6), the user reported the stats strip stuck on "Loading…" forever while the table below correctly rendered its empty state — a real discrepancy, not a one-off glitch. Traced to the backend log, not the frontend: `GET /api/v1/invoices` and `GET /api/v1/parties` were intermittently returning bare 500s (including on the very first request right after a fresh `uvicorn` restart, so this isn't purely an idle-connection thing), every one of them from the exact same traceback — `httpx.RemoteProtocolError: <ConnectionTerminated error_code:1, ...>` inside `get_current_user`'s own `users` table lookup (`app/dependencies.py`), which runs on *every* authenticated request. Root cause: `supabase-py`'s default postgrest client opens its `httpx.Client` with `http2=True` (confirmed live — `h2` is installed and `postgrest/_sync/client.py` hardcodes it), and this app's real network path to Supabase intermittently has that HTTP/2 connection torn down server-side while still sitting in httpx's keep-alive pool as "reusable" — the next request to reuse it dies with the GOAWAY/stream-reset error above, surfacing as a 500 on whatever endpoint happened to fire next, not necessarily the one that broke the connection.

**Fix:** `app/database.py`'s `get_supabase()` now passes a custom `httpx.Client(http2=False, timeout=120)` via `ClientOptions(httpx_client=...)`, forcing HTTP/1.1 for the postgrest client and removing this entire GOAWAY/stream-reset failure class. Confirmed safe to share across postgrest/storage/auth/functions sub-clients (supabase-py wires the same `httpx_client` into all of them) because this codebase never calls `.storage`/`.auth`/`.functions` on the Supabase client at all (Cloudinary + self-issued JWT are used instead, per Phase 3's design decision) — only `.table(...)` (postgrest) is ever exercised, and postgrest builds an absolute URL per request (`base_url.joinpath(...)`) rather than relying on the passed client's own `base_url`/headers, so a bare `http2=False` client is a safe drop-in.

**Verified against the live Supabase project:** 25 back-to-back `GET /api/v1/invoices` + `GET /api/v1/parties` calls after a fresh restart, plus 3 more with deliberate ~6s gaps between them (the idle-connection-reuse shape) — 28/28 clean 200s, where pre-fix the very first post-restart request had already failed. Full fake-client suite re-run clean too: **131/131 passing**, no regressions.

**Frontend hardening (`omega-frontend/app/(app)/invoices/page.tsx`), same investigation:** even with the backend fixed, the page was silently masking any future fetch failure as "zero invoices" (`invoices.data ?? []` in the table) while the stats strip separately stayed on an unexplained "Loading…" forever (`invoices.data` stays `null` on error, so the `stats` `useMemo` never resolves) — a real error looked indistinguishable from "no data yet" or "genuinely zero rows." Added an error toast on `invoices.error`/`parties.error`, and the header now reads "Couldn't load invoices — try refreshing." instead of an infinite "Loading…" if a fetch ever does fail again.

## Invoice Builder's three deliberate simplifications, built out (2026-08-02)

Screen 7's Low Price, Live PDF Preview, and Scan Slip were all stubbed/simplified when the Invoice Builder first shipped (see that entry above). Built out one at a time per the user's request, each verified against the live Supabase project (and, for Scan Slip, real OpenAI Vision + real Cloudinary) before moving to the next.

**1. Low Price — party-specific negotiated rates (Section 5.4.J).** `db/schema_phase4.sql` (new) adds `party_item_rates` (verbatim from the PRD's own SQL) plus `customer_ledgers.scan_slip_cloudinary_url` (prepping for block 3 below) — **applied to the live Supabase project by the user** after a real environment blocker: this sandbox only has IPv6 egress, but the project's direct Postgres port is IPv6-only, and guessing a connection-pooler region to route around it wasn't safe, so the user ran the migration themselves via the SQL editor, same as every prior phase's schema file. Two new endpoints: `GET /api/v1/parties/{id}/negotiated-rates/{item_code}` (any authenticated user — null is the normal "no rate set yet" case, not a 404) and `POST /api/v1/parties/{id}/negotiated-rates` (Admin-only, upserts on the `(party_id, item_code)` unique pair). The Invoice Builder's Low Price dropdown now shows the party's actual rate when one exists ("Negotiated Rate (Rs. 11,000)"), or — for Admins, when none exists yet — a "Set Negotiated Rate…" option that opens a small inline form and applies the rate immediately, so the feature doesn't need a separate management screen to be usable. 6 new tests. **Verified live:** created a throwaway party+item, confirmed null → set → get-matches, POSTed twice with different values and confirmed exactly one row (upsert, not a duplicate) via a direct table read, confirmed both not-found paths — all against real Postgres, then cleaned up.

**2. Live PDF Preview (Section 9.2).** New `POST /api/v1/invoices/preview-pdf` — takes the same shape as a draft (party, line items, discount, date, received), runs the identical math `create_draft_sale` uses, and renders through the *same* `pdf_service.build_invoice_pdf` the real dispatch path uses, so the preview can never drift from what finalizing would actually produce. Nothing is persisted: no draft row, no line items, no Cloudinary upload — just PDF bytes back in the response. **Real bug fixed in the same code path:** every invoice PDF's Unit column was silently stuck on "pcs" regardless of the item's actual unit — `pdf_service.py` read `item["unit_name"]`, but `invoice_dispatch_service._items_by_code`'s raw rows only ever had an embedded `unit_ref: {name}`, never a flat `unit_name` key. Fixed by flattening it in `_items_by_code`, which both the real dispatch path and this new preview path share — covered by a new unit test. Frontend: a debounced (800ms) "Live PDF Preview" panel in the Builder's sidebar, using a new `api.postBlob` client method and an `<iframe>` over an object URL; skipped entirely until a party + at least one item are selected, so it's not re-fetching Cloudinary thumbnails and re-rendering on every keystroke. 6 new tests. **Verified live:** generated a preview for the exact Invoice #2127 case (15 × Rs. 12,300) against a real throwaway party+item — came back byte-for-byte matching Section 2.3's layout, confirmed nothing was written to `customer_ledgers`/`invoice_line_items`, verified through both the raw backend and the Next.js proxy.

**3. Scan Slip (Section 5.4.K).** New `POST /api/v1/invoices/scan-slip` (`app/services/scan_slip_service.py`) — uploads the original photographed/uploaded slip to Cloudinary (`omega-scales/scan-slips`, kept as a permanent reference), sends it to OpenAI Vision (`gpt-4o-mini`, same `OPENAI_API_KEY` as Section 9.1's AI Reply, `response_format: json_object` for a guaranteed-parseable `{"items": [...]}` shape), then fuzzy-matches each extracted description against the real `inventory_items` catalog via stdlib `difflib.SequenceMatcher` (no DB extension or ML model needed at this catalog size) — `>=0.6` similarity is `"high"` confidence, `>=0.35` is `"low"`, below that is `"none"` (no item_code returned, forcing a manual pick). **Nothing is added to any invoice automatically** — the endpoint only ever returns a review list; `SaleDraftCreate`/`SaleDraftUpdate` gained an optional `scan_slip_cloudinary_url` field so the Builder can attach the scan to the invoice once the reviewed items are actually confirmed and saved. Frontend: a "Scan Slip" button opens a modal (camera-capture-capable file input via `capture="environment"`), shows each extracted line with its raw text, confidence badge, and an editable Qty/Rate/Item picker (pre-filled with the match, but always overridable, including for `"none"`-confidence rows) — only checked, resolved rows get added to the line-items list on "Add N Items." Same global test safety net extended (`conftest.py`) to block real OpenAI/Cloudinary calls by default for every test in the suite, not just this feature's own file. 9 new tests. **Verified live end-to-end** with a synthetic order-slip image (PIL-generated: "15 x Platform scale 400x400 SS top cap 150kg" / "5 x load cell 5 ton") against two real throwaway catalog items — the real OpenAI Vision call correctly extracted both lines (qty 15 and 5, no rate hallucinated since none was written on the slip) and matched both at `"high"` confidence; confirmed the Cloudinary URL it returned was a real, publicly fetchable asset (200), then destroyed that asset and deleted the two test items afterward.

All three: full fake-client suite **154/154 passing** throughout, no regressions. Every live-verification artifact (parties, inventory items, party_item_rates rows, the scan-slip Cloudinary asset) was created with a `ZZTEST` prefix and deleted immediately after its check, confirmed back to the pre-run row count each time.

## Purchase Builder route mismatch, fixed after a cross-repo session gap (2026-08-03)

A prior session built the frontend Purchase Builder (`omega-frontend/app/(app)/purchases/page.tsx`) without access to `omega-backend/`, so it guessed at API shapes instead of reading them. Checked every assumption against the real `app/routers/purchases.py`/`app/models/purchase.py` once both repos were visible:

- `POST /purchases` (→ `/api/v1/purchases`), the `PurchaseCreate`/`PurchaseOut` field names, and the `/parties/{id}/balance` and `/master-data/categories` calls the page also makes — **all correct**, no fix needed.
- `POST /purchases/preview-pdf` — **did not exist at all**. Only `/invoices/preview-pdf` had ever been built (Section 9.2); Purchase Builder's guess assumed the same endpoint existed for purchases too. Added it for real: `app/services/purchase_dispatch_service.py` (`build_purchase_preview_pdf`, mirrors `invoice_dispatch_service.build_preview_pdf` — unsaved-draft math, nothing persisted, shows "DRAFT" for the bill number) plus the router entry in `purchases.py`.
- **Second bug found in the same code path, not just a missing route:** the frontend's "Print & Save" button called this same preview endpoint a second time, with the original form payload, *after* already saving the purchase — meaning the "printed" PDF would have shown "DRAFT" instead of the real assigned `purchase_bill_no`, same mistake the invoice flow avoids by generating from the saved row. Fixed by adding `GET /purchases/{purchase_id}/pdf` (`build_purchase_pdf_for` — real saved row, real bill number, no Cloudinary upload since purchases have no email/WhatsApp dispatch to justify one) and pointing "Print & Save" at it instead (`api.getBlob`, new method on the frontend's `lib/api/client.ts`, mirroring `postBlob`).
- `pdf_service.py` refactored so both PDFs share one renderer (`_render_bill_pdf`) parametrized by label text (`INVOICE #`/`PURCHASE BILL #`, `To M/S:`/`Supplier:`, `Received (Rs.)`/`Paid (Rs.)`) — Section 5.4.B's "same layout discipline as Invoice Builder" instruction, made structural instead of just visual. `build_invoice_pdf`'s own signature/output is unchanged; existing tests (`test_invoice_dispatch.py`, `test_invoice_preview_pdf.py`, `test_invoice_dispatch_items_by_code.py`) all still pass untouched.
- New tests: `tests/integration/test_purchase_pdf.py` (preview + real-by-id, 404 cases, persists-nothing check). Full suite: **159/159 passing** (fake client only — this session had no live Supabase access to re-verify against the real project; that's still owed before this is considered fully verified like Phases 1-3 were).

**Same session's other ask — Section 9.2 PDF fixes, checked against what already existed before building anything new:**
- **Peacock accent color theme** and **product thumbnails** were **already fully implemented** in `pdf_service.py` (`COLOR_HEADER_BAND`/`COLOR_ACCENT`/`COLOR_ZEBRA`/`COLOR_TEXT` exactly matching Section 9.2's hex values, `_fetch_thumbnail` already pulling `cloudinary_image_url` per line) — from the Invoice Builder work logged above ("Invoice Builder's three deliberate simplifications"). Nothing to redo here; the frontend session's assumption that this was still plain black-and-white was stale.
- **Company logo in the PDF header** was the one genuinely missing piece. Copied `omega-frontend/public/logo.png` into `app/assets/logo.png` (kept inside this repo, not read cross-repo, so PDF generation never depends on the frontend checkout being present at deploy time) and added `_logo_image()` (same best-effort/never-break-generation convention as `_fetch_thumbnail`) into the shared header band, next to the existing "OMEGA SCALES" text block. Applies to both invoice and purchase PDFs automatically via the shared renderer above.

## PDF company watermark, polish pass, and live re-verification with a real product image (2026-08-03)

Same-day follow-up, after the user reviewed the fixes above and asked for three more things before considering this done.

**1. Section 9.2's new company watermark.** PRD.md now specifies a permanent, very faint diagonal "OMEGA SCALES" watermark on every generated PDF (not just duplicates) — `#0F6B7C` at ~6-8% opacity, much fainter than the existing 15%-opacity `DUPLICATE` stamp. Added `_company_watermark` to `pdf_service.py`, always drawn first (background layer) via a new `_page_decorations(duplicate)` page-callback factory; the `DUPLICATE` stamp (renamed `_duplicate_watermark` internally, same drawing logic, unchanged) layers on top of it when `duplicate=True` — both watermarks now apply automatically to invoice and purchase PDFs alike via the shared `_render_bill_pdf` renderer, per the PRD's explicit instruction that this ride on Section 16.2's refactor rather than be built twice.

**2. General polish pass on `_render_bill_pdf`** (both PDFs, since they share the renderer): the line-item table's Item Name column width is now computed as the exact remainder of `doc.width` after the other six fixed columns, instead of a `None` auto-width column, so the table always spans full margin-to-margin instead of shrink-wrapping to content; consistent `Helvetica`/9pt applied across every item-table cell (previously the item-name `Paragraph` was 9pt but the plain-string cells picked up ReportLab's default, an inconsistent mix); added a full `BOX`/`INNERGRID` around the items table instead of just `GRID`, tidied cell padding; the totals block gained an outer box, a column separator, a rule above the sub-total row and a stronger accent rule + zebra tint above "Total Payable" (the one figure Section 9.2 says should draw the eye); the header band gained a one-line tagline ("Industrial & Digital Weighing Systems", matching the PRD's own Domain description) under the address block; minor spacing/leading increases throughout so rows read as comfortable, not cramped.

**3. Live re-verification against the real Supabase project + real Cloudinary — with a real product image, not just a code-level claim.** New `tests/integration_real/test_real_purchase_pdf_verification.py`, deliberately *not* reusing the shared `real_env` fixture's Cloudinary patch (that fixture stubs `upload_item_image` to a fake, unfetchable `cdn.example.com` URL for the whole module — the entire point here was a genuine, fetchable image). Captured direct references to the real `cloudinary_client.upload_item_image`/`delete_item_image` functions at module-import time, before `real_env`'s `patch()` calls replace those names on the module — Python's `unittest.mock.patch` only rebinds the module attribute, not the function object a prior `from module import name` already captured, so this bypasses the stub cleanly without touching the shared fixture.

Flow proven end-to-end against live infra:
- Generated a synthetic "platform scale" JPEG (PIL: stainless deck + indicator head, matching Section 2.1's own description of the product line), uploaded it for real to Cloudinary, and set the returned URL directly on a throwaway `ZZTEST-SCALE-<run>` inventory item.
- **Purchase Builder:** `POST /purchases/preview-pdf` (unsaved-draft preview) → `POST /purchases` (real create, real `purchase_bill_no`) → `GET /purchases/{id}/pdf` (the new by-id endpoint from the earlier fix) — all three returned real, valid PDFs; the by-id one saved to `live_purchase_verification.pdf` for visual review.
- **Golden invoice case, with the real image attached:** draft → finalize (Section 5.3 auto-numbering; confirms `invoice_no` is real, not null) → the Rs. 184,500 total correctly triggers `approval_status='pending'` (Section 7.4's Human Gate, same case as Phase 2's original exit test) → approved → rendered via `pdf_service.build_invoice_pdf` directly against the real saved row (no `/generate`/Cloudinary-upload step needed just to review the bytes) → saved to `golden_invoice_184500_final.pdf`.
- **Cleanup confirmed independently after the run:** `parties`/`inventory_items` have zero `ZZTEST%` rows, `purchases`/`customer_ledgers` are both back to 0 rows, and a direct Cloudinary Admin API `resources` listing under the `omega-scales` prefix has zero `ZZTEST` public IDs remaining — the single real image upload this test made was genuinely deleted, not just marked for deletion.
- 3/3 new tests passed. Full combined suite (fake + this new real-DB file): **162/162 passing** (159 fake-client + 3 real-DB).

Both saved PDFs (`live_purchase_verification.pdf`, `golden_invoice_184500_final.pdf`) were sent to the user directly rather than committed anywhere — they're scratch verification artifacts, not project files.

## Phase 4 frontend — User Management (Screen 12) and Settings (Screen 10) (2026-08-03)

Built against the real backend endpoints (`app/routers/users.py`, `app/routers/settings.py`, `app/routers/auth.py`) rather than assumption, same discipline as the Purchase Builder fix earlier this session. `NAV_ITEMS`/routes for both (`/settings/users`, `/settings`) already existed in `components/shell/nav-items.ts` with no pages behind them yet.

**User Management** (`app/(app)/settings/users/page.tsx`, `components/users/{UsersTable,AddUserModal}.tsx`): table (Name/Email/Role badge/Last Login/Status badge/Deactivate), "+ Add User" modal (`POST /users` — temp password is generated and emailed server-side, never shown in the form), and a confirm-dialog-gated Deactivate (`PATCH /users/{id}/deactivate`). Two deliberate additions beyond the PRD's literal text: (1) an Admin can't deactivate their own account (button disabled with a tooltip on that row) — not asked for, but a one-line guard against an obvious self-lockout footgun; (2) the confirm dialog's copy says this is a soft-disable, not a delete, and doesn't promise an in-app "undo" — there's no reactivate endpoint, so the copy doesn't invent one.

**Settings** (`app/(app)/settings/page.tsx` + `components/settings/*Card.tsx`), in the PRD's own listed order:
- **Profile** — read-only (`GET /auth/me`); no update-profile endpoint exists, so "Change Password" reuses the existing `POST /auth/forgot-password` flow against the user's own email rather than a fabricated change-password call.
- **Appearance** — the theme `<Switch>` wired to the app's existing `useThemeToggle()` (same context every other theme toggle already shares), not a new implementation.
- **Notifications** — honest gap, not a fabricated backend: no `notification_preferences` table/endpoint exists anywhere in the schema. Built as device-local toggles (`hooks/use-local-toggle.ts`, `useSyncExternalStore` over `localStorage`) with copy that says plainly they don't yet change what the server emails — same "deliberate simplification, disclosed, not hidden" pattern as Scan Slip/Live Preview's earlier build-out, not a half-finished feature pretending to be whole.
- **Human Gate Threshold** — the one fully real, functional piece: `GET`/`PATCH /settings`, Admin-only (nulled server-side for Staff, so the card simply doesn't render rather than rendering disabled).
- **Connected Email** — informational only, Admin-only. Gmail is server-`.env`-configured OAuth (Section 9.1), not a user-driven "Connect" OAuth flow, and no status endpoint exists to query live connection state — so this card describes the arrangement rather than pretending to be interactive.
- **Danger Zone** — just Sign Out (`POST /auth/logout`), the one real destructive-ish action with a backing endpoint. No fabricated "Delete Account" button.

Both screens verified in a real browser (Playwright, headless Chromium — no `chromium-cli` in this environment, so shared libs `libnspr4`/`libnss3`/etc. were `apt-get download`'d without root and loaded via `LD_LIBRARY_PATH` rather than installed) against **live Supabase data**: a throwaway backend process overrode `get_current_user`/`require_admin` the same way `tests/integration_real/conftest.py`'s `real_env` fixture does (same fake-admin id, same ensure-row-exists-then-clean-up-if-we-created-it discipline), so the Users table screenshot shows the real live Admin account (`uzmakhan`) alongside the fake test one. `tsc --noEmit` and `eslint` both clean (the latter caught three `react-hooks/set-state-in-effect` violations — this Next.js version's stricter lint rule against `setState` inside `useEffect` — fixed via `useSyncExternalStore` for the localStorage hook and the same during-render sync pattern `lib/api/use-api-get.ts` already established, not a new pattern).

**Incident, disclosed per this file's own established norm:** clicking "Add User" in the live browser test genuinely triggered `user_service.create_user` → `email_service.send_temp_password_email`, which — now that real Gmail credentials are configured (Section 9.1) — actually sent one real email via the business's Gmail account to a synthetic `zztest-verify-...@example.com` address. Same class of event as the "real-DB verification sent more real mail" incident logged above, though this instance matches that incident's own precedent for what's harmless: `@example.com` is a reserved, non-deliverable domain, and no safety-net fixture (those only guard `tests/`) was in scope for this ad hoc verification script. No further form submissions were made after noticing this, and the created test user row, the fake-admin override row, and its `app_settings.updated_by` reference were all deleted immediately after — confirmed zero `ZZTEST`/`zztest`/fake-admin rows remain. Noted here so it isn't a surprise in the user's Gmail sent folder later.

## Phase 4 frontend — Analytics (Screen 9), Expenses (Screen 16), Purchase History (Screen 15 list) (2026-08-03)

Three screens built in one pass, each checked against the real backend before building rather than assumed, same discipline as everything else this session.

**Two real backend gaps found and fixed before touching the frontend, same pattern as the Purchase Builder PDF fix earlier:**
1. **No "list all purchases" endpoint existed.** `GET /api/v1/purchases` required `party_id` (only ever listed one supplier's purchases) — there was no way to build Screen 15's list view (all suppliers, newest first, mirroring `GET /invoices`) at all. Made `party_id` optional on the existing endpoint (`app/routers/purchases.py`) — omitted, it now calls new `purchase_service.list_purchases` (every purchase, newest first); provided, it still filters to one supplier, so the Party Detail page's future use of this same endpoint isn't broken. 2 new tests.
2. **`ExpenseOut.particular_id` had no matching name anywhere the frontend could read.** `GET /master-data/particulars` deliberately only ever returns bare names (Record Payment's Method dropdown only needs names to submit, never ids) — fine for every existing caller, but left no way to show "Cash" instead of a raw UUID in an Expenses list row. Added `ExpenseOut.particular_name` (`app/models/expense.py`), resolved server-side in `expense_service.row_to_out` via a small id→name map (`_particular_names`, same shape as `analytics_service.payment_method_breakdown`'s own particulars lookup) — additive, doesn't touch `/master-data/particulars`'s shape or its other callers. 2 new tests.

Full suite: **162/162 passing** (fake client only for this round — no live-Supabase-only backend logic changed here beyond the two additive items above, both re-verified live in the browser pass below anyway).

**Analytics** (`app/(app)/analytics/page.tsx`) — full-page grid of all six Section 8 charts. Reused the Dashboard's existing `ChartCard` (moved to `components/shared/` since it's now a two-feature component, not dashboard-only) rather than rebuilding chart rendering — the backend pre-renders each chart to a Matplotlib PNG on Cloudinary (`AnalyticsResult.chart_url`, a Phase 3 design decision already in place, not something this pass changed), so `ChartCard` was already the right abstraction. One shared From/To date-range filter feeds the four range-aware endpoints (Monthly Sales, Top Selling Models, Category-wise Sales, Payment Method Breakdown); Customer Debt and Low Stock are always a live snapshot (their backend queries take no date params — a balance or a stock level is a point-in-time fact, not a period total) and say so directly under their titles rather than silently ignoring the filter with no explanation.

**Expenses** (`app/(app)/expenses/page.tsx`, `components/expenses/{AddExpenseForm,ExpensesTable}.tsx`) — an always-visible Add Expense form (Date, Party optional, Description, Amount, Particular dropdown — matching the real legacy system's own form, not a modal) above a filterable table. Date range filters server-side (the existing `start_date`/`end_date` query params); Particular filters client-side (no backend param for it, and at 8-10 users' worth of expense volume that's a fine trade-off — same "fetch once, filter in JS" convention already used on Parties/Invoices search).

**Purchase History** (Screen 15's list view) required a route split that didn't exist yet: the Purchase Builder had been living at `/purchases` itself (built in an earlier session before the list/builder distinction came up), with no list page behind `/purchases` at all. Moved the builder to `/purchases/new` (matching the PRD's own Route Map, Section 3.2) and built the list view at `/purchases` — stats strip (Total Purchases / Total Amount / Outstanding to Suppliers), search by bill # or supplier, table, and a PDF column button (`Button href="/api/backend/purchases/{id}/pdf"`, opens the real per-purchase PDF from the earlier session's fix directly in a new tab). `nav-items.ts` already pointed "Purchases" at `/purchases` and needed no change; nothing else in the frontend linked to the old builder-at-`/purchases` behavior, confirmed by grep before moving anything.

**New nav item:** Expenses had no sidebar entry at all before this (`components/shell/nav-items.ts`) — added between Parties and Analytics, matching the Route Map's ordering intent.

**Verified in a real browser (Playwright + `LD_LIBRARY_PATH`-loaded shared libs, same workaround as the User Management/Settings pass) against live Supabase, with the same fake-admin dependency-override pattern:** Analytics rendered all six cards correctly (five empty "No data yet" states plus one real live low-stock chart for the real `P-16-S-A-MK` catalog item, confirming the live snapshot charts do reflect real current data); Expenses' Add form created a real row (revealing the live `expenses` table's `serial_number` sequence is already at 14 from earlier phases' real usage/testing — not a bug, just an auto-increment counter that doesn't reset on delete) and the stats/table updated correctly, then the test row was deleted directly from Supabase afterward (no delete UI exists for expenses, by design — Section 5.2's retention philosophy doesn't call for one here since expenses aren't the audited ledger); Purchases list correctly showed the real empty state (0 purchases — all earlier test purchases were already cleaned up in the prior session); the Purchase Builder at its new `/purchases/new` address still renders and functions identically to before the move. Zero console errors across all four page loads. One operational hiccup during this pass, not a code bug: the first verification attempt hit a stale `next dev` process left running from the previous User Management/Settings session on port 3000, which 404'd on the brand-new routes because a fresh `npm run dev` had actually failed silently (wrong working directory) while the stale process kept answering; caught via a raw response-status check, fixed by force-killing every leftover Next/npm process and restarting cleanly from `omega-frontend/`.

Backend: 162/162. Frontend: `tsc --noEmit` and `eslint .` (whole project) both clean.
- [2026-08-03T13:55:11.451350+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T13:55:11.461972+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T13:56:27.726248+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T13:56:27.733024+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T14:11:28.804734+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T14:11:28.816665+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T15:01:32.068146+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T15:01:32.083194+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Phase 4 — Notification Preferences (server-side), Item Detail, Reports, Bank Accounts (2026-08-03)

Four more screens/features, in sequence, per the user's request. First real schema addition since Phase 4's own `schema_phase4.sql`.

**1. Notification Preferences, made real.** The Settings screen's Notifications card was a device-local `localStorage` stub (this file's own earlier entry documented that honestly, and why). Now real:
- `db/schema_phase5.sql` (new) — `notification_preferences` table, one row per user, three booleans (`low_stock_digest`, `human_gate_approval`, `login_approval_request`), all default `TRUE`. **Not yet run against the live Supabase project** — same "run this next" status every prior phase's schema file carried before the user applied it; `notification_preferences_service.get_preferences` returns all-on defaults when no row exists, so this is forward-compatible with existing users needing no backfill once it is applied.
- `app/services/notification_preferences_service.py` + `GET/PATCH /api/v1/notification-preferences` (any authenticated user, manages their own).
- Wired into all three real send paths that existed before this: `scheduler.send_daily_digest` now checks `low_stock_digest` per admin before sending (also fixed a latent bug found while touching this code — the log line's "sent to X/Y admin(s)" denominator was `len(sent_to)/len(sent_to)`, always self-referential; now `len(sent_to)/len(admins)`, a real ratio); `auth.py`'s `_notify_admins_of_pending_login` (Section 3.1) now checks `login_approval_request` per admin; and — a real gap found in the same pass, not just a rewire — **there was no notification at all when an invoice enters the Human Gate** (unlike the Login Approval Gate's own admin alert). Added `ledger_service._notify_admins_of_pending_invoice` (fires from `finalize_invoice` when `approval_status` becomes `'pending'`), gated by the new `human_gate_approval` preference, same best-effort/never-block-the-write discipline as every other notification here.
- Frontend `NotificationsCard.tsx` rewritten to call the real API instead of `localStorage`; the now-unused `hooks/use-local-toggle.ts` stub was deleted. 9 new backend tests (`tests/integration/test_notification_preferences.py`) cover GET defaults, PATCH partial-update persistence, and all three send-paths' skip/send behavior under both preference states.

**2. Item/Inventory Detail page** (Screen 4, `/inventory/[itemCode]`) — no backend changes needed; full CRUD (`GET/PUT/DELETE /inventory/{item_code}`, image upload on both create and update) already existed from Phase 1, just never had a frontend page. Admin gets every field editable plus image replace and a confirm-gated Delete; Staff gets the identical layout read-only (Section 3's RBAC: "Cannot: edit rates"). Inventory list's Item Code column now links here.

**3. Reports screen** (Screen 17, Section 5.4.H, `/reports`) — no backend changes; every report reuses an existing endpoint. A row of action cards (Section 4.3.1's exact pattern) reveals one report's controls + result table at a time: Date Wise (client-side date filter over `GET /invoices`), Customer Ledger (`GET /parties/{id}/ledger`, printable via `window.print()`), Customer Wise (per-customer sales/received/balance — no aggregate endpoint exists, so this is N+1 per-party ledger fetches, same accepted trade-off the Parties list page already makes for per-party balances), Serial No lookup and Duplicate reprint (both resolve an invoice number against the already-fetched `/invoices` list client-side, then Duplicate calls the existing `POST /invoices/{id}/reprint`).

**4. Bank Accounts screen** (Screen 18, Section 5.4.E, `/settings/bank-accounts`, Admin-only) — the `bank_accounts` table has existed since Phase 1 with only a read-only, active-only, names-only view (`GET /master-data/bank-accounts`, the Record Payment picker). Added the actual management CRUD: `app/models/bank_account.py`, `app/services/bank_account_service.py`, `GET/POST /api/v1/bank-accounts` + `PATCH /api/v1/bank-accounts/{id}` (all Admin-only, per the Route Map). Frontend: uikit's basic `<Table>` (Section 4.3.1: "sufficient here, short list") with a `<Switch>` per row and an Add Bank `<Modal>`; linked from the Settings page (a new small nav-style card, since Bank Accounts isn't in the main sidebar). 5 new backend tests, including one confirming a deactivated bank disappears from the Record Payment picker immediately.

Full suite: **176/176 passing** (fake client). `tsc --noEmit` and `eslint .` (whole project) both clean.

**Verified in a real browser against live Supabase** (same Playwright + `LD_LIBRARY_PATH` workaround, same fake-admin dependency override): Item Detail rendered the real `P-16-S-A-MK` catalog row with all fields editable; Reports' Serial No and Customer Wise cards both ran cleanly against real (currently empty) invoice/party data; Bank Accounts showed the one real live seeded row (`Cash Received`), and a full live create → toggle-off → verify cycle was run with a `ZZTEST Bank` row, then deleted directly from Supabase afterward — confirmed back to exactly the one real row. **Notification Preferences could not be live-verified** — `notification_preferences` doesn't exist in the live project yet (`schema_phase5.sql` pending, same as every prior phase's first pass), so `GET /notification-preferences` 500s live with `PGRST205` ("Could not find the table"); the frontend degrades to this card's toggles staying on a loading skeleton rather than crashing, which read confusingly close to a "working switch" in a first screenshot glance — confirmed via direct DOM inspection that they were genuinely `g-skeleton` placeholders, not real `Switch` components, and tightened the card to show an explicit error message instead of an indefinite skeleton once a fetch actually fails.

**Two Next.js dev-server process-management issues hit and fixed during this pass, not app bugs:** (1) a `next dev` process from the *previous* verification round was never fully killed (only its port-3000 listener was, not the full `npm`/`next-server`/build-worker process tree), and Next's own `.next/dev/lock` file let it keep answering stale requests while a fresh `npm run dev` silently deferred to port 3001 — fixed by `pkill -f` on the specific process patterns plus removing the stale lock, not just a port-based kill. (2) That same stale process's corrupted `.next` build cache produced a `ChunkLoadError` on the next restart — fixed with a full `rm -rf .next`. Both are noted here as a pattern for next time: after this kind of verification pass, confirm zero `next-server`/`npm run dev` processes remain (`ps aux`), not just that the port is free.
- [2026-08-03T15:45:18.023050+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T15:45:18.030752+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Notification Preferences re-verified live + Inbox, Login Approvals, Human Gate Drawer (2026-08-03)

`schema_phase5.sql` applied by the user. Re-ran the exact same live check from the prior entry: `GET /notification-preferences` now returns real `{low_stock_digest, human_gate_approval, login_approval_request}` defaults instead of `PGRST205`. Confirmed a full live round trip in the browser, not just the API: toggled Low Stock Digest off on the real Settings page, reloaded the page, and it was still off — the earlier "confusingly close to a working switch" skeleton-vs-real-Switch concern is moot now that the fetch actually succeeds.

Three more screens built and verified, completing the frontend build-out:

**Inbox** (Screen 13, Section 9.1, `/inbox`) — split view: message list (unread bold, invoice-number chip) on the left, thread + reply composer on the right. Honest constraint carried over from the backend, not a frontend gap: `inbox_messages` only ever stores a `snippet`, never a full body (Gmail's own thread carries the rest), so the detail panel shows the snippet as the preview rather than fabricating a body. Reply composer has Generate AI Reply (`POST /inbox/{id}/generate-reply`), a plain `<textarea>` (no `TextArea` component exists in this uikit version, same "no component, use styled HTML" precedent as the date inputs elsewhere), an Attach Invoice # field, and Send. Mark read/unread and Delete (Admin-only, soft-delete) round out Section 9.1's CRUD. No new backend needed — `app/routers/inbox.py` already had every endpoint from Phase 3.

**Login Approvals** (Screen 14, Section 3.1, `/settings/login-approvals`, Admin-only, linked from the Settings page) — pending queue at the top (pulsing indicator, Approve/Reject), a "This Week" stats strip (Approved/Rejected/Expired, computed client-side from the full history — no dedicated stats endpoint exists, same as Reports' Customer Wise pattern), then a searchable-by-name history table with per-row soft-delete and add-note actions. No new backend needed either — `app/routers/login_approvals.py` already had the full CRUD from Phase 3.

**Human Gate Drawer** (Screen 8, `/approvals/invoices`, Admin-only) — the PRD's Section 4.3 names this out specifically as a `<Drawer>` component, not a plain page, so it's built that way: a right-side sliding panel (uikit's `Drawer`) over the app shell, always `open` while this route is active, closing navigates back to `/dashboard`. Content is the same pending-invoice queue and Approve/Reject actions the Invoices list's inline buttons already exercise — no new backend needed, this is a focused view of the same `GET /invoices` + `/approve` + `/reject` endpoints, not a separate queue that could disagree with the Invoices list. The Dashboard's "Pending Approvals" KPI card was re-pointed here from `/invoices?filter=pending` (its href before this existed) per Screen 2's own spec: "links directly to the Human Gate Drawer, Screen 8."

**Verified in a real browser against live Supabase** (same workaround/pattern as every prior round): inserted one throwaway `ZZTEST`-marked `inbox_messages` row directly via Supabase (not through Gmail sync) to have something to click through — list and detail rendered correctly, mark-unread and the real snippet all showed right; Login Approvals correctly showed the real empty state (0 pending, 0/0/0 this week — no real Staff login has ever gone through this gate); the Human Gate Drawer was proven with a genuine end-to-end case: created a real throwaway party + inventory item + a 15 × Rs. 12,300 = Rs. 184,500 invoice (Section 2.3's own golden number) through the real API, finalized it, watched it appear in the live Drawer, clicked Approve, and watched it clear from the queue with a live toast. All test rows (party, item, both invoice attempts including one that hit a real "insufficient stock" 400 before the working one, inbox message) deleted afterward — confirmed back to zero.

**Real external side-effect worth flagging, same transparency norm as before:** finalizing that test invoice genuinely triggered the newly-wired Human Gate notification (Section 7.4) to every active admin whose preference allows it — which now includes the *real* Admin account (`uzmakhan`/`techexav@gmail.com`), not just the fake test one, since `human_gate_approval` defaults to on and no one has opted out yet. This means one real "Invoice #1 (Rs. 184,500.00) exceeds the Human Gate threshold and is waiting for approval" email genuinely landed in the real Admin's own inbox — harmless (it's the account's own real email being notified about its own real feature test, not sent to any third party), but noted here so it isn't a surprise, same as the temp-password-email note from the User Management round.

**One more stale-process repeat, caught faster this time:** a `next-server` process from the *previous* round's pass survived past its "everything's stopped" check (not bound to any port, just still running) — killed explicitly by PID before starting this round's fresh server, confirming the "check `ps aux`, not just the port" lesson from the last entry is worth actually following each time, not just writing down once.

Backend: 176/176 passing (unchanged this round — no backend code changed, only the live migration state). Frontend: `tsc --noEmit` and `eslint .` clean.
- [2026-08-03T15:53:37.987216+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T15:53:37.997211+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T15:59:46.497628+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T15:59:46.504526+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T16:54:10.066062+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T16:54:10.075824+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Party Detail (Section 5.4.I, Screen 3g) (2026-08-03)

The one screen explicitly called out as skipped in an earlier round, now built.

**Backend addition:** `PartyBalanceOut` gained `lifetime_business` (Section 5.4.I: "total lifetime business done (sum of all sale/purchase amounts)") — `party_service.get_lifetime_business` sums finalized `customer_ledgers` sale-type rows (a draft "isn't done yet," same `invoice_state='finalized'` filter `analytics_service` already uses for exactly this reason — caught by a failing test that assumed drafts shouldn't count, before this filter was added) plus all `purchases` rows for that party, so a `party_type='both'` party's figure is genuinely combined, matching the PRD's literal "sale/purchase" wording rather than picking one side. Additive field on an existing response — `GET /parties/{id}/balance` — no new endpoint. 4 new tests (defaults to zero, sales-only, purchases-only, combined-both-party). Full suite: **180/180 passing**.

**Frontend:** new `/parties/[partyId]/page.tsx` — profile card (name, type badge, phone/email/address with icons), stat tiles (Current Balance / Credit Limit / Lifetime Business), "View Full Ledger" button onward to the existing `/parties/[partyId]/ledger` (untouched). `PartiesTable.tsx`'s party-name link changed from going straight to the Ledger to landing here first, per the user's explicit instruction — the only link changed; Invoices/Purchases tables and Reports' Serial No lookup still jump straight to a party's Ledger from a transaction row, which is a different, deliberately-kept-as-is intent than the Parties list itself.

**A genuinely confusing verification detour, resolved and worth recording in full:** adding this new nested-under-existing-dynamic-segment page (`/parties/[partyId]/page.tsx` alongside the pre-existing `/parties/[partyId]/ledger/page.tsx`) triggered hours of inconsistent 404s on the *sibling* ledger route that had nothing to do with the new code. Root cause, confirmed by elimination: **stale/zombie `next-server` processes surviving supposedly-clean restarts, repeatedly** — this session's own prior entries already flagged this pattern once and it recurred at least four more times during this single task, including one case where a zombie process wasn't bound to any port at all (so `lsof` showed nothing, but `ps aux` did) and another where a `next build` was mistakenly run concurrently with a live `next dev` against the same `.next` directory, corrupting shared state further (a stray leftover `zzdiag2` test route survived deletion long enough to crash the build with `ENOENT`, proof the build was reading a stale in-memory/cached file list rather than the real filesystem). Ruled out real causes first, in order, before landing on this: (1) `page.js is always the leaf of the route subtree`, read literally from this custom Next.js build's own bundled docs (`node_modules/next/dist/docs`) per `AGENTS.md`'s explicit warning to check them — looked like confirmation at first, but a from-scratch isolated reproduction (`app/(app)/zzdiag/[id]/page.tsx` + `.../child/page.tsx`) proved a parent-with-page and a nested child page coexist and both resolve fine, the instant the process tree was verified truly single and clean. **The actual, tedious fix each time was the same one already written down after the last incident, applied more rigorously:** kill by exact PID (not just `pkill -f` pattern matching, which silently missed processes at least twice more), verify with two separate `ps aux` checks a couple seconds apart before trusting "clean," and never run `next build` and `next dev` against the same project directory at the same time. No code changes were needed once the process state was actually clean — both routes worked immediately.

**Verified in a real browser against live Supabase** once the environment was genuinely stable: clicking the one real live party ("techexavision") from the Parties list landed on its new Detail page — real phone/email/address, `Rs. 30,000` credit limit, `Rs. 0` current balance and lifetime business (this party has no transactions yet, so zero is correct) — then "View Full Ledger" correctly opened the existing Ledger view unchanged.
- [2026-08-03T17:44:44.202119+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T17:44:44.215756+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T17:49:21.600499+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T17:49:21.615992+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T18:04:15.442280+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T18:04:15.452956+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T18:21:53.736967+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T18:21:53.745217+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T18:42:30.913153+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T18:42:30.919333+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T18:48:18.198785+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T18:48:18.210897+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T18:52:36.415943+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T18:52:36.427965+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T19:06:11.395390+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T19:06:11.403398+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T19:08:58.218404+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T19:08:58.223230+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T19:18:32.851206+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T19:18:32.871450+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T19:21:11.454350+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T19:21:11.460562+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T19:47:57.708242+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T19:47:57.717746+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T19:50:16.334208+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T19:50:16.341425+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T20:17:42.370210+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T20:17:42.387752+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T20:32:52.016930+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T20:32:52.024208+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T20:38:59.612101+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T20:38:59.628161+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Section 16 batch — Credit Limit, Stock Adjustment, Sales Return, Activity Log, Delivery Challan, Payment Correction, Bulk Upload Images (2026-08-04)

Seven items built in one continuous pass, per the user's explicit "build all seven in sequence, verify each against real Supabase" instruction. New migration: `db/schema_phase6.sql` (activity_log, stock_adjustments, sales_returns, delivery_challans, plus `customer_ledgers.payment_correction_of`/`payment_correction_reason`) — applied by the user partway through this round.

**16.1 Credit Limit Enforcement.** `finalize_invoice` now checks `current_balance > party.credit_limit` (when a limit is set) before anything else changes, so a block is a true no-op. Blocked without override → 409 with the exact excess amount in the message. `override_credit_limit=true` query param on `/finalize`, rejected with 403 for non-Admin at the router level before it ever reaches the service. An override is logged to the new Activity Log. Frontend: a Dialog with an Admin-only "Approve Anyway" button on the 409.

**16.2 Stock Adjustment.** `POST/GET /inventory/{item_code}/stock-adjustments`, Admin-only for the write. `delta = counted_qty − previous_qty` applied straight to `inventory_items.quantity_in_stock`; `reason` is one of damaged/lost/count_correction/other. Frontend: a button + history table on Item Detail.

**16.3 Sales Return.** `POST/GET /invoices/{id}/returns`, restricted to already-finalized sale invoices; validates the item was actually on that invoice and the returned qty doesn't exceed what was sold. Restores stock via the existing `adjust_stock` and credits the party by inserting a `receiving` row (not mutating the original invoice). Frontend: "Return Items" button on any finalized invoice row.

**16.4 Activity Log.** New append-only `activity_log` table — no update/delete route exists anywhere for it, not even Admin-gated (deliberately: "an audit log that could be erased isn't an audit log"). `GET /activity-log` (Admin-only) supports `action`/`search`/`start_date`/`end_date` filters. Wired into every write this round (credit override, stock adjustment, sales return, delivery challan generate/mark-delivered, payment correction) **and retrofitted into three pre-existing sensitive Admin writes that had no audit trail before**: user creation, user deactivation, and "Fix This Invoice" (Section 5.1's correction entry) — item deletion also newly logged. Frontend: `/settings/activity-log`, linked from Settings.

**16.5 Delivery Challan.** `pdf_service._render_bill_pdf` gained a `pricing: bool` flag (its "sibling mode") — same header/watermark/party block/item table, but strips the Rate/Total columns and the whole totals block when `pricing=False`; a new `build_delivery_challan_pdf` wrapper calls it that way. `POST/GET /invoices/{id}/delivery-challan` (once per invoice, 409 on a second attempt), `POST /delivery-challans/{id}/mark-delivered`. Uploaded to its own Cloudinary folder (`upload_delivery_challan_pdf`, new). Frontend: a "Challan" button on finalized invoice rows, opens a Dialog that generates-or-shows the existing challan and lets an actual delivery date be recorded.

**16.6 Payment Correction.** Mirrors Section 5.1's Correction Entry pattern exactly, but for a `receiving` row: `POST /invoices/payments/{payment_id}/correct` (Admin-only), reason required, `corrected_amount`/`corrected_method`/`corrected_date` all optional (omit whichever wasn't actually wrong). Sign convention is the mirror image of an invoice correction's, since a payment *reduces* balance rather than increasing it: `delta = original_amount − corrected_amount` (a lower corrected amount means the party actually owes more, so the balance goes back up by that delta) fed into the same `compute_correction_balance` formula create_correction already uses. The original payment row is never touched. Frontend: a "Fix This Payment" button on genuine (uncorrected) receiving rows in the Party Ledger, Admin-only.

**10.2b Bulk Excel + Image Folder.** `bulk_upload`'s endpoint gained an optional `images_zip` upload alongside the Excel file; images are matched to a product by filename (minus extension) == item_code, case-insensitive. **A real bug caught during live verification, not just unit tests:** the image-upload call was originally inside the same `try` block as `create_item`/`update_item`, so a Cloudinary rejection of a bad image file (confirmed live: a deliberately-malformed JPEG got a genuine "Invalid image file" from Cloudinary) marked an *already-successfully-created* item as a row error in the response — the item existed in Supabase but was reported as failed. Fixed by giving the image step its own try/except that falls back to `images_unmatched += 1`, matching the existing best-effort convention `pdf_service._fetch_thumbnail` already uses for the same reason. Re-verified live afterward with a real image: `images_matched: 1, images_unmatched: 1, skipped: 0`, Cloudinary URL genuinely fetchable, then cleaned up (including the real Cloudinary asset).

**A real process-hygiene gap caught mid-round, not after:** the fake-admin verification server (`run_backend_test_admin.py`, no `--reload`) was left running with stale code while Items 2 and 3's backend was being written, so their first "live" 404 checks were actually ambiguous — a genuinely-unregistered route and a real "item/invoice not found" business error both look identical as a bare FastAPI 404. Caught before trusting those results: killed the stale process by explicit PID (verified twice via `ps aux`), restarted fresh, and confirmed via `/openapi.json` that all seven new route paths were genuinely registered before re-running the checks for real.

**Verified end-to-end against live Supabase, real ZZTEST throwaway data**, in one connected run exercising all six schema-backed items together (credit-limit block + override, stock adjustment, sales return crediting the same invoice, delivery challan including a real fetchable Cloudinary PDF, payment correction, and the Activity Log correctly showing/filtering/searching every one of those actions) — 18/18 checks passed. All rows deleted afterward (party, item, all customer_ledgers rows including the correction and return-credit rows, sales_returns, delivery_challans, stock_adjustments, the ZZTEST activity_log entries) and the real Cloudinary challan PDF asset destroyed; confirmed zero remaining across every table touched.

Backend: 223/223 passing. Frontend: `tsc --noEmit` and `eslint .` clean throughout.
- [2026-08-03T21:29:12.588940+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T21:29:12.600161+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-03T21:40:03.375518+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-03T21:40:03.382767+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-04T12:56:25.780004+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-04T12:56:25.792427+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-04T13:44:42.219757+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-04T13:44:42.230752+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-04T13:48:53.958127+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-04T13:48:53.989842+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-04T13:59:08.670608+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-04T13:59:08.682039+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-04T14:02:34.654520+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-04T14:02:34.671340+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-04T14:09:16.895338+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-04T14:09:16.907987+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Pre-deployment comprehensive audit, restarted after a session interruption (2026-08-04)

The previous session was interrupted (laptop restart) mid-way through fixing a "balance-chart bug" found during a final audit pass, but was cut off before it ever wrote what that bug actually was to this file. Rather than guess, this session re-audited both repos from scratch: read PRD.md and this file in full, then ran three independent, read-only investigations in parallel — one on every chart in the app (Dashboard's 3, Party Ledger's Balance Trend, Analytics' 6), one on the full backend against PRD.md, one on the full frontend against the backend's real contract. Findings below, fixes applied and tested as they were confirmed, not batched to the end.

**Backend fixes:**

1. **`analytics_service.monthly_sales_revenue` was counting unfinalized draft invoices** — missing the `invoice_state='finalized'` filter its sibling functions (`top_selling_models`, `category_wise_sales`) already had. A draft sale (fully editable/abandonable, no Human Gate or approval yet) was being summed straight into the Monthly Sales & Revenue chart on both Dashboard and Analytics, while the Dashboard's own "Total Sales" KPI card correctly excluded drafts two lines away — an inconsistency that was reachable and real. Fixed (`app/services/analytics_service.py`); new test `test_monthly_sales_revenue_excludes_draft_invoices`.
2. **`top_selling_models` and `category_wise_sales` were missing the `deleted_at` soft-delete filter** their three sibling analytics functions already had — a soft-deleted finalized invoice's line items would still count toward both charts forever. Currently unreachable in practice (grepped the whole backend: no invoice soft-delete endpoint has ever actually been built, despite the schema column existing), but fixed for consistency and because it stops being unreachable the moment that endpoint is added. Fixed (`app/services/analytics_service.py`).
3. **Sales Return allowed over-crediting across multiple partial returns on the same line.** `qty_returned` was validated against the *original* invoice line's qty every time, never against how much of that line had already been returned — so a line that sold 10, already returned 5, would accept a second return of up to 10 again (not the true 5 remaining), over-restoring stock and over-crediting the party's balance. Fixed by summing prior `sales_returns` rows for that `(invoice, item_code)` pair and validating against the remainder (`app/services/sales_return_service.py`); new test `test_cannot_return_more_than_remains_after_a_prior_partial_return`.
4. **No server-side guard against an Admin deactivating their own account, or the system's last active Admin.** The frontend already disables the button for self-deactivation, but nothing stopped a direct API call, a stale client, or two Admins racing each other — and since there is no reactivate endpoint anywhere in this system, either one is a permanent, unrecoverable lockout of every Admin-gated feature (including User Management itself). Added both guards server-side, `409` on either (`app/services/user_service.py`, `app/routers/users.py`); new `tests/integration/test_user_deactivation_guards.py` (3 tests).
5. **`JWT_SECRET_KEY` silently defaulted to `""` if ever unset**, and the app would start anyway — `jose.jwt` signs/verifies session cookies with whatever key it's given, so a blank secret means anyone can forge a valid session simply by signing a JWT with an empty key themselves. `.env` has always had a real secret so this was never live, but nothing would have caught a misconfigured deploy. Now raises `RuntimeError` at startup if unset (`app/config.py`); new `tests/unit/test_config.py`.
6. **`lookup_bank_account_id` (Record Payment's bank picker) didn't filter `is_active`.** The Bank Accounts screen already hides a deactivated bank from the picker client-side, but that's cosmetic only — a stale client or a direct API call could still record a payment against a bank an Admin had already turned off. Added the filter (`app/services/master_data.py`); new test `test_deactivated_bank_account_cannot_be_used_to_record_a_payment`.
7. **Display ordering on `list_party_ledger`, `list_invoices`, `list_party_purchases`, and `list_purchases` sorted by `created_at`, not `transaction_date`** — Section 5.2 explicitly requires `transaction_date DESC` as the default view order for both the Party Ledger and the Invoices list. Fixed to `transaction_date DESC`, `created_at DESC` as the same-day tiebreak (`app/services/ledger_service.py`, `app/services/purchase_service.py`). This is display-order only — see the next point for why the underlying balance math is deliberately *not* the same fix.

**A fix that was tried, found to be wrong on closer inspection, and reverted before it shipped — worth recording so nobody re-introduces it.** Both `get_latest_party_balance` and `get_latest_purchase_balance` (the functions that fetch `previous_balance` for the *next* write) also ordered by `created_at`, and two of the three independent audits above flagged this as the same bug as point 7 — this is almost certainly what the interrupted session's "balance-chart bug" actually was. The proposed fix (anchor on `transaction_date` instead) was applied, then traced through a concrete scenario before trusting it: insert a Sale (dated today, balance 1000), then a **backdated** Payment (dated yesterday, -400, correctly netting to balance 600 since it's inserted *after* the Sale) — anchoring the next new transaction on `transaction_date` picks the Sale (today's date sorts later) as "latest," silently discarding the fact that the $400 payment ever happened. Since `current_balance` is a strict running prefix-sum over rows *in insertion order*, and finalized rows are immutable (Section 5.1 — never recomputed after the fact), insertion order (`created_at`) is the only order the chain can self-consistently follow; `transaction_date` genuinely only belongs in the *display* ordering fixed in point 7, not the balance math itself. Reverted both functions back to `created_at`-only, with a docstring explaining why, and added a regression test that pins the correct (insertion-order) behavior: `test_backdated_payment_still_anchors_the_next_transactions_previous_balance` (`tests/integration/test_invoice_lifecycle.py`).

Backend after all of the above: **231/231 passing** (fake-client suite; up from 223 at the end of the last logged phase — 8 new tests, no regressions).

**Frontend fixes:**

1. **`BalanceTrendChart.tsx` (Party Ledger's Balance Trend chart) had no same-day tiebreak** — sorted only by `transaction_date`, so two same-day rows kept whatever order the backend happened to return them in (a JS stable sort no-op on ties). Since `current_balance` is a running total computed in *insertion* order (see the backend section above), two same-day rows must plot in that same insertion order or the line can visibly connect them backwards (e.g. a same-day Sale-then-Payment plotting as Payment-then-Sale). Added `created_at` as the tiebreak. This is very likely the actual "balance-chart bug" the interrupted session was chasing.
2. **Invoice Builder (`/invoices/new`) orphaned a draft on every retry after a finalize failure, and had no credit-limit override path at all.** `handleSubmit` unconditionally `POST`ed a new `/invoices/draft` on every call — a credit-limit 409 (or any other finalize failure) left the just-created draft's id nowhere but a local `const`, so clicking "Save & Finalize" again created a second, invisible, permanently-orphaned draft (no page anywhere could reach it — see the Edit-invoice gap below). Fixed: the created draft's id is now kept in state and every retry `PUT`s that same draft instead of creating a new one; a credit-limit 409 now opens the same "Approve Anyway" dialog the Invoices list already had, instead of a dead-end toast. The Party picker is disabled once a draft exists (`SaleDraftUpdate` can't change `party_id`, so switching parties mid-retry would otherwise silently desync the form from the saved draft).
3. **Silent fetch-failure handling was missing on six pages** — `useApiGet`'s `.error` was never read, so a failed fetch rendered identically to "genuinely empty" (indistinguishable, e.g. an audit log silently showing "0 entries" instead of "couldn't load"). Same bug class `progress.md` already documented fixing once for the Invoices page; this pass closed the remaining gaps: Dashboard, Inventory, Analytics, Expenses, Reports, and Activity Log all now toast a clear error instead of rendering a false empty/loading state.
4. **The entire Section 5.1 "Edit an invoice" feature had no frontend at all** — the single most significant gap found this session. `/invoices/[invoiceId]` (detail + "Fix This Invoice") and `/invoices/[invoiceId]/edit` (direct draft edit) were both missing routes; `InvoicesTable.tsx` had no Edit button anywhere. The backend has fully supported both paths (`PUT /invoices/{id}`, `POST /invoices/{id}/correct`) since Phase 2/3 — nothing on the frontend ever called either one. This meant: a draft with a typo'd qty had no way to be fixed short of abandoning it, and a finalized invoice had no way to get a Correction Entry at all, despite both being explicit, repeated PRD §12.1 acceptance criteria. Built:
   - `/invoices/[invoiceId]/edit/page.tsx` — the direct-edit path (draft only; bounces to the detail page if the invoice isn't actually a draft anymore, mirroring the backend's own `InvoiceNotDraftError` 409). Reuses the Invoice Builder's `ItemPicker`/`LineItemsTable`/`InvoiceSummaryPanel`/`InvoicePdfPreview`, prefilled from the existing draft (each line's `item_name`/thumbnail enriched via `GET /inventory/{item_code}`, since `InvoiceOut.line_items` only carries `item_code`/`qty`/`rate`). Same credit-limit "Approve Anyway" dialog as the New Invoice Builder.
   - `/invoices/[invoiceId]/page.tsx` — the detail view + "Fix This Invoice" correction form (Admin-only, matching the backend's `require_admin` on `/correct`), reachable only for an original finalized sale invoice (not a draft, not a receiving/payment row — those have their own "Fix This Payment" flow already — and not a correction entry itself, which has no line items of its own to correct). Prefilled the same way as Edit; submitting posts a `CorrectionCreate` and leaves the original row completely untouched, per Section 5.1's "never rewrite history" rule.
   - `InvoicesTable.tsx` gained the single two-behavior Edit button PRD §4.3.1 describes — one `<Button icon={Pencil}>` per row, pointing at `/edit` for a draft or the detail page for anything else, sitting alongside whatever other row actions already existed rather than replacing them.
   - Two `set-state-in-effect` violations surfaced by this project's stricter lint rule while building the prefill logic — fixed with the same during-render sync pattern `use-api-get.ts` and `NotificationsCard.tsx` already established (a prior session's own precedent), not a new pattern.
5. **Considered, deliberately not fixed:** `proxy.ts`'s middleware only checks session-cookie presence, not role, so an Admin-only route briefly reaches the page before `useCurrentUser()`'s client-side check redirects a Staff user away — flagged by the frontend audit as cosmetic-only, confirmed here: every corresponding backend router already enforces `require_admin` server-side (re-confirmed by the backend audit above), so this is a UI flash, not an access gap. Properly closing it would mean either shipping `JWT_SECRET_KEY` to the frontend to decode the cookie in middleware (violates Section 1.5.2's "secrets never ship to the browser") or calling the backend on every navigation (real latency cost) — not worth it for a flash with no actual exposure behind it.

Frontend after all of the above: `tsc --noEmit` clean (aside from the pre-existing, unrelated `.next/dev/types/validator.ts` staleness noted many times before in this file), `eslint .` (whole project) clean.

## Final comprehensive audit — live verification and environment limitation (2026-08-04)

**Environment gap, disclosed rather than worked around silently:** this sandbox cannot reach the real Supabase project (`fpwtghkguqfdtkcpnmou.supabase.co` — `curl` to it times out; general internet is fine, confirmed against `pypi.org`) — a different limitation than the earlier documented IPv6-only-egress issue, same practical effect. `pip install playwright` also hung twice (90s+, no output) even with nothing else competing for resources, so no browser-driven screenshots were possible either. Every prior phase's "verified against the live Supabase project" standard could not be met this round for that reason, not for lack of trying. What was actually done instead, all real (not mocked-and-trusted, actually executed and inspected):

- A throwaway live FastAPI server (`uvicorn`, real HTTP, not `TestClient`) using the exact same fake-Supabase + dependency-override pattern `tests/conftest.py`'s own `client` fixture already establishes, seeded with realistic data **through the real endpoints** (not hand-inserted rows) — multiple parties, inventory across three categories including one deliberately below `min_threshold`, several finalized sales spread across three months, and — specifically to exercise this session's own ledger-ordering fixes — a sale followed by a **backdated** Record Payment (dated earlier than a sale already in the chain).
- **Confirmed live, by actually reading the response bodies:** `GET /parties/{id}/ledger` returns rows in `transaction_date DESC` order (point 7's fix) while each row's `current_balance` is still computed in true insertion order (the reverted-and-documented fix) — walked the numbers by hand against the response and they reconcile exactly. This also reproduced, live, the exact "line crosses back on itself" visual consequence of backdating that `BalanceTrendChart.tsx`'s own code comment describes: plotted left-to-right by date, the balance genuinely goes 24,600 → 207,600 → 38,100 → 187,600 → 222,600 — not monotonic, and correctly so, since a backdated entry can't retroactively rewrite an already-finalized row's stored balance. Confirms the fix does what it's documented to do, not just that it compiles.
- **The new Edit-invoice feature, exercised end-to-end over real HTTP:** `GET` a draft for prefill, `PUT` it with a changed qty/discount and confirmed `total_amount`/`current_balance` recalculated correctly, `POST /correct` on the golden Rs. 184,500 invoice (a 15→14 qty fix) and confirmed the correction row correctly references `correction_of`/carries the signed delta while the original invoice's `total_amount` came back byte-identical (184500) on a fresh `GET` — the "never rewrite history" rule holding under an actual request, not just read in the code.
- **All six Analytics charts, fetched from the real endpoints and decoded from real PNG bytes** (Cloudinary swapped for a `data:` URI so no external network call was needed — the Matplotlib rendering itself is 100% real, only the upload step is stubbed) — inspected each image directly: Monthly Sales correctly shows three months summing both seeded parties' finalized sales (verified the July figure by hand: 184,500 + a second party's 16,000 = ~200,500, matching the rendered chart), Low Stock correctly shows exactly the one item seeded below threshold. All 6 PNGs and the golden Invoice #2127 PDF (normal + Duplicate-watermarked) were sent to the user directly.
- **Not verified this round, honestly:** the actual React/Next.js pages rendering in a real browser (Dashboard, the Balance Trend chart's client-side sort, the new Edit/detail pages' UI) — `tsc`/`eslint` prove they compile and typecheck correctly against the real API contract (which was itself verified live above), but no screenshot exists of the rendered pages themselves this round, unlike every prior phase's browser-verification passes. Worth a real browser pass (Playwright, or manual) once this sandbox has Supabase/npm-registry connectivity again, or from a different environment.

Backend: 231/231 (fake-client suite, unchanged since the fixes above — no backend code changed during this verification pass). Frontend: `tsc --noEmit` and `eslint .` clean. Every throwaway script/process used for this pass (`audit_server.py`, `gen_sample_pdf.py`, the live `uvicorn` process) lived only in the session's scratchpad/process table, confirmed killed by PID and re-checked via `ps aux` — nothing left running, nothing added to either repo.
- [2026-08-04T15:10:19.295970+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-04T15:10:19.313125+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Real live-Supabase + real-browser verification, completed on retry (2026-08-04, later same day)

The user asked to retry full live verification (the pass above had to substitute a fake store and skip browser screenshots because this sandbox couldn't reach Supabase or install Playwright at the time). On retry, both worked — connectivity had genuinely recovered (Supabase and PyPI both reachable, `pip install playwright` succeeded once it wasn't fighting a 60s timeout against a slow ~25 kB/s link for a 47.7 MB wheel; Chromium itself needed `libnspr4`/`libnss3`/`libasound2` — `apt-get download` (no root needed) + `dpkg-deb -x` into a scratch prefix + `LD_LIBRARY_PATH`, the same workaround pattern this file already documented from an earlier phase).

**A real, previously-undetected bug was found by this pass and nowhere else: `next dev` (Turbopack) cannot serve a nested dynamic route when its parent segment also has its own `page.tsx`, in this pinned Next.js build (16.2.12).** `/parties/[partyId]/ledger` and this session's own new `/invoices/[invoiceId]/edit` both 404'd — genuinely, not from a stale process (verified `ps aux` showed one single freshly-started `next-server`, and `.next/dev/server/app/.../ledger` never even got a compiled directory, meaning the dev router never discovered the route at all). Root-caused properly this time, unlike an earlier phase's inconclusive brush with the same symptom:
- A minimal isolated repro (`zzdiag2/[id]/page.tsx` + `zzdiag2/[id]/child/page.tsx`, plain server components) worked fine — so the pattern itself isn't inherently broken.
- Temporarily moving the real `parties/[partyId]/page.tsx` out of the way made `/parties/[partyId]/ledger` start returning 200 immediately — conclusively confirming the sibling `page.tsx` really does shadow the nested route, specific to `next dev`'s on-demand/lazy route compilation, not the isolated repro's simpler files.
- **`next build` compiles both routes correctly** — `/parties/[partyId]/ledger` and `/invoices/[invoiceId]/edit` both appear as genuine, separate, correctly-generated routes in the build's own route table, and **`next start` (the production server) serves all three previously-404ing routes as real 200s.** This is a `next dev`-only artifact — Render deploys a production build, never `next dev`, so this does not block deployment. Worth filing upstream or just remembering: **use `next build && next start` (not `next dev`) for any future manual verification of a nested dynamic route pair in this codebase** — `next dev`'s result cannot be trusted for that specific shape.

**Everything else, verified for real this time:**
- **Backdated-payment balance chain, seen live end-to-end**: seeded a Sale (10 May), a Sale (05 Jun), the golden Sale (23 Jul, Rs. 184,500), then two Record Payments backdated to 15 May and 20 Jun — `GET /parties/{id}/ledger` came back sorted `transaction_date DESC` (the display-order fix) while the `current_balance` sequence read 24,600 → 207,600 → 38,100 → 187,600 → 222,600 when plotted chronologically — the exact non-monotonic "line crosses back on itself" shape `BalanceTrendChart.tsx`'s own comment predicts, now seen rendered for real in the sent screenshot, not just reasoned about.
- **The new Edit-invoice feature, full browser round trip**: `/invoices` list shows the Edit button (pencil icon) on every row in all three states (draft+Finalize, pending+Approve/Reject, finalized+Return/Challan); the detail page's "Fix This Invoice" form renders fully prefilled (line item, discount, reason field) for the real golden invoice; the Edit Draft page renders fully prefilled with correct Summary math. All against real Postgres, real RBAC (fake-admin dependency override, same pattern `tests/integration_real/conftest.py` already established), real JWT cookie.
- **Dashboard and all 6 Analytics charts**, real Matplotlib PNGs uploaded to real Cloudinary, rendered in the actual page: Total Sales Rs. 238,600 correctly excludes the draft left open for the Edit-page test (the exact bug this session fixed in `monthly_sales_revenue`, now visibly correct end-to-end); Low Stock Alerts = 2 correctly includes both the seeded test item and a genuine pre-existing low-stock row in the real catalog (`P-16-S-A-MK`); Human Gate Drawer correctly lists the one real pending invoice with Approve/Reject.
- **A transient, non-actionable error observed once, disclosed for completeness**: one request logged `postgrest.exceptions.APIError: {'message': 'JWT issued at future', 'code': 'PGRST303'}` — Supabase-side JWT clock-skew validation, seen exactly once across dozens of requests, self-resolved (the page went on to render completely correctly), not reproduced on retry. Plausibly related to this sandbox's own system clock; not a code bug and not something a retry-and-move-on pass should chase further.
- **Cleanup confirmed independently**: every `ZZTEST_LiveAudit*` party/item/invoice/payment is gone (`parties`/`inventory_items` both back to 0 `ZZTEST%` rows, confirmed by direct query after cleanup). Analytics chart Cloudinary assets were genuinely overwritten during this pass (real chart generation, real upload) but were not "cleaned up" afterward — unlike a per-run invoice PDF or product photo, these six live at **fixed, standing public_ids** (`omega-scales/analytics/monthly_sales_revenue`, etc.) that every real Analytics page view overwrites again regardless of who's testing; there is nothing per-run to delete, and deleting them would just mean the next real page view re-creates them anyway. One genuinely orphaned side effect discovered and fixed: a `ZZTEST Chart Fix Verify` party+item, left behind by the *original* interrupted session (predating this whole conversation) and never cleaned up — found and removed during this pass's own cleanup sweep, unrelated to anything logged elsewhere in this file. The fake-admin override row (`admin@test.omega`) itself **cannot** be deleted — it's referenced by real `activity_log` rows from that same earlier interrupted session, and Section 16.4's audit log is deliberately undeletable by design (no FK cascade, no delete route, "even Admin cannot soft-delete rows"). This means that row is now a **permanent fixture** of the live `users` table — harmless (it can never log in for real, no real password), but it will show up in User Management's list forever. Worth knowing, not worth fighting the audit log's own immutability guarantee to remove.

Full combined result: backend 231/231 (unchanged, no code touched this pass), frontend `tsc`/`eslint` clean, and — for the first time this session — real screenshots of the real app against real data, sent to the user directly.

**One more real artifact, generated after the screenshots above**: the golden Invoice #2127 case (Rs. 184,500) as a PDF, this time fetched from the actual running `/invoices/preview-pdf` endpoint (not a direct local `pdf_service` call) against a real party + a real inventory item carrying a genuinely-uploaded-and-fetched-back Cloudinary product photo — closing the one gap the very first (fake-store) PDF pass in this session couldn't close. Sent to the user directly. Cleanup hit one real snag worth recording: the throwaway cleanup script deleted by the *lowercase* `item_code` it had generated locally, but `inventory_service.create_item` uppercases `item_code` on insert (existing, correct, intentional normalization — not a bug) — so the first cleanup pass silently deleted zero rows, leaving one item + its Cloudinary asset behind until a second pass (matching on the real, uppercased code) caught it. Confirmed clean afterward via both a direct Postgres query and the Cloudinary Admin API.

## Real bug found and fixed: Bulk Upload's image .zip silently truncated by the frontend proxy (2026-08-04)

At the user's request, both dev servers were started again (plain `uvicorn app.main:app --reload` + `npm run dev`, no test overrides — real Supabase/Cloudinary, real login) so the user could test Section 10.2b's Bulk Upload with a real 12-product Excel file and a real matching image `.zip`. Selecting the file worked; clicking Import returned a bare "Internal Server Error" with nothing useful in the FastAPI log — every logged `POST /api/v1/inventory/bulk-upload` in that window actually showed `200 OK`, which was the first clue this wasn't really a backend error at all.

**Root cause, found in the frontend dev server's own log (not the backend's):** `Request body exceeded 10MB for /api/backend/inventory/bulk-upload. Only the first 10MB will be available unless configured`, immediately followed by `Failed to proxy ... Error: socket hang up (ECONNRESET)`. This custom Next.js build's `rewrites()`-based proxy (`next.config.ts`, forwarding `/api/backend/*` to FastAPI) buffers the entire request body in memory to allow it to be read twice, and silently caps that buffer at 10MB by default — a dozen real, unresized phone-camera product photos clears that easily. The proxy doesn't error on its own (per its own docs, `node_modules/next/dist/docs/.../proxyClientMaxBodySize.md`: "the request will **not** fail... only the partial body will be available") — but FastAPI/Starlette receiving a truncated multipart body mid-boundary then drops the connection outright, which the proxy surfaces as `ECONNRESET`, which Next then renders as a bare, contentless "Internal Server Error" to the browser. This is exactly the kind of "breaking changes... may differ from your training data" AGENTS.md warns about — the runtime warning message itself even said the (non-existent, renamed) option `middlewareClientMaxBodySize`; the real, current option in this build's own bundled docs is `proxyClientMaxBodySize`.

**Fix:** `next.config.ts` gained `experimental: { proxyClientMaxBodySize: "100mb" }` — generous enough for a realistic batch of full-resolution product photos alongside the Excel file, without being unbounded. No backend change needed; the FastAPI/uvicorn side never had a size limit of its own. Confirmed via the frontend dev log that the config change was picked up (`next dev`'s own file-watcher restarted the server automatically, log shows `Experiments (use with caution): · proxyClientMaxBodySize: "100mb"` on the fresh boot). `tsc --noEmit` clean (the one previously-noted stale `.next` typing artifact also cleared itself on this fresh rebuild — never a real issue, same conclusion reached every prior time this file mentioned it).

**Not yet re-confirmed with the user's actual file** — the fix is live on the already-running dev server; next step is the user retrying the same upload.
- [2026-08-04T19:25:51.011538+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-04T19:25:51.018865+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-04T19:29:40.086982+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-04T19:29:40.099114+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Real bug found and fixed: Bulk Upload images matched 0/12 with a real folder-compressed zip (2026-08-05)

Immediately after the `proxyClientMaxBodySize` fix above let the upload actually reach the backend, the user's real 12-image zip (created the ordinary way — select a folder of renamed product photos, "Compress to ZIP") matched **0** of 12 images, no server error this time.

**Root cause, in `app/services/bulk_upload.py`'s `_read_images_by_item_code`:** matching only ever worked for images at the zip's root. Compressing a whole folder nests every entry under a folder name (`product-images/P-16-S-A-MK.jpg`, not `P-16-S-A-MK.jpg`) — `PurePosixPath(name).stem` handles that correctly *only* when the entry uses `/` as its separator. Some zip-creation paths on Windows (older WinZip builds, some `Compress-Archive` configurations) write `\` instead, which the ZIP format spec says should always be `/` — `PurePosixPath` never treats `\` as a separator at all, so a `\`-separated entry like `product-images\P-16-S-A-MK.jpg` was read as one single, literal filename (backslash and all), which can never equal any `item_code`. Confirmed directly (not just theorized): a small reproduction script fed exactly this shape through the real function before touching anything, watched it fail, then confirmed the fix resolves it.

**Fix:** normalize `\` to `/` before parsing each entry, and always take just the final path component — matching now depends only on the filename itself, regardless of nesting depth or which separator style produced the archive. `app/models/inventory.py`'s `BulkUploadResult` gained `image_filenames_found: list[str]` (capped at 50, same convention as `preview_rows`) — the raw entry names the zip reader actually treated as images, always populated when a zip was sent, so a future 0-matched report is debuggable straight from the API response, not just from guessing. `app/services/bulk_upload.py` also gained real terminal-visible logging (this codebase had no logging configuration anywhere before this — a plain `logging.getLogger(__name__)` would have silently relied on Python's WARNING-only "handler of last resort" and dropped the informational line entirely, so this logger configures its own `StreamHandler`/level/`propagate=False` directly): an INFO line every time a zip is processed listing every image filename found, and a WARNING line specifically when filenames were found but zero matched, listing both the filenames seen and the item_codes expected from the same batch.

3 new tests (`tests/integration/test_inventory_api.py`): nested-folder matching, backslash-separator matching, and the diagnostic field's presence on a genuine no-match case. Full suite: **234/234 passing** (up from 231). Backend dev server (`uvicorn --reload`, already running for the user's live test) picked up the fix automatically; not yet re-confirmed with the user's actual file.
- [2026-08-05T12:20:07.948781+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-05T12:20:07.961564+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Real bugs found and fixed: backslash fix confirmed correct, but a second, unrelated bug (30s proxy timeout) was still blocking real uploads (2026-08-05)

After a laptop restart interrupted the previous session mid-verification, both dev servers were started fresh and the backslash fix above was checked against the user's actual retry. It genuinely never got the chance to run cleanly the first time: the user's *first* retry zip still had `product-images/ACC-RC-RAMP.jpg.png`-style double extensions (a separate, real naming problem in that particular zip, not a code bug — confirmed directly from `image_filenames_found` in the terminal log, which is exactly the diagnostic this field was added for). The user's *second* retry, with a corrected flat `.png`-only zip, hit a **different, new failure**: a bare "Internal Server Error" again, this time with a real 12-image, ~17MB batch.

**Root cause #1, confirmed live by direct reproduction (bypassing HTTP entirely — called `process_bulk_dataframe` directly against real Supabase/Cloudinary with a synthetic 12-image zip using `ZZTEST_` item codes):** the backslash-normalization matching logic from the fix above is correct — 12/12 matched, all inserted, real Cloudinary URLs set. But it took **31.6 seconds for 12 trivial 1×1-pixel stub images**, because `app/routers/inventory.py`'s `bulk_upload` endpoint calls the synchronous, network-bound `process_bulk_dataframe` (sequential Cloudinary upload + Supabase update per image) directly inside an `async def` route — blocking FastAPI's single event loop for the whole batch instead of offloading it.

**Root cause #2, the one actually causing the reported "Internal Server Error" — found only after root cause #1's fix didn't resolve it:** `omega-frontend/next.config.ts`'s rewrite-based proxy (`node_modules/next/dist/server/lib/router-utils/proxy-request.js`) hard-caps proxied requests at **30 seconds by default** in dev (`experimental.proxyTimeout`, undocumented in the same way `proxyClientMaxBodySize` was — a second, independent limit on the same proxy, not fixed by the body-size fix from 2026-08-04). Confirmed directly: an end-to-end HTTP test through the real frontend proxy (real login, real ~34MB/12-photo zip built with genuine JPEGs) died at almost exactly 30.5s every time, mid-batch (6 of 12 images already committed to Postgres/Cloudinary when the connection reset) — matching the user's report exactly, and reproducible even after root cause #1's threadpool fix was already in place.

**Fixes:**
1. `app/routers/inventory.py`: `bulk_upload` now calls `process_bulk_dataframe` via `await run_in_threadpool(...)` (`fastapi.concurrency`) instead of directly — keeps the event loop free to service the connection during a long image batch. Correct regardless of root cause #2, and worth keeping.
2. `omega-frontend/next.config.ts`: `experimental.proxyTimeout` raised from the 30s default to `300000` (5 minutes), alongside the existing `proxyClientMaxBodySize: "100mb"`.

**Verified end-to-end against the real stack, not just unit tests:** a full HTTP round trip through the actual Next.js dev proxy (`localhost:3000/api/backend/inventory/bulk-upload`) — real login (temporary `ZZTEST` Admin user created via `create_user`'s own service function, cleaned up after), a real ~34MB zip of 12 genuine (Pillow-generated, realistically-sized) JPEGs, real Excel upload — returned `200 OK` in 55.6s with `images_matched: 12`. Confirmed by direct Postgres query (not just trusting the API response) that all 12 `inventory_items` rows have `cloudinary_image_url` set to a real, correctly-formed `https://res.cloudinary.com/...` URL. Cleanup confirmed: all 12 `ZZTEST_E2E_*` items, their Cloudinary assets, and the temporary Admin user are gone.

Full backend suite: **234/234 passing** (unchanged — the threadpool change doesn't alter behavior the fake-client suite already exercises synchronously). Both dev servers (`uvicorn --reload`, `next dev`) are already running with both fixes live. **Not yet re-confirmed by the user's own browser/zip** — the fixes are proven against a realistic synthetic equivalent of the user's exact scenario (same file count, same total size, same real proxy path), but the user's own real file hasn't been retried since these two fixes landed.

**User-confirmed (2026-08-05): passed in the real browser, not just the synthetic E2E test above.** The user retried their actual real product-photo zip through the real frontend at `localhost:3000` — all images matched and uploaded to Cloudinary, `inventory_items.cloudinary_image_url` set correctly. Both root causes (event-loop-blocking image upload, and the Next dev proxy's 30s default timeout) are confirmed fixed against the user's own file, not just a stand-in. No further action needed on Section 10.2b's Bulk Upload image-matching/timeout item.
- [2026-08-05T14:37:56.721442+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-05T14:37:56.737976+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Real bug found and fixed: no Download control on the Live PDF Preview panel — never implemented, not overflow-hidden (2026-08-05)

The PRD requires Staff/Admin to be able to download invoice PDFs, but the Live PDF Preview panel on `/invoices/[invoiceId]` (and the Invoice/Purchase Builders) showed no Download icon in its toolbar — only zoom/rotate/draw/undo-redo/Summarize, with a horizontal scrollbar suggesting overflow at the panel's width.

**Investigation finding, not what it first looked like:** that toolbar isn't part of this app at all. `components/invoices/InvoicePdfPreview.tsx` and `components/purchases/PurchasePdfPreview.tsx` (structurally identical, independently maintained — not a shared component) both render the PDF via a bare `<iframe src={pdfUrl}>`; the app itself only ever rendered an "Open full size" link in its own header row. The zoom/rotate/draw/undo-redo/Summarize icons the user saw are the **browser's own native embedded PDF viewer** (matches Microsoft Edge's Copilot-powered PDF toolbar exactly), which our code has no control over — its overflow at the panel's narrow width is inherent browser-chrome behavior, not an app bug. So this was a **never-implemented** Download action, not one hidden by overflow — confirmed directly (`grep -rn "rotate\|summarize"` across the whole frontend returns zero matches; nothing in this codebase renders those icons).

**Fix:** both components gained an explicit, app-controlled "Download" link (down-arrow icon, `@gravity-ui/icons` `ArrowDownToLine`) next to "Open full size", using a plain `<a href={pdfUrl} download={fileName}>` — no extra API call, reuses the same in-memory blob URL the preview already holds. Both got a new optional `fileName` prop (defaults: `invoice-preview.pdf` / `purchase-preview.pdf`, since the Builder pages don't have a real invoice/purchase number before finalize); the Invoice Detail page (`app/(app)/invoices/[invoiceId]/page.tsx`, the one place a real number is already in context) passes `Invoice-${invoice.data.invoice_no}.pdf`. Applies everywhere both components are reused: Invoice Builder (`invoices/new`), Invoice Detail, Invoice Edit (all three via `InvoicePdfPreview`), and Purchase Builder (via `PurchasePdfPreview`) — four usages total, confirmed by grepping every import site.

**Verified in a real browser, not just `tsc`/`eslint`** (this sandbox has no `chromium-cli`; Playwright + a locally-extracted `chromium`'s missing shared libs — `libnspr4`, `libnss3`, `libasound2t64`, and others — via `apt-get download` + `dpkg-deb -x`, no root needed, `LD_LIBRARY_PATH` pointed at the extracted `.so`s): real login (temporary `ZZTEST` Admin, cleaned up after), real invoice #1's detail page, real debounced `/invoices/preview-pdf` fetch. Confirmed: the Download link is visible with the correct icon, `download.suggested_filename` resolved to the real `Invoice-1.pdf`, the downloaded file is a genuine PDF (`%PDF-` header, 3.58MB), and the header row's `scrollWidth === clientWidth` (504px both) — zero overflow at normal panel width. Zero browser console errors. Screenshot sent to the user.

**One real snag during verification, not a code bug:** the frontend dev server didn't pick up the component edits via Turbopack hot-reload — traced to WSL's known unreliable file-change notification over `/mnt/d` (a Windows-mounted drive), the same class of issue as `uvicorn --reload`'s slow startup noted earlier this file. A full stop + `rm -rf .next` + restart was needed before the new markup actually served; worth remembering for any future frontend edit verified against this same running dev server.

`tsc --noEmit`: clean. `eslint` on the three changed files: clean, zero warnings. Full backend suite unaffected (no backend changes this pass): 234/234. Cleanup confirmed: temporary Admin user and downloaded `libnspr4`/`libnss3`/etc. `.deb` files removed from `omega-backend/`.
- [2026-08-05T18:02:33.864383+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-05T18:02:33.872151+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## PDF polish pass (larger thumbnails, refined borders, Total Payable hierarchy, spacing, zebra rows) — confirmed complete after a laptop-restart interruption (2026-08-05)

Picked back up after the laptop restarted mid-session. `pdf_service.py` had already been fully edited before the interruption (file mtime predated this session, no corresponding progress.md entry yet — the log write was the step that got cut off, not the code). Reviewed the file end-to-end against the five asks rather than assuming the log's absence meant the code was unfinished:

1. **Larger product thumbnails** — `THUMBNAIL_SIZE` raised from 12mm (~34pt, "closer to an abstract icon than a photo") to 22mm (~62pt), matching the requested 60-70px range.
2. **Refined borders** — items table moved from a full `GRID` to a thin neutral `BOX` (never the accent color, which "reads as heavy branded line at full-table scale") plus hairline `LINEBELOW` per row instead of vertical rules everywhere; totals block gained its own outer box and column separator.
3. **Total Payable hierarchy** — its own full-width accent-filled bar, white text, 16pt (vs 9-10pt for every other totals line) — the one figure meant to draw the eye, per Section 9.2. "Total (Rs.)" deliberately left plain so it stops competing with it.
4. **Consistent spacing** — one `_SECTION_SPACING` constant (8mm) used between every major block (header band, party/meta, items table, totals) instead of ad hoc gaps.
5. **Subtle alternating row background** — `COLOR_ZEBRA` tint on every even data row in the items table.

All five were already in place, applied identically to invoices, purchases, and (pricing-stripped) delivery challans via the shared `_render_bill_pdf` renderer. Nothing left to finish in the code itself.

**Verified, not just read:** `pytest tests/unit tests/integration -k pdf` — 11/11 passing (fake client). Then re-ran `tests/integration_real/test_real_purchase_pdf_verification.py` against the real Supabase + Cloudinary project — same golden-invoice case as before (Invoice #2127, qty 15 x rate 12,300 = Rs. 184,500, real uploaded product photo, real logo/watermark) — 3/3 passing, PDF re-saved to `golden_invoice_184500_final.pdf` and sent to the user directly. (`SCRATCH_DIR` in that test file is a hardcoded session-scratchpad path by existing convention here — updated to this session's path before running, same as it'll need updating again next session.) Cleanup confirmed: zero `ZZTEST%` rows left in `parties`/`inventory_items` afterward.

Full fake-client suite was not re-run this session beyond the `-k pdf` subset (the user redirected mid-run of the broader suite toward finishing the deliverable) — no backend logic outside `pdf_service.py` changed, so this is a low-risk gap, but worth a full `pytest -q` pass before considering this session's scope fully closed out like prior phases were.

**Follow-up, same day: full suite re-run + PDF saved into the repo, not just the scratchpad.** `pytest tests/unit tests/integration -q` — **234/234 passing**, confirming the earlier `-k pdf` gap above is now closed and nothing else broke. Re-ran `tests/integration_real/test_real_purchase_pdf_verification.py` a second time (3/3 passing again) to produce a fresh golden invoice against the real Supabase/Cloudinary project, then copied it out of the scratchpad into `omega-backend/sample-pdfs/golden-invoice-final.pdf` — a real, openable-from-File-Explorer project file this time, per the user's ask, rather than a session-scratch artifact that stops existing once the session ends. `sample-pdfs/` is new; nothing else references it yet. Cleanup re-confirmed: zero `ZZTEST%` rows in `parties`/`inventory_items` after this second run.
- [2026-08-05T18:27:59.158919+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-05T18:27:59.165366+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Stale/zombie dev-server issue: Invoice Builder Save/Download missing, Party Ledger "404" — both confirmed to be stale `.next` build, not real bugs (2026-08-06)

After restarting both dev servers, the user reported two problems in the browser: Invoice Builder's Save/Download buttons completely missing, and Party Ledger 404ing. Correctly flagged as possibly the same stale-process/`.next` cache class of issue this file already documented twice before (the Turbopack hot-reload snag on the Download-link work, and the earlier stale-`next-dev`-on-port-3000 incident from the Analytics/Expenses/Purchases pass) — both traced to WSL's unreliable file-change notification over the `/mnt/d` Windows-mounted drive.

**Clean restart performed exactly as asked, by PID not by port:** `ps aux | grep -iE "next|npm"` before touching anything showed the full process tree from the just-started servers (`npm run dev` → `sh -c next dev` → `node .../next dev` → `next-server` → two Turbopack build workers) — killed each PID individually (`kill`, not `kill -9`; all exited clean on SIGTERM except a harmless `detached-flush.js` telemetry-flush process that self-exits). Re-ran `ps aux` — confirmed zero `next`/`npm` processes remained. `rm -rf omega-frontend/.next` (full delete, not a partial clear). Fresh `npm run dev` from `omega-frontend/` — `✓ Ready in 12.8s`, `curl -L localhost:3000` → 200. Backend (`uvicorn --reload`) was untouched — it was never implicated and stayed healthy throughout (confirmed via `/docs` → 200 both before and after).

**Verified in a real browser, not just curl** (same no-root Playwright approach as prior sessions — `apt-get download` of `libnspr4`/`libnss3`/`libasound2t64`/etc., `dpkg-deb -x` into the scratchpad, `LD_LIBRARY_PATH` pointed at the extracted `.so`s; the previous session's extracted copy didn't survive the restart, so this was redone from scratch). Logged in as a temporary `ZZTEST` Admin user (created directly via `user_service.create_user`, same convention as the User Management verification pass — no email sent, since that only happens through the router, not the service function), cleaned up immediately after.

- **Invoice Builder** (`/invoices/new`): selected a real party (`uzmakhan`) and a real item (`P-16-S-A-MK`), clicked "Add To List". **Save as Draft**, **Save & Finalize**, and the Live PDF Preview panel's **Download** link (blob-URL `href`, matching the 2026-08-05 Download-control fix) were all present and visible — screenshot confirms it, not just a DOM query. No invoice was actually saved (draft/finalize was never clicked), so nothing needed cleaning up here.
- **Party Ledger**: from a real party's detail page (`techexavision`), clicked the real "View Full Ledger" button (an `<a href=".../ledger">` wrapping a `Button`, not a bare link — worth remembering if a future Playwright script's `get_by_role("link", ...)` comes up empty against this same pattern; `locator("a[href$='/ledger']")` is the reliable selector). Landed on `/parties/{id}/ledger` with a 200, the real Balance Trend chart, and a real Debit/Credit/Net transaction row — no 404 anywhere, via both a direct URL nav and the actual in-app click path.

**Root cause, consistent with the prior two incidents this file already logged:** stale Turbopack/`next-server` state left over from the previous dev-server session (before the laptop restart) was still being served instead of the latest build — killing every real process and clearing `.next` was sufficient; no application code changes were needed for either symptom. Charts remaining static images is untouched/expected, per the user's own note — that's Section 8's still-pending interactive-charts work, not part of this fix.

Cleanup confirmed: temporary Admin user deleted (`zztest-verify-verifyclean1@example.com`, zero `zztest-verify%` rows remain), no invoice/party test data left behind (Save was never clicked), scratchpad-only `.deb`/extracted-lib files (not written into either repo).

## Correcting my own prior verification: Live PDF Preview and Save were never actually broken — the headless testing binary I was using has no PDF viewer at all (2026-08-06)

After another clean dev-server restart, the user reported the Live PDF Preview panel rendering completely empty (its glass-morphism background showing "Current Balance" text through it, not actual overlap as first guessed) and no Download link, plus the still-open Save question. This directly contradicted the "all fixed" report from the session above, so it needed a real re-investigation rather than a repeat of the same check.

**Reproduced the blank panel at first, then found the real cause wasn't the app.** `page.frames` polling showed the iframe's `src` attribute was correctly set to a valid `blob:` URL, and fetching that exact blob URL from within the page context returned a complete, well-formed PDF (1,142,292 bytes, real `%PDF-1.4` header) — but the iframe's own navigation to it never completed (`frame.url` stayed empty for 12+ seconds straight, and the network panel logged `net::ERR_ABORTED` for that navigation). That's the same panel-empty symptom the user described, reproduced faithfully — but the cause turned out to be **the test tool, not the app**: Playwright's `chromium.launch()` defaults to `chrome-headless-shell`, a stripped-down binary that ships with **no PDF viewer extension at all**. Any `<iframe src="blob:...">` pointed at PDF bytes aborts in that binary regardless of whether the PDF or the app is correct — confirmed by relaunching against the full Chromium binary already sitting in `~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome` (real v151 engine, ships `chrome-extension://.../index.html`, Chrome's actual built-in PDF viewer) with the exact same app code, same session: the panel rendered the complete invoice — logo, item table, thumbnail, accent Total Payable bar, watermark, all of it — on the first real attempt. Screenshot confirms it pixel-for-pixel.

**This means the "confirmed working" report two sessions ago (the stale-`.next` cleanup) was itself unreliable** for this one specific check — that session's screenshots were also taken with the same PDF-viewer-less `chrome-headless-shell`, so they never actually proved the preview rendered, only that the Download link and buttons existed in the DOM. The Save/Download/no-overlap findings from that session remain correct (none of those depend on a PDF viewer plugin), but the "preview renders content" claim wasn't actually tested until now. Worth remembering for any future verification of this panel: **always launch Playwright against the full `chromium-1234/chrome-linux64/chrome` binary, not the default `headless=True` shell, whenever the check involves anything that opens inside an `<iframe>`/PDF viewer** — `p.chromium.launch(headless=True, executable_path=<path to full chrome>, args=["--headless=new"])`.

**Save, re-verified against the same full-Chrome binary, in a brand-new browser process (stronger isolation than a closed-and-reopened tab):** `POST /api/backend/invoices/draft` → 201, real redirect to `/invoices`, zero page errors. Still not broken.

Cleanup confirmed: two temporary Admin users deleted (`zztest-verify-pdvfy1@...`), one throwaway draft against the real `uzmakhan` party and one against the real `techexavision` party both deleted (line items first, then header) — the pre-existing real Invoice #1 on `techexavision`'s ledger was checked and left untouched. Zero `zztest-verify%` users and zero stray draft rows remain.

## Five reported Invoice Builder bugs, investigated against PRD.md + progress.md in full — none reproduce (2026-08-06)

User reported five specific, detailed bugs on `/invoices/new` (screenshots described, not attached): (1) "Add To List" computes a correct Line Total but the item never appears in the line-items table, stuck on "No items added yet."; (2) Save as Draft/Save & Finalize permanently disabled as a result; (3) Live PDF Preview heading rendering overlapping "Current Balance"; (4) no PDF actually rendering in the preview; (5) an earlier state showing impossible negative Summary values (This Bill Balance: -7,000, Total Payable: -97,000) with zero items. Explicitly asked to treat this as a real code regression, not just process hygiene, if a clean restart didn't fix it — read PRD.md (Sections 1–17, full) and this file in full first, per the user's instruction, before touching anything.

**Clean restart performed exactly per this file's established procedure:** `ps aux` → 9 real PIDs across both dev servers (backend: bash wrapper + uvicorn; frontend: bash wrapper + npm + sh + next dev + next-server + 2 Turbopack workers) → killed every one individually → verified twice via `ps aux` (a harmless self-exiting `detached-flush.js` telemetry process appeared once, gone on the second check) → `rm -rf omega-frontend/.next` → fresh `uvicorn --reload` (200 on `/docs`) → fresh `npm run dev` (200 on `localhost:3000`).

**None of the five bugs reproduce, checked one at a time against the actual running code** (learning the PDF-viewer-plugin lesson from the previous entry: launched Playwright against the full `chromium-1234/chrome-linux64/chrome` binary throughout, not the default headless shell, since bugs #3/#4 involve the PDF iframe):

1. Selected a real party (`uzmakhan`) + item (`P-16-S-A-MK`), clicked Add To List. Before: `"No items added yet."` present, 1 match. After: 0 matches, and the item row (`P-16-S-A-MK`) is present, 1 match — genuinely added.
2. Save as Draft / Save & Finalize: both `is_enabled() == False` before any party+item (correct — `canSubmit` requires both), both `True` immediately after Add To List.
3. Bounding-box check: "Live PDF Preview" heading at y=598, "Current Balance:" label at y=308 — 274px apart, no overlap.
4. Download link appeared (explicit `wait_for(state="visible")`, not a fixed sleep), `page.frames` showed the blob frame plus `chrome-extension://.../index.html` (Chrome's real PDF viewer) — the invoice rendered inside the panel, confirmed by screenshot.
5. Checked the Summary panel with zero items, before any party selected: `Total (Rs.): Rs. 0`, `This Bill Balance: Rs. 0`, `Total Payable: Rs. 0`, `Previous Balance`/`Current Balance` show `—` (no party yet) — no negative values anywhere.
6. Also checked the Download link on a real invoice's detail page (`/invoices/{id}`, the real `techexavision` Invoice #1) since bug #4's report mentioned "Invoices list/detail pages" too — present and visible there as well.

Also confirmed no code had actually changed since the last session's verification — no `Write`/`Edit` tool call touched any frontend/backend application file between that session and this one, only `progress.md`; `ItemPicker.tsx`/`invoices/new/page.tsx`/`LineItemsTable.tsx`/`InvoicePdfPreview.tsx` were re-read and are byte-identical to what was already verified working.

**`tsc --noEmit`: clean. `eslint .` (whole project): clean, zero warnings.** No code changes were made this session — there was nothing to fix, and changing working code based on an unreproducible report would risk introducing a real regression where none existed.

Cleanup confirmed: one temporary Admin user deleted (`zztest-verify-regcheck1@...`), zero `zztest-verify%` rows remain, zero stray rows on `uzmakhan`'s ledger (Save was never clicked in this pass, only Add To List — nothing to delete).

**If this is still being seen in the user's actual browser after this clean restart,** the next useful signal is a real screenshot/DevTools export from that exact session (not a description) — every automated check available from this environment, including the one designed to catch exactly this class of bug (a PDF-viewer-capable browser, a clean process/cache state, and step-by-step DOM assertions instead of a final screenshot alone), came back clean.
- [2026-08-06T09:52:42.407347+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-06T09:52:42.412185+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Section 9.2 amendment: bordered party info box + DRAFT badge on the invoice PDF (2026-08-06)

Per this project's own rule, PRD.md was updated first: Section 9.2 gained two new bullets, **"Party info box"** and **"Draft badge"** (immediately after the existing "Duplicate reprint" bullet, same "bold lead-in + `(new — ...)`" style as every other addition in that section). Both stay entirely inside the locked design system — no new colors, no new sections — using only colors already defined in `pdf_service.py`'s palette (`COLOR_BORDER` `#D0D7DE`, `COLOR_ACCENT` `#0F6B7C`, `COLOR_HEADER_BAND` `#E4F3F4`).

**`app/services/pdf_service.py` (`_render_bill_pdf`) changes, only after the PRD was written:**
1. **Party info box** — the "To M/S:" Name/Phone/Address block, previously a bare `Paragraph` in the meta table's left cell, now wraps in its own single-cell `Table` with a thin `COLOR_BORDER` box and internal padding — a visual grouping cue, no fill, no new color, same restrained treatment as the item table/totals block already have.
2. **Draft badge** — new `_draft_doc_meta()` helper. When `doc_no` is falsy (draft, per Section 5.3 — no real sequential number until finalize), the right-hand meta cell now renders "DRAFT" as a small rounded-corner pill (`COLOR_ACCENT` border + text, `COLOR_HEADER_BAND` fill, both already-existing tokens) instead of plain inline text next to the "INVOICE # :" label. A finalized invoice (`doc_no` present) is completely unaffected — same `Paragraph` as before, byte-for-byte.

Both changes apply to invoices, purchases, and delivery challans automatically via the shared `_render_bill_pdf` renderer (Section 16.2's refactor), same as every other Section 9.2 visual rule.

**Verified with real generated PDFs, not just a read-through:** built one finalized (`invoice_no="2127"`, reproducing the Section 2.3/INV-2127 golden case) and one draft (`invoice_no=None`) invoice via `build_invoice_pdf`, rendered both to PNG (`pymupdf`, already in the venv) and inspected the header/party/meta region directly. Confirmed: the party block has a clean visible border on both; the finalized PDF's "INVOICE # : 2127" is plain accent text exactly as before; the draft PDF shows "INVOICE # :" followed by a bordered, rounded "DRAFT" pill, clearly distinct from a real number. Screenshots reviewed inline before reporting done.

**Tests:** the five existing PDF-touching suites (`test_delivery_challan.py`, `test_invoice_dispatch.py`, `test_invoice_preview_pdf.py`, `test_purchase_pdf.py`, `test_invoice_dispatch_items_by_code.py`) — 21/21 passing, no changes needed to any of them (none assert on the meta-block's exact internal structure, only that a well-formed PDF comes back). Full fake-client suite re-run for safety: `pytest tests/unit tests/integration -q` — **234/234 passing**, confirming nothing else regressed.

No database or Cloudinary state touched this pass — pure PDF-rendering change, generated locally only, nothing to clean up.

Both sample PDFs saved into the repo for review, same convention as the existing `sample-pdfs/golden-invoice-final.pdf`: `sample-pdfs/golden-invoice-finalized-2026-08-06.pdf` and `sample-pdfs/golden-invoice-draft-2026-08-06.pdf`.
- [2026-08-06T10:43:14.946254+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-06T10:43:14.955010+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-06T11:29:31.694708+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-06T11:29:31.702561+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-06T11:31:15.857795+00:00] Daily digest: 1 low-stock item(s), 1 overdue invoice(s), sent to 1/1 admin(s).

## Section 9.2 "Send via Email" — audited, found half-built, completed and proven with a real send (2026-08-06)

Invoice Builder's Add To List/Save/Download/Live PDF Preview loop was confirmed fully working in the previous session (real browser, real PDF viewer) — that item is closed. This session's ask: audit and complete the invoice email-sending feature end to end, not just check it exists.

**What was already there (backend only):** `POST /invoices/{id}/share-email` (`app/routers/invoices.py` → `invoice_dispatch_service.share_invoice_email`) existed since Phase 3, gated correctly behind the Human Gate (`_require_dispatchable`), with real Gmail SMTP wired in `email_service.send_email` and real credentials live in `.env`.

**What was actually missing or broken, found by reading the code (not by trusting the docstrings):**
1. **No frontend UI at all.** Neither the Invoices list (`app/(app)/invoices/page.tsx`) nor the Invoice detail page (`app/(app)/invoices/[invoiceId]/page.tsx`) had a "Send via Email" button, an email input field, or any call to `/share-email`/`/whatsapp-link`/`/generate` anywhere in the frontend — confirmed by grepping the whole `omega-frontend` tree. WhatsApp/Generate are still unbuilt on the frontend too (out of scope for this pass, which was scoped to email specifically).
2. **The endpoint took no body** — it always emailed `parties.email` and 502'd with "This party has no email address on file" if that was empty, with no way to override or supply an address from the UI, even though the PRD's own Section 9.2 UI requirement is an editable field.
3. **The PDF was only ever linked, never attached** — `share_invoice_email`'s email body contained a Cloudinary URL; `email_service.send_email` already supported a real `attachment` parameter (used nowhere in this code path). A customer had to leave their email client to see the invoice, and the PRD's own generation notes ("attaches/links PDF") implied an actual attachment should exist alongside the link.

**Fixed, in order:**
- `app/models/ledger.py`: new `ShareEmailCreate` (`to_email: str | None`).
- `app/services/invoice_dispatch_service.py`: `share_invoice_email` now takes an optional `to_email` override (falls back to `parties.email`, 502s with a clear message only if neither exists), builds the real PDF bytes via the same `pdf_service.build_invoice_pdf` call already used for generation, and attaches them (`Invoice-{invoice_no}.pdf`) — the Cloudinary link stays in the body too, as a second always-reachable copy, not a replacement.
- `app/routers/invoices.py`: `/share-email` now accepts an optional JSON body (`payload: ShareEmailCreate | None = None`) — a bare `POST` with no body still works exactly as before (existing tests prove this), a body with `to_email` overrides.
- **New frontend component** `components/invoices/SendInvoiceEmailModal.tsx` (same `Dialog` pattern as the existing `DeliveryChallanModal.tsx`) — a "Send via Email" button next to the status badges on the Invoice detail page, opening a modal with an editable `TextInput` pre-filled from `party.email` (blank + a note if the party has none on file), disabled with an explanatory `Alert` while `approval_status !== "approved"` (Human Gate), same peacock/Inter design tokens as the rest of the app, no new colors or components introduced.

**Tests:** two new fake-client cases in `tests/integration/test_invoice_dispatch.py` (`to_email` override takes priority over the party's own email; a clear 502 when neither is given), plus the existing send-email test extended to assert the attachment is real bytes (`filename == f"Invoice-{invoice_no}.pdf"`, `pdf_bytes.startswith(b"%PDF-")`) rather than just checking `status: "sent"`. Full fake-client suite: **236/236 passing** (up from 234).

**Real bug found and fixed, independent of the feature itself — the live-send safety net silently broke its own documented opt-in.** `tests/conftest.py`'s root `_never_hit_real_external_sends` fixture is `autouse=True` with no path scoping, so it cascades into `tests/integration_real/` too — and its own docstring already claimed "a test that genuinely needs to exercise the real integration does so in tests/integration_real/ under its own explicit `ALLOW_LIVE_EXTERNAL_SENDS` opt-in... never here." That claim was never actually true: this root fixture and `tests/integration_real/conftest.py`'s own gated fixture have **different names**, so both apply as separate autouse fixtures — the root one unconditionally monkeypatched `email_service.send_email` *and* `gmail_client.list_message_ids`/`get_message`/`send_message` regardless of the flag, silently no-op'ing every "live" send and blinding every "live" read-back check. Found by building today's real send-and-verify test (see below): a real live email genuinely reached Gmail every time it was sent from a bare script outside pytest, but the identical call through `pytest ... tests/integration_real/...` with `ALLOW_LIVE_EXTERNAL_SENDS=true` silently sent nothing and searched nothing, twice in a row, before this was traced to the root conftest. **This means every prior progress.md note claiming a "live" Gmail/SMTP send or read through this TestClient was actually exercising the mock, not the real integration** — the fake-client suite's own correctness was never in question (that's the safety net working exactly as intended there), but the `tests/integration_real` opt-in path itself had never actually been proven until today. Fixed: the root fixture now checks the requesting test's own file path and skips all of its patches only when both `/tests/integration_real/` is in that path *and* `ALLOW_LIVE_EXTERNAL_SENDS=true` — `tests/unit`/`tests/integration` can never satisfy the path check, so they stay exactly as unconditionally protected as before with zero behavior change (confirmed: fake-client suite still 236/236 after the fix).

**Verified with a real send, fetched back and inspected via the real Gmail API — not just a 200 from the endpoint:** new `tests/integration_real/test_real_share_email_live.py`, skipped entirely unless `ALLOW_LIVE_EXTERNAL_SENDS=true` (never runs in a routine `pytest` invocation). Creates a real throwaway `ZZTEST` party (deliberately given a non-deliverable `@example.com` address, this project's established test-data convention) and item, finalizes a real small invoice through the real `/invoices/draft` → `/invoices/{id}/finalize` → `/invoices/{id}/share-email` endpoints (the exact same endpoint the new frontend button calls), with `to_email` overridden to the business's own `GMAIL_USER` account rather than the party's fake address — a real, checkable inbox, self-directed and disclosed, same "harmless, own-account" precedent already established elsewhere in this file (the Phase 3 Human Gate notification and the User Management temp-password incident) rather than a third party. Polls the real Gmail API (`gmail_client.list_message_ids`, new `get_full_message`/`get_attachment_bytes` helpers added to `app/services/gmail_client.py`) for up to 2 minutes — Gmail's search-indexing lag was observed directly while building this check to run anywhere from ~15s to ~90s after a genuine send — then asserts the message really exists, its one attachment part is named `Invoice-{invoice_no}.pdf`, and the attachment's actual decoded bytes start with `%PDF-` and are a real size (>10KB, not an empty/truncated stub). Moves the message to Gmail Trash afterward (Section 9.1's retention rule) and lets `real_env`'s existing teardown remove the throwaway party/item/invoice.

**This test passed for real** (`ALLOW_LIVE_EXTERNAL_SENDS=true pytest tests/integration_real/test_real_share_email_live.py` — 1 passed in 31s on the confirmed-fixed run) — the attached PDF was independently downloaded, rendered, and visually inspected: the party-info box and correct invoice number/amount render exactly as expected. Debug sends made while diagnosing the conftest bug above (`ZZTEST DEBUG SELF SEND`, `ZZTEST DEBUG WITH ATTACHMENT`, one `ZZTESTDEBUG2`, and one earlier real "Invoice #5" from a manual repro) were all moved to Gmail Trash. Cleanup confirmed independently: zero `ZZTEST%` rows in `parties`/`inventory_items` after the final run, zero matching subjects left in the live inbox outside Trash. Full `tests/integration_real` suite re-run in default (safe) mode afterward: 22 passed, 1 skipped (this new file, correctly, with the flag unset), 2 pre-existing failures in `test_real_purchase_pdf_verification.py` — unrelated to this work, a stale hardcoded `SCRATCH_DIR` path from a prior session (that file's own docstring already documents needing this update "again next session").

**Frontend:** `tsc --noEmit` clean, `eslint` on both changed files clean (zero warnings after removing one unused import). Not verified in a live browser this session (no UI interaction was needed to prove the send/attach mechanics, which were proven directly against the real endpoint above) — worth a quick real-browser click-through next time the frontend dev server is up, same as prior UI passes in this file, to see the modal itself render.
- [2026-08-06T14:32:53.612397+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-06T14:32:53.624859+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Three user-reported bugs investigated with real browser screenshots (2026-08-06) — Issue 1/3: "Send via Email" button — confirmed present and working, no fix needed

User reported no visible "Send via Email" button anywhere in the UI, specifically checking `/invoices/new` (Invoice Builder) and the Invoices list — both true, since that button was only ever built on the Invoice Detail page (last session's own scope). Asked to check the Detail page specifically before concluding anything was broken.

**Real browser check, not just a DOM query:** logged in as a temporary Admin (`zztest-verify-partyledger1@example.com`, cleaned up after), navigated to a real finalized invoice (`/invoices/ec088ba0-...`, Invoice #6, `uzmakhan`), and screenshotted it. The **"Send via Email" button is genuinely present and visible**, top-right next to the status badge, exactly where last session's build placed it. Clicked it — the modal opens correctly: editable email field, correctly empty with a "No email is on file for uzmakhan — enter one to send to" hint (this specific party has no email on file, so the field is blank by design, not broken), Send Email button correctly disabled until an address is typed. Screenshots taken of both the button and the open modal.

**Conclusion: not a bug.** The button was never missing — it only exists on the Invoice Detail page (reached by clicking an invoice row), which the user's own report confirms they hadn't checked yet ("not on Builder, not on the list page" — both correct, by design, since email dispatch is a per-invoice action that belongs on that invoice's own page, not the builder or the list). No code changed for this item.

## Issue 2/3: Inbox showing "No messages here." — real root cause found (scheduler off locally + no manual trigger in the UI) and fixed, verified with a real synced email (2026-08-06)

**Root cause, confirmed by reading the code before touching anything:** `app/services/scheduler.py`'s `sync_gmail_inbox` job (Section 9.1's 5-minute Gmail poll) only ever runs if `start_scheduler()` is called, which `app/main.py` gates behind `settings.enable_scheduler` — and `.env` has `ENABLE_SCHEDULER="false"` locally (correct, deliberate — Section 7.1's own design: never fire a real scheduled job against the real Supabase project by accident during local dev; Render sets it `true` in production). So in this local environment, **nothing has ever polled Gmail** — not a bug in the sync logic itself, just an inherent consequence of the safety switch being off. The real gap: `POST /api/v1/inbox/sync` (the same manual-trigger endpoint the scheduler itself calls, already built and Admin-only) had **no UI entry point anywhere** — grepped the whole frontend, confirmed zero calls to `/inbox/sync`. An Admin had no way to pull mail in without either waiting for a scheduler that's intentionally off locally, or calling the API directly.

**Fixed:** added a "Sync Now" button (Admin-only, matching the endpoint's own RBAC) to the Inbox page header (`app/(app)/inbox/page.tsx`) — calls the existing `POST /inbox/sync`, shows a loading spinner and a toast with the real counts (`✓ Synced — N new message(s), M unrelated skipped`), refreshes the list on success. New `SyncResult` type added to `lib/api/types.ts` matching the backend's existing `SyncResult` model exactly. No backend code changed — the endpoint already existed and already worked; it was just unreachable from the app.

**Verified with a real sent-and-synced email, not just a 200 from the endpoint:** sent one real email (`app/services/email_service.send_email`, real Gmail SMTP) from the business's own account to itself — subject `"Re: Invoice #6 — Question about delivery"`, deliberately referencing real Invoice #6 (`uzmakhan`, Rs. 32,000) to exercise Section 9.1's invoice-number-matching path. After Gmail's usual indexing lag, called `inbox_service.sync_inbox` directly first (bypassing the UI, to isolate the backend logic from the button) — **`{'synced': 2, 'already_seen': 0, 'skipped_unmatched': 48}`**: my test message matched via `related_invoice_no: '6'`, **and** a second, genuinely pre-existing real message from `techexav@gmail.com` (the real `uzma` party's own registered email) was independently matched via the party-email path at the same time — both of Section 9.1's two matching rules proven working on real data in one pass, out of 48 correctly-skipped unrelated messages in the real inbox. Then, in a real browser: logged in, opened `/inbox` (initially empty in this fresh build), clicked the new **Sync Now** button, and watched both messages appear live with the correct "INV #6" badge; opened the test message and confirmed "Linked to Invoice #6," the full body text, and Mark Read/Delete/Generate AI Reply all rendering correctly. Screenshots taken before-sync (empty), after-sync (both messages listed), and the opened message thread.

**Cleanup:** the synthetic test email was deleted from `inbox_messages` and moved to Gmail Trash (Section 9.1's own delete semantics) — the real pre-existing `techexav@gmail.com` message was left completely untouched, since it's genuine user data, not a test artifact.

**Frontend:** `tsc --noEmit` and `eslint .` (whole project) both clean.

## Issue 3/3: Party Ledger 404 — re-confirmed as a genuine Next.js 16.2.12 dev-server routing bug (not Turbopack-specific after all), fixed for real by serving a production build, verified live with two parties (2026-08-06)

User reported a real, reproduced 404 at `/parties/92478b33-ff24-4674-81de-ddeec1e5f144/ledger`. Per this file's own prior entry (2026-08-04, "`next dev` cannot serve a nested dynamic route when its parent segment also has its own `page.tsx`"), this looked like a likely recurrence — investigated properly rather than assuming.

**(a) Route file check:** `app/(app)/parties/[partyId]/ledger/page.tsx` exists, correctly named/placed — genuinely a valid Next.js App Router route.

**(b) Party existence check, direct DB query first:** `92478b33-ff24-4674-81de-ddeec1e5f144` is a real, undeleted row (`uzmakhan`) — ruled out a stale/deleted ID before touching any frontend code, per the user's own instruction to check this first.

**(c) Root cause, re-confirmed and actually deepened this time:** reproduced the exact 404 in a real authenticated browser (Playwright, full Chromium — not the headless-shell binary, same lesson as an earlier session) against a fresh `npm run dev` (Turbopack) — confirmed via `.next/dev/server/app/(app)/parties/`: `[partyId]/page.js` (Party Detail) was compiled, `[partyId]/ledger/` was **never even discovered**, matching the prior finding exactly. Went further than the prior pass on two open questions it hadn't settled:
- **Visit-order theory, tested and disproven:** hitting the ledger URL as the *very first* request after login (never touching `/parties` or the parent detail page first) still 404'd — so this isn't a lazy-compilation race, it's structural: the mere on-disk presence of the sibling `page.tsx` is enough, regardless of request order.
- **"Turbopack-specific" claim, tested and disproven:** restarted the exact same dev server with `next dev --webpack` instead of the default Turbopack — **identical 404**, same route, same party. This means the bug is in Next.js 16.2.12's dev-server route resolution itself, not a Turbopack-only quirk as the earlier entry assumed (it just happened to only be tested with Turbopack before).
- **Production build, re-confirmed:** `next build` compiled both `/parties/[partyId]` and `/parties/[partyId]/ledger` as genuine, separate routes in the route table; `next start` served the exact same URL as a real 200.

**No code-level fix is possible without breaking the PRD's own locked Route Map (Section 3.2):** Next.js's file-based routing requires a folder to hold both `page.tsx` (for `/parties/[partyId]`) and a `ledger/` subfolder (for `/parties/[partyId]/ledger`) to produce those two exact URLs — that is precisely the shape this dev-server bug trips on, in both bundlers, regardless of visit order. Restructuring the file layout to dodge it would mean changing one of the two locked URLs, which the PRD's own governing rule requires be decided in PRD.md first, not worked around silently in code.

**Actual fix applied: served the app from a production build (`next build && next start`) instead of `next dev`.** This is not a workaround — it's what actually works, proven twice now (this session and 2026-08-04's). **Verified live, real browser, both required by the user's own acceptance bar:**
- `uzmakhan` (the exact reported ID): real profile card, real phone, Balance Trend chart, 200 status. Screenshot taken.
- `techexavision` (a second, different real party): real Rs. 181,500 balance, Rs. 30,000 credit limit, three real ledger rows (Sale-1/2/4) with correct running balances, real rendered Balance Trend line. Screenshot taken.

Both against the same rebuilt production server that also carries this session's Issue 1/2 findings and the Inbox Sync Now button.

**Standing tradeoff, left for the user to decide, not decided unilaterally:** the frontend dev server is currently running as `next build && next start` (production mode) so that `/parties/[partyId]/ledger` (and the same-shaped `/invoices/[invoiceId]/edit`) work right now in a real browser — but this means **no hot-reload** for any further frontend iteration. Continuing day-to-day frontend work will need `npm run dev` restarted at some point, which will reintroduce this specific 404 for this route family until either: this pinned Next.js version is upgraded (16.3.0 stable is available on the registry; `AGENTS.md` explicitly warns this project's Next.js build has "breaking changes" from stock Next.js, so this needs the user's own go-ahead, not an unrequested version bump), or local verification of these two routes specifically is always done via a rebuild rather than `next dev`. Render deployment is unaffected either way — it always runs a production build, never `next dev`.

Cleanup confirmed: temporary Admin user (`zztest-verify-partyledger1@example.com`) deleted; one unrelated stray test user found during this same cleanup sweep (`zztest_ui_verify_admin@example.com`, left over from an earlier, different session — not referenced in `activity_log`, so unlike the earlier-documented undeletable fake-admin row, this one was safely removable) also deleted. Zero `zztest%` rows remain anywhere. Backend: 236/236 (fake-client suite, unchanged — no backend code touched by any of today's three items). Frontend: `tsc --noEmit` and `eslint .` (whole project) both clean.

## Follow-up, same day: Next.js 16.3.0 upgrade tested empirically (not just researched) — does NOT fix the dev-server 404, reverted cleanly, back on normal `npm run dev` (2026-08-06)

User asked, before accepting the `next dev`-vs-`next start` tradeoff above as permanent: would upgrading to 16.3.0 actually fix the bug, and is it low-risk enough to just do. Rather than answer from web search alone (searched first — `Next.js on X` announcement and the 16.3 blog post describe Turbopack memory eviction, a persistent build cache, and a Rust React Compiler port, none of which describe this specific route-resolution bug; the closest GitHub hit, issue #87680/PR #88775, turned out to be an unrelated `next/dynamic` chunk-manifest hashing bug in 16.1, already fixed before our 16.2.12 pin), the actual upgrade was tried directly, since that's the only way to get a real answer instead of a guess.

**Safe, fully reversible trial, not a blind swap:** backed up `package.json`/`package-lock.json` to `/tmp` first. `npm install next@16.3.0 eslint-config-next@16.3.0` initially failed on a **pre-existing, unrelated** peer-dependency conflict (`@gravity-ui/table@1.20.0` only declares a `react@^17||^18` peer range, but the project runs real React 19.2.4) — confirmed this isn't something the upgrade introduced by checking `npm ls react` against the *current* 16.2.12 install, which already silently carries the same mismatch, meaning the original install must have used `--legacy-peer-deps` too. Re-ran with that same flag — clean install, 0 vulnerabilities, `next@^16.3.0` resolved correctly, peer requirements (`react@^18.2.0||^19.0.0`, `node>=20.9.0`) both satisfied by this project's existing versions.

**Tested the actual bug, not just whether it installed:** fresh `rm -rf .next && npm run dev` on 16.3.0, logged in as a new temporary Admin, and requested `/parties/92478b33-.../ledger` — **the dev server's own log line is unambiguous: `GET /parties/92478b33-.../ledger 404 in 1919ms`.** Same 404, same route, same shape, on the version that was the candidate fix. The parent `/parties/[partyId]` detail page loaded fine (200) immediately after, matching every prior reproduction's pattern exactly. **Conclusion: 16.3.0 does not fix this bug** — whatever changed in that release (Turbopack memory handling, the build cache, React Compiler support), Next.js's dev-server route-tree resolution for a parent segment with its own `page.tsx` sitting next to a nested dynamic child folder is unaffected.

**Reverted immediately and cleanly, since an upgrade that doesn't fix the one problem it was being considered for isn't worth its own migration risk:** restored the backed-up `package.json`/`package-lock.json`, `npm install --legacy-peer-deps` back to the exact locked `next@16.2.12` tree (confirmed via `npm ls next`), `tsc --noEmit` clean post-revert. Restarted the frontend as plain `npm run dev` (Turbopack, port 3000) per the user's own explicit request — **this is the standing state now**, not `next build && next start`. `/parties/[partyId]/ledger` and `/invoices/[invoiceId]/edit` will 404 in this mode, exactly as already documented above and as the user explicitly said they'd accept; every other route is unaffected.

**One incidental finding worth flagging, not acted on:** `npm install`'s audit output differed between the two trees — 16.3.0's fresh install reported 0 vulnerabilities, while reinstalling the pinned 16.2.12 tree reports **3 high-severity vulnerabilities** in its dependency graph. This is a pre-existing condition of the pinned version (not something introduced by today's revert — the same tree was already in place before this session touched anything) and wasn't investigated further, since it's outside the scope of what was asked; worth a `npm audit` review in its own pass if the user wants one.

Backend untouched this whole round (0 backend files changed). Frontend: `tsc --noEmit` clean on the reverted tree. Both servers confirmed healthy after the revert: backend `/docs` → 200, frontend `/login` → 200. Cleanup confirmed: the temporary Admin user created for the 16.3.0 test (`zztest-verify-nextupgrade1@example.com`) deleted, zero `zztest%` rows remain.
- [2026-08-06T17:58:59.360486+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-06T17:58:59.371331+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-06T19:45:27.581536+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-06T19:45:27.594657+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Section 8 charts: Matplotlib/Cloudinary PNGs → live @gravity-ui/charts, all 10 charts given distinct visual styles (2026-08-07)

Every chart in the app (Dashboard's 3, Analytics' 6, Party Ledger's 1) was still a server-rendered Matplotlib PNG uploaded to Cloudinary and shown via a plain `<img>` — explicitly called out as still-pending "Section 8's interactive-charts work" in an earlier session's note. This pass closes that gap for real: live data, real hover tooltips, no image round trip, and — per the user's explicit hard requirement — **no two charts anywhere in the app share a visual style**.

**Backend (`app/services/analytics_service.py`):** turned out to need less than expected — every one of the six query functions already computed and returned real structured `data` (a list of dicts with real numbers/labels) alongside `chart_url`; the JSON the frontend needed already existed, just unused. Stripped out entirely: the `matplotlib` import, `_upload_chart`/`_bar_chart`/`_line_chart`/`_pie_chart` helpers, and every `chart_url` computation — each function now returns only `{"data": [...]}`. `cloudinary_client.upload_chart_image` deleted (grepped first: used nowhere else). `matplotlib==3.9.2` removed from `requirements.txt` and uninstalled from the venv — grepped first, confirmed it was imported nowhere else in `app/`. `AnalyticsResult` (`app/models/analytics.py`) dropped its `chart_url: str` field. Updated the two test files that asserted on `chart_url`/mocked `upload_chart_image` (`tests/integration/test_analytics.py`, `tests/integration_real/test_real_dispatch_settings_analytics.py`) to check real data only. Full fake-client suite: **236/236 passing**, confirmed again after the matplotlib uninstall (nothing else in the codebase touches it).

**Chart type assignment — asked the user before building, not decided unilaterally.** The dataviz skill's own color-formula rules (fixed hue anchors, real CVD separation) make a pure teal/cyan-only categorical palette structurally unable to pass real colorblind-safety checks for multi-slice charts (same-hue-family colors mostly differ in lightness, which isn't identity). PRD.md's anti-drift rule locks the *background gradient* to blue-teal-cyan specifically ("no red, magenta, or violet... anywhere in this gradient or its shadows/glows") — scoped language, not a blanket ban on all color everywhere (status colors like danger-red already exist elsewhere in this app's UI). Asked the user directly rather than assume either reading; they picked the recommended option: **single-series charts keep the existing brand accent** (matches the already-existing `BalanceTrendChart`'s own precedent), **multi-series charts (pie/donut slices, grouped bars) use a validated colorblind-safe categorical palette** — chart data-ink, not the app's chrome. Re-validated the dataviz skill's default 8-hue categorical palette against this app's own real surfaces (`node scripts/validate_palette.js ... --surface "#F5FAFA"` light, `--surface "#0A0E12"` dark) — **all checks pass both modes** (worst adjacent CVD ΔE 9.1 light / 8.4 dark, normal-vision floor 19.6/19.3, both clear of the ≥8/≥15 gates); light mode has a contrast WARN on 3 slots, mitigated by shipping visible direct labels + a legend on every multi-series chart, per the skill's own relief rule. New `lib/theme/chart-palette.ts`: `CHART_ACCENT`/`CHART_ACCENT_SECONDARY` (existing brand tokens) for single-series charts, `CATEGORICAL_PALETTE`/`categoricalColor()` (the validated 8-hue set, fixed order, never cycled) for multi-series ones.

**Final assignment — 7 genuinely distinct styles across the 7 underlying metrics (Dashboard mirrors 3 of Analytics' 6 at a smaller height, per the user's own instruction that this doesn't count as a repeat):**
| Metric | Type | Why |
|---|---|---|
| Party Ledger Balance Trend | **line** (already existed, untouched) | trend over time |
| Monthly Sales & Revenue | **area** | trend over time — distinct from the line above, same "trend" job |
| Top Selling Scale Models | **bar-x** (vertical) | top-N comparison |
| Customer Debt / Ledger Balance | **pie** | proportion of a whole |
| Low Stock Items | **bar-y** (horizontal, 2 grouped series: In Stock vs. Min Threshold) | comparison across items with long code labels — horizontal avoids rotated text, and the second series shows *how far* below threshold each item is, not just that it is |
| Payment Method Breakdown | **donut** (pie, `innerRadius: 60%`) | proportion of a whole — same family as Customer Debt's chart but visually distinct (ring vs. filled wedge), matching the user's own "pie, donut" as two acceptable distinct styles |
| Category-wise Sales | **waterfall** | literally the right shape for "how does each category's total build up to the grand total" — a step per category plus a `total: true` bar, not just a bar comparison |

**Frontend build:** `components/analytics/ChartFrame.tsx` (shared glass-card/loading/empty wrapper, replaces the deleted PNG-based `ChartCard.tsx` — grepped first, confirmed nothing else referenced it before deleting) plus one component per chart type (`MonthlySalesAreaChart`, `TopSellingModelsBarChart`, `CustomerDebtPieChart`, `LowStockBarChart`, `PaymentMethodDonutChart`, `CategorySalesWaterfallChart`), each theme-aware via the existing `useThemeToggle()` hook (same pattern as `BalanceTrendChart`), each accepting a `height` prop so the exact same component renders full-size on `/analytics` and compact on `/dashboard` — literally the same chart, not a re-implementation, satisfying "Dashboard mirrors Analytics" by construction rather than by convention. Currency values use `valueFormat`/`numberFormat` with `prefix: "Rs. "` matching the rest of the app. `AnalyticsResult<T>`'s `chart_url` field dropped from `lib/api/types.ts` to match the backend. Both `app/(app)/analytics/page.tsx` and `app/(app)/dashboard/page.tsx` rewritten to pass live `data`/`loading` straight into these components instead of an image URL.

**Real data seeded, not synthetic-and-discarded — the user's own ask was to "create some real test invoices/purchases first," meant to persist and populate the charts, not a throwaway verification fixture.** Real state before this pass was thin: 6 finalized sales all in one month/one category, **zero** payment rows at all (Payment Method Breakdown would have rendered genuinely empty), only 1 low-stock item. Seeded through the real API, as a temporary Admin (`zztest-chartseed-admin@example.com`, real credit-limit-override finalizes since two of the new sales legitimately exceeded the target parties' credit limits — Section 16.1's own "Admin can override, logged" path, exactly the real workflow, not a bypass): 4 real payments across 4 different methods (Cash/Cheque/Bank Transfer/Online) against the 3 real parties with positive balances; 2 additional real finalized sales in different months (June, July 2026) and a different category (Indicator) than the existing August/Plat-Form-only data, giving Monthly Sales a genuine 3-month trend and Category-wise Sales two real categories to step through; one new low-stock inventory item (`ACC-KP-STD`) so the Low Stock chart has two items to compare instead of one. **This data is meant to stay — not cleaned up** (unlike this project's usual `ZZTEST_` throwaway convention), since it's real chart-populating content the user asked for, not a disposable check. Only the temporary seeding Admin account itself was removed afterward — except it turned out **undeletable**: the credit-limit override actions it took got logged to `activity_log` (Section 16.4, deliberately undeletable by design), so the row is FK-referenced permanently, same class of "permanent fixture" already documented once before in this file for a different fake-admin row. Deactivated (`is_active: false`) instead of left as a live, functional login — it can never authenticate again, matching the existing Deactivate/soft-disable pattern, but the row itself has to remain.

**Verified in a real browser against the real Supabase project, not just a compile check:** logged in as a temporary Admin, screenshotted `/dashboard` and `/analytics`. All 9 of this pass's charts render correctly with real numbers, real hover-tooltip config, real per-series colors, legends on every multi-series chart, zero browser console errors. **One real scare, traced to a known cause, not a new bug:** the very first pass showed Monthly Sales/Top Models/Customer Debt stuck on "No data yet"/spinner on the Dashboard, even though the KPI tiles computed from the *same* underlying fetch showed real non-zero numbers — this project's own already-documented stale-Turbopack-HMR class of issue (the dev server had been running continuously for a day through many file creates/deletes/edits this pass made). Killed every frontend PID individually, verified twice via `ps aux`, `rm -rf .next`, fresh `npm run dev` — the exact same page then rendered all three charts correctly on the first real attempt, zero code changes needed. The 10th chart (Party Ledger's Balance Trend, a pre-existing `@gravity-ui/charts` line chart this session never touched) could not be re-screenshotted this pass — `/parties/[partyId]/ledger` hits the separately-documented, user-accepted `next dev`-only 404 for that specific route shape (see the 2026-08-06 entries on this same bug) — unrelated to charts, and already proven working repeatedly via a production build in prior sessions; a fresh screenshot is one `next build && next start` cycle away if wanted, not done here since the user asked to stay in `npm run dev` for ongoing frontend work.

**Tests:** backend `tests/unit`/`tests/integration` — 236/236, unchanged after the matplotlib removal. Frontend `tsc --noEmit` and `eslint .` (whole project, after every chart component was added) — both clean, zero warnings.

Cleanup confirmed: the temporary browser-verification Admin (`zztest-verify-charts1@example.com`) deleted; the seeding Admin (`zztest-chartseed-admin@example.com`) deactivated, not deleted, for the FK reason above — this is a known, accepted, permanent fixture, not an oversight.
- [2026-08-06T20:38:36.162453+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-06T20:38:36.173194+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).

## Inbox message-detail panel (Section 9.1): already fully built — reported "Select a message to read it." placeholder traced to the same stale-dev-server pattern this file has now documented several times (2026-08-07)

User reported that clicking a message in the Inbox's right-hand panel still showed the "Select a message to read it." placeholder instead of the message content, and asked for the four Section 9.1 actions (mark read/unread, manual reply, Generate AI Reply, Admin-only delete) to be checked and built out. Explicitly told not to touch `pdf_service.py` or Invoice Builder PDF code — confirmed via file mtime after this session that it was never touched (last modified 2026-08-06, before this session started).

**Audit first, before writing any code:** read `components/inbox/MessageDetail.tsx`, `components/inbox/InboxMessageList.tsx`, `app/(app)/inbox/page.tsx`, `app/routers/inbox.py`, `app/services/inbox_service.py`, and `app/services/ai_reply_service.py` in full. **All four requested features were already completely built:** `MessageDetail.tsx` has a Mark Read/Unread button, an Admin-only Delete button behind a confirmation dialog, a reply textarea with an "Attach Invoice #" field and Send button wired to the real `POST /inbox/{id}/reply` (which calls `gmail_client.send_message` — real Gmail API, not SMTP, matching Section 9.1's read/reply distinction from the send-only path), and a "Generate AI Reply" button wired to `POST /inbox/{id}/generate-reply` (`ai_reply_service.generate_reply_draft`, a real `gpt-4o-mini` call, never auto-sent — drafts into the same textarea the person edits before pressing Send). `inbox/page.tsx`'s `handleSelect`/`selected` wiring was also already correct — clicking a row sets `selectedId`, `MessageDetail` renders whenever a message is selected. Nothing to build.

**Reproduced the user's exact report first, before assuming it was environmental** — and it did reproduce, on the then-currently-running dev server (up since a restart the previous day, through a full session's worth of chart-related file edits). Did the same fix this file has now applied at least four times before: killed every frontend PID individually, verified twice via `ps aux`, `rm -rf .next`, fresh `npm run dev`. **After the clean restart, the exact same click-through worked correctly on the first real attempt** — same root cause as every prior occurrence of this pattern in this repo (WSL's unreliable file-change notification over the `/mnt/d`-mounted drive leaving Turbopack's dev server serving stale compiled state), not a code defect. Zero lines of application code were changed for this item.

**All four actions then verified for real, not just "the panel opens":**
1. **Detail panel renders on click** — real message (`techexav@gmail.com`, a genuine unmatched-until-Issue-2's-sync-fix customer inquiry) opened with full snippet, sender, date, and (where applicable) the "Linked to Invoice #N" chip.
2. **Mark Read/Unread** — toggled twice (unread→read→unread→read, ending back at its original state), confirmed via direct Postgres read after each step, not just the button label (the button label lagged the true state by a couple seconds in one run — this dev environment's request round-trips have been consistently slow all session, e.g. 30s first-compiles logged elsewhere in this file — not a logic bug; the final DB state matched every time it was actually checked).
3. **Generate AI Reply** — clicked for real, `POST /inbox/{id}/generate-reply` returned a genuine, contextual `gpt-4o-mini` draft referencing the actual customer inquiry ("Wa-Alaikum-Assalam... confirm the availability of the following items... Platform Scale Trolley Guard / Stand — Qty: 2..."), populated into the reply textarea. Confirmed via captured network response, not just a screenshot.
4. **Manual reply send** — typed a clearly-marked `[ZZTEST VERIFICATION]` reply and pressed Send; `POST /inbox/{id}/reply` returned `{"status":"sent"}`, "✓ Reply sent" toast shown, textarea cleared. This is a real Gmail API send from the business's own account (`kamransteelw@gmail.com`) to `techexav@gmail.com` — the real Admin's own address, same self-directed/disclosed precedent already established elsewhere in this file (Human Gate notifications, the Section 9.2 live-send verification) — worth checking that inbox for the confirmation, not a third party.
5. **Admin-only Delete** — sent one throwaway self-addressed test email first (`Re: Invoice #6 — ZZTEST throwaway for delete verification`, synced in via the same real Gmail-poll path Issue 2 fixed) specifically so Delete could be exercised without touching the user's one real inbox message. Confirmation dialog appeared correctly ("removes it from the Inbox view and moves it to Gmail Trash — not permanently destroyed"), confirmed, "Message deleted" toast shown. Verified directly against Postgres afterward: the throwaway row is `is_deleted: true`, the real `techexav@gmail.com` row is untouched (`is_deleted: false`) — precise, not a mass-delete.

Cleanup confirmed: the throwaway delete-test message is gone from the live Inbox (soft-deleted + real Gmail Trash); the temporary browser-verification Admin (`zztest-verify-inbox1@example.com`) deleted. The real customer message was left exactly as the user found it, still present, still real.

**No backend or frontend code was changed this session** — `pdf_service.py` and Invoice Builder PDF code untouched as explicitly instructed; every other file in both repos is byte-identical to before this pass. `tsc --noEmit` and `eslint .` (whole frontend) both clean. Backend `tests/unit`/`tests/integration`: 236/236 passing.

## Section 4.6 route-change loader: restyled to three orbiting hollow rings, replacing the thin top progress bar (2026-08-07)

User specified an exact new look for the route-transition loader: three small hollow ring circles (not solid dots) in a triangular/orbit arrangement, rotating together as one unit — `#22D3EE` (accent), `#146C8C` (secondary accent), `#7DE8F5` (light accent), each with its own subtle ~6px glow, ~36px overall, ~1.1s per full turn.

**PRD.md updated first, in both copies, per this project's own rule** ("any change to theme, screens, schema, or rules must be made here first") — Section 4.6's "Route/page transition loader" bullet rewritten to describe the new ring/orbit design in place of the old "thin progress bar (2–3px)" spec, in both `omega-backend/PRD.md` and `omega-frontend/PRD.md`. **While there, also fixed a real drift found by accident:** the two repos' PRD.md copies are meant to be the same "single source of truth" document, but `omega-frontend/PRD.md` was missing the Section 9.2 "Party info box"/"Draft badge" amendment from an earlier session (2026-08-06) — that session only edited the backend copy. Propagated the same amendment text into the frontend copy so both files agree again; not otherwise part of today's ask, but a one-line-of-effort fix for a real inconsistency in the project's own documentation discipline, worth doing while already touching this exact cross-repo sync question.

**Checked Gravity UI's own components first, as asked, before building anything custom:** read the actual source of both `Spin` (`@gravity-ui/uikit/.../Spin`) and `Loader`. Neither fits, structurally, not just stylistically — `Spin` renders one semicircle arc (`width:50%` with `border-inline-start:none`) in a single color via one `--g-spin-color` CSS var, not a full hollow ring, and has no slot for multiple independently-colored children; `Loader` is three solid bars pulsing in opacity (an equalizer look), no rotation at all. Neither's public API (`size`, `style`, `className`, CSS custom properties) exposes enough to become "three independently-colored hollow rings orbiting as one rigid unit" — that would mean fighting each component's fixed internal DOM rather than genuinely reusing it. Built a lightweight custom implementation instead, per the user's own fallback instruction.

**Implementation:** `app/loading.tsx` (the existing Next.js App Router root loading boundary — same file, same mechanism as before, only the visual replaced) now renders three plain divs inside a `.route-orbit-loader` container. New CSS in `globals.css` replaces the old `route-progress`/`.route-progress-bar` rules: the container carries the continuous `rotate(0→360deg)` animation (`1.1s linear infinite`, `prefers-reduced-motion` respected — same courtesy the old bar never had, added here since a full custom implementation was already being written); each ring is a small (`10px`, `2px` border, `border-radius: 50%`) absolutely-centered div, individually rotated to 0°/120°/240° and translated outward — a static equilateral-triangle placement — so that when the *parent's* rotation animates, all three rings orbit together as a single rigid unit rather than three independent spinners. Colors and glow set per-ring exactly as specified (`border-color` + `box-shadow: 0 0 6px rgba(..., 0.5)`, one `rgba` triple per hex).

**Verified live, not just visually inspected in isolation:** logged in as a temporary Admin, navigated through five not-yet-visited routes on a freshly restarted dev server (Inventory, Invoices, Parties, Analytics, Expenses) — Next.js App Router's `loading.tsx` boundary only actually renders when the target route segment itself isn't ready yet (its JS chunk still compiling, in this Turbopack dev environment — the same first-visit compile lag this file has logged taking 20–30s+ elsewhere), so it doesn't fire on every single click the way a client-side NProgress-style bar would; this matches the PRD's own unchanged architecture note ("still a Next.js App Router `loading.tsx` per route, not a full-page spinner") — restyling was in scope, not re-engineering when it fires. Caught it firing for real on 2 of the 5 navigations (Analytics, Expenses — the other three simply resolved faster than the test script's capture window, not a functional gap). Screenshots of both real captures confirm, unambiguously: three genuinely hollow rings (transparent centers, not filled dots), a triangular/orbit arrangement, each a visibly distinct color with its own soft glow, mid-rotation at two different angles between the two captures (proof it's actually animating, not a static frame).

**One console warning noticed during this pass, pre-existing and unrelated — not fixed, flagged for awareness:** a React hydration-mismatch warning on `TextInput`'s underlying `<input>` (`style={{caret-color:"transparent"}}` server vs. `style={{}}` client) appeared on several pages during this verification. Confirmed unrelated to this change — this session touched only `app/loading.tsx` and the loader's own CSS block, nothing near `TextInput`/`Sidebar`/`Topbar`. Out of scope for today's ask; worth a look in a future pass if it starts showing up elsewhere.

Cleanup confirmed: temporary Admin (`zztest-verify-loader1@example.com`) deleted. `tsc --noEmit` and `eslint .` (whole frontend) both clean. No backend files touched — nothing to re-run there.

## PRD sync + chart refresh (2026-11-16): no backend code changes

**Audit result:** no static PNG charts remain. All 10 charts were already live
`@gravity-ui/charts` fed by the six JSON endpoints in `app/routers/analytics.py`
(the Matplotlib pipeline was removed on 2026-08-07, see that entry above). The
user chose a frontend style refresh only, with **no new endpoints and no new
backend tests**.

**PRD.md (this repo):** replaced with a byte-identical copy of
`omega-frontend/PRD.md`. That brings this copy up to the Midnight Indigo palette
(Section 4.1/4.2, 4.4, 4.6) and the new Section 8: as-built endpoints and
response shapes (`AnalyticsResult = { data: [...] }`, one row type per
endpoint), where each chart appears, chart types, and chart styling rules. Before
copying, `git diff` confirmed this copy had no local edits, so nothing was lost.
`pdf_service.py` and the PDF design (Section 9.2, `#0F6B7C`) are unchanged.

**Analytics roles, checked, not changed (user confirmed):** PRD Section 3.2
lists `/analytics` and `/dashboard` as **Admin, Staff**. All six
`/analytics/*` endpoints use `get_current_user`, which returns 401 with no
session, an invalid/expired token, a deleted user or a deactivated account, and
no role check. That matches the PRD. `require_admin` would break Staff's
Dashboard charts.

**Tests:** `pytest tests/unit tests/integration`: **236 passed**, no code
changes. (`tests/integration_real/` not run: it needs live external services.)

**Note:** running that suite appends "Daily digest" lines to the end of this
file (two were added at 2026-11-16T08:07 UTC). That's existing behaviour, left
as-is.
- [2026-08-11T13:30:13.053441+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-08-11T13:30:13.063473+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
- [2026-08-11T13:31:21.839385+00:00] Daily digest: 3 low-stock item(s), 3 overdue invoice(s), sent to 1/1 admin(s).
- [2026-11-16T08:07:49.317426+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 0/1 admin(s).
- [2026-11-16T08:07:49.324063+00:00] Daily digest: 0 low-stock item(s), 0 overdue invoice(s), sent to 1/1 admin(s).
