# -*- coding: utf-8 -*-
"""List of Asgards (page 3 of the «UI-Asgard» template).

* **Default view**: only the user's Asgards; pick one and enter.
* **Advanced view**: also the «Bifröst server» section to type the address by
  hand, search the local network, use TLS and pin the fingerprint.
"""

from __future__ import annotations

from typing import Any

from .. import theme
from .. import widgets as ui
from ..i18n import tr
from ..protocol import DEFAULT_PORT, STATUS_AVAILABLE, STATUS_BUSY, STATUS_OFFLINE, normalize_fingerprint
from ..qt import QtCore, QtGui, QtWidgets, Signal
from ..settings import VIEW_ADVANCED, VIEW_DEFAULT
from .header import Header

Qt = QtCore.Qt


def status_info(status: str) -> tuple[str, str]:
    """Text and dot color of an Asgard's status."""
    info = {
        STATUS_AVAILABLE: (tr("Available"), theme.SUCCESS),
        STATUS_BUSY: (tr("In a session"), theme.WARNING),
        STATUS_OFFLINE: (tr("Offline"), theme.TEXT_DIM),
    }
    return info.get(status, (status, theme.TEXT_DIM))


def features(item: dict[str, Any]) -> str:
    capabilities = item.get("capabilities") or {}
    parts = []
    if capabilities.get("ai"):
        parts.append(tr("AI tracking"))
    if capabilities.get("pan_tilt"):
        parts.append(tr("Moving camera (simulated)") if capabilities.get("pan_tilt_simulated") else tr("Moving camera"))
    if capabilities.get("actuator"):
        parts.append(tr("Hand"))
    video = capabilities.get("video") or {}
    if video.get("width"):
        parts.append(f"{video['width']}×{video['height']}")
    return " · ".join(parts)


