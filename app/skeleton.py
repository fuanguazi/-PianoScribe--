# -*- coding: utf-8 -*-
"""
skeleton.py — pulsing gradient placeholder widgets for PianoScribe.

Provides:
  * `Skeleton`       — a single shimmering rounded-rect bar used as a
                        placeholder while real content loads (e.g. while
                        LilyPond is rendering a sheet, or while a MIDI file
                        is being analyzed).
  * `SkeletonSheet`  — a composite of multiple `Skeleton` bars arranged to
                        mimic a sheet-music layout (title bar + 5 staff lines
                        + scattered note blocks, repeated for each "system").
  * `make_skeleton`  — convenience factory.

Both widgets read their colors from `design_tokens.tokens(...)` so they
automatically adapt to the current theme. Call `refresh_theme()` after a
theme switch to re-read colors and repaint.

Animation uses `QPropertyAnimation` driving a custom `shimmerPos` Qt
property (0.0 -> 1.0) — the property setter calls `self.update()` so the
paintEvent redraws at ~60 fps without polling.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import (
    Property,
    QRectF,
    QPropertyAnimation,
    QEasingCurve,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import design_tokens


# ============================================================
#  Skeleton
# ============================================================
class Skeleton(QWidget):
    """A pulsing gradient placeholder bar.

    Visual: rounded rectangle filled with skeleton_base color, overlaid with a
    moving shimmer gradient (skeleton_shimmer) that sweeps left-to-right every
    1.5s. Used as a placeholder while real content loads.
    """

    # 1.5s shimmer sweep duration (matches the visual rhythm of common
    # Facebook / LinkedIn-style skeleton placeholders).
    _SWEEP_MS: int = 1500
    # Shimmer band width as a fraction of the bar width.
    _BAND_FRACTION: float = 0.4

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        width: Optional[int] = None,
        height: int = 16,
        radius: Optional[int] = None,
        animated: bool = True,
    ) -> None:
        """Build the skeleton. Sets fixed height; width can be flexible."""
        super().__init__(parent)

        self._height: int = max(1, int(height))
        self._width: Optional[int] = width
        # Radius is resolved lazily in paintEvent so refresh_theme() can pick
        # up the default from tokens() if the caller didn't override it.
        self._radius_override: Optional[int] = (
            int(radius) if radius is not None else None
        )

        # Cached QColor instances — refreshed from tokens.
        self._base_color: QColor = QColor(0, 0, 0, 13)
        self._shimmer_color: QColor = QColor(255, 255, 255, 153)
        self._load_colors()

        # Fixed height; width is flexible unless explicitly given.
        self.setFixedHeight(self._height)
        if self._width is not None:
            self.setFixedWidth(self._width)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Shimmer animation state.
        self._shimmer_pos: float = 0.0
        self._anim: QPropertyAnimation = QPropertyAnimation(self, b"shimmerPos")
        self._anim.setDuration(self._SWEEP_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

        if animated:
            self._anim.start()

    # ---------------- Qt property ----------------
    @Property(float)
    def shimmerPos(self) -> float:  # noqa: N802 — Qt API name
        return self._shimmer_pos

    @shimmerPos.setter
    def shimmerPos(self, value: float) -> None:
        self._shimmer_pos = float(value)
        self.update()

    # ---------------- Theme ----------------
    def _load_colors(self) -> None:
        """Read skeleton colors from design_tokens for the current theme."""
        t = design_tokens.tokens()
        self._base_color = design_tokens.qcolor(t.color.skeleton_base)
        self._shimmer_color = design_tokens.qcolor(t.color.skeleton_shimmer)

    def refresh_theme(self) -> None:
        """Re-read colors for the current theme and repaint."""
        self._load_colors()
        self.update()

    # ---------------- Animation control ----------------
    def start_animation(self) -> None:
        """Start the shimmer sweep animation (idempotent)."""
        if self._anim.state() != QPropertyAnimation.Running:
            self._anim.start()

    def stop_animation(self) -> None:
        """Stop the shimmer animation."""
        if self._anim.state() == QPropertyAnimation.Running:
            self._anim.stop()

    # ---------------- Painting ----------------
    def paintEvent(self, event) -> None:  # noqa: N802 — Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if r.width() <= 0.0 or r.height() <= 0.0:
            return

        # Resolve radius: explicit override > design_tokens default (sm).
        if self._radius_override is not None:
            radius = float(self._radius_override)
        else:
            radius = float(design_tokens.tokens().radius.sm)
        # Clamp so very small bars don't collapse into self-overlapping arcs.
        max_r = min(r.width(), r.height()) / 2.0
        radius = max(0.0, min(radius, max_r))

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.setClipPath(path)

        # Base fill.
        p.fillRect(r, self._base_color)

        # Shimmer band — `_BAND_FRACTION` of width, sweeping left -> right.
        band_w = r.width() * self._BAND_FRACTION
        if band_w <= 0.0:
            return
        x_start = -band_w
        x_end = r.width()
        x = x_start + (x_end - x_start) * self._shimmer_pos

        # Transparent edges -> opaque shimmer in the middle, for a soft band.
        transparent = QColor(self._shimmer_color)
        transparent.setAlpha(0)
        shimmer_grad = QLinearGradient(x, 0.0, x + band_w, 0.0)
        shimmer_grad.setColorAt(0.0, transparent)
        shimmer_grad.setColorAt(0.5, self._shimmer_color)
        shimmer_grad.setColorAt(1.0, transparent)
        p.fillRect(QRectF(x, 0.0, band_w, r.height()), shimmer_grad)


# ============================================================
#  SkeletonSheet
# ============================================================
class SkeletonSheet(QWidget):
    """A composite skeleton mimicking a sheet music layout.

    Layout: 5 horizontal "staff lines" (thin skeleton bars) + a "title bar" +
    a few "note blocks" scattered. Mimics the visual structure of sheet music
    so users see a recognizable placeholder while real sheet renders.
    """

    # Number of "staff systems" (a group of 5 staff lines + scattered notes).
    _N_SYSTEMS: int = 3
    # Staff line geometry.
    _STAFF_LINE_HEIGHT: int = 2
    _STAFF_LINE_GAP: int = 12
    _N_STAFF_LINES: int = 5
    # Note block geometry.
    _NOTE_SIZE: int = 8
    # Per-child stagger when starting the composite animation.
    _STAGGER_MS: int = 50

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Build the composite skeleton."""
        super().__init__(parent)
        # All child Skeleton widgets — used for start/stop/refresh fan-out.
        self._children: List[Skeleton] = []
        # Pending stagger timers — kept alive here so they fire even after
        # start_animation() returns.
        self._stagger_timers: List[QTimer] = []
        self._build()

    # ---------------- Layout ----------------
    def _build(self) -> None:
        t = design_tokens.tokens()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- Title bar (60% width, height 20) ---
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(0)
        title = Skeleton(
            height=20,
            radius=t.radius.sm,
            animated=False,
        )
        title_row.addWidget(title, 60)
        title_row.addStretch(40)
        outer.addLayout(title_row)
        self._children.append(title)

        outer.addSpacing(t.spacing.lg)

        # --- Staff systems ---
        for sys_idx in range(self._N_SYSTEMS):
            self._add_staff_system(outer)
            if sys_idx < self._N_SYSTEMS - 1:
                outer.addSpacing(t.spacing.xl)

        # Trailing stretch so the layout doesn't pin to the top.
        outer.addStretch(1)

    def _add_staff_system(self, outer_layout: QVBoxLayout) -> None:
        """Append one staff-line group + scattered notes to `outer_layout`."""
        # 5 thin horizontal "staff lines".
        for _ in range(self._N_STAFF_LINES):
            line = Skeleton(
                height=self._STAFF_LINE_HEIGHT,
                radius=1,
                animated=False,
            )
            outer_layout.addWidget(line)
            self._children.append(line)
            outer_layout.addSpacing(self._STAFF_LINE_GAP)

        # Notes row — small 8x8 rounded squares scattered via varying
        # stretch factors so they appear at irregular horizontal positions.
        notes_row = QHBoxLayout()
        notes_row.setContentsMargins(0, 0, 0, 0)
        notes_row.setSpacing(0)
        # (stretch_before, note_block_height) — heights vary slightly so the
        # row reads as a cluster of notes rather than a uniform grid.
        pattern = [(2, 8), (1, 8), (3, 8), (2, 8)]
        for stretch_before, note_h in pattern:
            notes_row.addStretch(stretch_before)
            note = Skeleton(
                width=self._NOTE_SIZE,
                height=note_h,
                radius=2,
                animated=False,
            )
            notes_row.addWidget(note)
            self._children.append(note)
        notes_row.addStretch(2)
        outer_layout.addLayout(notes_row)

    # ---------------- Animation control ----------------
    def start_animation(self) -> None:
        """Start all child skeleton animations (stagger by 50ms)."""
        # Cancel any pending stagger timers from a previous start.
        for timer in self._stagger_timers:
            timer.stop()
        self._stagger_timers.clear()

        for idx, child in enumerate(self._children):
            delay = idx * self._STAGGER_MS
            if delay <= 0:
                child.start_animation()
                continue
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(child.start_animation)
            timer.start(delay)
            self._stagger_timers.append(timer)

    def stop_animation(self) -> None:
        """Stop all child animations."""
        for timer in self._stagger_timers:
            timer.stop()
        self._stagger_timers.clear()
        for child in self._children:
            child.stop_animation()

    def refresh_theme(self) -> None:
        """Refresh all child skeletons."""
        for child in self._children:
            child.refresh_theme()


# ============================================================
#  Convenience factory
# ============================================================
def make_skeleton(
    width: Optional[int] = None,
    height: int = 16,
    radius: Optional[int] = None,
    animated: bool = True,
) -> Skeleton:
    """Convenience factory for a `Skeleton` widget."""
    return Skeleton(
        width=width,
        height=height,
        radius=radius,
        animated=animated,
    )


__all__ = ["Skeleton", "SkeletonSheet", "make_skeleton"]
