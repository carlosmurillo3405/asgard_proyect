# -*- coding: utf-8 -*-
"""Seguridad de Bifröst: contraseñas, secretos de dispositivo, límite de
intentos fallidos y certificados TLS."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import ipaddress
import os
import secrets
import ssl
import time
from collections import deque
from pathlib import Path

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_PBKDF2_ITERATIONS = 390_000
MIN_PASSWORD_LENGTH = 8


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_secret(secret: str) -> str:
    """Hash con sal de una contraseña o secreto (scrypt, o PBKDF2 si no hay scrypt)."""
    salt = os.urandom(16)
    data = secret.encode("utf-8")
    if hasattr(hashlib, "scrypt"):
        try:
            digest = hashlib.scrypt(data, salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
            return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"
        except (ValueError, MemoryError):
            pass
    digest = hashlib.pbkdf2_hmac("sha256", data, salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_secret(secret: str, stored: str) -> bool:
    """Compara en tiempo constante una contraseña con su hash almacenado."""
    try:
        parts = stored.split("$")
        data = secret.encode("utf-8")
        if parts[0] == "scrypt" and len(parts) == 6:
            n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
            salt, expected = _unb64(parts[4]), _unb64(parts[5])
            digest = hashlib.scrypt(data, salt=salt, n=n, r=r, p=p, dklen=len(expected), maxmem=64 * 1024 * 1024)
        elif parts[0] == "pbkdf2_sha256" and len(parts) == 4:
            iterations = int(parts[1])
            salt, expected = _unb64(parts[2]), _unb64(parts[3])
            digest = hashlib.pbkdf2_hmac("sha256", data, salt, iterations, dklen=len(expected))
        else:
            return False
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError, MemoryError, UnicodeError):
        return False


_DUMMY_HASH: str | None = None


def dummy_verify(secret: str) -> None:
    """Tarda lo mismo que una verificación real; así no se revela si un usuario existe."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_secret("bifrost-usuario-inexistente")
    verify_secret(secret, _DUMMY_HASH)


def new_device_secret() -> str:
    return secrets.token_urlsafe(24)


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")
    if password != password.strip():
        problems.append("no debe empezar ni terminar con espacios")
    return problems


class LoginThrottle:
    """Bloquea temporalmente una IP o un par IP+usuario tras varios fallos."""

    def __init__(
        self,
        max_failures: int = 5,
        window: float = 300.0,
        lockout: float = 300.0,
        max_ip_failures: int | None = None,
    ) -> None:
        self.max_failures = max_failures
        self.window = window
        self.lockout = lockout
        self.max_ip_failures = max_ip_failures or max_failures * 4
        self._failures: dict[tuple[str, ...], deque[float]] = {}
        self._blocked_until: dict[tuple[str, ...], float] = {}

    @staticmethod
    def _keys(ip: str, user: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return ("ip", ip), ("user", ip, user.lower())

    def retry_after(self, ip: str, user: str, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        wait = 0.0
        for key in self._keys(ip, user):
            until = self._blocked_until.get(key, 0.0)
            if until > now:
                wait = max(wait, until - now)
        return wait

    def failure(self, ip: str, user: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        ip_key, user_key = self._keys(ip, user)
        for key, limit in ((ip_key, self.max_ip_failures), (user_key, self.max_failures)):
            history = self._failures.setdefault(key, deque())
            history.append(now)
            while history and now - history[0] > self.window:
                history.popleft()
            if len(history) >= limit:
                self._blocked_until[key] = now + self.lockout
                history.clear()

    def success(self, ip: str, user: str) -> None:
        self._failures.pop(self._keys(ip, user)[1], None)

    def cleanup(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for key, history in list(self._failures.items()):
            while history and now - history[0] > self.window:
                history.popleft()
            if not history:
                del self._failures[key]
        for key, until in list(self._blocked_until.items()):
            if until <= now:
                del self._blocked_until[key]


# --------------------------------------------------------------------------- #
# TLS
# --------------------------------------------------------------------------- #
def server_ssl_context(cert_path: str | Path, key_path: str | Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


def certificate_file_fingerprint(cert_path: str | Path) -> str:
    """Huella SHA-256 del primer certificado de un archivo PEM."""
    pem = Path(cert_path).read_text(encoding="ascii", errors="replace")
    begin = "-----BEGIN CERTIFICATE-----"
    end = "-----END CERTIFICATE-----"
    start = pem.index(begin)
    stop = pem.index(end, start) + len(end)
    der = ssl.PEM_cert_to_DER_cert(pem[start:stop])
    return hashlib.sha256(der).hexdigest()


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def generate_self_signed(cert_path: str | Path, key_path: str | Path, names: list[str]) -> str:
    """Crea un certificado autofirmado (P-256, 10 años) y devuelve su huella."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    names = [name.strip() for name in names if name and name.strip()] or ["bifrost"]
    key = ec.generate_private_key(ec.SECP256R1())
    public_key = key.public_key()
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, names[0][:64]),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Proyecto Asgard"),
        ]
    )
    alternative: list[x509.GeneralName] = []
    for name in names:
        try:
            alternative.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            alternative.append(x509.DNSName(name))
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(alternative), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=True,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(public_key), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_private(
        Path(key_path),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    cert_file = Path(cert_path)
    cert_file.parent.mkdir(parents=True, exist_ok=True)
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
