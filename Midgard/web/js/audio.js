// Audio de la llamada en el navegador (equivalente a audio.py de escritorio).
// Siempre en máxima calidad: PCM de 16 bits a 48 kHz. Por el puerto web viaja en
// paquetes A del canal de control (el respaldo TCP del protocolo).

import { tr } from "./i18n.js";
import { AUDIO_RATE } from "./protocol.js";

export const audioSupported = typeof window.AudioWorkletNode === "function" && !!navigator.mediaDevices;

export class AudioEngine {
  constructor() {
    this.context = null;
    this.playback = null;
    this.capture = null;
    this.microphoneStream = null;
    this.microphoneSource = null;
    this.link = null;
    this.micOn = true;
    this.speakerOn = true;
    this.inputLevel = 0;
    this.playbackStats = { buffer_ms: 0, target_ms: 60, underruns: 0, overflows: 0 };
    this.received = 0;
    this.sent = 0;
    this.errors = [];
  }

  get active() {
    return this.context !== null;
  }

  /** Starts playback and, if possible, the microphone. Errors are kept in ``errors``. */
  async start(link, microphone, speaker) {
    this.link = link;
    this.errors = [];
    if (!audioSupported) {
      this.errors.push(tr("This browser cannot play the call's audio."));
      return;
    }
    const context = new AudioContext({ sampleRate: AUDIO_RATE, latencyHint: "interactive" });
    this.context = context;
    await context.audioWorklet.addModule("js/audio-worklet.js");
    this.playback = new AudioWorkletNode(context, "asgard-playback", { numberOfInputs: 0, outputChannelCount: [2] });
    this.playback.port.onmessage = (event) => { this.playbackStats = event.data; };
    this.playback.connect(context.destination);
    await this.setSpeaker(speaker);
    await this.openMicrophone(microphone);
    if (context.state === "suspended") {
      try {
        await context.resume();
      } catch {
        // se reanuda con el siguiente clic del usuario
      }
    }
  }

  async openMicrophone(deviceId) {
    this.closeMicrophone();
    if (!this.context) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      this.errors.push(tr("The microphone is only available on HTTPS pages."));
      return;
    }
    try {
      this.microphoneStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId: deviceId ? { exact: deviceId } : undefined,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
    } catch (error) {
      this.errors.push(tr("The microphone could not be opened: {error}", { error: error.message || error.name }));
      return;
    }
    this.microphoneSource = this.context.createMediaStreamSource(this.microphoneStream);
    this.capture = new AudioWorkletNode(this.context, "asgard-capture", { numberOfOutputs: 1, outputChannelCount: [1] });
    this.capture.port.onmessage = (event) => {
      this.inputLevel = event.data.level;
      if (this.micOn && this.link && this.link.sendAudio(1, new Int16Array(event.data.pcm))) this.sent += 1;
    };
    this.microphoneSource.connect(this.capture);
    this.capture.connect(this.context.destination);     // silencio: solo para que el navegador lo procese
  }

  closeMicrophone() {
    if (this.microphoneStream) for (const track of this.microphoneStream.getTracks()) track.stop();
    if (this.microphoneSource) this.microphoneSource.disconnect();
    if (this.capture) this.capture.disconnect();
    this.microphoneStream = null;
    this.microphoneSource = null;
    this.capture = null;
    this.inputLevel = 0;
  }

  async setSpeaker(deviceId) {
    if (!this.context || typeof this.context.setSinkId !== "function") return "";
    try {
      await this.context.setSinkId(deviceId || "");
      return "";
    } catch (error) {
      return tr("The speaker could not be changed: {error}", { error: error.message || error.name });
    }
  }

  async resume() {
    if (this.context && this.context.state === "suspended") {
      try {
        await this.context.resume();
      } catch {
        // sin gesto del usuario el navegador no lo permite todavía
      }
    }
  }

  feed(meta, data) {
    if (!this.playback || !this.speakerOn) return;
    const channels = meta.ch === 2 ? 2 : 1;
    if (data.byteLength % (2 * channels) !== 0) return;
    this.received += 1;
    this.playback.port.postMessage({ pcm: data.buffer, channels }, [data.buffer]);
  }

  setSpeakerOn(on) {
    this.speakerOn = on;
    if (!on && this.playback) this.playback.port.postMessage({ clear: true });
  }

  /** Message tone on the chosen speaker (audio test). */
  playTone() {
    if (!this.context) return false;
    const now = this.context.currentTime;
    for (const [frequency, start] of [[880, 0], [1320, 0.12]]) {
      const oscillator = this.context.createOscillator();
      const gain = this.context.createGain();
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0, now + start);
      gain.gain.linearRampToValueAtTime(0.25, now + start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.001, now + start + 0.22);
      oscillator.connect(gain).connect(this.context.destination);
      oscillator.start(now + start);
      oscillator.stop(now + start + 0.25);
    }
    return true;
  }

  stats() {
    return {
      transport: "websocket",
      microphone: this.microphoneStream !== null,
      speaker: this.playback !== null,
      input_level: this.inputLevel,
      buffer_ms: this.playbackStats.buffer_ms,
      target_ms: this.playbackStats.target_ms,
      underruns: this.playbackStats.underruns,
      overflows: this.playbackStats.overflows,
      received_tcp: this.received,
      sent_tcp: this.sent,
    };
  }

  stop() {
    this.closeMicrophone();
    if (this.playback) this.playback.disconnect();
    this.playback = null;
    if (this.context) this.context.close().catch(() => {});
    this.context = null;
    this.link = null;
  }
}
