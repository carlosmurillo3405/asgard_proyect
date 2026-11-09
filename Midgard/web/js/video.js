// Video del Asgard con sus capas, la cruceta de la cámara y la vista previa
// (equivalente a AsgardView y CameraPad de call.py).

import { COLORS } from "./brand.js";
import { tr } from "./i18n.js";
import { ICONS } from "./icons.js";
import { el, icon } from "./ui.js";

// Pares de puntos clave (orden de asgard.tracking.KEYPOINTS) que forman el esqueleto.
const SKELETON = [[1, 2], [1, 3], [3, 5], [2, 4], [4, 6], [1, 7], [2, 8], [7, 8], [7, 9], [9, 11], [8, 10], [10, 12]];
const SVG = "http://www.w3.org/2000/svg";

export function targetText(state) {
  return { tracking: tr("following"), searching: tr("searching…"), lost: tr("out of sight") }[state] || "";
}

function rgba(hex, alpha) {
  const value = parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

// Iconos de Lucide como Path2D para dibujarlos en el canvas.
const iconPaths = new Map();
function iconPath(name) {
  if (iconPaths.has(name)) return iconPaths.get(name);
  const path = new Path2D();
  const doc = new DOMParser().parseFromString(`<svg xmlns="${SVG}">${ICONS[name] || ""}</svg>`, "image/svg+xml");
  for (const node of Array.from(doc.documentElement.children)) {
    const n = (attr) => Number(node.getAttribute(attr) || 0);
    if (node.tagName === "path") path.addPath(new Path2D(node.getAttribute("d")));
    else if (node.tagName === "circle") { path.moveTo(n("cx") + n("r"), n("cy")); path.arc(n("cx"), n("cy"), n("r"), 0, Math.PI * 2); }
    else if (node.tagName === "line") { path.moveTo(n("x1"), n("y1")); path.lineTo(n("x2"), n("y2")); }
    else if (node.tagName === "polyline") {
      const points = node.getAttribute("points").trim().split(/[\s,]+/).map(Number);
      path.moveTo(points[0], points[1]);
      for (let i = 2; i < points.length; i += 2) path.lineTo(points[i], points[i + 1]);
    } else if (node.tagName === "rect") {
      const sub = new Path2D();
      sub.roundRect(n("x"), n("y"), n("width"), n("height"), n("rx"));
      path.addPath(sub);
    }
  }
  iconPaths.set(name, path);
  return path;
}

function drawIcon(context, name, x, y, size, color, width = 2) {
  context.save();
  context.translate(x, y);
  context.scale(size / 24, size / 24);
  context.strokeStyle = color;
  context.lineWidth = width;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.stroke(iconPath(name));
  context.restore();
}

/** Round pad: nudges the camera while held down (Shift = faster); the center re-centers it. */
export function cameraPad(size, floating, onNudge, onCenter) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 100 100");
  const shape = (tag, attrs) => {
    const node = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  };
  svg.append(shape("circle", { cx: 50, cy: 50, r: 49.5, fill: floating ? rgba(COLORS.background, 0.78) : COLORS.field,
                               stroke: COLORS.border, "stroke-width": 1 }));
  const node = el(`div.pad${floating ? "" : ".visible"}`, {}, [svg]);
  node.style.width = `${size}px`;
  node.style.height = `${size}px`;
  if (!floating) node.style.position = "relative";
  let timer = null;
  const directions = { up: [0, -1, "chevron-up", 0, 4], down: [0, 1, "chevron-down", 0, -4], left: [-1, 0, "chevron-left", -4, 0],
                       right: [1, 0, "chevron-right", 4, 0] };
  const stop = () => {
    clearInterval(timer);
    timer = null;
    for (const zone of svg.querySelectorAll(".zone")) zone.classList.remove("pressed");
  };
  for (const [name, [dx, dy, iconName, pan, tilt]] of Object.entries(directions)) {
    const zone = shape("g", { class: "zone" });
    const angle = Math.atan2(dy, dx);
    const wedge = (r) => {
      const a = angle - Math.PI / 4;
      const b = angle + Math.PI / 4;
      return `M ${50 + 16 * Math.cos(a)} ${50 + 16 * Math.sin(a)} L ${50 + r * Math.cos(a)} ${50 + r * Math.sin(a)} `
        + `A ${r} ${r} 0 0 1 ${50 + r * Math.cos(b)} ${50 + r * Math.sin(b)} L ${50 + 16 * Math.cos(b)} ${50 + 16 * Math.sin(b)} Z`;
    };
    zone.append(shape("path", { d: wedge(49) }));
    const cx = 50 + dx * 33;
    const cy = 50 + dy * 33;
    zone.append(shape("circle", { class: "mark", cx, cy, r: 15 }));
    const chevron = icon(iconName, 18, 2.2);
    chevron.setAttribute("x", cx - 9);
    chevron.setAttribute("y", cy - 9);
    chevron.setAttribute("width", 18);
    chevron.setAttribute("height", 18);
    chevron.setAttribute("color", COLORS.text);
    zone.append(chevron);
    zone.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const step = event.shiftKey ? 2.5 : 1;
      zone.classList.add("pressed");
      onNudge(pan * step, tilt * step);
      clearInterval(timer);
      timer = setInterval(() => onNudge(pan * step, tilt * step), 140);
      zone.setPointerCapture(event.pointerId);
    });
    zone.addEventListener("pointerup", stop);
    zone.addEventListener("pointercancel", stop);
    svg.append(zone);
  }
  const center = shape("g", { class: "zone center" });
  center.append(shape("circle", { cx: 50, cy: 50, r: 13.5, fill: COLORS.card, stroke: COLORS.border, "stroke-width": 1 }));
  center.append(shape("circle", { class: "mark", cx: 50, cy: 50, r: 13.5 }));
  const house = icon("house", 13, 2);
  house.setAttribute("x", 43.5);
  house.setAttribute("y", 43.5);
  house.setAttribute("width", 13);
  house.setAttribute("height", 13);
  house.setAttribute("color", COLORS.text_soft);
  center.append(house);
  center.addEventListener("pointerdown", (event) => { event.preventDefault(); event.stopPropagation(); onCenter(); });
  svg.append(center);
  node.title = tr("Move the classroom camera (Shift: faster)");
  return node;
}

