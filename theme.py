"""
FEAR v3 - visual theme.

Everything UI-related that isn't specific to one tab lives here: the color
palette, the bundled Orbitron/Rajdhani fonts, the global stylesheet, and a
handful of reusable "HUD" widgets (angular cut-corner panels and buttons,
corner brackets, a live status dot, a glowing progress bar). Every other
module imports from here rather than hardcoding colors, so the look stays
consistent and can be re-tuned in one place.

Nothing in here touches app behavior/logic -- it's presentation only.
"""

import os

from PySide6.QtCore import (
    Qt, QTimer, QRectF, QSize, QPointF, Property, QPropertyAnimation, QEasingCurve
)
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QBrush,
    QLinearGradient, QRadialGradient
)
from PySide6.QtWidgets import (
    QWidget, QFrame, QPushButton, QLabel, QGraphicsDropShadowEffect,
    QSizePolicy, QButtonGroup, QHBoxLayout
)

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")

FONT_DISPLAY = "Orbitron"   # headers, labels, buttons -- angular/technical
FONT_BODY = "Rajdhani"      # everything read at length -- titles, hints, input


# ───────────────────────────── palette ─────────────────────────────

class C:
    BG = "#04070f"           # window background
    BG_VOID = "#010409"      # deepest black (fullscreen video/image chrome)
    PANEL = "#0a1526"        # card / panel fill
    PANEL_SOLID = "#0b1220"  # input fields, list rows
    PANEL_RAISED = "#0e1c33" # hover state fill
    BORDER = "#153152"       # default hairline border
    BORDER_SOFT = "#0d2137"  # quieter border (dividers)

    ACCENT = "#00e7ff"       # cyan -- primary
    ACCENT2 = "#ff2d6b"      # magenta -- danger / alerts
    ACCENT3 = "#ffc300"      # amber -- warnings / active

    DIM = "#5c85ad"          # secondary text
    TEXT = "#a9c9e6"         # body text
    TEXT_BRIGHT = "#eef8ff"  # emphasized text / headings
    SUCCESS = "#2be5a0"      # confirmations
    DANGER = "#ff2d6b"

    @staticmethod
    def rgba(hexcolor, alpha):
        c = QColor(hexcolor)
        return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


# ───────────────────────────── fonts ─────────────────────────────

_FONT_FILES = [
    "Orbitron-Regular.ttf", "Orbitron-Medium.ttf", "Orbitron-Bold.ttf", "Orbitron-Black.ttf",
    "Rajdhani-Light.ttf", "Rajdhani-Regular.ttf", "Rajdhani-Medium.ttf",
    "Rajdhani-SemiBold.ttf", "Rajdhani-Bold.ttf",
]

_fonts_loaded = False


