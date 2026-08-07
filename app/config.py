import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    supabase_url: str = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_anon_key: str = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")

    cloudinary_cloud_name: str = os.getenv("NEXT_PUBLIC_CLOUDINARY_CLOUD_NAME", "")
    cloudinary_api_key: str = os.getenv("CLOUDINARY_API_KEY", "")
    cloudinary_api_secret: str = os.getenv("CLOUDINARY_API_SECRET", "")

    human_gate_threshold: float = float(os.getenv("AGENT_HUMAN_GATE_THRESHOLD", "100000.00"))

    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "")

    gmail_user: str = os.getenv("GMAIL_USER", "")
    gmail_app_password: str = os.getenv("GMAIL_APP_PASSWORD", "")

    gmail_client_id: str = os.getenv("GMAIL_CLIENT_ID", "")
    gmail_client_secret: str = os.getenv("GMAIL_CLIENT_SECRET", "")
    gmail_refresh_token: str = os.getenv("GMAIL_REFRESH_TOKEN", "")

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    fastapi_backend_url: str = os.getenv("FASTAPI_BACKEND_URL", "http://127.0.0.1:8000")

    # CORS (Section 14) — comma-separated list of origins allowed to call this
    # API directly from a browser. The frontend's normal request path goes
    # through Next.js's server-side rewrite proxy (same-origin, no CORS
    # involved), but this still needs to be correct for direct browser calls
    # (e.g. the /docs Swagger UI "Try it out" button) and as a safety net if
    # that proxy is ever bypassed. Defaults cover local dev plus the current
    # production Vercel domain; override via env when the frontend domain
    # changes instead of editing code.
    allowed_origins: list[str] = [
        origin.strip()
        for origin in os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,https://inomega-rrsz.vercel.app",
        ).split(",")
        if origin.strip()
    ]

    # Section 7.1's heartbeats (daily digest, login-request expiry, Gmail sync)
    # run on a real BackgroundScheduler started from app startup. Defaults OFF
    # so `pytest`/local dev never fires a real scheduled job against the real
    # Supabase project by accident — Render (Section 14.2) sets this to true.
    enable_scheduler: bool = os.getenv("ENABLE_SCHEDULER", "false").lower() == "true"
    # Section 3: "HTTP-only secure cookies" — Secure is required once this is
    # actually deployed behind HTTPS (Render, Section 14.2), but a Secure
    # cookie is never resent over a plain-http connection (local dev, tests),
    # so derive it from the configured backend URL's scheme rather than
    # hardcoding True.
    cookie_secure: bool = fastapi_backend_url.startswith("https")


settings = Settings()

if not settings.jwt_secret_key:
    # A blank secret doesn't fail loudly on its own — jose.jwt.encode/decode
    # will happily sign and verify every session cookie with an empty-string
    # key, which means anyone can forge a valid Admin session simply by
    # signing a JWT with "" themselves. Fail at startup instead of silently
    # running with no real session security.
    raise RuntimeError(
        "JWT_SECRET_KEY is not set. Refusing to start: session cookies would be "
        "signed with an empty key, which anyone could forge. Set a real random "
        "secret in the environment before starting the app."
    )
