# -*- coding: utf-8 -*-
"""
toast.py — Toast notification widget + manager for the PianoScribe PySide6 app.

Renders floating, auto-dismissing toast notifications anchored to the
bottom-right of a parent window. Each toast shows a semantic-color left
accent bar, an icon, a bold title, and an optional caption message. Toasts
stack vertically (newest at the bottom) with an 8px gap, slide in/out from
the right edge, and fade in/out smoothly.

Public API
----------
    Toast                     — single toast notification widget (QFrame subclass)
    ToastManager              — manages a stack of toasts for a parent window
    get_toast_manager(parent) — singleton accessor (creates/rebinds manager)
    toast(level, title, ...)  — convenience: get_toast_manager().show(...)

Visual
------
- Rounded card with semi-transparent `card_bg` background and `card_border` border
- 4px-wide left accent bar in semantic color (success / info / warning / error)
- Drop shadow (elevation_3 token) for depth
- Width auto-fits content, clamped to [280, 420]px
- Height ~64px (title only) or ~80px (title + message)

Animations
----------
- Fade in:  opacity 0 -> 1, motion.fast (120ms), OutCubic
- Slide in: pos from off-right -> target, motion.base (200ms), OutQuint
- Fade out: opacity 1 -> 0, motion.fast (120ms), InCubic
- Slide out: pos -> off-right, motion.base, InCubic
- Fade + slide run as a parallel animation group

Theme support
-------------
- Reads `design_tokens.tokens()` lazily on each paint so theme switches take
  effect immediately. Call `ToastManager.refresh_theme()` to refresh all
  active toasts after a theme switch.
- Icons are loaded from `app_icons` (lazy import); falls back to a Unicode
  glyph if the module is unavailable.

Standalone
----------
The module imports only `design_tokens` + PySide6 + stdlib. If `app_icons`
doesn't exist at runtime, toasts render with Unicode fallback glyphs.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    QObject,
    QPoint,
    QRectF,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QEasingCurve,
    QTimer,
    Qt,
    Signal,
)  # noqa: F401  (QObject used as ToastManager base)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPaintEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

import design_tokens
from design_tokens import tokens, qcolor, qfont, get_current_theme_name


logger = logging.getLogger(__name__)


# ============================================================
#  CONSTANTS
# ============================================================
_LEVELS = ("success", "info", "warning", "error")

_ICON_NAMES = {
    "success": "check_circle",
    "info":    "info_circle",
    "warning": "alert_triangle",
    "error":   "alert_circle",
}

# Unicode fallback glyphs (drawn when app_icons is unavailable).
_FALLBACK_GLYPHS = {
    "success": "\u2713",  # CHECK MARK
    "info":    "\u2139",  # INFORMATION SOURCE
    "warning": "\u26A0",  # WARNING SIGN
    "error":   "\u2715",  # MULTIPLICATION X
}

# Layout constants (px). Pulled from the spec; kept as module-level so the
# manager and widget agree on geometry.
_TOAST_MIN_WIDTH = 280
_TOAST_MAX_WIDTH = 420
_MARGIN_RIGHT = 24
_MARGIN_BOTTOM = 24
_GAP = 8
_ACCENT_BAR_WIDTH = 4
_PADDING_LEFT = 12   # space between accent bar and icon
_PADDING_RIGHT = 12
_PADDING_TOP = 12
_PADDING_BOTTOM = 12
_ICON_SIZE = 20
_TITLE_TO_MESSAGE_GAP = 2
_SHADOW_PADDING = 16  # extra space around inner card for drop shadow

# No dedicated warning token in design_tokens yet — these are the standard
# Apple HIG / system-orange values used elsewhere in the app (note_vocal).
_WARNING_COLOR = {
    "light": "#FF9500",
    "dark":  "#FF9F0A",
}


def _level_color_str(level: str, theme_name: Optional[str] = None) -> str:
    """Return the semantic color token string for the given toast level."""
    t = tokens(theme_name)
    if level == "success":
        return t.color.success
    if level == "info":
        return t.color.accent
    if level == "warning":
        return _WARNING_COLOR.get(t.theme_name, _WARNING_COLOR["light"])
    if level == "error":
        return t.color.danger
    # Unknown — fall back to accent.
    return t.color.accent


# ============================================================
#  INNER CARD (paints rounded card + accent bar)
# ============================================================
class _ToastCard(QFrame):
    """Inner card widget. Paints the rounded background, accent bar, and
    border manually so the accent bar inherits the rounded left corners
    via clipping. Read tokens lazily on each paint so theme switches take
    effect immediately.
    """

    def __init__(self, parent: QWidget, level: str) -> None:
        super().__init__(parent)
        self._level = level
        # Avoid QSS background clobbering our manual paint.
        self.setAttribute(Qt.WA_StyledBackground, False)
        # Transparent so the rounded corner cutoffs show the parent.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("toastCard")

    def set_level(self, level: str) -> None:
        self._level = level
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        t = tokens()
        bg = qcolor(t.color.card_bg)
        border = qcolor(t.color.card_border)
        accent = qcolor(_level_color_str(self._level, t.theme_name))
        radius = float(t.radius.lg)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Card path (rounded rect, 0.5px inset for crisp 1px border).
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        # Layer 1: card background (semi-transparent — parent shows through).
        p.fillPath(path, bg)

        # Layer 2: accent bar (left edge, clipped to rounded card so its
        # left corners follow the card's curvature).
        p.save()
        p.setClipPath(path)
        bar_rect = QRectF(0.0, 0.0,
                          float(_ACCENT_BAR_WIDTH),
                          float(self.height()))
        p.fillRect(bar_rect, accent)
        p.restore()

        # Layer 3: 1px border.
        p.setPen(QPen(border, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


# ============================================================
#  TOAST WIDGET
# ============================================================
class Toast(QFrame):
    """A single toast notification. Auto-dismisses after ``duration_ms``.

    Visual: rounded card with semantic-color left border bar, icon, title,
    optional message. Floats above parent window content. Width auto-fits
    content (clamped to 280-420px).

    Lifecycle
    ---------
    - ``showEvent`` -> ``show_event``: starts fade-in + slide-in animation,
      then schedules the auto-dismiss timer (if ``duration_ms > 0``).
    - Click: dismiss immediately.
    - Hover: pauses auto-dismiss timer; resume on leave.
    - ``dismiss()``: plays fade-out + slide-out, then ``hide()`` +
      ``deleteLater()``.

    Animations
    ----------
    - Fade in/out: QGraphicsOpacityEffect on the outer Toast (so the
      entire subtree — inner card + drop shadow + text — fades together).
    - Slide in/out: QPropertyAnimation on ``pos`` of the outer Toast.
    - Combined via QParallelAnimationGroup.
    """

    # Emitted when the fade-out animation finishes (right before hide +
    # deleteLater). Useful for the manager to remove the toast from its
    # active list.
    dismissed = Signal(object)

    def __init__(self, parent: QWidget, level: str, title: str,
                 message: Optional[str] = None, duration_ms: int = 3000):
        if level not in _LEVELS:
            raise ValueError(
                f"Invalid toast level {level!r}; expected one of {_LEVELS}"
            )
        super().__init__(parent)

        self._level = level
        self._title = title
        self._message = message
        self._duration_ms = int(duration_ms)
        self._hovered = False
        self._dismiss_scheduled = False
        self._anim_group: Optional[QParallelAnimationGroup] = None
        self._fade_anim: Optional[QPropertyAnimation] = None
        self._slide_anim: Optional[QPropertyAnimation] = None

        # Auto-dismiss timer.
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)

        # Window flags — frameless, no system shadow, no focus, stays on
        # top within its parent.
        self.setWindowFlags(
            Qt.SubWindow
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMinimumWidth(_TOAST_MIN_WIDTH)
        self.setMaximumWidth(_TOAST_MAX_WIDTH)

        # Opacity effect on the outer Toast — fades the entire subtree.
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)  # start invisible; show_event fades in
        self.setGraphicsEffect(self._opacity_effect)

        # Inner card — paints rounded bg + accent bar; carries the drop
        # shadow effect so the shadow draws outside its bounds into the
        # outer Toast's _SHADOW_PADDING region.
        self._inner = _ToastCard(self, level)

        # NOTE: A separate QGraphicsDropShadowEffect on `_inner` would
        # conflict with the QGraphicsOpacityEffect on the outer Toast
        # (Qt only allows one effect per widget in the paint pipeline, and
        # the dual-effect composition triggers "A paint device can only be
        # painted by one painter at a time" warnings). Instead we paint
        # the shadow manually in Toast.paintEvent — see `_paint_shadow`.

        # Outer layout reserves _SHADOW_PADDING on all sides so the drop
        # shadow isn't clipped by the Toast's own bounds.
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(
            _SHADOW_PADDING, _SHADOW_PADDING,
            _SHADOW_PADDING, _SHADOW_PADDING,
        )
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self._inner)

        # Inner layout: HBox [icon] [content vbox]. Accent bar is painted
        # in _ToastCard.paintEvent so it inherits the rounded left corners.
        inner_layout = QHBoxLayout(self._inner)
        inner_layout.setContentsMargins(
            _ACCENT_BAR_WIDTH + _PADDING_LEFT,
            _PADDING_TOP,
            _PADDING_RIGHT,
            _PADDING_BOTTOM,
        )
        inner_layout.setSpacing(_PADDING_LEFT)

        # Icon (top-aligned so single-line and two-line toasts look balanced).
        self._icon_label = QLabel(self._inner)
        self._icon_label.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_label.setStyleSheet("background: transparent; border: none;")
        inner_layout.addWidget(self._icon_label, 0, Qt.AlignTop)

        # Content vbox: title + optional message.
        content_vbox = QVBoxLayout()
        content_vbox.setContentsMargins(0, 0, 0, 0)
        content_vbox.setSpacing(_TITLE_TO_MESSAGE_GAP)

        self._title_label = QLabel(title, self._inner)
        self._title_label.setFont(qfont("h3"))
        self._title_label.setWordWrap(False)
        self._title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        content_vbox.addWidget(self._title_label)

        if message:
            self._message_label = QLabel(message, self._inner)
            self._message_label.setFont(qfont("caption"))
            self._message_label.setWordWrap(True)
            self._message_label.setTextInteractionFlags(Qt.NoTextInteraction)
            content_vbox.addWidget(self._message_label)
        else:
            self._message_label = None

        inner_layout.addLayout(content_vbox)

        # Apply current theme colors + load icon.
        self._refresh_style()

    # ===========================================================
    #  PUBLIC API
    # ===========================================================

    def show_event(self) -> None:
        """On show: start fade-in + slide-in animation, then schedule
        the auto-dismiss timer for ``duration_ms`` (if > 0).

        The ToastManager positions the toast (via ``move()``) before
        calling ``show()``, so by the time ``showEvent`` fires the
        target position is already set on ``self.pos()``.
        """
        self._start_show_animation()
        if self._duration_ms > 0:
            self._dismiss_timer.start(self._duration_ms)

    def showEvent(self, event) -> None:  # type: ignore[override]
        # Qt hook -> our public show_event().
        self.show_event()
        super().showEvent(event)

    def dismiss(self) -> None:
        """Start fade-out + slide-out animation, then hide + deleteLater.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._dismiss_scheduled:
            return
        self._dismiss_scheduled = True
        # Cancel any pending auto-dismiss timer.
        self._dismiss_timer.stop()
        self._start_hide_animation()

    # ===========================================================
    #  PAINTING (manual drop shadow)
    # ===========================================================

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint a soft drop shadow around the inner card. The shadow is
        drawn manually (rather than via QGraphicsDropShadowEffect) so it
        composes cleanly with the QGraphicsOpacityEffect on the outer
        Toast — combining two graphics effects on parent + child triggers
        Qt's "A paint device can only be painted by one painter at a time"
        warnings.

        Approach: draw N layered rounded rects around the inner card with
        increasing size and decreasing alpha to approximate a Gaussian blur.
        """
        t = tokens()
        radius = float(t.radius.lg)

        # Shadow color from elevation_3 token; alpha clamped to 0.4 for
        # consistent visual weight across themes (light/dark tokens differ).
        shadow_color = qcolor(t.color.elevation_3)
        shadow_color.setAlphaF(0.4)

        # Inner card geometry (in Toast-local coords).
        inner_geom = self._inner.geometry()
        shadow_offset_y = 4
        shadow_blur = 12

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Draw layered expanding rounded rects, outermost first (so the
        # innermost — darkest — layer paints on top and creates a soft
        # falloff). Each layer's alpha follows a Gaussian-ish curve.
        for i in range(shadow_blur, 0, -1):
            alpha_f = 0.4 * ((1.0 - (i / shadow_blur)) ** 2)
            if alpha_f <= 0.0:
                continue
            color = QColor(shadow_color)
            color.setAlphaF(alpha_f)
            r = QRectF(inner_geom).adjusted(
                -float(i), -float(i) + shadow_offset_y,
                float(i), float(i) + shadow_offset_y,
            )
            path = QPainterPath()
            path.addRoundedRect(r, radius + i, radius + i)
            p.fillPath(path, color)

    # ===========================================================
    #  THEME / STYLING
    # ===========================================================

    def _refresh_style(self) -> None:
        """Re-apply colors from current theme tokens. Called on init and
        on theme switch (via ToastManager.refresh_theme()).
        """
        t = tokens()
        title_color = t.color.text_primary
        message_color = t.color.text_secondary
        self._title_label.setStyleSheet(
            f"color: {title_color}; background: transparent; border: none;"
        )
        if self._message_label is not None:
            self._message_label.setStyleSheet(
                f"color: {message_color}; background: transparent; border: none;"
            )
        # Reload icon (color depends on theme / level).
        self._load_icon()
        # Repaint card + manual shadow (Toast.paintEvent re-reads tokens).
        self.update()
        self._inner.update()

    # ===========================================================
    #  ICON LOADING
    # ===========================================================

    def _load_icon(self) -> None:
        """Load the icon from ``app_icons`` lazily; fall back to a Unicode
        glyph if the module is unavailable or the lookup fails.

        ``app_icons.get_pixmap(name, size, color, theme_name)`` is the
        expected signature; if the module exposes a different API or any
        exception is raised, we fall back gracefully.
        """
        color_str = _level_color_str(self._level)
        try:
            from app_icons import icon_pixmap  # type: ignore[import-not-found]
            pix = icon_pixmap(
                _ICON_NAMES[self._level],
                _ICON_SIZE,
                color_str,
                get_current_theme_name(),
            )
            if isinstance(pix, QPixmap) and not pix.isNull():
                self._icon_label.setPixmap(pix)
                self._icon_label.setText("")
                # Clear any color we set on the fallback label.
                self._icon_label.setStyleSheet(
                    "background: transparent; border: none;"
                )
                return
        except ImportError:
            logger.debug(
                "app_icons module not available; using Unicode fallback "
                "glyph %r for toast level %r.",
                _FALLBACK_GLYPHS.get(self._level), self._level,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to load toast icon %r: %s; using fallback glyph.",
                _ICON_NAMES[self._level], exc,
            )

        # Fallback: Unicode glyph colored via stylesheet.
        glyph = _FALLBACK_GLYPHS[self._level]
        font = QFont()
        font.setPixelSize(_ICON_SIZE)
        font.setBold(True)
        self._icon_label.setFont(font)
        self._icon_label.setPixmap(QPixmap())
        self._icon_label.setText(glyph)
        self._icon_label.setStyleSheet(
            f"color: {color_str}; background: transparent; border: none;"
        )

    # ===========================================================
    #  ANIMATIONS
    # ===========================================================

    def _off_right_point(self, y: int) -> QPoint:
        """A point just off the right edge of the parent window at height y."""
        parent = self.parent()
        if parent is not None:
            return QPoint(parent.width() + 8, y)
        return QPoint(self.x() + self.width() + 24, y)

    def _start_show_animation(self) -> None:
        """Fade-in (opacity 0->1, fast, OutCubic) + slide-in (off-right -> target, base, OutQuint)."""
        t = tokens()
        target = self.pos()
        start = self._off_right_point(target.y())

        # Move to start position so the slide-in runs from off-screen.
        self.move(start)

        # Fade
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(t.motion.fast)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Slide
        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(t.motion.base)
        self._slide_anim.setStartValue(start)
        self._slide_anim.setEndValue(target)
        self._slide_anim.setEasingCurve(QEasingCurve.OutQuint)

        # Combine
        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(self._fade_anim)
        self._anim_group.addAnimation(self._slide_anim)
        self._anim_group.start()

    def _start_hide_animation(self) -> None:
        """Fade-out (opacity 1->0, fast, InCubic) + slide-out (target -> off-right, base, InCubic)."""
        t = tokens()
        target_pos = self.pos()
        end = self._off_right_point(target_pos.y())

        # Fade
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(t.motion.fast)
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.InCubic)

        # Slide
        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(t.motion.base)
        self._slide_anim.setStartValue(target_pos)
        self._slide_anim.setEndValue(end)
        self._slide_anim.setEasingCurve(QEasingCurve.InCubic)

        # Combine — on finish, emit signal + cleanup.
        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(self._fade_anim)
        self._anim_group.addAnimation(self._slide_anim)
        self._anim_group.finished.connect(self._on_hide_finished)
        self._anim_group.start()

    def _on_hide_finished(self) -> None:
        """Called when the fade-out animation finishes — emit signal, hide,
        schedule deletion.
        """
        self.dismissed.emit(self)
        self.hide()
        self.setParent(None)
        self.deleteLater()

    # ===========================================================
    #  EVENT HANDLING
    # ===========================================================

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Click anywhere on the toast to dismiss immediately."""
        if event.button() == Qt.LeftButton:
            self.dismiss()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        """Pause auto-dismiss on hover."""
        self._hovered = True
        if self._dismiss_timer.isActive():
            self._dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        """Resume auto-dismiss on leave (restart with full duration)."""
        self._hovered = False
        if not self._dismiss_scheduled and self._duration_ms > 0:
            self._dismiss_timer.start(self._duration_ms)
        super().leaveEvent(event)