class AsgardModel(QtCore.QAbstractTableModel):
    KEYS = ("name", "location", "status", "features", "id")

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []
        self.titles = (tr("Name"), tr("Location"), tr("Status"), tr("Features"), tr("Identifier"))

    def set_items(self, items: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802 - API de Qt
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802 - API de Qt
        return len(self.KEYS)

    def item(self, row: int) -> dict[str, Any] | None:
        return self.items[row] if 0 <= row < len(self.items) else None

    def row_of(self, identifier: str) -> int:
        return next((i for i, item in enumerate(self.items) if item.get("id") == identifier), -1)

    def data(self, index: QtCore.QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self.items[index.row()]
        key = self.KEYS[index.column()]
        status = item.get("status", STATUS_OFFLINE)
        if role == Qt.ItemDataRole.DisplayRole:
            if key == "status":
                return status_info(status)[0]
            if key == "features":
                return features(item)
            return str(item.get(key, "") or "")
        if role == Qt.ItemDataRole.ForegroundRole:
            if status == STATUS_OFFLINE:
                return QtGui.QBrush(QtGui.QColor(theme.TEXT_DIM))
            return QtGui.QBrush(QtGui.QColor(theme.TEXT if key == "name" else theme.TEXT_SOFT))
        if role == Qt.ItemDataRole.ToolTipRole:
            if status == STATUS_BUSY:
                return tr("This Asgard is in a call.")
            if status == STATUS_OFFLINE:
                return tr("This Asgard is not connected to Bifröst.")
            return tr("Double-click to enter.")
        if role == Qt.ItemDataRole.UserRole:
            return item
        return None

    def headerData(self, section: int, orientation: Any, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.titles[section]
        return None


class StatusDelegate(QtWidgets.QStyledItemDelegate):
    """«Status» column: colored dot and text."""

    def paint(self, painter: QtGui.QPainter, option: Any, index: QtCore.QModelIndex) -> None:
        item = index.data(Qt.ItemDataRole.UserRole) or {}
        text, dot_color = status_info(item.get("status", STATUS_OFFLINE))
        view = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(view, index)
        view.text = ""
        style = view.widget.style() if view.widget is not None else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.ControlElement.CE_ItemViewItem, view, painter, view.widget)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = QtCore.QRectF(option.rect)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(dot_color))
        painter.drawEllipse(QtCore.QPointF(rect.left() + 16, rect.center().y()), 3.5, 3.5)
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        offline = item.get("status") == STATUS_OFFLINE
        painter.setPen(QtGui.QColor(theme.TEXT if selected else (theme.TEXT_DIM if offline else theme.TEXT_SOFT)))
        painter.setFont(option.font)
        painter.drawText(rect.adjusted(28, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.restore()


class AsgardTable(QtWidgets.QTableView):
    enter = Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._advanced = False
        self.table_model = AsgardModel()
        self.setModel(self.table_model)
        self.setItemDelegateForColumn(2, StatusDelegate(self))
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.setFont(theme.font(13))
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(44)
        header = self.horizontalHeader()
        header.setFont(theme.font(12, "semibold"))
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setHighlightSections(False)
        header.setFixedHeight(38)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setMinimumHeight(220)
        self.doubleClicked.connect(lambda index: self._enter_row(index.row()))
        self.empty = ui.label("", 13, role="soft", wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setParent(self.viewport())
        self.empty.hide()

    def _enter_row(self, row: int) -> None:
        item = self.table_model.item(row)
        if item is not None and item.get("status") != STATUS_OFFLINE:
            self.enter.emit(str(item.get("id")))

    def selected(self) -> dict[str, Any] | None:
        rows = self.selectionModel().selectedRows()
        return self.table_model.item(rows[0].row()) if rows else None

    def set_items(self, items: list[dict[str, Any]], preferred: str = "") -> None:
        previous = self.selected()
        key = (previous or {}).get("id") or preferred
        self.table_model.set_items(items)
        row = self.table_model.row_of(key) if key else -1
        if row < 0:
            row = next((i for i, item in enumerate(items) if item.get("status") == STATUS_AVAILABLE), -1)
        if row >= 0:
            self.selectRow(row)

    def set_empty(self, text: str) -> None:
        self.empty.setText(text)
        self.empty.setVisible(bool(text) and self.table_model.rowCount() == 0)
        self._place_empty()

    def _place_empty(self) -> None:
        self.empty.setGeometry(24, 24, max(10, self.viewport().width() - 48), max(10, self.viewport().height() - 48))

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.selected()
            if item is not None:
                self._enter_row(self.table_model.row_of(str(item.get("id"))))
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_empty()
        self._fit_columns()

    def set_advanced(self, advanced: bool) -> None:
        self._advanced = advanced
        self._fit_columns()

    def _fit_columns(self) -> None:
        width = self.width()
        self.setColumnHidden(1, width < 520)
        self.setColumnHidden(3, not self._advanced or width < 700)
        self.setColumnHidden(4, not self._advanced or width < 900)


class ServerSection(QtWidgets.QWidget):
    """The template's «Bifröst server» (only in the advanced view)."""

    connect_requested = Signal(str, int, bool, str)
    search_requested = Signal()
    automatic_requested = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(14)
        column.addWidget(ui.label(tr("Bifröst server"), 14, "semibold"))
        self.card = ui.Card(margin=16, spacing=0)
        column.addWidget(self.card)
        self.grid = QtWidgets.QGridLayout()
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(8)
        self.card.body.addLayout(self.grid)

        self.address_label = ui.label(tr("Address (IP or domain)"), 12, role="soft")
        self.port_label = ui.label(tr("Port"), 12, role="soft")
        self.address = ui.field(mono=True)
        self.address.setMinimumWidth(180)
        self.port = ui.field(mono=True)
        self.port.setFixedWidth(80)
        self.port.setValidator(QtGui.QIntValidator(1, 65535, self))
        self.tls = QtWidgets.QCheckBox(tr("Secure connection (TLS)"))
        self.search_button = ui.button(tr("Search the local network"))
        self.search_button.setMinimumWidth(168)
        self.connect_button = ui.button(tr("Connect"), "primary")
        self.connect_button.setMinimumWidth(108)
        self.address.returnPressed.connect(self._connect)
        self.port.returnPressed.connect(self._connect)
        self.connect_button.clicked.connect(self._connect)
        self.search_button.clicked.connect(self.search_requested.emit)

        self.card.body.addSpacing(12)
        self.card.body.addWidget(ui.label(
            tr("Server TLS fingerprint (optional; 'main.py fingerprint' shows it on Bifröst)"), 12, role="soft"))
        self.card.body.addSpacing(8)
        self.fingerprint = ui.field(mono=True)
        self.fingerprint.setStyleSheet("min-height: 26px; font-size: 12px;")
        self.card.body.addWidget(self.fingerprint)
        self.card.body.addSpacing(14)
        status_row = QtWidgets.QHBoxLayout()
        status_row.setSpacing(16)
        self.status = ui.Indicator(tr("Not connected."), theme.TEXT_DIM, 12)
        status_row.addWidget(self.status, 1)
        self.auto_button = ui.button(tr("Use the automatic server"), "link")
        self.auto_button.setToolTip(tr("Goes back to server.json or to the local network search"))
        self.auto_button.clicked.connect(self.automatic_requested.emit)
        status_row.addWidget(self.auto_button)
        self.card.body.addLayout(status_row)
        self._compact: bool | None = None
        self._arrange(False)

    def _arrange(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        while self.grid.count():
            self.grid.takeAt(0)
        if compact:
            self.grid.addWidget(self.address_label, 0, 0, 1, 4)
            self.grid.addWidget(self.address, 1, 0, 1, 4)
            self.grid.addWidget(self.port_label, 2, 0, 1, 4)
            self.grid.addWidget(self.port, 3, 0)
            self.grid.addWidget(self.tls, 3, 1, 1, 3)
            self.grid.addWidget(self.search_button, 4, 0, 1, 2)
            self.grid.addWidget(self.connect_button, 4, 2, 1, 2)
            for column in range(5):
                self.grid.setColumnStretch(column, 1 if column in (1, 2, 3) else 0)
        else:
            self.grid.addWidget(self.address_label, 0, 0)
            self.grid.addWidget(self.port_label, 0, 1)
            self.grid.addWidget(self.address, 1, 0)
            self.grid.addWidget(self.port, 1, 1)
            self.grid.addWidget(self.tls, 1, 2)
            self.grid.addWidget(self.search_button, 1, 3)
            self.grid.addWidget(self.connect_button, 1, 4)
            for column in range(5):
                self.grid.setColumnStretch(column, 1 if column == 0 else 0)
            self.grid.setColumnMinimumWidth(2, 0)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._arrange(self.width() < 900)

    def set_values(self, host: str, port: int, tls: bool, fingerprint: str) -> None:
        self.address.setText(host)
        self.port.setText(str(port or DEFAULT_PORT))
        self.tls.setChecked(tls)
        self.fingerprint.setText(fingerprint)

    def set_status(self, text: str, dot_color: str, pulse: bool = False) -> None:
        self.status.set(text, dot_color, pulse)

    def set_manual(self, manual: bool) -> None:
        self.auto_button.setVisible(manual)

    def _error(self, field: QtWidgets.QLineEdit, message: str) -> None:
        field.setProperty("error", True)
        ui.refresh_style(field)
        ui.shake(field)
        self.set_status(message, theme.ERROR)
        QtCore.QTimer.singleShot(2500, lambda: (field.setProperty("error", False), ui.refresh_style(field)))

    def _connect(self) -> None:
        host = self.address.text().strip()
        if not host:
            self._error(self.address, tr("Enter Bifröst's IP or domain."))
            return
        try:
            port = int(self.port.text() or DEFAULT_PORT)
        except ValueError:
            port = 0
        if not 1 <= port <= 65535:
            self._error(self.port, tr("The port must be a number between 1 and 65535."))
            return
        fingerprint = self.fingerprint.text().strip()
        if fingerprint:
            try:
                fingerprint = normalize_fingerprint(fingerprint)
            except ValueError as error:
                self._error(self.fingerprint, str(error))
                return
        self.connect_requested.emit(host, port, self.tls.isChecked(), fingerprint)


class LobbyPage(QtWidgets.QWidget):
    enter = Signal(str)
    refresh = Signal()
    profile_requested = Signal()
    view_changed = Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = Header(tr("Asgard System"))
        self.header.profile_requested.connect(self.profile_requested.emit)
        self.header.view_changed.connect(self.view_changed.emit)
        root.addWidget(self.header)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QtWidgets.QWidget()
        self.column = QtWidgets.QVBoxLayout(content)
        self.column.setContentsMargins(24, 12, 24, 24)
        self.column.setSpacing(0)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.server = ServerSection()
        self.column.addWidget(self.server)
        self.server_space = QtWidgets.QSpacerItem(0, 28)
        self.column.addItem(self.server_space)

        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(ui.label("Asgard", 14, "semibold"))
        heading.addStretch(1)
        self.summary = ui.label("", 12, role="soft")
        heading.addWidget(self.summary)
        self.column.addLayout(heading)
        self.column.addSpacing(14)
        self.card = ui.Card(margin=16, spacing=16)
        self.column.addWidget(self.card, 1)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        self.hint = ui.label(tr("Select an available Asgard."), 13, role="soft", wrap=True)
        row.addWidget(self.hint, 1)
        self.refresh_button = ui.button(tr("Refresh"), icon_name="refresh-cw")
        self.refresh_button.setMinimumWidth(140)
        self.refresh_button.clicked.connect(self._refresh)
        row.addWidget(self.refresh_button)
        self.enter_button = ui.button(tr("Enter Asgard"), "primary", icon_name="arrow-right")
        self.enter_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.enter_button.setMinimumWidth(160)
        self.enter_button.clicked.connect(self._enter_selected)
        row.addWidget(self.enter_button)
        self.card.body.addLayout(row)
        self.table = AsgardTable()
        self.table.enter.connect(self.enter.emit)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_button())
        self.card.body.addWidget(self.table, 1)
        self.connection = ui.Indicator("", theme.TEXT_DIM, 12)
        self.card.body.addWidget(self.connection)
        self._advanced = False
        self._loaded = False
        self._update_button()
        self.table.set_empty(tr("Loading the Asgards…"))

    # ------------------------------------------------------------------ #
    def _refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        QtCore.QTimer.singleShot(900, lambda: self.refresh_button.setEnabled(True))
        self.refresh.emit()

    def _enter_selected(self) -> None:
        item = self.table.selected()
        if item is not None:
            self.enter.emit(str(item.get("id")))

    def _update_button(self) -> None:
        item = self.table.selected()
        enabled = item is not None and item.get("status") != STATUS_OFFLINE
        self.enter_button.setEnabled(enabled)
        if item is None:
            self.enter_button.setToolTip(tr("Select an Asgard from the list."))
        elif item.get("status") == STATUS_OFFLINE:
            self.enter_button.setToolTip(tr("That Asgard is not connected right now."))
        else:
            self.enter_button.setToolTip(tr("Enter «{name}»", name=item.get("name", item.get("id"))))

    def set_asgards(self, items: list[dict[str, Any]], preferred: str = "") -> None:
        self._loaded = True
        self.table.set_items(items, preferred)
        available = sum(1 for item in items if item.get("status") == STATUS_AVAILABLE)
        if items:
            self.summary.setText(tr("{assigned} assigned · {available} available", assigned=len(items), available=available))
        else:
            self.summary.setText("")
        self.table.set_empty("" if items else tr("Your user has no Asgards assigned yet.\n"
                                                 "Ask the Bifröst administrator to give you access."))
        if items and not available:
            self.hint.setText(tr("No Asgard is available right now; the list updates by itself."))
        else:
            self.hint.setText(tr("Select an available Asgard."))
        self._update_button()

    def set_connection(self, text: str, dot_color: str, pulse: bool = False) -> None:
        self.connection.set(text, dot_color, pulse)
        self.server.set_status(text, dot_color, pulse)

    def set_view(self, advanced: bool) -> None:
        self._advanced = advanced
        self.header.set_view(VIEW_ADVANCED if advanced else VIEW_DEFAULT)
        self.server.setVisible(advanced)
        self.server_space.changeSize(0, 28 if advanced else 0)
        self.connection.setVisible(not advanced)
        self.table.set_advanced(advanced)
        self.column.invalidate()

    def brand_target(self, target: QtWidgets.QWidget) -> dict[str, QtCore.QRectF]:
        """Where the brand of the sign-in transition ends (``target`` coordinates)."""
        def rect(widget: QtWidgets.QWidget) -> QtCore.QRectF:
            if not widget.isVisible():
                return QtCore.QRectF()
            origin = widget.mapTo(target, QtCore.QPoint(0, 0))
            return QtCore.QRectF(origin.x(), origin.y(), widget.width(), widget.height())

        h = self.header
        return {"logo": rect(h.logo), "title": rect(h.title), "subtitle": rect(h.subtitle)}


class OpeningLayer(ui.ModalLayer):
    """«Connecting to Room 1…» while Bifröst opens the call."""

    def __init__(self, host: QtWidgets.QWidget, name: str) -> None:
        super().__init__(host, 400, close_on_outside_click=False)
        body = self.card.body
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(14)
        self.spinner = ui.Spinner(22, theme.TEXT, 2.5)
        row.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignTop)
        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(6)
        texts.addWidget(ui.label(tr("Connecting to «{name}»", name=name), 17, "semibold", wrap=True))
        self.detail = ui.AnimatedDots(tr("Checking the Asgard and preparing the call"))
        self.detail.setFont(theme.font(12))
        self.detail.setProperty("role", "soft")
        texts.addWidget(self.detail)
        row.addLayout(texts, 1)
        body.addLayout(row)
        self.open()
