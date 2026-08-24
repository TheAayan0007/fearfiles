"""
FEAR - File Encryption And Reader
Entry point. Each tab lives in its own module: encrypt_tab.py, read_tab.py,
decrypt_tab.py. This module owns the window chrome around them: the brand
header and the nav bar that switches between the three.
"""

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QStackedWidget, QButtonGroup, QFrame
)

import theme
from theme import C, HUDButton, LiveDot, display_font, brand_label, CenteredColumn, screen_default_size
from encrypt_tab import EncryptTab
from read_tab import ReadTab
from decrypt_tab import DecryptTab


class NavBar(QWidget):
    """Replaces the default QTabWidget tab strip with three exclusive,
    checkable HUD buttons driving a QStackedWidget -- gives full control
    over the look instead of fighting QTabBar's stylesheet."""

    currentChanged = Signal(int)

    def __init__(self, labels):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.buttons = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, label in enumerate(labels):
            btn = HUDButton(label, variant="nav", checkable=True, cut=10)
            btn.setMinimumHeight(42)
            self.group.addButton(btn, i)
            layout.addWidget(btn, 1)
            self.buttons.append(btn)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.currentChanged)

    def setCurrentIndex(self, index):
        self.buttons[index].setChecked(True)


class Header(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 16)
        layout.setSpacing(10)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)
        title = brand_label("FEAR", px=25)
        subtitle = QLabel("FILE ENCRYPTION AND READER")
        subtitle.setFont(display_font(9, "Medium", 2.6))
        subtitle.setStyleSheet(f"color: {C.DIM}; background: transparent;")
        brand_col.addWidget(title)
        brand_col.addWidget(subtitle)
        layout.addLayout(brand_col)

        layout.addStretch()

        status_col = QVBoxLayout()
        status_col.setSpacing(2)
        tag_row = QHBoxLayout()
        tag_row.setSpacing(6)
        tag_row.setContentsMargins(0, 0, 0, 0)
        dot = LiveDot(color=C.ACCENT, diameter=7)
        tag = QLabel("V3.0")
        tag.setFont(display_font(12, "Black", 1.2))
        tag.setStyleSheet(f"color: {C.ACCENT}; background: transparent;")
        tag_row.addStretch()
        tag_row.addWidget(dot)
        tag_row.addWidget(tag)
        status_col.addLayout(tag_row)
        ready = QLabel("SYSTEM READY")
        ready.setFont(display_font(8.5, "Medium", 1.8))
        ready.setStyleSheet(f"color: {C.BORDER}; background: transparent;")
        ready.setAlignment(Qt.AlignRight)
        status_col.addWidget(ready)
        layout.addLayout(status_col)


class HeaderDivider(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {C.BORDER_SOFT}; border: none;")


class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.setWindowTitle("FEAR v3 — File Encryption And Reader")
        self.resize(*screen_default_size(app))
        self.setMinimumSize(640, 740)
        self.setStyleSheet(f"QMainWindow {{ background-color: {C.BG}; }}")

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(Header())
        outer.addWidget(HeaderDivider())

        nav_wrap = QWidget()
        nav_layout = QHBoxLayout(nav_wrap)
        nav_layout.setContentsMargins(28, 16, 28, 16)
        self.nav = NavBar(["ENCRYPT", "READ", "DECRYPT"])
        nav_layout.addWidget(CenteredColumn(self.nav, max_width=760))
        outer.addWidget(nav_wrap)

        self.encrypt_tab = EncryptTab()
        self.read_tab = ReadTab()
        self.decrypt_tab = DecryptTab()

        self.stack = QStackedWidget()
        self.stack.addWidget(self.encrypt_tab)   # index 0
        self.stack.addWidget(self.read_tab)      # index 1
        self.stack.addWidget(self.decrypt_tab)   # index 2
        self.nav.currentChanged.connect(self.stack.setCurrentIndex)
        outer.addWidget(self.stack, 1)

        self.setCentralWidget(central)

    def closeEvent(self, event):
        self.read_tab.cleanup_on_close()
        event.accept()

    def center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(max(geo.x(), x), max(geo.y(), y))


def main():
    # Must be set before QApplication is constructed. Qt6 enables high-DPI
    # scaling by default, but on Windows with fractional scaling (125%,
    # 150% -- the common case on most 1920x1080 laptop displays) the
    # default rounding policy can make fonts/controls come out the wrong
    # physical size or slightly blurry. PassThrough uses the exact OS
    # scale factor instead of rounding it to the nearest integer.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("FEAR")
    theme.install_fonts()
    app.setStyleSheet(theme.build_qss())
    window = MainWindow(app)
    window.center_on_screen()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
