# -*- coding: utf-8 -*-
"""Pruebas de la consola en vivo, de 'estado' y del archivo de conexión de Midgard."""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bifrost import consola
from bifrost.admin import main as admin_main
from bifrost.seguridad import generate_self_signed


class FakeTerminal(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


class ConsoleTests(unittest.TestCase):
    def test_visible_length_and_cut_ignore_escape_sequences(self) -> None:
        texto = "\x1b[1mBif\x1b[0mröst"
        self.assertEqual(consola._visible(texto), 7)
        self.assertEqual(consola._visible(consola._recortar(texto, 4)), 4)
        self.assertEqual(consola.duracion(3725), "01:02:05")
        self.assertEqual(consola.duracion(90061), "1 d 01:01:01")

    def test_status_bar_reserves_rows_draws_and_restores_the_terminal(self) -> None:
        salida = FakeTerminal()
        estado = {"running": True, "mode": "local", "tcp_port": 8765, "audio_port": 5004,
                  "asgards": ["aula-1"], "users": ["ana"], "sessions": [{}], "started": time.time() - 65}
        barra = consola.BarraEstado(salida, lambda: estado)
        barra.iniciar()
        barra.dibujar()
        barra.detener()
        texto = salida.getvalue()
        self.assertIn("\x1b[?25l", texto)                       # cursor oculto mientras corre
        self.assertIn("en ejecución", texto)                   # título de la terminal
        self.assertIn("BIFRÖST EN EJECUCIÓN", texto)
        self.assertIn("Asgard 1", texto)
        self.assertIn("activo 00:01:0", texto)
        self.assertTrue(texto.rstrip().endswith("\x1b[?25h\x1b[0 q"))  # cursor restaurado al final
        self.assertIn("\x1b[r", texto)                          # zona de desplazamiento liberada
        # En una terminal angosta se quitan primero los datos menos importantes.
        angosta = barra._linea(estado, 60)
        self.assertEqual(consola._visible(angosta), 60)
        self.assertIn("Asgard 1", angosta)
        self.assertNotIn("Ctrl+C", angosta)

    def test_redirected_output_is_not_styled(self) -> None:
        self.assertFalse(consola.soporta_estilo(io.StringIO()))
        texto = consola.resumen([("Modo", "LOCAL")], "Bifröst 1", "● en ejecución", estilo=False)
        self.assertNotIn("\x1b", texto)
        self.assertIn("Modo", texto)

    def test_estado_reports_running_and_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "estado.json"
            salida = io.StringIO()
            with redirect_stdout(salida):
                self.assertEqual(consola.mostrar_estado(ruta), 3)
            self.assertIn("no está en ejecución", salida.getvalue())
            ruta.write_text(json.dumps({"running": True, "pid": os.getpid(), "updated": time.time(),
                                        "started": time.time() - 10, "mode": "local", "tcp_port": 8765,
                                        "audio_port": 5004, "asgards": ["aula-1"], "users": [],
                                        "sessions": [], "version": "1"}), encoding="utf-8")
            salida = io.StringIO()
            with redirect_stdout(salida):
                self.assertEqual(consola.mostrar_estado(ruta), 0)
            self.assertIn("en ejecución", salida.getvalue())
            self.assertIn("aula-1", salida.getvalue())
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            datos["updated"] = time.time() - 60
            ruta.write_text(json.dumps(datos), encoding="utf-8")
            self.assertFalse(consola.leer_estado(ruta)["running"])


class ClientFileTests(unittest.TestCase):
    def test_client_file_pins_self_signed_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            datos = Path(tmp)
            (datos / "tls").mkdir()
            huella = generate_self_signed(datos / "tls" / "bifrost.crt", datos / "tls" / "bifrost.key", ["ejemplo.com"])
            salida = datos / "servidor.json"
            with redirect_stdout(io.StringIO()):
                codigo = admin_main(["cliente", "--datos", str(datos), "--servidor", "bifrost.ejemplo.com:9000",
                                     "--tls", "--nombre", "Escuela", "--salida", str(salida)])
            self.assertEqual(codigo, 0)
            archivo = json.loads(salida.read_text(encoding="utf-8"))
            self.assertEqual((archivo["servidor"], archivo["puerto"], archivo["tls"], archivo["nombre"]),
                             ("bifrost.ejemplo.com", 9000, True, "Escuela"))
            self.assertEqual(archivo["huella"].replace(":", "").lower(), huella)
            texto = io.StringIO()
            with redirect_stdout(texto):
                admin_main(["cliente", "--datos", str(datos), "--servidor", "bifrost.ejemplo.com", "--tls",
                            "--sin-huella"])
            self.assertNotIn("huella", json.loads(texto.getvalue()))


if __name__ == "__main__":
    unittest.main()
