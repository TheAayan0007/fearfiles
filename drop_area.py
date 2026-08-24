"""FEAR - shared drag-and-drop file selector used by all three tabs."""

import os

from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import QPainter, QPen, QColor, QBrush
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QSizePolicy, QWidget
)

from theme import C, cut_rect_path, display_font, body_font, HUDButton


class _UploadGlyph(QWidget):
    """Small hand-drawn upload icon (arrow into a tray) so the drop zone
    reads instantly rather than relying on text alone."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 30)
        self._color = QColor(C.DIM)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def sizeHint(self):
        return QSize(30, 30)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self._color, 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        w, h = self.width(), self.height()
        cx = w / 2
        # arrow shaft + head
        p.drawLine(cx, h * 0.12, cx, h * 0.62)
        p.drawLine(cx, h * 0.12, cx - 7, h * 0.34)
        p.drawLine(cx, h * 0.12, cx + 7, h * 0.34)
        # tray
        p.drawLine(w * 0.16, h * 0.78, w * 0.16, h * 0.92)
        p.drawLine(w * 0.84, h * 0.78, w * 0.84, h * 0.92)
        p.drawLine(w * 0.16, h * 0.92, w * 0.84, h * 0.92)
        p.end()


class DropArea(QFrame):
    fileDropped = Signal(str)

    def __init__(self, hint_text="Drag & drop a file here, or click Browse"):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._filename = None
        self._dragging = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(2)
        layout.addStretch(1)

        self.glyph = _UploadGlyph()
        glyph_row = QHBoxLayout()
        glyph_row.addStretch()
        glyph_row.addWidget(self.glyph)
        glyph_row.addStretch()
        layout.addLayout(glyph_row)
        layout.addSpacing(4)

        self.title_label = QLabel("DRAG & DROP FILE")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(display_font(13, "Bold", 1.8))
        self.title_label.setStyleSheet(f"color: {C.TEXT_BRIGHT}; background: transparent;")
        layout.addWidget(self.title_label)

        self.hint_label = QLabel(hint_text)
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setFont(body_font(13, "Medium", 0.3))
        self.hint_label.setStyleSheet(f"color: {C.DIM}; background: transparent;")
        layout.addWidget(self.hint_label)

        layout.addSpacing(8)
        self.browse_btn = HUDButton("BROWSE FILES", variant="ghost")
        self.browse_btn.clicked.connect(self.browse)
        browse_row = QHBoxLayout()
        browse_row.addStretch()
        browse_row.addWidget(self.browse_btn)
        browse_row.addStretch()
        layout.addLayout(browse_row)
        layout.addStretch(1)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        cut = 20
        path = cut_rect_path(rect, cut, ("tr", "bl"))

        if self._filename:
            fill = QColor(C.rgba(C.ACCENT, 16))
            pen = QPen(QColor(C.ACCENT), 1.4)
        elif self._dragging:
            fill = QColor(C.rgba(C.ACCENT, 30))
            pen = QPen(QColor(C.ACCENT), 1.8)
        else:
            fill = QColor(C.PANEL)
            pen = QPen(QColor(C.BORDER), 1.2, Qt.DashLine)

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(fill))
        p.drawPath(path)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # corner brackets, inset from the frame edge
        bracket_color = QColor(C.ACCENT if (self._filename or self._dragging) else C.BORDER)
        bpen = QPen(bracket_color, 2)
        bpen.setCapStyle(Qt.FlatCap)
        p.setPen(bpen)
        s, i = 14, 7
        w, h = self.width(), self.height()
        for (ox, oy, dx, dy) in (
            (i, i, 1, 1), (w - i, i, -1, 1), (i, h - i, 1, -1), (w - i, h - i, -1, -1)
        ):
            p.drawLine(ox, oy, ox + s * dx, oy)
            p.drawLine(ox, oy, ox, oy + s * dy)
        p.end()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._dragging = True
            self.update()

    def dragLeaveEvent(self, event):
        self._dragging = False
        self.update()

    def dropEvent(self, event):
        self._dragging = False
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.fileDropped.emit(path)
        self.update()

    def browse(self, _checked=False):
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            self.fileDropped.emit(path)

    def set_filename(self, path):
        self._filename = os.path.basename(path)
        self.glyph.set_color(C.ACCENT)
        self.title_label.setText("FILE READY")
        self.title_label.setStyleSheet(f"color: {C.ACCENT}; background: transparent;")
        self.hint_label.setText(self._filename)
        self.hint_label.setStyleSheet(f"color: {C.TEXT_BRIGHT}; background: transparent;")
        self.update()
