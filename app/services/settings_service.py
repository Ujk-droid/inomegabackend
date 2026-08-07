"""Section 12.1 — the Human Gate threshold must be Admin-editable at runtime,
not a hardcoded .env value. app_settings is a single-row table; if it's
missing (a fresh environment where schema_phase3.sql hasn't seeded it yet,
or the in-memory fake client in tests) this seeds it from the .env default
the first time it's read."""

from supabase import Client

from app.config import settings as env_settings


def _get_or_seed_row(supabase: Client) -> dict:
    resp = supabase.table("app_settings").select("*").limit(1).execute()
    if resp.data:
        return resp.data[0]

    payload = {"human_gate_threshold": str(env_settings.human_gate_threshold)}
    inserted = supabase.table("app_settings").insert(payload).execute()
    return inserted.data[0]


def get_human_gate_threshold(supabase: Client) -> float:
    return float(_get_or_seed_row(supabase)["human_gate_threshold"])


def get_settings_row(supabase: Client) -> dict:
    return _get_or_seed_row(supabase)


def update_human_gate_threshold(supabase: Client, new_threshold: float, admin_id: str) -> dict:
    row = _get_or_seed_row(supabase)
    resp = (
        supabase.table("app_settings")
        .update({"human_gate_threshold": str(new_threshold), "updated_by": admin_id})
        .eq("id", row["id"])
        .execute()
    )
    return resp.data[0]
