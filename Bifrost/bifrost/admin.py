# -*- coding: utf-8 -*-
"""Bifröst administration commands (users, Asgard devices, permissions, sessions, TLS).

Examples::

    python main.py user add ana --name "Ana López"
    python main.py asgard register room-1 --name "Room 1" --location "Building A"
    python main.py permission grant ana room-1
    python main.py client --server bifrost.mydomain.com --tls --output server.json
    python main.py sessions
    python main.py status          # is it running?
    python main.py monitor         # live view (useful when it runs as a service)
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sys
from pathlib import Path

from .database import Database, DatabaseError
from .i18n import tr
from .protocol import DEFAULT_PORT, format_fingerprint, local_ipv4_addresses
from .security import certificate_file_fingerprint, generate_self_signed

ADMIN_COMMANDS = ("user", "asgard", "permission", "sessions", "fingerprint", "certificate", "client", "status", "monitor")
PROGRAM_DIR = Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    return Path(os.environ.get("BIFROST_DATA") or PROGRAM_DIR / "data")


def database_path(data_dir: Path) -> Path:
    return data_dir / "bifrost.db"


def status_path(data_dir: Path) -> Path:
    return data_dir / "status.json"


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
    """Returns (certificate, key, fingerprint, created), generating a self-signed one when missing."""
    cert, key = tls_paths(data_dir)
    created = False
    if force or not cert.exists() or not key.exists():
        generate_self_signed(cert, key, names or default_certificate_names())
        created = True
    return cert, key, certificate_file_fingerprint(cert), created


def _yes(text: str) -> bool:
    return text.strip().lower() in ("yes", "y", "si", "sí", "s", "1", "true")


def _read_password(from_stdin: bool, confirm: bool = True) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    while True:
        first = getpass.getpass(tr("Password: "))
        if not confirm:
            return first
        second = getpass.getpass(tr("Repeat the password: "))
        if first == second:
            return first
        print(tr("The passwords do not match; try again."))


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return _yes(input(tr("{question} [y/N]: ", question=question)))
    except EOFError:
        return False


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print(tr("(no records)"))
        return
    widths = [max(len(str(item)) for item in column) for column in zip(headers, *rows)]
    line = "  ".join(header.ljust(width) for header, width in zip(headers, widths))
    print(line)
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(item).ljust(width) for item, width in zip(row, widths)))


def _yes_no(value: bool) -> str:
    return tr("yes") if value else tr("no")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--data",
        type=Path,
        default=default_data_dir(),
        help=tr("Bifröst data folder (BIFROST_DATA variable; ./data by default)"),
    )
    parser = argparse.ArgumentParser(prog="main.py", description=tr("Bifröst administration."))
    commands = parser.add_subparsers(dest="command", required=True)

    user = commands.add_parser("user", help=tr("Midgard user accounts"))
    u_sub = user.add_subparsers(dest="action", required=True)
    p = u_sub.add_parser("add", parents=[common], help=tr("creates a user"))
    p.add_argument("username")
    p.add_argument("--name", help=tr("display name (the username by default)"))
    p.add_argument("--admin", action="store_true", help=tr("administrator: access to every Asgard"))
    p.add_argument("--password-stdin", action="store_true", help=tr("reads the password from standard input"))
    u_sub.add_parser("list", parents=[common], help=tr("lists the users"))
    p = u_sub.add_parser("remove", parents=[common], help=tr("deletes a user"))
    p.add_argument("username")
    p.add_argument("--yes", action="store_true", help=tr("do not ask for confirmation"))
    p = u_sub.add_parser("password", parents=[common], help=tr("changes the password"))
    p.add_argument("username")
    p.add_argument("--password-stdin", action="store_true", help=tr("reads the password from standard input"))
    for action, text in (("enable", tr("allows access")), ("disable", tr("blocks access without deleting"))):
        p = u_sub.add_parser(action, parents=[common], help=text)
        p.add_argument("username")
    p = u_sub.add_parser("edit", parents=[common], help=tr("changes the name or role"))
    p.add_argument("username")
    p.add_argument("--name")
    p.add_argument("--admin", choices=("yes", "no"))

    asgard = commands.add_parser("asgard", help=tr("registered Asgard devices"))
    a_sub = asgard.add_subparsers(dest="action", required=True)
    p = a_sub.add_parser("register", parents=[common], help=tr("registers an Asgard and shows its secret"))
    p.add_argument("device")
    p.add_argument("--name")
    p.add_argument("--location", default="")
    a_sub.add_parser("list", parents=[common], help=tr("lists the Asgard devices"))
    p = a_sub.add_parser("remove", parents=[common], help=tr("deletes an Asgard"))
    p.add_argument("device")
    p.add_argument("--yes", action="store_true", help=tr("do not ask for confirmation"))
    p = a_sub.add_parser("secret", parents=[common], help=tr("generates a new secret"))
    p.add_argument("device")
    p = a_sub.add_parser("edit", parents=[common], help=tr("changes the name, location or state"))
    p.add_argument("device")
    p.add_argument("--name")
    p.add_argument("--location")
    p.add_argument("--active", choices=("yes", "no"))

    permission = commands.add_parser("permission", help=tr("which user may enter which Asgard"))
    p_sub = permission.add_subparsers(dest="action", required=True)
    for action, text in (("grant", tr("grants access ('*' = every Asgard)")),
                         ("revoke", tr("removes access ('*' = every Asgard)"))):
        p = p_sub.add_parser(action, parents=[common], help=text)
        p.add_argument("username")
        p.add_argument("asgard")
    p = p_sub.add_parser("list", parents=[common], help=tr("lists permissions"))
    p.add_argument("username", nargs="?")

    p = commands.add_parser("sessions", parents=[common], help=tr("session history"))
    p.add_argument("--limit", type=int, default=20)

    p = commands.add_parser("fingerprint", parents=[common], help=tr("shows the TLS certificate fingerprint"))
    p.add_argument("--cert", type=Path, help=tr("own certificate (the self-signed one in data/tls by default)"))

    p = commands.add_parser("certificate", parents=[common], help=tr("generates the self-signed TLS certificate"))
    p.add_argument("--public-name", default="", help=tr("domains or IP addresses separated by commas"))
    p.add_argument("--force", action="store_true", help=tr("replaces the existing certificate"))

    p = commands.add_parser(
        "client", parents=[common],
        help=tr("creates server.json: Midgard's default server (users type nothing)"),
    )
    p.add_argument("--server", required=True, help=tr("Bifröst domain or IP, with :port when it is not 8765"))
    p.add_argument("--tls", action="store_true", help=tr("Bifröst uses TLS (public mode)"))
    p.add_argument("--cert", type=Path, help=tr("server certificate (the self-signed one in data/tls by default)"))
    p.add_argument("--no-fingerprint", action="store_true",
                   help=tr("do not pin the fingerprint (Let's Encrypt or other authority certificates, which are renewed)"))
    p.add_argument("--name", default="", help=tr("server name the users will see"))
    p.add_argument("--output", type=Path, help=tr("file to write (shown on screen by default)"))

    commands.add_parser("status", parents=[common], help=tr("tells whether Bifröst is running and with which connections"))
    commands.add_parser("monitor", parents=[common], help=tr("live view of the server (status and log)"))
    return parser


def parse_server(text: str) -> tuple[str, int]:
    """'host', 'host:port' or '[ipv6]:port'."""
    value = text.strip()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") else DEFAULT_PORT
    if value.count(":") == 1:
        host, port = value.split(":")
        return host, int(port)
    return value, DEFAULT_PORT


def client_file(args: argparse.Namespace) -> int:
    """Connection file for Midgard: with it, users only type their username and password."""
    try:
        host, port = parse_server(args.server)
    except ValueError:
        print(tr("Error: the port in --server must be a number."), file=sys.stderr)
        return 1
    data: dict[str, object] = {"server": host, "port": port, "tls": bool(args.tls)}
    if args.tls and not args.no_fingerprint:
        cert = args.cert or tls_paths(args.data)[0]
        if not cert.exists():
            print(tr("Error: {path} does not exist. Start Bifröst in public mode once (it creates the certificate) "
                     "or use --no-fingerprint if the certificate comes from Let's Encrypt.", path=cert), file=sys.stderr)
            return 1
        data["fingerprint"] = format_fingerprint(certificate_file_fingerprint(cert))
    if args.name:
        data["name"] = args.name
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if not args.output:
        print(text)
        return 0
    args.output.write_text(text + "\n", encoding="utf-8")
    print(tr("Connection file created: {path}", path=args.output))
    print(tr("Copy it next to Midgard's installer (Midgard/server.json) before installing or"))
    print(tr("building the executable: Midgard will connect to this server by itself."))
    return 0


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    data_dir: Path = args.data
    if args.command in ("status", "monitor"):
        from .console import monitor, show_status

        if args.command == "status":
            return show_status(status_path(data_dir))
        return monitor(status_path(data_dir), log_path(data_dir))
    if args.command == "client":
        return client_file(args)
    try:
        if args.command == "fingerprint":
            cert = args.cert or tls_paths(data_dir)[0]
            if not cert.exists():
                print(tr("{path} does not exist. Generate one with: python main.py certificate", path=cert))
                return 1
            print(format_fingerprint(certificate_file_fingerprint(cert)))
            return 0
        if args.command == "certificate":
            names = [name.strip() for name in args.public_name.split(",") if name.strip()]
            cert, key = tls_paths(data_dir)
            if cert.exists() and not args.force:
                print(tr("{path} already exists. Use --force to replace it (clients will have to trust the new fingerprint).",
                         path=cert))
                return 1
            _, _, fingerprint, _ = ensure_certificate(data_dir, names or None, force=True)
            print(tr("Certificate: {cert}\nKey:         {key}\nSHA-256 fingerprint: {fingerprint}",
                     cert=cert, key=key, fingerprint=format_fingerprint(fingerprint)))
            return 0

        db = Database(database_path(data_dir))
        if args.command == "user":
            return _users(db, args)
        if args.command == "asgard":
            return _asgards(db, args)
        if args.command == "permission":
            return _permissions(db, args)
        if args.command == "sessions":
            rows = [
                [s.started, s.ended or tr("(active)"), s.username, s.device_id, s.address, s.reason or ""]
                for s in db.recent_sessions(args.limit)
            ]
            _print_table([tr("Start (UTC)"), tr("End (UTC)"), tr("User"), "Asgard", tr("Address"), tr("Reason")], rows)
            return 0
    except DatabaseError as error:
        print(tr("Error: {error}", error=error), file=sys.stderr)
        return 1
    return 0


def _users(db: Database, args: argparse.Namespace) -> int:
    if args.action == "add":
        password = _read_password(args.password_stdin)
        user = db.add_user(args.username, password, args.name, args.admin)
        if user.is_admin:
            print(tr("User '{name}' created (administrator).", name=user.username))
        else:
            print(tr("User '{name}' created (user).", name=user.username))
            print(tr("Give them access with: python main.py permission grant {name} <asgard|*>", name=user.username))
        print(tr("Midgard finds this server by itself on the local network; for the Internet give users"))
        print(tr("a Midgard with server.json (python main.py client --server <domain> --tls --output server.json)."))
    elif args.action == "list":
        rows = []
        for user in db.list_users():
            access = tr("all") if user.is_admin or user.full_access else tr("by permission")
            rows.append(
                [user.username, user.display_name, _yes_no(user.is_admin), access,
                 _yes_no(user.active), user.last_login or tr("never")]
            )
        _print_table([tr("User"), tr("Name"), "Admin", tr("Access"), tr("Active"), tr("Last sign-in (UTC)")], rows)
    elif args.action == "remove":
        if not _confirm(tr("Delete the user '{name}'?", name=args.username), args.yes):
            print(tr("Cancelled."))
            return 1
        db.delete_user(args.username)
        print(tr("User deleted."))
    elif args.action == "password":
        db.set_password(args.username, _read_password(args.password_stdin))
        print(tr("Password updated."))
    elif args.action in ("enable", "disable"):
        db.set_user_flags(args.username, active=args.action == "enable")
        print(tr("User enabled.") if args.action == "enable" else tr("User disabled."))
    elif args.action == "edit":
        admin = None if args.admin is None else args.admin == "yes"
        user = db.set_user_flags(args.username, admin=admin, display_name=args.name)
        print(tr("User '{name}' updated.", name=user.username))
    return 0


def _asgards(db: Database, args: argparse.Namespace) -> int:
    if args.action == "register":
        record, secret = db.register_asgard(args.device, args.name or args.device, args.location)
        print(tr('Asgard \'{device}\' registered as "{name}".', device=record.device_id, name=record.name))
        print(tr("Device secret (keep it; it will not be shown again):"))
        print(f"\n    {secret}\n")
        print(tr("Configure it on the Asgard with:"))
        print(f"    ./install.sh --device {record.device_id} --secret {secret} --server <{tr('Bifröst IP')}>")
    elif args.action == "list":
        rows = [
            [r.device_id, r.name, r.location, _yes_no(r.active), r.last_seen or tr("never")]
            for r in db.list_asgards()
        ]
        _print_table([tr("Identifier"), tr("Name"), tr("Location"), tr("Active"), tr("Last connection (UTC)")], rows)
    elif args.action == "remove":
        if not _confirm(tr("Delete the Asgard '{device}'?", device=args.device), args.yes):
            print(tr("Cancelled."))
            return 1
        db.delete_asgard(args.device)
        print(tr("Asgard deleted."))
    elif args.action == "secret":
        secret = db.regenerate_secret(args.device)
        print(tr("New secret (update it in the device's asgard.ini):"))
        print(f"\n    {secret}\n")
    elif args.action == "edit":
        active = None if args.active is None else args.active == "yes"
        record = db.update_asgard(args.device, name=args.name, location=args.location, active=active)
        print(tr("Asgard '{device}' updated.", device=record.device_id))
    return 0


def _permissions(db: Database, args: argparse.Namespace) -> int:
    if args.action == "grant":
        db.grant(args.username, args.asgard)
        if args.asgard == "*":
            print(tr("'{name}' may now enter every Asgard.", name=args.username))
        else:
            print(tr("'{name}' may now enter the Asgard '{device}'.", name=args.username, device=args.asgard))
    elif args.action == "revoke":
        db.revoke(args.username, args.asgard)
        print(tr("Permission revoked."))
    else:
        rows = [[user, tr("(all)") if device == "*" else device] for user, device in db.permissions(args.username)]
        _print_table([tr("User"), "Asgard"], rows)
    return 0
