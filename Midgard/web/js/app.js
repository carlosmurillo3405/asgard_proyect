// Midgard Web: la interfaz (equivalente a midgard/ui/*.py) unida al controlador.
// Páginas: acceso, transición, listado de Asgard, llamada y perfil.

import { cameraSupported, CAMERA_PROFILES, describeProfile, SCREEN_PROFILES, screenShareSupported } from "./capture.js";
import { LANGUAGE_NAMES, LANGUAGES, setLanguage, tr } from "./i18n.js";
import { STATE_CONNECTED, STATE_CONNECTING } from "./link.js";
import { STATUS_AVAILABLE, STATUS_BUSY, STATUS_OFFLINE } from "./protocol.js";
import { avatarBase64, endReasonLabel, isPackagedApp, MidgardController, ServerChoice, VERSION } from "./session.js";
import { isAdvanced, loadSettings, saveSettings, VIEW_ADVANCED, VIEW_DEFAULT } from "./settings.js";
import {
  askText, avatar, button, clockText, dialog, el, field, icon, indicator, logo, messageList, modal, roundButton,
  segmented, select, separator, setOptions, shake, switchControl, toast,
} from "./ui.js";
import { AsgardView, cameraPad, targetText } from "./video.js";

const COLOR = { success: "var(--success)", warning: "var(--warning)", error: "var(--error)", dim: "var(--text-dim)" };

function languageOptions() {
  return [["auto", tr("System language")], ...LANGUAGES.map((code) => [code, LANGUAGE_NAMES[code]])];
}

function statusInfo(status) {
  return {
    [STATUS_AVAILABLE]: [tr("Available"), COLOR.success],
    [STATUS_BUSY]: [tr("In a session"), COLOR.warning],
    [STATUS_OFFLINE]: [tr("Offline"), COLOR.dim],
  }[status] || [status, COLOR.dim];
}

function features(item) {
  const capabilities = item.capabilities || {};
  const parts = [];
  if (capabilities.ai) parts.push(tr("AI tracking"));
  if (capabilities.pan_tilt) parts.push(capabilities.pan_tilt_simulated ? tr("Moving camera (simulated)") : tr("Moving camera"));
  if (capabilities.actuator) parts.push(tr("Hand"));
  const video = capabilities.video || {};
  if (video.width) parts.push(`${video.width}×${video.height}`);
  return parts.join(" · ");
}

function qualityName(profile) {
  return { Low: tr("Low"), Medium: tr("Medium"), High: tr("High"), Excellent: tr("Maximum") }[profile] || profile;
}

function localDate(text) {
  if (!text) return "—";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? text : date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
}

function duration(start, end) {
  const seconds = Math.round((new Date(end) - new Date(start)) / 1000);
  if (!start || !end || Number.isNaN(seconds)) return tr("in progress");
  const hours = Math.floor(Math.max(0, seconds) / 3600);
  const rest = Math.max(0, seconds) % 3600;
  if (hours) return tr("{hours} h {minutes} min", { hours, minutes: String(Math.floor(rest / 60)).padStart(2, "0") });
  return tr("{minutes} min {seconds} s", { minutes: Math.floor(rest / 60), seconds: String(rest % 60).padStart(2, "0") });
}

function rectOf(node) {
  const box = node.getBoundingClientRect();
  return { x: box.left, y: box.top, w: box.width, h: box.height };
}

// --------------------------------------------------------------------------- //
// Cabecera común
// --------------------------------------------------------------------------- //
class Header {
  constructor(app, subtitle) {
    this.app = app;
    this.logo = logo();
    this.title = el("span.title", { text: "MIDGARD" });
    this.separator = separator(true);
    this.subtitle = el("span.subtitle", { text: subtitle });
    this.extras = el("div.extras");
    this.view = select([[VIEW_DEFAULT, tr("Default view")], [VIEW_ADVANCED, tr("Advanced view (developer)")]],
                       app.settings.view_mode, "field bar");
    this.view.title = tr("Switches between the simple view and the view with developer tools");
    this.view.addEventListener("change", () => app.changeView(this.view.value));
    this.avatar = avatar(38);
    this.name = el("span.name");
    this.chip = el("div.chip", { title: tr("View profile"), onclick: () => app.openProfile() }, [
      this.avatar, el("div.names", {}, [this.name, el("span.link", { text: tr("View profile") })]),
    ]);
    this.node = el("div.header", {}, [this.logo, this.title, this.separator, this.subtitle, this.extras,
                                      el("div.spacer"), this.view, this.chip]);
  }

  setUser(name, image) {
    this.name.textContent = name;
    this.avatar.setPerson(name, image);
  }

  setView(key) {
    this.view.value = key;
  }
}

// --------------------------------------------------------------------------- //
// Acceso
// --------------------------------------------------------------------------- //
class LoginPage {
  constructor(app) {
    this.app = app;
    this.busy = false;
    this.brandLogo = logo();
    this.compactLogo = logo();
    this.username = field({ size: "large", maxLength: 64, autocomplete: "username", value: app.settings.username });
    this.password = field({ size: "large", type: "password", maxLength: 256, autocomplete: "current-password" });
    this.reveal = button("", { variant: "ghost", icon: "eye", title: tr("Show or hide the password"), onclick: () => this.togglePassword() });
    this.reveal.classList.add("reveal", "icon-only");
    this.error = el("div.error-text", { hidden: true });
    this.spinner = el("span.spinner", { hidden: true });
    this.buttonText = el("span", { text: tr("Enter Asgard") });
    this.submit = el("button.button.primary.large", { type: "button", onclick: () => this.send() }, [this.spinner, this.buttonText]);
    this.card = el("div.card.login-card", {}, [
      el("h1", { text: tr("Sign in") }),
      el("p.intro", { text: tr("Enter your credentials to access the Asgard system.") }),
      el("div.group", {}, [el("label", { text: tr("Username") }), this.username]),
      el("div.group", {}, [el("label", { text: tr("Password") }), el("div.field-wrap", {}, [this.password, this.reveal])]),
      this.error,
      this.submit,
    ]);
    this.status = indicator("");
    this.status.hidden = true;
    this.configure = button(tr("Connection settings"), { variant: "link", onclick: () => app.connectionSettings() });
    this.configure.hidden = true;
    this.language = select(languageOptions(), app.settings.language, "field bar");
    this.language.title = tr("Language of Midgard");
    this.language.addEventListener("change", () => app.changeLanguage(this.language.value));
    this.node = el("div.page.login", {}, [
      el("div.login-body", {}, [
        el("div.login-panel.runes", {}, [el("div.login-brand", {}, [
          this.brandLogo, el("div.title", { text: "MIDGARD" }), el("div.subtitle", { text: tr("Asgard System") }),
        ])]),
        el("div.login-divider"),
        el("div.login-side", {}, [
          el("div.compact-brand", {}, [this.compactLogo, el("span.title", { text: "MIDGARD" })]),
          this.card,
          el("div.login-note", {}, [icon("lock", 13), el("span", { text: tr("Access restricted to authorized users.") })]),
          el("div.login-status", {}, [this.status, this.configure]),
        ]),
      ]),
      el("div.footer", {}, [
        el("span", { text: tr("Asgard System") }), el("span.spacer"), this.language,
        el("span.version", { text: isPackagedApp() ? tr("Mobile app · v{version}", { version: VERSION }) : tr("Web client · v{version}", { version: VERSION }) }),
      ]),
    ]);
    this.username.addEventListener("keydown", (event) => { if (event.key === "Enter") this.password.focus(); });
    this.password.addEventListener("keydown", (event) => { if (event.key === "Enter") this.send(); });
    for (const input of [this.username, this.password]) input.addEventListener("input", () => this.clearError());
  }

  togglePassword() {
    const hidden = this.password.type === "password";
    this.password.type = hidden ? "text" : "password";
    this.reveal.replaceChildren(icon(hidden ? "eye-off" : "eye", 16));
  }

  clearError() {
    if (this.error.hidden) return;
    this.error.hidden = true;
    for (const input of [this.username, this.password]) input.classList.remove("invalid");
  }

  send() {
    if (this.busy) return;
    const username = this.username.value.trim();
    const password = this.password.value;
    if (!username || !password) {
      this.showError(tr("Enter your username and password."), username ? this.password : this.username);
      return;
    }
    this.app.signIn(username, password);
  }

  focus() {
    (this.username.value ? this.password : this.username).focus();
  }

  setBusy(busy, text = "") {
    this.busy = busy;
    this.buttonText.textContent = busy ? text || tr("Checking credentials…") : tr("Enter Asgard");
    this.spinner.hidden = !busy;
    this.username.disabled = busy;
    this.password.disabled = busy;
  }

  showError(message, input = null) {
    this.setBusy(false);
    this.error.textContent = message;
    this.error.hidden = false;
    for (const node of input ? [input] : [this.username, this.password]) node.classList.add("invalid");
    shake(this.card);
    const target = input || this.password;
    target.focus();
    target.select();
  }

  setServer(state, text) {
    const colors = { searching: COLOR.warning, connected: COLOR.success, error: COLOR.error };
    this.status.set(text, colors[state] || COLOR.dim, state === "searching");
    this.status.hidden = !text;
    this.configure.hidden = state !== "error";
  }

  reset(message = "") {
    this.setBusy(false);
    this.password.value = "";
    if (message) {
      this.error.textContent = message;
      this.error.hidden = false;
    } else {
      this.error.hidden = true;
    }
    this.focus();
  }

  brandLogoNode() {
    return this.brandLogo.offsetParent ? this.brandLogo : this.compactLogo;
  }
}

