from functools import lru_cache

import httpx
from supabase import Client, ClientOptions, create_client

from app.config import settings

# supabase-py's default postgrest client opens its httpx.Client with http2=True.
# Under this app's real network path to Supabase, that HTTP/2 connection
# intermittently gets torn down server-side (Cloudflare/PostgREST edge) while
# still sitting in httpx's keep-alive pool as "reusable" — the next request to
# reuse it fails with httpx.RemoteProtocolError: ConnectionTerminated, which
# FastAPI surfaces as a bare 500 on whatever endpoint happened to fire next
# (get_current_user's own users-table lookup runs on every authenticated
# request, so this could 500 any endpoint, not just one). Forcing HTTP/1.1
# here removes the whole GOAWAY/stream-reset failure class — postgrest builds
# an absolute URL per request (base_url.joinpath(...)) rather than relying on
# this client's own base_url/headers, so a bare http2=False client is a safe
# drop-in. Confirmed live: every 500 in progress.md's investigation traced to
# this exact ConnectionTerminated error, none to application logic.
_POSTGREST_HTTP_CLIENT = httpx.Client(http2=False, timeout=120)


@lru_cache
def get_supabase() -> Client:
    """Backend Supabase client (service role key — bypasses RLS, server-side only).

    Cached so the app reuses one client. Not called at import time, so the app can
    still boot and serve non-DB routes (e.g. health check) with placeholder .env values.
    """
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=ClientOptions(httpx_client=_POSTGREST_HTTP_CLIENT),
    )
