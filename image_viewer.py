"""
FEAR - fullscreen image viewer ("lightbox") with left/right navigation
between every image currently in the Read tab's library.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy

from theme import C, HUDButton, display_font, body_font


class ImageLightbox(QDialog):
    def __init__(self, images, start_index, parent=None):
        super().__init__(parent)
        self.images = images  # list of LibraryItem, all kind == "image"
        self.index = start_index
        self.setWindowTitle("Image viewer")
        self.setStyleSheet(f"QDialog {{ background-color: {C.BG_VOID}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(20, 16, 20, 10)
        top_row.setSpacing(10)
        self.title_label = QLabel("")
        self.title_label.setFont(body_font(15, "SemiBold", 0.2))
        self.title_label.setStyleSheet(f"color: {C.TEXT_BRIGHT}; background: transparent;")
        self.counter_label = QLabel("")
        self.counter_label.setFont(display_font(11, "Bold", 1.4))
        self.counter_label.setStyleSheet(f"color: {C.ACCENT}; background: transparent;")
        close_btn = HUDButton("CLOSE (ESC)", variant="ghost", cut=6)
        close_btn.setMinimumHeight(32)
        close_btn.clicked.connect(self.close)
        top_row.addWidget(self.title_label)
        top_row.addWidget(self.counter_label)
        top_row.addStretch()
        top_row.addWidget(close_btn)
        layout.addLayout(top_row)

        middle_row = QHBoxLayout()
        middle_row.setSpacing(0)
        self.prev_btn = HUDButton("\u2039", variant="ghost", cut=10, uppercase=False)
        self.prev_btn.setFixedWidth(56)
        self.prev_btn.setFont(display_font(20, "Bold", 0))
        self.prev_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.prev_btn.clicked.connect(self.show_previous)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.next_btn = HUDButton("\u203a", variant="ghost", cut=10, uppercase=False)
        self.next_btn.setFixedWidth(56)
        self.next_btn.setFont(display_font(20, "Bold", 0))
        self.next_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.next_btn.clicked.connect(self.show_next)
        middle_row.addWidget(self.prev_btn)
        middle_row.addWidget(self.image_label, 1)
        middle_row.addWidget(self.next_btn)
        layout.addLayout(middle_row, 1)

        self._render_current()
        self.showFullScreen()

    def _render_current(self):
        item = self.images[self.index]
        image = QImage.fromData(item.image_bytes)
        target_size = self.size() if self.isVisible() else self.sizeHint()
        pixmap = QPixmap.fromImage(image).scaled(
            max(target_size.width() - 160, 200), max(target_size.height() - 160, 200),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(pixmap)
        self.title_label.setText(item.title)
        self.counter_label.setText(f"{self.index + 1} / {len(self.images)}")
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.images) - 1)

    def show_previous(self):
        if self.index > 0:
            self.index -= 1
            self._render_current()

    def show_next(self):
        if self.index < len(self.images) - 1:
            self.index += 1
            self._render_current()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Left:
            self.show_previous()
        elif event.key() == Qt.Key_Right:
            self.show_next()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_current()