export class AsgardView {
  constructor(page) {
    this.page = page;
    this.canvas = el("canvas");
    this.context = this.canvas.getContext("2d");
    this.waitingIcon = el("span");
    this.waitingTitle = el("div.title");
    this.waitingDetail = el("div.detail");
    this.waitingSpinner = el("div.spinner", { hidden: true });
    this.waiting = el("div.waiting", { hidden: true }, [this.waitingIcon, this.waitingSpinner, this.waitingTitle, this.waitingDetail]);
    this.preview = el("video", { muted: true, playsInline: true, autoplay: true });
    this.pip = el("div.pip", { hidden: true }, [this.preview]);
    this.pad = cameraPad(112, true, (dpan, dtilt) => page.c.nudge(dpan, dtilt), () => page.c.center());
    this.node = el("div.video", {}, [this.canvas, this.waiting, this.pad, this.pip]);
    this.bitmap = null;
    this.decoding = false;
    this.pending = null;
    this.mouse = null;
    this.message = "";
    this.node.addEventListener("pointermove", (event) => { this.mouse = this.toNormalized(event); });
    this.node.addEventListener("pointerleave", () => { this.mouse = null; });
    this.node.addEventListener("contextmenu", (event) => event.preventDefault());
    this.node.addEventListener("pointerup", (event) => {
      if (event.target.closest(".pad")) return;
      const point = this.toNormalized(event);
      if (point && this.bitmap) page.videoClicked(point[0], point[1], event.button === 2 ? 2 : 1);
    });
    new ResizeObserver(() => this.resize()).observe(this.node);
  }

