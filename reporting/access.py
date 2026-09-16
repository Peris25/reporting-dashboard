"""Authentication and authorisation helpers.

The functions here are deliberately free of Streamlit and database imports so
the access rules (password hashing, visibility scoping, permissions) can be unit
tested on their own. The Streamlit app wires them to the session and database.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from reporting.departments import is_global_view, normalize_department, normalize_subteam

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 240_000


def hash_password(password, *, salt=None, iterations=PBKDF2_ITERATIONS):
    """Return a self-describing PBKDF2 hash string safe to store in the database."""
    if not password:
        raise ValueError("Password must not be empty.")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"{PBKDF2_ALGORITHM}${iterations}${salt}${digest.hex()}"


def verify_password(password, encoded):
    """Check a password against a stored hash without leaking timing information."""
    try:
        algorithm, iterations, salt, expected = str(encoded).split("$")
        if algorithm != PBKDF2_ALGORITHM:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), bytes.fromhex(salt), int(iterations))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(candidate.hex(), expected)


def generate_temp_password(length=10):
    """A readable temporary password for accounts that must reset on first login."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass(frozen=True)
class CurrentUser:
    username: str
    display_name: str
    department: str
    subteam: str = ""
    role: str = "member"

    @property
    def is_admin(self):
        return self.role == "admin" or is_global_view(self.department)


def is_admin(role, department):
    """True when the account can see and manage every department's requests."""
    return str(role or "").strip().lower() == "admin" or is_global_view(department)


def visible_tickets(df, *, department, admin):
    """Scope a ticket dataframe to what a user is allowed to see.

    Admins see everything. Everyone else sees requests their department owns
    (Assigned Department) plus requests their department raised (Reporting
    Department), so work sent to them and work they raised are both visible.
    """
    if admin:
        return df
    target = normalize_department(department).lower()
    if not target:
        return df.iloc[0:0]
    assigned = df.get("Assigned Department", "").fillna("").astype(str).str.strip().str.lower()
    reporting = df.get("Reporting Department", "").fillna("").astype(str).str.strip().str.lower()
    return df.loc[assigned.eq(target) | reporting.eq(target)]


def can_manage(*, department, admin, ticket_department):
    """Edit, progress, close, and reassign are limited to the owning department."""
    if admin:
        return True
    return bool(normalize_department(department)) and normalize_department(department) == normalize_department(ticket_department)


def can_delete(*, admin):
    """Deletion is restricted to admins (the IT global-view department)."""
    return bool(admin)


def clean_subteam(department, subteam):
    """Keep a sub-team only when it is valid for the given department."""
    return normalize_subteam(department, subteam)
