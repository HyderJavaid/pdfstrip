"""StripSafe desktop window (Qt): a sidebar with Process Files, Settings and About, dark or light.

All file work runs in worker processes (see workers.py); the window only receives their results as
queued Qt signals, so the interface never waits on a PDF.
"""

import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QObject, QPointF, QRect, QRectF, QSize, Qt,
                            Signal)
from PySide6.QtGui import (QBrush, QColor, QFontMetrics, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QButtonGroup, QFileDialog,
                               QFrame, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QSlider, QStackedWidget, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget)

from . import __version__, settings as settings_store
from .core import SUPPORTED_EXTENSIONS, Result, expand_paths, human_size, is_supported
from .metadata import MetaReport
from .theme import PALETTES, Palette, blend, qss
from .workers import WorkerPool, inspect_job, process_job

# (label, preset name, description) for the quality slider.
QUALITY_STEPS = [
    ("Strip only", "lossless", "Removes metadata, keeps every pixel"),
    ("High quality", "light", "Gentle compression, looks identical"),
    ("Balanced", "balanced", "Good size savings, minor quality loss"),
    ("Smallest", "strong", "Maximum savings for email"),
]
NAV = [("process", "Process Files"), ("settings", "Settings"), ("about", "About")]
STATUS_COLORS = {"Ready": "muted", "Working": "accent", "Done": "success", "Failed": "danger"}


@dataclass(eq=False)  # compared and hashed by identity
class Item:
    path: Path
    kind: str  # "pdf" or "image"
    size: int
    checked: bool = True
    status: str = "Ready"  # Ready, Working, Done, Failed
    report: Optional[MetaReport] = None
    inspect_error: Optional[str] = None
    thumb: object = None   # PIL image
    result: Optional[Result] = None
    pixmaps: dict = field(default_factory=dict)  # cache of QPixmaps by size


# --------------------------------------------------------------------------- small helpers --
def _label(text="", name=None, wrap=False, align=None):
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    if align:
        label.setAlignment(align)
    return label


def _button(text, variant=None, slot=None, name=None):
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        btn.setProperty("variant", variant)
    if name:
        btn.setObjectName(name)
    if slot:
        btn.clicked.connect(lambda _checked=False: slot())
    return btn


