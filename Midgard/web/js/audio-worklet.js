// Procesadores de audio de Midgard Web (corren en el hilo de audio del navegador).
//
// asgard-capture: micrófono -> bloques de 240 muestras (5 ms) PCM de 16 bits a 48 kHz.
// asgard-playback: PCM recibido -> salida estéreo con un colchón (jitter buffer)
//                  que empieza en 60 ms y descarta lo que pase de 300 ms.

const BLOCK = 240;

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Int16Array(BLOCK);
    this.fill = 0;
    this.peak = 0;
  }

  process(inputs, outputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      for (let i = 0; i < channel.length; i++) {
        let sample = channel[i];
        if (sample > 1) sample = 1;
        else if (sample < -1) sample = -1;
        const size = sample < 0 ? -sample : sample;
        if (size > this.peak) this.peak = size;
        this.block[this.fill++] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
        if (this.fill === BLOCK) {
          this.port.postMessage({ pcm: this.block.buffer, level: this.peak }, [this.block.buffer]);
          this.block = new Int16Array(BLOCK);
          this.fill = 0;
          this.peak = 0;
        }
      }
    }
    for (const output of outputs) for (const data of output) data.fill(0);   // no suena: solo captura
    return true;
  }
}

class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.capacity = sampleRate * 2;            // 2 s
    this.left = new Float32Array(this.capacity);
    this.right = new Float32Array(this.capacity);
    this.readAt = 0;
    this.writeAt = 0;
    this.size = 0;
    this.playing = false;
    this.target = Math.round(sampleRate * 0.06);
    this.limit = Math.round(sampleRate * 0.3);
    this.underruns = 0;
    this.overflows = 0;
    this.calls = 0;
    this.port.onmessage = (event) => {
      if (event.data.clear) {
        this.size = 0;
        this.readAt = this.writeAt;
        this.playing = false;
      } else if (event.data.pcm) {
        this.push(new Int16Array(event.data.pcm), event.data.channels || 1);
      }
    };
  }

  push(samples, channels) {
    const frames = Math.floor(samples.length / channels);
    if (this.size + frames > this.limit) {
      // Demasiado retraso acumulado: se descarta lo más viejo y se vuelve al objetivo.
      const skip = Math.min(this.size, this.size + frames - this.target);
      this.readAt = (this.readAt + skip) % this.capacity;
      this.size -= skip;
      this.overflows += 1;
    }
    for (let i = 0; i < frames; i++) {
      const left = samples[i * channels] / 32768;
      this.left[this.writeAt] = left;
      this.right[this.writeAt] = channels > 1 ? samples[i * channels + 1] / 32768 : left;
      this.writeAt = (this.writeAt + 1) % this.capacity;
    }
    this.size = Math.min(this.capacity, this.size + frames);
  }

  process(inputs, outputs) {
    const output = outputs[0];
    const left = output[0];
    const right = output[1] || output[0];
    if (!this.playing && this.size >= this.target) this.playing = true;
    for (let i = 0; i < left.length; i++) {
      if (this.playing && this.size > 0) {
        left[i] = this.left[this.readAt];
        right[i] = this.right[this.readAt];
        this.readAt = (this.readAt + 1) % this.capacity;
        this.size -= 1;
      } else {
        left[i] = 0;
        right[i] = 0;
        if (this.playing) {
          this.playing = false;          // se vació: se vuelve a llenar el colchón antes de seguir
          this.underruns += 1;
        }
      }
    }
    this.calls += 1;
    if (this.calls % 40 === 0) {
      this.port.postMessage({ buffer_ms: Math.round((this.size / sampleRate) * 1000), target_ms: Math.round((this.target / sampleRate) * 1000),
                              underruns: this.underruns, overflows: this.overflows });
    }
    return true;
  }
}

registerProcessor("asgard-capture", CaptureProcessor);
registerProcessor("asgard-playback", PlaybackProcessor);
