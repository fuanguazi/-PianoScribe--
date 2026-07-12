# -*- coding: utf-8 -*-
"""app_icons.py — PianoScribe SVG icon system.

Self-contained module that exports an `IconPainter` class for rendering SVG
path data into `QIcon` / `QPixmap` / SVG strings, plus a registry of all
icons used in the PianoScribe application.

All icons share the following visual contract:

  * 24x24 viewBox
  * 1.5px stroke (configurable per-painter)
  * `fill="none"`
  * `stroke="currentColor"` by default, or an explicit color supplied by the
    caller (hex string, `rgb()`/`rgba()` string, or `QColor`)
  * round line caps and joins
  * Lucide / Feather-style outline aesthetic

When rendered to a `QPixmap` / `QIcon` with no explicit color, icons pick up
the current theme's `text_primary` color automatically via `design_tokens`.

Multiple sub-paths in a single icon are separated by the literal token ``||``
in the registry value. Each segment becomes its own ``<path>`` element in the
rendered SVG, which keeps path data readable and lets sub-paths use different
moveto origins.

Public API
----------
    IconPainter(path_data, stroke_width=1.5)
        .svg(color=None, size=24) -> str
        .pixmap(color=None, size=24, theme_name=None) -> QPixmap
        .icon(color=None, size=24, theme_name=None) -> QIcon

    ICONS: Dict[str, str]
        name -> path data (sub-paths joined by '||')

    get_icon(name) -> IconPainter
    icon_pixmap(name, size=24, color=None, theme_name=None) -> QPixmap
    icon(name, size=24, color=None, theme_name=None) -> QIcon

The module can be imported without a running `QApplication` and without
PySide6 installed at all — only `ICONS` / `get_icon()` / `IconPainter.svg()`
work in that degraded mode. `pixmap()` and `icon()` require PySide6.QtSvg.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

# NOTE: PySide6 imports are deferred to method-call time so the module can be
# imported in environments without PySide6 (e.g. to introspect ICONS). This
# lets the registry be unit-tested without spinning up a Qt application.

ColorLike = Union[str, "QColor"]  # forward ref; resolved at call time


# ============================================================
#  SVG TEMPLATE
# ============================================================
_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'viewBox="0 0 24 24" width="{size}" height="{size}" '
    'fill="none" stroke="{color}" stroke-width="{sw}" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '{paths}'
    '</svg>'
)

_PATH_TEMPLATE = '<path d="{d}"/>'

# Token used to separate multiple <path> elements inside a single registry
# entry. Chosen because it cannot appear in valid SVG path data.
_PATH_SEPARATOR = '||'


# ============================================================
#  COLOR HELPERS
# ============================================================
def _normalize_color(color: object) -> str:
    """Normalize a color argument to a string usable in the SVG stroke attr.

    * ``None`` -> ``'currentColor'`` so the SVG inherits the surrounding text
      color (useful in QSS / HTML / QSvgWidget contexts).
    * `QColor` -> ``'#RRGGBB'`` (or ``'rgba(r, g, b, a)'`` when alpha < 255,
      since SVG 1.1 does not support ``#AARRGGBB``).
    * `str` -> returned as-is (caller can pass hex, ``rgb()``, ``rgba()`` or a
      named color).
    """
    if color is None:
        return 'currentColor'

    # Duck-type QColor without importing it at module load.
    if hasattr(color, 'red') and hasattr(color, 'green') and hasattr(color, 'blue') \
            and hasattr(color, 'alpha'):
        try:
            r, g, b, a = color.red(), color.green(), color.blue(), color.alpha()
            if a >= 255:
                return f'#{r:02X}{g:02X}{b:02X}'
            return f'rgba({r}, {g}, {b}, {a / 255.0:.3f})'
        except Exception:
            # Last-resort: try QColor.name()
            try:
                return color.name()  # type: ignore[union-attr]
            except Exception:
                return 'currentColor'

    if isinstance(color, str):
        return color

    # Unknown type — coerce to string and hope for the best.
    return str(color)


def _theme_text_primary(theme_name: Optional[str]) -> str:
    """Resolve the current theme's `text_primary` color string.

    Falls back to ``'#1D1D1F'`` (the light-theme default) when `design_tokens`
    is unavailable (e.g. running outside the app context).
    """
    try:
        from design_tokens import tokens, get_current_theme_name
        name = theme_name if theme_name is not None else get_current_theme_name()
        return str(getattr(tokens(name).color, 'text_primary', '#1D1D1F'))
    except Exception:
        return '#1D1D1F'


# ============================================================
#  IconPainter
# ============================================================
class IconPainter:
    """Renders SVG path data into QIcon / QPixmap / SVG strings.

    All icons use a 24x24 viewBox, a configurable stroke width (default 1.5px),
    `fill="none"`, round line caps/joins, and a stroke color that defaults to
    `currentColor` (or the theme's `text_primary` when rendered to a pixmap).
    """

    __slots__ = ('_paths', '_stroke_width')

    # -- construction ---------------------------------------------------
    def __init__(self, path_data: str, stroke_width: float = 1.5) -> None:
        if not isinstance(path_data, str):
            raise TypeError(
                f"path_data must be str, got {type(path_data).__name__}"
            )
        # Split on the separator so registry entries can carry multiple
        # <path> elements (e.g. a sun's rays + its disc).
        self._paths: List[str] = [
            p.strip() for p in path_data.split(_PATH_SEPARATOR) if p.strip()
        ]
        if not self._paths:
            raise ValueError("path_data contains no valid path segments")
        if stroke_width <= 0:
            raise ValueError(f"stroke_width must be > 0, got {stroke_width}")
        self._stroke_width = float(stroke_width)

    # -- introspection --------------------------------------------------
    @property
    def paths(self) -> List[str]:
        """List of sub-path `d` strings (one per `<path>` element)."""
        return list(self._paths)

    @property
    def stroke_width(self) -> float:
        return self._stroke_width

    # -- core -----------------------------------------------------------
    def svg(self, color: object = None, size: int = 24) -> str:
        """Return a complete, self-contained SVG string for this icon.

        Parameters
        ----------
        color : str | QColor | None
            Stroke color. If ``None``, uses ``'currentColor'`` so the SVG
            inherits the surrounding text color (useful in QSS / HTML
            contexts). For a `QColor`, the value is converted to a hex or
            `rgba()` string.
        size : int
            Output pixel size (width == height). Used only for the
            ``width`` / ``height`` attributes of the root ``<svg>``; the
            viewBox is always 24x24.
        """
        if size <= 0:
            raise ValueError(f"size must be > 0, got {size}")
        color_str = _normalize_color(color)
        paths_xml = ''.join(
            _PATH_TEMPLATE.format(d=d) for d in self._paths
        )
        return _SVG_TEMPLATE.format(
            size=int(size),
            color=color_str,
            sw=self._stroke_width,
            paths=paths_xml,
        )

    def pixmap(
        self,
        color: object = None,
        size: int = 24,
        theme_name: Optional[str] = None,
    ) -> "QPixmap":
        """Render this icon to a `QPixmap`.

        Renders at ``size * devicePixelRatio`` for crisp HiDPI output and
        sets the pixmap's logical size to ``size`` via
        `setDevicePixelRatio()`.

        If `color` is ``None``, the current theme's `text_primary` color is
        used (or `theme_name` if explicitly provided).
        """
        from PySide6.QtCore import QByteArray, Qt
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer

        if size <= 0:
            raise ValueError(f"size must be > 0, got {size}")

        # Resolve the effective stroke color before building the SVG.
        if color is None:
            color = _theme_text_primary(theme_name)

        svg_xml = self.svg(color=color, size=size)

        # Detect devicePixelRatio for crisp HiDPI rendering. Fall back to 1
        # when no QGuiApplication is running or no screen is attached.
        dpr = 1.0
        try:
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app is not None:
                screen = app.primaryScreen()
                if screen is not None:
                    dpr = float(screen.devicePixelRatio()) or 1.0
        except Exception:
            pass
        # Clamp to a sane range — extremely high DPRs would waste memory.
        dpr = max(1.0, min(4.0, dpr))

        render_size = max(1, int(round(size * dpr)))
        pixmap = QPixmap(render_size, render_size)
        pixmap.fill(Qt.transparent)

        renderer = QSvgRenderer(QByteArray(svg_xml.encode('utf-8')))
        if not renderer.isValid():
            # Return a transparent pixmap if the SVG failed to parse — the
            # caller gets a non-null pixmap but it just shows nothing.
            return pixmap

        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            # renderer.render() with no target rect fills the painter's
            # current device — i.e. the entire pixmap.
            renderer.render(painter)
        finally:
            painter.end()

        # Tell Qt the pixmap represents a `size x size` logical image so it
        # gets drawn at the right size in a widget.
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    def icon(
        self,
        color: object = None,
        size: int = 24,
        theme_name: Optional[str] = None,
    ) -> "QIcon":
        """Render this icon to a `QIcon` (auto pixel-ratio aware).

        Equivalent to ``QIcon(self.pixmap(...))``. For multi-resolution icons
        (different sizes for different modes), call `pixmap()` explicitly
        and assemble the `QIcon` yourself.
        """
        from PySide6.QtGui import QIcon
        pm = self.pixmap(color=color, size=size, theme_name=theme_name)
        return QIcon(pm)


# ============================================================
#  ICON REGISTRY
# ============================================================
# Each value is the SVG path 'd' attribute of a single <path> element, OR
# multiple sub-paths joined by '||' (each becomes its own <path>). All paths
# are designed for a 24x24 viewBox with 1.5px stroke, fill="none", round
# line caps/joins. Style is Lucide / Feather line icons.
ICONS: Dict[str, str] = {
    # --- Mode cards (4) -----------------------------------------------
    # microphone (singing mode)
    'mic':        'M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z'
                  ' M19 10v2a7 7 0 0 1-14 0v-2'
                  ' M12 19v3'
                  ' M8 22h8',
    # piano keyboard (standard mode)
    'piano':      'M3 5h18v14H3z'
                  ' M3 9h18'
                  ' M9 5v14'
                  ' M15 5v14'
                  ' M7 9v6'
                  ' M11 9v6'
                  ' M13 9v6'
                  ' M17 9v6',
    # audio waveform (vocal mode)
    'waveform':   'M3 12h2'
                  ' M7 8v8'
                  ' M11 5v14'
                  ' M15 8v8'
                  ' M19 12h2',
    # pencil editing (edit mode)
    'edit':       'M12 20h9'
                  ' M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z',

    # --- Theme toggle (2) ---------------------------------------------
    # sun with rays (light theme indicator)
    'sun':        'M12 1v2'
                  ' M12 21v2'
                  ' M4.22 4.22l1.42 1.42'
                  ' M18.36 18.36l1.42 1.42'
                  ' M1 12h2'
                  ' M21 12h2'
                  ' M4.22 19.78l1.42-1.42'
                  ' M18.36 5.64l1.42-1.42'
                  ' M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z',
    # crescent moon (dark theme indicator)
    'moon':       'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z',
    # gear / settings (Lucide settings-2 style)
    'settings':   'M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z'
                  ' M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',

    # --- Transport (3) ------------------------------------------------
    # play triangle
    'play':       'M6 4l14 8-14 8z',
    # stop square
    'stop':       'M5 5h14v14H5z',
    # download / export arrow into tray
    'download':   'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'
                  ' M7 10l5 5 5-5'
                  ' M12 15V3',

    # --- Edit tools (3) -----------------------------------------------
    # arrow cursor (selection tool)
    'cursor':     'M3 3l7.07 17 2.51-7.39L20 10.07z',
    # pencil
    'pencil':     'M12 20h9'
                  ' M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z',
    # eraser
    'eraser':     'M7 21H4a1 1 0 0 1-1-1v-3.59a2 2 0 0 1 .59-1.42'
                  'L13.41 4.59a2 2 0 0 1 2.83 0L19.41 8a2 2 0 0 1 0 2.83L8.83 21H7z'
                  ' M18 13l-4-4'
                  ' M7 21h10',

    # --- Window controls (3) ------------------------------------------
    # minimize (horizontal line near bottom)
    'minimize':   'M5 12h14',
    # maximize (square outline)
    'maximize':   'M5 5h14v14H5z',
    # close X
    'close':      'M18 6L6 18'
                  ' M6 6l12 12',

    # --- Toolbar misc (10) --------------------------------------------
    # magnifier with plus
    'zoom_in':    'M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14z'
                  ' M21 21l-4.3-4.3'
                  ' M11 8v6'
                  ' M8 11h6',
    # magnifier with minus
    'zoom_out':   'M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14z'
                  ' M21 21l-4.3-4.3'
                  ' M8 11h6',
    # fit / expand-arrows frame
    'fit':        'M3 8V5a2 2 0 0 1 2-2h3'
                  ' M16 3h3a2 2 0 0 1 2 2v3'
                  ' M21 16v3a2 2 0 0 1-2 2h-3'
                  ' M8 21H5a2 2 0 0 1-2-2v-3',
    # counter-clockwise undo arrow
    'undo':       'M3 12a9 9 0 1 0 3-6.7L3 8'
                  ' M3 3v5h5',
    # clockwise redo arrow
    'redo':       'M21 12a9 9 0 1 1-3-6.7L21 8'
                  ' M21 3v5h-5',
    # import / upload arrow (arrow exits tray upward)
    'import':    'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'
                 ' M17 8l-5-5-5 5'
                 ' M12 3v12',
    # back arrow (left)
    'back':       'M19 12H5'
                  ' M12 19l-7-7 7-7',
    # speaker with sound waves
    'volume':     'M11 5L6 9H2v6h4l5 4z'
                  ' M19.07 4.93a10 10 0 0 1 0 14.14'
                  ' M15.54 8.46a5 5 0 0 1 0 7.07',
    # play triangle inside circle (edit page play button)
    'play_circle': 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z'
                   ' M10 8l6 4-6 4z',
    # pause two vertical bars
    'pause':      'M6 4h4v16H6z'
                  ' M14 4h4v16h-4z',

    # --- Section headers (7) ------------------------------------------
    # bar chart (difficulty gauge)
    'difficulty': 'M3 21h18'
                  ' M5 21V10'
                  ' M12 21V4'
                  ' M19 21v-7',
    # line chart with axes (stats)
    'stats':      'M3 3v18h18'
                  ' M7 16l4-6 4 3 5-7',
    # play in circle (playback section)
    'playback':   'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z'
                  ' M10 8l6 4-6 4z',
    # sparkle (denoise)
    'denoise':    'M12 3l1.6 6.4L20 11l-6.4 1.6L12 19l-1.6-6.4L4 11l6.4-1.6z'
                  ' M18 5l.5 1.5L20 7l-1.5.5L18 9l-.5-1.5L16 7l1.5-.5z',
    # sliders (sensitivity / tune) — three horizontal bars with knobs
    'sliders':    'M4 21v-7'
                  ' M4 10V3'
                  ' M12 21v-9'
                  ' M12 8V3'
                  ' M20 21v-5'
                  ' M20 12V3'
                  ' M1 14h6'
                  ' M9 8h6'
                  ' M17 16h6',
    # music notes on staff lines (sheet music)
    'sheet_music': 'M3 5h18'
                   ' M3 9h18'
                   ' M3 13h18'
                   ' M3 17h18'
                   ' M9 5v12'
                   ' M9 17a2 2 0 1 0 0-4'
                   ' M15 5v10'
                   ' M15 15a2 2 0 1 0 0-4',
    # grid of squares (piano roll)
    'piano_roll': 'M3 5h18v14H3z'
                  ' M3 9h18'
                  ' M3 13h18'
                  ' M8 5v14'
                  ' M14 5v14',
    # file with text (input card)
    'input':      'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z'
                  ' M14 3v5h5'
                  ' M9 13h6'
                  ' M9 17h6',

    # --- Status / misc (5) --------------------------------------------
    # checkmark
    'check':      'M20 6L9 17l-5-5',
    # warning triangle with exclamation
    'warning':    'M12 3L1 21h22z'
                  ' M12 9v4'
                  ' M12 17h.01',
    # info: 'i' in circle
    'info':       'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z'
                  ' M12 16v-4'
                  ' M12 8h.01',
    # error: X in circle
    'error':      'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z'
                  ' M15 9l-6 6'
                  ' M9 9l6 6',
    # single music note (input card icon)
    'music_note': 'M9 18a3 3 0 1 0 0-6 3 3 0 0 0 0 6z'
                  ' M9 12V4l10-2v10',

    # --- Brand (1) ----------------------------------------------------
    # PianoScribe monogram: stylized 'P' inside a circle.
    # Uses '||' so the outer ring and the P glyph render as two separate
    # <path> elements (also exercises the multi-path code path).
    'monogram':   'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z'
                  '||M9 17V7h3.5a3 3 0 0 1 0 6H9',
}


# ============================================================
#  CONVENIENCE HELPERS
# ============================================================
def get_icon(name: str) -> IconPainter:
    """Return an `IconPainter` for the given icon name.

    Raises
    ------
    KeyError
        If `name` is not present in the `ICONS` registry.
    """
    if name not in ICONS:
        raise KeyError(
            f"Unknown icon name: {name!r}. "
            f"Available ({len(ICONS)}): {sorted(ICONS.keys())}"
        )
    return IconPainter(ICONS[name])


def icon_pixmap(
    name: str,
    size: int = 24,
    color: object = None,
    theme_name: Optional[str] = None,
) -> "QPixmap":
    """Render a named icon to `QPixmap` (theme-aware by default)."""
    return get_icon(name).pixmap(color=color, size=size, theme_name=theme_name)


def icon(
    name: str,
    size: int = 24,
    color: object = None,
    theme_name: Optional[str] = None,
) -> "QIcon":
    """Render a named icon to `QIcon` (theme-aware by default)."""
    return get_icon(name).icon(color=color, size=size, theme_name=theme_name)


__all__ = [
    'IconPainter',
    'ICONS',
    'get_icon',
    'icon_pixmap',
    'icon',
]


# ============================================================
#  STANDALONE SMOKE ENTRYPOINT
# ============================================================
if __name__ == '__main__':  # pragma: no cover - manual smoke entrypoint
    import sys
    import xml.etree.ElementTree as ET

    expected = [
        'mic', 'piano', 'waveform', 'edit', 'sun', 'moon', 'settings',
        'play', 'stop', 'download', 'cursor', 'pencil', 'eraser',
        'minimize', 'maximize', 'close',
        'zoom_in', 'zoom_out', 'fit', 'undo', 'redo', 'import', 'back',
        'volume', 'play_circle', 'pause',
        'difficulty', 'stats', 'playback', 'denoise',
        'sheet_music', 'piano_roll', 'input',
        'check', 'warning', 'info', 'error', 'music_note', 'monogram',
    ]

    missing = [n for n in expected if n not in ICONS]
    assert not missing, f'missing icons: {missing}'
    print(f'total icons in registry: {len(ICONS)}')

    # Verify every icon produces a well-formed (parseable) SVG string.
    bad = []
    for name in ICONS:
        svg = get_icon(name).svg()
        try:
            ET.fromstring(svg)
        except ET.ParseError as exc:
            bad.append((name, str(exc)))
    assert not bad, f'icons with malformed SVG: {bad}'
    print(f'all {len(ICONS)} SVG strings parse as well-formed XML')

    # If PySide6 + QtSvg are available, also verify rendering works.
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtSvg import QSvgRenderer  # noqa: F401
        from PySide6.QtGui import QColor
    except ImportError:
        print('PySide6/QtSvg unavailable — skipping render test')
        sys.exit(0)

    app = QApplication.instance() or QApplication(sys.argv)

    for name in ['mic', 'monogram', 'sun', 'piano']:
        ic = icon(name, size=24)
        pm = ic.pixmap(24, 24)
        assert not pm.isNull(), f'{name}: pixmap is null'
        # larger size + explicit color
        pm2 = icon_pixmap(name, size=48, color=QColor('#FF00FF'))
        assert not pm2.isNull(), f'{name}: 48px pixmap is null'
    print('PySide6 render test OK (24px + 48px, default + explicit colors)')
