// Lógica de Midgard sin interfaz (equivalente a midgard/session.py).
//
// Encuentra el servidor, inicia la sesión del usuario, mantiene el listado de
// Asgard, abre y reanuda la llamada, maneja el audio y los envíos de cámara y
// pantalla, y convierte las acciones del usuario en comandos para el Asgard.
// La interfaz recibe todo como eventos: controller.onEvent(tipo, ...datos).

import { AudioEngine } from "./audio.js";
import { CAMERA_PROFILES, SCREEN_PROFILES, startCamera, startScreen } from "./capture.js";
import { tr } from "./i18n.js";
import { Link } from "./link.js";
import { MAX_CHAT_LENGTH, PROTOCOL_VERSION, ROLE_MIDGARD, VIDEO, b64encode, messageText } from "./protocol.js";

export const VERSION = "2.0.0";
const TRAIL_SECONDS = 4;
const TOKENS = "midgard.tokens";      // token del usuario y de la llamada: sobreviven a recargar la pestaña

export function sessionEndText(reason) {
  const texts = {
    logout: tr("Call ended."),
    timeout: tr("The call ended because the connection was lost for too long."),
    replaced: tr("The call was opened in another Midgard window."),
    server_shutdown: tr("The Bifröst server shut down."),
    server_restart: tr("The Bifröst server restarted."),
    expired: tr("The call expired while there was no connection."),
  };
  return texts[reason] || tr("Call ended ({reason}).", { reason });
}

export function endReasonLabel(reason) {
  const labels = {
    logout: tr("ended by the user"),
    timeout: tr("connection lost"),
    replaced: tr("opened in another window"),
    server_shutdown: tr("server shut down"),
    server_restart: tr("server restarted"),
  };
  return labels[reason] || reason || "—";
}

/** True inside the Android or iOS app (Capacitor): the page does not come from Bifröst. */
export function isPackagedApp() {
  return !!(window.Capacitor && (typeof window.Capacitor.isNativePlatform !== "function" || window.Capacitor.isNativePlatform()));
}

/** «web», «android» or «ios» (shown in Bifröst's connection list). */
export function platformName() {
  if (!isPackagedApp()) return "web";
  return typeof window.Capacitor.getPlatform === "function" ? String(window.Capacitor.getPlatform()) : "app";
}

export class ServerChoice {
  constructor(host, port, tls, name = "", source = "manual") {
    this.host = host;
    this.port = port;
    this.tls = tls;
    this.name = name;
    this.source = source;
  }

  get address() {
    const host = this.host.includes(":") ? `[${this.host}]` : this.host;
    return `${host}:${this.port}`;
  }

  get url() {
    return `${this.tls ? "wss" : "ws"}://${this.address}/ws`;
  }

  describe() {
    const origin = {
      manual: tr("set by hand"),
      file: tr("default server"),
      page: tr("this page's server"),
      last: tr("last server used"),
    }[this.source] || this.source;
    return `${this.name || "Bifröst"} · ${this.address}` + (origin ? ` (${origin})` : "");
  }
}

/** Parses «host», «host:port» or «[ipv6]:port». */
export function parseAddress(text, defaultPort) {
  const value = String(text || "").trim();
  if (!value) return null;
  let host = value;
  let port = defaultPort;
  if (value.startsWith("[")) {
    const end = value.indexOf("]");
    host = value.slice(1, end);
    const rest = value.slice(end + 1);
    if (rest.startsWith(":")) port = Number(rest.slice(1));
  } else if ((value.match(/:/g) || []).length === 1) {
    [host, port] = value.split(":");
    port = Number(port);
  }
  if (!host || !Number.isInteger(port) || port < 1 || port > 65535) return null;
  return { host, port };
}

