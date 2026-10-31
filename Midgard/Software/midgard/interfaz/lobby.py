# -*- coding: utf-8 -*-
"""Listado de Asgard (página 3 de la plantilla «UI-Asgard»).

* **Vista predeterminada**: solo los Asgard del usuario; elegir uno y entrar.
* **Vista avanzada**: además, la sección «Servidor Bifröst» para escribir la
  dirección a mano, buscar en la red local, usar TLS y fijar la huella.
"""

from __future__ import annotations

from typing import Any

from .. import componentes as ui
from .. import tema
from ..ajustes import VIEW_ADVANCED, VIEW_DEFAULT
from ..protocolo import DEFAULT_PORT, STATUS_AVAILABLE, STATUS_BUSY, STATUS_OFFLINE, normalize_fingerprint
from ..qt import QtCore, QtGui, QtWidgets, Signal
from .cabecera import Cabecera

Qt = QtCore.Qt

ESTADOS = {
    STATUS_AVAILABLE: ("Disponible", tema.EXITO),
    STATUS_BUSY: ("En sesión", tema.AVISO),
    STATUS_OFFLINE: ("Desconectado", tema.TEXTO_TENUE),
}


def funciones(item: dict[str, Any]) -> str:
    capacidades = item.get("capabilities") or {}
    partes = []
    if capacidades.get("ai"):
        partes.append("Seguimiento con IA")
    if capacidades.get("pan_tilt"):
        partes.append("Cámara móvil" + (" (simulada)" if capacidades.get("pan_tilt_simulated") else ""))
    if capacidades.get("actuator"):
        partes.append("Mano")
    video = capacidades.get("video") or {}
    if video.get("width"):
        partes.append(f"{video['width']}×{video['height']}")
    return " · ".join(partes)


