# -*- coding: utf-8 -*-
"""Base de datos SQLite de Bifröst.

Tablas:

* ``usuarios``: cuentas de Midgard (contraseña con hash scrypt).
* ``asgards``: dispositivos registrados con su secreto (también con hash).
* ``permisos``: qué usuario puede entrar a qué Asgard.
* ``sesiones``: historial de conexiones (quién, a qué Asgard, cuándo y por qué terminó).

Cada operación abre su propia conexión, así el servidor y los comandos de
administración pueden usar la base al mismo tiempo (modo WAL).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .seguridad import dummy_verify, hash_secret, new_device_secret, password_problems, verify_secret

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nombre TEXT NOT NULL,
    clave_hash TEXT NOT NULL,
    admin INTEGER NOT NULL DEFAULT 0,
    acceso_total INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    creado TEXT NOT NULL,
    ultimo_acceso TEXT
);
CREATE TABLE IF NOT EXISTS asgards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identificador TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    ubicacion TEXT NOT NULL DEFAULT '',
    secreto_hash TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    creado TEXT NOT NULL,
    ultima_conexion TEXT
);
CREATE TABLE IF NOT EXISTS permisos (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    asgard_id INTEGER NOT NULL REFERENCES asgards(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, asgard_id)
);
CREATE TABLE IF NOT EXISTS sesiones (
    id TEXT PRIMARY KEY,
    usuario TEXT NOT NULL,
    asgard TEXT NOT NULL,
    direccion TEXT NOT NULL DEFAULT '',
    inicio TEXT NOT NULL,
    fin TEXT,
    motivo TEXT
);
CREATE INDEX IF NOT EXISTS sesiones_inicio ON sesiones(inicio);
CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""


class DatabaseError(Exception):
    """Error de validación o de integridad al modificar la base de datos."""


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
        username=row["usuario"],
        display_name=row["nombre"],
        password_hash=row["clave_hash"],
        is_admin=bool(row["admin"]),
        full_access=bool(row["acceso_total"]),
        active=bool(row["activo"]),
        created=row["creado"],
        last_login=row["ultimo_acceso"],
    )


def _asgard(row: sqlite3.Row) -> AsgardRecord:
    return AsgardRecord(
        id=row["id"],
        device_id=row["identificador"],
        name=row["nombre"],
        location=row["ubicacion"],
        secret_hash=row["secreto_hash"],
        active=bool(row["activo"]),
        created=row["creado"],
        last_seen=row["ultima_conexion"],
    )


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            db.execute(
                "INSERT OR IGNORE INTO meta(clave, valor) VALUES ('version_esquema', ?)",
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
            raise DatabaseError(
                "El usuario debe tener de 1 a 64 caracteres: letras, números, '.', '_', '-' o '@'."
            )
        problems = password_problems(password)
        if problems:
            raise DatabaseError("La contraseña " + " y ".join(problems) + ".")
        name = (display_name or username).strip()[:80] or username
        try:
            with self._db() as db:
                db.execute(
                    "INSERT INTO usuarios(usuario, nombre, clave_hash, admin, creado) VALUES (?, ?, ?, ?, ?)",
                    (username, name, hash_secret(password), int(admin), now_text()),
                )
        except sqlite3.IntegrityError as error:
            raise DatabaseError(f"Ya existe el usuario '{username}'.") from error
        user = self.get_user(username)
        assert user is not None
        return user

    def get_user(self, username: str) -> UserRecord | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM usuarios WHERE usuario = ?", (username.strip(),)).fetchone()
        return _user(row) if row else None

    def list_users(self) -> list[UserRecord]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM usuarios ORDER BY usuario").fetchall()
        return [_user(row) for row in rows]

    def _require_user(self, username: str) -> UserRecord:
        user = self.get_user(username)
        if user is None:
            raise DatabaseError(f"No existe el usuario '{username}'.")
        return user

    def delete_user(self, username: str) -> None:
        user = self._require_user(username)
        with self._db() as db:
            db.execute("DELETE FROM usuarios WHERE id = ?", (user.id,))

    def set_password(self, username: str, password: str) -> None:
        user = self._require_user(username)
        problems = password_problems(password)
        if problems:
            raise DatabaseError("La contraseña " + " y ".join(problems) + ".")
        with self._db() as db:
            db.execute("UPDATE usuarios SET clave_hash = ? WHERE id = ?", (hash_secret(password), user.id))

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
        for column, value in (("activo", active), ("admin", admin), ("acceso_total", full_access)):
            if value is not None:
                updates.append(f"{column} = ?")
                values.append(int(value))
        if display_name is not None:
            updates.append("nombre = ?")
            values.append(display_name.strip()[:80] or user.username)
        if updates:
            with self._db() as db:
                db.execute(f"UPDATE usuarios SET {', '.join(updates)} WHERE id = ?", (*values, user.id))
        return self._require_user(username)

    def authenticate_user(self, username: str, password: str) -> UserRecord | None:
        """Devuelve el usuario si la contraseña es correcta y la cuenta está activa."""
        user = self.get_user(username)
        if user is None or not user.active:
            dummy_verify(password)
            return None
        if not verify_secret(password, user.password_hash):
            return None
        with self._db() as db:
            db.execute("UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?", (now_text(), user.id))
        return user

    # -- Asgard ------------------------------------------------------------- #
    def register_asgard(self, device_id: str, name: str, location: str = "") -> tuple[AsgardRecord, str]:
        """Registra un Asgard y devuelve el secreto (solo se muestra esta vez)."""
        device_id = device_id.strip()
        if not valid_device_id(device_id):
            raise DatabaseError(
                "El identificador debe tener de 1 a 64 caracteres ASCII: letras, números, '.', '_' o '-'."
            )
        secret = new_device_secret()
        try:
            with self._db() as db:
                db.execute(
                    "INSERT INTO asgards(identificador, nombre, ubicacion, secreto_hash, creado) VALUES (?, ?, ?, ?, ?)",
                    (device_id, (name or device_id).strip()[:80], location.strip()[:120], hash_secret(secret), now_text()),
                )
        except sqlite3.IntegrityError as error:
            raise DatabaseError(f"Ya existe un Asgard con el identificador '{device_id}'.") from error
        record = self.get_asgard(device_id)
        assert record is not None
        return record, secret

    def get_asgard(self, device_id: str) -> AsgardRecord | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM asgards WHERE identificador = ?", (device_id,)).fetchone()
        return _asgard(row) if row else None

    def _require_asgard(self, device_id: str) -> AsgardRecord:
        record = self.get_asgard(device_id)
        if record is None:
            raise DatabaseError(f"No existe el Asgard '{device_id}'.")
        return record

    def list_asgards(self) -> list[AsgardRecord]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM asgards ORDER BY nombre, identificador").fetchall()
        return [_asgard(row) for row in rows]

    def delete_asgard(self, device_id: str) -> None:
        record = self._require_asgard(device_id)
        with self._db() as db:
            db.execute("DELETE FROM asgards WHERE id = ?", (record.id,))

    def regenerate_secret(self, device_id: str) -> str:
        record = self._require_asgard(device_id)
        secret = new_device_secret()
        with self._db() as db:
            db.execute("UPDATE asgards SET secreto_hash = ? WHERE id = ?", (hash_secret(secret), record.id))
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
            updates.append("nombre = ?")
            values.append(name.strip()[:80] or device_id)
        if location is not None:
            updates.append("ubicacion = ?")
            values.append(location.strip()[:120])
        if active is not None:
            updates.append("activo = ?")
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
            db.execute("UPDATE asgards SET ultima_conexion = ? WHERE id = ?", (now_text(), record.id))
        return record

    # -- permisos ----------------------------------------------------------- #
    def grant(self, username: str, device_id: str) -> None:
        """Da acceso a un Asgard ('*' = a todos los Asgard)."""
        user = self._require_user(username)
        if device_id == "*":
            self.set_user_flags(username, full_access=True)
            return
        record = self._require_asgard(device_id)
        with self._db() as db:
            db.execute(
                "INSERT OR IGNORE INTO permisos(usuario_id, asgard_id) VALUES (?, ?)", (user.id, record.id)
            )

    def revoke(self, username: str, device_id: str) -> None:
        user = self._require_user(username)
        if device_id == "*":
            self.set_user_flags(username, full_access=False)
            with self._db() as db:
                db.execute("DELETE FROM permisos WHERE usuario_id = ?", (user.id,))
            return
        record = self._require_asgard(device_id)
        with self._db() as db:
            db.execute("DELETE FROM permisos WHERE usuario_id = ? AND asgard_id = ?", (user.id, record.id))

    def has_permission(self, user: UserRecord, device_id: str) -> bool:
        if user.is_admin or user.full_access:
            return True
        with self._db() as db:
            row = db.execute(
                """SELECT 1 FROM permisos p JOIN asgards a ON a.id = p.asgard_id
                   WHERE p.usuario_id = ? AND a.identificador = ?""",
                (user.id, device_id),
            ).fetchone()
        return row is not None

    def allowed_devices(self, user: UserRecord) -> set[str] | None:
        """Asgard a los que puede entrar el usuario; ``None`` significa todos."""
        current = self.get_user(user.username)
        if current is None or not current.active:
            return set()
        if current.is_admin or current.full_access:
            return None
        with self._db() as db:
            rows = db.execute(
                """SELECT a.identificador FROM permisos p JOIN asgards a ON a.id = p.asgard_id
                   WHERE p.usuario_id = ?""",
                (current.id,),
            ).fetchall()
        return {row[0] for row in rows}

    def permissions(self, username: str | None = None) -> list[tuple[str, str]]:
        """Pares (usuario, asgard); '*' representa acceso total o administrador."""
        query = """SELECT u.usuario AS usuario, a.identificador AS asgard
                   FROM permisos p JOIN usuarios u ON u.id = p.usuario_id
                   JOIN asgards a ON a.id = p.asgard_id"""
        params: tuple[object, ...] = ()
        if username:
            query += " WHERE u.usuario = ?"
            params = (username,)
        with self._db() as db:
            rows = db.execute(query + " ORDER BY u.usuario, a.identificador", params).fetchall()
        pairs = [(row["usuario"], row["asgard"]) for row in rows]
        for user in self.list_users():
            if (user.full_access or user.is_admin) and (not username or user.username.lower() == username.lower()):
                pairs.append((user.username, "*"))
        return sorted(set(pairs))

    # -- sesiones ----------------------------------------------------------- #
    def start_session(self, session_id: str, username: str, device_id: str, address: str) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO sesiones(id, usuario, asgard, direccion, inicio) VALUES (?, ?, ?, ?, ?)",
                (session_id, username, device_id, address, now_text()),
            )

    def end_session(self, session_id: str, reason: str) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE sesiones SET fin = ?, motivo = ? WHERE id = ? AND fin IS NULL",
                (now_text(), reason[:60], session_id),
            )

    def close_open_sessions(self, reason: str) -> int:
        with self._db() as db:
            cursor = db.execute(
                "UPDATE sesiones SET fin = ?, motivo = ? WHERE fin IS NULL", (now_text(), reason[:60])
            )
            return cursor.rowcount

    def recent_sessions(self, limit: int = 20, username: str | None = None) -> list[SessionRecord]:
        query = "SELECT * FROM sesiones"
        params: tuple[object, ...] = ()
        if username:
            query += " WHERE usuario = ? COLLATE NOCASE"
            params = (username,)
        with self._db() as db:
            rows = db.execute(query + " ORDER BY inicio DESC LIMIT ?", (*params, max(1, int(limit)))).fetchall()
        return [
            SessionRecord(row["id"], row["usuario"], row["asgard"], row["direccion"], row["inicio"], row["fin"], row["motivo"])
            for row in rows
        ]

    def counts(self) -> dict[str, int]:
        with self._db() as db:
            users = db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
            asgards = db.execute("SELECT COUNT(*) FROM asgards").fetchone()[0]
        return {"usuarios": int(users), "asgards": int(asgards)}