// --------------------------------------------------------------------------- //
// Listado de Asgard
// --------------------------------------------------------------------------- //
class ServerSection {
  constructor(app, onConnect) {
    this.app = app;
    this.address = field({ mono: true, placeholder: "bifrost.example.com" });
    this.port = field({ mono: true, inputMode: "numeric", maxLength: 5 });
    this.tls = el("input", { type: "checkbox" });
    this.connectButton = button(tr("Connect"), { variant: "primary", onclick: () => this.connect() });
    this.status = indicator(tr("Not connected."));
    this.automatic = button(tr("Use the automatic server"), { variant: "link", onclick: () => app.useAutomatic() });
    this.automatic.title = tr("Goes back to the server of this page or to server.json");
    this.onConnect = onConnect;
    this.node = el("div.server-section", {}, [
      el("div.section-title", {}, [el("h2", { text: tr("Bifröst server") })]),
      el("div.card.server-card", {}, [
        el("div.server-grid", {}, [
          el("div.group.wide", {}, [el("label", { text: tr("Address (IP or domain)") }), this.address]),
          el("div.group", {}, [el("label", { text: tr("Port") }), this.port]),
          el("label.check", {}, [this.tls, el("span", { text: tr("Secure connection (TLS)") })]),
          this.connectButton,
        ]),
        el("div.server-status", {}, [this.status, this.automatic]),
      ]),
    ]);
    for (const input of [this.address, this.port]) {
      input.addEventListener("keydown", (event) => { if (event.key === "Enter") this.connect(); });
    }
  }

  setValues(host, port, tls) {
    this.address.value = host || "";
    this.port.value = String(port || 8080);
    this.tls.checked = !!tls;
  }

  setManual(manual) {
    this.automatic.hidden = !manual;
  }

  error(input, message) {
    input.classList.add("invalid");
    shake(input);
    this.status.set(message, COLOR.error);
    setTimeout(() => input.classList.remove("invalid"), 2500);
  }

  connect() {
    const host = this.address.value.trim();
    if (!host) {
      this.error(this.address, tr("Enter Bifröst's IP or domain."));
      return;
    }
    const port = Number(this.port.value || 8080);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      this.error(this.port, tr("The port must be a number between 1 and 65535."));
      return;
    }
    this.onConnect(host, port, this.tls.checked);
  }
}

class LobbyPage {
  constructor(app) {
    this.app = app;
    this.items = [];
    this.selectedId = "";
    this.header = new Header(app, tr("Asgard System"));
    this.server = new ServerSection(app, (host, port, tls) => app.connectManual(host, port, tls));
    this.summary = el("span.soft.small");
    this.hint = el("span.hint", { text: tr("Select an available Asgard.") });
    this.refreshButton = button(tr("Refresh"), { icon: "refresh-cw", onclick: () => this.refresh() });
    this.enterButton = button(tr("Enter Asgard"), { variant: "primary", icon: "arrow-right", iconAfter: true, onclick: () => this.enterSelected() });
    this.body = el("tbody");
    this.empty = el("div.table-empty", { text: tr("Loading the Asgards…") });
    const heads = [["name", tr("Name")], ["location", tr("Location")], ["status", tr("Status")], ["features", tr("Features")],
                   ["identifier", tr("Identifier")]];
    this.table = el("table.asgards", {}, [
      el("thead", {}, [el("tr", {}, heads.map(([key, text]) => el(`th.${key}`, { text })))]),
      this.body,
    ]);
    this.connection = indicator("");
    this.node = el("div.page.lobby", {}, [
      this.header.node,
      el("div.lobby-content.scroll", {}, [
        this.server.node,
        el("div.section-title", {}, [el("h2", { text: "Asgard" }), el("span.spacer"), this.summary]),
        el("div.card.lobby-card", {}, [
          el("div.lobby-actions", {}, [this.hint, this.refreshButton, this.enterButton]),
          el("div.table-wrap.scroll", {}, [this.table, this.empty]),
          this.connection,
        ]),
      ]),
    ]);
    this.updateButton();
  }

  refresh() {
    this.refreshButton.disabled = true;
    setTimeout(() => { this.refreshButton.disabled = false; }, 900);
    this.app.c.refreshList();
  }

  selected() {
    return this.items.find((item) => item.id === this.selectedId) || null;
  }

  enterSelected() {
    const item = this.selected();
    if (item && item.status !== STATUS_OFFLINE) this.app.enterAsgard(item.id);
  }

  updateButton() {
    const item = this.selected();
    this.enterButton.disabled = !item || item.status === STATUS_OFFLINE;
    if (!item) this.enterButton.title = tr("Select an Asgard from the list.");
    else if (item.status === STATUS_OFFLINE) this.enterButton.title = tr("That Asgard is not connected right now.");
    else this.enterButton.title = tr("Enter «{name}»", { name: item.name || item.id });
  }

  setAsgards(items, preferred = "") {
    this.items = items;
    if (!this.items.some((item) => item.id === this.selectedId)) {
      const wanted = items.find((item) => item.id === preferred);
      const available = items.find((item) => item.status === STATUS_AVAILABLE);
      this.selectedId = (wanted || available || {}).id || "";
    }
    this.body.replaceChildren(...items.map((item) => this.row(item)));
    const free = items.filter((item) => item.status === STATUS_AVAILABLE).length;
    this.summary.textContent = items.length ? tr("{assigned} assigned · {available} available", { assigned: items.length, available: free }) : "";
    this.empty.hidden = items.length > 0;
    this.empty.textContent = tr("Your user has no Asgards assigned yet.\nAsk the Bifröst administrator to give you access.");
    this.hint.textContent = items.length && !free ? tr("No Asgard is available right now; the list updates by itself.")
      : tr("Select an available Asgard.");
    this.updateButton();
  }

  row(item) {
    const [statusText, color] = statusInfo(item.status);
    const status = el("span.status", { text: statusText });
    status.style.setProperty("--dot", color);
    const node = el(`tr.row${item.status === STATUS_OFFLINE ? ".offline" : ""}${item.id === this.selectedId ? ".selected" : ""}`, {
      title: item.status === STATUS_BUSY ? tr("This Asgard is in a call.")
        : item.status === STATUS_OFFLINE ? tr("This Asgard is not connected to Bifröst.") : tr("Double-click to enter."),
    }, [
      el("td.name", { text: item.name || "" }), el("td.location", { text: item.location || "" }),
      el("td.status", {}, [status]), el("td.features", { text: features(item) }), el("td.identifier.mono", { text: item.id }),
    ]);
    node.addEventListener("click", () => {
      this.selectedId = item.id;
      for (const other of this.body.children) other.classList.toggle("selected", other === node);
      this.updateButton();
    });
    node.addEventListener("dblclick", () => { if (item.status !== STATUS_OFFLINE) this.app.enterAsgard(item.id); });
    return node;
  }

  setConnection(text, color, pulse = false) {
    this.connection.set(text, color, pulse);
    this.server.status.set(text, color, pulse);
  }

  setView(advanced) {
    this.header.setView(advanced ? VIEW_ADVANCED : VIEW_DEFAULT);
    this.server.node.hidden = !advanced;
    this.connection.hidden = advanced;
    this.table.classList.toggle("advanced", advanced);
  }
}

// --------------------------------------------------------------------------- //
// Llamada
// --------------------------------------------------------------------------- //
function section(title, detail = "") {
  return el("div.section", {}, [el("span.title", { text: title }), detail ? el("span.detail", { text: detail }) : null]);
}

function slider(min, max, step, value) {
  return el("input", { type: "range", min, max, step, value });
}

class CallPage {
  constructor(app) {
    this.app = app;
    this.c = app.c;
    this.settings = app.settings;
    this.active = false;
    this.started = 0;
    this.hand = false;
    this.incomingFps = 0;
    this.frames = 0;
    this.measured = performance.now();
    this.lastFrameMeta = {};
    this.header = new Header(app, "");
    this.indicator = indicator("", COLOR.success);
    this.header.extras.append(this.indicator);
    this.view = new AsgardView(this);
    this.bar = this.buildBar();
    this.stage = el("div.stage", {}, [this.view.node, this.bar.node]);
    this.panel = this.buildPanel();
    this.body = el("div.call-body", {}, [this.stage, this.panel.node]);
    this.node = el("div.page.call", {}, [this.header.node, this.body]);
    new ResizeObserver(() => this.place()).observe(this.body);
    this.node.addEventListener("pointerdown", () => { if (this.c.audio) this.c.audio.resume(); });
    this.wakeLock = null;
    document.addEventListener("visibilitychange", () => { if (this.active) this.keepAwake(true); });
  }

  /** Keeps the screen on during the call (phones and tablets), where the browser allows it. */
  async keepAwake(on) {
    try {
      if (on && !this.wakeLock && "wakeLock" in navigator && document.visibilityState === "visible") {
        this.wakeLock = await navigator.wakeLock.request("screen");
        this.wakeLock.addEventListener("release", () => { this.wakeLock = null; });
      } else if (!on && this.wakeLock) {
        const lock = this.wakeLock;
        this.wakeLock = null;
        await lock.release();
      }
    } catch {
      // sin HTTPS o sin permiso: la pantalla se apaga como siempre
    }
  }

  get advanced() {
    return isAdvanced(this.settings);
  }

  dialogHost() {
    return this.node;
  }

  notify(text, kind = "info") {
    toast(text, kind);
    this.dev.log(text);
  }

  latencyText() {
    const rtt = this.c.link ? this.c.link.rttMs : null;
    return rtt !== null && rtt !== undefined ? `${Math.round(rtt)} ms` : "—";
  }

