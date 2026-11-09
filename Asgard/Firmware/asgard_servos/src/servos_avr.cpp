// PWM por hardware del ATmega328P (Arduino Uno / Nano).
//
// Canales 0 y 1 (pan y tilt): Timer1 en modo 14 (PWM rápido con TOP = ICR1) y
// prescaler 8: un paso cada 0,5 µs y un periodo de 40000 pasos = 20 ms. Las
// salidas OC1A (D9) y OC1B (D10) suben al empezar el periodo y bajan solas al
// llegar al valor de OCR1A/OCR1B: el pulso no depende del programa ni de las
// interrupciones del puerto serie, así que no tiembla.
//
// Canal 2 (mano): Timer2 en PWM rápido de 8 bits con prescaler 1024: un paso
// cada 64 µs y un periodo de 16,4 ms (61 Hz, que los servos aceptan). La
// resolución (unos 6°) basta para una mano que solo sube y baja.
//
// Timer0 no se toca: lo usan millis() y delay().

#if defined(ARDUINO_ARCH_AVR)

#include <avr/io.h>

#include "config.h"
#include "servos.h"

namespace servos {

static uint16_t pulse_us[CHANNELS];   // 0 = suelto

constexpr uint16_t TIMER1_TOP = PERIOD_US * 2 - 1;   // 0,5 µs por paso
constexpr uint16_t TIMER2_STEP_US = 64;              // 16 MHz / 1024

static void connect_output(uint8_t channel, bool on) {
  // COMnx1 = 1: salida no invertida (sube al empezar el periodo, baja en la comparación).
  switch (channel) {
    case 0:
      if (on) TCCR1A |= _BV(COM1A1); else TCCR1A &= ~_BV(COM1A1);
      break;
    case 1:
      if (on) TCCR1A |= _BV(COM1B1); else TCCR1A &= ~_BV(COM1B1);
      break;
    case 2:
      if (on) TCCR2A |= _BV(COM2B1); else TCCR2A &= ~_BV(COM2B1);
      break;
  }
}

void begin() {
  for (uint8_t channel = 0; channel < CHANNELS; channel++) {
    digitalWrite(PINS[channel], LOW);
    pinMode(PINS[channel], OUTPUT);
  }
  // Timer1: modo 14 (WGM13..10 = 1110), prescaler 8 (CS11), salidas desconectadas.
  TCCR1A = _BV(WGM11);
  TCCR1B = _BV(WGM13) | _BV(WGM12) | _BV(CS11);
  ICR1 = TIMER1_TOP;
  TCNT1 = 0;
  // Timer2: PWM rápido de 8 bits (WGM21..20 = 11), prescaler 1024 (CS22..20 = 111).
  TCCR2A = _BV(WGM21) | _BV(WGM20);
  TCCR2B = _BV(CS22) | _BV(CS21) | _BV(CS20);
  for (uint8_t channel = 0; channel < CHANNELS; channel++) {
    apply(channel, 0);
  }
}

void apply(uint8_t channel, uint16_t us) {
  if (channel >= CHANNELS) {
    return;
  }
  if (us != 0) {
    us = constrain(us, MIN_PULSE_US, MAX_PULSE_US);
  }
  pulse_us[channel] = us;
  if (us == 0) {
    // Sin pulsos: la salida queda en bajo y el servo, suelto.
    connect_output(channel, false);
    digitalWrite(PINS[channel], LOW);
    return;
  }
  // En modo PWM los OCR tienen doble búfer: el valor nuevo entra al empezar el
  // periodo siguiente, nunca a mitad de un pulso.
  switch (channel) {
    case 0:
      OCR1A = us * 2 - 1;
      break;
    case 1:
      OCR1B = us * 2 - 1;
      break;
    case 2: {
      uint16_t steps = (us + TIMER2_STEP_US / 2) / TIMER2_STEP_US;
      OCR2B = (uint8_t)(steps - 1);
      break;
    }
  }
  connect_output(channel, true);
}

void release_all() {
  for (uint8_t channel = 0; channel < CHANNELS; channel++) {
    apply(channel, 0);
  }
}

uint16_t pulse(uint8_t channel) {
  return channel < CHANNELS ? pulse_us[channel] : 0;
}

}  // namespace servos

#endif  // ARDUINO_ARCH_AVR
