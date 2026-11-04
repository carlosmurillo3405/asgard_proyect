// Configuración del firmware de los servos de Asgard.
#pragma once

#include <Arduino.h>

// Versión del firmware y del protocolo que espera Asgard (asgard/esp32.py).
#define ASGARD_FIRMWARE "2.0.0"
constexpr int PROTOCOL = 2;
constexpr uint32_t BAUD_RATE = 115200;

// Pin de cada canal: 0 = pan (horizontal), 1 = tilt (vertical), 2 = mano.
// Se evitan los pines de arranque (strapping) y los del puerto serie, para que
// los servos no reciban basura al encender o al programar el ESP32.
#if defined(CONFIG_IDF_TARGET_ESP32S2) || defined(CONFIG_IDF_TARGET_ESP32S3) || \
    defined(CONFIG_IDF_TARGET_ESP32C3) || defined(CONFIG_IDF_TARGET_ESP32C6)
constexpr uint8_t PINS[] = {4, 5, 6};
#else  // ESP32 clásico (DevKit, WROOM-32)
constexpr uint8_t PINS[] = {25, 26, 27};
#endif
constexpr uint8_t CHANNELS = sizeof(PINS) / sizeof(PINS[0]);

// Señal de servo: 50 Hz (periodo de 20 ms) con 14 bits, 1,22 µs por paso.
constexpr uint32_t FREQUENCY_HZ = 50;
constexpr uint8_t RESOLUTION_BITS = 14;
constexpr uint32_t PERIOD_US = 1000000UL / FREQUENCY_HZ;
constexpr uint16_t MIN_PULSE_US = 400;     // los pulsos válidos se limitan a este rango
constexpr uint16_t MAX_PULSE_US = 2600;
constexpr long PULSE_LIMIT_US = 3000;      // más que esto se rechaza como orden errónea

constexpr uint32_t MAX_TIMEOUT_MS = 60000; // máximo del perro guardián (orden T)
constexpr size_t MAX_LINE = 96;            // largo máximo de una orden