  // -- barra --------------------------------------------------------------------- //
  buildBar() {
    const b = {};
    b.mic = roundButton("mic", tr("Microphone"), () => this.setMicrophone(!this.c.sendMicrophone));
    b.camera = roundButton("video", tr("My camera"), () => this.setCamera(!this.c.cameraRunning));
    b.screen = roundButton("monitor-up", tr("Screen"), () => this.setScreen(!this.c.screenRunning));
    b.hand = roundButton("hand", tr("Hand"), () => this.c.setHand(!this.hand));
    b.watch = roundButton("eye", tr("Watch"), () => this.setReceive(!this.c.receiveVideo, null));
    b.listen = roundButton("volume-2", tr("Listen"), () => this.setReceive(null, !this.c.receiveAudio));
    b.chat = roundButton("message-square-text", tr("Chat"), () => this.togglePanel(null, "chat"));
    b.controls = roundButton("move", tr("Room camera"), () => this.togglePanel(null, "camera"));
    b.settings = roundButton("settings", tr("Settings"), () => this.togglePanel(null, "settings"));
    b.dev = roundButton("terminal", tr("Development"), () => this.togglePanel(null, "dev"));
    b.leave = roundButton("phone-off", tr("Leave"), () => this.confirmLeave());
    b.leave.setMode("danger");
    b.mic.title = tr("Turn my microphone on or mute it");
    b.camera.title = tr("Send my camera to the classroom");
    b.screen.title = tr("Share my screen in the classroom");
    b.hand.title = tr("Raise or lower the Asgard's hand");
    b.watch.title = tr("Receive the Asgard's video");
    b.listen.title = tr("Listen to the Asgard's audio");
    b.chat.title = tr("Messages for the classroom screen");
    b.controls.title = tr("Move the classroom camera");
    b.settings.title = tr("Microphone, speaker, camera, screen and quality");
    b.dev.title = tr("Developer tools");
    b.leave.title = tr("Leave the call");
    b.camera.hidden = !cameraSupported;
    b.screen.hidden = !screenShareSupported;
    const groups = [[b.mic, b.camera, b.screen], [b.hand], [b.watch, b.listen], [b.chat, b.controls, b.settings, b.dev], [b.leave]];
    const children = [];
    groups.forEach((group, index) => {
      if (index) children.push(el("span.group-separator"));
      children.push(...group);
    });
    b.node = el("div.call-bar", {}, children);
    return b;
  }

  updateButtons() {
    const b = this.bar;
    const mic = this.c.sendMicrophone;
    b.mic.setIcon(mic ? "mic" : "mic-off");
    b.mic.setMode(mic ? "normal" : "off");
    b.mic.setLabel(mic ? tr("Microphone") : tr("Muted"));
    b.camera.setIcon(this.c.cameraRunning ? "video" : "video-off");
    b.camera.setMode(this.c.cameraRunning ? "highlight" : "normal");
    b.screen.setIcon(this.c.screenRunning ? "monitor-off" : "monitor-up");
    b.screen.setMode(this.c.screenRunning ? "highlight" : "normal");
    b.screen.setLabel(this.c.screenRunning ? tr("Sharing") : tr("Screen"));
    b.hand.setMode(this.hand ? "highlight" : "normal");
    b.hand.setLabel(this.hand ? tr("Lower hand") : tr("Hand"));
    b.watch.setIcon(this.c.receiveVideo ? "eye" : "eye-off");
    b.watch.setMode(this.c.receiveVideo ? "normal" : "off");
    b.listen.setIcon(this.c.receiveAudio ? "volume-2" : "volume-x");
    b.listen.setMode(this.c.receiveAudio ? "normal" : "off");
    const open = this.settings.side_open;
    const current = this.panel.tabs.value();
    for (const [roundButtonNode, key] of [[b.chat, "chat"], [b.controls, "camera"], [b.settings, "settings"], [b.dev, "dev"]]) {
      roundButtonNode.setMode(open && current === key ? "highlight" : "normal");
    }
  }

  // -- panel lateral ------------------------------------------------------------------ //
  buildPanel() {
    const panel = {};
    panel.tabs = segmented(this.tabOptions(), (key) => this.showTab(key));
    const close = button("", { variant: "ghost", icon: "x", title: tr("Close the panel"), onclick: () => this.togglePanel(false) });
    close.classList.add("icon-only");
    this.chat = this.buildChat();
    this.camera = this.buildCameraTab();
    this.audioVideo = this.buildSettingsTab();
    this.dev = this.buildDevTab();
    panel.pages = { chat: this.chat.node, camera: this.camera.node, settings: this.audioVideo.node, dev: this.dev.node };
    panel.node = el("div.side-panel", {}, [el("div.tabs-row", {}, [panel.tabs, close]), ...Object.values(panel.pages)]);
    return panel;
  }

  tabOptions() {
    const options = [["chat", tr("Chat")], ["camera", tr("Camera")], ["settings", tr("Settings")]];
    if (this.advanced) options.push(["dev", tr("Development")]);
    return options;
  }

  showTab(key) {
    if (!this.panel.pages[key] || (key === "dev" && !this.advanced)) key = "chat";
    this.panel.tabs.setValue(key);
    for (const [name, page] of Object.entries(this.panel.pages)) page.hidden = name !== key;
    this.settings.side_panel = key;
    saveSettings(this.settings);
    if (key === "settings") this.app.loadDevices();
    this.updateButtons();
  }

  togglePanel(open = null, tab = "") {
    if (open === null) open = !(this.settings.side_open && (!tab || this.panel.tabs.value() === tab));
    if (tab) this.showTab(tab);
    this.settings.side_open = open;
    saveSettings(this.settings);
    this.place();
    this.updateButtons();
  }

  place() {
    const narrow = this.body.clientWidth < 1060;
    const open = this.settings.side_open;
    this.panel.node.classList.toggle("closed", !open);
    const margin = this.body.clientWidth >= 760 ? 24 : 12;
    this.stage.style.right = `${open && !narrow ? 372 + 16 + margin : margin}px`;
    const width = this.stage.clientWidth;
    this.bar.node.classList.toggle("bar-labels-off", width < 900);
    this.bar.watch.hidden = width < 640;
    this.bar.listen.hidden = width < 640;
    this.bar.controls.hidden = width < 560;
  }

  buildChat() {
    const messages = messageList(tr("The messages you write will appear on the classroom screen."));
    const input = field({ size: "large", placeholder: tr("Write a message…"), maxLength: 1000 });
    const send = () => {
      const text = input.value.trim();
      if (!text) return;
      const identifier = this.c.sendChat(text);
      if (identifier === null) {
        messages.system(tr("The message could not be sent (is there a connection with the Asgard?)."));
        return;
      }
      input.value = "";
      messages.add(text, tr("You"), clockText(), true, identifier, tr("Sending…"));
    };
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") send(); });
    const sendButton = button("", { variant: "primary", icon: "send-horizontal", title: tr("Send (Enter)"), onclick: send });
    const node = el("div.tab", {}, [messages, el("div.chat-input", {}, [input, sendButton])]);
    return { node, messages, input };
  }

  buildCameraTab() {
    const tab = {};
    tab.mode = segmented([["manual", tr("Manual")], ["follow", tr("Follow person")], ["auto", tr("Automatic")]],
                         (mode) => this.c.setCameraMode(mode));
    tab.target = el("span.grow.soft", { text: tr("No person chosen.") });
    tab.release = button(tr("Stop following"), { onclick: () => this.c.releaseTarget() });
    tab.pad = cameraPad(150, false, (dpan, dtilt) => this.c.nudge(dpan, dtilt), () => this.c.center());
    tab.pan = slider(10, 170, 0.1, 90);
    tab.tilt = slider(40, 140, 0.1, 90);
    tab.panValue = el("span.value", { text: "90°" });
    tab.tiltValue = el("span.value", { text: "90°" });
    tab.draggingUntil = 0;
    let lastSent = 0;
    for (const [input, value] of [[tab.pan, tab.panValue], [tab.tilt, tab.tiltValue]]) {
      input.addEventListener("input", () => {
        value.textContent = `${Math.round(input.value)}°`;
        tab.draggingUntil = performance.now() + 1000;
        if (performance.now() - lastSent > 120) {
          lastSent = performance.now();
          this.c.setPanTilt(Number(tab.pan.value), Number(tab.tilt.value));
        }
      });
      input.addEventListener("change", () => this.c.setPanTilt(Number(tab.pan.value), Number(tab.tilt.value)));
    }
    tab.presets = select([], "", "field");
    tab.go = button(tr("Go"), { icon: "locate-fixed", onclick: () => { if (tab.presets.value) this.c.gotoPreset(tab.presets.value); } });
    tab.save = button(tr("Save…"), {
      icon: "bookmark",
      onclick: () => askText({ title: tr("Save position"), label: tr("Name of the position (for example: whiteboard)"),
                               onAccept: (name) => this.c.savePreset(name) }),
    });
    tab.remove = button("", {
      icon: "trash-2", title: tr("Delete the chosen position"),
      onclick: () => {
        const name = tab.presets.value;
        if (!name) return;
        dialog({ title: tr("Delete position"), message: tr("Delete the position «{name}»?", { name }), accept: tr("Delete"),
                 danger: true, icon: "trash-2", onAccept: () => this.c.deletePreset(name) });
      },
    });
    tab.remove.classList.add("icon-only");
    tab.node = el("div.tab.scroll", { hidden: true }, [
      section(tr("Camera mode")), tab.mode,
      el("div.row", {}, [tab.target, tab.release]),
      section(tr("Move the camera"), tr("Hold an arrow down; Shift moves faster. The keyboard arrows work too.")),
      el("div.row", {}, [el("span.grow"), tab.pad, el("span.grow")]),
      section(tr("Position")),
      el("div.row", {}, [el("span.grow.soft", { text: tr("Left / right (pan)") }), tab.panValue]), tab.pan,
      el("div.row", {}, [el("span.grow.soft", { text: tr("Down / up (tilt)") }), tab.tiltValue]), tab.tilt,
      section(tr("Saved positions"), tr("Save frequent framings (whiteboard, desk…).")),
      tab.presets,
      el("div.row", {}, [tab.go, tab.save, tab.remove]),
      el("span.soft.small", { text: tr("Tip: click a person in the video to follow them, or any other point to aim the camera there.") }),
    ]);
    tab.go.classList.add("grow");
    tab.save.classList.add("grow");
    return tab;
  }