def _card(layout_cls=QVBoxLayout, margins=(18, 16, 18, 16), spacing=8):
    frame = QFrame()
    frame.setObjectName("card")
    layout = layout_cls(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return frame, layout


def _clear(layout):
    while layout.count():
        child = layout.takeAt(0)
        widget = child.widget()
        if widget:
            widget.hide()          # gone from the screen now, not on the next event-loop turn
            widget.setParent(None)
            widget.deleteLater()
        elif child.layout():
            _clear(child.layout())


def _repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def pil_to_pixmap(img, size=None, crop=False) -> QPixmap:
    img = img.convert("RGB")
    if size and crop:
        from PIL import ImageOps
        img = ImageOps.fit(img, (size, size))
    elif size:
        img = img.copy()
        img.thumbnail((size, size))
    qimg = QImage(img.tobytes(), img.width, img.height, img.width * 3, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


def draw_logo(painter: QPainter, rect: QRectF, color: QColor, inner: QColor):
    """A shield with a check mark."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    pts = [(.5, 0), (.92, .15), (.92, .5), (.5, 1), (.08, .5), (.08, .15)]
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF([QPointF(x + px * w, y + py * h) for px, py in pts]))
    painter.setPen(QPen(inner, max(2.0, w / 9), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline(QPolygonF([QPointF(x + .3 * w, y + .5 * h), QPointF(x + .45 * w, y + .64 * h),
                                    QPointF(x + .72 * w, y + .34 * h)]))


def logo_icon(pal: Palette) -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    draw_logo(painter, QRectF(6, 4, 52, 56), QColor(pal.accent), QColor(pal.on_accent))
    painter.end()
    return QIcon(pix)


def draw_check(painter: QPainter, rect: QRectF, checked: bool, pal: Palette):
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if checked:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.accent))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QPen(QColor(pal.on_accent), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        x, y, s = rect.x(), rect.y(), rect.width()
        painter.drawPolyline(QPolygonF([QPointF(x + s * .27, y + s * .52), QPointF(x + s * .43, y + s * .68),
                                        QPointF(x + s * .74, y + s * .33)]))
    else:
        painter.setPen(QPen(QColor(pal.muted), 1.3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(.65, .65, -.65, -.65), 5, 5)


def draw_pill(painter: QPainter, rect: QRect, text: str, color: str, bg: str, font):
    fm = QFontMetrics(font)
    w, h = fm.horizontalAdvance(text) + 18, fm.height() + 8
    box = QRectF(rect.x() + 4, rect.y() + (rect.height() - h) / 2, w, h)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(blend(bg, color, .15)))
    painter.drawRoundedRect(box, h / 2, h / 2)
    painter.setPen(QColor(color))
    painter.setFont(font)
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class CheckBox(QAbstractButton):
    """Matches the queue's check marks (QCheckBox needs image files to be styled)."""

    def __init__(self, pal: Palette):
        super().__init__()
        self.pal = pal
        self.setCheckable(True)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event):
        painter = QPainter(self)
        draw_check(painter, QRectF(1, 1, 18, 18), self.isChecked(), self.pal)


class Logo(QWidget):
    def __init__(self, pal: Palette):
        super().__init__()
        self.pal = pal
        self.setFixedSize(34, 38)

    def paintEvent(self, _event):
        painter = QPainter(self)
        draw_logo(painter, QRectF(2, 2, 30, 34), QColor(self.pal.accent), QColor(self.pal.on_accent))


# --------------------------------------------------------------------------------- queue --
class QueueModel(QAbstractTableModel):
    HEADERS = ["Name", "Type", "Size", "Status", ""]
    ItemRole = Qt.ItemDataRole.UserRole

    def __init__(self):
        super().__init__()
        self.items: List[Item] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.HEADERS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == self.ItemRole:
            return item
        if index.column() == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return item.path.name
            if role == Qt.ItemDataRole.ToolTipRole:
                return str(item.path)
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def add(self, items):
        if items:
            self.beginInsertRows(QModelIndex(), len(self.items), len(self.items) + len(items) - 1)
            self.items.extend(items)
            self.endInsertRows()

    def remove(self, item):
        row = self.items.index(item)
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.items[row]
        self.endRemoveRows()

    def clear(self):
        self.beginResetModel()
        self.items.clear()
        self.endResetModel()

    def touch(self, item):
        """Repaint one row after its item changed."""
        try:
            row = self.items.index(item)
        except ValueError:
            return
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.HEADERS) - 1))

    def touch_all(self):
        if self.items:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.items) - 1, len(self.HEADERS) - 1))


