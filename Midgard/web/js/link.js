// Enlace con Bifröst por su puerto web (equivalente a client_link.py).
//
// Abre dos WebSocket a /ws: el canal de control (saludo, órdenes, chat y audio
// en paquetes A) y el de medios (cuadros JPEG). Si la red se corta, se vuelve a
// conectar con espera creciente; el saludo lleva el token del usuario y el de la
// llamada, así Bifröst reanuda la sesión sin pedir la contraseña.

import { tr } from "./i18n.js";
import {
  AUDIO, CONTROL, HELLO, KEEPALIVE, PROTOCOL_VERSION, PacketReader, REJECT, ROLE_MEDIA, SCREEN, VIDEO, WELCOME,
  encodePacket, messageText,
} from "./protocol.js";

export const STATE_CONNECTING = "connecting";
export const STATE_CONNECTED = "connected";
export const STATE_DISCONNECTED = "disconnected";
export const STATE_STOPPED = "stopped";

const KEEPALIVE_MS = 10000;
const PING_MS = 5000;
const AUDIO_QUEUE_LIMIT = 96 * 1024;       // sin colchón en el envío: el audio viejo no sirve
const FRAME_QUEUE_LIMIT = 512 * 1024;
const RETRY_STEPS = [1000, 2000, 4000, 8000, 15000];

export class Link {
  constructor(options) {
    this.url = options.url;
    this.label = options.label || options.url;
    this.hello = options.hello;
    this.onWelcome = options.onWelcome || (() => {});
    this.onControl = options.onControl || (() => {});
    this.onAudio = options.onAudio || (() => {});
    this.onFrame = options.onFrame || (() => {});
    this.onState = options.onState || (() => {});
    this.onProblem = options.onProblem || (() => {});
    this.control = null;
    this.media = null;
    this.welcomed = false;
    this.stopped = true;
    this.fatal = false;
    this.attempt = 0;
    this.rttMs = null;
    this.bytesSent = 0;
    this.bytesReceived = 0;
    this._timers = [];
    this._retry = null;
    this._mediaRetry = null;
  }

  get connected() {
    return this.welcomed && this.control !== null && this.control.readyState === WebSocket.OPEN;
  }

  get mediaConnected() {
    return this.media !== null && this.media.readyState === WebSocket.OPEN && this.media.welcomed === true;
  }

  start() {
    this.stopped = false;
    this.fatal = false;
    this._connect();
  }

  stop() {
    this.stopped = true;
    clearTimeout(this._retry);
    clearTimeout(this._mediaRetry);
    this._closeSockets();
    this._setState(STATE_STOPPED, "");
  }

  sendControl(meta) {
    if (!this.connected) return false;
    return this._send(this.control, encodePacket(CONTROL, meta));
  }

  sendAudio(channels, pcm) {
    if (!this.connected || this.control.bufferedAmount > AUDIO_QUEUE_LIMIT) return false;
    return this._send(this.control, encodePacket(AUDIO, { ch: channels }, pcm));
  }

  framePending() {
    return !this.mediaConnected || this.media.bufferedAmount > FRAME_QUEUE_LIMIT;
  }

  sendFrame(stream, meta, data) {
    if (this.framePending()) return false;
    return this._send(this.media, encodePacket(stream, meta, data));
  }

  stats() {
    return {
      state: this.connected ? STATE_CONNECTED : STATE_DISCONNECTED,
      connected: this.connected,
      media: this.mediaConnected,
      rtt_ms: this.rttMs,
      bytes_sent: this.bytesSent,
      bytes_received: this.bytesReceived,
    };
  }

  // -- conexión --------------------------------------------------------------- //
  _connect() {
    if (this.stopped) return;
    this._closeSockets();
    this.welcomed = false;
    this._setState(STATE_CONNECTING, this.label);
    let socket;
    try {
      socket = new WebSocket(this.url);
    } catch (error) {
      this._failed(tr("Could not connect to the server."));
      return;
    }
    socket.binaryType = "arraybuffer";
    const reader = new PacketReader();
    this.control = socket;
    socket.onopen = () => {
      this._send(socket, encodePacket(HELLO, this.hello()));
    };
    socket.onmessage = (event) => {
      if (socket !== this.control) return;
      this.bytesReceived += event.data.byteLength || 0;
      let packets;
      try {
        packets = reader.push(event.data);
      } catch (error) {
        socket.close();
        return;
      }
      for (const packet of packets) this._onControlPacket(socket, packet);
    };
    socket.onclose = () => {
      if (socket !== this.control) return;
      this.control = null;
      const wasWelcomed = this.welcomed;
      this.welcomed = false;
      this._stopTimers();
      if (this.media) {
        this.media.close();
        this.media = null;
      }
      if (this.stopped) return;
      if (this.fatal) {
        this.stopped = true;
        return;
      }
      this._failed(wasWelcomed ? tr("The connection with the server was lost.") : tr("Could not connect to the server."));
    };
  }

