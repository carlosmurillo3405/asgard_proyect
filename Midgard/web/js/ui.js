// Componentes de la plantilla «UI-Asgard» para Midgard Web (equivalentes a widgets.py).
// Todo se construye con el DOM (sin innerHTML con datos del usuario).

import { LOGO } from "./brand.js";
import { tr } from "./i18n.js";
import { ICONS } from "./icons.js";

const SVG = "http://www.w3.org/2000/svg";

/** Creates an element: el("div.card.big", {text, title, onclick, ...}, children). */
export function el(spec, props = {}, children = []) {
  const [tag, ...classes] = spec.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "text") node.textContent = value;
    else if (key === "className") node.className = `${node.className} ${value}`.trim();
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key in node && typeof value !== "string") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Lucide icon (24 × 24 grid, stroke 2) as inline SVG. */
export function icon(name, size = 18, strokeWidth = 2) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", strokeWidth);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const markup = ICONS[name];
  if (markup) {
    const parsed = new DOMParser().parseFromString(`<svg xmlns="${SVG}">${markup}</svg>`, "image/svg+xml");
    for (const child of Array.from(parsed.documentElement.childNodes)) svg.append(document.importNode(child, true));
  }
  return svg;
}

/** The Asgard logo; ``progress`` < 1 draws only part of its strokes (for the transition). */
export function logo(extraClass = "") {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", LOGO.viewBox.join(" "));
  svg.setAttribute("aria-hidden", "true");
  for (const stroke of LOGO.strokes) {
    const line = document.createElementNS(SVG, "polyline");
    line.setAttribute("points", stroke.map((p) => p.join(",")).join(" "));
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", "currentColor");
    line.setAttribute("stroke-width", LOGO.stroke);
    line.setAttribute("stroke-linecap", "square");
    line.setAttribute("stroke-linejoin", "miter");
    svg.append(line);
  }
  return el(`div.logo${extraClass ? "." + extraClass : ""}`, {}, [svg]);
}

export function label(text, className = "") {
  return el(`span${className ? "." + className.split(" ").join(".") : ""}`, { text });
}

export function button(text, options = {}) {
  const classes = ["button", options.variant, options.size, options.iconAfter ? "icon-after" : "", !text && options.icon ? "icon-only" : ""]
    .filter(Boolean).join(".");
  const node = el(`button.${classes}`, { type: "button", title: options.title, onclick: options.onclick });
  if (options.icon) node.append(icon(options.icon, options.iconSize || 16));
  if (text) node.append(el("span", { text }));
  return node;
}

export function field(options = {}) {
  const classes = ["field", options.size, options.mono ? "mono" : ""].filter(Boolean).join(".");
  return el(`input.${classes}`, {
    type: options.type || "text", placeholder: options.placeholder || "", value: options.value || "",
    maxLength: options.maxLength || undefined, autocomplete: options.autocomplete || "off",
    spellcheck: "false", autocapitalize: "off", inputMode: options.inputMode || undefined,
  });
}

export function select(options, value, className = "field") {
  const node = el(`select.${className.split(" ").join(".")}`);
  setOptions(node, options, value);
  return node;
}

export function setOptions(node, options, value) {
  node.replaceChildren(...options.map(([key, text]) => el("option", { value: key, text })));
  if (value !== undefined && options.some(([key]) => key === value)) node.value = value;
}

export function switchControl(text, checked, onchange) {
  const input = el("input", { type: "checkbox", checked });
  input.addEventListener("change", () => onchange(input.checked));
  const node = el("label.switch", {}, [input, el("span.track"), text ? el("span", { text }) : null]);
  node.input = input;
  node.set = (value) => { if (input.checked !== value) input.checked = value; };
  return node;
}

export function indicator(text = "", dotColor = "var(--text-dim)") {
  const dot = el("span.dot");
  const textNode = el("span", { text });
  const node = el("span.indicator", {}, [dot, textNode]);
  node.set = (value, color, pulse = false) => {
    textNode.textContent = value;
    dot.style.background = color || "var(--text-dim)";
    dot.classList.toggle("pulse", !!pulse);
    node.title = value;
  };
  node.text = () => textNode.textContent;
  node.set(text, dotColor);
  return node;
}

