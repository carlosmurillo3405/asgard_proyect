# -*- coding: utf-8 -*-
"""Pruebas de la base de datos y de la seguridad de Bifröst."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bifrost.base_datos import Database, DatabaseError
from bifrost.protocolo import normalize_fingerprint
from bifrost.seguridad import (
    LoginThrottle,
    certificate_file_fingerprint,
    generate_self_signed,
    hash_secret,
    verify_secret,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "b.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_users_are_authenticated_by_password_and_active_flag(self) -> None:
        self.db.add_user("Ana", "contraseña-segura", "Ana López")
        self.assertIsNotNone(self.db.authenticate_user("ana", "contraseña-segura"))
        self.assertIsNone(self.db.authenticate_user("ana", "otra-cosa"))
        self.db.set_user_flags("ana", active=False)
        self.assertIsNone(self.db.authenticate_user("ana", "contraseña-segura"))
        with self.assertRaises(DatabaseError):
            self.db.add_user("ANA", "contraseña-segura")
        with self.assertRaises(DatabaseError):
            self.db.add_user("corta", "123")

    def test_asgard_secret_is_only_valid_for_its_device(self) -> None:
        _, secret = self.db.register_asgard("aula-1", "Aula 1")
        _, other = self.db.register_asgard("aula-2", "Aula 2")
        self.assertIsNotNone(self.db.authenticate_asgard("aula-1", secret))
        self.assertIsNone(self.db.authenticate_asgard("aula-1", other))
        new_secret = self.db.regenerate_secret("aula-1")
        self.assertIsNone(self.db.authenticate_asgard("aula-1", secret))
        self.assertIsNotNone(self.db.authenticate_asgard("aula-1", new_secret))
        with self.assertRaises(DatabaseError):
            self.db.register_asgard("con espacios", "x")

    def test_permissions_per_asgard_full_access_and_admin(self) -> None:
        self.db.register_asgard("aula-1", "Aula 1")
        self.db.register_asgard("aula-2", "Aula 2")
        ana = self.db.add_user("ana", "contraseña-ana")
        self.db.grant("ana", "aula-1")
        self.assertTrue(self.db.has_permission(ana, "aula-1"))
        self.assertFalse(self.db.has_permission(ana, "aula-2"))
        self.db.grant("ana", "*")
        self.assertTrue(self.db.has_permission(self.db.get_user("ana"), "aula-2"))
        self.db.revoke("ana", "*")
        self.assertFalse(self.db.has_permission(self.db.get_user("ana"), "aula-1"))
        admin = self.db.add_user("jefe", "contraseña-jefe", admin=True)
        self.assertTrue(self.db.has_permission(admin, "aula-2"))
        self.assertIn(("jefe", "*"), self.db.permissions())

    def test_allowed_devices_reflect_current_permissions(self) -> None:
        self.db.register_asgard("aula-1", "Aula 1")
        self.db.register_asgard("aula-2", "Aula 2")
        ana = self.db.add_user("ana", "contraseña-ana")
        self.assertEqual(self.db.allowed_devices(ana), set())
        self.db.grant("ana", "aula-2")
        self.assertEqual(self.db.allowed_devices(ana), {"aula-2"})
        # El registro guardado en memoria no importa: se consulta el estado actual.
        self.db.grant("ana", "*")
        self.assertIsNone(self.db.allowed_devices(ana))
        self.db.set_user_flags("ana", active=False)
        self.assertEqual(self.db.allowed_devices(ana), set())

    def test_session_log_records_start_end_and_restart_cleanup(self) -> None:
        self.db.start_session("s1", "ana", "aula-1", "127.0.0.1")
        self.db.start_session("s2", "ana", "aula-1", "127.0.0.1")
        self.db.start_session("s3", "luis", "aula-2", "127.0.0.1")
        self.db.end_session("s1", "logout")
        self.assertEqual(self.db.close_open_sessions("reinicio"), 2)
        reasons = {record.id: record.reason for record in self.db.recent_sessions()}
        self.assertEqual(reasons, {"s1": "logout", "s2": "reinicio", "s3": "reinicio"})
        self.assertEqual({r.id for r in self.db.recent_sessions(10, "ANA")}, {"s1", "s2"})


class SecurityTests(unittest.TestCase):
    def test_hash_roundtrip_and_rejects_garbage(self) -> None:
        stored = hash_secret("contraseña")
        self.assertTrue(verify_secret("contraseña", stored))
        self.assertFalse(verify_secret("contrasena", stored))
        self.assertFalse(verify_secret("x", "basura"))

    def test_throttle_blocks_after_limit_and_recovers(self) -> None:
        throttle = LoginThrottle(max_failures=3, window=60, lockout=30)
        for second in range(3):
            throttle.failure("1.2.3.4", "ana", now=100 + second)
        self.assertGreater(throttle.retry_after("1.2.3.4", "ana", now=103), 0)
        self.assertEqual(throttle.retry_after("1.2.3.4", "luis", now=103), 0)
        self.assertEqual(throttle.retry_after("1.2.3.4", "ana", now=140), 0)

    def test_self_signed_certificate_fingerprint_matches_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cert, key = Path(tmp) / "c.crt", Path(tmp) / "c.key"
            fingerprint = generate_self_signed(cert, key, ["bifrost.ejemplo.com", "203.0.113.5"])
            self.assertEqual(certificate_file_fingerprint(cert), fingerprint)
            self.assertEqual(normalize_fingerprint(fingerprint.upper()), fingerprint)


if __name__ == "__main__":
    unittest.main()
