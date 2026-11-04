#include "protocol.h"

#include <esp_system.h>

#include "config.h"
#include "servos.h"

namespace protocol {

static Stream *port = nullptr;

static uint32_t timeout_ms = 0;        // perro guardián; 0 = apagado (al arrancar)
static uint32_t last_data_ms = 0;
static bool released_by_timeout = false;

static char line[MAX_LINE];
static size_t length = 0;
static bool overflow = false;

static const char *reset_reason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return "watchdog";
    case ESP_RST_EXT: return "external";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    default: return "other";
  }
}

static void identify(bool at_boot) {
  port->printf("ASGARD-SERVOS %sproto=%d channels=%u fw=%s chip=%s",
               at_boot ? "ready " : "", PROTOCOL, CHANNELS, ASGARD_FIRMWARE, ESP.getChipModel());
  if (at_boot) {
    port->printf(" reset=%s\n", reset_reason());
  } else {
    port->printf(" timeout=%lu\n", (unsigned long)timeout_ms);
  }
}

static void show_state() {
  port->printf("state timeout=%lu", (unsigned long)timeout_ms);
  for (uint8_t channel = 0; channel < CHANNELS; channel++) {
    port->printf(" %u=%u", channel, servos::pulse(channel));
  }
  port->print('\n');
}

static void show_help() {
  port->print("# ?  identity\n");
  port->print("# S channel us [channel us ...]  pulse in microseconds, 0 = release (e.g. S 0 1500)\n");
  port->print("# X  releases every servo\n");
  port->print("# T ms  releases everything when no data arrives within that time (0 = off)\n");
  port->print("# E  channel state\n");
  for (uint8_t channel = 0; channel < CHANNELS; channel++) {
    port->printf("# channel %u = GPIO %u\n", channel, PINS[channel]);
  }
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
  long channels[CHANNELS * 2];
  long pulses[CHANNELS * 2];
  size_t count = 0;
  const char *text;
  while ((text = strtok(nullptr, " \t")) != nullptr) {
    long channel, us;
    if (!read_number(text, channel) || !read_number(strtok(nullptr, " \t"), us)) {
      port->print("err S expects pairs: channel microseconds\n");
      return;
    }
    if (channel < 0 || channel >= CHANNELS) {
      port->printf("err channel %ld does not exist (there are %u)\n", channel, CHANNELS);
      return;
    }
    if (us < 0 || us > PULSE_LIMIT_US) {
      port->printf("err pulse %ld out of range\n", us);
      return;
    }
    if (count == CHANNELS * 2) {
      port->print("err S too many pairs\n");
      return;
    }
    channels[count] = channel;
    pulses[count] = us;
    count++;
  }
  if (count == 0) {
    port->print("err S without channels\n");
    return;
  }
  for (size_t i = 0; i < count; i++) {
    servos::apply((uint8_t)channels[i], (uint16_t)pulses[i]);
  }
}

static void command_timeout() {
  long value;
  if (!read_number(strtok(nullptr, " \t"), value) || value < 0 || value > (long)MAX_TIMEOUT_MS) {
    port->printf("err T timeout from 0 to %lu ms\n", (unsigned long)MAX_TIMEOUT_MS);
    return;
  }
  timeout_ms = (uint32_t)value;
  port->printf("ok T %lu\n", (unsigned long)timeout_ms);
}

static void process(char *text) {
  const char *command = strtok(text, " \t");
  if (command == nullptr) {
    return;
  }
  if (command[1] != '\0') {
    port->printf("err unknown command: %s (H = help)\n", command);
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
      port->print("ok X\n");
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
      port->printf("err unknown command: %s (H = help)\n", command);
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
        port->print("err line too long\n");
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
    port->print("warn no data from the Raspberry Pi: servos released\n");
  }
}

}  // namespace protocol
