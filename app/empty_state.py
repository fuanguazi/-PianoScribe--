"""Empty-state placeholder widget for PianoScribe.

Used by the analysis page (sheet music + piano roll areas when no audio is
loaded) and the edit page (when no MIDI is imported). Renders an elegant SVG
illustration plus optional title / subtitle / CTA button.

The widget is transparent (no background) so it blends with the parent card.
Illustration colors are pulled from the design-token system
(``tokens(theme).color.empty_state_icon``) and re-rendered when the theme
changes via :meth:`EmptyState.update_theme`.

Self-contained — no hard dependency on the optional ``app_icons`` module.
All four illustration presets are rendered via :class:`QSvgRenderer` and a
pixmap cache keyed by ``(preset, color, size)`` so theme switches are cheap.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import Qt, QSize

_log = logging.getLogger(__name__)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ============================================================
#  DESIGN TOKENS — with safe fallbacks for unit testing
# ============================================================
try:
    from design_tokens import (
        get_current_theme_name,
        qcolor,
        qfont,
        tokens,
    )
    _HAS_DESIGN_TOKENS = True
except Exception:  # pragma: no cover — minimal fallback when design_tokens missing
    _HAS_DESIGN_TOKENS = False

    _FALLBACK_LIGHT = {
        "empty_state_icon": "rgba(0, 0, 0, 0.15)",
        "empty_state_text": "#86868B",
        "text_primary": "#1D1D1F",
        "text_secondary": "#86868B",
        "hint_text": "#AEAEB2",
        "accent": "#007DFF",
        "brand_gradient": ("#6366F1", "#8B5CF6", "#EC4899"),
        "brand_gradient_hover": ("#7C7FF5", "#A78BFA", "#F472B6"),
        "brand_gradient_pressed": ("#4F52E0", "#6F46D4", "#D63B83"),
    }
    _FALLBACK_DARK = {
        "empty_state_icon": "rgba(255, 255, 255, 0.15)",
        "empty_state_text": "#98989D",
        "text_primary": "#F5F5F7",
        "text_secondary": "#98989D",
        "hint_text": "#636366",
        "accent": "#0A84FF",
        "brand_gradient": ("#818CF8", "#A78BFA", "#F472B6"),
        "brand_gradient_hover": ("#9BA5FA", "#BBA0FB", "#F88FBE"),
        "brand_gradient_pressed": ("#6E78E5", "#8E74E6", "#D85FA0"),
    }

    class _ColorStub:
        def __init__(self, d):
            for k, v in d.items():
                setattr(self, k, v)

    class _TypeStub:
        size_px = 16

    class _TypoStub:
        h3 = _TypeStub()
        caption = _TypeStub()

    class _SpacingStub:
        md = 12

    class _RadiusStub:
        md = 12

    class _TokenStub:
        def __init__(self, name):
            d = _FALLBACK_LIGHT if name == "light" else _FALLBACK_DARK
            self.color = _ColorStub(d)
            self.typography = _TypoStub()
            self.spacing = _SpacingStub()
            self.radius = _RadiusStub()
            self.theme_name = name

    def tokens(theme_name=None):  # type: ignore[override]
        if theme_name is None:
            theme_name = "light"
        return _TokenStub(theme_name)

    def qcolor(s):  # type: ignore[override]
        return QColor(s)

    def get_current_theme_name():  # type: ignore[override]
        return "light"

    def qfont(level):  # type: ignore[override]
        f = QFont()
        if level == "h3":
            f.setPixelSize(16)
            f.setWeight(QFont.DemiBold)
        elif level == "caption":
            f.setPixelSize(12)
        return f


# Optional: import app_icons module (built in parallel — graceful fallback).
try:
    from app_icons import icon as _get_app_icon  # type: ignore[import]
    _HAS_APP_ICONS = True
except Exception:  # pragma: no cover — app_icons is optional
    _HAS_APP_ICONS = False
    _get_app_icon = None


# ============================================================
#  COLOR / SVG HELPERS
# ============================================================
def _normalize_color(color_str: str, min_alpha: float = 0.20) -> QColor:
    """Parse a color string and ensure the alpha is at least ``min_alpha``.

    The design-token ``empty_state_icon`` value (rgba 0.15) is intentionally
    faint. For the illustrations to be visible we lift the alpha to at least
    0.20 so the SVG doesn't disappear against a card background.
    """
    c = qcolor(color_str)
    if not c.isValid():
        # Last-ditch fallback to a near-transparent black.
        c = QColor(0, 0, 0, 38)
    if c.alphaF() < min_alpha:
        c.setAlphaF(min_alpha)
    return c


def _svg_color_parts(color: QColor) -> Tuple[str, float]:
    """Return ``(hex_str '#RRGGBB', alpha_float)`` for SVG attributes."""
    return color.name(), float(color.alphaF())


def _fmt_alpha(a: float) -> str:
    """Format an alpha float as a 3-decimal SVG attribute value."""
    return f"{max(0.0, min(1.0, a)):.3f}"


# ============================================================
#  ILLUSTRATION SVG GENERATORS
# ============================================================
# Each function takes a color string (any format accepted by ``qcolor()``)
# and returns a complete SVG document string ready for ``QSvgRenderer``.
# All illustrations use a 96x96 viewBox so they scale cleanly.


def _svg_sheet_music(color_hex: str) -> str:
    """Musical staff with 5 lines, simplified treble clef, 3 notes."""
    c = _normalize_color(color_hex)
    hex_str, alpha = _svg_color_parts(c)
    a = _fmt_alpha(alpha)

    # 5 staff lines (8 px apart, centered vertically).
    staff_y = (30, 38, 46, 54, 62)
    lines = "\n".join(
        f'  <line x1="10" y1="{y}" x2="86" y2="{y}" '
        f'stroke="{hex_str}" stroke-opacity="{a}" stroke-width="1.2"/>'
        for y in staff_y
    )

    # Treble clef: vertical staff with a small swirl on top and a tail below.
    clef = (
        f'  <path d="M 22 26 Q 16 36 20 44 Q 26 52 20 60 L 20 70" '
        f'fill="none" stroke="{hex_str}" stroke-opacity="{a}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>\n'
        f'  <circle cx="20" cy="72" r="2.2" fill="{hex_str}" fill-opacity="{a}"/>'
    )

    # 3 notes — filled circles with stems on different staff positions.
    notes = ""
    for nx, ny, slen in ((38, 30, 16), (54, 46, 18), (72, 62, 14)):
        notes += (
            f'  <ellipse cx="{nx}" cy="{ny}" rx="3.6" ry="2.5" '
            f'fill="{hex_str}" fill-opacity="{a}" '
            f'transform="rotate(-22 {nx} {ny})"/>\n'
            f'  <line x1="{nx + 3}" y1="{ny}" x2="{nx + 3}" y2="{ny - slen}" '
            f'stroke="{hex_str}" stroke-opacity="{a}" stroke-width="1.3" '
            f'stroke-linecap="round"/>\n'
        )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" '
        'fill="none">\n'
        + lines
        + "\n"
        + clef
        + "\n"
        + notes
        + "</svg>"
    )


def _svg_piano_roll(color_hex: str) -> str:
    """Piano roll grid + keyboard (8 white keys, 5 black keys)."""
    c = _normalize_color(color_hex)
    hex_str, alpha = _svg_color_parts(c)
    a_grid = _fmt_alpha(alpha * 0.75)        # softer grid lines
    a_keys = _fmt_alpha(alpha)               # keyboard outline
    a_white_sep = _fmt_alpha(alpha * 0.9)    # white-key separators
    a_black = _fmt_alpha(min(1.0, alpha * 1.5))  # black keys more visible

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" '
        'fill="none">'
    ]

    # ---- Grid (5 rows x 8 cols) above keyboard ----
    grid_x, grid_y = 12, 14
    cell_w, cell_h = 9, 5
    n_cols, n_rows = 8, 5
    grid_w = cell_w * n_cols  # 72
    grid_h = cell_h * n_rows  # 25

    parts.append(
        f'  <rect x="{grid_x}" y="{grid_y}" width="{grid_w}" height="{grid_h}" '
        f'fill="none" stroke="{hex_str}" stroke-opacity="{a_grid}" '
        f'stroke-width="1"/>'
    )
    for i in range(1, n_cols):
        x = grid_x + i * cell_w
        parts.append(
            f'  <line x1="{x}" y1="{grid_y}" x2="{x}" '
            f'y2="{grid_y + grid_h}" stroke="{hex_str}" '
            f'stroke-opacity="{a_grid}" stroke-width="0.8"/>'
        )
    for i in range(1, n_rows):
        y = grid_y + i * cell_h
        parts.append(
            f'  <line x1="{grid_x}" y1="{y}" x2="{grid_x + grid_w}" '
            f'y2="{y}" stroke="{hex_str}" stroke-opacity="{a_grid}" '
            f'stroke-width="0.8"/>'
        )

    # ---- Keyboard at bottom ----
    kb_y = grid_y + grid_h + 8  # 47
    kb_h = 24
    n_white = 8
    white_w = grid_w / n_white  # 9

    parts.append(
        f'  <rect x="{grid_x}" y="{kb_y}" width="{grid_w}" height="{kb_h}" '
        f'fill="none" stroke="{hex_str}" stroke-opacity="{a_keys}" '
        f'stroke-width="1.2"/>'
    )
    for i in range(1, n_white):
        x = grid_x + i * white_w
        parts.append(
            f'  <line x1="{x:.1f}" y1="{kb_y}" x2="{x:.1f}" '
            f'y2="{kb_y + kb_h}" stroke="{hex_str}" '
            f'stroke-opacity="{a_white_sep}" stroke-width="1"/>'
        )

    # Black keys: placed after white keys 0,1,3,4,5 (skipping 2 and 6 to
    # mirror a real piano octave).
    black_positions = (0, 1, 3, 4, 5)
    black_w = white_w * 0.6
    black_h = kb_h * 0.6
    for pos in black_positions:
        bx = grid_x + (pos + 1) * white_w - black_w / 2
        parts.append(
            f'  <rect x="{bx:.2f}" y="{kb_y}" width="{black_w:.2f}" '
            f'height="{black_h}" fill="{hex_str}" fill-opacity="{a_black}"/>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _svg_midi_import(color_hex: str) -> str:
    """MIDI file icon (folded corner) + music note + import arrow."""
    c = _normalize_color(color_hex)
    hex_str, alpha = _svg_color_parts(c)
    a = _fmt_alpha(alpha)
    a_strong = _fmt_alpha(min(1.0, alpha * 1.4))

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" '
        'fill="none">\n'
        # File outline with folded corner
        '  <path d="M 28 16 L 60 16 L 68 24 L 68 80 L 28 80 Z" '
        f'fill="none" stroke="{hex_str}" stroke-opacity="{a}" '
        'stroke-width="1.5" stroke-linejoin="round"/>\n'
        # Fold corner inner line
        '  <path d="M 60 16 L 60 24 L 68 24" '
        f'fill="none" stroke="{hex_str}" stroke-opacity="{a}" '
        'stroke-width="1.2" stroke-linejoin="round"/>\n'
        # Music note inside the file
        f'  <ellipse cx="42" cy="62" rx="4" ry="3" fill="{hex_str}" '
        f'fill-opacity="{a_strong}" transform="rotate(-18 42 62)"/>\n'
        f'  <line x1="46" y1="62" x2="46" y2="38" stroke="{hex_str}" '
        f'stroke-opacity="{a_strong}" stroke-width="1.8" '
        'stroke-linecap="round"/>\n'
        # Note flag
        f'  <path d="M 46 38 Q 56 36 56 44" fill="none" '
        f'stroke="{hex_str}" stroke-opacity="{a_strong}" '
        'stroke-width="1.5" stroke-linecap="round"/>\n'
        # Arrow pointing in (from the left)
        f'  <line x1="10" y1="48" x2="22" y2="48" stroke="{hex_str}" '
        f'stroke-opacity="{a_strong}" stroke-width="2" '
        'stroke-linecap="round"/>\n'
        '  <path d="M 18 44 L 22 48 L 18 52" fill="none" '
        f'stroke="{hex_str}" stroke-opacity="{a_strong}" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>\n'
        "</svg>"
    )


def _svg_generic(color_hex: str) -> str:
    """Dotted rectangle frame + folder icon (placeholder)."""
    c = _normalize_color(color_hex)
    hex_str, alpha = _svg_color_parts(c)
    a = _fmt_alpha(alpha)
    a_strong = _fmt_alpha(min(1.0, alpha * 1.4))

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" '
        'fill="none">\n'
        # Dotted rectangle frame
        '  <rect x="12" y="16" width="72" height="64" rx="6" ry="6" '
        f'fill="none" stroke="{hex_str}" stroke-opacity="{a}" '
        'stroke-width="1.5" stroke-dasharray="3 3"/>\n'
        # Folder icon in center
        '  <path d="M 36 40 L 44 40 L 47 43 L 60 43 L 60 60 L 36 60 Z" '
        f'fill="none" stroke="{hex_str}" stroke-opacity="{a_strong}" '
        'stroke-width="1.5" stroke-linejoin="round"/>\n'
        # Folder divider line
        f'  <line x1="36" y1="48" x2="60" y2="48" stroke="{hex_str}" '
        f'stroke-opacity="{a}" stroke-width="1"/>\n'
        "</svg>"
    )


_ILLUSTRATIONS: Dict[str, Callable[[str], str]] = {
    "sheet_music": _svg_sheet_music,
    "piano_roll": _svg_piano_roll,
    "midi_import": _svg_midi_import,
    "generic": _svg_generic,
}


# ============================================================
#  PIXMAP CACHE + RENDERING
# ============================================================
# Key: (preset_name, color_string, size_px). The color string is the
# normalized form (after _normalize_color) so theme switches bump the cache.
_PIXMAP_CACHE: Dict[Tuple[str, str, int], QPixmap] = {}


def _device_pixel_ratio() -> float:
    """Return the primary screen's devicePixelRatio, defaulting to 1.0."""
    try:
        app = QApplication.instance()
        if app is None:
            return 1.0
        screen = QApplication.primaryScreen()
        if screen is None:
            return 1.0
        dpr = float(screen.devicePixelRatio())
        return dpr if dpr > 0.0 else 1.0
    except Exception:
        return 1.0