export function separator(vertical = false) {
  return el(vertical ? "div.separator.vertical" : "hr.separator");
}

export function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function avatar(size = 38) {
  const node = el("span.avatar");
  node.style.width = `${size}px`;
  node.style.height = `${size}px`;
  node.style.fontSize = `${Math.round(size * 0.36)}px`;
  node.setPerson = (name, image) => {
    node.replaceChildren(image ? el("img", { src: image, alt: "" }) : document.createTextNode(initials(name)));
  };
  return node;
}

/** Segmented selector: options = [[key, text]]; onchange(key). */
export function segmented(options, onchange) {
  const thumb = el("span.thumb");
  const node = el("div.segmented", {}, [thumb]);
  let current = options.length ? options[0][0] : "";
  const buttons = new Map();
  const place = () => {
    const active = buttons.get(current);
    if (!active) { thumb.style.width = "0"; return; }
    thumb.style.left = `${active.offsetLeft}px`;
    thumb.style.width = `${active.offsetWidth}px`;
  };
  node.setOptions = (list) => {
    for (const b of buttons.values()) b.remove();
    buttons.clear();
    for (const [key, text] of list) {
      const b = el("button", { type: "button", text, onclick: () => { if (!b.disabled && key !== current) { node.setValue(key); onchange(key); } } });
      buttons.set(key, b);
      node.append(b);
    }
    if (!buttons.has(current) && list.length) current = list[0][0];
    node.setValue(current);
  };
  node.setValue = (key) => {
    current = key;
    for (const [k, b] of buttons) b.classList.toggle("active", k === key);
    requestAnimationFrame(place);
  };
  node.value = () => current;
  node.setDisabled = (key, disabled) => { const b = buttons.get(key); if (b) b.disabled = disabled; };
  new ResizeObserver(place).observe(node);
  node.setOptions(options);
  return node;
}

/** Round call button with a label below. Modes: normal, highlight, off, danger. */
export function roundButton(iconName, text, onclick) {
  const circle = el("span.circle", {}, [icon(iconName, 20)]);
  const labelNode = el("span.label", { text });
  const node = el("button.round", { type: "button", title: text, onclick }, [circle, labelNode]);
  node.setIcon = (name) => circle.replaceChildren(icon(name, 20));
  node.setLabel = (value) => { labelNode.textContent = value; node.title = value; };
  node.setMode = (mode) => {
    node.classList.remove("highlight", "off", "danger");
    if (mode !== "normal") node.classList.add(mode);
  };
  return node;
}

// -- avisos ------------------------------------------------------------------------ //
let toastHost = null;
const TOAST_ICONS = { info: "info", success: "circle-check", warning: "triangle-alert", error: "circle-x" };

export function toast(text, kind = "info", ms = 4200) {
  if (!text) return;
  if (!toastHost) {
    toastHost = el("div.toasts", { role: "status", "aria-live": "polite" });
    document.body.append(toastHost);
  }
  const node = el(`div.toast.${kind}`, {}, [icon(TOAST_ICONS[kind] || "info", 16), el("span", { text })]);
  toastHost.append(node);
  while (toastHost.children.length > 4) toastHost.firstChild.remove();
  setTimeout(() => {
    node.classList.add("leaving");
    node.addEventListener("animationend", () => node.remove(), { once: true });
  }, ms);
}

