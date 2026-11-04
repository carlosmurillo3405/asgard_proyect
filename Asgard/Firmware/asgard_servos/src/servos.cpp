#include "servos.h"

#include "configuracion.h"

namespace servos {

static uint16_t pulso_us[CANALES];   // 0 = suelto

// Núcleo 3.x: ledcAttach/ledcWrite por pin. Núcleo 2.x: ledcSetup/ledcAttachPin por canal.
static void preparar(uint8_t canal) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PINES[canal], FRECUENCIA_HZ, BITS);
#else
  ledcSetup(canal, FRECUENCIA_HZ, BITS);
  ledcAttachPin(PINES[canal], canal);
#endif
}

static void escribir_ciclo(uint8_t canal, uint32_t ciclo) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PINES[canal], ciclo);
#else
  ledcWrite(canal, ciclo);
#endif
}

void iniciar() {
  for (uint8_t canal = 0; canal < CANALES; canal++) {
    preparar(canal);
    aplicar(canal, 0);
  }
}

void aplicar(uint8_t canal, uint16_t us) {
  if (canal >= CANALES) {
    return;
  }
  if (us != 0) {
    us = constrain(us, PULSO_MIN_US, PULSO_MAX_US);
  }
  pulso_us[canal] = us;
  // Ciclo 0 = salida en bajo todo el periodo: sin pulsos, el servo queda suelto.
  escribir_ciclo(canal, ((uint32_t)us << BITS) / PERIODO_US);
}

void soltar_todo() {
  for (uint8_t canal = 0; canal < CANALES; canal++) {
    aplicar(canal, 0);
  }
}

uint16_t pulso(uint8_t canal) {
  return canal < CANALES ? pulso_us[canal] : 0;
}

}  // namespace servos