def _color_cache_key(color: QColor) -> str:
    """Serialize a QColor to a stable cache-key string."""
    return "#{:02X}{:02X}{:02X}{:02X}".format(
        color.red(), color.green(), color.blue(), color.alpha()
    )


def _render_illustration(
    preset: str, color_str: str, size: int
) -> QPixmap:
    """Render the SVG illustration onto a DPR-aware QPixmap.

    Results are cached by ``(preset, normalized_color, size)`` — subsequent
    calls with the same parameters return the cached pixmap.
    """
    color = _normalize_color(color_str)
    cache_key = (preset, _color_cache_key(color), size)
    cached = _PIXMAP_CACHE.get(cache_key)
    if cached is not None and not cached.isNull():
        return cached

    svg_gen = _ILLUSTRATIONS.get(preset, _svg_generic)
    svg_str = svg_gen(color.name(QColor.HexArgb))

    renderer = QSvgRenderer(svg_str.encode("utf-8"))
    if not renderer.isValid():
        # Return an empty (transparent) pixmap so callers don't crash.
        empty = QPixmap(size, size)
        empty.fill(Qt.transparent)
        return empty

    dpr = _device_pixel_ratio()
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)

    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        renderer.render(painter)
    finally:
        painter.end()

    _PIXMAP_CACHE[cache_key] = pix
    return pix


