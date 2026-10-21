"""User accounts and role permissions for the web app.

Roles follow knowledge/policies/approval_workflow.md:
    viewer               read-only access
    officer              Procurement Officer: runs the agent, manages stock/quotes, drafts, receives goods
    manager              Procurement Manager: officer rights + approve requisitions below UGX 2,000,000
    owner                Business Owner: everything, including approvals at or above the threshold and users

Passwords are stored as bcrypt hashes in data/users.json (git-ignored).

Create an account from the command line:
    python src/auth.py create <username> <role> "<Full Name>"
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt

ROOT = Path(__file__).resolve().parent.parent
OWNER_APPROVAL_THRESHOLD_UGX = 2_000_000
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
# Checked for unknown usernames so response time doesn't reveal which accounts exist.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode("ascii")

ROLES = {
    "viewer": "Viewer",
    "officer": "Procurement Officer",
    "manager": "Procurement Manager",
    "owner": "Business Owner",
}

PERMISSIONS = {
    "viewer": frozenset({"view"}),
    "officer": frozenset({"view", "run_agent", "manage_data", "create_draft", "receive_goods"}),
    "manager": frozenset({
        "view", "run_agent", "manage_data", "create_draft", "receive_goods",
        "approve", "reject", "manage_memory",
    }),
    "owner": frozenset({
        "view", "run_agent", "manage_data", "create_draft", "receive_goods",
        "approve", "approve_above_threshold", "reject", "manage_memory",
        "rebuild_index", "manage_users",
    }),
}


def can(user: dict[str, Any] | None, permission: str) -> bool:
    return bool(user) and permission in PERMISSIONS.get(user.get("role", ""), frozenset())


def can_approve_amount(user: dict[str, Any] | None, total_ugx: float | None) -> tuple[bool, str]:
    """Apply the approval workflow: managers below the threshold, owners for any amount."""
    if not can(user, "approve"):
        return False, "Your role cannot approve requisitions."
    if total_ugx is None:
        return False, "The total cost is unknown, so the approval limit cannot be checked."
    if total_ugx >= OWNER_APPROVAL_THRESHOLD_UGX and not can(user, "approve_above_threshold"):
        return False, (
            f"Total UGX {total_ugx:,.0f} is at or above UGX {OWNER_APPROVAL_THRESHOLD_UGX:,}; "
            "it must be escalated to the Business Owner."
        )
    return True, ""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)  # password hashes: owner-only on Linux servers
    os.replace(tmp, path)


class UserStore:
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else ROOT
        self.path = self.base_dir / "data" / "users.json"

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("User file has an invalid structure.")
        return data

    def _save(self, users: dict[str, dict[str, Any]]) -> None:
        _atomic_write(self.path, json.dumps(users, indent=2))

    @staticmethod
    def _public(username: str, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "username": username,
            "full_name": record["full_name"],
            "role": record["role"],
            "role_label": ROLES[record["role"]],
            "active": record.get("active", True),
            "locked": UserStore.is_locked(record),
            "created_at": record.get("created_at"),
        }

    @staticmethod
    def _hash(password: str) -> str:
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if len(password.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes.")
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")

    def has_users(self) -> bool:
        return bool(self._load())

    def list_users(self) -> list[dict[str, Any]]:
        return [self._public(name, rec) for name, rec in sorted(self._load().items())]

    def create_user(self, username: str, password: str, role: str, full_name: str) -> dict[str, Any]:
        username = str(username or "").strip().lower()
        if not USERNAME_PATTERN.match(username):
            raise ValueError("Username must be 3-32 characters: lowercase letters, digits, '.', '_' or '-'.")
        if role not in ROLES:
            raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
        full_name = " ".join(str(full_name or "").split())
        if not 2 <= len(full_name) <= 80:
            raise ValueError("Full name must be 2-80 characters.")
        users = self._load()
        if username in users:
            raise ValueError(f"User '{username}' already exists.")
        users[username] = {
            "full_name": full_name,
            "role": role,
            "password_hash": self._hash(password),
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save(users)
        return self._public(username, users[username])

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        """Return the user on success. After MAX_FAILED_LOGINS failures the account
        is locked for LOCKOUT_MINUTES, across all sessions and browsers."""
        username = str(username or "").strip().lower()
        password = password if isinstance(password, str) else ""
        users = self._load()
        record = users.get(username)
        if not record:
            bcrypt.checkpw(b"x", _DUMMY_HASH.encode("ascii"))
            return None
        if self.is_locked(record) or not record.get("active", True) or not password:
            return None
        try:
            ok = bcrypt.checkpw(password.encode("utf-8")[:72], record["password_hash"].encode("ascii"))
        except (ValueError, KeyError):
            ok = False
        if ok:
            if record.get("failed_logins") or record.get("locked_until"):
                record.pop("failed_logins", None)
                record.pop("locked_until", None)
                self._save(users)
            return self._public(username, record)
        record["failed_logins"] = record.get("failed_logins", 0) + 1
        if record["failed_logins"] >= MAX_FAILED_LOGINS:
            record["locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            record["failed_logins"] = 0
        self._save(users)
        return None

    @staticmethod
    def is_locked(record: dict[str, Any]) -> bool:
        locked_until = record.get("locked_until")
        if not locked_until:
            return False
        try:
            return datetime.fromisoformat(locked_until) > datetime.now(timezone.utc)
        except ValueError:
            return False

    def is_username_locked(self, username: str) -> bool:
        record = self._load().get(str(username or "").strip().lower())
        return bool(record) and self.is_locked(record)

    def get_user(self, username: str) -> dict[str, Any] | None:
        record = self._load().get(str(username or "").strip().lower())
        return self._public(username, record) if record else None

    def update_user(self, username: str, *, role: str | None = None, active: bool | None = None,
                    password: str | None = None) -> dict[str, Any]:
        users = self._load()
        username = str(username or "").strip().lower()
        if username not in users:
            raise ValueError(f"User '{username}' does not exist.")
        record = users[username]
        if role is not None:
            if role not in ROLES:
                raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
            record["role"] = role
        if active is not None:
            record["active"] = bool(active)
        if password:
            record["password_hash"] = self._hash(password)
            record.pop("failed_logins", None)
            record.pop("locked_until", None)
        if not any(r["role"] == "owner" and r.get("active", True) for r in users.values()):
            raise ValueError("At least one active Business Owner account is required.")
        self._save(users)
        return self._public(username, record)


def _cli(argv: list[str]) -> int:
    if len(argv) != 4 or argv[0] != "create":
        print(__doc__)
        return 1
    _, username, role, full_name = argv
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        return 1
    try:
        user = UserStore().create_user(username, password, role, full_name)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Created {user['username']} ({user['role_label']}).")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
