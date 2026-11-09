# Midgard Web — Midgard in the browser

**English** · [Español](README.es.md)

Midgard Web is the desktop Midgard written in HTML, CSS and JavaScript. It has the same screens: sign-in with the logo transition, the list of Asgards, the call with its video, the camera pad, the tracking layers, chat, hand, profile and the developer view. Bifröst serves it on its **web port**, so nothing is installed on the user's computer.

## Use

1. Open the address Bifröst shows at start-up as «Midgard Web», for example `http://192.168.1.10:8080` (or `https://bifrost.example.com:8080` in public mode).
2. Sign in with the same username and password as on the desktop, pick the Asgard and enter.

It works in recent versions of Chrome, Edge, Firefox and Safari, on computers, tablets and phones. On a phone the side panel opens over the video and the camera pad stays visible. Chrome and Edge offer to **install** the page as an app (the icon in the address bar, or «Add to home screen» on Android).

The page connects to the server it comes from, so there is nothing to set up. «Connection settings» (a link on the sign-in screen, or **Ctrl+Shift+D**) connects to another Bifröst.

## Differences with the desktop

| | Desktop | Web |
| --- | --- | --- |
| Microphone and camera | Always | Only on HTTPS pages (Bifröst with `--web-tls` or in public mode) or on `localhost`. Without HTTPS you can still watch, listen, chat and move the camera. |
| Choice of speaker | Any | Chrome and Edge; other browsers use the system output. |
| Screen sharing | Yes | On computers; phones cannot share their screen. |
| Audio transport | UDP, with TCP fallback | WebSocket (TCP) through the web port. |
| Settings | `settings.json` | The browser's storage for that address. The password is never saved. |
| Language | Selector | The same selector; the page reloads in the new language and the call goes on. |

Reloading the page in the middle of a call does not end it: the session and the call come back by themselves (Bifröst keeps the call for 30 s, its `--grace`).

## Files

| Path | Contents |
| --- | --- |
| `index.html`, `manifest.webmanifest`, `sw.js` | Page, data to install it as an app, and service worker (network first; the saved copy is only used without network). |
| `css/app.css` | «UI-Asgard» template: colors, controls, pages and the layout for phones, tablets and computers. |
| `js/app.js` | Interface: sign-in, transition, Asgard list, call, side panel and profile (like `midgard/ui/`). |
| `js/session.js` | Controller without interface (like `midgard/session.py`): server, sign-in, list, call and commands. |
| `js/link.js`, `js/protocol.js` | WebSocket link with Bifröst and the native packets (protocol 3). |
| `js/audio.js`, `js/audio-worklet.js` | 48 kHz 16-bit audio: microphone, and playback with a jitter buffer (AudioWorklet). |
| `js/capture.js` | Sends the camera and the screen as JPEG, with the same quality profiles as the desktop. |
| `js/video.js` | The Asgard's video with its layers (people, skeleton, trails, on-screen data) and the camera pad. |
| `js/ui.js`, `js/i18n.js`, `js/settings.js` | Components, translations and remembered settings. |
| `locale/web.es.json` | Spanish texts that only the web uses. |
| `js/brand.js`, `js/icons.js`, `img/`, `fonts/`, `locale/common.es.json`, `locale/midgard.es.json` | **Generated** from `Common/` and `midgard/locale/` by `python Midgard/build_web.py` (`python Common/sync.py` runs it too). Do not edit them by hand. |

There is no build step and no external library: the browser loads the modules as they are. To try it while developing, start Bifröst from the repository (`python Bifrost/main.py --mode local`) and open `http://localhost:8080`. `localhost` counts as a secure page, so the microphone and the camera work there.

Texts are written in English inside `tr("…")`; their translations come from the desktop catalogs plus `locale/web.es.json`.
