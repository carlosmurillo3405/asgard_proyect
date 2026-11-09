#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Builds Midgard for Android and iOS: Midgard Web packaged with Capacitor.

The mobile apps are the same interface as Midgard Web (``Midgard/web``), which
in turn copies the design of the desktop application. They talk to Bifröst
through its web port (WebSocket, 8080 by default).

Usage::

    python build_mobile.py android                # debug APK in mobile/dist/
    python build_mobile.py android --open         # opens the project in Android Studio
    python build_mobile.py ios                    # prepares the project and opens Xcode (macOS)
    python build_mobile.py prepare                # only www/, server.json and the icons
    python build_mobile.py android --server bifrost.example.com --tls --name "Classrooms"

Without ``--server`` it uses ``--server-file`` or, if it exists, ``Midgard/server.json``
(the same file as the desktop installer, made with ``bifrost client``); without
any of them, the app asks for the server address on its first start.

Needs Node.js 20+ and, for Android, Android Studio (SDK and JDK 17 or 21);
for iOS, a Mac with Xcode and CocoaPods.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIDGARD = HERE.parent
WEB = MIDGARD / "web"
WWW = HERE / "www"
ASSETS = HERE / "assets"
DIST = HERE / "dist"
DEFAULT_WEB_PORT = 8080
BACKGROUND = "#1a1a1a"

sys.path.insert(0, str(MIDGARD))
from midgard import __version__  # noqa: E402
from midgard.i18n import set_language, tr  # noqa: E402


class BuildError(Exception):
    pass


def run(command: list[str], cwd: Path = HERE) -> None:
    print("  $ " + " ".join(command), flush=True)
    try:
        result = subprocess.run(command, cwd=cwd)
    except OSError as error:
        raise BuildError(tr("{command} could not be run: {error}", command=command[0], error=error)) from error
    if result.returncode != 0:
        raise BuildError(tr("{command} finished with errors (code {code}).", command=Path(command[0]).name, code=result.returncode))


