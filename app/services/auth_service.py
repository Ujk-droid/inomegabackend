"""Section 3 — password hashing, session JWT, and the login-lockout rule.

Deviates from the PRD's literal "Framework: Supabase Auth" text — see
db/schema_phase3.sql's header comment and progress.md for the rationale. The
users table (already live from Phase 1) is a plain password_hash + user_role
table, so this issues its own JWT rather than delegating to Supabase Auth/GoTrue.
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 hours
FAILED_ATTEMPT_LIMIT = 5  # Section 3: "5 failed attempts locks the account for 15 minutes"
LOCKOUT_MINUTES = 15

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None


def parse_timestamp(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def is_locked(user: dict) -> bool:
    """Section 3's lockout rule — true while locked_until is still in the future."""
    locked_until = user.get("locked_until")
    if not locked_until:
        return False
    return parse_timestamp(locked_until) > datetime.now(timezone.utc)


def record_failed_login(failed_attempts: int) -> dict:
    """DB update payload after one more failed attempt: increments the counter,
    and locks the account for LOCKOUT_MINUTES once it reaches FAILED_ATTEMPT_LIMIT."""
    new_count = failed_attempts + 1
    update: dict = {"failed_login_attempts": new_count}
    if new_count >= FAILED_ATTEMPT_LIMIT:
        update["locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
    return update


def record_successful_login() -> dict:
    return {"failed_login_attempts": 0, "locked_until": None, "last_login": datetime.now(timezone.utc).isoformat()}
