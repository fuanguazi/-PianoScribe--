# -*- coding: utf-8 -*-
"""
design_tokens.py — PianoScribe centralized design-token system.

This module is the SINGLE SOURCE OF TRUTH for visual design tokens used across
the PianoScribe PySide6 application. It is the foundation of a multi-stage UI
redesign — later stages (component refactor, theme switcher, motion system)
will import names and helpers from here, so the public API is intentionally
small and stable.

Token groups
------------
1. Color tokens (per-theme)
   A `ColorTokens` instance carries every legacy color key already present in
   `piano_app.THEMES` (so callers can be migrated incrementally) PLUS a set of
   new tokens:

     * Brand gradient — three-stop Royal Indigo → Violet → Pink gradient
       (`brand_gradient`, `brand_gradient_hover`, `brand_gradient_pressed`).
       Used for primary buttons, hero panels, brand accents.
     * Elevation shadows — `elevation_1/2/3` for cards, hover states, modals.
     * Skeleton loading — `skeleton_base`, `skeleton_shimmer` for placeholders.
     * Scrollbars, tooltips, segmented controls, ripple, empty states.

2. Typography tokens (theme-independent)
   A 9-level type scale (display, h1, h2, h3, body, caption, overline,
   stat_number, stat_number_sm). Each level exposes size_px, line_height_px,
   weight, letter_spacing_px and is_mono.

   Font family stacks:
     * Sans: 'HarmonyOS Sans', 'PingFang SC', 'Microsoft YaHei',
             'SF Pro Display', 'Segoe UI', 'Noto Sans CJK SC', 'sans-serif'
     * Mono: 'SF Mono', 'JetBrains Mono', 'Consolas', 'Menlo', 'monospace'

3. Spacing tokens — 4 / 8 / 12 / 16 / 20 / 24 / 32 / 48 / 64 px scale.

4. Radius tokens — 8 / 12 / 16 / 24 / 999 (pill).

5. Motion tokens — 120 / 200 / 320 ms durations + named easing curves
   mapping to `QEasingCurve`.

Public API
---------
    tokens(theme_name=None) -> TokenNamespace
    get_current_theme_name() -> str
    set_current_theme_name(name) -> None
    qcolor(hex_or_rgba) -> QColor
    qfont(level) -> QFont
    brand_gradient_qcolor_tuple(theme_name=None) -> (QColor, QColor, QColor)
    brand_gradient_css(theme_name=None, angle=135) -> str
    elevation_shadow_qss(elevation=1) -> str

Standalone usage
----------------
    cd app && python -c "
    from design_tokens import tokens
    print(tokens('light').color.accent)
    "
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt  # noqa: F401  (re-exported for downstream use)
from PySide6.QtGui import QColor, QFont


# ============================================================
#  LEGACY COLOR DICTIONARIES (extended with new tokens)
# ============================================================
# Values copied verbatim from `piano_app.THEMES` (lines 105-176) and extended
# with the new design tokens. Keeping the exact string formats means the
# tokens can be substituted directly into QSS templates.

_LIGHT_COLORS: Dict[str, object] = {
    # --- legacy keys (verbatim from piano_app.THEMES['light']) ---
    'bg': '#F5F5F7', 'card_bg': 'rgba(255, 255, 255, 0.90)', 'card_border': 'rgba(0, 0, 0, 0.04)',
    'text_primary': '#1D1D1F', 'text_secondary': '#86868B',
    'accent': '#3FA9C4', 'accent_hover': '#3595AE', 'accent_pressed': '#2B8095', 'accent_disabled': '#9FD0DC',
    'accent_glow': 'rgba(63, 169, 196, 0.25)', 'accent2': '#5BC8A8',
    'danger': '#FF3B30', 'danger_hover': '#E02E24', 'danger_pressed': '#C0241C', 'danger_disabled': '#FFB0AC',
    'success': '#34C759', 'success_hover': '#28A745', 'success_pressed': '#1E8A36', 'success_disabled': '#A0E3B0',
    'surface': 'rgba(255, 255, 255, 0.80)', 'surface_hover': 'rgba(245, 245, 247, 0.95)', 'surface_pressed': 'rgba(235, 235, 238, 0.90)', 'surface_disabled': 'rgba(240, 240, 243, 0.6)',
    'divider': 'rgba(0, 0, 0, 0.06)', 'border': 'rgba(0, 0, 0, 0.04)', 'input_bg': 'rgba(255, 255, 255, 0.85)', 'shadow': 'rgba(0, 0, 0, 0.04)',
    'glass_blur': '24px', 'glass_highlight': 'rgba(255, 255, 255, 0.6)', 'glass_shadow': 'rgba(0, 0, 0, 0.04)',
    'menubar_bg': 'rgba(255, 255, 255, 0.85)', 'status_bg': 'rgba(255, 255, 255, 0.85)', 'status_text': '#86868B',
    'progress_bg': 'rgba(0, 0, 0, 0.04)', 'slider_groove': 'rgba(0, 0, 0, 0.06)', 'slider_handle': '#3FA9C4',
    'diff_btn_border': 'rgba(0, 0, 0, 0.04)', 'diff_btn_text': '#86868B',
    'menu_hover_bg': 'rgba(63, 169, 196, 0.08)', 'menu_hover_text': '#3FA9C4',
    'sep_color': 'rgba(0, 0, 0, 0.04)', 'hint_text': '#8E8E93', 'label_disabled': '#C7C7CC',
    'roll_bg': '#1C1C1E', 'roll_grid': '#2C2C2E', 'roll_black_col': '#242426',
    'roll_title': '#E5E5EA', 'roll_hint': '#8E8E93', 'roll_card_bg': '#1C1C1E',
    'keyboard_bg': '#FFFFFF', 'keyboard_border': '#D1D1D6', 'keyboard_note_name': '#8E8E93',
    'keyboard_black_key': '#1C1C1E', 'keyboard_black_border': '#3A3A3C', 'keyboard_active': '#3FA9C4',
    'cursor_color': '#FF3B30', 'note_right': '#3FA9C4', 'note_left': '#FF9500',
    'note_active': '#34C759', 'note_vocal': '#FF9500',
    'sheet_bg': '#FFFFFF', 'sheet_card_bg': 'rgba(255, 255, 255, 0.90)',
    'card_hover_bg': 'rgba(63, 169, 196, 0.06)', 'card_hover_border': '#3FA9C4', 'card_normal_border': 'rgba(0, 0, 0, 0.04)',
    'card_title_text': '#1D1D1F', 'card_desc_text': '#86868B',
    'toggle_btn_bg': 'rgba(0, 0, 0, 0.03)', 'toggle_btn_hover': 'rgba(0, 0, 0, 0.06)', 'toggle_icon': '#1D1D1F',
    'page_bg': '#FFFFFF',
    'denoise_auto_bg': '#3FA9C4', 'denoise_manual_bg': 'rgba(245, 245, 247, 0.8)', 'denoise_manual_text': '#86868B',
    'denoise_manual_hover': 'rgba(235, 235, 238, 0.8)', 'denoise_disabled_bg': 'rgba(240, 240, 243, 0.6)',
    'denoise_disabled_handle': '#C7C7CC', 'denoise_disabled_subpage': '#C7C7CC',
    'zoom_btn_bg': 'rgba(255, 255, 255, 0.80)', 'zoom_btn_border': 'rgba(0, 0, 0, 0.04)', 'zoom_btn_text': '#86868B',
    'info_diff_level': '#D1D1D6', 'info_diff_name': '#8E8E93', 'info_diff_detail': '#86868B',
    'info_stats_text': '#1D1D1F',
    'back_btn_bg': 'rgba(255, 255, 255, 0.80)', 'back_btn_border': 'rgba(0, 0, 0, 0.04)', 'back_btn_text': '#1D1D1F',
    'audio_label_color': '#8E8E93', 'progress_label_color': '#86868B',

    # --- new tokens ---
    'brand_gradient': ('#7BB8E0', '#7BC8B8', '#8FD3A8'),  # 淡蓝 → 淡青绿 → 淡草绿
    'brand_gradient_hover': ('#92C8EC', '#92D6C8', '#A6DDBA'),
    'brand_gradient_pressed': ('#5FA0CC', '#5FB0A0', '#72BD90'),

    'elevation_1': 'rgba(0, 0, 0, 0.04)',   # soft shadow for cards
    'elevation_2': 'rgba(0, 0, 0, 0.08)',   # hover / floating
    'elevation_3': 'rgba(0, 0, 0, 0.12)',   # modals / toasts

    'skeleton_base': 'rgba(0, 0, 0, 0.05)',
    'skeleton_shimmer': 'rgba(255, 255, 255, 0.6)',

    'scrollbar_bg': 'rgba(0, 0, 0, 0.0)',
    'scrollbar_handle': 'rgba(0, 0, 0, 0.20)',
    'scrollbar_handle_hover': 'rgba(0, 0, 0, 0.35)',

    'tooltip_bg': 'rgba(28, 28, 30, 0.95)',
    'tooltip_text': '#F5F5F7',
    'tooltip_border': 'rgba(255, 255, 255, 0.10)',

    'segment_active_bg': '#3FA9C4',
    'segment_active_text': '#FFFFFF',
    'segment_inactive_bg': 'rgba(255, 255, 255, 0.80)',
    'segment_inactive_text': '#86868B',

    'ripple_color': 'rgba(255, 255, 255, 0.30)',         # primary (on accent bg)
    'ripple_color_secondary': 'rgba(0, 0, 0, 0.08)',    # secondary (on surface bg)

    'empty_state_icon': 'rgba(0, 0, 0, 0.15)',
    'empty_state_text': '#86868B',

    'mono_font_color': '#1D1D1F',
}

_DARK_COLORS: Dict[str, object] = {
    # --- legacy keys (verbatim from piano_app.THEMES['dark']) ---
    'bg': '#000000', 'card_bg': 'rgba(28, 28, 30, 0.85)', 'card_border': 'rgba(255, 255, 255, 0.06)',
    'text_primary': '#F5F5F7', 'text_secondary': '#98989D',
    'accent': '#4FBFD8', 'accent_hover': '#69D0E6', 'accent_pressed': '#3AA8C0', 'accent_disabled': '#1A4F5A',
    'accent_glow': 'rgba(79, 191, 216, 0.3)', 'accent2': '#30D158',
    'danger': '#FF453A', 'danger_hover': '#FF6961', 'danger_pressed': '#E02E24', 'danger_disabled': '#5A2825',
    'success': '#30D158', 'success_hover': '#40E168', 'success_pressed': '#28B84C', 'success_disabled': '#1A4030',
    'surface': 'rgba(44, 44, 46, 0.75)', 'surface_hover': 'rgba(58, 58, 60, 0.85)', 'surface_pressed': 'rgba(72, 72, 74, 0.85)', 'surface_disabled': 'rgba(36, 36, 38, 0.5)',
    'divider': 'rgba(255, 255, 255, 0.06)', 'border': 'rgba(255, 255, 255, 0.04)', 'input_bg': 'rgba(44, 44, 46, 0.75)', 'shadow': 'rgba(0, 0, 0, 0.4)',
    'glass_blur': '24px', 'glass_highlight': 'rgba(255, 255, 255, 0.08)', 'glass_shadow': 'rgba(0, 0, 0, 0.4)',
    'menubar_bg': 'rgba(28, 28, 30, 0.85)', 'status_bg': 'rgba(28, 28, 30, 0.85)', 'status_text': '#98989D',
    'progress_bg': 'rgba(255, 255, 255, 0.06)', 'slider_groove': 'rgba(255, 255, 255, 0.08)', 'slider_handle': '#4FBFD8',
    'diff_btn_border': 'rgba(255, 255, 255, 0.06)', 'diff_btn_text': '#98989D',
    'menu_hover_bg': 'rgba(79, 191, 216, 0.15)', 'menu_hover_text': '#4FBFD8',
    'sep_color': 'rgba(255, 255, 255, 0.04)', 'hint_text': '#636366', 'label_disabled': '#48484A',
    'roll_bg': '#000000', 'roll_grid': '#1C1C1E', 'roll_black_col': '#0A0A0C',
    'roll_title': '#E5E5EA', 'roll_hint': '#636366', 'roll_card_bg': '#000000',
    'keyboard_bg': '#1C1C1E', 'keyboard_border': 'rgba(255, 255, 255, 0.06)', 'keyboard_note_name': '#98989D',
    'keyboard_black_key': '#000000', 'keyboard_black_border': 'rgba(255, 255, 255, 0.04)', 'keyboard_active': '#4FBFD8',
    'cursor_color': '#FF453A', 'note_right': '#4FBFD8', 'note_left': '#FF9F0A',
    'note_active': '#30D158', 'note_vocal': '#FF9F0A',
    'sheet_bg': '#1C1C1E', 'sheet_card_bg': 'rgba(28, 28, 30, 0.85)',
    'card_hover_bg': 'rgba(79, 191, 216, 0.12)', 'card_hover_border': '#4FBFD8', 'card_normal_border': 'rgba(255, 255, 255, 0.06)',
    'card_title_text': '#F5F5F7', 'card_desc_text': '#98989D',
    'toggle_btn_bg': 'rgba(255, 255, 255, 0.05)', 'toggle_btn_hover': 'rgba(255, 255, 255, 0.10)', 'toggle_icon': '#F5F5F7',
    'page_bg': '#000000',
    'denoise_auto_bg': '#4FBFD8', 'denoise_manual_bg': 'rgba(44, 44, 46, 0.75)', 'denoise_manual_text': '#98989D',
    'denoise_manual_hover': 'rgba(58, 58, 60, 0.85)', 'denoise_disabled_bg': 'rgba(36, 36, 38, 0.5)',
    'denoise_disabled_handle': '#48484A', 'denoise_disabled_subpage': '#48484A',
    'zoom_btn_bg': 'rgba(44, 44, 46, 0.75)', 'zoom_btn_border': 'rgba(255, 255, 255, 0.06)', 'zoom_btn_text': '#98989D',
    'info_diff_level': '#48484A', 'info_diff_name': '#98989D', 'info_diff_detail': '#98989D',
    'info_stats_text': '#F5F5F7',
    'back_btn_bg': 'rgba(44, 44, 46, 0.75)', 'back_btn_border': 'rgba(255, 255, 255, 0.06)', 'back_btn_text': '#F5F5F7',
    'audio_label_color': '#98989D', 'progress_label_color': '#98989D',

    # --- new tokens ---
    'brand_gradient': ('#5BA8C8', '#5BC8B8', '#6FD3A0'),  # 暗色模式下更亮的蓝绿渐变
    'brand_gradient_hover': ('#75BBDA', '#75D6C8', '#89DDB0'),
    'brand_gradient_pressed': ('#4790AC', '#47B0A0', '#5BBD8E'),

    'elevation_1': 'rgba(0, 0, 0, 0.30)',
    'elevation_2': 'rgba(0, 0, 0, 0.40)',
    'elevation_3': 'rgba(0, 0, 0, 0.50)',

    'skeleton_base': 'rgba(255, 255, 255, 0.06)',
    'skeleton_shimmer': 'rgba(255, 255, 255, 0.10)',

    'scrollbar_bg': 'rgba(0, 0, 0, 0.0)',
    'scrollbar_handle': 'rgba(255, 255, 255, 0.20)',
    'scrollbar_handle_hover': 'rgba(255, 255, 255, 0.35)',

    'tooltip_bg': 'rgba(245, 245, 247, 0.95)',
    'tooltip_text': '#1D1D1F',
    'tooltip_border': 'rgba(255, 255, 255, 0.10)',

    'segment_active_bg': '#4FBFD8',
    'segment_active_text': '#FFFFFF',
    'segment_inactive_bg': 'rgba(44, 44, 46, 0.75)',
    'segment_inactive_text': '#98989D',

    'ripple_color': 'rgba(255, 255, 255, 0.30)',         # primary (on accent bg)
    'ripple_color_secondary': 'rgba(255, 255, 255, 0.10)',  # secondary (on surface bg)

    'empty_state_icon': 'rgba(255, 255, 255, 0.15)',
    'empty_state_text': '#98989D',

    'mono_font_color': '#F5F5F7',
}


# ============================================================
#  COLOR TOKENS
# ============================================================
class ColorTokens:
    """Per-theme color tokens exposed as attributes.

    All legacy keys from `piano_app.THEMES` are present (so callers can be
    migrated one-by-one) along with the new design-system tokens (brand
    gradient, elevation, skeleton, scrollbar, tooltip, segmented control,
    ripple, empty-state, mono font color).

    Color strings keep the same format as the legacy THEMES dict
    (`'#RRGGBB'` or `'rgba(r, g, b, a)'`) so they can be substituted directly
    into QSS templates. Brand gradient values are 3-tuples of hex strings.
    """

    def __init__(self, color_dict: Dict[str, object]) -> None:
        for key, value in color_dict.items():
            # Brand gradient values are tuples; everything else is a string.
            setattr(self, key, value)

    def as_dict(self) -> Dict[str, object]:
        """Return a plain dict view of all color tokens."""
        return dict(self.__dict__)

    def keys(self) -> List[str]:
        return list(self.__dict__.keys())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ColorTokens(keys={len(self.__dict__)})"


# ============================================================
#  TYPOGRAPHY TOKENS
# ============================================================
class TypeLevel:
    """A single typography level."""

    __slots__ = ("size_px", "line_height_px", "weight", "letter_spacing_px", "is_mono")

    def __init__(
        self,
        size_px: int,
        line_height_px: int,
        weight: str,
        letter_spacing_px: float = 0.0,
        is_mono: bool = False,
    ) -> None:
        self.size_px = size_px
        self.line_height_px = line_height_px
        self.weight = weight
        self.letter_spacing_px = letter_spacing_px
        self.is_mono = is_mono

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"TypeLevel(size={self.size_px}px, lh={self.line_height_px}px, "
            f"weight={self.weight}, ls={self.letter_spacing_px}px, mono={self.is_mono})"
        )


# Font family stacks (Chinese + English fallback).
FONT_FAMILY_STACK: List[str] = [
    'HarmonyOS Sans',
    'PingFang SC',
    'Microsoft YaHei',
    'SF Pro Display',
    'Segoe UI',
    'Noto Sans CJK SC',
    'sans-serif',
]

MONO_FONT_FAMILY_STACK: List[str] = [
    'SF Mono',
    'JetBrains Mono',
    'Consolas',
    'Menlo',
    'monospace',
]


class Typography:
    """9-level type scale (theme-independent)."""

    display      = TypeLevel(40, 56, 'Bold',    1.0, is_mono=False)
    h1           = TypeLevel(28, 36, 'Bold',    0.0, is_mono=False)
    h2           = TypeLevel(20, 28, 'DemiBold', 0.2, is_mono=False)
    h3           = TypeLevel(16, 24, 'DemiBold', 0.2, is_mono=False)
    body         = TypeLevel(14, 20, 'Normal',  0.0, is_mono=False)
    caption      = TypeLevel(12, 16, 'Normal',  0.0, is_mono=False)
    overline     = TypeLevel(11, 14, 'Bold',    1.2, is_mono=False)  # uppercase
    stat_number  = TypeLevel(64, 72, 'Bold',    0.0, is_mono=True)
    stat_number_sm = TypeLevel(28, 36, 'Bold',  0.0, is_mono=True)

    @classmethod
    def get(cls, level: str) -> TypeLevel:
        """Look up a type level by name. Raises AttributeError if unknown."""
        attr = getattr(cls, level)
        if not isinstance(attr, TypeLevel):
            raise AttributeError(f"'{level}' is not a valid typography level")
        return attr

    @classmethod
    def levels(cls) -> List[str]:
        return [
            'display', 'h1', 'h2', 'h3', 'body',
            'caption', 'overline', 'stat_number', 'stat_number_sm',
        ]


# ============================================================
#  SPACING TOKENS
# ============================================================
class Spacing:
    """4-px based spacing scale (theme-independent)."""

    xs: int      = 4
    sm: int      = 8
    md: int      = 12
    lg: int      = 16
    xl: int      = 20
    xxl: int     = 24
    xxxl: int    = 32
    huge: int    = 48
    massive: int = 64


# ============================================================
#  RADIUS TOKENS
# ============================================================
class Radius:
    """Corner radius scale (theme-independent). `pill` = 999 (fully rounded)."""

    sm: int   = 8
    md: int   = 12
    lg: int   = 16
    xl: int   = 24
    pill: int = 999


# ============================================================
#  MOTION TOKENS
# ============================================================
class Motion:
    """Animation durations (ms) and named easing curves (theme-independent).

    Easing values are string names mapping to `QEasingCurve.Type` enum
    values — callers translate them via `MOTION_EASING_MAP`.
    """

    fast: int              = 120
    base: int              = 200
    slow: int              = 320
    easing_standard: str   = 'OutCubic'
    easing_emphasized: str = 'OutQuint'
    easing_decelerated: str = 'OutCubic'
    easing_accelerated: str = 'InCubic'


# Map easing-curve name strings to QEasingCurve.Type enum values.
# Defined lazily to avoid importing QEasingCurve at module top-level (which
# would pull in extra QtCore symbols). Importing here is fine.
from PySide6.QtCore import QEasingCurve

MOTION_EASING_MAP = {
    'OutCubic': QEasingCurve.OutCubic,
    'OutQuint': QEasingCurve.OutQuint,
    'InCubic':  QEasingCurve.InCubic,
    'InOutCubic': QEasingCurve.InOutCubic,
    'Linear':   QEasingCurve.Linear,
}

# Map typography weight name strings to QFont.Weight enum values.
_WEIGHT_MAP = {
    'Thin':     getattr(QFont, 'Thin', 0),
    'ExtraLight': getattr(QFont, 'ExtraLight', 12),
    'Light':    getattr(QFont, 'Light', 25),
    'Normal':   QFont.Normal,
    'Medium':    QFont.Medium,
    'DemiBold': QFont.DemiBold,
    'Bold':     QFont.Bold,
    'ExtraBold': getattr(QFont, 'ExtraBold', 81),
    'Black':    getattr(QFont, 'Black', 87),
}

# Letter-spacing enum on QFont. In PySide6 6.x both QFont.AbsoluteSpacing and
# QFont.SpacingType.AbsoluteSpacing resolve to the same integer.
try:
    _ABSOLUTE_SPACING = QFont.SpacingType.AbsoluteSpacing  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover - older PySide6 fallback
    _ABSOLUTE_SPACING = QFont.AbsoluteSpacing  # type: ignore[attr-defined]


# ============================================================
#  TOKEN NAMESPACE
# ============================================================
class TokenNamespace:
    """Aggregate of all token groups returned by `tokens()`."""

    __slots__ = ("color", "typography", "spacing", "radius", "motion", "theme_name")

    def __init__(
        self,
        color: ColorTokens,
        typography: Typography,
        spacing: Spacing,
        radius: Radius,
        motion: Motion,
        theme_name: str,
    ) -> None:
        self.color = color
        self.typography = typography
        self.spacing = spacing
        self.radius = radius
        self.motion = motion
        self.theme_name = theme_name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"TokenNamespace(theme='{self.theme_name}')"


# ============================================================
#  THEME-NAME SYNC (lazy, single source of truth in piano_app)
# ============================================================
# Local fallback when piano_app is not yet importable (e.g. during very early
# init or standalone tests). Production code reads `piano_app._current_theme_name`
# lazily at call time so state is never duplicated.
_cached_theme_name: str = 'light'


def get_current_theme_name() -> str:
    """Return 'light' or 'dark'.

    Reads `piano_app._current_theme_name` lazily so the token system stays in
    sync with the legacy theme switcher. Falls back to the cached local value
    when `piano_app` is not importable (early init / standalone use).
    """
    global _cached_theme_name
    try:
        import piano_app  # type: ignore[import]
        name = getattr(piano_app, '_current_theme_name', None)
        if name in ('light', 'dark'):
            _cached_theme_name = name
            return name
    except Exception:
        # Either the module isn't imported yet or attribute is missing —
        # fall through to the cached default.
        pass
    return _cached_theme_name


def set_current_theme_name(name: str) -> None:
    """Update the cached current theme.

    Writes through to `piano_app._current_theme_name` when possible so the
    legacy theme system observes the change. Does NOT trigger a UI refresh —
    the caller is responsible for re-polishing stylesheets.
    """
    global _cached_theme_name
    if name not in ('light', 'dark'):
        raise ValueError(f"Invalid theme name: {name!r} (expected 'light' or 'dark')")
    _cached_theme_name = name
    try:
        import piano_app  # type: ignore[import]
        piano_app._current_theme_name = name
    except Exception:
        # piano_app not yet importable — local cache is the source of truth.
        pass


# ============================================================
#  COLOR-TOKEN INSTANCES (cached per theme)
# ============================================================
_COLOR_TOKENS_CACHE: Dict[str, ColorTokens] = {}


def _color_tokens(theme_name: str) -> ColorTokens:
    """Return the cached `ColorTokens` instance for the given theme."""
    if theme_name not in _COLOR_TOKENS_CACHE:
        if theme_name == 'light':
            _COLOR_TOKENS_CACHE[theme_name] = ColorTokens(_LIGHT_COLORS)
        elif theme_name == 'dark':
            _COLOR_TOKENS_CACHE[theme_name] = ColorTokens(_DARK_COLORS)
        else:
            raise ValueError(f"Unknown theme: {theme_name!r}")
    return _COLOR_TOKENS_CACHE[theme_name]


# ============================================================
#  PUBLIC API
# ============================================================
def tokens(theme_name: Optional[str] = None) -> TokenNamespace:
    """Return the full token namespace for the given theme.

    Parameters
    ----------
    theme_name : str, optional
        'light' or 'dark'. If None, uses the current theme (see
        `get_current_theme_name`).

    Returns
    -------
    TokenNamespace
        Object with attributes:
            .color      -> ColorTokens   (all legacy + new color keys)
            .typography -> Typography    (9-level type scale)
            .spacing    -> Spacing        (4-px based scale)
            .radius     -> Radius         (8/12/16/24/999)
            .motion     -> Motion         (durations + easing names)
            .theme_name -> str            (the resolved theme name)
    """
    resolved = theme_name if theme_name is not None else get_current_theme_name()
    if resolved not in ('light', 'dark'):
        resolved = 'light'
    return TokenNamespace(
        color=_color_tokens(resolved),
        typography=Typography,
        spacing=Spacing,
        radius=Radius,
        motion=Motion,
        theme_name=resolved,
    )


def qcolor(hex_or_rgba: str) -> QColor:
    """Parse a color string into a `QColor`.

    Supports:
      * `'#RRGGBB'`  (also `'#RGB'`, `'#AARRGGBB'`, `'#RRGGBBAA'`)
      * `'rgb(r, g, b)'`              (alpha = 255)
      * `'rgba(r, g, b, a)'`          (a in [0, 1] or [0, 255])

    Whitespace and case are tolerated. Returns a copy of QColor each call so
    callers can mutate freely.
    """
    if not isinstance(hex_or_rgba, str):
        raise TypeError(f"qcolor() expects str, got {type(hex_or_rgba).__name__}")
    s = hex_or_rgba.strip()

    # Hex form — QColor parses '#RRGGBB' / '#AARRGGBB' / '#RRGGBBAA' natively.
    if s.startswith('#'):
        return QColor(s)

    # rgba(...) / rgb(...) form
    if s.lower().startswith('rgb'):
        open_paren = s.find('(')
        close_paren = s.rfind(')')
        if open_paren == -1 or close_paren == -1:
            raise ValueError(f"Malformed rgb() color: {hex_or_rgba!r}")
        inner = s[open_paren + 1:close_paren]
        parts = [p.strip() for p in inner.split(',') if p.strip()]
        if len(parts) < 3:
            raise ValueError(f"Malformed rgb() color: {hex_or_rgba!r}")
        try:
            r = int(parts[0])
            g = int(parts[1])
            b = int(parts[2])
        except ValueError as exc:
            raise ValueError(f"Non-integer RGB channel in {hex_or_rgba!r}") from exc
        alpha = 255
        if len(parts) >= 4 and parts[3] != '':
            a_str = parts[3]
            try:
                a_val = float(a_str)
            except ValueError as exc:
                raise ValueError(f"Invalid alpha in {hex_or_rgba!r}") from exc
            # Accept both 0-1 (CSS) and 0-255 (Qt) ranges.
            if 0.0 <= a_val <= 1.0:
                alpha = int(round(a_val * 255))
            elif 1.0 < a_val <= 255.0:
                alpha = int(round(a_val))
            else:
                alpha = max(0, min(255, int(round(a_val))))
        return QColor(r, g, b, alpha)

    # Last-resort: hand to QColor's parser (handles named colors like 'red').
    return QColor(s)


def qfont(level: str) -> QFont:
    """Build a `QFont` for the given typography level name.

    Parameters
    ----------
    level : str
        One of: 'display', 'h1', 'h2', 'h3', 'body', 'caption',
        'overline', 'stat_number', 'stat_number_sm'.

    Applies the appropriate family stack (sans or mono based on `is_mono`),
    pixel size, weight, and absolute letter spacing.

    Raises
    ------
    AttributeError
        If `level` is not a known typography level.
    """
    type_level = Typography.get(level)
    font = QFont()

    # Family stack — use the modern setFamilies() API so Qt falls back through
    # the list when a family is unavailable on the host system.
    family_stack = MONO_FONT_FAMILY_STACK if type_level.is_mono else FONT_FAMILY_STACK
    try:
        font.setFamilies(family_stack)
    except AttributeError:  # pragma: no cover - older PySide6 fallback
        font.setFamily(family_stack[0])

    # Weight
    weight_enum = _WEIGHT_MAP.get(type_level.weight, QFont.Normal)
    try:
        font.setWeight(weight_enum)
    except TypeError:
        # Older PySide6 expected an int.
        font.setWeight(int(weight_enum))

    # Size — pixel size keeps the type scale stable across screen DPI.
    font.setPixelSize(type_level.size_px)

    # Letter spacing (absolute px)
    if type_level.letter_spacing_px:
        try:
            font.setLetterSpacing(_ABSOLUTE_SPACING, float(type_level.letter_spacing_px))
        except Exception:
            # Some PySide6 versions reject the enum variant — silently ignore.
            pass

    return font


def brand_gradient_qcolor_tuple(
    theme_name: Optional[str] = None,
) -> Tuple[QColor, QColor, QColor]:
    """Return the 3-stop brand gradient as a `(QColor, QColor, QColor)` tuple."""
    resolved = theme_name if theme_name is not None else get_current_theme_name()
    if resolved not in ('light', 'dark'):
        resolved = 'light'
    gradient = _color_tokens(resolved).brand_gradient
    return (qcolor(gradient[0]), qcolor(gradient[1]), qcolor(gradient[2]))


def brand_gradient_css(
    theme_name: Optional[str] = None,
    angle: int = 135,
) -> str:
    """Return a QSS `qlineargradient(...)` string for the brand gradient.

    The angle is interpreted CSS-style: 0deg = bottom→top, 90deg = left→right,
    135deg = top-left→bottom-right (default). The function normalizes the
    direction vector so the gradient runs edge-to-edge.

    Example output for the light theme at 135deg::

        qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #6366F1, stop:0.5 #8B5CF6, stop:1 #EC4899)
    """
    resolved = theme_name if theme_name is not None else get_current_theme_name()
    if resolved not in ('light', 'dark'):
        resolved = 'light'
    gradient = _color_tokens(resolved).brand_gradient

    # Convert CSS gradient angle to a normalized direction vector in Qt's
    # coordinate space (y-axis points downward).
    rad = math.radians(angle)
    dx = math.sin(rad)
    dy = -math.cos(rad)
    m = max(abs(dx), abs(dy))
    if m > 0:
        dx /= m
        dy /= m

    # Anchor the gradient to the bounding-box edges so it spans the full
    # element regardless of aspect ratio.
    x1 = max(0.0, -dx)
    y1 = max(0.0, -dy)
    x2 = max(0.0, dx)
    y2 = max(0.0, dy)

    # Format floats compactly (avoid trailing zeros).
    def _fmt(v: float) -> str:
        s = f"{v:.4f}".rstrip('0').rstrip('.')
        return s if s else '0'

    return (
        f"qlineargradient(x1:{_fmt(x1)}, y1:{_fmt(y1)}, "
        f"x2:{_fmt(x2)}, y2:{_fmt(y2)}, "
        f"stop:0 {gradient[0]}, stop:0.5 {gradient[1]}, stop:1 {gradient[2]})"
    )


def elevation_shadow_qss(elevation: int = 1) -> str:
    """Return a parseable shadow descriptor for `QGraphicsDropShadowEffect`.

    PySide6 QSS does NOT support `box-shadow`, so callers must apply shadows
    via `QGraphicsDropShadowEffect`. This helper returns a comma-separated
    string of `offset_y, blur_radius, spread, color` that callers can split
    and feed into the effect, OR callers can read the `elevation_N` color
    tokens directly from `tokens(...).color`.

    Parameters
    ----------
    elevation : int
        1 (cards, default), 2 (hover / floating), or 3 (modals / toasts).

    Returns
    -------
    str
        e.g. ``'0,4,12,rgba(0, 0, 0, 0.04)'`` (light theme, elevation 1).
    """
    if elevation not in (1, 2, 3):
        elevation = 1
    color_attr = f'elevation_{elevation}'
    color_value = getattr(_color_tokens(get_current_theme_name()), color_attr)

    # Tuned (offset_y, blur_radius, spread) tuples per elevation level.
    _SHADOW_GEOMETRY = {
        1: (0, 4, 12),    # resting card
        2: (0, 8, 24),    # hover / floating
        3: (0, 16, 48),   # modal / toast
    }
    oy, blur, spread = _SHADOW_GEOMETRY[elevation]
    return f"{oy},{blur},{spread},{color_value}"


# ============================================================
#  MODULE-LEVEL CONVENIENCE ALIASES
# ============================================================
# Expose the static token classes at module level so callers can do either:
#     from design_tokens import Spacing, Radius
#     x = Spacing.md
# or:
#     from design_tokens import tokens
#     x = tokens('light').spacing.md
__all__ = [
    # Token classes
    'ColorTokens', 'TypeLevel', 'Typography',
    'Spacing', 'Radius', 'Motion', 'TokenNamespace',
    # Font stacks
    'FONT_FAMILY_STACK', 'MONO_FONT_FAMILY_STACK',
    # Easing / weight maps
    'MOTION_EASING_MAP', '_WEIGHT_MAP',
    # Public API
    'tokens', 'get_current_theme_name', 'set_current_theme_name',
    'qcolor', 'qfont', 'brand_gradient_qcolor_tuple',
    'brand_gradient_css', 'elevation_shadow_qss',
    # Legacy color dicts (read-only views for downstream introspection)
    '_LIGHT_COLORS', '_DARK_COLORS',
]


if __name__ == '__main__':  # pragma: no cover - manual smoke entrypoint
    _t = tokens('light')
    print('accent:', _t.color.accent)
    print('brand_gradient:', _t.color.brand_gradient)
    print('spacing.md:', _t.spacing.md)
    print('radius.lg:', _t.radius.lg)
    print('motion.base:', _t.motion.base)
    print('typography.display.size_px:', _t.typography.display.size_px)
    print('brand_gradient_css:', brand_gradient_css('light'))
    print('elevation_shadow_qss(1):', elevation_shadow_qss(1))