def tool(name: str, hint: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise BuildError(tr("{name} was not found. {hint}", name=name, hint=hint))
    return path


# --------------------------------------------------------------------------- #
# www/: Midgard Web + server.json
# --------------------------------------------------------------------------- #
def server_data(args: argparse.Namespace) -> dict[str, object] | None:
    """Default server of the app (the same server.json as the desktop, with web_port)."""
    if args.server:
        text = args.server.strip()
        host, port = text, DEFAULT_WEB_PORT
        if text.startswith("["):
            host, _, rest = text[1:].partition("]")
            port = int(rest[1:]) if rest.startswith(":") else DEFAULT_WEB_PORT
        elif text.count(":") == 1:
            host, value = text.split(":")
            port = int(value)
        data: dict[str, object] = {"server": host, "web_port": port, "web_tls": bool(args.tls)}
        if args.name:
            data["name"] = args.name
    else:
        path = Path(args.server_file) if args.server_file else MIDGARD / "server.json"
        if not path.is_file():
            if args.server_file:
                raise BuildError(tr("{path} does not exist.", path=path))
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise BuildError(tr("{path} could not be read: {error}", path=path, error=error)) from error
        print(tr("Default server taken from {path}", path=path))
    if not isinstance(data, dict) or not isinstance(data.get("server"), str) or not str(data["server"]).strip():
        raise BuildError(tr("'server' is missing in the connection file."))
    port = data.get("web_port", DEFAULT_WEB_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise BuildError(tr("'web_port' must be a number between 1 and 65535."))
    return data


def prepare_www(args: argparse.Namespace) -> None:
    import build_web       # Midgard/build_web.py (Midgard/ ya está en sys.path)

    build_web.update()          # diseño, iconos, tipografías y traducciones al día
    if WWW.exists():
        shutil.rmtree(WWW)
    # El service worker solo sirve en el navegador: en la app la página ya está instalada.
    shutil.copytree(WEB, WWW, ignore=shutil.ignore_patterns("sw.js", "manifest.webmanifest", "README*.md"))
    data = server_data(args)
    if data is not None:
        (WWW / "server.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        scheme = "wss" if data.get("web_tls", data.get("tls")) else "ws"
        print(tr("Default server: {address}", address=f"{scheme}://{data['server']}:{data.get('web_port', DEFAULT_WEB_PORT)}"))
    else:
        print(tr("No server.json: the app will ask for the server address on its first start."))
    print(tr("Web files ready in {path}", path=WWW))


def draw_assets() -> None:
    """Icon and splash screen with the Asgard logo (the same as the desktop icon); needs Qt."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from midgard import theme
        from midgard.qt import QtCore, QtGui
    except Exception as error:
        raise BuildError(tr("Qt is needed to draw the icons: {error}", error=error)) from error
    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    ASSETS.mkdir(parents=True, exist_ok=True)
    # nombre, lado, margen del logotipo (fracción del lado), con fondo
    for name, side, margin, filled in (
        ("icon-only.png", 1024, 0.16, True),
        ("icon-foreground.png", 1024, 0.30, False),      # zona segura de los iconos adaptables de Android
        ("icon-background.png", 1024, None, True),
        ("splash.png", 2732, 0.40, True),
        ("splash-dark.png", 2732, 0.40, True),
    ):
        image = QtGui.QImage(side, side, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor(theme.BACKGROUND) if filled else QtGui.QColor(0, 0, 0, 0))
        if margin is not None:
            painter = QtGui.QPainter(image)
            inset = side * margin
            theme.paint_logo(painter, QtCore.QRectF(inset, inset, side - 2 * inset, side - 2 * inset), theme.TEXT)
            painter.end()
        image.save(str(ASSETS / name), "PNG")
    del app


# --------------------------------------------------------------------------- #
# Proyectos nativos
# --------------------------------------------------------------------------- #
def version_code(version: str) -> int:
    major, minor, patch = (int(part) for part in (version.split(".") + ["0", "0"])[:3])
    return major * 10000 + minor * 100 + patch


ANDROID_PERMISSIONS = (
    '<uses-permission android:name="android.permission.CAMERA" />',
    '<uses-permission android:name="android.permission.RECORD_AUDIO" />',
    '<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />',
    '<uses-feature android:name="android.hardware.camera" android:required="false" />',
    '<uses-feature android:name="android.hardware.microphone" android:required="false" />',
)


def configure_android() -> None:
    manifest = HERE / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    text = manifest.read_text(encoding="utf-8")
    missing = [line for line in ANDROID_PERMISSIONS if line.split('"')[1] not in text]
    if missing:
        text = text.replace("</manifest>", "".join(f"    {line}\n" for line in missing) + "</manifest>")
    if "android:usesCleartextTraffic" not in text:
        # ws:// en redes locales (Bifröst sin TLS en el puerto web).
        text = text.replace("<application", '<application\n        android:usesCleartextTraffic="true"', 1)
    manifest.write_text(text, encoding="utf-8")
    gradle = HERE / "android" / "app" / "build.gradle"
    if gradle.is_file():
        text = gradle.read_text(encoding="utf-8")
        text = re.sub(r"versionCode \d+", f"versionCode {version_code(__version__)}", text)
        text = re.sub(r'versionName "[^"]*"', f'versionName "{__version__}"', text)
        gradle.write_text(text, encoding="utf-8")


IOS_TEXTS = {
    "NSCameraUsageDescription": "Midgard sends your camera to the classroom only when you turn it on during a call.",
    "NSMicrophoneUsageDescription": "Midgard sends your voice to the classroom during a call.",
    "NSLocalNetworkUsageDescription": "Midgard connects to the Bifröst server of your local network.",
}


def configure_ios() -> None:
    info = HERE / "ios" / "App" / "App" / "Info.plist"
    with info.open("rb") as file:
        data = plistlib.load(file)
    data.update(IOS_TEXTS)
    security = data.setdefault("NSAppTransportSecurity", {})
    # ws:// hacia Bifröst en la red local; con TLS (wss://) no hace falta.
    security["NSAllowsLocalNetworking"] = True
    security["NSAllowsArbitraryLoadsInWebContent"] = True
    with info.open("wb") as file:
        plistlib.dump(data, file)
    project = HERE / "ios" / "App" / "App.xcodeproj" / "project.pbxproj"
    if project.is_file():
        text = project.read_text(encoding="utf-8")
        text = re.sub(r"MARKETING_VERSION = [^;]+;", f"MARKETING_VERSION = {__version__};", text)
        text = re.sub(r"CURRENT_PROJECT_VERSION = [^;]+;", f"CURRENT_PROJECT_VERSION = {version_code(__version__)};", text)
        project.write_text(text, encoding="utf-8")


def native(target: str, args: argparse.Namespace) -> None:
    node_hint = tr("Install Node.js 20 or newer (https://nodejs.org) and open a new terminal.")
    npm = tool("npm", node_hint)
    npx = tool("npx", node_hint)
    if not (HERE / "node_modules" / "@capacitor" / "cli").is_dir():
        print(tr("Installing Capacitor (npm install)…"))
        run([npm, "install"])
    if not (HERE / target).is_dir():
        print(tr("Creating the {platform} project…", platform=target))
        run([npx, "cap", "add", target])
    print(tr("Setting up permissions and version {version}…", version=__version__))
    if target == "android":
        configure_android()
    else:
        configure_ios()
    print(tr("Generating the icon and the splash screen…"))
    run([npx, "capacitor-assets", "generate", f"--{target}",
         "--iconBackgroundColor", BACKGROUND, "--iconBackgroundColorDark", BACKGROUND,
         "--splashBackgroundColor", BACKGROUND, "--splashBackgroundColorDark", BACKGROUND])
    run([npx, "cap", "sync", target])
    if args.open:
        run([npx, "cap", "open", target])
        return
    if target == "android":
        build_android(args)
    else:
        build_ios(args)


def build_android(args: argparse.Namespace) -> None:
    folder = HERE / "android"
    gradlew = folder / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if os.name != "nt":
        gradlew.chmod(0o755)
    task = "assembleRelease" if args.release else "assembleDebug"
    print(tr("Building the APK ({task})…", task=task))
    run([str(gradlew), task], cwd=folder)
    kind = "release" if args.release else "debug"
    outputs = sorted((folder / "app" / "build" / "outputs" / "apk" / kind).glob("*.apk"))
    if not outputs:
        raise BuildError(tr("Gradle did not produce any APK."))
    DIST.mkdir(exist_ok=True)
    target = DIST / f"Midgard-{__version__}-{kind}.apk"
    shutil.copyfile(outputs[0], target)
    print(tr("Done: {target}", target=target))
    if args.release and "unsigned" in outputs[0].name:
        print(tr("The release APK is not signed: sign it in Android Studio (Build > Generate Signed App Bundle / APK)."))


def build_ios(args: argparse.Namespace) -> None:
    folder = HERE / "ios" / "App"
    if args.simulator:
        xcodebuild = tool("xcodebuild", tr("Install Xcode from the App Store."))
        workspace = folder / "App.xcworkspace"
        project = ["-workspace", str(workspace)] if workspace.exists() else ["-project", str(folder / "App.xcodeproj")]
        run([xcodebuild, *project, "-scheme", "App", "-configuration", "Debug", "-sdk", "iphonesimulator",
             "-derivedDataPath", str(HERE / "build" / "ios"), "CODE_SIGNING_ALLOWED=NO", "build"])
        print(tr("Simulator build ready in {path}", path=HERE / "build" / "ios"))
        return
    print(tr("Opening Xcode: choose your team in «Signing & Capabilities» and press Run (▶) with the iPhone connected."))
    run([tool("npx", ""), "cap", "open", "ios"])


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    set_language("auto")
    parser = argparse.ArgumentParser(description=tr("Builds Midgard for Android and iOS (Midgard Web with Capacitor)."))
    parser.add_argument("target", choices=("android", "ios", "prepare"),
                        help=tr("android, ios, or prepare (only the web files and the icons)"))
    parser.add_argument("--server", help=tr("Bifröst's address for the app, host[:web port] (8080 by default)"))
    parser.add_argument("--tls", action="store_true", help=tr("Bifröst's web port uses HTTPS (wss://)"))
    parser.add_argument("--name", default="", help=tr("server name the users will see"))
    parser.add_argument("--server-file", help=tr("server.json made with «bifrost client» (Midgard/server.json by default)"))
    parser.add_argument("--open", action="store_true", help=tr("opens the project in Android Studio or Xcode instead of building it"))
    parser.add_argument("--release", action="store_true", help=tr("Android: release APK (to sign) instead of debug"))
    parser.add_argument("--simulator", action="store_true", help=tr("iOS: builds for the simulator without signing (checks the project)"))
    args = parser.parse_args(argv)
    try:
        if args.server and args.server_file:
            raise BuildError(tr("Use --server or --server-file, not both."))
        if args.target == "ios" and platform.system() != "Darwin":
            raise BuildError(tr("The iOS app can only be built on a Mac with Xcode."))
        prepare_www(args)
        draw_assets()
        if args.target != "prepare":
            native(args.target, args)
    except (BuildError, ValueError) as error:
        print(tr("Error: {error}", error=error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