  buildSettingsTab() {
    const tab = {};
    tab.microphone = select([["", tr("System default")]], this.settings.microphone, "field");
    tab.speaker = select([["", tr("System default")]], this.settings.speaker, "field");
    tab.level = el("div.level", {}, [el("div")]);
    tab.test = button(tr("Test"), { icon: "volume-2", title: tr("Plays a tone on the chosen speaker"),
                                    onclick: () => { if (!this.c.playTestTone()) this.notify(tr("The audio is not active yet."), "warning"); } });
    tab.sendMic = switchControl(tr("Send my microphone"), this.c.sendMicrophone, (on) => this.setMicrophone(on));
    tab.listen = switchControl(tr("Listen to the Asgard"), this.c.receiveAudio, (on) => this.setReceive(null, on));
    tab.audioStatus = el("span.soft.small");
    tab.watch = switchControl(tr("Watch the Asgard's video"), this.c.receiveVideo, (on) => this.setReceive(on, null));
    tab.camera = select([], this.settings.camera, "field");
    tab.findCameras = button("", { icon: "refresh-cw", title: tr("Look for cameras again"), onclick: () => this.app.loadDevices(true) });
    tab.findCameras.classList.add("icon-only");
    const quality = (profiles, current) => select(Object.entries(profiles).map(([name, p]) =>
      [name, `${qualityName(name)} · ${p.height}p, ${p.fps} fps`]), current, "field");
    tab.cameraQuality = quality(CAMERA_PROFILES, this.settings.camera_profile);
    tab.cameraDetail = el("span.dim.small", { text: describeProfile(CAMERA_PROFILES[tab.cameraQuality.value]) });
    tab.sendCamera = switchControl(tr("Send my camera to the classroom"), false, (on) => this.setCamera(on));
    tab.screenQuality = quality(SCREEN_PROFILES, this.settings.screen_profile);
    tab.screenDetail = el("span.dim.small", { text: describeProfile(SCREEN_PROFILES[tab.screenQuality.value]) });
    tab.share = switchControl(tr("Share my screen"), false, (on) => this.setScreen(on));
    tab.cameraQuality.addEventListener("change", () => {
      const name = tab.cameraQuality.value;
      tab.cameraDetail.textContent = describeProfile(CAMERA_PROFILES[name]);
      this.settings.camera_profile = name;
      saveSettings(this.settings);
      if (this.c.cameraRunning) this.c.startCamera(this.settings.camera, name).then(() => this.updateButtons());
    });
    tab.screenQuality.addEventListener("change", () => {
      const name = tab.screenQuality.value;
      tab.screenDetail.textContent = describeProfile(SCREEN_PROFILES[name]);
      this.settings.screen_profile = name;
      saveSettings(this.settings);
    });
    tab.camera.addEventListener("change", () => {
      this.settings.camera = tab.camera.value;
      saveSettings(this.settings);
      if (this.c.cameraRunning) this.c.startCamera(tab.camera.value, this.settings.camera_profile).then(() => this.updateButtons());
    });
    const devices = async () => {
      const error = await this.c.setAudioDevices(tab.microphone.value, tab.speaker.value);
      saveSettings(this.settings);
      if (error) this.notify(tr("Audio: {error}", { error }), "warning");
    };
    tab.microphone.addEventListener("change", devices);
    tab.speaker.addEventListener("change", devices);
    tab.node = el("div.tab.scroll", { hidden: true }, [
      section(tr("Audio"), tr("Always in top quality: 48 kHz, 16 bits.")),
      el("span.soft", { text: tr("Microphone") }), tab.microphone, tab.level,
      el("span.soft", { text: tr("Speaker or headphones") }), el("div.row", {}, [el("div.grow", {}, [tab.speaker]), tab.test]),
      tab.sendMic, tab.listen, tab.audioStatus,
      section(tr("Asgard's video"), tr("The Asgard always sends its top quality.")), tab.watch,
      cameraSupported ? section(tr("My camera")) : null,
      cameraSupported ? el("div.row", {}, [el("div.grow", {}, [tab.camera]), tab.findCameras]) : null,
      cameraSupported ? el("span.soft", { text: tr("Sending quality") }) : null,
      cameraSupported ? tab.cameraQuality : null, cameraSupported ? tab.cameraDetail : null, cameraSupported ? tab.sendCamera : null,
      screenShareSupported ? section(tr("Share screen")) : null,
      screenShareSupported ? el("span.soft", { text: tr("Sending quality") }) : null,
      screenShareSupported ? tab.screenQuality : null, screenShareSupported ? tab.screenDetail : null,
      screenShareSupported ? tab.share : null,
      el("span.soft.small", { text: tr("Use headphones so the classroom does not hear its own echo.") }),
    ]);
    if (!window.isSecureContext) {
      tab.node.prepend(el("span.error-text.small", { text: tr("This page is not on HTTPS: the browser does not allow the microphone or the camera.") }));
    }
    return tab;
  }

  buildDevTab() {
    const tab = {};
    const gauge = (name) => {
      const value = el("span.value");
      const current = el("span.current");
      const target = el("span.target");
      const minimum = el("span");
      const maximum = el("span");
      const node = el("div.gauge", {}, [el("div.head", {}, [el("span", { text: name }), value]), el("div.track"), target, current,
                                        el("div.limits", {}, [minimum, maximum])]);
      node.set = (now, aim, limits) => {
        const [low, high] = limits;
        const x = (v) => `calc(6px + (100% - 12px) * ${Math.max(0, Math.min(1, high > low ? (v - low) / (high - low) : 0.5))})`;
        value.textContent = `${now.toFixed(1)}°  →  ${aim.toFixed(1)}°`;
        current.style.left = x(now);
        target.style.left = x(aim);
        minimum.textContent = `${Math.round(low)}°`;
        maximum.textContent = `${Math.round(high)}°`;
      };
      return node;
    };
    tab.panGauge = gauge(tr("Pan (horizontal)"));
    tab.tiltGauge = gauge(tr("Tilt (vertical)"));
    tab.servoInfo = el("span.soft.small");
    tab.detect = switchControl(tr("Detect people"), true, (on) => this.c.setDetection(on));
    tab.aiInfo = el("span.soft.small");
    tab.params = {};
    tab.paramsUntil = 0;
    const params = [["sensitivity", tr("Sensitivity"), 0.05, 1.5, 0.01, 2], ["speed", tr("Maximum speed (°/s)"), 10, 300, 1, 0],
                    ["deadzone", tr("Dead zone (°)"), 0, 10, 0.1, 1], ["aim_y", tr("Aim point (0 head · 1 feet)"), 0, 1, 0.01, 2]];
    const paramNodes = [];
    for (const [key, title, min, max, step, digits] of params) {
      const input = slider(min, max, step, min);
      const value = el("span.value.small");
      input.addEventListener("input", () => { value.textContent = Number(input.value).toFixed(digits); });
      input.addEventListener("change", () => {
        tab.paramsUntil = performance.now() + 1500;
        this.c.setTracking({ [key]: Number(input.value) });
      });
      tab.params[key] = { input, value, digits };
      paramNodes.push(el("div.row", {}, [el("span.grow.soft.small", { text: title }), value]), input);
    }
    tab.invertPan = switchControl(tr("Invert pan"), false, (on) => this.c.setTracking({ invert_pan: on }));
    tab.invertTilt = switchControl(tr("Invert tilt"), false, (on) => this.c.setTracking({ invert_tilt: on }));
    tab.people = el("div.people");
    const layers = [["show_boxes", tr("Boxes and identifiers")], ["show_trails", tr("Trails (4 s)")],
                    ["show_skeleton", tr("Skeleton (body points)")], ["show_hud", tr("On-screen data")], ["show_grid", tr("Rule-of-thirds grid")]];
    const layerNodes = layers.map(([key, text]) => switchControl(text, this.settings[key], (on) => { this.settings[key] = on; saveSettings(this.settings); }));
    tab.network = el("div.mono-block");
    tab.asgard = el("div.mono-block");
    tab.logBox = el("div.log");
    const copy = button(tr("Copy"), { icon: "copy", onclick: () => navigator.clipboard && navigator.clipboard.writeText(tab.logBox.textContent) });
    tab.node = el("div.tab.scroll", { hidden: true }, [
      section(tr("Servomotors")), tab.panGauge, tab.tiltGauge, tab.servoInfo,
      section(tr("AI tracking")), tab.detect, tab.aiInfo, ...paramNodes,
      el("div.row", {}, [tab.invertPan, tab.invertTilt]),
      el("span", { text: tr("Detected people") }), tab.people,
      section(tr("Layers over the video")), ...layerNodes,
      section(tr("Network and media")), tab.network,
      section("Asgard"), tab.asgard,
      el("div.row", {}, [el("div.grow", {}, [section(tr("Log"))]), copy]), tab.logBox,
    ]);
    tab.log = (text) => {
      const line = `${new Date().toLocaleTimeString()}  ${text}\n`;
      tab.logBox.textContent = (tab.logBox.textContent + line).split("\n").slice(-400).join("\n");
      tab.logBox.scrollTop = tab.logBox.scrollHeight;
    };
    return tab;
  }

