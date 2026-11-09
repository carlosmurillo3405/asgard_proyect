# Midgard Web — Midgard en el navegador

[English](README.md) · **Español**

Midgard Web es el Midgard de escritorio escrito en HTML, CSS y JavaScript. Tiene las mismas pantallas: inicio de sesión con la transición del logotipo, la lista de Asgard, la llamada con su video, la cruceta de la cámara, las capas del seguimiento, chat, mano, perfil y la vista para desarrolladores. Bifröst la sirve en su **puerto web**, así que no se instala nada en la computadora del usuario.

## Uso

1. Abre la dirección que Bifröst muestra al arrancar como «Midgard Web», por ejemplo `http://192.168.1.10:8080` (o `https://bifrost.ejemplo.com:8080` en modo público).
2. Inicia sesión con el mismo usuario y contraseña del escritorio, elige el Asgard y entra.

Funciona en versiones recientes de Chrome, Edge, Firefox y Safari, en computadoras, tabletas y teléfonos. En el teléfono el panel lateral se abre sobre el video y la cruceta de la cámara queda siempre visible. Chrome y Edge ofrecen **instalar** la página como aplicación (el icono de la barra de direcciones, o «Agregar a la pantalla principal» en Android).

La página se conecta al servidor del que viene, así que no hay nada que configurar. «Configurar conexión» (enlace en la pantalla de acceso, o **Ctrl+Shift+D**) conecta con otro Bifröst.

## Diferencias con el escritorio

| | Escritorio | Web |
| --- | --- | --- |
| Micrófono y cámara | Siempre | Solo en páginas HTTPS (Bifröst con `--web-tls` o en modo público) o en `localhost`. Sin HTTPS igual puedes ver, escuchar, chatear y mover la cámara. |
| Elegir altavoz | Cualquiera | Chrome y Edge; los demás navegadores usan la salida del sistema. |
| Compartir pantalla | Sí | En computadoras; los teléfonos no pueden compartir su pantalla. |
| Transporte del audio | UDP, con respaldo TCP | WebSocket (TCP) por el puerto web. |
| Ajustes | `settings.json` | El almacenamiento del navegador para esa dirección. La contraseña nunca se guarda. |
| Idioma | Selector | El mismo selector; la página se recarga en el idioma nuevo y la llamada sigue. |

Recargar la página en plena llamada no la termina: la sesión y la llamada vuelven solas (Bifröst conserva la llamada 30 s, su `--grace`).

## Archivos

| Ruta | Contenido |
| --- | --- |
| `index.html`, `manifest.webmanifest`, `sw.js` | Página, datos para instalarla como aplicación y service worker (primero la red; la copia guardada solo se usa sin red). |
| `css/app.css` | Plantilla «UI-Asgard»: colores, controles, páginas y el diseño para teléfonos, tabletas y computadoras. |
| `js/app.js` | Interfaz: acceso, transición, lista de Asgard, llamada, panel lateral y perfil (como `midgard/ui/`). |
| `js/session.js` | Controlador sin interfaz (como `midgard/session.py`): servidor, acceso, lista, llamada y comandos. |
| `js/link.js`, `js/protocol.js` | Enlace WebSocket con Bifröst y los paquetes nativos (protocolo 3). |
| `js/audio.js`, `js/audio-worklet.js` | Audio de 48 kHz y 16 bits: micrófono y reproducción con colchón contra cortes (AudioWorklet). |
| `js/capture.js` | Envía la cámara y la pantalla en JPEG, con los mismos perfiles de calidad del escritorio. |
| `js/video.js` | El video del Asgard con sus capas (personas, esqueleto, trayectorias, datos en pantalla) y la cruceta de la cámara. |
| `js/ui.js`, `js/i18n.js`, `js/settings.js` | Componentes, traducciones y ajustes recordados. |
| `locale/web.es.json` | Textos en español que solo usa la web. |
| `js/brand.js`, `js/icons.js`, `img/`, `fonts/`, `locale/common.es.json`, `locale/midgard.es.json` | **Generados** desde `Common/` y `midgard/locale/` por `python Midgard/build_web.py` (también lo ejecuta `python Common/sync.py`). No los edites a mano. |

No hay paso de compilación ni bibliotecas externas: el navegador carga los módulos tal cual. Para probarla mientras desarrollas, arranca Bifröst desde el repositorio (`python Bifrost/main.py --mode local`) y abre `http://localhost:8080`. `localhost` cuenta como página segura, así que ahí funcionan el micrófono y la cámara.

Los textos se escriben en inglés dentro de `tr("…")`; sus traducciones vienen de los catálogos del escritorio más `locale/web.es.json`.