def clear_pixmap_cache() -> None:
    """Clear the pixmap cache. Useful in tests after a theme switch."""
    _PIXMAP_CACHE.clear()


# ============================================================
#  EMPTY STATE WIDGET
# ============================================================
class EmptyState(QWidget):
    """Centered empty-state placeholder with SVG illustration + text.

    Layout (vertical, centered):
      - SVG illustration (96x96 by default, semi-transparent)
      - 16 px gap
      - Title (h3 typography — 16 px DemiBold)
      - 4 px gap
      - Subtitle (caption — 12 px secondary color, optional, wraps)
      - 20 px gap (optional)
      - CTA button (optional, callable via callback)

    The widget is transparent (no background) so it blends with the parent
    card.
    """

    def __init__(
        self,
        illustration: str = "sheet_music",
        title: str = "等待加载",
        subtitle: str = "",
        cta_text: str = "",
        on_cta: Optional[Callable[[], None]] = None,
        icon_size: int = 96,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._illustration = (
            illustration if illustration in _ILLUSTRATIONS else "generic"
        )
        self._title = title
        self._subtitle = subtitle
        self._cta_text = cta_text
        self._on_cta = on_cta
        self._icon_size = max(16, int(icon_size))
        self._theme = "light"
        try:
            self._theme = get_current_theme_name()
        except Exception:
            self._theme = "light"

        # ---- Transparent background ----
        self.setObjectName("EmptyState")
        # WA_StyledBackground off so the widget doesn't draw its own bg
        # under QSS — the parent card shows through.
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet(
            "EmptyState { background: transparent; border: none; }"
        )

        # ---- Layout ----
        # Always create title / subtitle / CTA so the setter methods
        # (set_title, set_subtitle, set_cta) work in all cases. Labels are
        # hidden when their text is empty — hidden widgets collapse in the
        # QVBoxLayout so the layout adapts naturally.
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(24, 24, 24, 24)
        self._main_layout.setSpacing(0)
        self._main_layout.setAlignment(Qt.AlignCenter)

        # Illustration label — slightly larger than icon_size so the SVG
        # has breathing room.
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_label.setFixedSize(self._icon_size + 8, self._icon_size + 8)
        self._icon_label.setStyleSheet(
            "QLabel { background: transparent; border: none; }"
        )
        self._main_layout.addWidget(self._icon_label)

        # 16 px gap between illustration and title
        self._main_layout.addSpacing(16)

        # ---- Title (h3 = 16 px DemiBold) ----
        self._title_label = QLabel(title)
        self._title_label.setAlignment(Qt.AlignCenter)
        self._title_label.setWordWrap(True)
        if _HAS_DESIGN_TOKENS:
            try:
                self._title_label.setFont(qfont("h3"))
            except Exception:
                pass
        self._main_layout.addWidget(self._title_label)

        # ---- Subtitle (caption = 12 px) ----
        # Always created so set_subtitle works later; hidden when empty.
        self._main_layout.addSpacing(4)
        self._subtitle_label = QLabel(subtitle)
        self._subtitle_label.setAlignment(Qt.AlignCenter)
        self._subtitle_label.setWordWrap(True)
        self._subtitle_label.setMaximumWidth(360)
        self._subtitle_label.setStyleSheet(
            "QLabel { background: transparent; border: none; }"
        )
        if _HAS_DESIGN_TOKENS:
            try:
                self._subtitle_label.setFont(qfont("caption"))
            except Exception:
                pass
        self._subtitle_label.setVisible(bool(subtitle))
        self._main_layout.addWidget(self._subtitle_label)

        # ---- CTA button ----
        # Always created so set_cta works later; hidden when empty.
        self._main_layout.addSpacing(20)
        self._cta_btn = QPushButton(cta_text)
        self._cta_btn.setCursor(Qt.PointingHandCursor)
        self._cta_btn.setFixedHeight(36)
        self._cta_btn.setMinimumWidth(120)
        self._cta_btn.setMaximumWidth(240)
        # Always wire to the internal handler — on_cta is invoked from there.
        self._cta_btn.clicked.connect(self._handle_cta_click)
        self._cta_btn.setVisible(bool(cta_text))
        self._main_layout.addWidget(self._cta_btn)
        self._main_layout.setAlignment(self._cta_btn, Qt.AlignCenter)

        # Apply the current theme's colors + illustration
        self._apply_theme(self._theme)

    # ----------------------------------------------------------
    #  Theme handling
    # ----------------------------------------------------------
    def _apply_theme(self, theme_name: str) -> None:
        if theme_name not in ("light", "dark"):
            theme_name = "light"
        t = tokens(theme_name)

        # Illustration — render via cached QSvgRenderer.
        color_str = t.color.empty_state_icon
        pix = _render_illustration(self._illustration, color_str, self._icon_size)
        self._icon_label.setPixmap(pix)

        # Title: h3 typography (already applied via setFont), color =
        # text_secondary (subtle, not loud).
        title_color = t.color.text_secondary
        self._title_label.setStyleSheet(
            "QLabel { color: " + title_color + "; "
            "background: transparent; border: none; }"
        )

        # Subtitle: caption typography, color = hint_text (lighter still).
        sub_color = t.color.hint_text
        self._subtitle_label.setStyleSheet(
            "QLabel { color: " + sub_color + "; "
            "background: transparent; border: none; }"
        )

        # CTA button: brand-gradient background.
        self._style_cta_button(t)

    def _style_cta_button(self, t) -> None:
        """Apply brand-gradient styling to the CTA button."""
        try:
            radius = t.radius.md
        except AttributeError:
            radius = 12

        # Compose QSS qlineargradient strings from the brand gradient tuples.
        def _gradient_css(g):
            return (
                "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                "stop:0 " + g[0] + ", "
                "stop:0.5 " + g[1] + ", "
                "stop:1 " + g[2] + ")"
            )

        gradient = _gradient_css(t.color.brand_gradient)
        try:
            gradient_hover = _gradient_css(t.color.brand_gradient_hover)
        except AttributeError:
            gradient_hover = gradient
        try:
            gradient_pressed = _gradient_css(t.color.brand_gradient_pressed)
        except AttributeError:
            gradient_pressed = gradient

        self._cta_btn.setStyleSheet(
            "QPushButton {"
            " color: #FFFFFF;"
            " background: " + gradient + ";"
            " border: none;"
            " border-radius: " + str(radius) + "px;"
            " padding: 8px 18px;"
            " font-size: 13px;"
            " font-weight: 500;"
            "}"
            "QPushButton:hover {"
            " background: " + gradient_hover + ";"
            "}"
            "QPushButton:pressed {"
            " background: " + gradient_pressed + ";"
            "}"
            "QPushButton:disabled {"
            " background: rgba(128, 128, 128, 0.4);"
            " color: rgba(255, 255, 255, 0.6);"
            "}"
        )

    def update_theme(self, theme_name: str) -> None:
        """Re-render the illustration and label colors for the new theme."""
        if theme_name not in ("light", "dark"):
            theme_name = "light"
        self._theme = theme_name
        self._apply_theme(theme_name)

    # ----------------------------------------------------------
    #  CTA click handling — swallow user-callback exceptions so the UI
    #  never crashes from a callback error.
    # ----------------------------------------------------------
    def _handle_cta_click(self) -> None:
        cb = self._on_cta
        if cb is None:
            return
        try:
            cb()
        except Exception:
            import traceback
            _log.warning("CTA callback failed: %s", traceback.format_exc())

    # ----------------------------------------------------------
    #  Convenience accessors
    # ----------------------------------------------------------
    def set_illustration(self, name: str) -> None:
        """Swap the illustration preset (re-renders immediately)."""
        target = name if name in _ILLUSTRATIONS else "generic"
        if target == self._illustration:
            return
        self._illustration = target
        t = tokens(self._theme)
        pix = _render_illustration(
            self._illustration, t.color.empty_state_icon, self._icon_size
        )
        self._icon_label.setPixmap(pix)

    def set_title(self, title: str) -> None:
        self._title = title
        self._title_label.setText(title)
        # Title is always visible (even when empty) per the spec — it's the
        # primary text element.

    def set_subtitle(self, subtitle: str) -> None:
        """Update or clear the subtitle. Pass '' to hide it."""
        self._subtitle = subtitle
        self._subtitle_label.setText(subtitle)
        self._subtitle_label.setVisible(bool(subtitle))

    def set_cta(
        self,
        cta_text: str,
        on_cta: Optional[Callable[[], None]] = None,
    ) -> None:
        """Update the CTA button label / callback. Hides the button when empty."""
        self._cta_text = cta_text
        self._on_cta = on_cta
        self._cta_btn.setText(cta_text)
        self._cta_btn.setVisible(bool(cta_text))

    def sizeHint(self) -> QSize:
        # Width accommodates a 360 px subtitle wrap; height is approximate.
        return QSize(360, 260)


# ============================================================
#  MODULE API
# ============================================================
__all__ = [
    "EmptyState",
    "clear_pixmap_cache",
    "_ILLUSTRATIONS",
    "_render_illustration",
]


# ============================================================
#  MANUAL SMOKE TEST
# ============================================================
if __name__ == "__main__":  # pragma: no cover
    import sys

    try:
        app = QApplication.instance() or QApplication(sys.argv)
    except Exception as exc:
        print("QApplication unavailable — verifying import only:", exc)
        assert hasattr(sys.modules[__name__], "EmptyState")
        print("import OK")
        sys.exit(0)

    from PySide6.QtWidgets import QWidget, QVBoxLayout

    parent = QWidget()
    parent.resize(640, 480)
    lay = QVBoxLayout(parent)
    lay.addWidget(
        EmptyState(
            "sheet_music",
            "等待音频",
            "选择音频文件开始分析",
            "选择音频",
            lambda: None,
        )
    )
    lay.addWidget(
        EmptyState("piano_roll", "等待音频", "钢琴卷帘将在分析完成后显示")
    )
    lay.addWidget(
        EmptyState(
            "midi_import",
            "等待导入",
            "点击导入 MIDI 文件开始编辑",
            "导入 MIDI",
            lambda: None,
        )
    )
    parent.show()
    print("OK — widget constructed and shown")

    # Render a couple of pixmaps to exercise the SVG pipeline.
    for preset in _ILLUSTRATIONS:
        pix = _render_illustration(preset, "rgba(0, 0, 0, 0.15)", 96)
        assert not pix.isNull(), f"pixmap for {preset} is null"
        print(f"  rendered {preset}: {pix.width()}x{pix.height()}")
    print("OK")