class ModeloAsgard(QtCore.QAbstractTableModel):
    COLUMNAS = (("name", "Nombre"), ("location", "Ubicación"), ("status", "Estado"),
                ("features", "Funciones"), ("id", "Identificador"))

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802 - API de Qt
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802 - API de Qt
        return len(self.COLUMNAS)

    def item(self, fila: int) -> dict[str, Any] | None:
        return self.items[fila] if 0 <= fila < len(self.items) else None

    def fila_de(self, identificador: str) -> int:
        return next((i for i, item in enumerate(self.items) if item.get("id") == identificador), -1)

    def data(self, index: QtCore.QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self.items[index.row()]
        clave = self.COLUMNAS[index.column()][0]
        estado = item.get("status", STATUS_OFFLINE)
        if role == Qt.ItemDataRole.DisplayRole:
            if clave == "status":
                return ESTADOS.get(estado, (estado, ""))[0]
            if clave == "features":
                return funciones(item)
            return str(item.get(clave, "") or "")
        if role == Qt.ItemDataRole.ForegroundRole:
            if estado == STATUS_OFFLINE:
                return QtGui.QBrush(QtGui.QColor(tema.TEXTO_TENUE))
            return QtGui.QBrush(QtGui.QColor(tema.TEXTO if clave == "name" else tema.TEXTO_SUAVE))
        if role == Qt.ItemDataRole.ToolTipRole:
            if estado == STATUS_BUSY:
                return "Este Asgard está en una llamada."
            if estado == STATUS_OFFLINE:
                return "Este Asgard no está conectado a Bifröst."
            return "Doble clic para entrar."
        if role == Qt.ItemDataRole.UserRole:
            return item
        return None

    def headerData(self, section: int, orientation: Any, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNAS[section][1]
        return None


class DelegadoEstado(QtWidgets.QStyledItemDelegate):
    """Columna «Estado»: punto de color y texto."""

    def paint(self, pintor: QtGui.QPainter, opcion: Any, index: QtCore.QModelIndex) -> None:
        item = index.data(Qt.ItemDataRole.UserRole) or {}
        texto, color_punto = ESTADOS.get(item.get("status", STATUS_OFFLINE), ("", tema.TEXTO_TENUE))
        vista = QtWidgets.QStyleOptionViewItem(opcion)
        self.initStyleOption(vista, index)
        vista.text = ""
        estilo = vista.widget.style() if vista.widget is not None else QtWidgets.QApplication.style()
        estilo.drawControl(QtWidgets.QStyle.ControlElement.CE_ItemViewItem, vista, pintor, vista.widget)
        pintor.save()
        pintor.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = QtCore.QRectF(opcion.rect)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QtGui.QColor(color_punto))
        pintor.drawEllipse(QtCore.QPointF(rect.left() + 16, rect.center().y()), 3.5, 3.5)
        seleccionado = bool(opcion.state & QtWidgets.QStyle.StateFlag.State_Selected)
        offline = item.get("status") == STATUS_OFFLINE
        pintor.setPen(QtGui.QColor(tema.TEXTO if seleccionado else (tema.TEXTO_TENUE if offline else tema.TEXTO_SUAVE)))
        pintor.setFont(opcion.font)
        pintor.drawText(rect.adjusted(28, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, texto)
        pintor.restore()


class TablaAsgard(QtWidgets.QTableView):
    entrar = Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._avanzada = False
        self.modelo = ModeloAsgard()
        self.setModel(self.modelo)
        self.setItemDelegateForColumn(2, DelegadoEstado(self))
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.setFont(tema.fuente(13))
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(44)
        cabecera = self.horizontalHeader()
        cabecera.setFont(tema.fuente(12, "semi"))
        cabecera.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cabecera.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        cabecera.setHighlightSections(False)
        cabecera.setFixedHeight(38)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setMinimumHeight(220)
        self.doubleClicked.connect(lambda index: self._entrar_fila(index.row()))
        self.vacio = ui.etiqueta("", 13, rol="suave", ajuste=True)
        self.vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vacio.setParent(self.viewport())
        self.vacio.hide()

    def _entrar_fila(self, fila: int) -> None:
        item = self.modelo.item(fila)
        if item is not None and item.get("status") != STATUS_OFFLINE:
            self.entrar.emit(str(item.get("id")))

    def seleccionado(self) -> dict[str, Any] | None:
        filas = self.selectionModel().selectedRows()
        return self.modelo.item(filas[0].row()) if filas else None

    def set_items(self, items: list[dict[str, Any]], preferido: str = "") -> None:
        anterior = self.seleccionado()
        clave = (anterior or {}).get("id") or preferido
        self.modelo.set_items(items)
        fila = self.modelo.fila_de(clave) if clave else -1
        if fila < 0:
            fila = next((i for i, item in enumerate(items) if item.get("status") == STATUS_AVAILABLE), -1)
        if fila >= 0:
            self.selectRow(fila)

    def set_vacio(self, texto: str) -> None:
        self.vacio.setText(texto)
        self.vacio.setVisible(bool(texto) and self.modelo.rowCount() == 0)
        self._colocar_vacio()

    def _colocar_vacio(self) -> None:
        self.vacio.setGeometry(24, 24, max(10, self.viewport().width() - 48), max(10, self.viewport().height() - 48))

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.seleccionado()
            if item is not None:
                self._entrar_fila(self.modelo.fila_de(str(item.get("id"))))
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._colocar_vacio()
        self._ajustar_columnas()

    def set_avanzada(self, avanzada: bool) -> None:
        self._avanzada = avanzada
        self._ajustar_columnas()

    def _ajustar_columnas(self) -> None:
        ancho = self.width()
        self.setColumnHidden(1, ancho < 520)
        self.setColumnHidden(3, not self._avanzada or ancho < 700)
        self.setColumnHidden(4, not self._avanzada or ancho < 900)


class SeccionServidor(QtWidgets.QWidget):
    """«Servidor Bifröst» de la plantilla (solo en la vista avanzada)."""

    conectar = Signal(str, int, bool, str)
    buscar = Signal()
    automatico = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        columna = QtWidgets.QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(14)
        columna.addWidget(ui.etiqueta("Servidor Bifröst", 14, "semi"))
        self.tarjeta = ui.Tarjeta(margen=16, espacio=0)
        columna.addWidget(self.tarjeta)
        self.rejilla = QtWidgets.QGridLayout()
        self.rejilla.setHorizontalSpacing(12)
        self.rejilla.setVerticalSpacing(8)
        self.tarjeta.cuerpo.addLayout(self.rejilla)

        self.etiqueta_direccion = ui.etiqueta("Dirección (IP o dominio)", 12, rol="suave")
        self.etiqueta_puerto = ui.etiqueta("Puerto", 12, rol="suave")
        self.direccion = ui.campo(mono=True)
        self.direccion.setMinimumWidth(180)
        self.puerto = ui.campo(mono=True)
        self.puerto.setFixedWidth(80)
        self.puerto.setValidator(QtGui.QIntValidator(1, 65535, self))
        self.tls = QtWidgets.QCheckBox("Conexión segura (TLS)")
        self.boton_buscar = ui.boton("Buscar en la red local")
        self.boton_buscar.setMinimumWidth(168)
        self.boton_conectar = ui.boton("Conectar", "primario")
        self.boton_conectar.setMinimumWidth(108)
        self.direccion.returnPressed.connect(self._conectar)
        self.puerto.returnPressed.connect(self._conectar)
        self.boton_conectar.clicked.connect(self._conectar)
        self.boton_buscar.clicked.connect(self.buscar.emit)

        self.tarjeta.cuerpo.addSpacing(12)
        self.tarjeta.cuerpo.addWidget(ui.etiqueta(
            "Huella TLS del servidor (opcional; la muestra 'main.py huella' en Bifröst)", 12, rol="suave"))
        self.tarjeta.cuerpo.addSpacing(8)
        self.huella = ui.campo(mono=True)
        self.huella.setStyleSheet("min-height: 26px; font-size: 12px;")
        self.tarjeta.cuerpo.addWidget(self.huella)
        self.tarjeta.cuerpo.addSpacing(14)
        fila_estado = QtWidgets.QHBoxLayout()
        fila_estado.setSpacing(16)
        self.estado = ui.Indicador("Sin conectar.", tema.TEXTO_TENUE, 12)
        fila_estado.addWidget(self.estado, 1)
        self.boton_auto = ui.boton("Usar el servidor automático", "enlace")
        self.boton_auto.setToolTip("Vuelve a servidor.json o a la búsqueda en la red local")
        self.boton_auto.clicked.connect(self.automatico.emit)
        fila_estado.addWidget(self.boton_auto)
        self.tarjeta.cuerpo.addLayout(fila_estado)
        self._compacta: bool | None = None
        self._ordenar(False)

    def _ordenar(self, compacta: bool) -> None:
        if compacta == self._compacta:
            return
        self._compacta = compacta
        while self.rejilla.count():
            self.rejilla.takeAt(0)
        if compacta:
            self.rejilla.addWidget(self.etiqueta_direccion, 0, 0, 1, 4)
            self.rejilla.addWidget(self.direccion, 1, 0, 1, 4)
            self.rejilla.addWidget(self.etiqueta_puerto, 2, 0, 1, 4)
            self.rejilla.addWidget(self.puerto, 3, 0)
            self.rejilla.addWidget(self.tls, 3, 1, 1, 3)
            self.rejilla.addWidget(self.boton_buscar, 4, 0, 1, 2)
            self.rejilla.addWidget(self.boton_conectar, 4, 2, 1, 2)
            for columna in range(5):
                self.rejilla.setColumnStretch(columna, 1 if columna in (1, 2, 3) else 0)
        else:
            self.rejilla.addWidget(self.etiqueta_direccion, 0, 0)
            self.rejilla.addWidget(self.etiqueta_puerto, 0, 1)
            self.rejilla.addWidget(self.direccion, 1, 0)
            self.rejilla.addWidget(self.puerto, 1, 1)
            self.rejilla.addWidget(self.tls, 1, 2)
            self.rejilla.addWidget(self.boton_buscar, 1, 3)
            self.rejilla.addWidget(self.boton_conectar, 1, 4)
            for columna in range(5):
                self.rejilla.setColumnStretch(columna, 1 if columna == 0 else 0)
            self.rejilla.setColumnMinimumWidth(2, 0)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._ordenar(self.width() < 900)

    def set_valores(self, host: str, puerto: int, tls: bool, huella: str) -> None:
        self.direccion.setText(host)
        self.puerto.setText(str(puerto or DEFAULT_PORT))
        self.tls.setChecked(tls)
        self.huella.setText(huella)

    def set_estado(self, texto: str, color_punto: str, pulso: bool = False) -> None:
        self.estado.set(texto, color_punto, pulso)

    def set_manual(self, manual: bool) -> None:
        self.boton_auto.setVisible(manual)

    def _error(self, campo: QtWidgets.QLineEdit, mensaje: str) -> None:
        campo.setProperty("error", True)
        ui.refrescar_estilo(campo)
        ui.sacudir(campo)
        self.set_estado(mensaje, tema.ERROR)
        QtCore.QTimer.singleShot(2500, lambda: (campo.setProperty("error", False), ui.refrescar_estilo(campo)))

    def _conectar(self) -> None:
        host = self.direccion.text().strip()
        if not host:
            self._error(self.direccion, "Escribe la IP o el dominio de Bifröst.")
            return
        try:
            puerto = int(self.puerto.text() or DEFAULT_PORT)
        except ValueError:
            puerto = 0
        if not 1 <= puerto <= 65535:
            self._error(self.puerto, "El puerto debe ser un número entre 1 y 65535.")
            return
        huella = self.huella.text().strip()
        if huella:
            try:
                huella = normalize_fingerprint(huella)
            except ValueError as error:
                self._error(self.huella, str(error))
                return
        self.conectar.emit(host, puerto, self.tls.isChecked(), huella)


class PaginaLobby(QtWidgets.QWidget):
    entrar = Signal(str)
    actualizar = Signal()
    perfil = Signal()
    vista_cambiada = Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        raiz = QtWidgets.QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        self.cabecera = Cabecera("Sistema Asgard")
        self.cabecera.perfil.connect(self.perfil.emit)
        self.cabecera.vista_cambiada.connect(self.vista_cambiada.emit)
        raiz.addWidget(self.cabecera)

        desplazable = QtWidgets.QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        contenido = QtWidgets.QWidget()
        self.columna = QtWidgets.QVBoxLayout(contenido)
        self.columna.setContentsMargins(24, 12, 24, 24)
        self.columna.setSpacing(0)
        desplazable.setWidget(contenido)
        raiz.addWidget(desplazable, 1)

        self.servidor = SeccionServidor()
        self.columna.addWidget(self.servidor)
        self.espacio_servidor = QtWidgets.QSpacerItem(0, 28)
        self.columna.addItem(self.espacio_servidor)

        encabezado = QtWidgets.QHBoxLayout()
        encabezado.addWidget(ui.etiqueta("Asgard", 14, "semi"))
        encabezado.addStretch(1)
        self.resumen = ui.etiqueta("", 12, rol="suave")
        encabezado.addWidget(self.resumen)
        self.columna.addLayout(encabezado)
        self.columna.addSpacing(14)
        self.tarjeta = ui.Tarjeta(margen=16, espacio=16)
        self.columna.addWidget(self.tarjeta, 1)
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(12)
        self.indicacion = ui.etiqueta("Selecciona un Asgard disponible.", 13, rol="suave", ajuste=True)
        fila.addWidget(self.indicacion, 1)
        self.boton_actualizar = ui.boton("Actualizar", icono_nombre="refresh-cw")
        self.boton_actualizar.setMinimumWidth(140)
        self.boton_actualizar.clicked.connect(self._actualizar)
        fila.addWidget(self.boton_actualizar)
        self.boton_entrar = ui.boton("Entrar al Asgard", "primario", icono_nombre="arrow-right")
        self.boton_entrar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.boton_entrar.setMinimumWidth(160)
        self.boton_entrar.clicked.connect(self._entrar_seleccionado)
        fila.addWidget(self.boton_entrar)
        self.tarjeta.cuerpo.addLayout(fila)
        self.tabla = TablaAsgard()
        self.tabla.entrar.connect(self.entrar.emit)
        self.tabla.selectionModel().selectionChanged.connect(lambda *_: self._actualizar_boton())
        self.tarjeta.cuerpo.addWidget(self.tabla, 1)
        self.conexion = ui.Indicador("", tema.TEXTO_TENUE, 12)
        self.tarjeta.cuerpo.addWidget(self.conexion)
        self._avanzada = False
        self._cargado = False
        self._actualizar_boton()
        self.tabla.set_vacio("Cargando los Asgard…")

    # ------------------------------------------------------------------ #
    def _actualizar(self) -> None:
        self.boton_actualizar.setEnabled(False)
        QtCore.QTimer.singleShot(900, lambda: self.boton_actualizar.setEnabled(True))
        self.actualizar.emit()

    def _entrar_seleccionado(self) -> None:
        item = self.tabla.seleccionado()
        if item is not None:
            self.entrar.emit(str(item.get("id")))

    def _actualizar_boton(self) -> None:
        item = self.tabla.seleccionado()
        habilitado = item is not None and item.get("status") != STATUS_OFFLINE
        self.boton_entrar.setEnabled(habilitado)
        if item is None:
            self.boton_entrar.setToolTip("Selecciona un Asgard de la lista.")
        elif item.get("status") == STATUS_OFFLINE:
            self.boton_entrar.setToolTip("Ese Asgard no está conectado en este momento.")
        else:
            self.boton_entrar.setToolTip(f"Entrar a «{item.get('name', item.get('id'))}»")

    def set_asgards(self, items: list[dict[str, Any]], preferido: str = "") -> None:
        self._cargado = True
        self.tabla.set_items(items, preferido)
        disponibles = sum(1 for item in items if item.get("status") == STATUS_AVAILABLE)
        if items:
            self.resumen.setText(f"{len(items)} asignados · {disponibles} disponibles")
        else:
            self.resumen.setText("")
        self.tabla.set_vacio("" if items else "Tu usuario aún no tiene Asgard asignados.\n"
                                                  "Pide al administrador de Bifröst que te dé acceso.")
        if items and not disponibles:
            self.indicacion.setText("Ningún Asgard está disponible ahora; la lista se actualiza sola.")
        else:
            self.indicacion.setText("Selecciona un Asgard disponible.")
        self._actualizar_boton()

    def set_conexion(self, texto: str, color_punto: str, pulso: bool = False) -> None:
        self.conexion.set(texto, color_punto, pulso)
        self.servidor.set_estado(texto, color_punto, pulso)

    def set_vista(self, avanzada: bool) -> None:
        self._avanzada = avanzada
        self.cabecera.set_vista(VIEW_ADVANCED if avanzada else VIEW_DEFAULT)
        self.servidor.setVisible(avanzada)
        self.espacio_servidor.changeSize(0, 28 if avanzada else 0)
        self.conexion.setVisible(not avanzada)
        self.tabla.set_avanzada(avanzada)
        self.columna.invalidate()

    def destino_marca(self, destino: QtWidgets.QWidget) -> dict[str, QtCore.QRectF]:
        """Dónde termina la marca de la transición de acceso (coordenadas de ``destino``)."""
        def rect(widget: QtWidgets.QWidget) -> QtCore.QRectF:
            if not widget.isVisible():
                return QtCore.QRectF()
            origen = widget.mapTo(destino, QtCore.QPoint(0, 0))
            return QtCore.QRectF(origen.x(), origen.y(), widget.width(), widget.height())

        c = self.cabecera
        return {"logo": rect(c.logo), "titulo": rect(c.titulo), "subtitulo": rect(c.subtitulo)}


class CapaAbriendo(ui.CapaModal):
    """«Conectando con Aula 1…» mientras Bifröst abre la llamada."""

    def __init__(self, anfitrion: QtWidgets.QWidget, nombre: str) -> None:
        super().__init__(anfitrion, 400, cerrar_al_pulsar_fuera=False)
        cuerpo = self.tarjeta.cuerpo
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(14)
        self.spinner = ui.Spinner(22, tema.TEXTO, 2.5)
        fila.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignTop)
        textos = QtWidgets.QVBoxLayout()
        textos.setSpacing(6)
        textos.addWidget(ui.etiqueta(f"Conectando con «{nombre}»", 17, "semi", ajuste=True))
        self.detalle = ui.Puntos("Comprobando el Asgard y preparando la llamada")
        self.detalle.setFont(tema.fuente(12))
        self.detalle.setProperty("rol", "suave")
        textos.addWidget(self.detalle)
        fila.addLayout(textos, 1)
        cuerpo.addLayout(fila)
        self.abrir()
