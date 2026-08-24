"""
FEAR - the decrypted-file "library" shown in the Read tab: a data model
(LibraryItem) plus the clickable card widgets used to display it as a list.
"""

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QBrush
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy

import icons
from theme import C, cut_rect_path, display_font, body_font

THUMB_SIZE = 72


class LibraryItem:
    """One successfully-decrypted file added to the Read tab's library."""

    _next_id = 1

    def __init__(self, kind, title, temp_path=None, image_bytes=None, archive_ext=None):
        self.id = LibraryItem._next_id
        LibraryItem._next_id += 1
        self.kind = kind  # "video" | "audio" | "image" | "archive" | "generic"
        self.title = title
        self.temp_path = temp_path        # decrypted temp file: video/audio/archive
        self.image_bytes = image_bytes    # decrypted bytes kept in memory: image/generic
        self.archive_ext = archive_ext
        self.thumbnail = None             # QPixmap; filled in immediately for images,
                                           # asynchronously (maybe) for video


class LibraryCard(QFrame):
    """One row in the library list: thumbnail + kind tag + title. Clicking
    anywhere on the row (not just a button) fires `clicked`."""

    clicked = Signal(object)  # emits the LibraryItem

    def __init__(self, item, index_label):
        super().__init__()
        self.item = item
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(THUMB_SIZE + 20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hover = False
        self._accent = QColor(icons.KIND_COLOR.get(item.kind, C.DIM))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 16, 10)
        layout.setSpacing(14)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.thumb_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        text_layout.addStretch()
        self.kind_label = QLabel(index_label.upper())
        self.kind_label.setFont(display_font(9.5, "Bold", 1.8))
        self.kind_label.setStyleSheet(f"color: {self._accent.name()}; background: transparent;")
        self.kind_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.title_label = QLabel(item.title)
        self.title_label.setFont(body_font(16, "SemiBold", 0.2))
        self.title_label.setStyleSheet(f"color: {C.TEXT_BRIGHT}; background: transparent;")
        self.title_label.setWordWrap(True)
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout.addWidget(self.kind_label)
        text_layout.addWidget(self.title_label)
        text_layout.addStretch()
        layout.addLayout(text_layout, 1)

        self.set_thumbnail(item.thumbnail)

    def set_thumbnail(self, pixmap):
        if pixmap is None:
            placeholder_fn = {
                "video": icons.video_placeholder,
                "audio": icons.audio_placeholder,
                "archive": icons.archive_placeholder,
            }.get(self.item.kind, icons.generic_placeholder)
            pixmap = placeholder_fn(THUMB_SIZE)
        else:
            pixmap = pixmap.scaled(THUMB_SIZE, THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb_label.setPixmap(pixmap)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = cut_rect_path(rect, 12, ("tr",))
        fill = QColor(C.PANEL_RAISED if self._hover else C.PANEL)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(fill))
        p.drawPath(path)
        border = self._accent if self._hover else QColor(C.BORDER)
        p.setPen(QPen(border, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        # left accent bar in the kind color
        bar = QRectF(rect.left(), rect.top() + 2, 2.5, rect.height() - 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._accent))
        p.drawRect(bar)
        p.end()
        super().paintEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.item)
        super().mousePressEvent(event)


class LibraryListView(QWidget):
    """Vertical list of LibraryCards. Not scrollable on its own -- the
    whole Read tab (unlock form + this list, together) scrolls as one
    page, see read_tab.py. That way a growing library just makes the page
    taller instead of competing for a fixed-height box with the controls
    above it."""

    itemClicked = Signal(object)

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(8)

        self._counters = {}
        self.empty_hint = QWidget()
        self.empty_hint.setStyleSheet("background: transparent;")
        eh_layout = QVBoxLayout(self.empty_hint)
        eh_layout.setContentsMargins(20, 44, 20, 44)
        eh_layout.setSpacing(6)
        eh_title = QLabel("LIBRARY EMPTY")
        eh_title.setFont(display_font(12, "Bold", 2.2))
        eh_title.setStyleSheet(f"color: {C.DIM}; background: transparent;")
        eh_title.setAlignment(Qt.AlignCenter)
        eh_sub = QLabel("Unlock a file above to add it here")
        eh_sub.setFont(body_font(14, "Medium", 0.2))
        eh_sub.setStyleSheet(f"color: {C.BORDER}; background: transparent;")
        eh_sub.setAlignment(Qt.AlignCenter)
        eh_layout.addWidget(eh_title)
        eh_layout.addWidget(eh_sub)
        self._layout.addWidget(self.empty_hint)

    def add_item(self, item):
        self.empty_hint.hide()
        self._counters[item.kind] = self._counters.get(item.kind, 0) + 1
        index_label = f"{item.kind} {self._counters[item.kind]}"
        card = LibraryCard(item, index_label)
        card.clicked.connect(self.itemClicked)
        self._layout.addWidget(card)
        return card

    def clear(self):
        while self._layout.count() > 1:
            child = self._layout.takeAt(1)
            widget = child.widget()
            if widget and widget is not self.empty_hint:
                widget.deleteLater()
        self._counters = {}
        self.empty_hint.show()
