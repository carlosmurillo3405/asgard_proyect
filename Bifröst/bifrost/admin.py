# -*- coding: utf-8 -*-
"""Comandos de administración de Bifröst (usuarios, Asgard, permisos, sesiones, TLS).

Ejemplos::

    python main.py usuario agregar ana --nombre "Ana López"
    python main.py asgard registrar aula-1 --nombre "Aula 1" --ubicacion "Edificio A"
    python main.py permiso otorgar ana aula-1
    python main.py cliente --servidor bifrost.midominio.com --tls --salida servidor.json
    python main.py sesiones
    python main.py estado          # ¿está en ejecución?
    python main.py monitor         # vista en vivo (útil si corre como servicio)
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sys
from pathlib import Path

from .base_datos import Database, DatabaseError
from .protocolo import DEFAULT_PORT, format_fingerprint, local_ipv4_addresses
from .seguridad import certificate_file_fingerprint, generate_self_signed

ADMIN_COMMANDS = ("usuario", "asgard", "permiso", "sesiones", "huella", "certificado", "cliente", "estado", "monitor")
PROGRAM_DIR = Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    return Path(os.environ.get("BIFROST_DATOS") or PROGRAM_DIR / "datos")


def database_path(data_dir: Path) -> Path:
    return data_dir / "bifrost.db"


def status_path(data_dir: Path) -> Path:
    return data_dir / "estado.json"


def log_path(data_dir: Path) -> Path:
    return data_dir / "bifrost.log"


def tls_paths(data_dir: Path) -> tuple[Path, Path]:
    return data_dir / "tls" / "bifrost.crt", data_dir / "tls" / "bifrost.key"


def default_certificate_names() -> list[str]:
    names = [socket.gethostname(), "localhost", "127.0.0.1", *local_ipv4_addresses()]
    unique: list[str] = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return unique


def ensure_certificate(data_dir: Path, names: list[str] | None = None, force: bool = False) -> tuple[Path, Path, str, bool]:
    """Devuelve (certificado, clave, huella, creado) generando uno autofirmado si falta."""
    cert, key = tls_paths(data_dir)
    created = False
    if force or not cert.exists() or not key.exists():
        generate_self_signed(cert, key, names or default_certificate_names())
        created = True
    return cert, key, certificate_file_fingerprint(cert), created


def _yes(text: str) -> bool:
    return text.strip().lower() in ("si", "sí", "s", "yes", "y", "1", "true")


def _read_password(from_stdin: bool, confirm: bool = True) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    while True:
        first = getpass.getpass("Contraseña: ")
        if not confirm:
            return first
        second = getpass.getpass("Repite la contraseña: ")
        if first == second:
            return first
        print("Las contraseñas no coinciden; inténtalo de nuevo.")


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return _yes(input(f"{question} [s/N]: "))
    except EOFError:
        return False


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(sin registros)")
        return
    widths = [max(len(str(item)) for item in column) for column in zip(headers, *rows)]
    line = "  ".join(header.ljust(width) for header, width in zip(headers, widths))
    print(line)
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(item).ljust(width) for item, width in zip(row, widths)))


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--datos",
        type=Path,
        default=default_data_dir(),
        help="carpeta de datos de Bifröst (variable BIFROST_DATOS; por defecto ./datos)",
    )
    parser = argparse.ArgumentParser(prog="main.py", description="Administración de Bifröst.")
    commands = parser.add_subparsers(dest="command", required=True)

    usuario = commands.add_parser("usuario", help="cuentas de usuario de Midgard")
    u_sub = usuario.add_subparsers(dest="action", required=True)
    p = u_sub.add_parser("agregar", parents=[common], help="crea un usuario")
    p.add_argument("usuario")
    p.add_argument("--nombre", help="nombre visible (por defecto el usuario)")
    p.add_argument("--admin", action="store_true", help="administrador: acceso a todos los Asgard")
    p.add_argument("--clave-stdin", action="store_true", help="lee la contraseña de la entrada estándar")
    u_sub.add_parser("listar", parents=[common], help="lista los usuarios")
    p = u_sub.add_parser("eliminar", parents=[common], help="borra un usuario")
    p.add_argument("usuario")
    p.add_argument("--si", action="store_true", help="no pedir confirmación")
    p = u_sub.add_parser("clave", parents=[common], help="cambia la contraseña")
    p.add_argument("usuario")
    p.add_argument("--clave-stdin", action="store_true")
    for action, text in (("activar", "permite el acceso"), ("desactivar", "bloquea el acceso sin borrar")):
        p = u_sub.add_parser(action, parents=[common], help=text)
        p.add_argument("usuario")
    p = u_sub.add_parser("editar", parents=[common], help="cambia nombre o rol")
    p.add_argument("usuario")
    p.add_argument("--nombre")
    p.add_argument("--admin", choices=("si", "no"))

    asgard = commands.add_parser("asgard", help="dispositivos Asgard registrados")
    a_sub = asgard.add_subparsers(dest="action", required=True)
    p = a_sub.add_parser("registrar", parents=[common], help="registra un Asgard y muestra su secreto")
    p.add_argument("identificador")
    p.add_argument("--nombre")
    p.add_argument("--ubicacion", default="")
    a_sub.add_parser("listar", parents=[common], help="lista los Asgard")
    p = a_sub.add_parser("eliminar", parents=[common], help="borra un Asgard")
    p.add_argument("identificador")
    p.add_argument("--si", action="store_true")
    p = a_sub.add_parser("secreto", parents=[common], help="genera un secreto nuevo")
    p.add_argument("identificador")
    p = a_sub.add_parser("editar", parents=[common], help="cambia nombre, ubicación o estado")
    p.add_argument("identificador")
    p.add_argument("--nombre")
    p.add_argument("--ubicacion")
    p.add_argument("--activo", choices=("si", "no"))

    permiso = commands.add_parser("permiso", help="qué usuario entra a qué Asgard")
    p_sub = permiso.add_subparsers(dest="action", required=True)
    for action, text in (("otorgar", "da acceso"), ("revocar", "quita acceso")):
        p = p_sub.add_parser(action, parents=[common], help=f"{text} ('*' = todos los Asgard)")
        p.add_argument("usuario")
        p.add_argument("asgard")
    p = p_sub.add_parser("listar", parents=[common], help="lista permisos")
    p.add_argument("usuario", nargs="?")

    p = commands.add_parser("sesiones", parents=[common], help="historial de sesiones")
    p.add_argument("--limite", type=int, default=20)

    p = commands.add_parser("huella", parents=[common], help="muestra la huella del certificado TLS")
    p.add_argument("--cert", type=Path, help="certificado propio (por defecto el autofirmado de datos/tls)")

    p = commands.add_parser("certificado", parents=[common], help="genera el certificado TLS autofirmado")
    p.add_argument("--nombre-publico", default="", help="dominios o IP separados por comas")
    p.add_argument("--forzar", action="store_true", help="reemplaza el certificado existente")

    p = commands.add_parser(
        "cliente", parents=[common],
        help="crea servidor.json: el servidor predeterminado de Midgard (los usuarios no escriben nada)",
    )
    p.add_argument("--servidor", required=True, help="dominio o IP de Bifröst, con :puerto si no es 8765")
    p.add_argument("--tls", action="store_true", help="Bifröst usa TLS (modo público)")
    p.add_argument("--cert", type=Path, help="certificado del servidor (por defecto el autofirmado de datos/tls)")
    p.add_argument("--sin-huella", action="store_true",
                   help="no fijar la huella (certificados de Let's Encrypt u otra autoridad, que se renuevan)")
    p.add_argument("--nombre", default="", help="nombre del servidor que verán los usuarios")
    p.add_argument("--salida", type=Path, help="archivo a escribir (por defecto se muestra en pantalla)")

    commands.add_parser("estado", parents=[common], help="indica si Bifröst está en ejecución y con qué conexiones")
    commands.add_parser("monitor", parents=[common], help="vista en vivo del servidor (estado y registro)")
    return parser


def parse_server(text: str) -> tuple[str, int]:
    """'host', 'host:puerto' o '[ipv6]:puerto'."""
    value = text.strip()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") else DEFAULT_PORT
    if value.count(":") == 1:
        host, port = value.split(":")
        return host, int(port)
    return value, DEFAULT_PORT


def client_file(args: argparse.Namespace) -> int:
    """Archivo de conexión para Midgard: con él, el usuario solo escribe su usuario y contraseña."""
    try:
        host, port = parse_server(args.servidor)
    except ValueError:
        print("Error: el puerto de --servidor debe ser un número.", file=sys.stderr)
        return 1
    data: dict[str, object] = {"servidor": host, "puerto": port, "tls": bool(args.tls)}
    if args.tls and not args.sin_huella:
        cert = args.cert or tls_paths(args.datos)[0]
        if not cert.exists():
            print(f"Error: no existe {cert}. Inicia Bifröst en modo público una vez (crea el certificado) "
                  "o usa --sin-huella si el certificado es de Let's Encrypt.", file=sys.stderr)
            return 1
        data["huella"] = format_fingerprint(certificate_file_fingerprint(cert))
    if args.nombre:
        data["nombre"] = args.nombre
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if not args.salida:
        print(text)
        return 0
    args.salida.write_text(text + "\n", encoding="utf-8")
    print(f"Archivo de conexión creado: {args.salida}")
    print("Cópialo junto al instalador de Midgard (Midgard/Software/servidor.json) antes de instalar o de")
    print("construir el ejecutable: Midgard se conectará solo a este servidor.")
    return 0


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    data_dir: Path = args.datos
    if args.command in ("estado", "monitor"):
        from .consola import monitor, mostrar_estado

        if args.command == "estado":
            return mostrar_estado(status_path(data_dir))
        return monitor(status_path(data_dir), log_path(data_dir))
    if args.command == "cliente":
        return client_file(args)
    try:
        if args.command == "huella":
            cert = args.cert or tls_paths(data_dir)[0]
            if not cert.exists():
                print(f"No existe {cert}. Genera uno con: python main.py certificado")
                return 1
            print(format_fingerprint(certificate_file_fingerprint(cert)))
            return 0
        if args.command == "certificado":
            names = [name.strip() for name in args.nombre_publico.split(",") if name.strip()]
            cert, key = tls_paths(data_dir)
            if cert.exists() and not args.forzar:
                print(f"Ya existe {cert}. Usa --forzar para reemplazarlo (los clientes deberán confiar en la nueva huella).")
                return 1
            _, _, fingerprint, _ = ensure_certificate(data_dir, names or None, force=True)
            print(f"Certificado: {cert}\nClave:       {key}\nHuella SHA-256: {format_fingerprint(fingerprint)}")
            return 0

        db = Database(database_path(data_dir))
        if args.command == "usuario":
            return _users(db, args)
        if args.command == "asgard":
            return _asgards(db, args)
        if args.command == "permiso":
            return _permissions(db, args)
        if args.command == "sesiones":
            rows = [
                [s.started, s.ended or "(activa)", s.username, s.device_id, s.address, s.reason or ""]
                for s in db.recent_sessions(args.limite)
            ]
            _print_table(["Inicio (UTC)", "Fin (UTC)", "Usuario", "Asgard", "Dirección", "Motivo"], rows)
            return 0
    except DatabaseError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


def _users(db: Database, args: argparse.Namespace) -> int:
    if args.action == "agregar":
        password = _read_password(args.clave_stdin)
        user = db.add_user(args.usuario, password, args.nombre, args.admin)
        role = "administrador" if user.is_admin else "usuario"
        print(f"Usuario '{user.username}' creado ({role}).")
        if not user.is_admin:
            print(f"Dale acceso con: python main.py permiso otorgar {user.username} <asgard|*>")
        print("Midgard se conecta solo a este servidor en la red local; para Internet entrega a los usuarios")
        print("un Midgard con servidor.json (python main.py cliente --servidor <dominio> --tls --salida servidor.json).")
    elif args.action == "listar":
        rows = []
        for user in db.list_users():
            access = "todos" if user.is_admin or user.full_access else "por permiso"
            rows.append(
                [user.username, user.display_name, "sí" if user.is_admin else "no", access,
                 "sí" if user.active else "no", user.last_login or "nunca"]
            )
        _print_table(["Usuario", "Nombre", "Admin", "Acceso", "Activo", "Último acceso (UTC)"], rows)
    elif args.action == "eliminar":
        if not _confirm(f"¿Eliminar al usuario '{args.usuario}'?", args.si):
            print("Cancelado.")
            return 1
        db.delete_user(args.usuario)
        print("Usuario eliminado.")
    elif args.action == "clave":
        db.set_password(args.usuario, _read_password(args.clave_stdin))
        print("Contraseña actualizada.")
    elif args.action in ("activar", "desactivar"):
        db.set_user_flags(args.usuario, active=args.action == "activar")
        print(f"Usuario {'activado' if args.action == 'activar' else 'desactivado'}.")
    elif args.action == "editar":
        admin = None if args.admin is None else args.admin == "si"
        user = db.set_user_flags(args.usuario, admin=admin, display_name=args.nombre)
        print(f"Usuario '{user.username}' actualizado.")
    return 0


def _asgards(db: Database, args: argparse.Namespace) -> int:
    if args.action == "registrar":
        record, secret = db.register_asgard(args.identificador, args.nombre or args.identificador, args.ubicacion)
        print(f"Asgard '{record.device_id}' registrado como \"{record.name}\".")
        print("Secreto del dispositivo (guárdalo; no se volverá a mostrar):")
        print(f"\n    {secret}\n")
        print("Configúralo en el Asgard con:")
        print(f"    ./instalar.sh --dispositivo {record.device_id} --secreto {secret} --servidor <IP de Bifröst>")
    elif args.action == "listar":
        rows = [
            [r.device_id, r.name, r.location, "sí" if r.active else "no", r.last_seen or "nunca"]
            for r in db.list_asgards()
        ]
        _print_table(["Identificador", "Nombre", "Ubicación", "Activo", "Última conexión (UTC)"], rows)
    elif args.action == "eliminar":
        if not _confirm(f"¿Eliminar el Asgard '{args.identificador}'?", args.si):
            print("Cancelado.")
            return 1
        db.delete_asgard(args.identificador)
        print("Asgard eliminado.")
    elif args.action == "secreto":
        secret = db.regenerate_secret(args.identificador)
        print("Nuevo secreto (actualízalo en el asgard.ini del dispositivo):")
        print(f"\n    {secret}\n")
    elif args.action == "editar":
        active = None if args.activo is None else args.activo == "si"
        record = db.update_asgard(args.identificador, name=args.nombre, location=args.ubicacion, active=active)
        print(f"Asgard '{record.device_id}' actualizado.")
    return 0


def _permissions(db: Database, args: argparse.Namespace) -> int:
    if args.action == "otorgar":
        db.grant(args.usuario, args.asgard)
        target = "a todos los Asgard" if args.asgard == "*" else f"al Asgard '{args.asgard}'"
        print(f"'{args.usuario}' ahora puede entrar {target}.")
    elif args.action == "revocar":
        db.revoke(args.usuario, args.asgard)
        print("Permiso revocado.")
    else:
        rows = [[user, "(todos)" if device == "*" else device] for user, device in db.permissions(args.usuario)]
        _print_table(["Usuario", "Asgard"], rows)
    return 0
