# -*- coding: utf-8 -*-
"""Pruebas de Bifröst. Ejecuta: python -m unittest discover -s tests -t ."""

import logging

# Los rechazos esperados en las pruebas no deben llenar la salida.
logging.getLogger("bifrost").setLevel(logging.ERROR)
