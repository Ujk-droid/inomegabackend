# Omega Scales — FTE Worker & Inventory Ledger System
### Product Requirements Document (PRD) — FINAL v3.0
**Business:** Omega Scale — TR1/20/2, Marston Road, Near Gul Plaza, 74400, Karachi
**Domain:** Industrial & Digital Weighing Systems — Sales, Inventory, Customer Ledgers, Invoicing
**Framework:** Spec-Driven Agentic Engineering — built for Claude Code CLI (headless + loop + harness)
**Design Deliverable:** Dual-theme (Dark / Light) Figma template generated from this spec

---

## 1. Executive Summary

Omega Scale currently manages up to 1,500 weighing-scale products, customer ledgers, and invoices manually (see reference documents: `Ledger_Ijtibah_63.pdf`, `INV-2127_United_Ijtibah.pdf`). This system digitizes that entire workflow into a web application with:

- Full inventory management (bulk Excel import, CRUD, image catalog)
- Customer ledger with running-balance accounting (matches the exact format already in use)
- Invoice generation (pixel-matched to the existing INV-2127 paper format) with direct PDF + Gmail dispatch
- Sales/debt analytics dashboard
- An **agentic backend loop** with a human-approval gate for high-value transactions

This PRD is the single source of truth for two downstream tools:
1. **Claude Code CLI** — builds the application from this spec.
2. **Figma AI generation tool** — builds the UI screens from Section 4 (Design System) and Section 6 (Screens).

---

## 1.5 System Architecture Design (SAD)

Architecture decisions are scattered across this document by topic (schema in Section 5, deployment in Section 14, tech stack in Section 11). This section pulls them into one coherent picture — a standard SAD covers layers, components, data flow, and security boundaries, and this is that summary, with pointers to where each piece is specified in full.

### 1.5.1 Architecture Style

**Three-tier, client-server, with a managed-cloud-services layer underneath** — not a monolith, not microservices. A single frontend application talks to a single backend API, which is the only thing that talks to the database and external services. Nothing in the frontend ever calls Supabase, Cloudinary, Gmail, or OpenAI directly — every external integration is mediated by the backend, so there is exactly one place that enforces business rules (RBAC, Human Gate, retention rules) no matter which screen triggered the request.

```
┌─────────────────────────────────────────────────────────────┐
│  PRESENTATION LAYER — omega-frontend/ (Next.js, Section 4)   │
│  Gravity UI components · "Midnight Indigo" dark/light theme  │
│  Talks ONLY to the backend API — never to Supabase/Cloudinary │
│  /Gmail/OpenAI directly                                       │
└───────────────────────────┬────────────────────────────────┘
                              │  HTTPS, JWT in HTTP-only cookie
                              │  (Section 17.1: custom JWT, not
                              │   Supabase Auth as first planned)
┌───────────────────────────▼────────────────────────────────┐
│  APPLICATION / API LAYER — omega-backend/ (FastAPI)          │
│  RBAC on every endpoint (Section 3) · Human Gate (Section 7.4)│
│  Harness deny/ask rules (Section 7.2) · Business logic,       │
│  math/balance validation (Section 7.3), the "loop" (7.1)      │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────┘
       │           │           │          │          │
       ▼           ▼           ▼          ▼          ▼
  ┌─────────┐ ┌──────────┐ ┌───────┐ ┌────────┐ ┌──────────┐
  │Supabase │ │Cloudinary│ │ Gmail │ │ OpenAI │ │  (none)  │
  │Postgres │ │ images,  │ │ send +│ │ Vision │ │ WhatsApp │
  │+ Auth   │ │ PDFs,    │ │ read  │ │(reply, │ │ = wa.me  │
  │(Sec. 5) │ │ charts   │ │(9.1)  │ │scan-   │ │ link,    │
  │         │ │          │ │       │ │slip)   │ │ no API   │
  └─────────┘ └──────────┘ └───────┘ └────────┘ └──────────┘
        DATA & EXTERNAL SERVICES LAYER — all managed cloud
```

### 1.5.2 Layer Responsibilities

| Layer | Owns | Never Does |
|---|---|---|
| **Presentation** (`omega-frontend/`) | Rendering, client-side form state, calling the backend API, showing loading/error states (Section 4.6) | Business rules, direct database access, holding secrets (Cloudinary/Gmail/OpenAI keys never ship to the browser) |
| **Application/API** (`omega-backend/`) | Auth, RBAC, Human Gate, the harness (Section 7), all math/balance validation, orchestrating every external service call | Rendering UI, storing UI-only state |
| **Data & External Services** | Durable storage (Postgres), file storage (Cloudinary), email transport (Gmail), AI inference (OpenAI) | Enforcing this app's business rules — Supabase RLS is a defense-in-depth option (Section 3), not the primary enforcement point; that's the API layer |

### 1.5.3 Security Architecture (summary — full detail in Section 3)

- **Perimeter:** no public signup route exists anywhere (Section 3) — the only way in is Admin-created accounts.
- **Session:** JWT in an HTTP-only, secure cookie (Section 17.1) — never in `localStorage`, never readable by client-side JS.
- **Authorization:** RBAC checked on every backend endpoint, not just hidden in the frontend (a Staff user hitting an Admin-only URL directly gets rejected server-side, not just redirected client-side).
- **Two escalation gates**, both backend-enforced, neither bypassable from the frontend: the Human Gate (Section 7.4, money) and the Login Approval Gate (Section 3.1, access).
- **Constrain/Verify/Correct/Escalate** — the harness's four verbs (Section 7.2–7.4) are the architectural pattern underlying all of the above, not just an invoice-specific rule.

### 1.5.4 Data Flow — One Representative Example (Invoice Finalization)

```
Frontend (Invoice Builder)
   → POST /invoices/{id}/finalize  (API layer)
      → validates line-item math (Section 7.3)
      → checks credit limit (Section 16.1)
      → assigns sequential invoice_no (Section 5.3)
      → IF total > threshold: sets approval_status='pending',
        notifies Admin (Section 16.4 logs this to Activity Log)
      → writes to Supabase (customer_ledgers + invoice_line_items)
   ← returns updated invoice to frontend
```
Every other write in this system (Purchase, Expense, Payment, Correction) follows the same shape: frontend submits → API validates and orchestrates → data layer persists → API returns the result. The frontend is never trusted to have validated anything itself.

### 1.5.5 Deployment Topology (full detail in Section 14)

Two independently deployable units, matching the two-repo structure (Section 13.0): `omega-frontend/` → Vercel (or Hostinger, Section 14.1), `omega-backend/` → Render (Section 14.2). Both are stateless application layers; all durable state lives in the managed services (Supabase, Cloudinary), so either deployable can restart or scale without data loss.

---

## 2. Reference Data (Ground Truth, extracted from real documents)

These are not hypothetical examples — they are the actual formats the business already uses. All schema and UI must reproduce them exactly.

### 2.1 Sample Item (Product Catalog)
| Field | Value |
|---|---|
| Item Code | `P-16-S-A-MK` |
| Item Name | Platform 400mm x 400mm SS Top Capacity 150Kg 10g Model (MK-03-Omega) |
| Unit | pcs |
| Rate | 12,300 |

**Product line reference (from catalog images):** platform bench scales (D-60, R-10 series), heavy-duty floor/pit scales, waterproof compact scales, low-profile drum/pallet scales, roller conveyor scales — all share the pattern: **stainless steel or diamond-plate deck + digital LED/LCD indicator head**, used as the visual basis for inventory placeholder icons/thumbnails when no photo is uploaded.

### 2.2 Sample Customer Ledger (running balance)
Customer: **United Scale Ijtibah** — Period 01-Apr-26 to 28-Jul-26

| S.No | Date | Description | Debit | Credit | Net (running balance) |
|---|---|---|---|---|---|
| 280 | 14-Apr-26 | Sale - 2044 | 24,900 | 0 | 136,276 |
| 281 | 15-Apr-26 | Receiving - 1167 (Cheque) | 0 | 120,000 | 16,276 |
| ... | ... | ... | ... | ... | ... |
| 307 | 28-Jul-26 | Sale - 2132 | 23,000 | 0 | 472,738 |
| **END** | | | **1,409,362** | **1,048,000** | |

**Ledger rule (must be enforced in code, not just UI):**
```
current_balance = previous_balance + debit − credit
```
Every ledger row is a transaction (Sale = Debit, Receiving/Payment = Credit). The system must never allow a row to be inserted without recalculating and persisting the running Net for every subsequent row (a ledger is append-consistent, not just append-only).

### 2.3 Sample Invoice (exact layout to replicate — INV-2127)
```
OMEGA SCALES  —  TR1/20/2, Marston Road, Near Gul Plaza, 74400, Karachi
Mobile: 0321-2175034, 03100884427   |   Ptcl: 0213-32751125

To M/S: United Scale Ijtibah              INVOICE # : 2127
       0333-2218892                       DATE      : 23-Jul-26
       Nagan Chowrangi

Sno | Item Code   | Item Name                                  | Unit | Rate  | Qty | Total
1   | P-16-S-A-MK | Platform 400x400 SS Top Cap.150Kg 10g (MK-03) | pcs | 12300 | 15  | 184500

                                Total (Rs.)        184500
Previous Balance:  82238        Special Discount    0
This Bill Balance: 184500       Total (Rs.)         184500
Current Balance:   266738       Received (Rs.)      0
                                 Total Payable (Rs.) 184500

Note: Pay Dues within 15 Days
THANK YOU FOR YOUR BUSINESS!

_________________________       _________________________
   Receiver's Signature                Signature
```

**This invoice (Rs. 184,500) exceeds the Human Gate threshold (Rs. 100,000) — it is a live test case for the approval workflow (Section 7).**

---

## 3. Authentication & Access Control — Closed, Invite-Only System

**This is not a public-facing app.** It's an internal tool for roughly 8–10 people total (the owner and a small staff) — not a product with open signup. This changes a few defaults from what a typical public SaaS would do:

