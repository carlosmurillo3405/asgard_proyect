// Señal de los servos con el PWM por hardware del ESP32 (LEDC).
#pragma once

#include <Arduino.h>

namespace servos {

// Prepara todos los canales sin pulsos (servos sueltos).
void iniciar();

// Ancho de pulso en µs. 0 suelta el servo; otro valor se limita a
// PULSO_MIN_US..PULSO_MAX_US.
void aplicar(uint8_t canal, uint16_t us);

void soltar_todo();

uint16_t pulso(uint8_t canal);

}  // namespace servos
