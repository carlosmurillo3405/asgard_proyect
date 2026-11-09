# Midgard for Android and iOS

**English** · [Español](README.es.md)

The mobile apps are [Midgard Web](../web/README.md) packaged with [Capacitor](https://capacitorjs.com): the same interface and features as the desktop Midgard, except screen sharing. They connect to Bifröst's web port (8080 by default).

## What you need

| To build | You need |
| --- | --- |
| Both | The repository's Python environment (`setup_env`; Qt draws the icons) and **Node.js 20** or newer. |
| Android | **Android Studio**, which brings the Android SDK and the JDK. Works on Windows, Linux and macOS. |
| iOS | A **Mac** with **Xcode 16** or newer and **CocoaPods** (`brew install cocoapods`), plus an Apple account to sign the app. |

## The server

Choose which Bifröst the app connects to before building it. The connection file is the same `server.json` as the desktop's, made on Bifröst:

```bash
bifrost client --server bifrost.example.com --tls --no-fingerprint --output server.json
```

Copy it to `Midgard/server.json` (`build_mobile.py` takes it from there by itself) or pass it with `--server-file`. You can also give the address directly: `--server host[:web port] [--tls] [--name "Name"]`. Without any of them, the app asks for the address the first time it opens («Connection settings»).

The apps only accept certificates the phone trusts:

| Bifröst | Android app | iOS app |
| --- | --- | --- |
| Public mode with a domain and Let's Encrypt (`--tls`) | Yes | Yes (recommended) |
| Self-signed certificate (public mode without a domain, or `--web-tls`) | No | No |
| Local network without TLS (`ws://`) | Yes | It depends on WebKit: if it does not connect, use a Let's Encrypt certificate |

Inside the app the microphone and the camera work even when the server has no TLS: the app's page is local to the phone, not the server's.

## Building

```bash
cd Midgard/mobile
python build_mobile.py android            # debug APK in dist/Midgard-2.0.0-debug.apk
python build_mobile.py android --open     # opens Android Studio (run it on a connected phone, or sign it)
python build_mobile.py ios                # macOS: prepares the project and opens Xcode
python build_mobile.py ios --simulator    # macOS: builds for the simulator without signing
python build_mobile.py prepare            # only www/, server.json and the icons
```

The script:

1. updates Midgard Web's shared files and copies the web to `www/` with `server.json` (without the service worker, which only makes sense in the browser);
2. draws the icon and the splash screen with the Asgard logo (`assets/`);
3. the first time, runs `npm install` and `npx cap add android|ios`, which create `android/` or `ios/`;
4. adds the permissions (camera, microphone, local network, `ws://`) and sets the version (2.0.0);
5. makes the icons of every size (`@capacitor/assets`) and copies the web into the native project (`npx cap sync`);
6. builds the APK with Gradle, or opens Xcode.

`android/`, `ios/`, `www/`, `assets/`, `node_modules/`, `build/` and `dist/` are generated and listed in `.gitignore`. If you customize the native projects, remove them from `.gitignore` and keep them in the repository.

To install the debug APK, copy it to the phone and open it (allow «Install unknown apps»), or use `adb install dist/Midgard-2.0.0-debug.apk`.

## Publishing

- **Android**: `python build_mobile.py android --open`, then *Build → Generate Signed App Bundle / APK* in Android Studio with your key. Google Play asks for the `.aab` bundle.
- **iOS**: in Xcode choose the team in *Signing & Capabilities*, then *Product → Archive* to send it to TestFlight or the App Store.

The app ID is `mx.udg.asgard.midgard`. Change it in `capacitor.config.json` before the first build: afterwards it is part of `android/` and `ios/`.

## Differences with the desktop

- No screen sharing (the phones' web views do not allow it).
- The screen stays on during the call where the system allows it.
- When the app goes to the background the call is kept for 30 s (Bifröst's `--grace`) and resumes when you come back.

## Files

| File | Contents |
| --- | --- |
| `package.json` | Capacitor 7 (core, Android and iOS) and `@capacitor/assets`. |
| `capacitor.config.json` | App ID, name and colors; `https` page scheme on Android and permission for `ws://` on the local network. |
| `build_mobile.py` | Builds everything (see above). Its messages follow the system language. |
