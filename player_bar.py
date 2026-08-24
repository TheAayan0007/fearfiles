"""
FEAR - the "alpha" mini player bar, the expanded "now playing" view, and the
dedicated fullscreen video window. These three views don't own their own
QMediaPlayer -- ReadTab creates a single shared player, and switching
between views just re-targets where that player renders its video (see
ReadTab.play_item / expand_to_now_playing / enter_fullscreen). That keeps
playback position continuous as you move between mini bar, full view, and
true fullscreen.
"""

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QFrame, QWidget, QLabel, QSlider, QHBoxLayout, QVBoxLayout, QStackedWidget
)
from PySide6.QtMultimediaWidgets import QVideoWidget

import icons
from theme import C, HUDButton, HUDPanel, LiveDot, display_font, body_font


def format_ms(ms):
    if ms is None or ms < 0:
        ms = 0
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


class ClickableVideoWidget(QVideoWidget):
    """A QVideoWidget that reports double-clicks, used to jump into/out of
    fullscreen from anywhere on the video itself."""

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


def _time_label():
    lbl = QLabel("0:00")
    lbl.setFont(display_font(11, "Medium", 0.5))
    lbl.setStyleSheet(f"color: {C.DIM}; background: transparent;")
    lbl.setFixedWidth(46)
    return lbl


class _TransportRow(QHBoxLayout):
    """Shared row of time / seek slider / time used by both the mini bar and
    the bigger views, so the three stay visually consistent."""

    def __init__(self):
        super().__init__()
        self.setSpacing(10)
        self.time_label = _time_label()
        self.seek_slider = QSlider(Qt.Horizontal)
        self.duration_label = _time_label()
        self.duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.addWidget(self.time_label)
        self.addWidget(self.seek_slider, 1)
        self.addWidget(self.duration_label)

    def set_position(self, position_ms, duration_ms):
        self.seek_slider.blockSignals(True)
        self.seek_slider.setRange(0, max(duration_ms, 0))
        self.seek_slider.setValue(position_ms)
        self.seek_slider.blockSignals(False)
        self.time_label.setText(format_ms(position_ms))
        self.duration_label.setText(format_ms(duration_ms))


class AlphaBar(QFrame):
    """Bottom-docked mini player ('alpha'). Clicking the bar body expands to
    Now Playing; the play/pause button and seek slider handle their own
    clicks independently (see the WA_TransparentForMouseEvents labels)."""

    expandRequested = Signal()
    playPauseClicked = Signal()
    seekRequested = Signal(int)
    loopToggled = Signal(bool)

    VISUAL_SIZE = 52

    def __init__(self):
        super().__init__()
        self.setFixedHeight(78)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        self.visual_stack = QStackedWidget()
        self.visual_stack.setFixedSize(self.VISUAL_SIZE, self.VISUAL_SIZE)
        self.visual_stack.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.visual_stack.setStyleSheet(
            f"QStackedWidget {{ border: 1px solid {C.BORDER}; background: {C.BG_VOID}; }}"
        )

        self.thumb_label = QLabel()
        self.thumb_label.setScaledContents(True)
        self.thumb_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.visual_stack.addWidget(self.thumb_label)  # index 0: static icon

        self.mini_video = ClickableVideoWidget()
        self.mini_video.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.visual_stack.addWidget(self.mini_video)  # index 1: live small video

        layout.addWidget(self.visual_stack)

        mid = QVBoxLayout()
        mid.setSpacing(5)
        cap_row = QHBoxLayout()
        cap_row.setSpacing(6)
        self.live_dot = LiveDot(color=C.ACCENT, diameter=6)
        self.live_dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        cap_row.addWidget(self.live_dot)
        cap_label = QLabel("NOW PLAYING")
        cap_label.setFont(display_font(9, "Bold", 1.6))
        cap_label.setStyleSheet(f"color: {C.DIM}; background: transparent;")
        cap_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        cap_row.addWidget(cap_label)
        cap_row.addStretch()
        mid.addLayout(cap_row)

        self.title_label = QLabel("Nothing playing")
        self.title_label.setFont(body_font(15, "SemiBold", 0.2))
        self.title_label.setStyleSheet(f"color: {C.TEXT_BRIGHT}; background: transparent;")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        mid.addWidget(self.title_label)
        self.transport = _TransportRow()
        self.transport.seek_slider.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.transport.time_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.transport.duration_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.transport.seek_slider.sliderMoved.connect(self.seekRequested)
        mid.addLayout(self.transport)
        layout.addLayout(mid, 1)

        self.play_btn = HUDButton("PAUSE", variant="default", cut=6)
        self.play_btn.setFixedWidth(78)
        self.play_btn.setMinimumHeight(34)
        self.play_btn.clicked.connect(self.playPauseClicked)
        layout.addWidget(self.play_btn)

        self.loop_btn = HUDButton("LOOP", variant="default", cut=6, checkable=True)
        self.loop_btn.setFixedWidth(66)
        self.loop_btn.setMinimumHeight(34)
        self.loop_btn.toggled.connect(self.loopToggled)
        layout.addWidget(self.loop_btn)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(C.PANEL_SOLID))
        p.setPen(QPen(QColor(C.ACCENT), 1.5))
        p.drawLine(0, 0, self.width(), 0)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.expandRequested.emit()
        super().mousePressEvent(event)

    def show_static_thumb(self, pixmap):
        self.thumb_label.setPixmap(pixmap)
        self.visual_stack.setCurrentIndex(0)

    def show_live_video(self):
        self.visual_stack.setCurrentIndex(1)
        return self.mini_video

    def set_now_playing(self, item):
        self.title_label.setText(item.title)
        if item.kind != "video":
            icon = icons.audio_placeholder(self.VISUAL_SIZE)
            self.show_static_thumb(icon)

    def set_playing_state(self, is_playing):
        self.play_btn.setText("PAUSE" if is_playing else "PLAY")

    def set_position(self, position_ms, duration_ms):
        self.transport.set_position(position_ms, duration_ms)