def install_fonts():
    """Load the bundled fonts into the application font database. Safe to
    call more than once. Falls back gracefully (Qt just won't find an
    exact match and substitutes a system font) if a file is missing."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    for fname in _FONT_FILES:
        path = os.path.join(FONTS_DIR, fname)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    _fonts_loaded = True


def display_font(px=12, weight="Bold", spacing=1.5):
    """Orbitron, looked up by exact style name so the real bold/black
    outlines are used (not a synthetic/faux bold)."""
    f = QFontDatabase.font(FONT_DISPLAY, weight, 12)
    if f.family() != FONT_DISPLAY:
        f = QFont(FONT_DISPLAY)
    f.setPixelSize(px)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def body_font(px=14, weight="Regular", spacing=0.0):
    f = QFontDatabase.font(FONT_BODY, weight, 12)
    if f.family() != FONT_BODY:
        f = QFont(FONT_BODY)
    f.setPixelSize(px)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


# ───────────────────────────── shape helpers ─────────────────────────────

def cut_rect_path(rect, cut=12, corners=("tr",)):
    """A rectangle with one or more corners sliced off at 45 deg -- the
    angular 'HUD panel' silhouette used throughout the reference UIs
    (CSS clip-path polygons). `rect` is a QRectF/QRect."""
    r = QRectF(rect)
    x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
    cut = min(cut, r.width() / 2, r.height() / 2)

    path = QPainterPath()
    start = "tl"
    order = ["tl", "tr", "br", "bl"]
    pts = []

    def add_corner(name):
        if name == "tl":
            if name in corners:
                pts.append((x0, y0 + cut)); pts.append((x0 + cut, y0))
            else:
                pts.append((x0, y0))
        elif name == "tr":
            if name in corners:
                pts.append((x1 - cut, y0)); pts.append((x1, y0 + cut))
            else:
                pts.append((x1, y0))
        elif name == "br":
            if name in corners:
                pts.append((x1, y1 - cut)); pts.append((x1 - cut, y1))
            else:
                pts.append((x1, y1))
        elif name == "bl":
            if name in corners:
                pts.append((x0 + cut, y1)); pts.append((x0, y1 - cut))
            else:
                pts.append((x0, y1))

    for name in order:
        add_corner(name)

    path.moveTo(*pts[0])
    for p in pts[1:]:
        path.lineTo(*p)
    path.closeSubpath()
    return path


# ───────────────────────────── small overlay bits ─────────────────────────────

class CornerBrackets(QWidget):
    """Four L-shaped brackets pinned to the corners of whatever rect this
    widget occupies -- decorative viewfinder framing, mirrors the
    `.bracket` elements in the reference HUDs. Purely decorative: it never
    accepts mouse input."""

    def __init__(self, parent=None, size=22, thickness=2, inset=8, color=None, opacity=0.5):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._size = size
        self._thickness = thickness
        self._inset = inset
        self._color = QColor(color or C.ACCENT)
        self._opacity = opacity

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(self._color)
        col.setAlphaF(self._opacity)
        pen = QPen(col, self._thickness)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        s, i = self._size, self._inset
        w, h = self.width(), self.height()

        p.drawPolyline([_pt(i, i + s), _pt(i, i), _pt(i + s, i)])
        p.drawPolyline([_pt(w - i - s, i), _pt(w - i, i), _pt(w - i, i + s)])
        p.drawPolyline([_pt(i, h - i - s), _pt(i, h - i), _pt(i + s, h - i)])
        p.drawPolyline([_pt(w - i - s, h - i), _pt(w - i, h - i), _pt(w - i, h - i - s)])
        p.end()


def _pt(x, y):
    return QPointF(x, y)


class LiveDot(QWidget):
    """Small blinking glow dot -- an 'active/live' status indicator."""

    def __init__(self, parent=None, color=None, diameter=7, blink=True):
        super().__init__(parent)
        self._color = QColor(color or C.ACCENT)
        self._d = diameter
        self._alpha = 1.0
        self.setFixedSize(diameter + 10, diameter + 10)
        if blink:
            self._anim = QPropertyAnimation(self, b"alpha")
            self._anim.setStartValue(1.0)
            self._anim.setKeyValueAt(0.5, 0.25)
            self._anim.setEndValue(1.0)
            self._anim.setDuration(1400)
            self._anim.setLoopCount(-1)
            self._anim.start()

    def getAlpha(self):
        return self._alpha

    def setAlpha(self, v):
        self._alpha = v
        self.update()

    alpha = Property(float, getAlpha, setAlpha)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        col = QColor(self._color)
        col.setAlphaF(self._alpha)
        glow = QRadialGradient(cx, cy, self._d * 1.8)
        glow_col = QColor(self._color)
        glow_col.setAlphaF(0.55 * self._alpha)
        glow.setColorAt(0, glow_col)
        glow_col.setAlphaF(0)
        glow.setColorAt(1, glow_col)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(cx - self._d * 1.8, cy - self._d * 1.8, self._d * 3.6, self._d * 3.6))
        p.setBrush(QBrush(col))
        p.drawEllipse(QRectF(cx - self._d / 2, cy - self._d / 2, self._d, self._d))
        p.end()


# ───────────────────────────── panel ─────────────────────────────

class HUDPanel(QFrame):
    """An angular-cornered panel: translucent fill, hairline border, and
    an optional bright accent hairline across the top edge. The base
    container for cards, drop zones, and grouped sections."""

    def __init__(self, parent=None, cut=14, corners=("tr",), fill=None,
                 border=None, top_accent=False, accent_color=None):
        super().__init__(parent)
        self._cut = cut
        self._corners = corners
        self._fill = QColor(fill or C.PANEL)
        self._border = QColor(border or C.BORDER)
        self._top_accent = top_accent
        self._accent_color = QColor(accent_color or C.ACCENT)
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = cut_rect_path(rect, self._cut, self._corners)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._fill))
        p.drawPath(path)
        p.setPen(QPen(self._border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if self._top_accent:
            top_right_x = rect.right() - (self._cut if "tr" in self._corners else 0)
            top_left_x = rect.left() + (self._cut if "tl" in self._corners else 0)
            grad = QLinearGradient(top_left_x, 0, top_right_x, 0)
            edge = QColor(self._accent_color); edge.setAlphaF(0.0)
            mid = QColor(self._accent_color); mid.setAlphaF(1.0)
            grad.setColorAt(0.0, edge)
            grad.setColorAt(0.5, mid)
            grad.setColorAt(1.0, edge)
            p.setPen(QPen(QBrush(grad), 2))
            p.drawLine(_pt(top_left_x, rect.top()), _pt(top_right_x, rect.top()))
        p.end()


# ───────────────────────────── buttons ─────────────────────────────

_VARIANTS = {
    "default": dict(fg=C.TEXT, fg_hover=C.ACCENT, border=C.BORDER, border_hover=C.ACCENT,
                     fill=C.rgba(C.ACCENT, 12), fill_hover=C.rgba(C.ACCENT, 30),
                     fill_active=C.rgba(C.ACCENT, 40), glow=C.ACCENT),
    "primary": dict(fg=C.ACCENT, fg_hover="#02141a", border=C.ACCENT, border_hover=C.ACCENT,
                     fill=C.rgba(C.ACCENT, 34), fill_hover=C.ACCENT,
                     fill_active=C.ACCENT, glow=C.ACCENT),
    "danger": dict(fg=C.ACCENT2, fg_hover=C.ACCENT2, border=C.rgba(C.ACCENT2, 110), border_hover=C.ACCENT2,
                    fill=C.rgba(C.ACCENT2, 16), fill_hover=C.rgba(C.ACCENT2, 34),
                    fill_active=C.rgba(C.ACCENT2, 44), glow=C.ACCENT2),
    "ghost": dict(fg=C.DIM, fg_hover=C.TEXT_BRIGHT, border="transparent", border_hover=C.BORDER,
                   fill="transparent", fill_hover=C.rgba(C.ACCENT, 10),
                   fill_active=C.rgba(C.ACCENT, 18), glow=C.ACCENT),
    "nav": dict(fg=C.DIM, fg_hover=C.TEXT_BRIGHT, border=C.BORDER_SOFT, border_hover=C.ACCENT,
                fill=C.rgba(C.ACCENT, 6), fill_hover=C.rgba(C.ACCENT, 16),
                fill_active=C.rgba(C.ACCENT, 22), glow=C.ACCENT),
}


class HUDButton(QPushButton):
    """Custom-painted angular button matching the reference `.hud-btn`
    family (default / primary / danger / ghost / nav), including a
    checked/'active' state used for toggle chips (loop, show-password,
    the nav bar). Text is upper-cased automatically, Orbitron, letter
    spaced. A soft drop-shadow glow appears on hover/active."""

    def __init__(self, text="", variant="default", parent=None, cut=9, checkable=False, uppercase=True):
        super().__init__(text, parent)
        self.variant = variant
        self._cut = cut
        self._uppercase = uppercase
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(display_font(11, "Bold", 1.6))
        self.setMinimumHeight(38)
        sp = self.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Minimum)
        self.setSizePolicy(sp)
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setBlurRadius(0)
        self._glow.setOffset(0, 0)
        self._glow.setColor(QColor(_VARIANTS[variant]["glow"]))
        self.setGraphicsEffect(self._glow)
        self._glow_anim = QPropertyAnimation(self._glow, b"blurRadius")
        self._glow_anim.setDuration(160)

    def _set_glow(self, target):
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow.blurRadius())
        self._glow_anim.setEndValue(target)
        self._glow_anim.start()

    def enterEvent(self, event):
        if self.isEnabled():
            self._set_glow(22)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_glow(0 if not self.isChecked() else 14)
        super().leaveEvent(event)

    def checkStateSet(self):
        self._set_glow(14 if self.isChecked() else 0)
        super().checkStateSet()

    def nextCheckState(self):
        super().nextCheckState()
        self._set_glow(14 if self.isChecked() else 0)

    def sizeHint(self):
        base = super().sizeHint()
        return base + QSize(20, 6)

    def paintEvent(self, event):
        colors = _VARIANTS[self.variant]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        path = cut_rect_path(rect, self._cut, ("tr",) if self.variant != "nav" else ("tr", "bl"))

        hovered = self.underMouse() and self.isEnabled()
        active = self.isChecked()
        pressed = self.isDown() and self.isEnabled()

        if not self.isEnabled():
            fill = QColor(C.PANEL_SOLID)
            border = QColor(C.BORDER_SOFT)
            fg = QColor(C.BORDER)
        else:
            fill = QColor(colors["fill_active"] if active else (colors["fill_hover"] if hovered else colors["fill"]))
            if pressed:
                fill = fill.darker(115)
            border = QColor(colors["border_hover"] if (hovered or active) else colors["border"])
            fg = QColor(colors["fg_hover"] if (hovered or active) else colors["fg"])

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(fill))
        p.drawPath(path)
        if border.alpha() > 0:
            pen = QPen(border, 1.2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

        p.setPen(fg)
        p.setFont(self.font())
        text = self.text().upper() if self._uppercase else self.text()
        p.drawText(rect, Qt.AlignCenter, text)
        p.end()


# ───────────────────────────── progress / meter ─────────────────────────────

class HUDProgressBar(QWidget):
    """Thin glowing progress track -- used for the password-strength meter.
    Not a QProgressBar subclass: fully custom-painted to get the glowing
    leading edge from the reference loading bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._max = 100
        self._color = QColor(C.BORDER)
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setRange(self, lo, hi):
        self._max = max(hi, 1)
        self.update()

    def setValue(self, v):
        self._value = max(0, min(v, self._max))
        self.update()

    def setColor(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track = QRectF(0, h / 2 - 1.5, w, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C.BORDER_SOFT))
        p.drawRoundedRect(track, 1.5, 1.5)

        frac = self._value / self._max if self._max else 0
        fill_w = max(0.0, min(1.0, frac)) * w
        if fill_w > 0:
            fill_rect = QRectF(0, h / 2 - 1.5, fill_w, 3)
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(fill_rect, 1.5, 1.5)
            glow = QRadialGradient(fill_w, h / 2, 9)
            c1 = QColor(self._color); c1.setAlphaF(0.85)
            c2 = QColor(self._color); c2.setAlphaF(0)
            glow.setColorAt(0, c1)
            glow.setColorAt(1, c2)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QRectF(fill_w - 9, h / 2 - 9, 18, 18))
        p.end()


