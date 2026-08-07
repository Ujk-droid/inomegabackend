from supabase import Client

from app.models.party import NegotiatedRateOut, PartyBalanceOut, PartyCreate, PartyOut
from app.services.inventory_service import ItemNotFoundError, fetch_item_by_code


class DuplicatePartyNameError(Exception):
    pass


class PartyNotFoundError(Exception):
    pass


def row_to_out(row: dict) -> PartyOut:
    return PartyOut(
        id=row["id"],
        party_name=row["party_name"],
        party_type=row["party_type"],
        phone=row.get("phone"),
        email=row.get("email"),
        address=row.get("address"),
        credit_limit=float(row["credit_limit"]) if row.get("credit_limit") is not None else None,
        created_at=row.get("created_at"),
    )


def create_party(supabase: Client, party: PartyCreate) -> PartyOut:
    existing = supabase.table("parties").select("id").eq("party_name", party.party_name).limit(1).execute()
    if existing.data:
        raise DuplicatePartyNameError(f"Party '{party.party_name}' already exists")

    payload = party.model_dump(exclude_none=True)
    resp = supabase.table("parties").insert(payload).execute()
    return row_to_out(resp.data[0])


def get_party(supabase: Client, party_id: str) -> dict | None:
    resp = supabase.table("parties").select("*").eq("id", party_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def find_party_by_email(supabase: Client, email: str) -> dict | None:
    """Section 9.1's Inbox matching rule (a): 'the party's registered email in
    parties.email replying to a thread the system itself started.'"""
    resp = supabase.table("parties").select("*").eq("email", email).limit(1).execute()
    return resp.data[0] if resp.data else None


def require_party(supabase: Client, party_id: str) -> dict:
    party = get_party(supabase, party_id)
    if party is None:
        raise PartyNotFoundError(f"Party '{party_id}' not found")
    return party


def list_parties(supabase: Client) -> list[PartyOut]:
    resp = supabase.table("parties").select("*").order("party_name", desc=False).execute()
    return [row_to_out(row) for row in resp.data]


def get_latest_party_balance(supabase: Client, party_id: str) -> float:
    """Section 5.4.A: 'Current Balance ... must display live on the Sale/Purchase
    forms the moment a party is selected.' Latest non-deleted customer_ledgers
    row for this party, by append (created_at) order — 0.00 if the party has no
    ledger history yet.

    Deliberately created_at, not transaction_date: current_balance is a strict
    running prefix-sum over rows in the order they were actually inserted — each
    new row's previous_balance must equal the immediately-preceding INSERT's
    current_balance, or the chain breaks (a row's stored balance silently stops
    reflecting every delta that came before it). Anchoring on transaction_date
    instead would let a backdated entry's delta get skipped by a later insert
    whose date sorts earlier — e.g. insert Sale (dated today, balance 1000), then
    a backdated Payment (dated yesterday, -400, balance 600 — correctly netting
    both prior entries); the *next* new transaction must anchor on 600 (the
    payment, last inserted) or it silently loses track of that $400 payment ever
    happening. Since finalized rows are immutable (Section 5.1) and never
    recomputed once inserted, insertion order is the only order the running
    total can self-consistently follow. transaction_date still drives *display*
    order (list_party_ledger below, Section 5.2) — just not this balance math."""
    resp = (
        supabase.table("customer_ledgers")
        .select("current_balance")
        .eq("party_id", party_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return 0.0
    return float(resp.data[0]["current_balance"])


def get_lifetime_business(supabase: Client, party_id: str) -> float:
    """Section 5.4.I's Party Detail stat tile: 'total lifetime business done
    (sum of all sale/purchase amounts)' — sales owed to us (customer_ledgers,
    txn_type='sale' only — a 'receiving' row is a payment, not new business)
    plus everything ever bought from them (purchases), regardless of the
    party's type. A party_type='both' naturally sums both sides; a
    customer-only or supplier-only party just has zero on the side that
    never applies."""
    sales_resp = (
        supabase.table("customer_ledgers")
        .select("total_amount")
        .eq("party_id", party_id)
        .eq("txn_type", "sale")
        .eq("invoice_state", "finalized")  # a draft isn't "done" yet — same filter analytics_service uses
        .is_("deleted_at", "null")
        .execute()
    )
    total_sales = sum(float(row["total_amount"]) for row in sales_resp.data)

    purchases_resp = supabase.table("purchases").select("total_amount").eq("party_id", party_id).execute()
    total_purchases = sum(float(row["total_amount"]) for row in purchases_resp.data)

    return total_sales + total_purchases


def get_party_balance(supabase: Client, party_id: str) -> PartyBalanceOut:
    party = require_party(supabase, party_id)
    balance = get_latest_party_balance(supabase, party_id)
    return PartyBalanceOut(
        party_id=party_id,
        current_balance=balance,
        credit_limit=float(party["credit_limit"]) if party.get("credit_limit") is not None else None,
        lifetime_business=get_lifetime_business(supabase, party_id),
    )


# ── Negotiated rates / "Low Price" (Section 5.4.J) ──────────────────────────


def get_negotiated_rate(supabase: Client, party_id: str, item_code: str) -> NegotiatedRateOut:
    """None (not a 404) when this party simply has no negotiated rate for this
    item yet — that's the normal case for most party/item pairs, not an error."""
    resp = (
        supabase.table("party_item_rates")
        .select("negotiated_rate")
        .eq("party_id", party_id)
        .eq("item_code", item_code)
        .limit(1)
        .execute()
    )
    rate = float(resp.data[0]["negotiated_rate"]) if resp.data else None
    return NegotiatedRateOut(party_id=party_id, item_code=item_code, negotiated_rate=rate)


def set_negotiated_rate(supabase: Client, party_id: str, item_code: str, negotiated_rate: float) -> NegotiatedRateOut:
    """Upsert on the (party_id, item_code) unique pair — setting a rate twice
    updates it rather than erroring or creating a duplicate row."""
    require_party(supabase, party_id)
    if fetch_item_by_code(supabase, item_code) is None:
        raise ItemNotFoundError(f"Item code '{item_code}' not found")

    existing = (
        supabase.table("party_item_rates")
        .select("id")
        .eq("party_id", party_id)
        .eq("item_code", item_code)
        .limit(1)
        .execute()
    )
    if existing.data:
        supabase.table("party_item_rates").update({"negotiated_rate": str(negotiated_rate)}).eq(
            "id", existing.data[0]["id"]
        ).execute()
    else:
        supabase.table("party_item_rates").insert(
            {"party_id": party_id, "item_code": item_code, "negotiated_rate": str(negotiated_rate)}
        ).execute()

    return NegotiatedRateOut(party_id=party_id, item_code=item_code, negotiated_rate=negotiated_rate)
