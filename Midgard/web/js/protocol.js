// Protocolo del sistema Asgard (versión 3), el mismo de Common/protocol.py.
// Paquete: [largo del cuerpo u32][tipo: 1 letra][largo del JSON u32][JSON UTF-8][datos].
// Por el puerto web de Bifröst cada mensaje WebSocket lleva uno o más paquetes.

import { tr } from "./i18n.js";

export const PROTOCOL_VERSION = 3;
export const HELLO = "H";
export const WELCOME = "W";
export const REJECT = "X";
export const CONTROL = "C";
export const AUDIO = "A";
export const VIDEO = "V";
export const SCREEN = "S";
export const KEEPALIVE = "K";
export const ROLE_MIDGARD = "midgard";
export const ROLE_MEDIA = "media";
export const STATUS_AVAILABLE = "available";
export const STATUS_BUSY = "in_session";
export const STATUS_OFFLINE = "offline";
export const MAX_CHAT_LENGTH = 1000;
export const AUDIO_RATE = 48000;
export const AUDIO_BLOCK_FRAMES = 240;          // 5 ms, como el audio de escritorio
const MAX_PACKET = 16 * 1024 * 1024;

const encoder = new TextEncoder();
const decoder = new TextDecoder();

/** Serializes a packet ready to send. ``data`` is an ArrayBuffer or a typed array. */
export function encodePacket(type, meta = {}, data = null) {
  const json = encoder.encode(JSON.stringify(meta));
  const bytes = data ? (data instanceof ArrayBuffer ? new Uint8Array(data) : new Uint8Array(data.buffer, data.byteOffset, data.byteLength)) : null;
  const body = 1 + 4 + json.length + (bytes ? bytes.length : 0);
  const packet = new Uint8Array(4 + body);
  const view = new DataView(packet.buffer);
  view.setUint32(0, body);
  packet[4] = type.charCodeAt(0);
  view.setUint32(5, json.length);
  packet.set(json, 9);
  if (bytes) packet.set(bytes, 9 + json.length);
  return packet;
}

/** Joins the received bytes and returns complete packets: {type, meta, data}. */
export class PacketReader {
  constructor() {
    this.buffer = new Uint8Array(0);
  }

  push(chunk) {
    const incoming = new Uint8Array(chunk);
    if (this.buffer.length === 0) {
      this.buffer = incoming;
    } else {
      const joined = new Uint8Array(this.buffer.length + incoming.length);
      joined.set(this.buffer);
      joined.set(incoming, this.buffer.length);
      this.buffer = joined;
    }
    const packets = [];
    let offset = 0;
    while (this.buffer.length - offset >= 4) {
      const view = new DataView(this.buffer.buffer, this.buffer.byteOffset + offset);
      const body = view.getUint32(0);
      if (body < 5 || body > MAX_PACKET) throw new Error("invalid packet size");
      if (this.buffer.length - offset < 4 + body) break;
      const type = String.fromCharCode(this.buffer[offset + 4]);
      const metaLength = view.getUint32(5);
      const metaStart = offset + 9;
      const metaEnd = metaStart + metaLength;
      if (metaEnd > offset + 4 + body) throw new Error("invalid metadata size");
      const meta = metaLength ? JSON.parse(decoder.decode(this.buffer.subarray(metaStart, metaEnd))) : {};
      const data = this.buffer.slice(metaEnd, offset + 4 + body);
      packets.push({ type, meta, data });
      offset += 4 + body;
    }
    this.buffer = offset ? this.buffer.slice(offset) : this.buffer;
    return packets;
  }
}

/** Text of a message from Bifröst or the Asgard in this user's language (English template + values). */
export function messageText(meta, fallback = "") {
  const text = meta && meta.message;
  if (typeof text !== "string" || !text) return fallback;
  return meta.args && typeof meta.args === "object" ? tr(text, meta.args) : tr(text);
}

export function b64encode(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  return btoa(binary);
}
