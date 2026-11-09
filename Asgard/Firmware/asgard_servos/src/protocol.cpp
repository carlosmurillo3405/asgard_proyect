#include "protocol.h"

#include "board.h"
#include "config.h"
#include "servos.h"

// Los textos van con F(): en el Arduino Uno quedan en la memoria flash y no
// ocupan los 2 KB de RAM. Solo se usa print() (el Arduino no tiene printf).

namespace protocol {

static Stream *port = nullptr;

static uint32_t timeout_ms = 0;        // perro guardián; 0 = apagado (al arrancar)
static uint32_t last_data_ms = 0;
static bool released_by_timeout = false;

static char line[MAX_LINE];
static size_t length = 0;
static bool overflow = false;

static void identify(bool at_boot) {
  port->print(F("ASGARD-SERVOS "));
  if (at_boot) {
    port->print(F("ready "));
  }
  port->print(F("proto="));
  port->print(PROTOCOL);
  port->print(F(" channels="));
  port->print(CHANNELS);
  port->print(F(" fw=" ASGARD_FIRMWARE " chip="));
  port->print(board::chip());
  if (at_boot) {
    port->print(F(" reset="));
    port->print(board::reset_reason());
  } else {
    port->print(F(" timeout="));
    port->print(timeout_ms);
  }
  port->print('\n');
}

static void show_state() {
  port->print(F("state timeout="));
  port->print(timeout_ms);
  for (uint8_t channel = 0; channel < CHANNELS; channel++) {
    port->print(' ');
    port->print(channel);
    port->print('=');
    port->print(servos::pulse(channel));
  }
  port->print('\n');
}

static void show_help() {
  port->print(F("# ?  identity\n"
                "# S channel us [channel us ...]  pulse in microseconds, 0 = release (e.g. S 0 1500)\n"
                "# X  releases every servo\n"
                "# T ms  releases everything when no data arrives within that time (0 = off)\n"
                "# E  channel state\n"));
  for (uint8_t channel = 0; channel < CHANNELS; channel++) {
    port->print(F("# channel "));
    port->print(channel);
    port->print(F(" = pin "));
    port->print(PINS[channel]);
    port->print('\n');
  }
}

static void error_with(const __FlashStringHelper *text, const char *detail = nullptr) {
  port->print(F("err "));
  port->print(text);
  if (detail != nullptr) {
    port->print(detail);
  }
  port->print('\n');
}

static bool read_number(const char *text, long &value) {
  if (text == nullptr) {
    return false;
  }
  char *end = nullptr;
  value = strtol(text, &end, 10);
  return end != text && *end == '\0';
}

// S canal us [canal us ...]: se valida toda la orden antes de mover algún servo.
static void command_pulses() {
  uint8_t channels[CHANNELS * 2];
  uint16_t pulses[CHANNELS * 2];
  uint8_t count = 0;
  const char *text;
  while ((text = strtok(nullptr, " \t")) != nullptr) {
    long channel, us;
    if (!read_number(text, channel) || !read_number(strtok(nullptr, " \t"), us)) {
      error_with(F("S expects pairs: channel microseconds"));
      return;
    }
    if (channel < 0 || channel >= CHANNELS) {
      error_with(F("channel does not exist: "), text);
      return;
    }
    if (us < 0 || us > PULSE_LIMIT_US) {
      error_with(F("pulse out of range"));
      return;
    }
    if (count == CHANNELS * 2) {
      error_with(F("S too many pairs"));
      return;
    }
    channels[count] = (uint8_t)channel;
    pulses[count] = (uint16_t)us;
    count++;
  }
  if (count == 0) {
    error_with(F("S without channels"));
    return;
  }
  for (uint8_t i = 0; i < count; i++) {
    servos::apply(channels[i], pulses[i]);
  }
}

static void command_timeout() {
  long value;
  if (!read_number(strtok(nullptr, " \t"), value) || value < 0 || value > (long)MAX_TIMEOUT_MS) {
    error_with(F("T timeout from 0 to 60000 ms"));
    return;
  }
  timeout_ms = (uint32_t)value;
  port->print(F("ok T "));
  port->print(timeout_ms);
  port->print('\n');
}

static void process(char *text) {
  const char *command = strtok(text, " \t");
  if (command == nullptr) {
    return;
  }
  if (command[1] != '\0') {
    error_with(F("unknown command (H = help): "), command);
    return;
  }
  switch (toupper(command[0])) {
    case '?':
      identify(false);
      break;
    case 'S':
      command_pulses();
      break;
    case 'X':
      servos::release_all();
      port->print(F("ok X\n"));
      break;
    case 'T':
      command_timeout();
      break;
    case 'K':   // mantener vivo: basta con haber recibido la línea
      break;
    case 'E':
      show_state();
      break;
    case 'H':
      show_help();
      break;
    default:
      error_with(F("unknown command (H = help): "), command);
  }
}

void begin(Stream &output) {
  port = &output;
  last_data_ms = millis();
  identify(true);
}

void serve() {
  while (port->available() > 0) {
    char c = (char)port->read();
    if (c == '\n' || c == '\r') {
      if (overflow) {
        error_with(F("line too long"));
      } else if (length > 0) {
        line[length] = '\0';
        last_data_ms = millis();
        released_by_timeout = false;
        process(line);
      }
      length = 0;
      overflow = false;
    } else if (length < MAX_LINE - 1) {
      line[length++] = c;
    } else {
      overflow = true;
    }
  }
  if (timeout_ms != 0 && !released_by_timeout && millis() - last_data_ms > timeout_ms) {
    servos::release_all();
    released_by_timeout = true;
    port->print(F("warn no data from the Raspberry Pi: servos released\n"));
  }
}

}  // namespace protocol
