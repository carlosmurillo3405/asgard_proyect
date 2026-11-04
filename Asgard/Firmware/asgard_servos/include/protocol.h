// Órdenes de texto que Asgard envía por el puerto serie (protocolo 2).
// La referencia completa está en Asgard/Firmware/README.md.
#pragma once

#include <Arduino.h>

namespace protocol {

// Anuncia «ASGARD-SERVOS ready … reset=<motivo>» por el puerto.
void begin(Stream &port);

// Lee y ejecuta las órdenes que llegaron, y revisa el perro guardián.
void serve();

}  // namespace protocol