// -- capas modales y diálogos --------------------------------------------------------- //
export function modal(width = 440, closeOnOutside = true) {
  const card = el("div.card");
  const layer = el("div.modal", {}, [card]);
  layer.style.setProperty("--width", `${width}px`);
  const listeners = [];
  layer.card = card;
  layer.onClosed = (callback) => listeners.push(callback);
  layer.dismiss = () => {
    if (layer.classList.contains("leaving")) return;
    layer.classList.add("leaving");
    document.removeEventListener("keydown", onKey);
    setTimeout(() => {
      layer.remove();
      for (const callback of listeners) callback();
    }, 170);
  };
  const onKey = (event) => { if (event.key === "Escape" && closeOnOutside) layer.dismiss(); };
  layer.addEventListener("pointerdown", (event) => { if (event.target === layer && closeOnOutside) layer.dismiss(); });
  document.addEventListener("keydown", onKey);
  document.body.append(layer);
  return layer;
}

/** Confirmation dialog: accept/cancel default to «OK»/«Cancel»; cancel = "" hides it. */
export function dialog(options) {
  const layer = modal(options.width || 440);
  const head = el("div.head", {}, [
    options.icon ? el("span", { className: options.danger ? "error-text" : "soft" }, [icon(options.icon, 22)]) : null,
    el("div.grow", {}, [el("h2", { text: options.title })]),
  ]);
  layer.card.append(head, el("div.message", { text: options.message }));
  if (options.monoDetail) layer.card.append(el("div.mono-detail", { text: options.monoDetail }));
  const actions = el("div.actions");
  const cancelText = options.cancel === undefined ? tr("Cancel") : options.cancel;
  if (cancelText) {
    actions.append(button(cancelText, { onclick: () => { layer.dismiss(); if (options.onCancel) options.onCancel(); } }));
  }
  const accept = button(options.accept || tr("OK"), {
    variant: options.danger ? "danger" : "primary",
    onclick: () => { layer.dismiss(); if (options.onAccept) options.onAccept(); },
  });
  actions.append(accept);
  layer.card.append(actions);
  setTimeout(() => accept.focus(), 50);
  return layer;
}

export function askText(options) {
  const layer = modal(420);
  const input = field({ maxLength: options.maxLength || 32, value: options.value || "" });
  const done = () => {
    const value = input.value.trim();
    if (!value) { shake(input); return; }
    layer.dismiss();
    options.onAccept(value);
  };
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") done(); });
  layer.card.append(
    el("h2", { text: options.title }),
    el("label.soft.small", { text: options.label }),
    input,
    el("div.actions", {}, [
      button(tr("Cancel"), { onclick: () => layer.dismiss() }),
      button(options.accept || tr("OK"), { variant: "primary", onclick: done }),
    ]),
  );
  setTimeout(() => input.focus(), 50);
  return layer;
}

export function shake(node) {
  node.classList.remove("shake");
  void node.offsetWidth;
  node.classList.add("shake");
}

/** Message history with bubbles (chat). */
export function messageList(emptyText) {
  const empty = el("div.empty", { text: emptyText });
  const node = el("div.messages.scroll", {}, [empty]);
  const bubbles = new Map();
  const scroll = () => { node.scrollTop = node.scrollHeight; };
  node.add = (text, sender, timeText, own = false, key = "", status = "") => {
    empty.remove();
    const statusNode = el("div.status", { text: status });
    const bubble = el(`div.bubble${own ? ".own" : ""}`, {}, [
      el("div.meta", {}, [el("span.sender", { text: sender }), el("span", { text: timeText })]),
      el("div.text", { text }),
      status ? statusNode : null,
    ]);
    bubble.statusNode = statusNode;
    if (key) bubbles.set(key, bubble);
    node.append(bubble);
    while (node.children.length > 300) node.firstChild.remove();
    scroll();
  };
  node.mark = (key, status) => {
    const bubble = bubbles.get(key);
    if (!bubble) return false;
    bubble.statusNode.textContent = status;
    if (!bubble.statusNode.isConnected) bubble.append(bubble.statusNode);
    return true;
  };
  node.system = (text) => {
    empty.remove();
    node.append(el("div.system-line", { text }));
    scroll();
  };
  node.clear = () => {
    bubbles.clear();
    node.replaceChildren(empty);
  };
  return node;
}

export function clockText(date = new Date()) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
