# -*- coding: utf-8 -*-
"""Interfaz gráfica de Midgard (Qt) con la plantilla «UI-Asgard».

Páginas:

* **Acceso** (``acceso.py``): usuario y contraseña. Al aceptarse, el logotipo
  viaja al centro mientras se prepara todo (``transicion.py``).
* **Asgard** (``lobby.py``): Asgard disponibles para el usuario; en la vista
  avanzada, la conexión con Bifröst se configura a mano.
* **Llamada** (``llamada.py``): video del Asgard, cámara, mano, chat,
  dispositivos y, en la vista de desarrollador, servos y seguimiento.
* **Perfil** (``perfil.py``): foto, contraseña, historial y cerrar sesión.
"""

from .ventana import VentanaMidgard, ejecutar

__all__ = ["VentanaMidgard", "ejecutar"]
