# Midgard para Android e iOS

[English](README.md) · **Español**

Las apps móviles son [Midgard Web](../web/README.es.md) empaquetada con [Capacitor](https://capacitorjs.com): la misma interfaz y las mismas funciones del Midgard de escritorio, salvo compartir pantalla. Se conectan al puerto web de Bifröst (8080 por omisión).

## Qué necesitas

| Para construir | Necesitas |
| --- | --- |
| Ambas | El entorno de Python del repositorio (`setup_env`; Qt dibuja los iconos) y **Node.js 20** o más reciente. |
| Android | **Android Studio**, que trae el SDK de Android y el JDK. Funciona en Windows, Linux y macOS. |
| iOS | Una **Mac** con **Xcode 16** o más reciente y **CocoaPods** (`brew install cocoapods`), y una cuenta de Apple para firmar la app. |

## El servidor

Elige a qué Bifröst se conecta la app antes de construirla. El archivo de conexión es el mismo `server.json` del escritorio, hecho en Bifröst:

```bash
bifrost client --server bifrost.ejemplo.com --tls --no-fingerprint --output server.json
```

Cópialo en `Midgard/server.json` (`build_mobile.py` lo toma de ahí solo) o pásalo con `--server-file`. También puedes dar la dirección directamente: `--server host[:puerto web] [--tls] [--name "Nombre"]`. Sin ninguno de ellos, la app pide la dirección la primera vez que se abre («Configurar conexión»).

Las apps solo aceptan certificados en los que confía el teléfono:

| Bifröst | App de Android | App de iOS |
| --- | --- | --- |
| Modo público con dominio y Let's Encrypt (`--tls`) | Sí | Sí (recomendado) |
| Certificado autofirmado (modo público sin dominio, o `--web-tls`) | No | No |
| Red local sin TLS (`ws://`) | Sí | Depende de WebKit: si no conecta, usa un certificado de Let's Encrypt |

Dentro de la app el micrófono y la cámara funcionan aunque el servidor no tenga TLS: la página de la app es local del teléfono, no del servidor.

## Construir

```bash
cd Midgard/mobile
python build_mobile.py android            # APK de depuración en dist/Midgard-2.0.0-debug.apk
python build_mobile.py android --open     # abre Android Studio (ejecútala en un teléfono conectado, o fírmala)
python build_mobile.py ios                # macOS: prepara el proyecto y abre Xcode
python build_mobile.py ios --simulator    # macOS: compila para el simulador sin firmar
python build_mobile.py prepare            # solo www/, server.json y los iconos
```

El script:

1. actualiza los archivos compartidos de Midgard Web y copia la web a `www/` con `server.json` (sin el service worker, que solo tiene sentido en el navegador);
2. dibuja el icono y la pantalla de inicio con el logotipo de Asgard (`assets/`);
3. la primera vez ejecuta `npm install` y `npx cap add android|ios`, que crean `android/` o `ios/`;
4. agrega los permisos (cámara, micrófono, red local, `ws://`) y pone la versión (2.0.0);
5. genera los iconos de todos los tamaños (`@capacitor/assets`) y copia la web al proyecto nativo (`npx cap sync`);
6. construye el APK con Gradle, o abre Xcode.

`android/`, `ios/`, `www/`, `assets/`, `node_modules/`, `build/` y `dist/` se generan y están en `.gitignore`. Si personalizas los proyectos nativos, quítalos de `.gitignore` y guárdalos en el repositorio.

Para instalar el APK de depuración, cópialo al teléfono y ábrelo (permite «Instalar apps desconocidas»), o usa `adb install dist/Midgard-2.0.0-debug.apk`.

## Publicar

- **Android**: `python build_mobile.py android --open` y luego *Build → Generate Signed App Bundle / APK* en Android Studio con tu llave. Google Play pide el paquete `.aab`.
- **iOS**: en Xcode elige el equipo en *Signing & Capabilities* y luego *Product → Archive* para enviarla a TestFlight o a la App Store.

El identificador de la app es `mx.udg.asgard.midgard`. Cámbialo en `capacitor.config.json` antes de la primera construcción: después queda dentro de `android/` e `ios/`.

## Diferencias con el escritorio

- No se puede compartir la pantalla (las vistas web de los teléfonos no lo permiten).
- La pantalla se mantiene encendida durante la llamada donde el sistema lo permite.
- Si la app pasa a segundo plano, la llamada se conserva 30 s (el `--grace` de Bifröst) y se reanuda al volver.

## Archivos

| Archivo | Contenido |
| --- | --- |
| `package.json` | Capacitor 7 (núcleo, Android e iOS) y `@capacitor/assets`. |
| `capacitor.config.json` | Identificador, nombre y colores de la app; esquema `https` de la página en Android y permiso para `ws://` en la red local. |
| `build_mobile.py` | Construye todo (ver arriba). Sus mensajes siguen el idioma del sistema. |