class NowPlayingView(QWidget):
    """The 'full window' view -- appears when the alpha bar is clicked."""

    minimizeRequested = Signal()
    fullscreenRequested = Signal()
    playPauseClicked = Signal()
    seekRequested = Signal(int)
    loopToggled = Signal(bool)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        minimize_btn = HUDButton("\u2039 BACK TO LIBRARY", variant="ghost", cut=6, uppercase=False)
        minimize_btn.setMinimumHeight(32)
        minimize_btn.clicked.connect(self.minimizeRequested)
        top_row.addWidget(minimize_btn)
        top_row.addStretch()
        self.live_dot = LiveDot(color=C.ACCENT, diameter=6)
        top_row.addWidget(self.live_dot)
        now_lbl = QLabel("NOW PLAYING")
        now_lbl.setFont(display_font(8.5, "Bold", 1.2))
        now_lbl.setStyleSheet(f"color: {C.DIM}; background: transparent;")
        top_row.addWidget(now_lbl)
        layout.addLayout(top_row)

        self.video_widget = ClickableVideoWidget()
        self.video_widget.doubleClicked.connect(self.fullscreenRequested)
        self.video_widget.setStyleSheet(f"background: {C.BG_VOID}; border: 1px solid {C.BORDER};")
        layout.addWidget(self.video_widget, 1)

        self.title_label = QLabel("")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(display_font(15, "Bold", 1.0))
        self.title_label.setStyleSheet(f"color: {C.TEXT_BRIGHT}; background: transparent;")
        layout.addWidget(self.title_label)

        self.transport = _TransportRow()
        self.transport.seek_slider.sliderMoved.connect(self.seekRequested)
        layout.addLayout(self.transport)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        self.play_btn = HUDButton("PAUSE", variant="primary", cut=8)
        self.play_btn.setMinimumHeight(38)
        self.play_btn.setMinimumWidth(96)
        self.play_btn.clicked.connect(self.playPauseClicked)
        self.loop_btn = HUDButton("LOOP", variant="default", cut=8, checkable=True)
        self.loop_btn.setMinimumHeight(38)
        self.loop_btn.toggled.connect(self.loopToggled)
        hint = QLabel("Double-click the video for fullscreen")
        hint.setFont(body_font(12.5, "Medium", 0.2))
        hint.setStyleSheet(f"color: {C.DIM}; background: transparent;")
        buttons.addWidget(self.play_btn)
        buttons.addWidget(self.loop_btn)
        buttons.addSpacing(6)
        buttons.addWidget(hint)
        buttons.addStretch()
        layout.addLayout(buttons)

    def set_now_playing(self, item):
        self.title_label.setText(item.title.upper())

    def set_playing_state(self, is_playing):
        self.play_btn.setText("PAUSE" if is_playing else "PLAY")

    def set_position(self, position_ms, duration_ms):
        self.transport.set_position(position_ms, duration_ms)


class FullscreenVideoWindow(QWidget):
    """A dedicated top-level window for true OS fullscreen playback. Exits
    via double-click on the video (mirroring how you entered) or Escape."""

    exitRequested = Signal()
    playPauseClicked = Signal()
    seekRequested = Signal(int)
    loopToggled = Signal(bool)

    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setStyleSheet(f"background-color: {C.BG_VOID}; color: {C.TEXT};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.video_widget = ClickableVideoWidget()
        self.video_widget.doubleClicked.connect(self.exitRequested)
        layout.addWidget(self.video_widget, 1)

        control_panel = HUDPanel(cut=0, corners=(), fill=C.PANEL_SOLID,
                                  border=C.BORDER_SOFT, top_accent=True)
        controls = QHBoxLayout(control_panel)
        controls.setContentsMargins(18, 12, 18, 14)
        controls.setSpacing(14)
        self.play_btn = HUDButton("PAUSE", variant="primary", cut=8)
        self.play_btn.setMinimumHeight(38)
        self.play_btn.setMinimumWidth(90)
        self.play_btn.clicked.connect(self.playPauseClicked)
        self.transport = _TransportRow()
        self.transport.seek_slider.sliderMoved.connect(self.seekRequested)
        self.loop_btn = HUDButton("LOOP", variant="default", cut=8, checkable=True)
        self.loop_btn.setMinimumHeight(38)
        self.loop_btn.toggled.connect(self.loopToggled)
        exit_btn = HUDButton("EXIT FULLSCREEN (ESC)", variant="ghost", cut=8)
        exit_btn.setMinimumHeight(38)
        exit_btn.clicked.connect(self.exitRequested)
        controls.addWidget(self.play_btn)
        controls.addLayout(self.transport, 1)
        controls.addWidget(self.loop_btn)
        controls.addWidget(exit_btn)
        layout.addWidget(control_panel)

    def set_playing_state(self, is_playing):
        self.play_btn.setText("PAUSE" if is_playing else "PLAY")

    def set_position(self, position_ms, duration_ms):
        self.transport.set_position(position_ms, duration_ms)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.exitRequested.emit()
        else:
            super().keyPressEvent(event)
