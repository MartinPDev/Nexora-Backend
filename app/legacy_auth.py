import hashlib
import hmac


PBKDF2_ITERATIONS = 600_000


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    ).hex()


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    if hmac.compare_digest(hash_password(password, salt), stored_hash):
        return True

    # Temporary compatibility for accounts created before the beta hardening.
    legacy_hash = hashlib.sha256((password + salt).encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_hash, stored_hash)
