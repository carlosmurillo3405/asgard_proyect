// Señal de los servos con el PWM por hardware del ESP32 (LEDC).
#pragma once

#include <Arduino.h>

namespace servos {

// Prepara todos los canales sin pulsos (servos sueltos).
void begin();

// Ancho de pulso en µs. 0 suelta el servo; otro valor se limita a
// MIN_PULSE_US..MAX_PULSE_US.
void apply(uint8_t channel, uint16_t us);

void release_all();

uint16_t pulse(uint8_t channel);

}  // namespace servos
