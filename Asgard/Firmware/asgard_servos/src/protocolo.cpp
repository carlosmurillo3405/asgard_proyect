#include "protocolo.h"

#include <esp_system.h>

#include "configuracion.h"
#include "servos.h"

namespace protocolo {

static Stream *puerto = nullptr;

static uint32_t espera_ms = 0;        // perro guardián; 0 = apagado (al arrancar)
static uint32_t ultimo_dato_ms = 0;
static bool soltado_por_espera = false;

static char linea[LINEA_MAX];
static size_t largo = 0;
static bool desbordada = false;

static const char *motivo_reinicio() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "encendido";
    case ESP_RST_BROWNOUT: return "voltaje";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "fallo";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return "vigilante";
    case ESP_RST_EXT: return "externo";
    case ESP_RST_DEEPSLEEP: return "suspension";
    default: return "otro";
  }
}

static void identificar(bool al_arrancar) {
  puerto->printf("ASGARD-SERVOS %sproto=%d canales=%u fw=%s chip=%s",
                 al_arrancar ? "lista " : "", PROTOCOLO, CANALES, ASGARD_FIRMWARE, ESP.getChipModel());
  if (al_arrancar) {
    puerto->printf(" reinicio=%s\n", motivo_reinicio());
  } else {
    puerto->printf(" espera=%lu\n", (unsigned long)espera_ms);
  }
}

static void mostrar_estado() {
  puerto->printf("estado espera=%lu", (unsigned long)espera_ms);
  for (uint8_t canal = 0; canal < CANALES; canal++) {
    puerto->printf(" %u=%u", canal, servos::pulso(canal));
  }
  puerto->print('\n');
}

static void mostrar_ayuda() {
  puerto->print("# ?  identificacion\n");
  puerto->print("# S canal us [canal us ...]  pulso en microsegundos, 0 = soltar (ej.: S 0 1500)\n");
  puerto->print("# X  suelta todos los servos\n");
  puerto->print("# T ms  suelta todo si no llegan datos en ese tiempo (0 = apagado)\n");
  puerto->print("# E  estado de los canales\n");
  for (uint8_t canal = 0; canal < CANALES; canal++) {
    puerto->printf("# canal %u = GPIO %u\n", canal, PINES[canal]);
  }
}

static bool leer_numero(const char *texto, long &valor) {
  if (texto == nullptr) {
    return false;
  }
  char *fin = nullptr;
  valor = strtol(texto, &fin, 10);
  return fin != texto && *fin == '\0';
}

// S canal us [canal us ...]: se valida toda la orden antes de mover algún servo.
static void ordenar_pulsos() {
  long canales[CANALES * 2];
  long pulsos[CANALES * 2];
  size_t cantidad = 0;
  const char *texto;
  while ((texto = strtok(nullptr, " \t")) != nullptr) {
    long canal, us;
    if (!leer_numero(texto, canal) || !leer_numero(strtok(nullptr, " \t"), us)) {
      puerto->print("err S espera pares: canal microsegundos\n");
      return;
    }
    if (canal < 0 || canal >= CANALES) {
      puerto->printf("err canal %ld no existe (hay %u)\n", canal, CANALES);
      return;
    }
    if (us < 0 || us > PULSO_LIMITE_US) {
      puerto->printf("err pulso %ld fuera de rango\n", us);
      return;
    }
    if (cantidad == CANALES * 2) {
      puerto->print("err S demasiados pares\n");
      return;
    }
    canales[cantidad] = canal;
    pulsos[cantidad] = us;
    cantidad++;
  }
  if (cantidad == 0) {
    puerto->print("err S sin canales\n");
    return;
  }
  for (size_t i = 0; i < cantidad; i++) {
    servos::aplicar((uint8_t)canales[i], (uint16_t)pulsos[i]);
  }
}

static void ordenar_espera() {
  long valor;
  if (!leer_numero(strtok(nullptr, " \t"), valor) || valor < 0 || valor > (long)ESPERA_MAX_MS) {
    puerto->printf("err T espera de 0 a %lu ms\n", (unsigned long)ESPERA_MAX_MS);
    return;
  }
  espera_ms = (uint32_t)valor;
  puerto->printf("ok T %lu\n", (unsigned long)espera_ms);
}

static void procesar(char *texto) {
  const char *orden = strtok(texto, " \t");
  if (orden == nullptr) {
    return;
  }
  if (orden[1] != '\0') {
    puerto->printf("err orden desconocida: %s (H = ayuda)\n", orden);
    return;
  }
  switch (toupper(orden[0])) {
    case '?':
      identificar(false);
      break;
    case 'S':
      ordenar_pulsos();
      break;
    case 'X':
      servos::soltar_todo();
      puerto->print("ok X\n");
      break;
    case 'T':
      ordenar_espera();
      break;
    case 'K':   // mantener vivo: basta con haber recibido la línea
      break;
    case 'E':
      mostrar_estado();
      break;
    case 'H':
      mostrar_ayuda();
      break;
    default:
      puerto->printf("err orden desconocida: %s (H = ayuda)\n", orden);
  }
}

void iniciar(Stream &salida) {
  puerto = &salida;
  ultimo_dato_ms = millis();
  identificar(true);
}

void atender() {
  while (puerto->available() > 0) {
    char c = (char)puerto->read();
    if (c == '\n' || c == '\r') {
      if (desbordada) {
        puerto->print("err linea demasiado larga\n");
      } else if (largo > 0) {
        linea[largo] = '\0';
        ultimo_dato_ms = millis();
        soltado_por_espera = false;
        procesar(linea);
      }
      largo = 0;
      desbordada = false;
    } else if (largo < LINEA_MAX - 1) {
      linea[largo++] = c;
    } else {
      desbordada = true;
    }
  }
  if (espera_ms != 0 && !soltado_por_espera && millis() - ultimo_dato_ms > espera_ms) {
    servos::soltar_todo();
    soltado_por_espera = true;
    puerto->print("aviso sin datos de la Raspberry: servos sueltos\n");
  }
}

}  // namespace protocolo