- **There is no public registration route, anywhere in the app or the API** — not a hidden `/signup` page, not an API endpoint that creates a user without an existing Admin session. The *only* way a new account is ever created is: Admin logs in → User Management (Screen 12) → "+ Add User" → system emails that person a temporary password. If someone who isn't Admin tries to hit a signup-style endpoint directly, it returns a 403, not a form.
- **Accounts are few and known** — the `users` table is expected to hold single-digit-to-low-double-digit rows for the life of this system, not thousands. This is worth stating because it changes engineering trade-offs elsewhere too: no need for email verification flows, no need for social login, no need for rate-limiting infrastructure sized for public traffic — a simple login-attempt lockout (e.g. 5 failed attempts locks the account for 15 minutes, Admin can unlock from User Management) is enough.
- **Admin is the only gate for who gets in.** Only Admin can create, deactivate, or change the role of a user (this section's RBAC table). Staff cannot invite other Staff.

### 3.1 Login Approval Gate (new — same pattern as the Human Gate, applied to login itself)

There are (at least) two Admin accounts on this system — Bhai and the user setting this up — and both can approve. Beyond that, a real-world security layer requested: **a Staff login is not just "correct password = in."** It must also be approved, live, by an Admin.

- **Admin accounts log in directly** — no approval needed. This has to be true, otherwise nobody could ever approve anything (an Admin cannot wait on their own approval).
- **A Staff login goes through a gate:** they submit correct email + password on the Login screen, but instead of landing in the app, they see a **"Waiting for admin approval..."** screen (with a spinner, polling every few seconds). Nothing about the app is accessible yet.
- **Every Admin currently active gets notified immediately** — a badge/toast in their own session if they're online, plus (matching the pattern from Section 7.1's daily digest) an email alert if not, so this doesn't get missed because nobody happened to be looking at the screen.
- **Either Admin can Approve or Reject** — whichever one acts first resolves it; the other sees it move out of their pending queue too, so two Admins never approve/reject the same request twice.
- **On Approve:** the waiting Staff session activates immediately (their polling screen detects it and proceeds into the app) — no need for them to log in again.
- **On Reject:** their attempt fails with a clear message ("Your login was declined by an administrator"), and it's logged.
- **Full CRUD on the request log itself** (a new **Login Approvals screen**, Admin-only): every past request — who, when, which device/IP if available, approved/rejected/timed-out, and by whom — is listed, searchable, and an Admin can delete old entries (still soft-delete, matching Section 5.2's retention rule) or add a note to one.
- **Timeout:** a pending request left unanswered for 10 minutes auto-expires to "Rejected — no response," so a Staff member isn't left staring at a spinner forever if no Admin is around; they can simply try again later.

```sql
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
```

**This applies only to Staff, not Admin-to-Admin.** If the business later wants every login (including Admin's) gated, that would need a third "super-admin" role who is always exempt — noted here as a possible future extension, not built now since it wasn't asked for.

| Role | Permissions |
|---|---|
| **Admin (Owner)** | Full CRUD on inventory, Excel bulk upload, ledger edits (via Correction Entry, Section 5.1), financial reports/export, **Human Gate approvals** (invoices > Rs. 100,000 before Gmail dispatch), record payments, manage Customers, **manage Users** (create/deactivate Staff and Admin accounts, Screen 12 — the only way into this system), edit Human Gate threshold (Settings), delete inbox messages |
| **Staff / Manager** | Read-only stock view, generate invoices (draft), record payments (Section 5.0), add/view Customers, download PDFs and use Export, read/reply to Inbox messages. **Cannot**: edit rates, approve invoices, delete anything, invite/deactivate other users, or access User Management |

- Framework: **Supabase Auth was the plan; the actual build uses a custom JWT + HTTP-only cookie issued by the FastAPI backend itself** (Section 16.1 documents this deviation and why) — functionally equivalent for this system's needs, but worth knowing before assuming Supabase's own Auth dashboard shows session activity.

### 3.2 Route Map (new — every screen's URL, since the new screens from Section 5.4 never had one)

*(The "What's Inside" column is a one-line reminder only — the full spec for each screen's content, fields, and behavior lives in Section 6, referenced by number here. Build against Section 6, not against this one-liner.)*

| Screen | Route | Who can access | Screen # (Section 6) | What's Inside |
|---|---|---|---|---|
| Login | `/login` | Public (pre-auth) | 1 | Email/password form, error state, redirect by role |
| Waiting for Approval | `/login/waiting` | The Staff member mid-login | 1 (sub-state) | Polling spinner, "waiting for admin" message |
| Dashboard | `/dashboard` | Admin, Staff | 2 | 4 KPI cards, 3-chart summary, Inbox preview panel |
| Inventory List | `/inventory` | Admin, Staff | 3 | Category 1/2 tabs, product table, Bulk Upload modal, low-stock alert logic |
| Item Detail/Edit | `/inventory/[itemCode]` | Admin (edit), Staff (view) | 4 | Image upload, category, rate/stock fields |
| Party Ledger | `/parties/[partyId]/ledger` | Admin, Staff | 5 | Balance-trend chart, running-balance table, Record Payment modal |
| Party Detail | `/parties/[partyId]` | Admin, Staff | Section 5.4.I | Profile card, stat tiles (Balance/Credit Limit/Lifetime Business), link to Ledger |
| Parties (list) | `/parties` | Admin, Staff | 11 | Party table with type badge, + Add Party |
| Invoices (list) | `/invoices` | Admin, Staff | 6 | Stats strip (Total/Paid/Unpaid/Overdue), invoice table, filter tabs, Edit button |
| Invoice Builder (new) | `/invoices/new` | Admin, Staff | 7 | Customer picker, Scan Slip, item picker, Low Price, Received field, live PDF preview |
| Invoice Builder (edit draft) | `/invoices/[invoiceId]/edit` | Admin, Staff | 7 (draft path of Section 5.1's Edit button) | Same as above, pre-filled |
| Invoice detail / Fix This Invoice | `/invoices/[invoiceId]` | Admin, Staff | Section 5.1 | PDF preview; "Fix This Invoice" correction form if finalized |
| Purchase Builder | `/purchases/new` | Admin, Staff | 15 | Supplier picker, item picker w/ Remaining stock, Received field |
| Purchases (list) | `/purchases` | Admin, Staff | 15 (list view) | Purchase table, same pattern as Invoices list |
| Expenses | `/expenses` | Admin, Staff | 16 | Add-expense form, filterable expense table |
| Reports | `/reports` | Admin, Staff | 17 | Date Wise / Customer Wise / Serial No / Duplicate lookups |
| Bank Accounts | `/settings/bank-accounts` | **Admin only** | 18 | Bank name table, Active/Inactive toggle, + Add Bank |
| Human Gate Drawer | `/approvals/invoices` | **Admin only** | 8 | Pending invoice queue, Approve/Reject |
| Analytics | `/analytics` | Admin, Staff | 9 | All 6 charts, date-range filters |
| Settings | `/settings` | Admin, Staff (reduced view for Staff — no Human Gate threshold field, Section 3's RBAC) | 10 | Profile, theme toggle, notifications, Gmail connection, Danger Zone |
| User Management | `/settings/users` | **Admin only** | 12 | Staff/Admin account table, + Add User, Deactivate |
| Inbox | `/inbox` | Admin, Staff | 13 | Split-view email list + thread + AI-reply composer |
| Login Approvals | `/settings/login-approvals` | **Admin only** | 14 | Pending requests, stats strip, searchable history |

Next.js Middleware guards every `Admin only` route above → redirects Staff to `/dashboard` if they try to access it directly by URL; guards every other authenticated route → redirects to `/login` if unauthenticated. This table is the authoritative list — if a screen is missing a route here, add it here first, then build it, rather than inventing a path mid-build.

---

## 4. Design System — Dual Theme (Dark + Light)

The original spec was Dark Sea Blue Glassmorphic only. **This version requires both a Dark and a Light theme**, switchable via a toggle, sharing the same component structure and only swapping tokens. Build as CSS variables / Tailwind theme tokens so Figma variables map 1:1 to code tokens.

### 4.1 Dark Theme: "Midnight Indigo" (locked 2026-11-16, replaces the earlier "Black Peacock Glass" teal palette)
| Token | Value | Usage |
|---|---|---|
| `--bg-base` | `#0B1020` | App background, deep midnight navy |
| `--surface` | `#131A2E` | Cards, panels, sidebar, top bar, modals |
| `--border` | `#222B45` | 1px card/table/input borders (dark mode uses borders, not shadows, for separation) |
| `--accent-primary` | `#6366F1` | Primary fills: action buttons, active nav indicator, focus ring, selection |
| `--accent-primary-fg` | `#818CF8` | Primary used *as text* (links, active nav label). `#6366F1` on `#131A2E` is only 3.87:1, below WCAG AA, so text uses this lighter tint (5.79:1) |
| `--accent-secondary` | `#22D3EE` | Secondary accent, "info" status, second chart series |
| `--success` | `#34D399` | Paid / In Stock / Active / positive deltas |
| `--warning` | `#FBBF24` | Unpaid / Pending / caution |
| `--danger` | `#F87171` | Overdue / Low Stock / errors / destructive actions |
| `--text-primary` | `#E8EBF5` | Body text (14.5:1 on surface) |
| `--text-muted` | `#9AA3BF` | Labels, meta text (6.9:1 on surface) |

### 4.2 Light Theme: "Midnight Indigo Light" (locked 2026-11-16, same token names as 4.1)
| Token | Value | Usage |
|---|---|---|
| `--bg-base` | `#F6F7FB` | App background |
| `--surface` | `#FFFFFF` | Cards, panels, sidebar, top bar, modals |
| `--border` | `#E4E7F0` | 1px borders (light mode adds soft layered shadows on cards) |
| `--accent-primary` | `#4F46E5` | Primary fills and primary text (6.29:1 on white, so it serves as its own `-fg`) |
| `--accent-secondary` | `#0891B2` | Secondary accent fills, chart series. As text use `#0E7490` (`--accent-secondary-fg`), since `#0891B2` is 3.68:1 on white |
| `--success` | `#059669` | Status fills/icons. As text use `#047857` (`--success-fg`); `#059669` is 3.77:1 |
| `--warning` | `#D97706` | Status fills/icons. As text use `#B45309` (`--warning-fg`); `#D97706` is 3.19:1 |
| `--danger` | `#DC2626` | Errors, destructive (4.83:1 on white, usable as text) |
| `--text-primary` | `#0F172A` | Body text |
| `--text-muted` | `#5B6478` | Labels, meta text (5.9:1 on white) |

**Chart series (both themes, fixed order, slot N is always the same hue):** `#6366F1`, `#22D3EE`, `#34D399`, `#FBBF24`, `#F472B6`, `#A78BFA`. Single-series charts use the theme's `--accent-primary`.

**Contrast rule:** each semantic colour has a *fill* value (the palette value above, used for buttons, badges, dots, chart marks and borders) and an *`-fg`* value (used when that colour is the text itself), which must reach WCAG AA (4.5:1) on `--surface`. Where the palette value already passes, `-fg` equals it.

*(Decision, revised 2026-11-16: the earlier teal "Black Peacock Glass" palette and its "no violet" anti-drift rule are retired. Indigo primary plus a cyan secondary gives clearer separation between primary actions and info/secondary states, and the solid-surface style (instead of gradient glass) improves text contrast and table readability. Green, amber and red stay reserved for status.)*

**Shape language (both themes):** solid surfaces (no gradient glass), **12px card radius**, 8px radius on inputs/buttons, 8pt spacing scale (4/8/12/16/24/32px). Dark mode separates layers with subtle 1px `--border` lines. Light mode uses the same borders plus soft layered shadows. Focus is a 2px `--accent-primary` ring. Transitions are 150–200ms ease and are turned off under `prefers-reduced-motion: reduce`.

**Out of scope for this palette:** the generated Invoice/Purchase PDF (Section 9.2, `pdf_service.py`) keeps its own `#0F6B7C` accent and header wash. It is a printed document, not app UI.

### 4.3 Component Library — Gravity UI (mapped to specific screens, not a vague list)

Gravity UI ships as several focused packages, not one giant bundle. Using the right one per job matters for both look and function:

**Core (`@gravity-ui/uikit`, the 70+ component foundation):**
- `<ThemeProvider theme="dark"|"light">` — root toggle; note the actual prop values are `light | dark | light-hc | dark-hc` (the `-hc` variants are high-contrast — worth keeping in mind for accessibility, even if not used by default)
- `<Card>` — every glass panel: KPI cards, chart containers, the Human Gate queue cards
- `<Button view="action"|"outlined-danger"|"outlined-success">` — every action across the app (uploads, approvals, sends)
- `<TextInput>` / `<PasswordInput>` — Login, all forms; PasswordInput ships the show/hide eye icon natively, no need to build it
- `<Select>` / `<Combobox>` — customer picker and item picker in Invoice Builder, category filter, role dropdown in User Management
- `<Switch>` — theme toggle, notification preference toggles (Settings)
- `<Checkbox>` — "Remember me" (Login)
- `<Alert>` — the inline error states throughout (wrong password, duplicate item code, reviewer/validation errors) — themeable by severity (`info`/`warning`/`danger`/`success`), so the same component covers "Incorrect email or password" and "3 errors will be skipped"
- `<Toaster>` / `useToaster` — every success confirmation specified earlier (manual item added, payment recorded, invoice sent) — one consistent toast system instead of ad hoc messages
- `<Badge>` — every status pill: invoice status (Unpaid/Partial/Paid/Overdue), user role (Admin/Staff), Active/Deactivated, In Stock/Low Stock
- `<Progress>` — the Bulk Upload modal's Step 4 progress bar
- `<Skeleton>` — the loading-state cards/tables required by Section 4.6
- `<Avatar>` — user avatar in the top bar and User Management table
- `<Tabs>` — the category filter tabs (Inventory) and status filter tabs (Invoices screen)
- `<Breadcrumbs>` — Customer → their Ledger, Invoice → its detail
- `<Pagination>` — every server-side-paginated table (Inventory up to 1,500 rows, Invoices, Customers)
- `<Tooltip>` — icon-only buttons (mark read/unread, delete) need a labeled tooltip so they're not guesswork
- `<Drawer>` — Human Gate approval queue (already specified), and doubles as the mobile off-canvas nav on small screens (Section 4.5)
- `<Modal>` / `<Dialog>` — Bulk Upload flow, Add Item, Add Customer, Add User, Record Payment

**Data table (`@gravity-ui/table`, not uikit's basic `<Table>`):** the Inventory list (up to 1,500 rows), Invoices list, Party Ledger, and Login Approvals history all need real data-grid behavior — sorting, column resizing, and reasonable performance at scale — which is what this separate headless package is for. uikit's own `<Table>` component is fine for short, simple lists (e.g. the Human Gate queue) but not for anything approaching 1,500 rows.

**Charts (`@gravity-ui/charts`):** all six Analytics charts (Section 8) — note this replaced the older `@gravity-ui/chartkit` wrapper referenced in earlier drafts of this PRD; use the current package.

**Navigation shell (`@gravity-ui/navigation`):** the left sidebar itself (logo, nav items, collapse behavior) — purpose-built for exactly this layout rather than hand-rolling it from `<Card>`s.

**Date pickers (`@gravity-ui/date-components`):** the date-range filters on Party Ledger and Analytics, and the `due_date` field in Invoice Builder (Section 5.3). **Every date field in the app uses this calendar picker, never a free-text date field** — the real system's Expenses/Sale/Purchase forms all use a dropdown calendar (seen as "30-Jul-26" style pickers in the reference screenshots), and that pattern is required everywhere a date is entered: Sale date, Purchase date, Expense date, Invoice due date, Login Approvals filters — no manually-typed dates anywhere, to avoid format mismatches (e.g. `30-07-26` vs `07/30/26`) that a free-text field would allow.

**Icons (`@gravity-ui/icons`):** the actual SVG set — uikit's `<Icon>` only renders them, it doesn't include them; e.g. `import {Gear} from '@gravity-ui/icons'; <Icon data={Gear} size={16} />`.

**AI chat components (`@gravity-ui/aikit`, new — fits the Inbox screen exactly):** rather than hand-building the "Generate AI Reply" composer from raw primitives, this package's `PromptInput` and message-list components are purpose-built for an AI-assisted compose box with a "thinking/generating" state — a good fit for Screen 13's Inbox reply flow specifically.

**Setup requirement, easy to miss:** both `@gravity-ui/uikit/styles/styles.css` and its `fonts.css` must be imported once at the app entry point, or every component above renders unstyled. Claude Code should treat a visually broken first render as this missing step, not a deeper bug.

### 4.3.1 Gravity UI — New Features (added after the legacy system review, Section 5.4)

The components above cover the original screen set. These features, added later, map to specific components too — listed here so nothing gets built from raw HTML instead of the design system:

- **Scan Slip (Section 5.4.K):** `<FileSelect>` (uikit) for the upload/camera picker, `<Modal>` for the review step, `<Table>` (short list, a handful of extracted rows) for the matched-items review with a `<Badge view="warning">` on any low-confidence match, `<Alert theme="warning">` if the AI couldn't confidently match an item. Gravity UI has no built-in OCR/vision component — the extraction itself is the OpenAI Vision call (Section 5.4.K); Gravity only renders the picker and the review UI around it.
- **Low Price quick-select (Section 5.4.J):** `<Select>` next to the Rate `<TextInput>` — options populated from that party's `party_item_rates` row if one exists, else a generic "10% off" / "Custom" pair.
- **Party Detail (Section 5.4.I, Screen 3g):** `<Card>` for the profile header, a row of smaller `<Card>`s for the stat tiles (Balance / Credit Limit / Lifetime Business), `<Badge>` for the party-type pill (Customer/Supplier/Both), `<Breadcrumbs>` linking back to the Parties list and forward to the full Ledger.
- **Purchase Builder & Expenses (Section 5.4.B/C, Screens 15–16):** identical component set to Invoice Builder (`<Select>`/`<Combobox>` for party/item pickers, `<TextInput>` for Qty/Rate/Amount, `@gravity-ui/date-components` for the date field) — same form, same components, different backing table.
- **Reports (Section 5.4.H, Screen 17):** a row of `<Card>`s acting as action buttons (Date Wise Report, Customer Ledger, Customer Wise Report, Serial No, Duplicate), each opening its result in a `<Table>` below; the Serial No and Duplicate lookups are a `<TextInput>` + `<Button>` pair, not a full form.
- **Bank Accounts (Section 5.4.E, Screen 18):** uikit's basic `<Table>` is sufficient here (short list, not 1,500 rows) with a `<Switch>` per row for Active/Inactive, and a `<Modal>` + `<TextInput>` for "+ Add Bank."
- **Category 1 / Category 2 dual tabs (Inventory, Screen 3):** two stacked `<TabsItem>` rows via `<Tabs>` — Category 1 on top, Category 2 below it, both filtering the same `<Table>`.
- **Stats strips (Invoices Screen 6, Login Approvals Screen 14):** a row of small `<Card>`s, each just a number + label — the same pattern reused in both places rather than two different implementations.
- **The two-behavior "Edit" button (Section 5.1):** a single `<Button icon={Pencil}>` per row; the branching (direct edit vs. "Fix This Invoice") happens in the click handler based on `invoice_state`, not as two different visual buttons — the person should never see two options here, only one.

### 4.4 Figma Handoff Notes
- Create Figma **Variables** (not just styles) named exactly as the tokens above, in two modes: `Dark` and `Light`, so switching mode in Figma mirrors the app's theme toggle.
- Base grid: 8pt spacing system, 12px card radius, 1px border, solid surfaces (no blur). *(Revised 2026-11-16 with the Midnight Indigo palette, Section 4.1.)*
- Deliver frames for every screen in Section 6, each in both modes.

### 4.5 Mobile Responsiveness (real-world requirement — was not specified before)

This is not optional for every screen equally. Split by how the screen is actually used:

**Tier 1 — Must work fully on mobile (phone-first, these get used away from a desk):**
- Login
- Human Gate Drawer (Approve/Reject) — the most time-sensitive: an Admin away from the shop must be able to approve a held invoice from their phone, not wait until they're back at a desktop
- Party Ledger View (read + Record Payment) — checking a customer's balance or logging a walk-in cash payment happens standing at the counter, phone in hand
- Party Detail (new — added after Section 5.4.I) — checking a party's credit limit/balance before agreeing to a sale in the field is exactly a phone-in-hand moment, same reasoning as Party Ledger
- Expenses (new — added after Section 5.4.C) — a fuel receipt, a rider's payment, a small cash expense: these get logged on the spot, not back at a desk
- Dashboard (KPIs + charts, stacked vertically on small screens)
- WhatsApp share action — naturally a mobile-adjacent flow already
- **Scan Slip specifically** (Section 5.4.K, lives inside Invoice Builder which is otherwise Tier 2) — photographing a handwritten order slip is an inherently mobile action (using the phone's camera); this one sub-feature must work well on mobile even though the rest of Invoice Builder is a Tier 2 "usable but not primary" experience.
- Login Approvals (Section 3.1) — same urgency as Human Gate: a Staff member waiting to log in needs an Admin to approve quickly, and Admin may well be away from a desktop when that happens.

**Tier 2 — Should be usable, simplified on mobile (occasional mobile use, not the primary way):**
- Inventory List (read/search fine on mobile; editing rate/stock works but is more comfortable on desktop)
- Invoice Builder (usable on mobile for a quick invoice; the two-column desktop layout collapses to stacked sections)
- Purchase Builder (new — same reasoning as Invoice Builder, its mirror; receiving stock is usually a shop-side task but occasional mobile entry should still work)
- Parties, Settings
- Inbox (Section 9.1) — reading and replying to a customer email works on mobile, but reviewing an AI-drafted reply carefully is more comfortable with a full screen; not the primary way it's used

**Tier 3 — Desktop-optimized, mobile shows a graceful notice instead of a broken layout:**
- Bulk Upload Excel modal (a 1,500-row file preview genuinely needs a wide screen)
- User Management (an occasional Admin task, not time-sensitive)
- Reports (new — Section 5.4.H; like Analytics, detailed lookups and printable reports are a desktop task)
- Bank Accounts (new — Section 5.4.E; an occasional Admin setup task, not time-sensitive, same reasoning as User Management)
- Analytics full-page (charts remain viewable, but detailed filtering is a desktop task) — the KPI summary on Dashboard already covers the "check on my phone" need

**Breakpoints (Tailwind defaults):** mobile `<640px` (single column, sidebar becomes a bottom nav or hamburger drawer), tablet `640–1024px` (collapsed sidebar, 2-column grids), desktop `>1024px` (full sidebar, full multi-column layouts as designed in Section 6).

This applies to both Stitch (generate a mobile variant for Tier 1 and 2 screens) and Claude Code (build with Tailwind responsive classes from the start, not retrofitted later).

### 4.6 Loading States (real-world requirement — was not specified before)

Every route change and every data-fetching action needs a visible loading state — a blank flash or a frozen screen while data loads reads as broken, even if it's just slow.

- **Route/page transition loader (revised — was a thin top progress bar, now a themed orbit spinner):** a small (~36px) group of three hollow ring circles arranged in a triangular/orbit pattern, centered at the very top of the screen, appearing briefly on every route change (e.g. Inventory → Party Ledger) and disappearing once the new page's data has loaded. The three rings — `#6366F1` (primary), `#22D3EE` (secondary), `#A78BFA` (light indigo), recoloured 2026-11-16 for the Midnight Indigo palette — each carry a subtle matching glow (a ~6px, low-opacity box-shadow in that ring's own color) and rotate together as one rigid unit, one full turn roughly every 1.1s. Still implemented as a Next.js App Router `loading.tsx` per route, not a full-page spinner — it should never fully block the old screen from view while the new one loads.
- **In-component loading:** any card or table waiting on its own data (e.g. a chart while its data loads, a ledger table while a date-filter reloads) shows a **skeleton** (a pulsing gray/glass placeholder shaped like the real content) rather than a spinner-in-empty-space — this is already implied by the Gravity UI component set but is stated explicitly here so it isn't skipped.
- **Button-level loading:** any button that triggers a request (Sign In, Send Email, Approve, Import) disables itself and shows an inline spinner + text change (e.g. "Sending...") while in flight — already specified for Login (Screen 1) and now applies to every action button in the app, not just that one.
- **The Waiting-for-Approval screen (0b)** and the **daily digest / bulk upload progress bar (Section 6, Screen 3)** are two loading states already designed in detail elsewhere — this section is the general rule everything else follows.

### 4.7 Typography — Locked (was left as "Inter or similar," now decided)

**Font: Inter**, loaded via `next/font/google` (self-hosted through Next.js, no external font-request delay).

- Chosen over Manrope and Space Grotesk (the three options discussed earlier) because Inter is the most-used font in real SaaS/financial dashboards, has excellent number/tabular-figure rendering (important for a ledger full of Rs. amounts that must align in columns), and reads cleanly at small sizes on mobile (Section 4.5).
- **Scale:** Heading 28px/600 weight, Section title 20px/600, Body 16px/400, Table text 14px/400, Caption/muted 13px/400. Numbers in tables (Rate, Qty, Balance) use `font-variant-numeric: tabular-nums` so columns of digits align vertically — this matters specifically for the ledger's running-balance column (Section 2.2).
- Same font, same scale in both Dark and Light themes — only color tokens change, per Section 4.1/4.2.

---

## 5. Database Schema (Supabase — Postgres)

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE party_type AS ENUM ('customer', 'supplier', 'both');

CREATE TABLE parties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    party_name VARCHAR(255) UNIQUE NOT NULL,
    party_type party_type DEFAULT 'customer',
    phone VARCHAR(50),
    email VARCHAR(255),                            -- added: required by the Gmail Inbox matching logic, Section 9.1
    address TEXT,
    credit_limit DECIMAL(12,2),                    -- optional; NULL = no limit enforced
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
-- (This table was called 'customers' in earlier drafts. It is created directly as 'parties' now —
--  see Section 5.4.A, which no longer needs its own RENAME step since this is the single source of truth.)

CREATE TYPE quote_status AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE user_role AS ENUM ('admin', 'staff');

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role user_role DEFAULT 'staff',
    is_active BOOLEAN DEFAULT TRUE,           -- Deactivate (Screen 12) sets this to FALSE, never deletes the row
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE inventory_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_code VARCHAR(100) UNIQUE NOT NULL,      -- e.g. 'P-16-S-A-MK'
    item_name TEXT NOT NULL,
    category VARCHAR(50),                          -- e.g. 'Load Cells', 'Indicators', 'Platform Scales', 'Spare Parts'
    unit VARCHAR(20) DEFAULT 'pcs',
    rate DECIMAL(12,2) NOT NULL,
    quantity_in_stock INT DEFAULT 0,
    min_threshold INT DEFAULT 5,
    cloudinary_image_url TEXT,
    cloudinary_public_id TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TYPE transaction_type AS ENUM ('sale', 'receiving');
CREATE TYPE payment_method AS ENUM ('cash', 'cheque', 'online', 'bank_transfer');

CREATE TYPE invoice_status AS ENUM ('unpaid', 'partial', 'paid', 'overdue');

CREATE TABLE customer_ledgers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    party_id UUID REFERENCES parties(id) ON DELETE RESTRICT,   -- renamed from customer_id for consistency with Section 5.4.A's parties table
    invoice_no VARCHAR(50) UNIQUE,                        -- UNIQUE added — was missing; a duplicate invoice number was previously possible
    due_date DATE,                                        -- new — "Pay Dues within 15 Days" (Section 2.3) was never actually tracked before
    invoice_status invoice_status DEFAULT 'unpaid',        -- new — computed/updated as payments are recorded against this invoice
    txn_type transaction_type NOT NULL DEFAULT 'sale',    -- 'sale' = Debit, 'receiving' = Credit
    particular_id UUID REFERENCES particulars(id),        -- replaces the earlier payment_method ENUM, per Section 5.4.F's own instruction (that fix was written but never actually applied to this table until now)
    payment_reference VARCHAR(100),                       -- cheque no. / transaction ID, e.g. "1167"
    payment_note TEXT,                                    -- e.g. "Cheque Sent To Shahab" (seen in real ledger)
    transaction_date DATE NOT NULL,
    discount_amount DECIMAL(12,2) DEFAULT 0.00,   -- the invoice's overall "Special Discount" field (Section 2.3) — applies once per invoice, not per line
    total_amount DECIMAL(12,2) NOT NULL,   -- SUM of all invoice_line_items.line_total for this invoice, minus discount_amount — OR the Payment amount received for a 'receiving' row
    received_at_sale DECIMAL(12,2) DEFAULT 0.00,   -- Section 5.4.D — partial payment collected at the same time as the sale
    previous_balance DECIMAL(12,2) DEFAULT 0.00,
    current_balance DECIMAL(12,2) NOT NULL,
    pdf_cloudinary_url TEXT,
    approval_status quote_status DEFAULT 'approved',   -- 'pending' if above human-gate threshold
    deleted_by UUID REFERENCES users(id),               -- who deleted it (soft-delete audit trail)
    deleted_at TIMESTAMPTZ,                              -- NULL means still active/visible
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ledgers_party_date ON customer_ledgers (party_id, transaction_date DESC);

-- NEW — fixes a real bug: the table above previously had item_code/qty/rate as single columns,
-- meaning ONE invoice could only ever contain ONE item. The business's actual Sale form (reference
-- screenshots) has an "Add To List" table supporting many line items per invoice. This table fixes that.
CREATE TABLE invoice_line_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ledger_id UUID REFERENCES customer_ledgers(id) ON DELETE CASCADE NOT NULL,
    item_code VARCHAR(100) REFERENCES inventory_items(item_code) NOT NULL,
    qty INT NOT NULL,
    rate DECIMAL(12,2) NOT NULL,
    line_total DECIMAL(12,2) NOT NULL,   -- qty * rate for this one line
    line_number INT NOT NULL,             -- display order, matches the "Sno" column in the real invoice (Section 2.3)
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_line_items_ledger ON invoice_line_items (ledger_id, line_number);
-- A 'receiving' (payment) row on customer_ledgers has zero rows here — line items only exist for 'sale' rows.
-- total_amount on the parent invoice = SUM(invoice_line_items.line_total WHERE ledger_id = this invoice) - discount_amount.
-- This is now the authoritative formula, replacing Section 2.2's simplified single-item version.
```

*(Note: `customer_phone` and `customer_name` are no longer duplicated on every ledger row — they now live once in `parties` and are joined in. This fixes a real risk: two invoices typed as "United Scale Ijtibah" vs. "united scale Ijtibah" would previously have split into two different customer ledgers by accident.)*

### 5.0 Recording a Payment (Receiving) — the other half of the ledger

The ledger has always had two row types in the real business data (Section 2.2): **Sale** (Debit, increases what the customer owes) and **Receiving** (Credit, decreases it — cheque, cash, or online payment). The original schema only modeled Sale rows. This is now fixed:

- **"Record Payment" action**, available from the Party Ledger View (Screen 5), lets Admin/Staff log a payment the moment it's received: amount, method (Cash / Cheque / Online / Bank Transfer), a reference number (cheque no. or transaction ID), and an optional note.
- The moment a payment is recorded, `current_balance` recalculates immediately for that customer — the account updates right there, same session, no delay. This is exactly the "receive payment → account updates instantly" behavior being asked for.
- Balance formula, now stated for both row types:
  ```
  current_balance = previous_balance + (total_amount if txn_type='sale' else 0)
                                      − (total_amount if txn_type='receiving' else 0)
  ```
- A 'receiving' row never needs Human Gate approval (it reduces debt, it's not a new charge) — only 'sale' rows above the threshold trigger the gate.
- This also answers who can record it: **Admin can record a payment on behalf of anyone** (walk-in cash, a cheque handed over in person). **Staff can also record a payment**, but cannot edit the rate/discount fields — matching the RBAC table in Section 3.

### 5.1 Invoice Edit Rule: Draft vs. Locked (matches real-world accounting practice)

Add `invoice_state` to `customer_ledgers`: `ENUM ('draft', 'finalized')`.

- **Draft invoices** (not yet dispatched to the customer, not yet Human Gate–approved): fully editable by Admin/Staff — items, rate, qty can all change freely.
- **Finalized invoices** (dispatched via Gmail, or approved through the Human Gate): **locked, cannot be edited directly.** This matches how the business's own paper ledger already works (Section 2.2) — no row is ever overwritten, corrections are always a new row.
- To fix a finalized invoice, Admin creates a **Correction Entry** (Credit Note to reduce, Debit Note to increase) — a new ledger row referencing the original `invoice_no`, which recalculates `current_balance` forward from that point. The original invoice row and its PDF remain untouched, forever, as the audit record.
- This keeps the balance chain (Section 2.2's rule) intact and never rewrites history — the same reason real invoicing/accounting software (and this business's own current process) never edits a finalized entry.

**One "Edit" button, two behaviors underneath (new — makes fixing a mistake simple without weakening the audit rule above).** The real legacy system has a straightforward "Update Bill" button (seen on the Sale Receipt list) — and that ease-of-use is worth keeping, but not at the cost of silently rewriting a dispatched invoice. So: every invoice (on the Invoices list, Screen 6, and its detail view) shows a single **"Edit"** button, and the app decides what happens when it's clicked, not the person:

- If the invoice is still **draft** → clicking "Edit" opens the normal Invoice Builder pre-filled, direct changes save immediately.
- If the invoice is **finalized** → clicking "Edit" opens a small **"Fix This Invoice"** form instead: what's wrong (a short reason, required), and the corrected fields (item/qty/rate/discount) — submitting it creates the Correction Entry described above and shows a clear confirmation: *"A correction has been recorded. The original invoice is preserved for the record; the customer's balance has been updated."* The person fixing the mistake experiences this as "editing the invoice" — they never have to know or care that it's technically a new row underneath.
- Both paths are reachable from the exact same button and the exact same place in the UI — the safety rule from above is enforced by the system, not by the person remembering which invoices are allowed to be touched.

```sql
ALTER TABLE customer_ledgers ADD COLUMN invoice_state VARCHAR(20) DEFAULT 'draft';
-- 'draft' | 'finalized'
ALTER TABLE customer_ledgers ADD COLUMN correction_of UUID REFERENCES customer_ledgers(id);
-- set only on a Correction Entry row, pointing back to the original invoice it corrects
ALTER TABLE customer_ledgers ADD COLUMN correction_reason TEXT;
-- required when correction_of is set — the short reason typed into "Fix This Invoice"
```

### 5.2 Data Retention Rule (explicit — this was missing before, now locked in)

- **Every finalized invoice / ledger entry is permanent by default.** There is no automatic expiry, no auto-archiving, and no scheduled cleanup job of any kind.
- **Only an Admin can remove an entry, and it must be a deliberate, individual action** — never a bulk auto-delete, never a background job. This is a **soft delete**: the row is marked `deleted_at` / `deleted_by`, not physically dropped from the database, so there is always a recovery trail and an audit log of who removed what and when.
- **Default view is always sorted by `transaction_date DESC`** (newest first) within a customer's ledger, and the same rule applies to the Invoices list screen — sorted by invoice date, most recent on top, with a date-range filter available (already specified in Screen 5).
- This rule applies to the harness too (Section 7): the deny-list in `settings.json` must include a rule that blocks any bulk-delete or `DROP`/`TRUNCATE`-style operation on `customer_ledgers`, so an agent loop can never mass-clear ledger history, even by mistake.

```sql
-- Deny bulk delete at the harness level (add to settings.json deny list logic)
-- Bash(psql *DELETE FROM customer_ledgers*)   → deny
-- Bash(psql *TRUNCATE customer_ledgers*)      → deny
-- Only a single-row, admin-authenticated API call may soft-delete one entry.
```

### 5.3 Invoice Numbering & Status Lifecycle (real-world requirement — was missing)

**Auto-numbering, not manual typing.** The real ledger (Section 2.2) shows sequential invoice numbers (2044, 2052, 2057…) with no gaps or repeats. This must be system-generated, never typed by Admin/Staff:
```sql
invoice_no = (SELECT MAX(invoice_no::int) FROM customer_ledgers WHERE invoice_no IS NOT NULL) + 1
```
Generated at the moment an invoice moves from `draft` to `finalized` (Section 5.1) — not at draft creation — so an abandoned draft never burns a number, keeping the sequence exactly as clean as the paper ledger's.

**Due date.** Defaults to `transaction_date + 15 days` (matching "Pay Dues within 15 Days" already printed on the real invoice, Section 2.3), editable per invoice if a customer negotiates different terms.

**Status, computed automatically, never hand-set:**
- `unpaid` — no payment recorded against this invoice yet, due date not passed
- `partial` — some payment recorded, but the invoice's own portion of the balance isn't fully cleared
- `paid` — payments recorded bring this invoice's amount to zero
- `overdue` — `due_date` has passed and status is still `unpaid` or `partial`; a scheduled daily beat (a third heartbeat, alongside Section 7.1's two) checks every finalized invoice each morning and flips `unpaid`/`partial` → `overdue` where the date has passed, and includes overdue invoices in the same daily digest email as the low-stock alert

*(Honest note on precision: the real ledger reduces a customer's total balance with each payment rather than marking specific invoices "paid" one by one — so which invoice a given payment actually closes is a judgment call, not something the paper record made explicit. This system keeps the simple, provable part — total balance via the running-balance formula, Section 2.2 — as the source of truth, and status per invoice is a best-effort convenience label layered on top, not a second ledger that could disagree with the real one.)*

### 5.4 Legacy System Feature Parity (new — from the existing desktop app screenshots)

The business already runs a working Access/VB desktop system (screenshots reviewed: Category, Expenses, Customer/Party Form, Sale, Purchase, Reports, Bank Form, Units Form). This PRD's earlier drafts only modeled half of it — the Sale side. **These modules are missing and must be added:**

**A. Parties, not just Customers.** The real system has one master list ("Parties") used for both Sale (customers) and Purchase (suppliers) — the same entity can appear as who you sell to or buy from. The `parties` table (Section 5) already has `party_type` and `email`; the one remaining behavior to build:
```sql
-- credit_limit and the party's current balance must display live on the Sale/Purchase forms
-- (Current Balance / CR Limit, top-right, as seen in the reference screenshots) the moment a party is selected.
```

**B. Purchase Module (new — buying stock from suppliers, the mirror of Sale).**
```sql
CREATE TABLE purchases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    purchase_bill_no VARCHAR(50) UNIQUE,          -- auto-numbered, same rule as Section 5.3's invoice numbering
    party_id UUID REFERENCES parties(id) NOT NULL,
    transaction_date DATE NOT NULL,
    discount_amount DECIMAL(12,2) DEFAULT 0.00,
    total_amount DECIMAL(12,2) NOT NULL,          -- SUM of purchase_line_items.line_total minus discount_amount
    received_amount DECIMAL(12,2) DEFAULT 0.00,    -- what WE have paid the supplier so far, editable at entry time (see D below)
    previous_balance DECIMAL(12,2) DEFAULT 0.00,
    current_balance DECIMAL(12,2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Same multi-item fix as invoice_line_items above — the real Purchase form also has an "Add To List" table.
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
```
A Purchase **increases** `inventory_items.quantity_in_stock` — for every line item in `purchase_line_items`, by that line's `qty` — the reverse of a Sale. Same balance-chain discipline as Section 2.2/5.0 applies, just from the business's side as the buyer rather than the seller.

**C. Expenses Module (new).**
```sql
CREATE TABLE expenses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    serial_number SERIAL,
    expense_date DATE NOT NULL,
    party_id UUID REFERENCES parties(id),          -- optional; not every expense has a party (e.g. utility bills)
    description TEXT,
    amount DECIMAL(12,2) NOT NULL,
    particular_id UUID REFERENCES particulars(id),  -- see F below — configurable category, not a fixed ENUM
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```
Matches the real "Expenses" form exactly: Serial Number, Date, Party Name, Description, Amount, Particular.

**D. "Received" amount directly on the Sale/Purchase form (new — was only handled as a separate ledger entry before).** The real system lets Received be entered *at the same time* as the sale, not only afterward via a separate "Record Payment" action (Section 5.0, which still exists for payments received later). Add:
```sql
ALTER TABLE customer_ledgers ADD COLUMN received_at_sale DECIMAL(12,2) DEFAULT 0.00;
```
The Invoices list (Screen 6) must show a **Received** column (matching the real "SALE RECEIPT" list's Received/Balance columns) — this was missing before; only a status badge existed.

**E. Bank Accounts (new — Bank Form).** The real system tracks specific bank accounts, not a generic "bank_transfer" label:
```sql
CREATE TABLE bank_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bank_name VARCHAR(100) NOT NULL,   -- e.g. 'Meezan Bank', 'HBL', 'MCB', 'Cash Received' (cash is modeled as a pseudo-"bank" row, matching the real system's own list)
    account_note TEXT,
    is_active BOOLEAN DEFAULT TRUE
);
ALTER TABLE customer_ledgers ADD COLUMN bank_account_id UUID REFERENCES bank_accounts(id);
```
A new **Bank Accounts screen** (Admin-only, Settings sub-section) lets Admin manage this list — add/deactivate banks, matching the real Bank Form's simple ID/Name table.

**F. Configurable Category & Particular lists (replaces the fixed ENUMs from earlier drafts).** The real system's `txn_type`/`payment_method` aren't hardcoded — they're editable master lists (Category 1 Form, Category 2 Form, Particular Form), so Admin can add a new payment type or category without a code change:
```sql
CREATE TABLE categories_1 (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), name VARCHAR(100) UNIQUE NOT NULL);
CREATE TABLE categories_2 (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), name VARCHAR(100) UNIQUE NOT NULL);
CREATE TABLE particulars (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), name VARCHAR(100) UNIQUE NOT NULL);
-- Seed categories_1 with the real system's actual values: All, Indicator, Load Cell, Plat Form, Key Pad, Crane Scales, Top Loading Scale
-- Seed particulars with: Cash, Cheque, Online, Bank Transfer, Discount (matches what's seen in the real ledger's Particular column)
ALTER TABLE inventory_items ADD COLUMN category_1_id UUID REFERENCES categories_1(id);
ALTER TABLE inventory_items ADD COLUMN category_2_id UUID REFERENCES categories_2(id);
```
This **replaces** the earlier `category VARCHAR(50)` single free-text field (Section 5) and the `payment_method` ENUM (Section 5.0) — both become admin-editable master tables instead. The Sale/Purchase forms show **two** category dropdowns side by side (Category 1, Category 2), exactly as seen in the real system's screens.

**G. Units master with conversion factor (new — Units Form).**
```sql
CREATE TABLE units (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(20) UNIQUE NOT NULL,   -- 'pcs', 'box', 'carton', 'KG', 'Grms' — the real system's actual list
    conversion_factor DECIMAL(10,4) DEFAULT 1.0000  -- e.g. 1 box = 12 pcs → factor 12
);
ALTER TABLE inventory_items ALTER COLUMN unit TYPE UUID USING NULL;  -- becomes a foreign key instead of free text
ALTER TABLE inventory_items ADD CONSTRAINT fk_unit FOREIGN KEY (unit) REFERENCES units(id);
```
The Sale/Purchase item picker shows a live "Remaining" (current stock) figure the moment an item is selected, and the Rate auto-adjusts if the chosen unit's `conversion_factor` differs from the item's base unit — matching the real form's Units/Factor/Rate row.

**H. Reports screen (new — distinct from Analytics, Section 8).** The real system has a dedicated lookup/reporting screen, simpler and more operational than the chart-based Analytics: Date Wise Report, Customer Ledger (printable), Customer Wise Report, Serial No lookup (jump to a specific invoice/bill number instantly), and Duplicate (reprint a duplicate copy of any invoice). This is a **new Screen 15**.

**I. Party Detail Page (new — clicking a party's name opens more than just their ledger).** The Parties list (Screen 11) links each row to a full **Party Detail** view, not straight to the Ledger: name, phone, address, email, `party_type` (customer/supplier/both), credit limit, current outstanding balance, total lifetime business done (sum of all sale/purchase amounts), and a tab or link over to their full Ledger (Screen 5) for the transaction history itself. The Ledger stays a separate, focused view (it needs the full-width table); the Detail page is the summary card you land on first.

**J. Manual Price Override + Low-Price Option (new — Sale/Purchase item rate).** The Rate field on Invoice Builder and Purchase Builder is never locked to the catalog price:
- **Manual override:** Admin/Staff can always type a different rate directly into the Rate field for that line item — the catalog `rate` is a default, not a floor.
- **"Low Price" quick option:** a small dropdown/button next to Rate offering pre-set lower tiers (e.g. a negotiated wholesale rate stored per party, or a flat "10% off catalog" quick-apply) — faster than typing a manual number when a regular customer always gets a set discount. This reads from an optional `parties.negotiated_rate_note` or a small `party_item_rates` override table if per-item negotiated pricing is needed:
```sql
CREATE TABLE party_item_rates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    party_id UUID REFERENCES parties(id) NOT NULL,
    item_code VARCHAR(100) REFERENCES inventory_items(item_code) NOT NULL,
    negotiated_rate DECIMAL(12,2) NOT NULL,
    UNIQUE(party_id, item_code)
);
```
When a party with a stored negotiated rate for that item is selected, the Rate field pre-fills with their rate instead of the catalog default — still editable either way.

**K. Scan Slip — AI-read a handwritten/rough order slip (new, significant feature).** A customer sometimes hands over a rough handwritten note ("15 platform scales, 5 load cells") instead of calling in an order. Rather than manually re-typing it:
- A **"Scan Slip"** button on Invoice Builder (and Purchase Builder) opens the camera/file picker, the person photographs or uploads the handwritten/printed slip.
- The image is sent to a vision-capable AI call (the same `OPENAI_API_KEY` from Section 11 — GPT-4o/GPT-4-Vision-class models read handwriting and print reasonably well; no separate API key needed) with a prompt asking it to extract line items: item description, quantity, and any rate mentioned.
- The AI's extracted items are shown as a **review list before anything is added** — matched against `inventory_items` by closest name/code match, with a confidence flag on any item it couldn't confidently match (Admin/Staff picks the right item manually for those). **Nothing is added to the invoice automatically without this review step** — same human-in-the-loop principle as the Human Gate and AI Reply features (Section 3.1's Login Gate, Section 9.1's AI Reply).
- Once reviewed and confirmed, the matched items populate the Invoice Builder's line-item list as normal, ready for Qty/Rate adjustment same as manual entry.
- The original scanned image is kept attached to that invoice (uploaded to Cloudinary) as a reference — useful later if there's ever a dispute about what was actually ordered.

---

## 6. Screens (for both Claude Code build and Figma template)

*(Numbering note: this section numbers screens 1–11. The Stitch prompt file numbers the same screens 0–9, because "Item Detail/Edit" here is screen 4 but is a modal inside Inventory in Stitch, not a separate generated screen. **Always match screens by name, not number, between this PRD and the Stitch output** — Claude Code should build against the names/fields described here, not assume the numbers line up across documents.)*

1. **Login** — full-screen glass card, centered on the themed background (theme toggle visible even before login). Fields: Email, Password (with show/hide eye icon), "Remember me" checkbox, "Forgot Password?" link, primary "Sign In" button. Company branding at top: "Ω OMEGA SCALES" logo/wordmark. Error state: inline red message under the field, e.g. "Incorrect email or password" — never a generic browser alert. Loading state: button shows a spinner and disables while the request is in flight. On success, redirect by role — Admin → Dashboard directly, **Staff → a "Waiting for admin approval..." screen (Section 3.1)** — a centered spinner with the message "An administrator needs to approve this login. This page will update automatically." that polls in the background and proceeds into the app (to Inventory List) the moment an Admin approves, or shows "Login declined" if rejected. No self-signup form on this screen — accounts are created by Admin only (Section 3), so there is no "Create account" link here.
2. **Dashboard** — KPI cards (Total Sales, Outstanding Receivables, Low Stock Alerts, **Pending Approvals** — this fourth card was missing before but is already in the actual Stitch screenshot and links directly to the Human Gate Drawer, Screen 8), plus a **3-chart summary** (Monthly Sales & Revenue, Top 5 Selling Scale Models, Customer Debt) — the same three from the original Analytics set; the Dashboard intentionally shows only these three as a quick daily glance, while the full six-chart set (Section 8) lives on the Analytics screen for deeper review. Also includes an **Inbox preview panel** (new) — the 5 most recent unread invoice-related emails, with an unread-count badge, linking to the full Inbox screen (13).
3. **Inventory List** — searchable/paginated table, thumbnail, category filter tabs (All Items / Load Cells / Indicators / Platform Scales / Spare Parts), **"Bulk Upload Excel" button** (see full flow below), add-item modal for single-item entry

   **Bulk Upload flow (its own modal, triggered by the button above):**
   - Step 1 — **File picker**: drag-and-drop or browse for `.xlsx`/`.csv`, plus a "Download Template" link (a blank Excel with the correct columns: item_code, item_name, category, unit, rate, quantity_in_stock, min_threshold).
   - Step 2 — **Preview & validate**: after upload, show a table preview of the first ~20 parsed rows, a count of total rows detected, and a validation summary — how many rows are new inserts vs. updates to an existing `item_code`, and how many rows have errors (missing rate, duplicate code, etc.) listed by row number.
   - Step 3 — **Confirm**: an "Import 1,247 items (3 errors will be skipped)" button — Admin sees the exact count before committing, nothing silent.
   - Step 4 — **Progress + result**: a progress bar while FastAPI processes the batch, then a result summary card — "1,244 imported, 3 skipped (view errors)" — with a downloadable error report for any skipped rows so nothing is silently lost.
   - This whole modal only appears for Admin; Staff do not see the Bulk Upload button at all (Section 3 RBAC).

   **Low-stock alert:** when `quantity_in_stock` drops to or below `min_threshold` for any item, the Dashboard's "Low Stock Alerts" KPI count increases immediately, and a daily digest email (via the same Gmail sender, Section 9) is sent to Admin listing all items currently below threshold — so restocking isn't only discovered by someone happening to check the dashboard.
4. **Item Detail / Edit** — image upload (Cloudinary), category, rate/stock fields (Admin only)
5. **Party Ledger View** (renamed from "Customer Ledger View" — Section 5.4.A generalized `customers` to `parties`, covering both customers and suppliers, so this screen must too) — a **small balance-trend chart** at the top (new, `@gravity-ui/charts` line chart, source: `current_balance` from every row in this party's `customer_ledgers` history, plotted by `transaction_date` — same live table as the main list below, so the chart and the numbers can never disagree) gives an at-a-glance read of whether this party's balance has been growing or shrinking over time, before scrolling into the row-by-row detail. Below that, the running-balance table exactly like Section 2.2, filter by date range, **"Record Payment" button** (opens a form: amount, method Cash/Cheque/Online/Bank Transfer with a Bank Account picker from Section 5.4.E, reference number, note — logs a Receiving row and updates balance immediately). Works identically whether the party is a customer (money owed to us) or a supplier (money we owe them) — same screen, same math, just which direction the balance runs.
6. **Invoices** (new — was only "Invoice Builder" before; the sidebar's "Invoices" link had no actual list screen behind it until now) — a **stats strip at the top** (new): Total Invoices, Paid count, Unpaid count, Overdue count — four small glass cards, always visible so the overall picture is clear before scrolling the list (matches the real system's need to see "how many invoices so far, how many paid/unpaid" at a glance). Below that, a searchable, paginated table of every invoice across all customers: columns Invoice #, Customer, Date, Due Date, Amount, **Received** (matches the real system's "SALE RECEIPT" list — Section 5.4.D), Balance, Status (badge: Unpaid/Partial/Paid/Overdue — Overdue in red), and Approval status if still pending Human Gate. Filter tabs: All / Unpaid / Overdue / Pending Approval. Clicking a row opens that invoice's detail/PDF preview, with an **"Edit"** button (Section 5.1 — opens direct edit for drafts, opens "Fix This Invoice" correction flow for finalized invoices, same button either way) and "Add Payment" action. A "+ New Invoice" button opens the Invoice Builder (below).
7. **Invoice Builder** — customer picker (shows their live Current Balance / CR Limit the moment selected, Section 5.4.A), a **"Scan Slip"** button (Section 5.4.K — photograph/upload a handwritten order, AI-extracts items for review before adding), item picker that shows a live **"Remaining"** stock figure the instant an item is chosen (Section 5.4.G), Category 1 / Category 2 dropdowns for filtering the item list, a Rate field that's always manually editable plus a **"Low Price"** quick-select next to it (Section 5.4.J), auto-calculates Total/Balance exactly like Section 2.3, a **Received** field for any amount collected at the time of sale (Section 5.4.D), live PDF preview, discount field
8. **Human Gate Drawer** — queue of invoices > Rs. 100,000 awaiting Admin approval, Approve/Reject buttons
9. **Analytics** — full-page chart view
10. **Settings** — User Profile, Theme toggle, Notification preferences, Human Gate threshold (Admin-editable), Connected Email (Gmail dispatch), Danger Zone
11. **Parties** (renamed from "Customers" — now covers customers and suppliers, Section 5.4.A) — a list of all parties with name, phone, party type badge (Customer/Supplier/Both), current outstanding balance, and last transaction date; clicking a row opens their **Party Detail page** (Section 5.4.I — full profile summary), which links onward to their full Ledger (Screen 5). "+ Add Party" button (Admin/Staff) for adding a new party before their first transaction, so Invoice/Purchase Builders always pick from an existing list rather than free-typing a name each time (this is what prevents the duplicate-name problem noted in Section 5).
12. **User Management** (new — Admin only, was referenced in Section 3 but had no screen) — a table of all Staff/Admin accounts (name, email, role, last login), an "+ Add User" button opening a form (name, email, role, temporary password auto-generated and emailed to them), and a "Deactivate" action per user (soft-disable login, not a delete — matches the retention philosophy in Section 5.2).
13. **Inbox** (new — Section 9.1) — a list of invoice-related Gmail messages (unread bolded, badge count in sidebar nav), filtered to only messages from known customers or replying to an invoice thread. Clicking a message opens it split-view: thread on the left, a reply composer on the right with a "Generate AI Reply" button, a manual text area, an "Attach Invoice PDF" picker (searches by invoice number, inserts the Cloudinary link), and Send. Per-message row actions: mark read/unread, delete (soft, mirrors Gmail Trash). A small "linked to Invoice #2127" chip appears when the system matched the thread to a specific invoice.
14. **Login Approvals** (new — Admin only, Section 3.1) — a live list of pending Staff login requests at the top (name, requested time, a pulsing "waiting" indicator, Approve/Reject buttons), a small **stats strip** above the history (This Week: Approved count, Rejected count, Expired/no-response count — three mini glass cards), and below it a searchable history of all past requests (who, when, approved/rejected/expired, by which Admin) with a delete action per row and the ability to add a note.
15. **Purchase Builder** (new — Section 5.4.B, mirrors Invoice Builder) — supplier picker (from the same Parties list, filtered to `party_type IN ('supplier','both')`), item picker showing live Remaining stock, Category 1/Category 2 dropdowns, Qty/Rate/Amount, a Received field for partial payment to the supplier at entry time, Line Total/Discount/Amount Payable, "Add New" and "Print And Save" buttons — same layout discipline as Invoice Builder, just for stock coming in instead of going out.
16. **Expenses** (new — Section 5.4.C) — a form (Date, Party [optional], Description, Amount, Particular dropdown) plus a list/table of past expenses below it, filterable by date range and Particular.
17. **Reports** (new — Section 5.4.H, distinct from Analytics) — Date Wise Report, Customer Ledger (printable), Customer Wise Report, a Serial No jump-to-invoice search, and Duplicate (reprint any invoice as a marked "Duplicate" copy).
18. **Bank Accounts** (new — Section 5.4.E, a Settings sub-section or its own small screen, Admin only) — a simple list (Bank Name, Active/Inactive toggle) matching the real system's Bank Form; "Cash" is one of the rows, not a special case.

**Forgot Password flow (Screen 1's link):** enters email → if it matches an active user, an emailed reset link (valid 1 hour) lets them set a new password → generic "If that email exists, we've sent a reset link" message either way, so the form never confirms or denies which emails have accounts (a basic security practice, not optional).

**Product image requirement (applies to Screen 7 Invoice Builder and the generated PDF, Section 9):** every line item in an invoice — both in the on-screen builder/preview and in the final PDF sent to the customer — must show the product's thumbnail image next to its item code/name, so the customer can visually confirm what they purchased alongside quantity and rate.

**Export for the accountant:** both the Party Ledger View and the Analytics screen include an "Export" button (Excel via a backend `pandas.to_excel()` call, and PDF via the same ReportLab engine used for invoices) — so the business can hand a clean statement to an accountant or auditor without screenshotting the app.

---

## 7. Agentic Loop & Harness (Claude Code Implementation Layer)

This system is built and *operated* using loop + harness engineering, not just coded once.

### 7.1 The Loop — Two Heartbeats

This system runs **two separate loops**, not one:

1. **Event-driven + conditional (invoice creation):** invoice creation (event) → conditional loop validates math before allowing PDF generation.
2. **Scheduled (daily low-stock digest, Screen 3):** every day at a fixed time (e.g. 8:00 AM), a scheduled beat queries `inventory_items` for anything at or below `min_threshold` and emails Admin the list. This is a plain schedule, not conditional — it always sends, even if the list is empty ("No items below threshold today"), so silence never gets confused with "nothing to check."

- **Spine:** `progress.md` — records every invoice processed, every escalation, every Gmail dispatch, and every low-stock digest sent
- **Maker–checker:** the invoice-generation agent (maker) is checked by a separate validation step (checker) before any email is sent

### 7.2 Harness — Constrain
```json
{
  "permissions": {
    "allow": ["Read", "Bash(npm test *)", "Bash(git diff *)"],
    "ask": ["Bash(git push *)"],
    "deny": [
      "Read(./.env)",
      "Read(./secrets/**)",
      "Bash(rm -rf *)",
      "Bash(git push --force *)"
    ]
  }
}
```

### 7.3 Harness — Verify (hooks)
- **Math rule (hard-coded check, not a model opinion):** `total_amount == rate * qty`
- **Balance rule:** `current_balance == previous_balance + total_amount − payment_received`
- A `PostToolUse` hook re-validates these two formulas after every ledger/invoice write; a mismatch blocks the write and logs to `progress.md`.

### 7.4 Harness — Escalate (Human Gate)
```json
{
  "harness_name": "Claude-Omega-Scales-Harness",
  "spine_file": "progress.md",
  "human_gate_threshold": 100000.00,
  "rules": {
    "math_formula": "total_amount == rate * qty",
    "balance_formula": "current_balance == previous_balance + total_amount",
    "gate_trigger": "If bill_total > 100,000 PKR → halt Gmail dispatch, open Human Gate Drawer, wait for Admin [APPROVE / REJECT]"
  }
}
```
**Live test case:** Invoice #2127 (Rs. 184,500) must trigger this gate — it is the acceptance test for this feature.

---

## 8. Analytics & Data Visualization

*(Revised 2026-11-16. The original Matplotlib → PNG → Cloudinary pipeline was retired on 2026-08-07. Every chart now renders live in the browser with `@gravity-ui/charts`, from JSON. There is no server-side image generation and no `chart_url` anywhere.)*

**Pipeline:** FastAPI query function (`app/services/analytics_service.py`) → JSON `{ "data": [...] }` → `@gravity-ui/charts` in the browser. All chart data comes from the same tables that power the rest of the app (Section 5). There is no separate "reporting" dataset to keep in sync, so the numbers on Analytics always match what's really in Inventory and the Ledgers.

### 8.1 Endpoints and response shapes (as built)

Every analytics endpoint returns `AnalyticsResult` = `{ "data": list[object] }`. The four range-aware endpoints accept optional `start_date` / `end_date` query params (`YYYY-MM-DD`, inclusive, matched against `transaction_date`). Customer Debt and Low Stock are always a live snapshot and take no date params. Every endpoint requires an authenticated session (`get_current_user`), and Admin and Staff can both read them, matching the `/analytics` and `/dashboard` rows in Section 3.2.

| # | Chart | Endpoint | Item shape | Source / rules |
|---|---|---|---|---|
| 1 | Monthly Sales & Revenue | `GET /analytics/monthly-sales-revenue` | `{ month: "YYYY-MM", revenue: number }`, ascending by month | `customer_ledgers` sales, `invoice_state='finalized'`, not soft-deleted, summed `total_amount` per month |
| 2 | Top 5 Selling Scale Models | `GET /analytics/top-selling-models` | `{ item_name: string, quantity_sold: number }`, max 5, descending | finalized, non-deleted `customer_ledgers` → `invoice_line_items` → `inventory_items`, summed quantity by item name |
| 3 | Customer Debt / Ledger Balance | `GET /analytics/customer-debt-balance` | `{ party_name: string, current_balance: number }`, only balances > 0 | latest (by `created_at`) non-deleted `customer_ledgers.current_balance` per `parties` row of type `customer` or `both` |
| 4 | Low Stock Items | `GET /analytics/low-stock-items` | `{ item_code: string, quantity_in_stock: number, min_threshold: number }`, most-below-threshold first | `inventory_items` where `quantity_in_stock <= min_threshold`: the same rule as the Dashboard KPI and the daily digest (Section 7.1), so they can never disagree |
| 5 | Payment Method Breakdown | `GET /analytics/payment-method-breakdown` | `{ method: string, total: number }` | `customer_ledgers` receivings, grouped by `particulars.name` (Cash/Cheque/Online/Bank Transfer, "Unknown" if unset) |
| 6 | Category-wise Sales | `GET /analytics/category-wise-sales` | `{ category: string, total: number }` | finalized, non-deleted sale line items grouped by the item's `categories_1.name` ("Uncategorized" if unset) |
| 7 | Party Balance Trend (Party Ledger page) | `GET /parties/{id}/ledger` (no dedicated chart endpoint) | ledger rows; the chart plots `{ x: transaction_date, y: current_balance }` | sorted client-side by `transaction_date`, ties broken by `created_at` (insertion order, which is the order `current_balance` was computed in, Section 17) |

### 8.2 Where each chart appears

- **Analytics** (`/analytics`): charts 1–6, with one shared From/To filter feeding charts 1, 2, 5 and 6. Charts 3 and 4 say "live snapshot" under their title.
- **Dashboard** (`/dashboard`): charts 1, 2 and 3, as the *same components* as Analytics at a shorter height. This repetition is intentional.
- **Party Ledger** (`/parties/[partyId]/ledger`): chart 7.

### 8.3 Chart types

| Chart | Type | Notes |
|---|---|---|
| Monthly Sales & Revenue | Area | Primary-accent line (the library draws area lines with round joins/caps by default), flat translucent fill (series `opacity` 0.25) |
| Top Selling Scale Models | Vertical bar | Rounded top corners, single series in the primary accent |
| Customer Debt / Ledger Balance | Donut | **Top 5 parties as slices, the rest grouped as "Others"** (muted neutral colour). **Total outstanding debt shown in the centre.** Legend, no slice labels |
| Low Stock Items | Horizontal bar, 2 series | In Stock vs Min Threshold per item, rounded, legend |
| Payment Method Breakdown | Donut | One slice per method, percentage labels on slices, empty centre. It reads differently from the Customer Debt donut on purpose |
| Category-wise Sales | Horizontal bar | **Sorted descending**, rounded, single series. **Total of all categories shown as a number beside the chart title** (replaces the earlier waterfall) |
| Party Balance Trend | Line | Primary-accent line with round joins/caps, no fill (keeps it distinct from the area chart) |

### 8.4 Chart styling rules (both themes)

- **Colours come from the design tokens** in `app/globals.css` (Section 4.1/4.2), read at runtime by `useChartColors()` (`lib/theme/use-chart-colors.ts`), so a theme switch recolours every chart. `lib/theme/chart-palette.ts` holds the same values as the fallback for server rendering.
  - Multi-series (slices, grouped bars): `--chart-1`…`--chart-6` = `#6366F1, #22D3EE, #34D399, #FBBF24, #F472B6, #A78BFA`, in fixed order: slot N is always the same hue.
  - Single-series charts: the theme's `--accent-primary` (`#6366F1` dark, `#4F46E5` light).
  - "Others" / remainder slices: `--text-muted`.
- **Lines:** straight segments between real data points, with round joins and caps (public `linejoin`/`linecap: 'round'` on line series; area lines are drawn round by default), width 2.5px. No curve smoothing: the library has no public option for it, and reshaping its rendered SVG is not allowed (it would depend on library internals).
- **Area fill:** flat fill in the series colour at 25% opacity, through the public `opacity` option. A gradient fill was considered and **skipped**: it would mean restyling the library's internal SVG path classes.
- **Bars:** 6px corner radius.
- **Gridlines:** 1px in `--border` (light, never competing with the data), and axis labels in `--text-muted`. Both come from the Gravity theme tokens (`--g-color-line-generic`, `--g-color-text-secondary`) set in Section 4, not from chart-specific CSS.
- **Tooltips** on every chart. Currency values formatted `Rs. 1,234,567`, no decimals.
- **Legends** only on multi-series charts and donuts. A single-series chart is named by its title.
- **Load animation:** the whole chart body (our own wrapper element, not library DOM) fades and rises 6px over about 400ms when data first arrives. It does not replay on resize, and is disabled under `prefers-reduced-motion: reduce`. Per-shape animation (bars growing, slices scaling) was **skipped** because it would need the library's internal classes.
- **Loading state:** the fixed `<Skeleton>` (Section 4.6) at the chart's real height. **Empty state:** the shared empty-state glyph with "No data yet". **Error:** a toast naming the failed charts; the card falls back to the empty state.
- **Responsive:** every chart fills its card's width and re-lays out on resize. Card heights are 300px on Analytics and 220px on Dashboard.
- **Shared building blocks** (`components/charts/`): `ChartFrame` (card, title, headline number, loading/empty, load animation), `AreaTrendChart`, `LineTrendChart`, `BarChart` (vertical or horizontal), `DonutChart` (optional centre total, top-N + "Others" grouping). The per-metric components in `components/analytics/` only map API rows into these.

---

## 9. Invoice PDF & Email + WhatsApp Sharing + Gmail Inbox

### 9.1 Gmail Inbox — reading, replying, and CRUD on invoice-related messages (new — was discussed but not yet written down)

This is a different capability from "sending" an invoice email (Section 9 below). Sending only needs an App Password (SMTP, outbound-only). **Reading the inbox needs the Gmail API with OAuth** — that's a real technical difference, so both are listed separately here.

- **What shows up:** only emails that are invoice-related — matched by (a) the party's registered email in `parties.email` replying to a thread the system itself started when an invoice was sent, or (b) the subject line containing an invoice number the system recognizes (e.g. "Re: Invoice #2127"). This is a filtered view, not the Admin's whole personal inbox — random newsletters or unrelated mail never appear here.
- **Where it lives:** a dedicated **Inbox screen** (new — Screen 13), with a preview panel on the Dashboard showing the 5 most recent unread invoice-related messages and an unread-count badge, linking through to the full Inbox screen.
- **Per-message actions (full CRUD):**
  - **Read** — open a message, see the thread, see which invoice it's tied to (linked, one click to that invoice)
  - **Reply — manually** — a compose box, type and send
  - **Reply — AI-generated draft** — a "Generate Reply" button calls the OpenAI API (a new key, see Section 11) with the message content and the linked invoice/ledger context, drafts a suggested reply into the compose box — **it is a draft, never auto-sent**; Admin/Staff reviews and edits before pressing Send, same human-in-the-loop principle as the Human Gate
  - **Share PDF in a reply** — attach or link the relevant invoice's Cloudinary PDF directly from the reply composer, no need to re-generate or hunt for it
  - **Mark as read/unread** — manual toggle, independent of whether it's been opened
  - **Delete** — removes it from the Inbox view (Gmail-side, moves to Trash via the API — not permanently destroyed, matching the retention philosophy of Section 5.2)
  - **Edit** — only applies to an unsent draft reply, not to the customer's original incoming message (which, like a finalized invoice, is never altered — see Section 5.1's same logic applied here)
- **Who can use it:** both Admin and Staff can read and reply; only Admin can delete. AI-generated replies are available to both, but every AI-drafted reply still requires a human to press Send — no auto-send loop exists here, on purpose.

```sql
CREATE TABLE inbox_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    gmail_message_id VARCHAR(255) UNIQUE NOT NULL,
    gmail_thread_id VARCHAR(255) NOT NULL,
    from_email VARCHAR(255) NOT NULL,
    party_id UUID REFERENCES parties(id),                -- matched if the sender is a known party (renamed from customer_id — was a broken reference)
    related_invoice_no VARCHAR(50),                       -- matched from thread/subject if possible
    subject TEXT,
    snippet TEXT,
    received_at TIMESTAMPTZ NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,                     -- soft delete, mirrors Gmail Trash
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

### 9.2 Sending — PDF, Email, WhatsApp

**PDF color theme (new — was plain black-and-white before, like the paper original):** the paper invoice (Section 2.3) is pure black-on-white, which is fine for a print shop but reads as dated for a PDF a customer opens on-screen. Real-world B2B invoices at this scale use a light, restrained accent — never the full app's dark glassmorphic look, which would be heavy and hard to print. The rule: **white page, dark text, one accent color used sparingly.**

- Header band: a light tint of the peacock accent (`#E4F3F4`, a ~90%-lightened version of `#146C8C`) behind the "OMEGA SCALES" name and address block — not a hard color block, a soft wash.
- Accent color: `#0F6B7C` for the invoice number, the horizontal rule under the header, and the "Total Payable" figure — the one number that matters most gets the one spot of color.
- Table: white background, `#0F6B7C` for the header row text (not filled), light gray (`#F5F7FA`) zebra-striping on alternating rows for readability, thin `#D0D7DE` borders — never heavy black grid lines.
- Body text: near-black (`#1A1A1A`), not pure `#000000` — pure black on white is harsher to read than a soft near-black, and it's the same principle behind the app's `--text-primary` tokens (Section 4.1/4.2) never being pure white or pure black either.
- Everything else (layout, fields, the exact wording "Pay Dues within 15 Days," the signature lines) stays exactly as Section 2.3 specifies — only the color treatment changes, not the structure.

**Generation:** ReportLab, pixel-matched to Section 2.3's layout with the color treatment above, **with one addition**: each line-item row includes a small product thumbnail (pulled from `inventory_items.cloudinary_image_url`) to the left of the Item Code column, so the printed/emailed invoice shows exactly which product(s) the customer bought, not just codes and text.

**Company watermark (new — every generated PDF, not just duplicates):** every invoice and purchase PDF carries a very light, diagonal **"OMEGA SCALES"** watermark across the page background — `#0F6B7C` at ~6–8% opacity (much fainter than the Duplicate watermark below, since this one is permanent branding/anti-forgery, not a status flag), positioned so it never interferes with reading the invoice content. This applies automatically via the shared `_render_bill_pdf` renderer (Section 16.2's refactor), so both invoice and purchase PDFs get it without separate implementation.

**Duplicate reprint (new — was referenced in Reports, Section 5.4.H, but never specified how it actually looks):** when Admin/Staff reprints an existing invoice from the Reports screen's Duplicate lookup, the generated PDF is identical to the original except for a diagonal **"DUPLICATE"** watermark (semi-transparent, `#0F6B7C` at ~15% opacity, rotated 45°, centered across the page) — so a reprinted copy is never visually indistinguishable from the original that was already sent, which matters if a customer disputes having received an invoice. This is layered on top of the fainter company watermark above, not a replacement for it.

**Party info box (new — was plain stacked text under "To M/S:"):** the customer block directly under "To M/S:" (Name, Phone, Address, per Section 2.3's layout) groups into a subtly bordered box instead of three loose lines of text — a thin `#D0D7DE` rule (the same neutral border already used for the item table and totals block above, not a new color) around the block, with a little internal padding so the text isn't flush against the border. No fill, no shadow — this is a grouping cue, not a new visual element, so it stays exactly as restrained as the rest of the invoice while making the "who this bill is for" block easier to pick out at a glance.

**Draft badge (new — a real gap: "INVOICE # : DRAFT" printed as plain text is easy to mistake for a real invoice number):** a `customer_ledgers` row that hasn't been finalized yet has no real sequential `invoice_no` (Section 5.3 only assigns one on finalize), and today that shows up in the PDF as plain text reading "DRAFT" where the number would otherwise be. Instead, whenever the invoice number is still `DRAFT`, it renders as a small bordered pill around the word — `#0F6B7C` border and text (the same accent already used for the invoice number itself, no new color), set apart from the "INVOICE #" label rather than sitting inline with it like a real number would. The point is that nobody holding a printed or emailed draft could mistake it for a finalized invoice; the moment the invoice is finalized and gets a real number, this pill disappears and the number prints exactly as it always has.
- `POST /api/v1/invoices/generate` → builds PDF → uploads to Cloudinary → returns URL
- `POST /api/v1/invoices/share-email` → Nodemailer/SMTP (Gmail App Password) → attaches/links PDF → **blocked until Human Gate approval if amount > threshold**
- **"Share on WhatsApp" button** (Invoice Builder, Screen 7): generates a `wa.me` click-to-chat link —
  ```
  https://wa.me/{customer_phone}?text={URL-encoded message with the Cloudinary PDF link}
  ```
  Clicking it opens WhatsApp (Web or App) with the message pre-filled — Admin/Staff reviews and presses Send themselves. **No API key, no Meta Business verification, no per-message cost.** This is a link the app constructs, not an automated dispatch — it goes through the same Human Gate rule as email: the button is disabled/hidden until the invoice is approved if it's above threshold, so WhatsApp can't be used to bypass the gate.
  - *(If the business later wants WhatsApp sent automatically with no human click, that upgrade path is the WhatsApp Business Cloud API via Meta — it requires business verification and costs per message. Not built now; noted here so the door isn't closed.)*

---

## 10. Adding Products — Two Ways (Manual + Bulk Excel)

Both options exist side by side, not one replacing the other:

1. **Manual, one at a time** — `POST /api/v1/inventory/create`. Admin fills a form (item code, name, unit, rate, stock, image upload) via the "+ Add New Item" button (Screen 3). **On save:** a success toast appears ("✓ P-16-S-A-MK added successfully") and the new item appears at the top of the Inventory table immediately, without a page refresh — so it's visually obvious the add worked. **On error** (e.g. duplicate item_code): an inline error under the Item Code field, not a silent failure — "This item code already exists." Good for adding a single new product as it arrives.
2. **Bulk, via Excel/CSV** — `POST /api/v1/inventory/bulk-upload`. FastAPI parses `.xlsx`/`.csv` with pandas + openpyxl, inserts or updates many rows in one pass — used for the initial catalog load and for periodic large updates. Supports **up to 1,500 products** in a single file (raised from the original 1,000 estimate to match the actual catalog size). Confirmation detail already specified in Screen 3's Bulk Upload flow (Section 6): exact imported/skipped counts, never a silent result.

**2b. Bulk images — folder + filename matching (new, since Excel cells can't carry actual image files).** The Bulk Upload modal (Section 6, Screen 3) gains a second, optional file input: **"Upload Product Images (optional)"**, accepting a `.zip` of image files. Matching rule: each image's filename (minus extension) must exactly equal an `item_code` from the same Excel batch — e.g. `P-16-S-A-MK.jpg` matches the row with `item_code = P-16-S-A-MK`. On the backend:
```
POST /api/v1/inventory/bulk-upload  (multipart: excel_file + optional images_zip)
```
Processing order: rows import first (as today), then for each successfully-imported/updated row, if a matching filename exists in the zip, that image uploads to Cloudinary and sets `cloudinary_image_url` — same as the manual single-item path (Section 4.3.1's eager-transformation rule, Section 11's capacity note, still apply). The Step 4 result screen adds a third count: **"1,244 imported, 1,180 images matched, 64 items had no matching image (fine, can be added later)."** An item without a matching image is not an error — it's simply saved without a thumbnail, exactly like the graceful "show nothing" behavior already specified for missing thumbnails elsewhere (Section 9.2).

**Testing both paths against each other (a good verification habit, not just a nice-to-have):** add the same test item manually first, note its `item_code`, then include a *different* item_code in a small test Excel file and upload it — confirm both appear correctly in the Inventory list with the right rate/stock/image, and that trying to manually add a duplicate of either one is rejected with the inline error above, not silently overwritten.

Full CRUD (either entry path lands in the same table):
- **CREATE**: single-item form (above) or bulk Excel (above)
- **READ**: search and view all products with server-side pagination and filters, up to 1,500 rows
- **UPDATE**: live price/rate updates and stock adjustment, either one item at a time or via a re-uploaded Excel (matched by `item_code`)
- **DELETE**: purge item record from Supabase and remove image asset from Cloudinary CDN (Admin only, one at a time — same no-bulk-delete harness rule as Section 5.2)

---

## 11. Tech Stack & Complete API Key List

| Layer | Choice |
|---|---|
| Frontend | Next.js 14+ (App Router) + Gravity UI (`@gravity-ui/uikit`, `@gravity-ui/table`, `@gravity-ui/charts`, `@gravity-ui/navigation`, `@gravity-ui/date-components`, `@gravity-ui/icons`, `@gravity-ui/aikit` for the Inbox — full breakdown in Section 4.3) |
| Backend | FastAPI (Python) — uses the official `supabase-py` package (`pip install supabase`) to talk to the Supabase database and Auth, not a raw `psycopg2`/SQLAlchemy connection string alone |
| Database | Supabase (Postgres) |
| Media/CDN | Cloudinary |
| Email (send) | Nodemailer (Gmail SMTP, App Password) |
| Email (read/reply) | Gmail API (OAuth 2.0) — new, needed for the Inbox feature (Section 9.1) |
| AI Reply Drafts | OpenAI API — new, needed for the Inbox's "Generate AI Reply" button |
| WhatsApp | None — free `wa.me` link, no API/account needed |
| Charts | FastAPI JSON (Section 8.1) → `@gravity-ui/charts` (pinned 1.57.2), rendered in the browser |
| Auth | Supabase Auth (JWT) |

### Every API key this system actually needs, and why:

*(One clarification worth stating plainly: Claude Code — the tool building this app — is separate from any AI key the finished app uses at runtime. This table is only about what the running app itself needs.)*

| # | Key / Credential | Used For | Where to get it | Cost |
|---|---|---|---|---|
| 1 | `DATABASE_URL` (Supabase Postgres connection string) + `NEXT_PUBLIC_SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_ANON_KEY` + `SUPABASE_SERVICE_ROLE_KEY` | All data storage — products, ledgers, invoices, users, inbox messages — plus authentication (Supabase Auth handles login sessions now, replacing the separate Better-Auth secret from earlier drafts) | supabase.com dashboard → Project Settings → API | Free tier available |
| 2 | `CLOUDINARY_CLOUD_NAME` + `CLOUDINARY_API_KEY` + `CLOUDINARY_API_SECRET` | Storing product images, invoice PDFs, chart PNGs | cloudinary.com dashboard | Free tier available |
| 3 | `GMAIL_USER` + `GMAIL_APP_PASSWORD` | **Sending** invoice emails (outbound only) | Google Account → Security → App Passwords (16-digit) | Free |
| 4 | `GMAIL_CLIENT_ID` + `GMAIL_CLIENT_SECRET` + `GMAIL_REFRESH_TOKEN` | **Reading** the inbox, marking read/unread, delete (Section 9.1) — this is a separate credential from #3 because reading requires OAuth scopes an App Password cannot grant | Google Cloud Console → enable Gmail API → OAuth consent screen → Credentials | Free (Gmail API has a generous free quota) |
| 5 | `OPENAI_API_KEY` | Powering the "Generate AI Reply" draft button in the Inbox, and the Scan Slip vision extraction (Section 5.4.K) | platform.openai.com → API keys | Pay-as-you-go, usually small for draft-length replies |
| 6 | *(none)* | WhatsApp sharing | `wa.me` links need no key at all | Free |

**Revised count: six items now — Supabase (Section 5's database move) actually reduced this by one, since Supabase Auth folds login/session handling into the same credential set as the database, replacing the separate `BETTER_AUTH_SECRET` from earlier drafts.** Item #4 (Gmail OAuth) is the more involved one to set up: it needs a Google Cloud project, the Gmail API enabled, and an OAuth consent screen — plan roughly 30–45 minutes for first-time setup, not just pasting a password like #3.

**Cloudinary capacity check (verified against current 2026 pricing):** the Free plan gives 25 credits/month (1 credit = 1 GB storage, 1 GB bandwidth, or 1,000 transformations, pooled together). 1,500 product images, compressed on upload to roughly 200–300 KB each, total under 0.5 GB of storage — well inside the free allowance. The real cost driver over time isn't the initial catalog, it's **bandwidth** (repeated views of images/PDFs by 8–10 daily users) and the growing pile of invoice PDFs and chart PNGs. To keep this comfortably free: **every image upload must run through Cloudinary's eager transformation** (auto-resize to a max width, e.g. 800px, and auto-format/quality via `f_auto,q_auto`) rather than storing the original camera-resolution file. If usage does grow past the free tier months from now, the next step is the Plus plan (~$99/month) — not a concern for launch, but worth knowing the upgrade path exists.

```env
DATABASE_URL="postgres://postgres:password@db.omega-scales-project.supabase.co:5432/postgres"
NEXT_PUBLIC_SUPABASE_URL="https://omega-scales-project.supabase.co"
NEXT_PUBLIC_SUPABASE_ANON_KEY="..."
SUPABASE_SERVICE_ROLE_KEY="..."
NEXT_PUBLIC_CLOUDINARY_CLOUD_NAME="omega-scales-cdn"
CLOUDINARY_API_KEY="..."
CLOUDINARY_API_SECRET="..."
GMAIL_USER="omegascales.official@gmail.com"
GMAIL_APP_PASSWORD="..."
GMAIL_CLIENT_ID="..."
GMAIL_CLIENT_SECRET="..."
GMAIL_REFRESH_TOKEN="..."
OPENAI_API_KEY="..."
FASTAPI_BACKEND_URL="http://127.0.0.1:8000"
AGENT_HUMAN_GATE_THRESHOLD="100000.00"
```

---

## 12. Testing Strategy & Acceptance Criteria

### 12.0 Testing Strategy (new — the checklist below is *what* to verify; this is *how*)

Code that "looks done" and code that is *proven* done are different things — this section exists so Claude Code writes real, runnable tests, not just working features. Four layers, each catching a different kind of mistake:

1. **Unit tests (Pytest, backend logic)** — the parts of this system that must be mathematically exact, tested in isolation with no database or network involved:
   - `total_amount == rate * qty − discount_amount` (Section 2.3/5.0)
   - `current_balance == previous_balance + sale_amount − receiving_amount` for every row type (Section 5.0's formula)
   - Invoice auto-numbering never repeats or skips (Section 5.3)
   - `due_date` and `overdue` status calculation (Section 5.3)
   - These are the same formulas the harness's `PostToolUse` hook re-checks at write-time (Section 7.3) — the unit tests prove the formula is right in the first place; the hook proves every real write obeys it.

2. **Integration tests (Pytest + a test database, or FastAPI's `TestClient`)** — API endpoints against a real (test) Postgres instance:
   - `POST /api/v1/invoices/generate` → the Human Gate correctly blocks dispatch above Rs. 100,000, and correctly allows it below
   - Bulk Excel upload with a deliberately malformed test file → correct import/skip counts, correct error report
   - Recording a payment → balance updates immediately, no Human Gate triggered
   - Login Approval flow → a Staff login creates a pending request; an Admin's approval unblocks the waiting session
   - Soft-delete behavior (Section 5.2) → a "deleted" row is hidden from normal queries but still exists in the database

3. **End-to-end tests (Playwright)** — a real browser driving the actual UI, covering the flows that matter most because they involve a person:
   - Login → (Staff) Waiting for Approval → Admin approves from a second session → Staff lands in the app
   - Create a draft invoice → finalize it → Rs. 184,500 (Section 2.3's real test case) correctly routes to the Human Gate → Admin approves → PDF generates and the Share on WhatsApp/Email buttons unlock
   - Bulk upload a test Excel file → preview → confirm → see the result summary
   - Dark/Light theme toggle → visual check that both render correctly (a screenshot-diff test is a reasonable option here, not required)

4. **The harness's own tests (Section 7.3's hooks, already specified)** — these run on every write in production, not just in a CI pipeline; think of them as the fourth layer that keeps running after the first three have already passed once.

**Where tests live and when they run:** standard project layout (`tests/unit/`, `tests/integration/`, `tests/e2e/`), run via `pytest` and `playwright test` respectively. Wire them into the loop from Section 7.1 the same way the course this project is built on teaches it: `/goal` in Claude Code should treat "all four layers pass" as part of its stopping condition, not just "the feature runs once when I tried it." A feature isn't part of Section 12's checklist below until its test exists and passes — the checklist is the test plan, not a separate wish list.

### 12.1 Acceptance Criteria (what "done" means, provable by a command — not an opinion)

- [ ] `total_amount == rate * qty` holds for every invoice row in the test set
- [ ] `current_balance` recomputes correctly across a full ledger replay (use the United Scale Ijtibah data from Section 2.2 as the golden test case)
- [ ] Invoice #2127 (Rs. 184,500) is blocked from Gmail dispatch until Admin approves via the Human Gate Drawer
- [ ] An invoice under Rs. 100,000 dispatches without requiring approval
- [ ] Bulk Excel upload of 1,500 rows completes and is queryable with pagination under 2s
- [ ] Dark and Light themes render from the same components with only token values differing
- [ ] Generated invoice PDF visually matches Section 2.3 layout
- [ ] Every invoice line item (on-screen builder, preview, and final PDF) shows the product's thumbnail image next to its item code/name
- [ ] Settings page exists with an Admin-only, editable Human Gate threshold field (default Rs. 100,000) that actually changes gate behavior when saved
- [ ] Finalized invoices/ledger entries are never auto-deleted; deleting requires an explicit Admin action on one entry at a time, recorded as a soft delete (`deleted_by`, `deleted_at`)
- [ ] Ledger and Invoices list screens default to sorted-by-date, newest first
- [ ] A bulk `DELETE`/`TRUNCATE` attempt on `customer_ledgers` is blocked by the harness deny rule, even inside an agent loop
- [ ] A draft invoice can be freely edited; once finalized (dispatched or Human Gate–approved), a direct edit attempt is rejected and only a Correction Entry is offered instead
- [ ] Clicking "Edit" on any invoice always works from the person's point of view — for a draft it opens direct editing, for a finalized invoice it opens "Fix This Invoice" and requires a reason before submitting, but both are reached from the exact same button so nobody has to know or remember which invoices are locked
- [ ] A correction on a finalized invoice never modifies the original row — the original invoice and its PDF are unchanged, and the correction appears as a new, clearly-linked entry in the party's ledger
- [ ] Every screen listed in Section 3.2's Route Map is reachable at its exact stated URL, and every Admin-only route redirects Staff to `/dashboard` if accessed directly
- [ ] Scan Slip, Purchase Builder, Expenses, Reports, Bank Accounts, and Party Detail are all built from Gravity UI components per Section 4.3.1 — none of them is raw unstyled HTML bolted onto an otherwise-consistent design system
- [ ] Opening any party's Ledger shows a small balance-trend chart at the top, sourced from the same live ledger rows as the table below it — never a separately cached or stale dataset
- [ ] An invoice can contain multiple line items (different products, different quantities each), matching the real Sale form's "Add To List" behavior — `total_amount` on the invoice equals the sum of all its line items minus the overall discount
- [ ] Recording a payment (Cash/Cheque/Online/Bank Transfer) against a customer immediately updates their `current_balance`, visible in the same session with no delay
- [ ] A recorded payment never triggers the Human Gate (it reduces debt, not a new charge), even if the amount exceeds Rs. 100,000
- [ ] "Share on WhatsApp" opens a pre-filled `wa.me` link with the invoice PDF URL, and is disabled/hidden for any invoice still pending Human Gate approval
- [ ] A single product can be added via the manual form AND a batch of up to 1,500 products can be added via Excel upload — both paths land in the same `inventory_items` table
- [ ] The Bulk Upload modal shows a preview and validation summary before committing — no Excel upload silently succeeds or fails without the Admin seeing exact counts and a downloadable error report for skipped rows
- [ ] Login shows an inline error (not a browser alert) on wrong credentials, and redirects Admin to Dashboard and Staff to Inventory List on success
- [ ] Customers exist as their own records (not free-typed text) — the same customer name cannot accidentally create two separate ledgers due to a typo
- [ ] Admin can create a new Staff account from the User Management screen; the new user receives an emailed temporary password and can log in
- [ ] Deactivating a user blocks their login without deleting their historical actions (soft-disable, matching Section 5.2's retention philosophy)
- [ ] When any item's stock drops to or below its `min_threshold`, the Dashboard's Low Stock count reflects it immediately and it appears in the next daily digest email
- [ ] The daily low-stock digest sends every day at its scheduled time regardless of whether any items are below threshold (an empty day says so explicitly — it never just stays silent)
- [ ] Forgot Password returns the same message whether or not the email exists, and a valid reset link expires after 1 hour
- [ ] The Party Ledger and Analytics screens each have a working Export (Excel and PDF) that a person outside the app (e.g. an accountant) can open directly
- [ ] A discount entered on an invoice is stored and reflected correctly in `total_amount` and the running balance chain
- [ ] All six Analytics charts (Section 8) query the live `inventory_items` and `customer_ledgers` tables directly — none reads from a separate cached/duplicated reporting table, so a change in Inventory or a new payment shows up on Analytics without a manual sync step
- [ ] Login, Human Gate Drawer, Party Ledger View, Party Detail, Expenses, Login Approvals, and Dashboard are fully usable on a phone-sized screen (<640px) — an Admin can approve a held invoice or a pending login from their phone without needing a desktop
- [ ] Scan Slip works correctly on a mobile browser specifically, using the device camera, even though the rest of Invoice Builder is a simplified (Tier 2) mobile experience
- [ ] Dashboard shows all four KPI cards (Total Sales, Outstanding Receivables, Low Stock Alerts, Pending Approvals), and clicking Pending Approvals navigates to the Human Gate Drawer
- [ ] The Inbox only shows emails matched to a known customer or an existing invoice thread — an unrelated email never appears there
- [ ] "Generate AI Reply" produces a draft in the compose box but never sends automatically — a human must press Send
- [ ] A reply can attach/link an existing invoice's PDF by searching its invoice number, without regenerating the PDF
- [ ] Deleting an inbox message soft-deletes it (moves to Gmail Trash via the API), never a hard destroy
- [ ] No signup route exists anywhere in the app or API — attempting to create an account without an authenticated Admin session returns a 403, not a form
- [ ] Five failed login attempts locks that account for 15 minutes; Admin can manually unlock it from User Management before the timer expires
- [ ] An Admin's own login never requires approval; a Staff login always creates a pending request and does not grant access until an Admin approves it
- [ ] The moment any Admin approves a pending Staff login, that Staff member's waiting screen proceeds into the app automatically, without them re-entering credentials
- [ ] A pending login request left unanswered for 10 minutes auto-resolves to "expired," and the Staff member can attempt to log in again
- [ ] The Login Approvals screen shows a full, searchable history of past requests, and an Admin can delete (soft) or annotate any entry
- [ ] Every route change shows a top progress-bar loader, and it never leaves a blank white/empty screen while the next page's data loads
- [ ] Numbers in the Party Ledger's Balance column use tabular figures (Inter, `tabular-nums`) so digits align vertically down the column
- [ ] Invoice numbers are system-generated sequentially on finalization, never typed manually, and a duplicate `invoice_no` is rejected by the database's UNIQUE constraint
- [ ] A finalized invoice's `due_date` defaults to 15 days after its transaction date, and its status automatically flips to `overdue` the day after that date passes if it's still unpaid or partial
- [ ] The Invoices screen lists every invoice across all customers, with working filter tabs for Unpaid / Overdue / Pending Approval
- [ ] An abandoned draft invoice never consumes an invoice number — the sequence has no gap where a draft was discarded
- [ ] Manually adding an item shows a success toast and the item appears at the top of the Inventory table immediately, with no page refresh needed
- [ ] Manually adding a duplicate `item_code` (one already used, whether added manually or via Excel) is rejected with an inline error, never silently overwritten or duplicated
- [ ] Uploading a `.zip` of images alongside a bulk Excel file correctly matches each image to its item by filename == item_code, and items with no matching image save successfully without one (not an error)
- [ ] The Inventory, Invoices, Party Ledger, and Login Approvals tables use `@gravity-ui/table` (not the basic uikit Table), so sorting and column behavior stay usable at 1,500 rows
- [ ] The Invoices screen shows a stats strip (Total Invoices, Paid, Unpaid, Overdue counts) that stays accurate as invoices are created, paid, or become overdue
- [ ] Every date field in the app (Sale, Purchase, Expense, due date, filters) uses a calendar picker component — no free-text date entry exists anywhere
- [ ] The Party Ledger screen works identically for a customer (they owe us) and a supplier (we owe them) — same balance math, same UI, correctly reflecting the direction of the debt for either
- [ ] A Purchase correctly increases `inventory_items.quantity_in_stock`, the reverse of a Sale's decrease
- [ ] An Expense entry with no linked party (e.g. a utility bill) is still valid and appears in the Expenses list correctly
- [ ] Clicking a party's name opens their Party Detail page (profile summary), which is a distinct view from their full Ledger, not the same screen
- [ ] The Rate field on Invoice/Purchase Builder can always be manually edited, and a party with a stored negotiated rate for an item pre-fills that rate automatically while still allowing further manual changes
- [ ] Scan Slip extracts items from an uploaded photo into a review list — nothing is added to the invoice until Admin/Staff confirms the matched items, and any item the AI couldn't confidently match is flagged for manual selection rather than guessed silently
- [ ] Every success/error state specified across this document (item added, payment recorded, wrong login, duplicate code, bulk upload result) renders through the same `Alert`/`Toaster` components — not ad hoc `alert()` calls or inconsistent one-off styling

**This document is the locked reference for the build.** Any change to theme, screens, schema, or rules must be made here first, then re-fed to Claude Code CLI and/or Google Stitch — not made ad hoc in either tool.

---

## 13. Build Sequence (Phased Implementation Order — read this before starting any Claude Code session)

### 13.0 Project Structure — Two Separate Folders, Backend First

**This is not one project built top-to-bottom — it is two separate folders, built in sequence, not in parallel:**

- **`omega-backend/`** — FastAPI + the database schema + the harness + all business logic (Sections 5, 7, 9, 10). Built and fully tested **first**, entirely on its own, with no frontend involved. Test it directly against its API endpoints (Postman, `curl`, or the Pytest/integration layers from Section 12.0) — the backend must work correctly by itself before a single frontend screen is built.
- **`omega-frontend/`** — Next.js + Gravity UI. Built **only after** the backend is complete and its own tests (Phase 1–3's exit tests below) are passing. This folder starts from the **Stitch-exported design template** (Section 4, Section 6's screens) — the frontend is not designed from scratch in code; it is built to match the already-approved Stitch/Figma output, then wired up to call the already-tested backend's API.

**Why this order, explicitly:** a frontend built against a backend that isn't finished yet means constant rework — API shapes change, and every frontend screen touching that endpoint breaks. Building and proving the backend first means the frontend is built once, against a stable, tested contract, using the visual design that's already been approved separately. Do not start `omega-frontend/` until the backend's Phase 1–3 exit tests (below) all pass.

Do not ask Claude Code to build everything at once. This PRD describes 18 screens, a full harness, and six chart types — attempted in one pass, that is exactly the kind of long, unattended run that gets worse over time (context fills with half-finished pieces, small mistakes compound). Build and test in this order, one phase fully passing before the next begins:

**Phase 1 — Foundation (Database + Inventory CRUD)**
- Setup: `pip install fastapi uvicorn supabase python-dotenv` — the official `supabase-py` client (Section 11), not a bare Postgres driver; it handles both the database queries and Auth token verification through one client (`create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)` for backend operations, verifying the JWT from the frontend's Supabase Auth session on protected routes)
- Section 5: full schema — `parties`, `users`, `inventory_items`, `units`, `categories_1`, `categories_2`, `particulars`, `bank_accounts`, in that order (later tables reference earlier ones via foreign key)
- Section 7.2: the harness `settings.json` deny/allow rules — set up *before* any other code, so every following phase is already protected
- Section 10: Inventory CRUD (manual add + bulk Excel), with the success/error toasts from Section 10's confirmation spec
- **Exit test before Phase 2:** unit tests for schema constraints pass, bulk upload of a test Excel file works with correct import/skip counts (Section 12.0, layer 1–2)

**Phase 2 — Invoice + Ledger + Purchase + Expenses Logic (the most sensitive part — math and money)**
- Section 2.2/5.0: the running-balance formula, for both `sale` and `receiving` row types
- Section 5.1: draft-vs-finalized invoice lock, Correction Entry
- Section 5.3: auto invoice numbering, due date, overdue status
- Section 5.4.B/C: Purchase module (stock in) and Expenses module — same rigor as Sale, since both move money
- Section 7.3/7.4: the harness hooks that re-validate the math on every write, and the Human Gate itself
- **Exit test before Phase 3:** the golden test case from Section 2.2 (United Scale Ijtibah's full ledger) replays correctly; Invoice #2127 (Rs. 184,500, Section 2.3) is proven to trigger the Human Gate and a sub-threshold invoice is proven not to; a test Purchase correctly increases stock (Section 12.0, layer 1–3)

**Phase 3 — Everything else backend-side**
- Section 3.1: Login Approval Gate
- Section 9: PDF generation, Email dispatch, WhatsApp link, Gmail Inbox (Section 9.1) with AI reply
- Section 7.1's second heartbeat: the daily low-stock digest
- Section 8: the six Analytics queries
- **Exit test before Phase 4:** all remaining integration tests from Section 12.0 pass

**Phase 4 — Frontend (all 18 screens, new folder: `omega-frontend/`)**
- **Start a fresh folder here** — do not build frontend code inside `omega-backend/`. Initialize a new Next.js project in `omega-frontend/`.
- Build against Section 6's screen specs and Section 4's design tokens — and against the **Stitch-exported design** (Figma frames or code export), which will be provided at this point, so the UI matches what was already approved visually rather than Claude Code guessing a layout independently
- Section 4.3's Gravity UI component mapping, Section 4.5's mobile tiers, Section 4.6's loading states
- Connect to `omega-backend/`'s already-tested API — no backend logic gets written or duplicated here; this folder only calls the endpoints Phase 1–3 already proved correct
- **Exit test before Phase 5:** the Playwright end-to-end flows from Section 12.0 layer 3 pass

**Phase 5 — Deploy**
- Section 14 (below): Hostinger for frontend, Render for backend — only after every phase above has passed its own tests

**The rule this sequence exists to enforce:** each phase's exit test is a real stopping condition for that phase's `/goal` run — not a suggestion. If asking Claude Code to continue past a phase, reference this section by name ("start Phase 2") instead of re-describing the order in a fresh prompt each time.

---

## 14. Deployment (yes, this is required — the app isn't "done" running only on a laptop)

Section 5.2's retention discipline and Section 3.1's live login-approval both assume the app is reachable by everyone, all the time — not just when someone's Claude Code session happens to be running locally. **Deployment is not optional polish; the Login Approval Gate and Human Gate literally cannot do their job if the app isn't live.**

**Before deploying:** all four test layers from Section 12.0 must pass locally first. Deployment moves *where* the code runs, exactly like the runtime-decision principle this project's methodology is built on (Loop Engineering course) — it is never a substitute for having actually tested the code. A bug shipped to Hostinger/Render is the same bug, just harder to fix quickly.

### 14.1 Frontend — Hostinger

Hostinger has two different ways to run this, and they are not the same thing:

- **Hostinger Node.js Hosting** (recommended for this project) — a managed plan (starting around $3.99/month) that runs the actual Next.js server: SSR, ISR, and API routes all work as built, deployed via a GitHub connection with automatic rebuilds on push. This is the right fit here because the app genuinely needs server features (session cookies, the Login Approval polling, server components reading live data) — it is not a static site.
- **Hostinger shared hosting with static export** — cheaper, but requires setting `output: 'export'` in `next.config.js`, which **turns off SSR, API routes, and dynamic session handling** — incompatible with almost everything this PRD specifies (Login Approval Gate, Human Gate, live balance updates). **Do not use this option for this project.**
- **Hostinger KVM VPS** — full root access, self-managed (you patch the OS, configure Nginx/PM2, handle SSL yourself). Capable of running this app, but is more setup and ongoing responsibility than the Node.js Hosting plan for no real benefit at this scale — see 13.3.

### 14.2 Backend — Render

FastAPI deploys cleanly to Render as a standard Python web service: connect the GitHub repo, Render detects `requirements.txt`, builds, and serves it, with environment variables (Section 11's `.env` list) set in Render's dashboard rather than committed to the repo. A free-tier or low-cost paid instance is enough for 8–10 internal users; the one caveat worth knowing is that Render's free tier sleeps after inactivity (a cold-start delay on the next request) — for an internal tool used during business hours, a small always-on paid tier avoids that delay and is inexpensive at this scale.

### 14.3 Why not KVM — the direct answer

KVM is expensive **relative to what this system needs**, not expensive in absolute terms — and the cost isn't only the monthly bill:

- **Money:** Hostinger's managed Node.js hosting and Render's managed backend both start under $10–15/month combined. A KVM VPS capable of comfortably running Next.js starts around $6.49/month on promotional pricing but renews higher, and that's before backups (daily backups are a paid add-on) — so the gap is smaller than it first looks, but it's still there.
- **Time and risk, the bigger cost:** a KVM VPS is **self-managed** — you (or whoever maintains this system) are responsible for OS security patches, Node.js version upgrades, Nginx configuration, SSL certificate renewal, and uptime monitoring. Managed hosting (Node.js Hosting + Render) hands all of that to the platform. For a small business running one internal tool, that operational burden is real money too, just not on the invoice.
- **When KVM would make sense instead:** if this system later needs to run things a managed platform can't easily host (a custom background worker outside the loop/harness pattern, unusual port requirements, or full infrastructure control for compliance reasons). None of that applies today. **Recommendation: managed hosting now (Hostinger Node.js + Render), revisit KVM only if a specific need for root access actually shows up.**

### 14.4 What connects to what

```
Hostinger (Node.js Hosting)  →  Next.js frontend (SSR, sessions, UI)
        │
        ├──→  Render  →  FastAPI backend (invoice logic, harness, PDF generation)
        ├──→  Supabase  →  Postgres database + Auth (already cloud-hosted, Section 11)
        ├──→  Cloudinary  →  images, PDFs, charts (already cloud-hosted)
        └──→  Gmail API / OpenAI / WhatsApp links  →  as specified in Sections 9 and 11
```

Every piece here is already a managed cloud service (Supabase, Cloudinary) except the two pieces this section just placed: the Next.js app on Hostinger, and the FastAPI app on Render. Nothing in this system needs a server you personally patch and reboot.

---

## 15. Next Steps

1. **Claude Code CLI**: `mkdir omega-backend && cd omega-backend` → `claude` → follow Section 13's phased build order, starting with Phase 1 (Foundation) through Phase 3 (rest of backend) — `/goal` each phase's own exit test as its stopping condition, not the whole PRD at once. Do not touch the frontend yet.
2. **Figma AI tool**: feed Sections 4 and 6 (tokens + screens) to generate the dual-theme template — this can happen in parallel with backend work, since it doesn't depend on the backend being finished.
3. **Once the backend passes its Phase 1–3 exit tests**, start `omega-frontend/` (Phase 4) — a fresh Next.js project built against the Stitch/Figma output and calling the now-tested backend API.
3. **Deployment**: once the acceptance criteria pass locally, follow Section 14 — Hostinger Node.js Hosting for the frontend, Render for the backend.
4. Keep this file as the single source of truth — both tools read from it; neither should diverge from it without updating this document first (the "repo holds the truth" rule).

---

## 16. Real-World Additions (requested after live use review — Rizwan Bhai's operational feedback)

These six items came from actually thinking through daily operation, not from the original spec — each is a genuine gap, not a nice-to-have.

**16.1 Credit Limit Enforcement (was display-only, now actually blocks).** Currently `credit_limit` is shown but never checked. New rule: when finalizing a `sale`, if `current_balance` (after this invoice) would exceed the party's `credit_limit` (and `credit_limit` is not null), block finalization with a clear message — *"This exceeds [Party]'s credit limit of Rs. X by Rs. Y."* Admin can override with a one-click confirm ("Approve anyway" — logged, per Section 16.4 below); Staff cannot override, only Admin.

**16.2 Stock Adjustment (physical count reconciliation).** New `stock_adjustments` table and a small action (from Item Detail, Admin-only): enter the *actual counted* quantity, a reason (dropdown: Damaged, Lost/Theft, Count Correction, Other + note), system computes the delta and writes both the adjustment record and updates `inventory_items.quantity_in_stock` in one transaction. Every adjustment is permanent (Section 5.2's retention rule) — never edited, only further adjustments if a mistake is made correcting a mistake.
```sql
CREATE TABLE stock_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_code VARCHAR(100) REFERENCES inventory_items(item_code) NOT NULL,
    previous_qty INT NOT NULL,
    counted_qty INT NOT NULL,
    delta INT NOT NULL,              -- counted_qty - previous_qty, can be negative
    reason VARCHAR(50) NOT NULL,     -- 'damaged' | 'lost' | 'count_correction' | 'other'
    note TEXT,
    adjusted_by UUID REFERENCES users(id) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

**16.3 Sales Return.** Distinct from a Correction Entry (which fixes a data-entry mistake) — a Return is a real event: the customer physically brings goods back. New `sales_returns` table, linked to the original invoice, which (a) increases `inventory_items.quantity_in_stock` back, and (b) creates a Credit-type entry on `customer_ledgers` reducing the party's balance — same "signed delta on the chain" pattern as a Correction Entry (Section 17.2), but semantically a Return, not a fix. A small "Return Items" action on the Invoice detail page, Admin/Staff both, restricted to already-finalized invoices.
```sql
CREATE TABLE sales_returns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    original_invoice_id UUID REFERENCES customer_ledgers(id) NOT NULL,
    item_code VARCHAR(100) REFERENCES inventory_items(item_code) NOT NULL,
    qty_returned INT NOT NULL,
    reason TEXT,
    ledger_credit_id UUID REFERENCES customer_ledgers(id),  -- the resulting Credit row
    processed_by UUID REFERENCES users(id) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

**16.4 Activity Log (who did what).** A new, simple, append-only `activity_log` table, written to (not read from) by every sensitive write already happening elsewhere in this system — rate changes, deactivations, correction entries, credit-limit overrides, stock adjustments, deletions. A new **Activity Log screen** (Admin only, `/settings/activity-log`, linked from Settings): searchable/filterable table — Timestamp, User, Action, Target (e.g. "Changed rate on P-16-S-A-MK from Rs. 12,000 to Rs. 12,300"), read-only, never edited or deleted (this is the one table where even Admin cannot soft-delete rows — an audit log that could be erased isn't an audit log).
```sql
CREATE TABLE activity_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) NOT NULL,
    action VARCHAR(100) NOT NULL,      -- e.g. 'rate_change', 'user_deactivated', 'credit_override'
    target_description TEXT NOT NULL,  -- human-readable, e.g. the rate-change example above
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

**16.5 Delivery Challan (delivery note, separate from the invoice).** A physical-goods business often invoices and delivers at different times. New `delivery_challans` table + a "Generate Delivery Challan" action on a finalized invoice — produces a simpler PDF (no pricing/totals, just Item, Qty, delivered-to address, and Receiver's Signature line) via the shared `_render_bill_pdf` renderer's sibling mode. Can be generated once per invoice, marked with a delivery date once actually delivered.
```sql
CREATE TABLE delivery_challans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id UUID REFERENCES customer_ledgers(id) NOT NULL,
    challan_no VARCHAR(50) UNIQUE,     -- own sequential numbering, same rule as Section 5.3
    delivered_at DATE,                  -- null until actually delivered
    pdf_cloudinary_url TEXT,
    created_by UUID REFERENCES users(id) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

**16.6 Payment Correction (the same "Edit" discipline as invoices, now applied to Receiving rows too — Rizwan Bhai's specific ask).** Section 5.1 built a unified "Edit" button for invoices (draft = direct edit, finalized = "Fix This Invoice" correction). **Receiving (payment) rows never got the same treatment** — if Cash/Cheque/Online amount, date, or party was entered wrong on a payment that's already been recorded (and possibly already reflected in a shared PDF/statement), there was no fix path at all. Same pattern, applied here: a payment row also gets an **"Edit"** button on the Party Ledger. Since a `receiving` row has no draft/finalized state (it's immediate), every correction goes through a **"Fix This Payment"** form (reason required, corrected amount/method/date) that creates a signed-delta correction row referencing the original — the original payment record is never altered, exactly matching Section 5.1's principle. This closes the exact gap Rizwan Bhai flagged: a mistake found *after* a slip/statement was already shared with someone still has a safe, audited way to get fixed.

```sql
ALTER TABLE customer_ledgers ADD COLUMN payment_correction_of UUID REFERENCES customer_ledgers(id);
ALTER TABLE customer_ledgers ADD COLUMN payment_correction_reason TEXT;
-- Mirrors invoice_state's correction_of/correction_reason pair from Section 5.1,
-- applied to 'receiving' rows instead of 'sale' rows.
```

## 17. As-Built Notes (real deviations found during the actual Phase 3/4 build — read this before assuming the earlier sections are 100% how the system behaves today)

This section exists because a spec written before building and the system after building are never word-for-word identical — real construction always surfaces a few honest tradeoffs. Rather than silently editing earlier sections to pretend they were right from the start, they're logged here so this document stays trustworthy.

**17.1 Auth is custom JWT, not literally "Supabase Auth."** Section 3 originally called for Supabase's own Auth product. The actual backend issues its own JWT in an HTTP-only cookie instead (rationale logged in `omega-backend/progress.md`). Functionally this delivers the same thing Section 3 needs (secure sessions, RBAC enforcement on every endpoint) — but if anyone goes looking for session activity in Supabase's own Auth dashboard, it won't be there; check the backend's own `users`/session logic instead.

**17.2 One invoice = one header + many line items (the multi-item fix).** Earlier drafts of Section 5 modeled `customer_ledgers` as one row per item, which would have made multi-item invoices impossible — a real bug caught mid-build (a business with an "Add To List" pattern on paper invoices clearly needs this). Fixed schema: `customer_ledgers` (header: party, invoice_no, discount, totals) + a separate `invoice_line_items` table (one row per product on that invoice), and the same pattern for `purchases`/`purchase_line_items`. Section 5's SQL blocks reflect this corrected shape.

**17.3 Two independent balances for a party who is both customer and supplier.** Purchases carry their own `previous_balance`/`current_balance`, separate from `customer_ledgers`. A party marked `party_type = 'both'` currently has two unrelated balance figures (what they owe us, what we owe them) rather than one netted number. Not wrong, just worth knowing before Party Detail (Section 5.4.I) is read as showing a single unified figure — it currently shows two.

**17.4 Low Price started as a flat toggle, now being upgraded.** The first Invoice Builder pass shipped "Low Price" as a generic "Catalog Rate / 10% off" dropdown rather than reading a real per-party negotiated rate. The `party_item_rates` table (Section 5.4.J) is being added now to make this reflect an actual stored negotiated rate per party+item, with the flat 10% option kept as a fallback when no negotiated rate exists.

**17.5 Live PDF preview and Scan Slip were sequenced after the core invoice flow, not skipped.** The first working Invoice Builder used a numeric summary panel instead of a rendered PDF preview, and shipped without Scan Slip's AI extraction — both were deliberately deferred so the core Human-Gate-driven invoice flow could be proven end-to-end first (and it was: a real Rs. 184,500 test invoice correctly triggered the gate). Both are being built next, in that order, per Section 5.4.K/9.2.

**17.6 A ledger `Description` doesn't currently show the payment method inline** (e.g. the real paper ledger's "Receiving - 1167 Cheque" style). The `particular_id` foreign key exists and is stored correctly, but the Party Ledger UI's description text doesn't currently interpolate the particular's name into the row label. Small, non-blocking, worth fixing when convenient.

**17.7 A real intermittent-connection bug was found and fixed (not a design gap, but worth remembering it existed).** `supabase-py`'s default Postgres client opened HTTP/2 connections that occasionally got torn down server-side while still marked reusable, surfacing as random 500s on any authenticated request — not just one screen. Fixed by forcing HTTP/1.1 in `app/database.py`. If a future change to that file ever reintroduces HTTP/2 defaults, this class of bug can return.