/** Picks the server: by hand, this page's, server.json or the last one that worked. */
export async function resolveServer(settings) {
  if (settings.server_mode === "manual" && settings.host) {
    return new ServerChoice(settings.host, settings.port, settings.tls, "", "manual");
  }
  if (!isPackagedApp() && location.protocol.startsWith("http")) {
    const tls = location.protocol === "https:";
    return new ServerChoice(location.hostname, Number(location.port) || (tls ? 443 : 80), tls, "", "page");
  }
  try {
    const response = await fetch("server.json", { cache: "no-cache" });
    if (response.ok) {
      const data = await response.json();
      // El mismo server.json del escritorio («bifrost client»): la web usa el puerto web, no «port».
      const port = Number(data.web_port || 8080);
      const tls = "web_tls" in data ? !!data.web_tls : !!data.tls;
      if (typeof data.server === "string" && data.server.trim() && Number.isInteger(port) && port > 0 && port < 65536) {
        return new ServerChoice(data.server.trim(), port, tls, String(data.name || "").slice(0, 80), "file");
      }
    }
  } catch {
    // sin server.json
  }
  if (settings.host) return new ServerChoice(settings.host, settings.port, settings.tls, "", "last");
  throw new Error(tr("The Bifröst server is not configured. Enter its address in «Connection settings»."));
}

function loadTokens() {
  try {
    return JSON.parse(sessionStorage.getItem(TOKENS) || "{}") || {};
  } catch {
    return {};
  }
}

function saveTokens(tokens) {
  try {
    sessionStorage.setItem(TOKENS, JSON.stringify(tokens));
  } catch {
    // sin almacenamiento de sesión
  }
}

export class MidgardController {
  constructor(settings, onEvent) {
    this.settings = settings;
    this.onEvent = onEvent;
    this.link = null;
    this.server = null;
    this.welcome = {};
    this.user = null;
    const tokens = loadTokens();
    this.userToken = tokens.user || "";
    this.resumeToken = tokens.resume || "";
    this.asgards = [];
    this.session = null;
    this.asgardConnected = false;
    this.asgardState = {};
    this.detections = { items: [], at: 0, target: null };
    this.trails = new Map();
    this.debug = false;
    this.avatarJpeg = "";
    this.audio = null;
    this.cameraSender = null;
    this.screenSender = null;
    this.receiveVideo = settings.receive_video;
    this.receiveAudio = settings.receive_audio;
    this.sendMicrophone = settings.send_microphone;
    this.speakerOn = settings.speaker_on;
    this.remoteFrame = null;          // último cuadro del Asgard sin dibujar: {data, meta, at}
    this.remoteFrames = 0;
    this.lastFrameAt = 0;
    this.pendingAuth = null;
    this.resolving = false;
    this.chatIds = 0;
  }

  emit(kind, ...payload) {
    this.onEvent(kind, ...payload);
  }

  get connected() {
    return this.link !== null && this.link.connected;
  }

  get authenticated() {
    return this.user !== null;
  }

  get inSession() {
    return this.session !== null;
  }

  get capabilities() {
    return (this.session && this.session.asgard && this.session.asgard.capabilities) || {};
  }

  _saveTokens() {
    saveTokens({ user: this.userToken, resume: this.resumeToken });
  }

  // -- conexión con Bifröst ------------------------------------------------------ //
  connect(choice) {
    // La primera conexión conserva los tokens guardados (recargar la página no cierra la sesión);
    // cambiar a otro servidor sí obliga a entrar de nuevo.
    if (this.link !== null || this.server !== null) {
      this.disconnect(this.server !== null && this.server.address === choice.address);
    }
    this.server = choice;
    this.link = new Link({
      url: choice.url,
      label: choice.address,
      hello: () => this._hello(),
      onWelcome: (meta) => this._onWelcome(meta),
      onControl: (meta) => this._onControl(meta),
      onAudio: (meta, data) => { if (this.audio) this.audio.feed(meta, data); },
      onFrame: (stream, meta, data) => this._onFrame(stream, meta, data),
      onState: (state, detail) => this.emit("link", state, detail),
      onProblem: (kind, info) => this._onProblem(kind, info),
    });
    this.link.start();
  }