  _failed(detail) {
    this._setState(STATE_DISCONNECTED, detail);
    const delay = RETRY_STEPS[Math.min(this.attempt, RETRY_STEPS.length - 1)];
    this.attempt += 1;
    clearTimeout(this._retry);
    this._retry = setTimeout(() => this._connect(), delay);
  }

  _onControlPacket(socket, packet) {
    if (packet.type === WELCOME && !this.welcomed) {
      this.welcomed = true;
      this.attempt = 0;
      this._setState(STATE_CONNECTED, "");
      this._startTimers();
      this._openMedia(packet.meta.media_token);
      this.onWelcome(packet.meta);
    } else if (packet.type === REJECT) {
      const message = messageText(packet.meta, tr("The server rejected the connection."));
      // «shutdown»: el servidor se reinicia y se reintenta; cualquier otro rechazo es definitivo.
      this.fatal = packet.meta.code !== "shutdown";
      this.onProblem("rejected", { code: String(packet.meta.code || ""), message });
      this._setState(STATE_DISCONNECTED, message);
      socket.close();
    } else if (packet.type === CONTROL) {
      if (packet.meta.op === "pong" && typeof packet.meta.t === "number") {
        this.rttMs = performance.now() - packet.meta.t;
        return;
      }
      this.onControl(packet.meta);
    } else if (packet.type === AUDIO) {
      this.onAudio(packet.meta, packet.data);
    }
  }

  _openMedia(token) {
    clearTimeout(this._mediaRetry);
    if (!token || this.stopped || !this.connected) return;
    let socket;
    try {
      socket = new WebSocket(this.url);
    } catch {
      return;
    }
    socket.binaryType = "arraybuffer";
    socket.welcomed = false;
    const reader = new PacketReader();
    this.media = socket;
    socket.onopen = () => {
      this._send(socket, encodePacket(HELLO, { role: ROLE_MEDIA, version: PROTOCOL_VERSION, token }));
    };
    socket.onmessage = (event) => {
      this.bytesReceived += event.data.byteLength || 0;
      let packets;
      try {
        packets = reader.push(event.data);
      } catch {
        socket.close();
        return;
      }
      for (const packet of packets) {
        if (packet.type === WELCOME) socket.welcomed = true;
        else if (packet.type === VIDEO || packet.type === SCREEN) this.onFrame(packet.type, packet.meta, packet.data);
        else if (packet.type === REJECT) socket.close();
      }
    };
    socket.onclose = () => {
      if (this.media === socket) this.media = null;
      if (!this.stopped && this.connected) {
        this._mediaRetry = setTimeout(() => this._openMedia(token), 2000);
      }
    };
  }

  _send(socket, packet) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    try {
      socket.send(packet);
      this.bytesSent += packet.byteLength;
      return true;
    } catch {
      return false;
    }
  }

  _startTimers() {
    this._stopTimers();
    const keepalive = encodePacket(KEEPALIVE);
    this._timers.push(setInterval(() => {
      this._send(this.control, keepalive);
      this._send(this.media, keepalive);
    }, KEEPALIVE_MS));
    const ping = () => this.sendControl({ op: "ping", t: performance.now() });
    this._timers.push(setInterval(ping, PING_MS));
    ping();
  }

  _stopTimers() {
    for (const timer of this._timers) clearInterval(timer);
    this._timers = [];
  }

  _closeSockets() {
    this._stopTimers();
    for (const socket of [this.control, this.media]) {
      if (socket) {
        socket.onclose = null;
        try {
          socket.close();
        } catch {
          // ya cerrado
        }
      }
    }
    this.control = null;
    this.media = null;
    this.welcomed = false;
  }

  _setState(state, detail) {
    this.onState(state, detail);
  }
}
