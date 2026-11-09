// Configuración del firmware de los servos de Asgard.
#pragma once

#include <Arduino.h>

// Versión del firmware y del protocolo que espera Asgard (asgard/servo_board.py).
#define ASGARD_FIRMWARE "2.1.0"
constexpr int PROTOCOL = 2;
constexpr uint32_t BAUD_RATE = 115200;

// Pin de cada canal: 0 = pan (horizontal), 1 = tilt (vertical), 2 = mano.
#if defined(ARDUINO_ARCH_AVR)
// Arduino Uno / Nano (ATmega328P): cada canal sale de un comparador de un temporizador,
// así el pulso lo genera el hardware y no depende de lo que haga el programa.
//   D9  = OC1A y D10 = OC1B: Timer1 de 16 bits, pasos de 0,5 µs a 50 Hz (pan y tilt)
//   D3  = OC2B: Timer2 de 8 bits, pasos de 64 µs a 61 Hz (mano: le basta con dos posiciones)
// No se usan D0/D1 (puerto serie) ni D13 (el LED parpadea al arrancar el cargador).
constexpr uint8_t PINS[] = {9, 10, 3};
#elif defined(CONFIG_IDF_TARGET_ESP32S2) || defined(CONFIG_IDF_TARGET_ESP32S3) || \
    defined(CONFIG_IDF_TARGET_ESP32C3) || defined(CONFIG_IDF_TARGET_ESP32C6)
// ESP32-S3 / C3 / C6: pines sin función de arranque (strapping) ni puerto serie.
constexpr uint8_t PINS[] = {4, 5, 6};
#else
// ESP32 clásico (DevKit, WROOM-32).
constexpr uint8_t PINS[] = {25, 26, 27};
#endif
constexpr uint8_t CHANNELS = sizeof(PINS) / sizeof(PINS[0]);

// Señal de servo: periodo de 20 ms (50 Hz).
constexpr uint32_t PERIOD_US = 20000;
constexpr uint16_t MIN_PULSE_US = 400;     // los pulsos válidos se limitan a este rango
constexpr uint16_t MAX_PULSE_US = 2600;
constexpr long PULSE_LIMIT_US = 3000;      // más que esto se rechaza como orden errónea

constexpr uint32_t MAX_TIMEOUT_MS = 60000; // máximo del perro guardián (orden T)
constexpr size_t MAX_LINE = 64;            // largo máximo de una orden (cabe en la RAM del Uno)
