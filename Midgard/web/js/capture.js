// Envío de la cámara y de la pantalla del usuario (equivalente a capture.py).
// Cada cuadro se reduce al perfil (nunca se amplía), se comprime en JPEG y se
// envía por el canal de medios; si la red no alcanza se salta el cuadro, así
// baja la frecuencia pero no crece el retraso.

import { tr } from "./i18n.js";
import { SCREEN, VIDEO } from "./protocol.js";

export const CAMERA_PROFILES = {
  Low: { width: 640, height: 360, fps: 12, quality: 45 },
  Medium: { width: 1280, height: 720, fps: 20, quality: 70 },
  High: { width: 1920, height: 1080, fps: 30, quality: 90 },
};
export const SCREEN_PROFILES = {
  Low: { width: 640, height: 360, fps: 12, quality: 50 },
  Medium: { width: 1280, height: 720, fps: 20, quality: 75 },
  High: { width: 1920, height: 1080, fps: 30, quality: 90 },
  Excellent: { width: 2560, height: 1440, fps: 30, quality: 94 },
};
export const screenShareSupported = !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia);
export const cameraSupported = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

export function describeProfile(profile) {
  return `${profile.width}×${profile.height} · ${profile.fps} fps · JPEG ${profile.quality}`;
}

class Sender {
  constructor(link, stream, profile, stream_type, onError) {
    this.link = link;
    this.stream = stream;
    this.profile = profile;
    this.type = stream_type;
    this.onError = onError;
    this.running = false;
    this.sequence = 0;
    this.fps = 0;
    this._sentAt = [];
    this._busy = false;
    this.video = document.createElement("video");
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.autoplay = true;
    this.video.srcObject = stream;
    this.canvas = document.createElement("canvas");
    this.context = this.canvas.getContext("2d", { alpha: false });
    for (const track of stream.getVideoTracks()) {
      track.addEventListener("ended", () => {
        if (this.running) {
          this.stop();
          this.onError(stream_type === SCREEN ? tr("Screen sharing stopped.") : tr("The camera stopped delivering images."));
        }
      });
    }
  }

  async start() {
    this.running = true;
    try {
      await this.video.play();
    } catch {
      // algunos navegadores reproducen solo al recibir el primer cuadro
    }
    this._tick();
  }

  _tick() {
    if (!this.running) return;
    const interval = 1000 / this.profile.fps;
    this._timer = setTimeout(() => this._tick(), interval);
    if (this._busy || this.video.readyState < 2 || this.link.framePending()) return;
    const sourceWidth = this.video.videoWidth;
    const sourceHeight = this.video.videoHeight;
    if (!sourceWidth || !sourceHeight) return;
    const scale = Math.min(1, this.profile.width / sourceWidth, this.profile.height / sourceHeight);
    const width = Math.max(2, Math.round((sourceWidth * scale) / 2) * 2);
    const height = Math.max(2, Math.round((sourceHeight * scale) / 2) * 2);
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    this.context.drawImage(this.video, 0, 0, width, height);
    this._busy = true;
    this.canvas.toBlob(async (blob) => {
      try {
        if (!blob || !this.running) return;
        const data = await blob.arrayBuffer();
        this.sequence += 1;
        if (this.link.sendFrame(this.type, { seq: this.sequence, w: width, h: height, ts: Math.round(performance.now()) }, data)) {
          const now = performance.now();
          this._sentAt.push(now);
          while (this._sentAt.length && now - this._sentAt[0] > 2000) this._sentAt.shift();
          this.fps = this._sentAt.length / 2;
        }
      } finally {
        this._busy = false;
      }
    }, "image/jpeg", this.profile.quality / 100);
  }

  stop() {
    this.running = false;
    clearTimeout(this._timer);
    for (const track of this.stream.getTracks()) track.stop();
    this.video.srcObject = null;
  }
}

export async function startCamera(link, deviceId, profile, onError) {
  if (!cameraSupported) throw new Error(tr("The camera is only available on HTTPS pages."));
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      deviceId: deviceId ? { exact: deviceId } : undefined,
      width: { ideal: profile.width },
      height: { ideal: profile.height },
      frameRate: { ideal: profile.fps },
    },
  });
  const sender = new Sender(link, stream, profile, VIDEO, onError);
  await sender.start();
  return sender;
}

export async function startScreen(link, profile, onError) {
  if (!screenShareSupported) throw new Error(tr("This browser cannot share the screen."));
  const stream = await navigator.mediaDevices.getDisplayMedia({ audio: false, video: { frameRate: { ideal: profile.fps } } });
  const sender = new Sender(link, stream, profile, SCREEN, onError);
  await sender.start();
  return sender;
}
