#include "board.h"

#if defined(ARDUINO_ARCH_AVR)
#include <avr/wdt.h>
#elif defined(ARDUINO_ARCH_ESP32)
#include <esp_system.h>
#endif

namespace board {

static const char *reason = "unknown";

#if defined(ARDUINO_ARCH_AVR)

void begin() {
  // MCUSR guarda por qué arrancó el chip. El cargador Optiboot del Uno lo borra
  // antes de saltar al programa, así que casi siempre llega en cero («unknown»);
  // sin cargador (programado por ICSP) sí se conoce el motivo.
  const uint8_t flags = MCUSR;
  MCUSR = 0;
  wdt_disable();   // tras un reinicio por vigilante, el AVR lo deja encendido
  if (flags & _BV(PORF)) {
    reason = "poweron";
  } else if (flags & _BV(BORF)) {
    reason = "brownout";
  } else if (flags & _BV(WDRF)) {
    reason = "watchdog";
  } else if (flags & _BV(EXTRF)) {
    reason = "external";
  }
}

const char *chip() {
#if defined(__AVR_ATmega328P__)
  return "ATmega328P";
#elif defined(__AVR_ATmega328__)
  return "ATmega328";
#else
  return "AVR";
#endif
}

#elif defined(ARDUINO_ARCH_ESP32)

void begin() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: reason = "poweron"; break;
    case ESP_RST_BROWNOUT: reason = "brownout"; break;
    case ESP_RST_SW: reason = "software"; break;
    case ESP_RST_PANIC: reason = "panic"; break;
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: reason = "watchdog"; break;
    case ESP_RST_EXT: reason = "external"; break;
    case ESP_RST_DEEPSLEEP: reason = "deepsleep"; break;
    default: reason = "other"; break;
  }
}

const char *chip() {
  return ESP.getChipModel();
}

#endif

const char *reset_reason() {
  return reason;
}

}  // namespace board