# ───────────────────────────── labels ─────────────────────────────

class CenteredColumn(QWidget):
    """Caps its content to a max width and centers it horizontally. Without
    this, a simple form (password field, drop zone, one button) stretches
    edge-to-edge on a wide/maximized window and looks broken -- a huge
    password box, a needlessly wide drop zone. Vertical space is left to
    the caller: give the CenteredColumn a stretch factor when adding it if
    the tab should grow to fill height (e.g. a scrolling list), or none if
    it should just hug its natural height near the top.

    Implemented as margins recomputed on resize (CSS's `max-width` +
    `margin: 0 auto`) rather than competing layout stretches -- a widget
    with an Expanding size policy placed between two addStretch() spacers
    does not reliably grow to fill the space up to its maximumWidth, since
    stretch-factor-0 items and Expanding spacer items don't have a
    well-defined priority order in QBoxLayout. Margins sidestep that
    entirely: whatever space is left after the margin is exactly what the
    content gets, no ambiguity."""

    def __init__(self, content_widget, max_width=800, parent=None):
        super().__init__(parent)
        self._max_width = max_width
        policy = content_widget.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Expanding)
        content_widget.setSizePolicy(policy)
        sp = self.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Expanding)
        self.setSizePolicy(sp)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content_widget)

    def resizeEvent(self, event):
        w = self.width()
        pad = max(0, (w - self._max_width) // 2)
        self.layout().setContentsMargins(pad, 0, pad, 0)
        super().resizeEvent(event)


def screen_default_size(app, width_frac=0.58, height_frac=0.82, min_w=860, min_h=760, max_w=1180, max_h=980):
    """A window size proportional to the actual screen instead of a flat
    guess -- a fixed 860x780 looks tiny and off-center on a 1920x1080+
    display. Falls back to (min_w, min_h) if no screen is available yet."""
    screen = app.primaryScreen()
    if screen is None:
        return min_w, min_h
    geo = screen.availableGeometry()
    w = max(min_w, min(max_w, int(geo.width() * width_frac)))
    h = max(min_h, min(max_h, int(geo.height() * height_frac)))
    return w, h


def section_label(text, color=None):
    """Small dim uppercase Orbitron caption used to head a group of
    controls -- mirrors `.panel-title` in the reference HUDs."""
    lbl = QLabel(text.upper())
    lbl.setFont(display_font(10, "Bold", 2.4))
    lbl.setStyleSheet(f"color: {color or C.DIM}; padding-bottom: 2px; border-bottom: 1px solid {C.BORDER_SOFT};")
    lbl.setContentsMargins(0, 6, 0, 6)
    return lbl


def field_caption(text, color=None):
    """Small uppercase caption above a single input field -- no divider,
    just enough hierarchy to separate it from the field below."""
    lbl = QLabel(text.upper())
    lbl.setFont(display_font(9.5, "Bold", 1.8))
    lbl.setStyleSheet(f"color: {color or C.DIM}; background: transparent;")
    return lbl


def brand_label(text, px=20, color=C.TEXT_BRIGHT):
    lbl = QLabel(text.upper())
    lbl.setFont(display_font(px, "Black", 2.0))
    lbl.setStyleSheet(f"color: {color};")
    return lbl


class StatusLabel(QLabel):
    """Status readout with a small leading dot, matching the reference
    toast/status-tag coloring per kind."""

    _KIND_COLOR = {"info": C.ACCENT, "success": C.SUCCESS, "error": C.ACCENT2, "warn": C.ACCENT3}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(body_font(13, "Medium", 0.3))
        self.setWordWrap(True)
        self._kind = "info"
        self.setText("")

    def set_status(self, text, kind="info"):
        self._kind = kind
        color = self._KIND_COLOR.get(kind, C.ACCENT)
        if text:
            self.setStyleSheet(f"color: {color};")
            self.setText(("● " + text))
        else:
            self.setText("")

    def clear_status(self):
        self.setText("")


# ───────────────────────────── global stylesheet ─────────────────────────────

def build_qss():
    return f"""
    QMainWindow, QDialog, QMessageBox {{
        background-color: {C.BG};
        color: {C.TEXT};
    }}
    QWidget {{
        color: {C.TEXT};
        font-family: "{FONT_BODY}";
        selection-background-color: {C.rgba(C.ACCENT, 90)};
        selection-color: {C.TEXT_BRIGHT};
    }}
    QLabel {{ background: transparent; }}

    QToolTip {{
        background-color: {C.PANEL_SOLID};
        color: {C.ACCENT};
        border: 1px solid {C.BORDER};
        padding: 4px 8px;
    }}

    QLineEdit {{
        background-color: {C.PANEL_SOLID};
        border: 1px solid {C.BORDER};
        color: {C.TEXT_BRIGHT};
        padding: 9px 11px;
        font-size: 14px;
    }}
    QLineEdit:focus {{ border: 1px solid {C.ACCENT}; }}
    QLineEdit:disabled {{ color: {C.DIM}; }}

    QPushButton {{
        background-color: {C.PANEL_SOLID};
        border: 1px solid {C.BORDER};
        color: {C.TEXT};
        padding: 7px 14px;
    }}
    QPushButton:hover {{ border-color: {C.ACCENT}; color: {C.ACCENT}; }}
    QPushButton:pressed {{ background-color: {C.rgba(C.ACCENT, 30)}; }}
    QPushButton:disabled {{ color: {C.BORDER}; border-color: {C.BORDER_SOFT}; }}

    QScrollBar:vertical {{
        background: {C.BG_VOID};
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {C.BORDER};
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {C.ACCENT}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    QScrollBar:horizontal {{
        background: {C.BG_VOID};
        height: 10px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {C.BORDER};
        min-width: 28px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {C.ACCENT}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

    QSlider::groove:horizontal {{
        background: {C.BORDER};
        height: 3px;
    }}
    QSlider::sub-page:horizontal {{ background: {C.ACCENT}; height: 3px; }}
    QSlider::add-page:horizontal {{ background: {C.BORDER}; height: 3px; }}
    QSlider::handle:horizontal {{
        background: {C.ACCENT};
        width: 13px; height: 13px;
        margin: -5px 0;
        border-radius: 6px;
    }}
    QSlider::handle:horizontal:hover {{ background: {C.TEXT_BRIGHT}; }}

    QListWidget {{
        background-color: {C.PANEL_SOLID};
        border: 1px solid {C.BORDER};
        color: {C.TEXT};
        outline: 0;
    }}
    QListWidget::item {{ padding: 6px; }}
    QListWidget::item:selected {{ background: {C.rgba(C.ACCENT, 45)}; color: {C.TEXT_BRIGHT}; }}
    QListWidget::item:hover:!selected {{ background: {C.rgba(C.ACCENT, 18)}; }}

    QMessageBox QPushButton, QDialog QPushButton {{
        min-width: 76px;
        padding: 7px 16px;
    }}

    QCheckBox {{ color: {C.TEXT}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {C.BORDER};
        background: {C.PANEL_SOLID};
    }}
    QCheckBox::indicator:checked {{
        border: 1px solid {C.ACCENT};
        background: {C.rgba(C.ACCENT, 60)};
    }}
    """
