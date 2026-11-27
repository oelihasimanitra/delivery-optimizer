"""Mots de passe (scrypt), sessions et limitation des tentatives. Bibliothèque standard uniquement."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time

SESSION_SECONDS = 12 * 3600
MIN_PASSWORD_LENGTH = 8
MAX_FAILURES = 5
LOCK_SECONDS = 60
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(digest) // 2)
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


def new_token() -> tuple[str, str]:
    """Retourne (jeton à envoyer au navigateur, empreinte à stocker)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class LoginThrottle:
    """Bloque un identifiant 60 s après 5 échecs consécutifs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, tuple[int, float]] = {}

    def blocked_for(self, username: str) -> float:
        with self._lock:
            failures, until = self._state.get(username, (0, 0.0))
            return max(0.0, until - time.time()) if failures >= MAX_FAILURES else 0.0

    def failure(self, username: str) -> None:
        with self._lock:
            failures, until = self._state.get(username, (0, 0.0))
            if failures >= MAX_FAILURES and until < time.time():
                failures = 0
            failures += 1
            self._state[username] = (failures, time.time() + LOCK_SECONDS if failures >= MAX_FAILURES else 0.0)

    def success(self, username: str) -> None:
        with self._lock:
            self._state.pop(username, None)