  async connectDefault() {
    if (this.resolving) return;
    this.resolving = true;
    this.emit("server_search");
    let choice;
    try {
      choice = await resolveServer(this.settings);
    } catch (error) {
      this.resolving = false;
      const pending = this.pendingAuth !== null;
      this.pendingAuth = null;
      this.emit("server_error", error.message);
      if (pending) this.emit("auth_error", "unreachable", error.message);
      return;
    }
    this.resolving = false;
    this.connect(choice);
    this.emit("server", choice);
  }

  disconnect(keepUser = false) {
    this._stopSessionMedia();
    if (this.link) this.link.stop();
    this.link = null;
    this.session = null;
    this.resumeToken = "";
    this.asgards = [];
    this.asgardState = {};
    if (!keepUser) {
      this.user = null;
      this.userToken = "";
    }
    this._saveTokens();
  }

  _hello() {
    const hello = { role: ROLE_MIDGARD, version: PROTOCOL_VERSION, software: `midgard-${platformName()} ${VERSION}` };
    if (this.userToken) hello.token = this.userToken;
    if (this.resumeToken) hello.resume = this.resumeToken;
    return hello;
  }

  _onProblem(kind, info) {
    const pending = this.pendingAuth !== null;
    this.pendingAuth = null;
    this.emit("problem", kind, info);
    if (pending) this.emit("auth_error", "unreachable", info.message || tr("Could not connect to the server."));
  }

  _onWelcome(meta) {
    this.welcome = meta;
    if (meta.auth && typeof meta.auth === "object") {
      this.user = meta.auth;
      this.emit("auth_ok", meta.auth, true);
    } else if (this.userToken) {
      this.user = null;
      this.userToken = "";
      this._saveTokens();
      this.emit("auth_lost", tr("Your session expired or the server restarted. Sign in again."));
    }
    if (meta.resumed && typeof meta.resumed === "object") {
      this._sessionStarted(meta.resumed, true);
    } else if (this.session !== null) {
      this._sessionEnded(sessionEndText("expired"));
    }
    const pending = this.pendingAuth;
    this.pendingAuth = null;
    if (pending && this.link) this.link.sendControl({ op: "auth", user: pending[0], password: pending[1] });
    this.emit("welcome", meta);
  }

  refreshList() {
    if (this.link && this.authenticated) this.link.sendControl({ op: "list" });
  }

  _onControl(meta) {
    const op = meta.op;
    if (op === "asgards") {
      this.asgards = (meta.items || []).filter((item) => item && typeof item === "object");
      this.emit("asgards", this.asgards);
    } else if (op === "auth_ok") {
      this.user = meta.user && typeof meta.user === "object" ? meta.user : {};
      this.userToken = String(meta.token || "");
      this._saveTokens();
      this.emit("auth_ok", this.user, false);
    } else if (op === "auth_error") {
      this.emit("auth_error", String(meta.code || ""), messageText(meta, tr("Access denied.")));
    } else if (op === "session_ok") {
      this._sessionStarted(meta, false);
    } else if (op === "session_error") {
      this.emit("session_error", String(meta.code || ""), messageText(meta, tr("The call could not be opened.")));
    } else if (op === "session_end") {
      this._sessionEnded(sessionEndText(String(meta.reason || "")));
    } else if (op === "signed_out") {
      this.user = null;
      this.userToken = "";
      this._saveTokens();
    } else if (op === "password_ok") {
      this.emit("password", true, tr("Password updated."));
    } else if (op === "password_error") {
      this.emit("password", false, messageText(meta, tr("The password could not be changed.")));
    } else if (op === "history") {
      this.emit("history", (meta.items || []).filter((item) => item && typeof item === "object"));
    } else if (op === "asgard_status") {
      this.asgardConnected = !!meta.connected;
      this.emit("asgard_status", this.asgardConnected);
    } else if (op === "evt") {
      this._onEvent(meta);
    } else if (op === "error") {
      if (meta.code === "auth_required" && this.user !== null) {
        this.user = null;
        this.userToken = "";
        this._saveTokens();
        this.emit("auth_lost", tr("The server asked you to sign in again."));
      } else {
        this.emit("notice", messageText(meta));
      }
    }
  }