  // -- acciones ----------------------------------------------------------------------- //
  confirmLeave() {
    const name = ((this.c.session || {}).asgard || {}).name || tr("the Asgard");
    dialog({ title: tr("Leave the call"), message: tr("The connection with «{name}» will close. The Asgard will go back to idle.", { name }),
             accept: tr("Leave"), danger: true, icon: "phone-off", onAccept: () => this.c.closeSession() });
  }

  setMicrophone(on) {
    this.c.setMicrophone(on);
    this.settings.send_microphone = on;
    saveSettings(this.settings);
    this.updateButtons();
  }

  setReceive(video, audio) {
    this.c.setReceive(video, audio);
    this.settings.receive_video = this.c.receiveVideo;
    this.settings.receive_audio = this.c.receiveAudio;
    saveSettings(this.settings);
    this.updateButtons();
  }

  async setCamera(on) {
    if (on === this.c.cameraRunning) return;
    if (!on) this.c.stopCamera();
    else await this.c.startCamera(this.audioVideo.camera.value || this.settings.camera, this.audioVideo.cameraQuality.value);
    this.updateButtons();
    this.audioVideo.sendCamera.set(this.c.cameraRunning);
  }

  async setScreen(on) {
    if (on === this.c.screenRunning) return;
    if (!on) this.c.stopScreen();
    else await this.c.startScreen(this.audioVideo.screenQuality.value);
    this.updateButtons();
    this.audioVideo.share.set(this.c.screenRunning);
  }

  videoClicked(nx, ny, mouseButton) {
    if (!this.c.inSession) return;
    const person = mouseButton === 1 && this.c.capabilities.ai ? this.c.personAt(nx, ny) : null;
    if (person !== null) this.c.selectPersonAt(nx, ny);
    else this.c.lookAt(nx, ny);
  }

  moveWithKeyboard(key, fast) {
    const step = fast ? 10 : 3;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    if (!moves[key] || !this.c.inSession) return false;
    this.c.nudge(...moves[key]);
    return true;
  }

  // -- ciclo ---------------------------------------------------------------------------- //
  render() {
    if (!this.active) return;
    requestAnimationFrame(() => this.render());
    const frame = this.c.takeRemoteFrame();
    if (frame) {
      this.lastFrameMeta = frame.meta;
      this.frames += 1;
      this.view.showFrame(frame);
    }
    const fresh = this.c.remoteFrameAge() < 3;
    if (!this.c.receiveVideo) {
      this.view.clear();
      this.view.setMessage(tr("Video paused"), tr("Turn on «Watch» to receive the Asgard's video."), "eye-off");
    } else if (!this.c.asgardConnected) {
      this.view.clear();
      this.view.setMessage(tr("The Asgard lost its connection"), tr("Waiting for it to come back…"), "", true);
    } else if (!fresh) {
      this.view.clear();
      this.view.setMessage(tr("Waiting for the Asgard's video…"), tr("The classroom camera is turning on."), "", true);
    }
    this.view.draw();
    this.view.setPreview(this.c.localPreview());
  }

  refresh() {
    if (!this.active) return;
    const now = performance.now();
    this.incomingFps = 0.6 * this.incomingFps + 0.4 * (this.frames / Math.max(0.001, (now - this.measured) / 1000));
    this.frames = 0;
    this.measured = now;
    const seconds = Math.floor((Date.now() - this.started) / 1000);
    if (!this.c.connected) this.indicator.set(tr("Reconnecting to Bifröst…"), COLOR.warning, true);
    else if (!this.c.asgardConnected) this.indicator.set(tr("The Asgard lost its connection"), COLOR.warning, true);
    else {
      const clock = [Math.floor(seconds / 3600), Math.floor((seconds % 3600) / 60), seconds % 60].map((v) => String(v).padStart(2, "0")).join(":");
      this.indicator.set(tr("In a call · {time}", { time: clock }), COLOR.success);
    }
    const stats = this.c.stats();
    this.refreshSettings(stats);
    if (this.advanced && this.panel.tabs.value() === "dev" && this.settings.side_open) this.refreshDev(stats);
    this.updateButtons();
  }

  refreshSettings(stats) {
    const tab = this.audioVideo;
    tab.sendMic.set(this.c.sendMicrophone);
    tab.listen.set(this.c.receiveAudio);
    tab.watch.set(this.c.receiveVideo);
    tab.sendCamera.set(this.c.cameraRunning);
    tab.share.set(this.c.screenRunning);
    const audio = stats.audio;
    tab.level.firstChild.style.width = `${Math.round(Math.sqrt(audio && this.c.sendMicrophone ? audio.input_level : 0) * 100)}%`;
    if (audio) {
      tab.audioStatus.textContent = [
        tr("Transport {transport}", { transport: "WebSocket" }), tr("buffer {ms} ms", { ms: audio.buffer_ms }),
        audio.microphone ? tr("microphone ready") : tr("no microphone"), audio.speaker ? tr("speaker ready") : tr("no speaker"),
      ].join(" · ");
    }
  }

  refreshDev(stats) {
    const tab = this.dev;
    const state = this.c.asgardState;
    const servo = state.servo || {};
    const capabilities = this.c.capabilities;
    tab.panGauge.set(Number(state.pan ?? 90), Number(servo.target_pan ?? state.pan ?? 90),
                     state.pan_limits || capabilities.pan_limits || [10, 170]);
    tab.tiltGauge.set(Number(state.tilt ?? 90), Number(servo.target_tilt ?? state.tilt ?? 90),
                      state.tilt_limits || capabilities.tilt_limits || [40, 140]);
    const servoParts = [String(state.servos || "?"), servo.moving ? tr("moving") : tr("still"),
                        servo.attached !== false ? tr("holding (pulses on)") : tr("released (no pulses)"),
                        tr("max. {speed}°/s", { speed: servo.speed ?? "?" })];
    if (servo.simulated) servoParts.push(tr("simulated"));
    tab.servoInfo.textContent = servoParts.join(" · ");
    const ai = state.ai || {};
    if (Object.keys(ai).length) {
      tab.detect.set(ai.enabled !== false);
      tab.detect.input.disabled = !ai.available;
      const target = state.target;
      tab.aiInfo.textContent = [
        String(ai.reason || ""), ai.running ? tr("active") : tr("paused"), tr("{hz} detections/s", { hz: ai.hz || 0 }),
        tr("mode {mode}", { mode: tr(String(state.mode || "?")) }),
        target !== null && target !== undefined ? tr("target #{id} ({state})", { id: target, state: tr(String(state.target_state || "")) }) : tr("no target"),
      ].join(" · ");
    }
    const params = state.params || {};
    if (Object.keys(params).length && performance.now() > tab.paramsUntil) {
      for (const [key, { input, value, digits }] of Object.entries(tab.params)) {
        if (key in params && document.activeElement !== input) {
          input.value = params[key];
          value.textContent = Number(params[key]).toFixed(digits);
        }
      }
      tab.invertPan.set(!!params.invert_pan);
      tab.invertTilt.set(!!params.invert_tilt);
    }
    const recent = performance.now() / 1000 - (this.c.detections.at || 0) < 1.5;
    tab.people.replaceChildren(...(recent ? this.c.detections.items : []).filter((item) => Number.isInteger(item.id)).map((item) => {
      const [x, y, w, h] = item.box || [0, 0, 0, 0];
      const text = `#${String(item.id).padEnd(3)} x ${x.toFixed(2)} y ${y.toFixed(2)}  ${w.toFixed(2)}×${h.toFixed(2)}${item.target ? " ◎" : ""}`;
      return el("div.person", {}, [el("span", { text }), button(tr("Follow"), { onclick: () => this.c.selectPerson(item.id) })]);
    }));
    const link = stats.link || {};
    const audio = stats.audio || {};
    const columns = (rows) => {
      const width = Math.max(...rows.map(([labelText]) => labelText.length)) + 2;
      return rows.map(([labelText, value]) => labelText.padEnd(width) + value).join("\n");
    };
    const rows = [
      [tr("latency"), this.latencyText()],
      [tr("video in"), `${this.incomingFps.toFixed(1)} fps · ${this.lastFrameMeta.w || "?"}×${this.lastFrameMeta.h || "?"}`],
      ["bytes", `↓ ${((link.bytes_received || 0) / 1e6).toFixed(1)} MB · ↑ ${((link.bytes_sent || 0) / 1e6).toFixed(1)} MB`],
      [tr("media"), link.media ? tr("connected") : tr("no channel")],
    ];
    if (stats.audio) {
      rows.push(["audio", tr("{transport} · buffer {level}/{target} ms", { transport: "WebSocket", level: audio.buffer_ms, target: audio.target_ms })]);
      rows.push(["", tr("dropouts {underruns} · overflows {overflows}", { underruns: audio.underruns, overflows: audio.overflows })]);
    }
    if (stats.camera_fps) rows.push([tr("my camera"), `${stats.camera_fps.toFixed(1)} fps`]);
    if (stats.screen_fps) rows.push([tr("my screen"), `${stats.screen_fps.toFixed(1)} fps`]);
    tab.network.textContent = columns(rows);
    const camera = state.camera || {};
    const asgardAudio = state.audio_state || {};
    const yes = tr("yes");
    const no = tr("no");
    const data = [
      ["software", String(state.software || "?")],
      [tr("camera"), tr("{width}×{height} · {fps} fps · sending {sent} fps · JPEG {quality}", {
        width: camera.width || 0, height: camera.height || 0, fps: camera.fps || 0, sent: camera.sent_fps || 0, quality: camera.quality ?? "?" })],
      ["audio", tr("{transport} · mic {mic} · speaker {speaker}", {
        transport: tr(String(asgardAudio.transport || "?")), mic: asgardAudio.microphone ? yes : no, speaker: asgardAudio.speaker ? yes : no })],
      [tr("hand"), `${state.actuator || "?"} · ${state.hand ? tr("raised") : tr("down")}`],
      [tr("simulation"), state.simulation ? yes : no],
    ];
    if (camera.error) data.push([tr("camera error"), String(camera.error)]);
    if (asgardAudio.error) data.push([tr("audio error"), String(asgardAudio.error)]);
    tab.asgard.textContent = columns(data);
  }