# ============================================================
#  TOAST MANAGER
# ============================================================
class ToastManager(QObject):
    """Manages a stack of toasts anchored to the bottom-right of a parent
    window.

    Multiple toasts stack vertically (newest at the bottom), 8px gap between
    them. Each toast slides in from the right and slides out to the right.
    When a toast is dismissed, toasts above it shift down to fill the gap.

    Anchored with 24px right margin and 24px bottom margin from the parent's
    content area. Repositions all toasts when the parent is resized.
    """

    def __init__(self, parent: QWidget) -> None:
        if parent is None:
            raise ValueError("ToastManager requires a non-None parent widget")
        super().__init__()  # QObject init
        self._parent: QWidget = parent
        self._active_toasts: List[Toast] = []
        # Hook parent's resize + close events via event filter.
        self._parent.installEventFilter(self)

    # ===========================================================
    #  PUBLIC API
    # ===========================================================

    def show(self, level: str, title: str, message: Optional[str] = None,
             duration_ms: int = 3000) -> Toast:
        """Create + show a new toast. Returns the toast widget for manual
        control (e.g. to call ``dismiss()`` early).
        """
        toast_widget = Toast(self._parent, level, title, message, duration_ms)
        # Force the toast to compute its proper sizeHint-based geometry
        # BEFORE _relayout() — otherwise toast.width()/height() return
        # the un-laid-out default size and all toasts stack on top of each
        # other at the same y coordinate.
        toast_widget.adjustSize()
        # Also resize explicitly to the sizeHint in case adjustSize() is
        # ignored (it can be for non-top-level widgets under some styles).
        hint = toast_widget.sizeHint()
        if hint.isValid() and not hint.isEmpty():
            toast_widget.resize(hint)
        # When the toast finishes its fade-out, remove it from the active
        # list and relayout the rest.
        toast_widget.dismissed.connect(self._on_toast_dismissed)
        self._active_toasts.append(toast_widget)
        # Position the toast at its target slot BEFORE show() so the
        # slide-in animation runs from off-screen to the correct target.
        self._relayout()
        toast_widget.show()
        # Ensure it's drawn on top of any other children of the parent
        # (central widget, status bar, etc.).
        toast_widget.raise_()
        return toast_widget

    def success(self, title: str, message: Optional[str] = None,
                duration_ms: int = 3000) -> Toast:
        return self.show("success", title, message, duration_ms)

    def info(self, title: str, message: Optional[str] = None,
             duration_ms: int = 3000) -> Toast:
        return self.show("info", title, message, duration_ms)

    def warning(self, title: str, message: Optional[str] = None,
                duration_ms: int = 3000) -> Toast:
        return self.show("warning", title, message, duration_ms)

    def error(self, title: str, message: Optional[str] = None,
              duration_ms: int = 5000) -> Toast:
        return self.show("error", title, message, duration_ms)

    def refresh_theme(self) -> None:
        """Re-apply current theme tokens to all active toasts. Call after
        a theme switch.
        """
        for toast in list(self._active_toasts):
            toast._refresh_style()

    @property
    def active_toasts(self) -> List[Toast]:
        """Snapshot of currently-active toasts (oldest first, newest last)."""
        return list(self._active_toasts)

    # ===========================================================
    #  LAYOUT
    # ===========================================================

    def _relayout(self) -> None:
        """Reposition all active toasts in the bottom-right of the parent.

        Newest toast (last in `_active_toasts`) goes at the bottom-right;
        older toasts stack above it. Uses instant ``move()`` here — the
        slide-in animation for newly-added toasts is started separately
        in ``Toast.show_event()``.
        """
        if not self._active_toasts:
            return
        parent_rect = self._parent.rect()
        right_edge = parent_rect.right() - _MARGIN_RIGHT
        bottom_edge = parent_rect.bottom() - _MARGIN_BOTTOM

        # Walk newest -> oldest, stacking upward.
        y = bottom_edge
        for toast in reversed(self._active_toasts):
            # Use the actual size; fall back to sizeHint() if the widget
            # hasn't been laid out yet (height = 0 or implausibly small).
            tw = toast.width()
            th = toast.height()
            if th <= 1:
                hint = toast.sizeHint()
                if hint.isValid() and not hint.isEmpty():
                    tw = hint.width()
                    th = hint.height()
                    toast.resize(tw, th)
            x = right_edge - tw
            target_y = y - th
            target_pos = QPoint(x, target_y)

            # If the toast is currently sliding in (show animation still
            # running), retarget its slide animation to the new position
            # so it ends up at the correct slot instead of the OLD slot
            # (which would otherwise override our move() once the
            # animation's endValue is reached).
            slide_anim = toast._slide_anim
            if (slide_anim is not None
                    and slide_anim.state() == QAbstractAnimation.Running):
                slide_anim.setEndValue(target_pos)
            else:
                # No running slide-in — just move instantly.
                toast.move(target_pos)

            y = target_y - _GAP

    def _on_parent_resized(self, event: QResizeEvent) -> None:
        """Hook the parent's resizeEvent to reposition toasts."""
        self._relayout()

    def _on_parent_closing(self) -> None:
        """Hide all toasts immediately (no animation) when the parent closes."""
        for toast in list(self._active_toasts):
            try:
                toast._dismiss_timer.stop()
                toast._dismiss_scheduled = True  # prevent re-entry
                # Cancel any running animations.
                if toast._anim_group is not None:
                    toast._anim_group.stop()
                toast.hide()
                toast.setParent(None)
                toast.deleteLater()
            except Exception:  # pragma: no cover - defensive
                pass
        self._active_toasts.clear()

    # ===========================================================
    #  EVENT FILTER (parent resize + close)
    # ===========================================================

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._parent:
            etype = event.type()
            if etype == QEvent.Resize:
                # Reposition toasts to the new bottom-right corner.
                self._on_parent_resized(event)  # type: ignore[arg-type]
            elif etype == QEvent.Close:
                self._on_parent_closing()
        return False  # don't consume the event

    # ===========================================================
    #  TOAST LIFECYCLE CALLBACKS
    # ===========================================================

    def _on_toast_dismissed(self, toast: Toast) -> None:
        """Called (via signal) when a toast's fade-out animation finishes.
        Removes it from the active list and slides the remaining toasts
        down to fill the gap.
        """
        try:
            self._active_toasts.remove(toast)
        except ValueError:
            # Already removed (e.g. parent close path) — fine.
            pass
        # Remaining toasts shift down — relayout instantly.
        self._relayout()