  _onEvent(meta) {
    const event = meta.evt;
    if (event === "state") {
      this.asgardState = meta;
      this.emit("state", meta);
    } else if (event === "detections") {
      const now = performance.now() / 1000;
      const items = (meta.items || []).filter((item) => item && typeof item === "object");
      this.detections = { items, at: now, target: meta.target, mode: meta.mode, aim: meta.aim };
      this._recordTrails(items, now);
    } else if (event === "chat_ack") {
      this.emit("chat_ack", String(meta.id || ""));
    } else if (event === "notice") {
      this.emit("notice", messageText(meta));
    }
  }

  _recordTrails(items, now) {
    for (const item of items) {
      const box = item.box;
      if (!Number.isInteger(item.id) || !Array.isArray(box) || box.length !== 4) continue;
      if (!this.trails.has(item.id)) this.trails.set(item.id, []);
      const trail = this.trails.get(item.id);
      trail.push([now, box[0] + box[2] / 2, box[1] + box[3] / 2]);
      if (trail.length > 90) trail.shift();
    }
    for (const [identifier, trail] of this.trails) {
      while (trail.length && now - trail[0][0] > TRAIL_SECONDS) trail.shift();
      if (!trail.length) this.trails.delete(identifier);
    }
  }

  // -- usuario ------------------------------------------------------------------ //
  authenticate(username, password) {
    if (this.link && this.link.connected) {
      this.link.sendControl({ op: "auth", user: username, password });
      return;
    }
    this.pendingAuth = [username, password];
    if (this.link === null) this.connectDefault();
  }

  cancelAuth() {
    this.pendingAuth = null;
  }

  signOut() {
    this._stopSessionMedia();
    if (this.link && this.link.connected && this.user !== null) this.link.sendControl({ op: "signout" });
    this.user = null;
    this.userToken = "";
    this.session = null;
    this.resumeToken = "";
    this.asgards = [];
    this._saveTokens();
    this.emit("signed_out");
  }

  changePassword(old, password) {
    if (!this.link || !this.link.connected || this.user === null) return false;
    return this.link.sendControl({ op: "password", old, new: password });
  }

  requestHistory() {
    if (!this.link || !this.authenticated) return false;
    return this.link.sendControl({ op: "history" });
  }

  /** User photo (base64 JPEG) shown on the classroom screen; empty removes it. */
  setAvatar(base64) {
    const changed = base64 !== this.avatarJpeg;
    this.avatarJpeg = base64;
    if (this.session !== null && changed) this.command("avatar", { image: base64 || "" });
  }

  // -- llamada ---------------------------------------------------------------- //
  openAsgard(asgardId) {
    if (!this.link || !this.link.connected || !this.authenticated) return false;
    return this.link.sendControl({ op: "open", asgard: asgardId });
  }

  closeSession() {
    if (this.session === null) return;
    this._stopSessionMedia();
    if (this.link && this.link.connected) this.link.sendControl({ op: "logout" });
    else this._sessionEnded(sessionEndText("logout"));
  }

  _sessionStarted(info, resumed) {
    const session = info.session && typeof info.session === "object" ? info.session : {};
    this.session = session;
    this.resumeToken = String(info.resume_token || this.resumeToken || "");
    this._saveTokens();
    this.asgardConnected = !!(session.asgard ? session.asgard.connected !== false : true);
    this._startAudio();
    this._sendPreferences();
    this.emit("session", info, resumed);
  }

  _sessionEnded(message) {
    const wasActive = this.session !== null;
    this.session = null;
    this.resumeToken = "";
    this._saveTokens();
    this._stopSessionMedia();
    this.asgardState = {};
    this.detections = { items: [], at: 0, target: null };
    this.trails.clear();
    this.remoteFrame = null;
    if (wasActive) this.emit("session_end", message);
    this.refreshList();
  }

  _sendPreferences() {
    this.command("media", { video: this.receiveVideo, audio: this.receiveAudio });
    this._sendRemoteStreams();
    if (this.debug) this.command("debug", { enabled: true });
    if (this.avatarJpeg) this.command("avatar", { image: this.avatarJpeg });
  }

