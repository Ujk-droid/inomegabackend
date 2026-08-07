"""Section 3 — pure logic: password hashing, JWT round-trip, and the 5-attempt
lockout rule. No DB, no FastAPI, matching this project's unit-test convention
(tests/unit/test_ledger_math.py)."""

from datetime import datetime, timedelta, timezone

from app.services import auth_service


def test_password_hash_roundtrip():
    hashed = auth_service.hash_password("correct horse battery staple")
    assert auth_service.verify_password("correct horse battery staple", hashed)
    assert not auth_service.verify_password("wrong password", hashed)


def test_jwt_roundtrip_carries_subject_and_role():
    token = auth_service.create_access_token("user-123", "admin")
    payload = auth_service.decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"


def test_jwt_garbage_token_fails_to_decode():
    assert auth_service.decode_token("not-a-real-token") is None


def test_is_locked_false_when_no_lockout_set():
    assert auth_service.is_locked({"locked_until": None}) is False


def test_is_locked_true_while_lock_is_in_the_future():
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert auth_service.is_locked({"locked_until": future}) is True


def test_is_locked_false_once_lock_has_expired():
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert auth_service.is_locked({"locked_until": past}) is False


def test_record_failed_login_locks_account_on_fifth_attempt():
    # Section 3: "5 failed attempts locks the account for 15 minutes" —
    # failed_login_attempts=4 going into the 5th failure must trigger the lock.
    update = auth_service.record_failed_login(4)
    assert update["failed_login_attempts"] == 5
    assert "locked_until" in update


def test_record_failed_login_does_not_lock_before_the_fifth_attempt():
    update = auth_service.record_failed_login(2)
    assert update["failed_login_attempts"] == 3
    assert "locked_until" not in update


def test_record_successful_login_resets_lockout_state():
    update = auth_service.record_successful_login()
    assert update["failed_login_attempts"] == 0
    assert update["locked_until"] is None
