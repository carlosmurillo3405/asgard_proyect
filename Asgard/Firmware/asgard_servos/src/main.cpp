/*
  Asgard · controlador de servos en un ESP32
  ============================================

  La Raspberry Pi envía por USB el ancho de pulso de cada servo y el ESP32 genera
  la señal con su PWM por hardware (LEDC). Los pulsos son estables aunque la
  Raspberry esté ocupada con la IA y el video, que es lo que hace temblar o
  «volverse locos» a los servos cuando el PWM se genera por software.

    include/configuracion.h   pines, versión y límites
    src/servos.cpp            señal PWM de cada canal (0 = pan, 1 = tilt, 2 = mano)
    src/protocolo.cpp         órdenes por el puerto serie y perro guardián

  Arranca sin pulsos (los servos no saltan al encender), suelta los servos si
  la Raspberry deja de hablar y avisa si se reinició por caída de voltaje.
  Instrucciones y protocolo: Asgard/Firmware/README.md.
*/

#include <Arduino.h>

#include "configuracion.h"
#include "protocolo.h"
#include "servos.h"

void setup() {
  Serial.begin(BAUDIOS);
  servos::iniciar();
  protocolo::iniciar(Serial);
}

void loop() {
  protocolo::atender();
  delay(1);
}