  _sendRemoteStreams() {
    this.command("remote_streams", {
      camera: this.cameraRunning,
      screen: this.screenRunning,
      mic: this.sendMicrophone && this.audio !== null && this.audio.microphoneStream !== null,
    });
  }

  async _startAudio() {
    if (this.audio || !this.link) return;
    const engine = new AudioEngine();
    this.audio = engine;
    engine.micOn = this.sendMicrophone;
    engine.setSpeakerOn(this.speakerOn && this.receiveAudio);
    try {
      await engine.start(this.link, this.settings.microphone, this.settings.speaker);
    } catch (error) {
      engine.errors.push(error.message || String(error));
    }
    if (this.audio !== engine) {        // la llamada terminó mientras arrancaba
      engine.stop();
      return;
    }
    this._applyAudioFlags();
    this._sendRemoteStreams();
    if (engine.errors.length) this.emit("audio_error", engine.errors.join("; "));
  }

  _applyAudioFlags() {
    if (!this.audio) return;
    this.audio.micOn = this.sendMicrophone;
    this.audio.setSpeakerOn(this.speakerOn && this.receiveAudio);
  }

  _stopSessionMedia() {
    if (this.audio) this.audio.stop();
    this.audio = null;
    for (const sender of [this.cameraSender, this.screenSender]) if (sender) sender.stop();
    this.cameraSender = null;
    this.screenSender = null;
  }

  // -- comandos para el Asgard --------------------------------------------------------- //
  command(name, args = {}) {
    if (this.session === null || !this.link) return false;
    return this.link.sendControl({ op: "cmd", cmd: name, ...args });
  }

  setCameraMode(mode) { return this.command("ptz_mode", { mode }); }
  setPanTilt(pan, tilt) { return this.command("ptz_set", { pan: Math.round(pan * 10) / 10, tilt: Math.round(tilt * 10) / 10 }); }
  nudge(dpan, dtilt) { return this.command("ptz_nudge", { dpan, dtilt }); }
  center() { return this.command("ptz_center"); }
  lookAt(x, y) { return this.command("ptz_look", { x: Math.round(x * 1e4) / 1e4, y: Math.round(y * 1e4) / 1e4 }); }
  selectPersonAt(x, y) { return this.command("track_select", { x: Math.round(x * 1e4) / 1e4, y: Math.round(y * 1e4) / 1e4 }); }
  selectPerson(trackId) { return this.command("track_select", { id: trackId }); }
  releaseTarget() { return this.command("track_release"); }
  savePreset(name) { return this.command("preset_save", { name }); }
  gotoPreset(name) { return this.command("preset_goto", { name }); }
  deletePreset(name) { return this.command("preset_delete", { name }); }
  setTracking(params) { return this.command("tracking_params", params); }
  setDetection(enabled) { return this.command("ai", { detect: !!enabled }); }
  setHand(raised) { return this.command("hand", { raised: !!raised }); }

  setDebug(enabled) {
    this.debug = enabled;
    return this.command("debug", { enabled: !!enabled });
  }

  sendChat(text) {
    const value = text.trim();
    if (!value || value.length > MAX_CHAT_LENGTH) return null;
    this.chatIds += 1;
    const messageId = `w${this.chatIds}`;
    return this.command("chat", { id: messageId, text: value }) ? messageId : null;
  }

  /** Id of the person drawn under a point (when the detections are recent). */
  personAt(x, y) {
    if (performance.now() / 1000 - (this.detections.at || 0) > 1.5) return null;
    let best = null;
    for (const item of this.detections.items || []) {
      const box = item.box;
      if (!Array.isArray(box) || box.length !== 4) continue;
      const [bx, by, bw, bh] = box;
      if (bx <= x && x <= bx + bw && by <= y && y <= by + bh && (best === null || bw * bh < best[0])) best = [bw * bh, item.id];
    }
    return best ? best[1] : null;
  }

