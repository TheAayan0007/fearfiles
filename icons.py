"""
FEAR - simple placeholder icons drawn with QPainter, so the app doesn't
depend on any external icon assets. Used as fallback thumbnails for
video/audio/archive/generic library items (video gets replaced with a real
frame grab when that succeeds -- see read_tab.py's _request_video_thumbnail).

Each kind gets its own accent color so the library list reads at a glance
even before you look at the label -- this mapping is reused by library.py
for the little kind tag next to the title.
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPixmap, QPainter, QColor, QBrush, QPen, QPolygonF

from theme import C, cut_rect_path

KIND_COLOR = {
    "video": C.ACCENT,
    "audio": C.ACCENT3,
    "archive": C.SUCCESS,
    "generic": C.DIM,
}


def _base_pixmap(size, accent):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    path = cut_rect_path(rect, size * 0.16, ("tr", "bl"))
    painter.setBrush(QBrush(QColor(C.PANEL_SOLID)))
    painter.setPen(Qt.NoPen)
    painter.drawPath(path)
    pen = QPen(QColor(accent), max(1.2, size * 0.014))
    pen.setCosmetic(False)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    return pixmap, painter


def video_placeholder(size=96):
    accent = KIND_COLOR["video"]
    pixmap, painter = _base_pixmap(size, accent)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(accent)))
    tri = QPolygonF([
        QPointF(size * 0.41, size * 0.30),
        QPointF(size * 0.41, size * 0.70),
        QPointF(size * 0.73, size * 0.50),
    ])
    painter.drawPolygon(tri)
    painter.end()
    return pixmap


def audio_placeholder(size=96):
    accent = KIND_COLOR["audio"]
    pixmap, painter = _base_pixmap(size, accent)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(accent)))
    heights = [0.30, 0.60, 0.85, 0.50, 0.35]
    bar_w = size * 0.08
    gap = size * 0.05
    total_w = len(heights) * bar_w + (len(heights) - 1) * gap
    x = (size - total_w) / 2
    for h in heights:
        bar_h = size * h * 0.56
        y = size * 0.76 - bar_h
        painter.drawRoundedRect(QRectF(x, y, bar_w, bar_h), bar_w * 0.3, bar_w * 0.3)
        x += bar_w + gap
    painter.end()
    return pixmap


def archive_placeholder(size=96):
    accent = KIND_COLOR["archive"]
    pixmap, painter = _base_pixmap(size, accent)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(accent)))
    painter.drawRoundedRect(QRectF(size * 0.24, size * 0.28, size * 0.52, size * 0.46), 3, 3)
    painter.setBrush(QBrush(QColor(C.PANEL_SOLID)))
    tooth_w = size * 0.065
    tooth_h = size * 0.045
    x = size * 0.5 - tooth_w / 2
    y = size * 0.30
    while y < size * 0.70:
        painter.drawRect(QRectF(x, y, tooth_w, tooth_h))
        y += tooth_h * 2
    painter.end()
    return pixmap


def generic_placeholder(size=96):
    accent = KIND_COLOR["generic"]
    pixmap, painter = _base_pixmap(size, accent)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(accent)))
    painter.drawRoundedRect(QRectF(size * 0.30, size * 0.16, size * 0.40, size * 0.68), 3, 3)
    painter.setBrush(QBrush(QColor(C.PANEL_SOLID)))
    for i in range(3):
        y = size * 0.34 + i * size * 0.14
        painter.drawRect(QRectF(size * 0.36, y, size * 0.28, size * 0.045))
    painter.end()
    return pixmap