  start(info, isNew = true) {
    const session = info.session || {};
    const asgard = session.asgard || {};
    const capabilities = asgard.capabilities || {};
    this.header.subtitle.textContent = asgard.location ? `${asgard.name} · ${asgard.location}` : asgard.name || "Asgard";
    const ai = !!capabilities.ai;
    for (const key of ["follow", "auto"]) this.camera.mode.setDisabled(key, !ai);
    this.camera.mode.title = ai ? "" : tr("Tracking not available: {reason}", { reason: capabilities.ai_reason || tr("no AI") });
    const [panLow, panHigh] = capabilities.pan_limits || [10, 170];
    const [tiltLow, tiltHigh] = capabilities.tilt_limits || [40, 140];
    Object.assign(this.camera.pan, { min: panLow, max: panHigh });
    Object.assign(this.camera.tilt, { min: tiltLow, max: tiltHigh });
    this.bar.hand.disabled = capabilities.actuator === false;
    if (capabilities.actuator === false) this.bar.hand.title = tr("This Asgard has no mechanical hand.");
    if (isNew || !this.started) {       // también al recargar la página en plena llamada
      this.started = Date.now();
      this.hand = false;
      this.chat.messages.clear();
      this.chat.messages.system(tr("Call started with «{name}».", { name: asgard.name || "Asgard" }));
      this.view.clear();
      this.dev.log(tr("Session {session} with {asgard}", { session: session.id || "?", asgard: asgard.id || "?" }));
    }
    this.c.setDebug(this.advanced);
    if (!this.active) {
      this.active = true;
      this.render();
      this.timer = setInterval(() => this.refresh(), 500);
    }
    this.keepAwake(true);
    this.updateButtons();
    this.place();
  }

  end() {
    this.active = false;
    this.keepAwake(false);
    clearInterval(this.timer);
    this.view.clear();
    this.view.setPreview(null);
  }

  setState(state) {
    this.hand = !!state.hand;
    const tab = this.camera;
    const mode = String(state.mode || "manual");
    tab.mode.setValue(mode);
    const situation = targetText(String(state.target_state || ""));
    if (state.target !== null && state.target !== undefined) tab.target.textContent = tr("Person #{id}", { id: state.target }) + (situation ? `: ${situation}` : "");
    else if (mode === "auto") tab.target.textContent = tr("Follows the person closest to the camera.");
    else tab.target.textContent = tr("No person chosen.");
    tab.release.disabled = (state.target === null || state.target === undefined) && mode === "manual";
    if (performance.now() > tab.draggingUntil) {
      for (const [input, value, key] of [[tab.pan, tab.panValue, "pan"], [tab.tilt, tab.tiltValue, "tilt"]]) {
        if (typeof state[key] === "number") {
          input.value = state[key];
          value.textContent = `${Math.round(state[key])}°`;
        }
      }
    }
    const names = (state.presets || []).map(String);
    const current = Array.from(tab.presets.options).map((option) => option.value);
    if (names.join("\n") !== current.join("\n")) setOptions(tab.presets, names.map((name) => [name, name]), tab.presets.value);
    tab.go.disabled = !names.length;
    tab.remove.disabled = !names.length;
    this.updateButtons();
  }

  setView(advanced) {
    this.header.setView(advanced ? VIEW_ADVANCED : VIEW_DEFAULT);
    this.panel.tabs.setOptions(this.tabOptions());
    this.bar.dev.hidden = !advanced;
    if (!advanced && this.panel.tabs.value() === "dev") this.showTab("chat");
    if (this.active) this.c.setDebug(advanced);
    this.updateButtons();
  }

  systemNotice(text) {
    this.chat.messages.system(text);
    this.dev.log(text);
  }

  setDevices(microphones, speakers, cameras) {
    const tab = this.audioVideo;
    const label = (device, index, kind) => device.label || `${kind} ${index + 1}`;
    setOptions(tab.microphone, [["", tr("System default")], ...microphones.map((d, i) => [d.deviceId, label(d, i, tr("Microphone"))])], this.settings.microphone);
    setOptions(tab.speaker, [["", tr("System default")], ...speakers.map((d, i) => [d.deviceId, label(d, i, tr("Speaker"))])], this.settings.speaker);
    setOptions(tab.camera, cameras.length ? cameras.map((d, i) => [d.deviceId, label(d, i, tr("Camera"))]) : [["", tr("No cameras were found")]],
               this.settings.camera);
    tab.speaker.disabled = !(window.AudioContext && "setSinkId" in AudioContext.prototype);
  }
}

// --------------------------------------------------------------------------- //
// Aplicación
// --------------------------------------------------------------------------- //
class MidgardWeb {
  constructor() {
    this.settings = loadSettings();
    this.root = document.getElementById("app");
    this.signingIn = false;
    this.openingLayer = null;
    this.profile = null;
    this.connectionLayer = null;
  }

  get advanced() {
    return isAdvanced(this.settings);
  }

  async init() {
    await setLanguage(this.settings.language);
    this.c = new MidgardController(this.settings, (kind, ...data) => this.handle(kind, data));
    this.c.avatarJpeg = avatarBase64(this.settings.avatars[this.settings.username.toLowerCase()]);
    this.login = new LoginPage(this);
    this.lobby = new LobbyPage(this);
    this.call = new CallPage(this);
    this.root.replaceChildren(this.login.node, this.lobby.node, this.call.node);
    this.applyView();
    this.call.showTab(this.settings.side_panel);
    this.call.togglePanel(this.settings.side_open);
    this.lobby.server.setValues(this.settings.host, this.settings.port, this.settings.tls);
    this.lobby.server.setManual(this.settings.server_mode === "manual");
    this.show(this.login);
    setTimeout(() => this.login.focus(), 50);
    document.addEventListener("keydown", (event) => this.onKey(event));
    window.addEventListener("beforeunload", () => { if (this.c.link) this.c.link.stop(); });
    if (navigator.mediaDevices) navigator.mediaDevices.addEventListener("devicechange", () => this.loadDevices());
    setTimeout(() => this.c.connectDefault(), 150);
    if ("serviceWorker" in navigator && window.isSecureContext && !isPackagedApp()) {
      navigator.serviceWorker.register("sw.js").catch(() => {});
    }
    window.__midgard = this;          // para depurar desde la consola del navegador
  }

  show(page) {
    for (const other of [this.login, this.lobby, this.call]) other.node.classList.toggle("active", other === page);
    this.current = page;
  }

