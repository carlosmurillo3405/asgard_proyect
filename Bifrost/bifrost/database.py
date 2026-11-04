# -*- coding: utf-8 -*-
"""Bifröst's SQLite database.

Tables:

* ``users``: Midgard accounts (password hashed with scrypt).
* ``asgards``: registered devices with their secret (also hashed).
* ``permissions``: which user may enter which Asgard.
* ``sessions``: connection history (who, to which Asgard, when and why it ended).

Every operation opens its own connection, so the server and the administration
commands can use the database at the same time (WAL mode).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .i18n import tr
from .security import dummy_verify, hash_secret, new_device_secret, password_problems, verify_secret

# Versión 2: tablas y columnas en inglés (Bifröst 2.0). No se migra la versión 1.
SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    admin INTEGER NOT NULL DEFAULT 0,
    full_access INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS asgards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    secret_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created TEXT NOT NULL,
    last_seen TEXT
);
CREATE TABLE IF NOT EXISTS permissions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    asgard_id INTEGER NOT NULL REFERENCES asgards(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, asgard_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    asgard TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    started TEXT NOT NULL,
    ended TEXT,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS sessions_started ON sessions(started);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class DatabaseError(Exception):
    """Validation or integrity error while changing the database."""


@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    display_name: str
    password_hash: str
    is_admin: bool
    full_access: bool
    active: bool
    created: str
    last_login: str | None


@dataclass(frozen=True)
class AsgardRecord:
    id: int
    device_id: str
    name: str
    location: str
    secret_hash: str
    active: bool
    created: str
    last_seen: str | None


@dataclass(frozen=True)
class SessionRecord:
    id: str
    username: str
    device_id: str
    address: str
    started: str
    ended: str | None
    reason: str | None


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_username(username: str) -> bool:
    return (
        0 < len(username) <= 64
        and username == username.strip()
        and all(char.isalnum() or char in "._-@" for char in username)
    )


def valid_device_id(device_id: str) -> bool:
    return 0 < len(device_id) <= 64 and all(
        char.isascii() and (char.isalnum() or char in "._-") for char in device_id
    )


def _user(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        password_hash=row["password_hash"],
        is_admin=bool(row["admin"]),
        full_access=bool(row["full_access"]),
        active=bool(row["active"]),
        created=row["created"],
        last_login=row["last_login"],
    )


def _asgard(row: sqlite3.Row) -> AsgardRecord:
    return AsgardRecord(
        id=row["id"],
        device_id=row["device_id"],
        name=row["name"],
        location=row["location"],
        secret_hash=row["secret_hash"],
        active=bool(row["active"]),
        created=row["created"],
        last_seen=row["last_seen"],
    )


def _password_error(problems: list[str]) -> DatabaseError:
    return DatabaseError(tr("Invalid password: {problems}.", problems="; ".join(problems)))


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "usuarios" in tables:
                raise DatabaseError(tr(
                    "{path} was created by Bifröst 1.x and cannot be used by this version. "
                    "Move it aside (or delete it) and register users and Asgard devices again.",
                    path=self.path,
                ))
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            db.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    # -- usuarios ----------------------------------------------------------- #
    def add_user(
        self, username: str, password: str, display_name: str | None = None, admin: bool = False
    ) -> UserRecord:
        username = username.strip()
        if not valid_username(username):
            raise DatabaseError(tr("The username must have 1 to 64 characters: letters, digits, '.', '_', '-' or '@'."))
        problems = password_problems(password)
        if problems:
            raise _password_error(problems)
        name = (display_name or username).strip()[:80] or username
        try:
            with self._db() as db:
                db.execute(
                    "INSERT INTO users(username, display_name, password_hash, admin, created) VALUES (?, ?, ?, ?, ?)",
                    (username, name, hash_secret(password), int(admin), now_text()),
                )
        except sqlite3.IntegrityError as error:
            raise DatabaseError(tr("The user '{name}' already exists.", name=username)) from error
        user = self.get_user(username)
        assert user is not None
        return user

    def get_user(self, username: str) -> UserRecord | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        return _user(row) if row else None

    def list_users(self) -> list[UserRecord]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [_user(row) for row in rows]

    def _require_user(self, username: str) -> UserRecord:
        user = self.get_user(username)
        if user is None:
            raise DatabaseError(tr("The user '{name}' does not exist.", name=username))
        return user

    def delete_user(self, username: str) -> None:
        user = self._require_user(username)
        with self._db() as db:
            db.execute("DELETE FROM users WHERE id = ?", (user.id,))

    def set_password(self, username: str, password: str) -> None:
        user = self._require_user(username)
        problems = password_problems(password)
        if problems:
            raise _password_error(problems)
        with self._db() as db:
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_secret(password), user.id))

    def set_user_flags(
        self,
        username: str,
        *,
        active: bool | None = None,
        admin: bool | None = None,
        full_access: bool | None = None,
        display_name: str | None = None,
    ) -> UserRecord:
        user = self._require_user(username)
        updates: list[str] = []
        values: list[object] = []
        for column, value in (("active", active), ("admin", admin), ("full_access", full_access)):
            if value is not None:
                updates.append(f"{column} = ?")
                values.append(int(value))
        if display_name is not None:
            updates.append("display_name = ?")
            values.append(display_name.strip()[:80] or user.username)
        if updates:
            with self._db() as db:
                db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", (*values, user.id))
        return self._require_user(username)

    def authenticate_user(self, username: str, password: str) -> UserRecord | None:
        """Returns the user when the password is right and the account is active."""
        user = self.get_user(username)
        if user is None or not user.active:
            dummy_verify(password)
            return None
        if not verify_secret(password, user.password_hash):
            return None
        with self._db() as db:
            db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now_text(), user.id))
        return user

    # -- Asgard ------------------------------------------------------------- #
    def register_asgard(self, device_id: str, name: str, location: str = "") -> tuple[AsgardRecord, str]:
        """Registers an Asgard and returns its secret (shown only this once)."""
        device_id = device_id.strip()
        if not valid_device_id(device_id):
            raise DatabaseError(tr("The identifier must have 1 to 64 ASCII characters: letters, digits, '.', '_' or '-'."))
        secret = new_device_secret()
        try:
            with self._db() as db:
                db.execute(
                    "INSERT INTO asgards(device_id, name, location, secret_hash, created) VALUES (?, ?, ?, ?, ?)",
                    (device_id, (name or device_id).strip()[:80], location.strip()[:120], hash_secret(secret), now_text()),
                )
        except sqlite3.IntegrityError as error:
            raise DatabaseError(tr("An Asgard with the identifier '{device}' already exists.", device=device_id)) from error
        record = self.get_asgard(device_id)
        assert record is not None
        return record, secret

    def get_asgard(self, device_id: str) -> AsgardRecord | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM asgards WHERE device_id = ?", (device_id,)).fetchone()
        return _asgard(row) if row else None

    def _require_asgard(self, device_id: str) -> AsgardRecord:
        record = self.get_asgard(device_id)
        if record is None:
            raise DatabaseError(tr("The Asgard '{device}' does not exist.", device=device_id))
        return record

    def list_asgards(self) -> list[AsgardRecord]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM asgards ORDER BY name, device_id").fetchall()
        return [_asgard(row) for row in rows]

    def delete_asgard(self, device_id: str) -> None:
        record = self._require_asgard(device_id)
        with self._db() as db:
            db.execute("DELETE FROM asgards WHERE id = ?", (record.id,))

    def regenerate_secret(self, device_id: str) -> str:
        record = self._require_asgard(device_id)
        secret = new_device_secret()
        with self._db() as db:
            db.execute("UPDATE asgards SET secret_hash = ? WHERE id = ?", (hash_secret(secret), record.id))
        return secret

    def update_asgard(
        self,
        device_id: str,
        *,
        name: str | None = None,
        location: str | None = None,
        active: bool | None = None,
    ) -> AsgardRecord:
        record = self._require_asgard(device_id)
        updates: list[str] = []
        values: list[object] = []
        if name is not None:
            updates.append("name = ?")
            values.append(name.strip()[:80] or device_id)
        if location is not None:
            updates.append("location = ?")
            values.append(location.strip()[:120])
        if active is not None:
            updates.append("active = ?")
            values.append(int(active))
        if updates:
            with self._db() as db:
                db.execute(f"UPDATE asgards SET {', '.join(updates)} WHERE id = ?", (*values, record.id))
        return self._require_asgard(device_id)

    def authenticate_asgard(self, device_id: str, secret: str) -> AsgardRecord | None:
        record = self.get_asgard(device_id)
        if record is None or not record.active:
            dummy_verify(secret)
            return None
        if not verify_secret(secret, record.secret_hash):
            return None
        with self._db() as db:
            db.execute("UPDATE asgards SET last_seen = ? WHERE id = ?", (now_text(), record.id))
        return record

    # -- permisos ----------------------------------------------------------- #
    def grant(self, username: str, device_id: str) -> None:
        """Grants access to an Asgard ('*' = every Asgard)."""
        user = self._require_user(username)
        if device_id == "*":
            self.set_user_flags(username, full_access=True)
            return
        record = self._require_asgard(device_id)
        with self._db() as db:
            db.execute(
                "INSERT OR IGNORE INTO permissions(user_id, asgard_id) VALUES (?, ?)", (user.id, record.id)
            )

    def revoke(self, username: str, device_id: str) -> None:
        user = self._require_user(username)
        if device_id == "*":
            self.set_user_flags(username, full_access=False)
            with self._db() as db:
                db.execute("DELETE FROM permissions WHERE user_id = ?", (user.id,))
            return
        record = self._require_asgard(device_id)
        with self._db() as db:
            db.execute("DELETE FROM permissions WHERE user_id = ? AND asgard_id = ?", (user.id, record.id))

    def allowed_devices(self, user: UserRecord) -> set[str] | None:
        """Asgard devices the user may enter; ``None`` means all of them."""
        current = self.get_user(user.username)
        if current is None or not current.active:
            return set()
        if current.is_admin or current.full_access:
            return None
        with self._db() as db:
            rows = db.execute(
                """SELECT a.device_id FROM permissions p JOIN asgards a ON a.id = p.asgard_id
                   WHERE p.user_id = ?""",
                (current.id,),
            ).fetchall()
        return {row[0] for row in rows}

    def permissions(self, username: str | None = None) -> list[tuple[str, str]]:
        """(user, asgard) pairs; '*' stands for full access or administrator."""
        query = """SELECT u.username AS username, a.device_id AS asgard
                   FROM permissions p JOIN users u ON u.id = p.user_id
                   JOIN asgards a ON a.id = p.asgard_id"""
        params: tuple[object, ...] = ()
        if username:
            query += " WHERE u.username = ?"
            params = (username,)
        with self._db() as db:
            rows = db.execute(query + " ORDER BY u.username, a.device_id", params).fetchall()
        pairs = [(row["username"], row["asgard"]) for row in rows]
        for user in self.list_users():
            if (user.full_access or user.is_admin) and (not username or user.username.lower() == username.lower()):
                pairs.append((user.username, "*"))
        return sorted(set(pairs))

    # -- sesiones ----------------------------------------------------------- #
    def start_session(self, session_id: str, username: str, device_id: str, address: str) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO sessions(id, username, asgard, address, started) VALUES (?, ?, ?, ?, ?)",
                (session_id, username, device_id, address, now_text()),
            )

    def end_session(self, session_id: str, reason: str) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE sessions SET ended = ?, reason = ? WHERE id = ? AND ended IS NULL",
                (now_text(), reason[:60], session_id),
            )

    def close_open_sessions(self, reason: str) -> int:
        with self._db() as db:
            cursor = db.execute(
                "UPDATE sessions SET ended = ?, reason = ? WHERE ended IS NULL", (now_text(), reason[:60])
            )
            return cursor.rowcount

    def recent_sessions(self, limit: int = 20, username: str | None = None) -> list[SessionRecord]:
        query = "SELECT * FROM sessions"
        params: tuple[object, ...] = ()
        if username:
            query += " WHERE username = ? COLLATE NOCASE"
            params = (username,)
        with self._db() as db:
            rows = db.execute(query + " ORDER BY started DESC LIMIT ?", (*params, max(1, int(limit)))).fetchall()
        return [
            SessionRecord(row["id"], row["username"], row["asgard"], row["address"], row["started"], row["ended"], row["reason"])
            for row in rows
        ]

    def counts(self) -> dict[str, int]:
        with self._db() as db:
            users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            asgards = db.execute("SELECT COUNT(*) FROM asgards").fetchone()[0]
        return {"users": int(users), "asgards": int(asgards)}
