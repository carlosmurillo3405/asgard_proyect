// PWM por hardware del ESP32 (LEDC): 50 Hz con 14 bits, 1,22 µs por paso.

#if defined(ARDUINO_ARCH_ESP32)

#include "config.h"
#include "servos.h"

namespace servos {

static uint16_t pulse_us[CHANNELS];   // 0 = suelto

constexpr uint32_t FREQUENCY_HZ = 1000000UL / PERIOD_US;
constexpr uint8_t RESOLUTION_BITS = 14;

// Núcleo 3.x: ledcAttach/ledcWrite por pin. Núcleo 2.x: ledcSetup/ledcAttachPin por canal.
static void prepare(uint8_t channel) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PINS[channel], FREQUENCY_HZ, RESOLUTION_BITS);
#else
  ledcSetup(channel, FREQUENCY_HZ, RESOLUTION_BITS);
  ledcAttachPin(PINS[channel], channel);
#endif
}

static void write_duty(uint8_t channel, uint32_t duty) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PINS[channel], duty);
#else
  ledcWrite(channel, duty);
#endif
}

void begin() {
  for (uint8_t channel = 0; channel < CHANNELS; channel++) {
    prepare(channel);
    apply(channel, 0);
  }
}

void apply(uint8_t channel, uint16_t us) {
  if (channel >= CHANNELS) {
    return;
  }
  if (us != 0) {
    us = constrain(us, MIN_PULSE_US, MAX_PULSE_US);
  }
  pulse_us[channel] = us;
  // Ciclo 0 = salida en bajo todo el periodo: sin pulsos, el servo queda suelto.
  write_duty(channel, ((uint32_t)us << RESOLUTION_BITS) / PERIOD_US);
}

void release_all() {
  for (uint8_t channel = 0; channel < CHANNELS; channel++) {
    apply(channel, 0);
  }
}

uint16_t pulse(uint8_t channel) {
  return channel < CHANNELS ? pulse_us[channel] : 0;
}

}  // namespace servos

#endif  // ARDUINO_ARCH_ESP32