  onKey(event) {
    if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "d") {
      event.preventDefault();
      this.connectionSettings();
      return;
    }
    const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement && document.activeElement.tagName);
    if (this.current === this.call && !typing && !document.querySelector(".modal") && this.call.moveWithKeyboard(event.key, event.shiftKey)) {
      event.preventDefault();
    }
  }

  // -- eventos del controlador --------------------------------------------------------- //
  handle(kind, data) {
    const handler = this[`ev_${kind}`];
    if (typeof handler === "function") {
      try {
        handler.apply(this, data);
      } catch (error) {
        console.error(`Midgard: ${kind}`, error);
      }
    }
  }

  welcomeText(meta) {
    const server = meta.server || "Bifröst";
    const encrypted = !!(this.c.server && this.c.server.tls);
    if (meta.mode === "public") {
      return encrypted ? tr("Connected to «{server}» (public network · encrypted).", { server }) : tr("Connected to «{server}» (public network).", { server });
    }
    return encrypted ? tr("Connected to «{server}» (local network · encrypted).", { server }) : tr("Connected to «{server}» (local network).", { server });
  }

  ev_server_search() {
    this.login.setServer("searching", tr("Looking for the Bifröst server…"));
    this.lobby.setConnection(tr("Looking for the Bifröst server…"), COLOR.warning, true);
  }

  ev_server(choice) {
    this.login.setServer("searching", tr("Connecting to {server}…", { server: choice.describe() }));
    this.lobby.server.setValues(choice.host, choice.port, choice.tls);
  }

  ev_server_error(message) {
    this.login.setServer("error", message);
    this.lobby.setConnection(message, COLOR.error);
  }

  ev_link(state, detail) {
    if (state === STATE_CONNECTED) return;      // la bienvenida trae el detalle
    if (state === STATE_CONNECTING) {
      this.login.setServer("searching", tr("Connecting to {server}…", { server: detail }));
      this.lobby.setConnection(tr("Connecting to {server}…", { server: detail }), COLOR.warning, true);
    } else if (state !== "stopped") {
      this.login.setServer("error", tr("No connection with the server: {detail}", { detail }));
      this.lobby.setConnection(tr("No connection: {detail}. Retrying…", { detail }), COLOR.error, true);
    }
  }

  ev_welcome(meta) {
    const text = this.welcomeText(meta);
    this.login.setServer("connected", text);
    this.lobby.setConnection(text, COLOR.success);
  }

  ev_problem(kind, info) {
    if (kind === "rejected") {
      const message = info.message || tr("The server rejected the connection.");
      this.cancelSignIn(message);
      toast(message, "error");
    }
  }

  ev_auth_ok(user) {
    this.applyUser(user);
    if (this.signingIn) {
      this.signingIn = false;
      clearTimeout(this.signInTimer);
      this.startTransition();
    } else if (this.current === this.login) {
      this.show(this.lobby);       // la sesión se recuperó con el token (por ejemplo, al recargar)
    }
  }

  ev_auth_error(code, message) {
    if (this.signingIn || this.current === this.login) {
      this.signingIn = false;
      clearTimeout(this.signInTimer);
      this.login.showError(message);
    }
  }

  ev_auth_lost(message) {
    if (this.current === this.login && !this.signingIn) return;
    this.backToLogin(message);
  }

  ev_signed_out() {
    this.backToLogin("");
  }

  ev_asgards(items) {
    this.listReceived = true;
    this.lobby.setAsgards(items, this.settings.last_asgard);
    if (this.transitionReady) this.transitionReady();
  }

  ev_session(info, resumed) {
    this.closeOpening();
    if (resumed && this.current === this.call) {
      this.call.start(info, false);
      this.call.systemNotice(tr("Connection restored; the call goes on."));
      toast(tr("Connection restored; the call goes on."), "success");
      return;
    }
    this.call.start(info, !resumed);
    this.show(this.call);
    const asgard = (info.session || {}).asgard || {};
    toast(tr("Connected to «{name}».", { name: asgard.name || "Asgard" }), "success");
  }

  ev_session_error(code, message) {
    this.closeOpening();
    toast(message, "error");
  }

  ev_session_end(message) {
    this.call.end();
    if (this.current === this.call) this.show(this.lobby);
    toast(message, "info");
  }

  ev_asgard_status(connected) {
    const text = connected ? tr("The Asgard connected again.") : tr("The Asgard lost its connection; the call is kept for a few seconds.");
    this.call.systemNotice(text);
    toast(text, connected ? "success" : "warning");
  }

  ev_state(state) {
    this.call.setState(state);
  }

  ev_chat_ack(identifier) {
    this.call.chat.messages.mark(identifier, tr("✓ Delivered"));
  }

  ev_notice(text) {
    if (!text) return;
    this.call.systemNotice(text);
    toast(text, "info");
  }

  ev_audio_error(text) {
    this.call.dev.log(tr("Audio: {error}", { error: text }));
    toast(tr("Audio: {error}", { error: text }), "warning");
  }

  ev_capture_error(text) {
    this.call.dev.log(text);
    toast(text, "error");
    this.call.updateButtons();
  }

  ev_password(ok, message) {
    if (this.profile) this.profile.passwordResult(ok, message);
    else toast(message, ok ? "success" : "error");
  }

  ev_history(items) {
    if (this.profile) this.profile.setHistory(items);
  }

  // -- acceso -------------------------------------------------------------------------- //
  signIn(username, password) {
    this.settings.username = username;
    saveSettings(this.settings);
    this.c.avatarJpeg = avatarBase64(this.settings.avatars[username.toLowerCase()]);
    this.signingIn = true;
    this.listReceived = false;
    this.login.setBusy(true, this.c.connected ? tr("Checking credentials…") : tr("Connecting to the server…"));
    this.c.authenticate(username, password);
    clearTimeout(this.signInTimer);
    this.signInTimer = setTimeout(() => {
      this.cancelSignIn(tr("The server did not answer. Check the connection or set it up in «Connection settings»."));
      this.login.configure.hidden = false;
    }, 20000);
  }

  cancelSignIn(message) {
    if (!this.signingIn) return;
    this.signingIn = false;
    clearTimeout(this.signInTimer);
    this.c.cancelAuth();
    this.login.showError(message);
  }

  /** The logo travels to the center while the list loads, then lands in the header (as on the desktop). */
  async startTransition() {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      this.show(this.lobby);
      this.afterSignIn();
      return;
    }
    const from = rectOf(this.login.brandLogoNode());
    const veil = el("div.veil");
    const traveler = el("div.traveler", {}, [logo().firstChild]);
    const line1 = el("div.line1", {}, [icon("circle-check", 13), el("span", { text: tr("Credentials accepted") })]);
    const line2 = el("div.line2", { text: `${tr("Preparing access to Asgard")}…` });
    const status = el("div.status", {}, [line1, line2]);
    const layer = el("div.transition-layer", {}, [veil, traveler, status]);
    document.body.append(layer);
    const place = (rect) => Object.assign(traveler.style, { left: `${rect.x}px`, top: `${rect.y}px`, width: `${rect.w}px`, height: `${rect.h}px` });
    place(from);
    const height = Math.max(110, Math.min(321, window.innerHeight * 0.39));
    const width = height * (from.w / from.h || 0.34);
    const center = { x: (window.innerWidth - width) / 2, y: Math.max(12, window.innerHeight * 0.5 - height * 0.75), w: width, h: height };
    status.style.top = `${center.y + height + 40}px`;
    const frames = (a, b) => [{ left: `${a.x}px`, top: `${a.y}px`, width: `${a.w}px`, height: `${a.h}px` },
                              { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px` }];
    requestAnimationFrame(() => { veil.style.opacity = "1"; });
    this.login.brandLogoNode().style.visibility = "hidden";
    await traveler.animate(frames(from, center), { duration: 950, easing: "cubic-bezier(0.65, 0, 0.35, 1)", fill: "forwards" }).finished;
    status.style.opacity = "1";
    const started = performance.now();
    const ready = new Promise((resolve) => {
      this.transitionReady = resolve;
      if (this.listReceived) resolve();
    });
    await Promise.race([ready, new Promise((resolve) => setTimeout(resolve, 9000))]);
    this.transitionReady = null;
    const wait = 1700 - (performance.now() - started);
    if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
    this.lobby.header.logo.style.visibility = "hidden";
    this.show(this.lobby);
    status.style.opacity = "0";
    const target = rectOf(this.lobby.header.logo);
    veil.style.transition = "opacity 820ms cubic-bezier(0.65, 0, 0.35, 1)";
    veil.style.opacity = "0";
    await traveler.animate(frames(center, target), { duration: 820, easing: "cubic-bezier(0.65, 0, 0.35, 1)", fill: "forwards" }).finished;
    this.lobby.header.logo.style.visibility = "";
    layer.remove();
    this.afterSignIn();
  }

  afterSignIn() {
    this.login.brandLogoNode().style.visibility = "";
    this.login.setBusy(false);
    this.login.password.value = "";
  }

  applyUser(user) {
    const name = String(user.display || user.name || "");
    const image = this.settings.avatars[String(user.name || this.settings.username).toLowerCase()] || "";
    for (const header of [this.lobby.header, this.call.header]) header.setUser(name, image);
    this.c.setAvatar(avatarBase64(image));
  }

  backToLogin(message) {
    this.signingIn = false;
    clearTimeout(this.signInTimer);
    this.closeOpening();
    if (this.profile) this.profile.layer.dismiss();
    this.call.end();
    this.lobby.setAsgards([]);
    this.login.reset(message);
    this.show(this.login);
  }

  signOut() {
    this.c.signOut();
  }

  // -- Asgard y llamada ------------------------------------------------------------------- //
  enterAsgard(identifier) {
    if (this.openingLayer) return;
    const item = this.c.asgards.find((i) => i.id === identifier) || { name: identifier };
    if (!this.c.openAsgard(identifier)) {
      toast(tr("There is no connection with the Bifröst server."), "error");
      return;
    }
    this.settings.last_asgard = identifier;
    saveSettings(this.settings);
    const layer = modal(400, false);
    layer.card.append(el("div.row", {}, [
      el("span.spinner"),
      el("div.grow", {}, [el("h2", { text: tr("Connecting to «{name}»", { name: item.name || identifier }) }),
                          el("span.soft", { text: `${tr("Checking the Asgard and preparing the call")}…` })]),
    ]));
    this.openingLayer = layer;
    this.openTimer = setTimeout(() => {
      this.closeOpening();
      toast(tr("The server did not answer when opening the call. Try again."), "error");
    }, 15000);
  }

  closeOpening() {
    clearTimeout(this.openTimer);
    if (this.openingLayer) this.openingLayer.dismiss();
    this.openingLayer = null;
  }

  // -- vista, idioma, perfil y conexión manual ------------------------------------------------ //
  applyView() {
    this.lobby.setView(this.advanced);
    this.call.setView(this.advanced);
  }

  changeView(key) {
    if (key === this.settings.view_mode) return;
    this.settings.view_mode = key;
    saveSettings(this.settings);
    this.applyView();
    toast(key === VIEW_ADVANCED ? tr("Advanced view: manual connection and developer tools.") : tr("Default view."), "info");
  }

  changeLanguage(setting) {
    if (setting === this.settings.language) return;
    this.settings.language = setting;
    saveSettings(this.settings);
    // La página se vuelve a abrir en el idioma nuevo; la sesión y la llamada se recuperan solas.
    location.reload();
  }

  async loadDevices() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      this.call.setDevices(devices.filter((d) => d.kind === "audioinput" && d.deviceId !== "default" && d.deviceId !== "communications"),
                           devices.filter((d) => d.kind === "audiooutput" && d.deviceId !== "default" && d.deviceId !== "communications"),
                           devices.filter((d) => d.kind === "videoinput"));
    } catch {
      // sin permiso todavía: las listas se llenan cuando el navegador lo concede
    }
  }

  openProfile() {
    if (this.profile || this.c.user === null) return;
    this.profile = new ProfileLayer(this);
    this.profile.layer.onClosed(() => { this.profile = null; });
  }

  connectManual(host, port, tls) {
    this.settings.server_mode = "manual";
    Object.assign(this.settings, { host, port, tls });
    saveSettings(this.settings);
    this.lobby.server.setManual(true);
    const previous = this.c.server;
    this.c.connect(new ServerChoice(host, port, tls, "", "manual"));
    if (this.connectionLayer) this.connectionLayer.dismiss();
    if (previous && previous.address !== `${host}:${port}` && this.c.user === null && this.current !== this.login) {
      this.backToLogin(tr("Connected to another server: sign in again."));
    }
  }

  useAutomatic() {
    this.settings.server_mode = "auto";
    saveSettings(this.settings);
    this.lobby.server.setManual(false);
    if (this.connectionLayer) this.connectionLayer.dismiss();
    this.c.disconnect(true);
    this.c.connectDefault();
    if (this.current !== this.login) toast(tr("Using the automatic server."), "info");
  }

  connectionSettings() {
    if (this.connectionLayer) return;
    const layer = modal(760);
    const section = new ServerSection(this, (host, port, tls) => this.connectManual(host, port, tls));
    const current = this.c.server;
    section.setValues(current ? current.host : this.settings.host, current ? current.port : this.settings.port,
                      current ? current.tls : this.settings.tls);
    section.setManual(this.settings.server_mode === "manual");
    section.status.set(this.login.status.text() || tr("Not connected."), COLOR.dim);
    section.node.querySelector(".section-title").remove();
    const close = button("", { variant: "ghost", icon: "x", title: tr("Close"), onclick: () => layer.dismiss() });
    close.classList.add("icon-only");
    layer.card.append(
      el("div.head", {}, [el("div.grow", {}, [el("h2", { text: tr("Connection settings") })]), close]),
      el("span.soft", { text: tr("Address of Bifröst and its web port (8080 by default). On the server, «python main.py» shows it as «Midgard Web».") }),
      section.node,
    );
    this.connectionLayer = layer;
    layer.onClosed(() => { this.connectionLayer = null; });
    setTimeout(() => section.address.focus(), 50);
  }
}

// --------------------------------------------------------------------------- //
// Perfil
// --------------------------------------------------------------------------- //
class ProfileLayer {
  constructor(app) {
    this.app = app;
    const c = app.c;
    const user = c.user || {};
    this.login = String(user.name || "");
    const display = String(user.display || this.login);
    this.layer = modal(500);
    const body = this.layer.card;
    this.avatar = avatar(72);
    this.avatar.setPerson(display, app.settings.avatars[this.login.toLowerCase()]);
    const role = user.admin ? tr("Administrator") : user.full_access ? tr("Access to every Asgard") : tr("User");
    const close = button("", { variant: "ghost", icon: "x", title: tr("Close"), onclick: () => this.layer.dismiss() });
    close.classList.add("icon-only");
    body.append(el("div.head", {}, [this.avatar, el("div.grow", {}, [
      el("h2", { text: display }), el("div.soft.small", { text: `@${this.login}` }), el("div.dim.small", { text: role }),
    ]), close]));
    const picker = el("input", { type: "file", accept: "image/*", hidden: true });
    picker.addEventListener("change", () => { if (picker.files[0]) this.changePhoto(picker.files[0]); picker.value = ""; });
    this.removeButton = button(tr("Remove photo"), { variant: "ghost", onclick: () => this.removePhoto() });
    this.removeButton.hidden = !app.settings.avatars[this.login.toLowerCase()];
    body.append(el("div.row", {}, [button(tr("Change photo"), { icon: "image", onclick: () => picker.click() }), this.removeButton, picker]),
                el("span.dim.small", { text: tr("The photo is shown on the classroom screen during your calls.") }), separator());
    const server = c.server ? c.server.describe() : "—";
    const mode = c.server && c.server.tls ? tr("Internet (TLS)") : tr("local network");
    const languageBox = select(languageOptions(), app.settings.language, "field");
    languageBox.addEventListener("change", () => app.changeLanguage(languageBox.value));
    body.append(el("div.profile-grid", {}, [
      el("span.key", { text: tr("Server") }), el("span", { text: `${server} · ${mode}` }),
      el("span.key", { text: tr("Last sign-in") }), el("span", { text: localDate(user.last_login) }),
      el("span.key", { text: tr("Account created") }), el("span", { text: localDate(user.created) }),
      el("span.key", { text: tr("Language") }), languageBox,
    ]));
    this.history = el("div.history", {}, [el("span.soft", { text: tr("Loading…") })]);
    body.append(el("strong", { text: tr("Recent calls") }), this.history);
    this.passwordButton = button(tr("Change password"), { icon: "key-round", onclick: () => this.showPassword() });
    this.current = field({ type: "password", placeholder: tr("Current password"), maxLength: 256, autocomplete: "current-password" });
    this.newPassword = field({ type: "password", placeholder: tr("New password (at least 8 characters)"), maxLength: 256, autocomplete: "new-password" });
    this.repeated = field({ type: "password", placeholder: tr("Repeat the new password"), maxLength: 256, autocomplete: "new-password" });
    this.passwordMessage = el("span.small", { hidden: true });
    this.repeated.addEventListener("keydown", (event) => { if (event.key === "Enter") this.savePassword(); });
    this.passwordSection = el("div.tab", { hidden: true }, [this.current, this.newPassword, this.repeated, this.passwordMessage,
                                                            el("div", {}, [button(tr("Save password"), { variant: "primary", onclick: () => this.savePassword() })])]);
    body.append(el("div", {}, [this.passwordButton]), this.passwordSection, separator());
    body.append(el("div.row", {}, [
      button(tr("Sign out"), { variant: "danger", icon: "log-out", onclick: () => this.signOut() }), el("span.grow"),
      button(tr("Done"), { onclick: () => this.layer.dismiss() }),
    ]));
    c.requestHistory();
  }

  showPassword() {
    this.passwordButton.hidden = true;
    this.passwordSection.hidden = false;
    this.current.focus();
  }

  savePassword() {
    const current = this.current.value;
    const password = this.newPassword.value;
    if (!current || !password) return this.passwordResult(false, tr("Enter the current password and the new one."));
    if (password !== this.repeated.value) return this.passwordResult(false, tr("The new passwords do not match."));
    if (password.length < 8) return this.passwordResult(false, tr("The new password must have at least 8 characters."));
    if (!this.app.c.changePassword(current, password)) this.passwordResult(false, tr("There is no connection with the server."));
    return undefined;
  }

  passwordResult(ok, message) {
    this.passwordMessage.textContent = message;
    this.passwordMessage.className = ok ? "small" : "small error-text";
    this.passwordMessage.style.color = ok ? "var(--success)" : "";
    this.passwordMessage.hidden = false;
    if (ok) for (const input of [this.current, this.newPassword, this.repeated]) input.value = "";
    else shake(this.passwordSection);
  }

  setHistory(items) {
    this.history.replaceChildren();
    if (!items.length) this.history.append(el("span.soft", { text: tr("You have no calls yet.") }));
    for (const item of items.slice(0, 6)) {
      const reason = item.reason ? endReasonLabel(String(item.reason)) : "";
      this.history.append(el("div.item", {}, [
        el("strong", { text: String(item.name || item.asgard) }), el("span.soft", { text: localDate(item.start) }), el("span.grow"),
        el("span.dim", { text: duration(item.start, item.end) + (reason && item.end ? ` · ${reason}` : "") }),
      ]));
    }
  }

  changePhoto(file) {
    const image = new Image();
    const url = URL.createObjectURL(file);
    image.onload = () => {
      const side = Math.min(image.width, image.height);
      const canvas = document.createElement("canvas");
      canvas.width = 256;
      canvas.height = 256;
      canvas.getContext("2d").drawImage(image, (image.width - side) / 2, (image.height - side) / 2, side, side, 0, 0, 256, 256);
      URL.revokeObjectURL(url);
      const data = canvas.toDataURL("image/jpeg", 0.88);
      this.app.settings.avatars[this.login.toLowerCase()] = data;
      saveSettings(this.app.settings);
      this.avatar.setPerson(this.login, data);
      this.removeButton.hidden = false;
      this.app.applyUser(this.app.c.user || {});
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      toast(tr("That image could not be opened."), "error");
    };
    image.src = url;
  }

  removePhoto() {
    delete this.app.settings.avatars[this.login.toLowerCase()];
    saveSettings(this.app.settings);
    this.avatar.setPerson(this.login, "");
    this.removeButton.hidden = true;
    this.app.applyUser(this.app.c.user || {});
  }

  signOut() {
    const inCall = this.app.c.inSession;
    this.layer.dismiss();
    dialog({
      title: tr("Sign out"),
      message: inCall ? tr("The current call will end and you will go back to the sign-in screen.") : tr("You will go back to the sign-in screen."),
      accept: tr("Sign out"), danger: true, icon: "log-out", onAccept: () => this.app.signOut(),
    });
  }
}

// --------------------------------------------------------------------------- //
const supported = "WebSocket" in window && "createImageBitmap" in window && "ResizeObserver" in window;
if (supported) {
  new MidgardWeb().init();
} else {
  document.getElementById("app").textContent = "Midgard needs a newer browser. / Midgard necesita un navegador más reciente.";
}