  // -- qué se recibe y qué se envía ------------------------------------------------- //
  setReceive(video, audio) {
    if (video !== undefined && video !== null) {
      this.receiveVideo = video;
      if (!video) this.remoteFrame = null;
    }
    if (audio !== undefined && audio !== null) this.receiveAudio = audio;
    this._applyAudioFlags();
    this.command("media", { video: this.receiveVideo, audio: this.receiveAudio });
  }

  setMicrophone(on) {
    this.sendMicrophone = on;
    this._applyAudioFlags();
    this._sendRemoteStreams();
  }

  async setAudioDevices(microphone, speaker) {
    this.settings.microphone = microphone;
    this.settings.speaker = speaker;
    if (!this.audio) return "";
    const problems = [];
    const speakerError = await this.audio.setSpeaker(speaker);
    if (speakerError) problems.push(speakerError);
    this.audio.errors = [];
    await this.audio.openMicrophone(microphone);
    problems.push(...this.audio.errors);
    this._sendRemoteStreams();
    return problems.join("; ");
  }

  playTestTone() {
    return this.audio !== null && this.audio.playTone();
  }

  get cameraRunning() { return this.cameraSender !== null && this.cameraSender.running; }
  get screenRunning() { return this.screenSender !== null && this.screenSender.running; }

  async startCamera(deviceId, profileName) {
    this.stopCamera(false);
    if (!this.link) return;
    const profile = CAMERA_PROFILES[profileName] || CAMERA_PROFILES.Medium;
    try {
      this.cameraSender = await startCamera(this.link, deviceId, profile, (message) => this._captureFailed(message));
    } catch (error) {
      this._captureFailed(tr("The camera could not be opened: {error}", { error: error.message || error.name }));
      return;
    }
    this._sendRemoteStreams();
  }

  stopCamera(notify = true) {
    if (this.cameraSender) this.cameraSender.stop();
    this.cameraSender = null;
    if (notify) this._sendRemoteStreams();
  }

  async startScreen(profileName) {
    this.stopScreen(false);
    if (!this.link) return;
    const profile = SCREEN_PROFILES[profileName] || SCREEN_PROFILES.High;
    try {
      this.screenSender = await startScreen(this.link, profile, (message) => this._captureFailed(message));
    } catch (error) {
      if (error && error.name === "NotAllowedError") return;     // el usuario canceló el diálogo
      this._captureFailed(tr("The screen could not be captured: {error}", { error: error.message || error.name }));
      return;
    }
    this._sendRemoteStreams();
  }

  stopScreen(notify = true) {
    if (this.screenSender) this.screenSender.stop();
    this.screenSender = null;
    if (notify) this._sendRemoteStreams();
  }

  _captureFailed(message) {
    this.emit("capture_error", message);
    this._sendRemoteStreams();
  }

  // -- medios recibidos -------------------------------------------------------------- //
  _onFrame(stream, meta, data) {
    if (stream === VIDEO && this.session !== null && this.receiveVideo) {
      this.remoteFrame = { data, meta, at: performance.now() };
      this.remoteFrames += 1;
      this.lastFrameAt = performance.now();
    }
  }

  takeRemoteFrame() {
    const frame = this.remoteFrame;
    this.remoteFrame = null;
    return frame;
  }

  remoteFrameAge() {
    return this.lastFrameAt ? (performance.now() - this.lastFrameAt) / 1000 : Infinity;
  }

  localPreview() {
    for (const sender of [this.screenSender, this.cameraSender]) if (sender && sender.running) return sender.stream;
    return null;
  }

  stats() {
    return {
      link: this.link ? this.link.stats() : {},
      audio: this.audio && this.audio.active ? this.audio.stats() : null,
      camera_fps: this.cameraSender ? this.cameraSender.fps : 0,
      screen_fps: this.screenSender ? this.screenSender.fps : 0,
      remote_frames: this.remoteFrames,
    };
  }

  shutdown() {
    if (this.session !== null && this.connected) this.closeSession();
    this.disconnect();
  }
}

export function avatarBase64(dataUrl) {
  return typeof dataUrl === "string" && dataUrl.startsWith("data:image/jpeg;base64,") ? dataUrl.slice(23) : "";
}

export { b64encode };
