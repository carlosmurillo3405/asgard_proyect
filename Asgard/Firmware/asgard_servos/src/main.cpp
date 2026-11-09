/*
  Asgard · controlador de servos (Arduino Uno; también Nano o ESP32)
  ===================================================================

  La Raspberry Pi envía por USB (o por su UART) el ancho de pulso de cada servo
  y la placa genera la señal con su PWM por hardware: los temporizadores del
  ATmega328P en el Arduino, o el LEDC del ESP32. Los pulsos son estables aunque
  la Raspberry esté ocupada con la IA y el video, que es lo que hace temblar o
  «volverse locos» a los servos cuando el PWM se genera por software.

    include/config.h          pines, versión y límites
    src/servos_avr.cpp        señal PWM en el Arduino (Timer1: pan y tilt; Timer2: mano)
    src/servos_esp32.cpp      señal PWM en el ESP32 (LEDC)
    src/board.cpp             modelo del chip y motivo del reinicio
    src/protocol.cpp          órdenes por el puerto serie y perro guardián

  Arranca sin pulsos (los servos no saltan al encender), suelta los servos si
  la Raspberry deja de hablar y se presenta al arrancar para que Asgard sepa
  que se reinició. Instrucciones y protocolo: Asgard/Firmware/README.md.
*/

#include <Arduino.h>

#include "board.h"
#include "config.h"
#include "protocol.h"
#include "servos.h"

void setup() {
  board::begin();
  servos::begin();
  Serial.begin(BAUD_RATE);
  protocol::begin(Serial);
}

void loop() {
  protocol::serve();
#if defined(ARDUINO_ARCH_ESP32)
  delay(1);   // cede la CPU a las demás tareas del ESP32
#endif
}