# ============================================================
#  SINGLETON ACCESSOR
# ============================================================
_MANAGER: Optional[ToastManager] = None


def get_toast_manager(parent: Optional[QWidget] = None) -> ToastManager:
    """Get or create the singleton ToastManager.

    - If no manager exists yet and ``parent`` is provided, creates one
      bound to that parent.
    - If a manager already exists and ``parent`` is provided, REBINDS the
      existing manager to the new parent (useful for theme / window
      changes).
    - If no manager exists and no parent is provided, raises RuntimeError.
    """
    global _MANAGER
    if _MANAGER is None:
        if parent is None:
            raise RuntimeError(
                "ToastManager has not been initialized yet — call "
                "get_toast_manager(parent_widget) first to bind it to a "
                "parent window."
            )
        _MANAGER = ToastManager(parent)
    elif parent is not None and _MANAGER._parent is not parent:
        # Rebind: detach event filter from old parent, attach to new one.
        try:
            _MANAGER._parent.removeEventFilter(_MANAGER)
        except Exception:  # pragma: no cover - defensive
            pass
        _MANAGER._parent = parent
        parent.installEventFilter(_MANAGER)
        _MANAGER._relayout()
    return _MANAGER


def toast(level: str, title: str, message: Optional[str] = None,
          duration_ms: int = 3000) -> Optional[Toast]:
    """Convenience: ``get_toast_manager().show(level, title, message, duration_ms)``.

    Returns None and logs a warning if no manager has been initialized yet
    (i.e. ``get_toast_manager(parent)`` was never called).
    """
    if _MANAGER is None:
        logger.warning(
            "toast() called before get_toast_manager(parent) — toast not "
            "shown. Initialize the manager first."
        )
        return None
    return _MANAGER.show(level, title, message, duration_ms)


__all__ = [
    "Toast",
    "ToastManager",
    "get_toast_manager",
    "toast",
]
