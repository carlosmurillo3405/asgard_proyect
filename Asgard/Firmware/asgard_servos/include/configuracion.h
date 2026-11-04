// Configuración del firmware de los servos de Asgard.
#pragma once

#include <Arduino.h>

// Versión del firmware y del protocolo que espera Asgard (asgard/esp32.py).
#define ASGARD_FIRMWARE "1.0.0"
constexpr int PROTOCOLO = 1;
constexpr uint32_t BAUDIOS = 115200;

// Pin de cada canal: 0 = pan (horizontal), 1 = tilt (vertical), 2 = mano.
// Se evitan los pines de arranque (strapping) y los del puerto serie, para que
// los servos no reciban basura al encender o al programar el ESP32.
#if defined(CONFIG_IDF_TARGET_ESP32S2) || defined(CONFIG_IDF_TARGET_ESP32S3) || \
    defined(CONFIG_IDF_TARGET_ESP32C3) || defined(CONFIG_IDF_TARGET_ESP32C6)
constexpr uint8_t PINES[] = {4, 5, 6};
#else  // ESP32 clásico (DevKit, WROOM-32)
constexpr uint8_t PINES[] = {25, 26, 27};
#endif
constexpr uint8_t CANALES = sizeof(PINES) / sizeof(PINES[0]);

// Señal de servo: 50 Hz (periodo de 20 ms) con 14 bits, 1,22 µs por paso.
constexpr uint32_t FRECUENCIA_HZ = 50;
constexpr uint8_t BITS = 14;
constexpr uint32_t PERIODO_US = 1000000UL / FRECUENCIA_HZ;
constexpr uint16_t PULSO_MIN_US = 400;     // los pulsos válidos se limitan a este rango
constexpr uint16_t PULSO_MAX_US = 2600;
constexpr long PULSO_LIMITE_US = 3000;     // más que esto se rechaza como orden errónea

constexpr uint32_t ESPERA_MAX_MS = 60000;  // máximo del perro guardián (orden T)
constexpr size_t LINEA_MAX = 96;           // largo máximo de una orden