class QueueDelegate(QStyledItemDelegate):
    """Paints the whole row itself: check box, pills, sizes and the remove cross."""

    checkToggled = Signal(object)
    removeClicked = Signal(object)
    ROW_HEIGHT = 46

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def sizeHint(self, option, index):
        return QSize(0, self.ROW_HEIGHT)

    def _check_rect(self, option):
        r = option.rect
        return QRectF(r.x() + 14, r.y() + (r.height() - 18) / 2, 18, 18)

    def paint(self, painter, option, index):
        pal = self.window.pal
        item = index.data(QueueModel.ItemRole)
        selected = self.window.is_selected(item)
        bg = pal.surface2 if selected else pal.surface
        rect = option.rect
        painter.save()
        painter.fillRect(rect, QColor(bg))
        painter.fillRect(QRect(rect.x(), rect.bottom(), rect.width(), 1), QColor(pal.border))
        col = index.column()
        font = option.font
        small = option.font
        small.setPointSizeF(max(8.0, font.pointSizeF() - 1))
        if col == 0:
            draw_check(painter, self._check_rect(option), item.checked, pal)
            painter.setPen(QColor(pal.text))
            painter.setFont(font)
            text_rect = rect.adjusted(44, 0, -8, 0)
            elided = QFontMetrics(font).elidedText(item.path.name, Qt.TextElideMode.ElideMiddle, text_rect.width())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        elif col == 1:
            draw_pill(painter, rect, "PDF" if item.kind == "pdf" else "Image",
                      pal.danger if item.kind == "pdf" else pal.accent, bg, small)
        elif col == 2:
            if item.result and item.result.ok:
                text, color = f"{human_size(item.size)}  →  {human_size(item.result.new_size)}", pal.success
            else:
                text, color = human_size(item.size), pal.muted
            painter.setPen(QColor(color))
            painter.setFont(small)
            painter.drawText(rect.adjusted(4, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        elif col == 3:
            draw_pill(painter, rect, item.status, getattr(pal, STATUS_COLORS[item.status]), bg, small)
        else:
            painter.setPen(QColor(pal.muted))
            painter.setFont(small)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "✕")
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            item = index.data(QueueModel.ItemRole)
            pos = event.position()
            if index.column() == 0 and self._check_rect(option).adjusted(-6, -6, 6, 6).contains(pos):
                self.checkToggled.emit(item)
                return True
            if index.column() == 4:
                self.removeClicked.emit(item)
                return True
        return False


# ------------------------------------------------------------------------------- widgets --
class DropZone(QFrame):
    dropped = Signal(list)

    def __init__(self, add_files, add_folder):
        super().__init__()
        self.setObjectName("dropzone")
        self.setAcceptDrops(True)
        self.setFixedHeight(136)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(_label("Drag & drop files here", "h2", align=Qt.AlignmentFlag.AlignCenter))
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        row.addWidget(_button("+  Add files", "primary", add_files))
        row.addWidget(_button("Add folder", None, add_folder))
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(_label("Supports JPG, PNG, WebP and PDF", "small", align=Qt.AlignmentFlag.AlignCenter))

    def _set_active(self, active):
        self.setProperty("active", active)
        _repolish(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, _event):
        self._set_active(False)

    def dropEvent(self, event):
        self._set_active(False)
        self.dropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()


class QualityControl(QWidget):
    changed = Signal(int)

    def __init__(self, value):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(_label("Compression quality", "small"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(QUALITY_STEPS) - 1)
        self.slider.setPageStep(1)
        self.slider.setFixedWidth(150)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.slider)
        self.caption = _label("", "bold")
        layout.addWidget(self.caption)
        self.set_value(value)
        self.slider.valueChanged.connect(self._moved)

    def _moved(self, value):
        self.caption.setText(QUALITY_STEPS[value][0])
        self.changed.emit(value)

    def set_value(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self.caption.setText(QUALITY_STEPS[value][0])


class OutputControl(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_ = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(_label("Output folder", "small"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.path = _label("", "path")
        self.path.setMinimumWidth(120)
        row.addWidget(self.path, 1)
        row.addWidget(_button("Change", None, window.pick_output))
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        text = self.window_.settings.output_dir or "Next to originals"
        self.path.setToolTip(text)
        self.path.setText(QFontMetrics(self.path.font()).elidedText(text, Qt.TextElideMode.ElideLeft, 140))


class Page(QWidget):
    def __init__(self, title, subtitle):
        super().__init__()
        self.setObjectName("page")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(28, 24, 28, 24)
        self.outer.setSpacing(0)
        self.outer.addWidget(_label(title, "h1"))
        self.outer.addWidget(_label(subtitle, "muted"))


class DetailPanel(QWidget):
    """What private data the selected file holds, a preview, and its size after processing."""

    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.tab = "metadata"
        self.item = None
        self.setFixedWidth(340)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(14)

    def show_item(self, item):
        self.item = item
        self.rebuild()

    def rebuild(self):
        _clear(self.layout_)
        win, item = self.window_, self.item
        card, lay = _card()
        self.layout_.addWidget(card)
        if item is None:
            lay.addWidget(_label("Select a file to see what private data it contains.", "muted", wrap=True))
            self.layout_.addStretch()
            return

        head = QHBoxLayout()
        head.setSpacing(12)
        thumb = QLabel()
        thumb.setFixedSize(56, 56)
        pix = self._pixmap(item, 56)
        if pix:
            thumb.setPixmap(pix)
        else:
            color = win.pal.danger if item.kind == "pdf" else win.pal.accent
            thumb.setText("PDF" if item.kind == "pdf" else "IMG")
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet(f"background: {blend(win.pal.surface, color, .15)}; color: {color};"
                                f"border-radius: 12px; font-weight: 700;")
        head.addWidget(thumb)
        names = QVBoxLayout()
        names.setSpacing(2)
        name = _label("", "bold")
        name.setText(QFontMetrics(name.font()).elidedText(item.path.name, Qt.TextElideMode.ElideMiddle, 200))
        name.setToolTip(str(item.path))
        names.addStretch()
        names.addWidget(name)
        names.addWidget(_label(human_size(item.size), "small"))
        names.addStretch()
        head.addLayout(names, 1)
        lay.addLayout(head)

        tabs = QHBoxLayout()
        tabs.setSpacing(18)
        group = QButtonGroup(self)
        for key, text in (("metadata", "Metadata found"), ("preview", "Preview")):
            btn = _button(text, name="tab")
            btn.setCheckable(True)
            btn.setChecked(self.tab == key)
            btn.clicked.connect(lambda _c=False, k=key: self._set_tab(k))
            group.addButton(btn)
            tabs.addWidget(btn)
        tabs.addStretch()
        lay.addLayout(tabs)
        divider = QFrame()
        divider.setObjectName("divider")
        lay.addWidget(divider)
        (self._preview if self.tab == "preview" else self._metadata)(lay, item)

        size_card, slay = _card(margins=(18, 14, 18, 16), spacing=10)
        self.layout_.addWidget(size_card)
        slay.addWidget(_label("Size after processing", "bold"))
        boxes = QHBoxLayout()
        boxes.setSpacing(8)
        boxes.addWidget(self._size_box("Original", human_size(item.size), None, None), 1)
        boxes.addWidget(_label("→", "muted"))
        if item.result and item.result.ok:
            saved = item.result.saved_percent
            boxes.addWidget(self._size_box("After", human_size(item.result.new_size), "success",
                                           f"{saved:.0f}% smaller" if saved > 0 else "no size change"), 1)
        else:
            boxes.addWidget(self._size_box("After", "—", None, QUALITY_STEPS[win.settings.quality][0]), 1)
        slay.addLayout(boxes)
        if item.status == "Failed" and item.result is not None and item.result.error:
            slay.addWidget(_label(item.result.error, "danger", wrap=True))
        self.layout_.addStretch()

    def _pixmap(self, item, size):
        if item.thumb is None:
            return None
        if size not in item.pixmaps:
            item.pixmaps[size] = pil_to_pixmap(item.thumb, size, crop=size <= 64)
        return item.pixmaps[size]

    def _size_box(self, title, value, color, caption):
        box = QFrame()
        box.setObjectName("inset")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(0)
        lay.addWidget(_label(title, "small"))
        lay.addWidget(_label(value, color or "value"))
        if color:
            lay.itemAt(1).widget().setStyleSheet("font-size: 12pt; font-weight: 600;")  # "success" colour at value size
        lay.addWidget(_label(caption or " ", "small"))
        return box

    def _set_tab(self, key):
        self.tab = key
        self.rebuild()

    def _metadata(self, lay, item):
        if item.report is None:
            if item.inspect_error:
                lay.addWidget(_label(item.inspect_error, "danger", wrap=True))
            else:
                lay.addWidget(_label("Reading metadata…", "muted"))
            return
        report = item.report
        if report.note:
            lay.addWidget(_label(report.note, "danger", wrap=True))
            return
        if report.clean:
            lay.addWidget(_label("No identifying metadata found.", "success"))
            return
        for label, value in report.fields:
            row = QHBoxLayout()
            row.addWidget(_label(label, "muted"))
            row.addStretch()
            val = _label(align=Qt.AlignmentFlag.AlignRight)
            val.setText(QFontMetrics(val.font()).elidedText(value, Qt.TextElideMode.ElideRight, 190))
            val.setToolTip(value)
            row.addWidget(val)
            lay.addLayout(row)
        if report.other_count:
            row = QHBoxLayout()
            row.addWidget(_label("Other (EXIF, IPTC, XMP)", "muted"))
            row.addStretch()
            row.addWidget(_label(f"{report.other_count} more"))
            lay.addLayout(row)
        pal, done = self.window_.pal, item.status == "Done"
        color = pal.success if done else pal.danger
        tag = _label("Removed after processing." if done else "This metadata will be removed.")
        tag.setStyleSheet(f"background: {blend(pal.surface, color, .14)}; color: {color}; border-radius: 6px;"
                          f"padding: 5px 10px; font-size: 9pt;")
        row = QHBoxLayout()
        row.addWidget(tag)
        row.addStretch()
        lay.addSpacing(6)
        lay.addLayout(row)

    def _preview(self, lay, item):
        pix = self._pixmap(item, 270)
        if pix:
            label = QLabel()
            label.setPixmap(pix)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(label)
        else:
            text = "PDF previews are not shown." if item.kind == "pdf" else "Preview unavailable."
            lay.addWidget(_label(text, "muted", align=Qt.AlignmentFlag.AlignCenter))


class Bridge(QObject):
    """Carries results from worker callbacks (any thread) to the window as queued signals."""

    meta = Signal(object, object, object, object)  # item, report, thumbnail, error
    started = Signal(object)
    done = Signal(object, object)
    finished = Signal()


# ------------------------------------------------------------------------------ main window --
class MainWindow(QMainWindow):
    def __init__(self, settings=None, pool=None):
        super().__init__()
        self.settings = settings or settings_store.load()
        self.pal = PALETTES[self.settings.theme]
        self.pool = pool or WorkerPool()
        self.working = False
        self.summary = ""
        self.selected: Optional[Item] = None
        self.model = QueueModel()
        self.bridge = Bridge()
        self.bridge.meta.connect(self._on_meta)
        self.bridge.started.connect(self._on_started)
        self.bridge.done.connect(self._on_done)
        self.bridge.finished.connect(self._on_finished)
        self.setWindowTitle("StripSafe")
        self.resize(1240, 740)
        self.setMinimumSize(1180, 640)
        self.setAcceptDrops(True)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_process())
        self.stack.addWidget(self._build_settings())
        self.stack.addWidget(self._build_about())
        outer.addWidget(self.stack, 1)
        self.apply_theme()
        self._update_chrome()

    # ----- sidebar
    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(230)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 24, 0, 18)
        lay.setSpacing(2)
        brand = QHBoxLayout()
        brand.setContentsMargins(20, 0, 20, 18)
        brand.setSpacing(10)
        self.logo = Logo(self.pal)
        brand.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(_label("StripSafe", "logo"))
        names.addWidget(_label("Clean files. Keep privacy.", "small"))
        brand.addLayout(names)
        lay.addLayout(brand)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = {}
        for index, (key, text) in enumerate(NAV):
            btn = _button(text, name="nav")
            btn.setCheckable(True)
            btn.setChecked(index == 0)
            btn.clicked.connect(lambda _c=False, i=index: self.stack.setCurrentIndex(i))
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
            lay.addWidget(btn)
        lay.addStretch()
        note = QFrame()
        note.setObjectName("localNote")
        nlay = QVBoxLayout(note)
        nlay.setContentsMargins(14, 12, 14, 12)
        nlay.setSpacing(2)
        nlay.addWidget(_label("100% local", "success"))
        nlay.itemAt(0).widget().setStyleSheet("font-weight: 600;")
        nlay.addWidget(_label("Your files never leave this computer. StripSafe makes no network connections.",
                              "small", wrap=True))
        wrap = QVBoxLayout()
        wrap.setContentsMargins(16, 0, 16, 0)
        wrap.addWidget(note)
        lay.addLayout(wrap)
        return side

    # ----- process page
    def _build_process(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QHBoxLayout(page)
        lay.setContentsMargins(28, 24, 24, 24)
        lay.setSpacing(24)
        main = QVBoxLayout()
        main.setSpacing(0)
        main.addWidget(_label("Clean your files", "h1"))
        main.addWidget(_label("Remove metadata and shrink images and PDFs, right here on this computer.", "muted"))
        main.addSpacing(18)
        self.dropzone = DropZone(self.add_files, self.add_folder)
        self.dropzone.dropped.connect(self.add_paths)
        main.addWidget(self.dropzone)
        main.addSpacing(14)

        queue, qlay = _card(margins=(0, 0, 0, 0), spacing=0)
        head = QHBoxLayout()
        head.setContentsMargins(18, 14, 14, 8)
        head.setSpacing(14)
        self.queue_title = _label("", "h2")
        head.addWidget(self.queue_title)
        self.summary_label = _label("", "success")
        head.addWidget(self.summary_label)
        head.addStretch()
        head.addWidget(_button("Clear all", "ghost", self.clear))
        qlay.addLayout(head)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.delegate = QueueDelegate(self)
        self.delegate.checkToggled.connect(self._toggle_item)
        self.delegate.removeClicked.connect(self.remove_item)
        self.table.setItemDelegate(self.delegate)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(QueueDelegate.ROW_HEIGHT)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 84), (2, 170), (3, 100), (4, 40)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        header.setFixedHeight(32)
        self.table.selectionModel().currentRowChanged.connect(self._on_current_row)
        self.select_all = CheckBox(self.pal)
        self.select_all.setChecked(True)
        self.select_all.clicked.connect(self._toggle_all)
        self.select_all.setParent(header)
        self.select_all.move(14, 6)
        qlay.addWidget(self.table, 1)
        self.empty = _label("No files yet. Add or drop some above.", "muted", align=Qt.AlignmentFlag.AlignCenter)
        self.empty.setParent(self.table.viewport())
        self.table.viewport().installEventFilter(self)
        main.addWidget(queue, 1)
        main.addSpacing(14)

        bar, blay = _card(QHBoxLayout, margins=(16, 14, 16, 14), spacing=18)
        self.quality = QualityControl(self.settings.quality)
        self.quality.changed.connect(self.set_quality)
        blay.addWidget(self.quality)
        self.output = OutputControl(self)
        blay.addWidget(self.output, 1)
        self.go = _button("Process files", "primary", self.start)
        self.go.setMinimumSize(140, 44)
        blay.addWidget(self.go)
        main.addWidget(bar)
        lay.addLayout(main, 1)

        self.detail = DetailPanel(self)
        lay.addWidget(self.detail)
        self.detail.rebuild()
        return page

    def eventFilter(self, obj, event):
        try:
            if obj is self.table.viewport() and event.type() == QEvent.Type.Resize:
                self._place_empty()
        except RuntimeError:  # the table is already gone while the app shuts down
            pass
        return super().eventFilter(obj, event)

    def _place_empty(self):
        vp = self.table.viewport()
        self.empty.setGeometry(0, 0, vp.width(), min(vp.height(), 120))

    # ----- settings / about pages
    def _setting_row(self, lay, title, subtitle, control):
        card, clay = _card(QHBoxLayout, margins=(22, 16, 22, 16), spacing=16)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(_label(title, "bold"))
        texts.addWidget(_label(subtitle, "small"))
        clay.addLayout(texts, 1)
        clay.setAlignment(texts, Qt.AlignmentFlag.AlignVCenter)
        clay.addWidget(control)
        lay.addSpacing(14)
        lay.addWidget(card)

    def _build_settings(self):
        page = Page("Settings", "Your choices are saved on this computer only.")
        lay = page.outer
        seg = QWidget()
        slay = QHBoxLayout(seg)
        slay.setContentsMargins(0, 0, 0, 0)
        slay.setSpacing(8)
        self.theme_group = QButtonGroup(self)
        self.theme_buttons = {}
        for key, text in (("dark", "Dark"), ("light", "Light")):
            btn = _button(text, "seg")
            btn.setCheckable(True)
            btn.setChecked(self.settings.theme == key)
            btn.setMinimumWidth(92)
            btn.clicked.connect(lambda _c=False, k=key: self.set_theme(k))
            self.theme_group.addButton(btn)
            self.theme_buttons[key] = btn
            slay.addWidget(btn)
        lay.addSpacing(6)
        self._setting_row(lay, "Appearance", "Switch between the dark and light theme.", seg)
        self.quality2 = QualityControl(self.settings.quality)
        self.quality2.changed.connect(self.set_quality)
        self._setting_row(lay, "Default compression", "Used for every batch you process.", self.quality2)
        box = QWidget()
        blay = QVBoxLayout(box)
        blay.setContentsMargins(0, 0, 0, 0)
        self.output2 = OutputControl(self)
        blay.addWidget(self.output2)
        reset = _button("Save next to originals", "ghost", self.reset_output)
        blay.addWidget(reset, 0, Qt.AlignmentFlag.AlignRight)
        box.setFixedWidth(330)
        self._setting_row(lay, "Output folder", "Cleaned copies are saved here. Originals are never changed.", box)
        lay.addStretch()
        return page

    def _build_about(self):
        page = Page("About StripSafe", f"Version {__version__}")
        card, clay = _card(margins=(22, 8, 22, 18), spacing=2)
        blocks = [
            ("What it does", "Removes hidden personal data from PDFs and images (author names, GPS location, camera "
                             "details, timestamps, editing history) and compresses them so they are easy to email."),
            ("Private by design", "Everything happens on this computer. StripSafe never connects to the internet and "
                                  "never uploads your files. Cleaned copies are saved as new files, so your originals "
                                  "are never changed."),
            ("Supported files", "PDF, JPG, PNG and WebP."),
            ("Good to know", "Text and pictures you can see on the page are not altered. Password-protected PDFs need "
                             "their password removed first."),
            ("License", "Free software under the GNU GPL v3."),
        ]
        for title, text in blocks:
            clay.addSpacing(10)
            clay.addWidget(_label(title, "bold"))
            clay.addWidget(_label(text, "muted", wrap=True))
        page.outer.addSpacing(20)
        page.outer.addWidget(card)
        page.outer.addStretch()
        return page

    # ----- theme / settings
    def apply_theme(self):
        self.pal = PALETTES[self.settings.theme]
        QApplication.instance().setStyleSheet(qss(self.pal))
        self.setWindowIcon(logo_icon(self.pal))
        self.logo.pal = self.pal
        self.logo.update()
        self.select_all.pal = self.pal
        self.select_all.update()
        self.table.viewport().update()
        self.detail.rebuild()
        for key, btn in self.theme_buttons.items():
            btn.setChecked(key == self.settings.theme)

    def set_theme(self, theme):
        if theme != self.settings.theme:
            self.settings.theme = theme
            settings_store.save(self.settings)
            self.apply_theme()

    def set_quality(self, idx):
        self.settings.quality = idx
        settings_store.save(self.settings)
        self.quality.set_value(idx)
        self.quality2.set_value(idx)
        self.detail.rebuild()

    def pick_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Save cleaned files in")
        if folder:
            self.settings.output_dir = folder
            settings_store.save(self.settings)
            self.output.refresh()
            self.output2.refresh()

    def reset_output(self):
        self.settings.output_dir = None
        settings_store.save(self.settings)
        self.output.refresh()
        self.output2.refresh()

    # ----- queue actions
    def is_selected(self, item):
        return item is self.selected

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def add_files(self):
        types = "PDFs and images (" + " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS)) + ");;All files (*)"
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files", "", types)
        if paths:
            self.add_paths(paths)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder")
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths):
        self.stack.setCurrentIndex(0)
        self.nav_buttons["process"].setChecked(True)
        known = {i.path for i in self.model.items}
        new = []
        for path in expand_paths(paths):
            path = Path(path)
            if path in known or not is_supported(path) or not path.is_file():
                continue
            known.add(path)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            new.append(Item(path, "pdf" if path.suffix.lower() == ".pdf" else "image", size))
        if not new:
            return
        self.summary = ""
        self.model.add(new)
        if self.selected is None:
            self.table.selectRow(self.model.items.index(new[0]))
        self._update_chrome()
        for item in new:
            self._submit_inspect(item)

    def _submit_inspect(self, item):
        def done(fut):
            try:
                report, thumb = fut.result()
                self.bridge.meta.emit(item, report, thumb, None)
            except BaseException as exc:  # includes a worker that died or was cancelled
                self.bridge.meta.emit(item, None, None, str(exc) or exc.__class__.__name__)

        self.pool.submit(inspect_job, item.path).add_done_callback(done)

    def _toggle_item(self, item):
        item.checked = not item.checked
        self.model.touch(item)
        self._update_chrome()

    def _toggle_all(self):
        value = self.select_all.isChecked()
        for item in self.model.items:
            item.checked = value
        self.model.touch_all()
        self._update_chrome()

    def remove_item(self, item):
        if self.working and item.status == "Working":
            return
        if item is self.selected:
            self.selected = None
        self.model.remove(item)
        self._sync_selection()
        self._update_chrome()

    def clear(self):
        if self.working:
            return
        self.model.clear()
        self.selected = None
        self.summary = ""
        self.detail.show_item(None)
        self._update_chrome()

    def _on_current_row(self, current, _previous):
        old = self.selected
        item = self.model.items[current.row()] if current.isValid() else None
        self.selected = item
        for it in (old, item):
            if it is not None:
                self.model.touch(it)
        self.detail.show_item(item)

    def _sync_selection(self):
        if self.selected is None and self.model.items:
            self.table.selectRow(0)
        elif not self.model.items:
            self.detail.show_item(None)

    def _update_chrome(self):
        n = len(self.model.items)
        self.queue_title.setText(f"Files queue ({n})")
        self.summary_label.setText(self.summary)
        self.empty.setVisible(n == 0)
        self._place_empty()
        self.select_all.setChecked(n > 0 and all(i.checked for i in self.model.items))
        todo = self._todo()
        self.go.setText(f"Process files ({len(todo)})" if todo else "Process files")
        self.go.setEnabled(bool(todo) and not self.working)

    def _todo(self):
        return [i for i in self.model.items if i.checked and i.status in ("Ready", "Failed")]

    # ----- results from workers
    def _on_meta(self, item, report, thumb, error):
        item.report, item.thumb, item.inspect_error = report, thumb, error
        item.pixmaps.clear()
        if item is self.selected:
            self.detail.rebuild()

    def _on_started(self, item):
        item.status = "Working"
        self.model.touch(item)

    def _on_done(self, item, result):
        item.result, item.status = result, "Done" if result.ok else "Failed"
        self.model.touch(item)
        if item is self.selected:
            self.detail.rebuild()

    def _on_finished(self):
        self.working = False
        items = self.model.items
        done = [i for i in items if i.result and i.result.ok]
        failed = [i for i in items if i.status == "Failed"]
        saved = sum(i.result.original_size - i.result.new_size for i in done)
        parts = []
        if done:
            parts.append(f"{len(done)} cleaned" + (f", saved {human_size(saved)}" if saved > 0 else ""))
        if failed:
            parts.append(f"{len(failed)} failed")
        self.summary = " · ".join(parts)
        self._update_chrome()

    # ----- processing
    def start(self):
        todo = self._todo()
        if self.working or not todo:
            return
        preset_name = QUALITY_STEPS[self.settings.quality][1]
        out = self.settings.output_dir
        if out and not Path(out).exists():
            try:
                Path(out).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(self, "StripSafe", f"Can't use that output folder:\n{exc}")
                return
        self.working = True
        self.summary = ""
        for item in todo:
            item.status, item.result = "Ready", None
            self.model.touch(item)
        self._update_chrome()
        threading.Thread(target=self._dispatch, args=(todo, preset_name, out), daemon=True).start()

    def _dispatch(self, items, preset_name, out):
        """Feed the worker pool, keeping only as many jobs in flight as there are workers,
        so a row says "Working" only while a process is really on it."""
        slots = threading.Semaphore(self.pool.max_workers)
        futures = []
        for item in items:
            slots.acquire()
            self.bridge.started.emit(item)
            fut = self.pool.submit(process_job, item.path, preset_name, out)
            futures.append(fut)

            def done(f, item=item):
                try:
                    result = f.result()
                except BaseException as exc:  # worker crashed, e.g. ran out of memory on a huge PDF
                    result = Result(item.path, None, item.size, 0,
                                    f"Processing stopped unexpectedly ({exc.__class__.__name__})")
                self.bridge.done.emit(item, result)
                slots.release()

            fut.add_done_callback(done)
        for fut in futures:
            try:
                fut.exception()  # wait for completion
            except BaseException:
                pass
        self.bridge.finished.emit()

    def closeEvent(self, event):
        self.pool.shutdown()
        super().closeEvent(event)


def main(argv=None) -> int:
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("StripSafe")
    window = MainWindow()
    window.show()
    if argv:
        window.add_paths(argv)
    return app.exec()
