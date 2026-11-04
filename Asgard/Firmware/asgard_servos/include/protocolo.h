// Órdenes de texto que Asgard envía por el puerto serie (protocolo 1).
// La referencia completa está en Asgard/Firmware/README.md.
#pragma once

#include <Arduino.h>

namespace protocolo {

// Anuncia «ASGARD-SERVOS lista … reinicio=<motivo>» por el puerto.
void iniciar(Stream &puerto);

// Lee y ejecuta las órdenes que llegaron, y revisa el perro guardián.
void atender();

}  // namespace protocolo
