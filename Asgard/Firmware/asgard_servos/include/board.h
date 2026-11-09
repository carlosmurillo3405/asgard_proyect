// Datos de la placa que se informan a Asgard: modelo del chip y motivo del último reinicio.
#pragma once

#include <Arduino.h>

namespace board {

// Lee el motivo del reinicio. Se llama una vez, al principio de setup().
void begin();

// «ATmega328P», «ESP32-D0WD»…
const char *chip();

// poweron, external, software, brownout, panic, watchdog, deepsleep, other o unknown.
// En el Arduino suele ser «unknown»: su cargador (Optiboot) borra el registro del motivo.
const char *reset_reason();

}  // namespace board