  resize() {
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(this.node.clientWidth * ratio));
    const height = Math.max(1, Math.round(this.node.clientHeight * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
  }

  hasImage() {
    return this.bitmap !== null;
  }

  async showFrame(frame) {
    if (this.decoding) {
      this.pending = frame;       // solo importa el más reciente
      return;
    }
    this.decoding = true;
    try {
      const bitmap = await createImageBitmap(new Blob([frame.data], { type: "image/jpeg" }));
      if (this.bitmap) this.bitmap.close();
      this.bitmap = bitmap;
      this.setMessage("");
    } catch {
      // cuadro dañado: se espera el siguiente
    } finally {
      this.decoding = false;
    }
    if (this.pending) {
      const next = this.pending;
      this.pending = null;
      this.showFrame(next);
    }
  }

  clear() {
    if (this.bitmap) this.bitmap.close();
    this.bitmap = null;
  }

  setMessage(title, detail = "", iconName = "", waiting = false) {
    const key = `${title}|${detail}|${iconName}|${waiting}`;
    if (key === this.message) return;
    this.message = key;
    this.waiting.hidden = !title;
    this.waitingTitle.textContent = title;
    this.waitingDetail.textContent = detail;
    this.waitingIcon.replaceChildren(iconName && !waiting ? icon(iconName, 36, 1.6) : "");
    this.waitingSpinner.hidden = !waiting;
  }

  setPreview(stream) {
    if (stream) {
      if (this.preview.srcObject !== stream) this.preview.srcObject = stream;
      this.pip.hidden = false;
    } else if (!this.pip.hidden) {
      this.preview.srcObject = null;
      this.pip.hidden = true;
    }
  }

  /** Rectangle (CSS pixels) where the image ends up, letterboxed. */
  imageRect() {
    const width = this.node.clientWidth;
    const height = this.node.clientHeight;
    if (!this.bitmap) return { x: 0, y: 0, w: width, h: height };
    const scale = Math.min(width / this.bitmap.width, height / this.bitmap.height);
    const w = this.bitmap.width * scale;
    const h = this.bitmap.height * scale;
    return { x: (width - w) / 2, y: (height - h) / 2, w, h };
  }

  toNormalized(event) {
    const box = this.node.getBoundingClientRect();
    const rect = this.imageRect();
    const x = (event.clientX - box.left - rect.x) / rect.w;
    const y = (event.clientY - box.top - rect.y) / rect.h;
    return x >= 0 && x <= 1 && y >= 0 && y <= 1 ? [x, y] : null;
  }

  draw() {
    const ratio = window.devicePixelRatio || 1;
    const context = this.context;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.fillStyle = COLORS.video;
    context.fillRect(0, 0, this.node.clientWidth, this.node.clientHeight);
    if (!this.bitmap) return;
    const rect = this.imageRect();
    context.imageSmoothingQuality = "high";
    context.drawImage(this.bitmap, rect.x, rect.y, rect.w, rect.h);
    this.drawLayers(context, rect);
  }

  chip(context, x, y, text, light = false, px = 12, iconName = "") {
    context.font = `500 ${px}px Inter, system-ui, sans-serif`;
    const iconWidth = iconName ? px + 6 : 0;
    const width = context.measureText(text).width + 20 + iconWidth;
    const height = px + 14;
    context.fillStyle = light ? COLORS.primary : rgba(COLORS.background, 0.82);
    context.beginPath();
    context.roundRect(x, y, width, height, height / 2);
    context.fill();
    const color = light ? COLORS.primary_text : COLORS.text;
    if (iconName) drawIcon(context, iconName, x + 10, y + height / 2 - px / 2, px, color);
    context.fillStyle = color;
    context.textBaseline = "middle";
    context.fillText(text, x + 10 + iconWidth, y + height / 2 + 0.5);
  }

  drawLayers(context, rect) {
    const page = this.page;
    const c = page.c;
    const settings = page.settings;
    const dev = page.advanced;
    const state = c.asgardState;
    const now = performance.now() / 1000;
    const recent = now - (c.detections.at || 0) < 1.0;
    const items = recent ? c.detections.items || [] : [];
    const hovered = this.mouse ? c.personAt(this.mouse[0], this.mouse[1]) : null;
    const point = (nx, ny) => [rect.x + nx * rect.w, rect.y + ny * rect.h];

    if (dev && settings.show_grid) {
      context.save();
      context.strokeStyle = rgba(COLORS.text, 0.18);
      context.setLineDash([4, 4]);
      context.lineWidth = 1;
      context.beginPath();
      for (const f of [1 / 3, 2 / 3]) {
        context.moveTo(...point(f, 0)); context.lineTo(...point(f, 1));
        context.moveTo(...point(0, f)); context.lineTo(...point(1, f));
      }
      context.stroke();
      context.restore();
    }
    if (dev) {
      const [cx, cy] = point(0.5, 0.5);
      context.strokeStyle = rgba(COLORS.text, 0.7);
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(cx - 12, cy); context.lineTo(cx + 12, cy);
      context.moveTo(cx, cy - 12); context.lineTo(cx, cy + 12);
      context.stroke();
    }
    if (dev && settings.show_trails) {
      context.lineWidth = 2;
      for (const trail of c.trails.values()) {
        for (let i = 1; i < trail.length; i++) {
          context.strokeStyle = rgba(COLORS.warning, 0.15 + 0.6 * (i / trail.length));
          context.beginPath();
          context.moveTo(...point(trail[i - 1][1], trail[i - 1][2]));
          context.lineTo(...point(trail[i][1], trail[i][2]));
          context.stroke();
        }
      }
    }
    for (const item of items) {
      const box = item.box;
      if (!Array.isArray(box) || box.length !== 4) continue;
      const target = !!item.target;
      const under = item.id === hovered;
      if (!(target || under || (dev && settings.show_boxes))) continue;
      const [x1, y1] = point(box[0], box[1]);
      const [x2, y2] = point(box[0] + box[2], box[1] + box[3]);
      context.save();
      if (target) { context.strokeStyle = COLORS.primary; context.lineWidth = 2.5; }
      else if (under) { context.strokeStyle = rgba(COLORS.primary, 0.9); context.lineWidth = 1.6; context.setLineDash([5, 4]); }
      else { context.strokeStyle = rgba(COLORS.text_soft, 0.8); context.lineWidth = 1.2; }
      context.beginPath();
      context.roundRect(x1, y1, x2 - x1, y2 - y1, 6);
      context.stroke();
      context.restore();
      if (dev && settings.show_skeleton && Array.isArray(item.pts)) this.skeleton(context, item.pts, point, target);
      const chipY = Math.max(rect.y + 4, y1 - 30);
      if (target) this.chip(context, x1, chipY, tr("Following") + (dev ? ` · #${item.id}` : ""), true, 12, "locate-fixed");
      else if (under) this.chip(context, x1, chipY, tr("Click to follow"), false, 12, "user-round-check");
      else if (dev) this.chip(context, x1, Math.max(rect.y + 4, y1 - 28), `#${item.id}`, false, 11);
    }
    const aim = recent ? c.detections.aim : null;
    if (Array.isArray(aim) && aim.length === 2 && (dev || state.mode !== "manual")) {
      const [px, py] = point(aim[0], aim[1]);
      context.strokeStyle = COLORS.primary;
      context.lineWidth = 1.6;
      context.beginPath();
      context.arc(px, py, 7, 0, Math.PI * 2);
      context.moveTo(px - 12, py); context.lineTo(px - 4, py);
      context.moveTo(px + 4, py); context.lineTo(px + 12, py);
      context.stroke();
    }
    const mode = state.mode || "manual";
    let text;
    let iconName;
    if (mode === "follow" && state.target !== null && state.target !== undefined) {
      const situation = state.target_state !== "tracking" ? targetText(String(state.target_state || "")) : "";
      text = tr("Following person #{id}", { id: state.target }) + (situation ? ` · ${situation}` : "");
      iconName = "locate-fixed";
    } else if (mode === "auto") {
      text = tr("Automatic tracking");
      iconName = "sparkles";
    } else {
      text = tr("Manual camera");
      iconName = "move";
    }
    this.chip(context, rect.x + 14, rect.y + 14, text, false, 12, iconName);
    if (dev && settings.show_hud) this.hud(context, rect);
  }

  skeleton(context, points, point, target) {
    const color = rgba(target ? COLORS.success : COLORS.text_soft, 0.85);
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.beginPath();
    for (const [a, b] of SKELETON) {
      if (points[a] && points[b]) {
        context.moveTo(...point(...points[a]));
        context.lineTo(...point(...points[b]));
      }
    }
    context.stroke();
    context.fillStyle = color;
    for (const p of points) {
      if (!p) continue;
      const [x, y] = point(...p);
      context.beginPath();
      context.arc(x, y, 2.5, 0, Math.PI * 2);
      context.fill();
    }
  }

  hud(context, rect) {
    const page = this.page;
    const state = page.c.asgardState;
    const servo = state.servo || {};
    const ai = state.ai || {};
    const camera = state.camera || {};
    const meta = page.lastFrameMeta || {};
    const fixed = (value, digits) => Number(value || 0).toFixed(digits).padStart(digits ? 5 : 3);
    const rows = [
      [tr("video"), `${fixed(page.incomingFps, 1)} fps  ${meta.w || "?"}×${meta.h || "?"}`],
      [tr("link"), page.latencyText()],
      ["pan", `${fixed(state.pan, 1)}° → ${fixed(servo.target_pan ?? state.pan, 1)}°`],
      ["tilt", `${fixed(state.tilt, 1)}° → ${fixed(servo.target_tilt ?? state.tilt, 1)}°`],
      [tr("AI"), tr("{hz} Hz  {count} people", { hz: fixed(ai.hz, 1), count: (page.c.detections.items || []).length })],
      [tr("camera"), tr("{fps} fps  sending {sent} fps", { fps: fixed(camera.fps, 1), sent: fixed(camera.sent_fps, 1) })],
    ];
    const widthLabel = Math.max(...rows.map(([labelText]) => labelText.length)) + 2;
    const lines = rows.map(([labelText, value]) => labelText.padEnd(widthLabel) + value);
    context.font = "11px 'JetBrains Mono', ui-monospace, monospace";
    const lineHeight = 15;
    const width = Math.max(...lines.map((line) => context.measureText(line).width)) + 24;
    const height = lines.length * lineHeight + 16;
    const x = rect.x + rect.w - width - 14;
    const y = rect.y + 14;
    context.fillStyle = rgba(COLORS.background, 0.78);
    context.strokeStyle = rgba(COLORS.border, 0.8);
    context.lineWidth = 1;
    context.beginPath();
    context.roundRect(x, y, width, height, 6);
    context.fill();
    context.stroke();
    context.fillStyle = COLORS.text;
    context.textBaseline = "middle";
    lines.forEach((line, index) => context.fillText(line, x + 12, y + 8 + lineHeight * index + lineHeight / 2));
  }
}
