// Ajustes que se recuerdan entre usos (en el almacenamiento del navegador).
// Los mismos de la aplicación de escritorio (midgard/settings.py), menos los
// que no aplican en la web. La contraseña nunca se guarda.

const KEY = "midgard.settings";
export const VIEW_DEFAULT = "default";
export const VIEW_ADVANCED = "advanced";

const DEFAULTS = {
  server_mode: "auto",       // auto: el servidor de esta página o server.json; manual: host/port/tls
  host: "",
  port: 8080,
  tls: false,
  username: "",
  last_asgard: "",
  avatars: {},               // usuario -> foto (JPEG en data: URL)
  microphone: "",
  speaker: "",
  camera: "",
  camera_profile: "Medium",
  screen_profile: "High",
  send_microphone: true,
  speaker_on: true,
  receive_video: true,
  receive_audio: true,
  language: "auto",
  view_mode: VIEW_DEFAULT,
  side_panel: "chat",
  side_open: true,
  show_boxes: true,
  show_trails: true,
  show_skeleton: true,
  show_hud: true,
  show_grid: false,
};

export function loadSettings() {
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(KEY) || "{}") || {};
  } catch {
    stored = {};
  }
  const settings = { ...DEFAULTS };
  for (const [key, value] of Object.entries(stored)) {
    if (key in DEFAULTS && typeof value === typeof DEFAULTS[key]) settings[key] = value;
  }
  if (![VIEW_DEFAULT, VIEW_ADVANCED].includes(settings.view_mode)) settings.view_mode = VIEW_DEFAULT;
  if (!["auto", "en", "es"].includes(settings.language)) settings.language = "auto";
  return settings;
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    // modo privado o almacenamiento lleno: los ajustes duran hasta cerrar la página
  }
}

export function isAdvanced(settings) {
  return settings.view_mode === VIEW_ADVANCED;
}
