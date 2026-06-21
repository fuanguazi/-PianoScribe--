"""PianoScribe - Professional AI Piano Sheet Music Generator v8

Features:
- HarmonyOS 6.1 style UI (light theme, rounded cards, capsule buttons)
- Mode selection: Standard / Accompaniment / Vocal / Edit
- Professional staff notation (五线谱) rendering with LilyPond via SVG + QSvgRenderer
- Piano roll visualization with realistic 88-key keyboard (Synthesia-style)
- Editable piano roll (left-click delete, right-click add/drag notes)
- MIDI import/export in edit mode
- HarmonyOS 6.1 animations (hover, page transition, button bounce)
- MIDI playback with FluidSynth / additive synthesis
- Difficulty grading with button group selector
- Difficulty-linked playback (display + audio + export all simplified)
- Zoom, scroll, playback cursor
"""

import sys
import os

# 抑制 TensorFlow/oneDNN 信息输出
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
import shutil
import threading
import traceback
import wave
import tempfile
import time
import math
import re
import logging
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.path.dirname(sys.executable)

# Register FluidSynth DLL directory (Windows)
_fluidsynth_dll_dirs = [
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp', 'fluidsynth', 'bin'),
    r'C:\tools\fluidsynth-temp\bin',
]
for _dll_dir in _fluidsynth_dll_dirs:
    if os.path.isdir(_dll_dir):
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(_dll_dir)
        os.environ['PATH'] = _dll_dir + ';' + os.environ.get('PATH', '')

# 确保 pyfluidsynth 能找到 libfluidsynth DLL
try:
    import fluidsynth as _fs_check
except ImportError:
    pass

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QProgressBar,
    QSplitter, QMessageBox, QSlider, QFrame, QScrollArea,
    QButtonGroup, QSizePolicy, QStackedWidget, QGridLayout,
    QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QSplashScreen
)
from PySide6.QtCore import Qt, Signal, Slot, QObject, QTimer, QRectF, QPointF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (
    QFont, QColor, QPalette, QDragEnterEvent, QDropEvent,
    QPainter, QPen, QBrush, QWheelEvent, QMouseEvent,
    QPainterPath, QLinearGradient, QCursor, QRadialGradient, QPixmap
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene

import numpy as np
import pretty_midi

# ============================================================
#  THEME SYSTEM (Light / Dark dual-theme)
# ============================================================
_current_theme_name = 'light'

THEMES = {
    'light': {
        'bg': '#F5F5F7', 'card_bg': '#FFFFFF', 'card_border': 'rgba(0,0,0,0.06)',
        'text_primary': '#1D1D1F', 'text_secondary': '#86868B',
        'accent': '#007DFF', 'accent_hover': '#0066CC', 'accent_pressed': '#0055AA', 'accent_disabled': '#99C2FF',
        'danger': '#E84026', 'danger_hover': '#D03020', 'danger_pressed': '#B02818', 'danger_disabled': '#F0A090',
        'success': '#64BB5C', 'success_hover': '#50A848', 'success_pressed': '#409838', 'success_disabled': '#A0D8A0',
        'surface': '#FFFFFF', 'surface_hover': '#F5F5F5', 'surface_pressed': '#DCDCDC', 'surface_disabled': '#F0F0F0',
        'divider': '#E5E5EA', 'border': '#E0E0E0', 'input_bg': '#FFFFFF', 'shadow': 'rgba(0,0,0,0.08)',
        'menubar_bg': '#FFFFFF', 'status_bg': '#FFFFFF', 'status_text': '#AAAAAA',
        'progress_bg': '#E8E8E8', 'slider_groove': '#E0E0E0', 'slider_handle': '#007DFF',
        'diff_btn_border': '#E0E0E0', 'diff_btn_text': '#666666',
        'menu_hover_bg': '#F0F5FF', 'menu_hover_text': '#007DFF',
        'sep_color': '#F0F0F0', 'hint_text': '#BBBBBB', 'label_disabled': '#BBBBBB',
        'roll_bg': '#1A1A1A', 'roll_grid': '#2A2A2A', 'roll_black_col': '#222222',
        'roll_title': '#CCCCCC', 'roll_hint': '#666666', 'roll_card_bg': '#1A1A1A',
        'keyboard_bg': '#FFFFFF', 'keyboard_border': '#CCCCCC', 'keyboard_note_name': '#999999',
        'keyboard_black_key': '#1A1A1A', 'keyboard_black_border': '#333333', 'keyboard_active': '#007DFF',
        'cursor_color': '#E84026', 'note_right': '#007DFF', 'note_left': '#FF6B35',
        'note_active': '#64BB5C', 'note_vocal': '#FF6B35',
        'sheet_bg': '#FFFFFF', 'sheet_card_bg': '#FFFFFF',
        'card_hover_bg': '#E8F2FF', 'card_hover_border': '#007DFF', 'card_normal_border': '#E8E8E8',
        'card_title_text': '#333333', 'card_desc_text': '#888888',
        'toggle_btn_bg': 'rgba(0,0,0,0.05)', 'toggle_btn_hover': 'rgba(0,0,0,0.1)', 'toggle_icon': '#333333',
        'page_bg': '#F1F3F5',
        'denoise_auto_bg': '#007DFF', 'denoise_manual_bg': '#F0F0F0', 'denoise_manual_text': '#666666',
        'denoise_manual_hover': '#E0E0E0', 'denoise_disabled_bg': '#EEEEEE',
        'denoise_disabled_handle': '#BBBBBB', 'denoise_disabled_subpage': '#BBBBBB',
        'zoom_btn_bg': '#FFFFFF', 'zoom_btn_border': '#E0E0E0', 'zoom_btn_text': '#666666',
        'info_diff_level': '#CCCCCC', 'info_diff_name': '#999999', 'info_diff_detail': '#888888',
        'info_stats_text': '#333333',
        'back_btn_bg': '#FFFFFF', 'back_btn_border': '#E0E0E0', 'back_btn_text': '#333333',
        'audio_label_color': '#999999', 'progress_label_color': '#888888',
    },
    'dark': {
        'bg': '#0D0D1A', 'card_bg': '#1A1A2E', 'card_border': 'rgba(255,255,255,0.06)',
        'text_primary': '#F5F5F7', 'text_secondary': '#98989D',
        'accent': '#0A84FF', 'accent_hover': '#409CFF', 'accent_pressed': '#0066CC', 'accent_disabled': '#3A5A7C',
        'danger': '#FF453A', 'danger_hover': '#FF6961', 'danger_pressed': '#D03020', 'danger_disabled': '#6A3A38',
        'success': '#30D158', 'success_hover': '#40E070', 'success_pressed': '#28A045', 'success_disabled': '#2A4A35',
        'surface': '#1C1C2E', 'surface_hover': '#2A2A40', 'surface_pressed': '#353550', 'surface_disabled': '#252540',
        'divider': '#38383A', 'border': '#38383A', 'input_bg': '#252540', 'shadow': 'rgba(0,0,0,0.3)',
        'menubar_bg': '#1A1A2E', 'status_bg': '#1A1A2E', 'status_text': '#98989D',
        'progress_bg': '#38383A', 'slider_groove': '#38383A', 'slider_handle': '#0A84FF',
        'diff_btn_border': '#38383A', 'diff_btn_text': '#98989D',
        'menu_hover_bg': '#1A2040', 'menu_hover_text': '#0A84FF',
        'sep_color': '#2A2A40', 'hint_text': '#555570', 'label_disabled': '#555570',
        'roll_bg': '#0A0A18', 'roll_grid': '#1A1A2E', 'roll_black_col': '#151528',
        'roll_title': '#CCCCCC', 'roll_hint': '#666680', 'roll_card_bg': '#0A0A18',
        'keyboard_bg': '#1A1A2E', 'keyboard_border': '#38383A', 'keyboard_note_name': '#98989D',
        'keyboard_black_key': '#0A0A18', 'keyboard_black_border': '#2A2A40', 'keyboard_active': '#0A84FF',
        'cursor_color': '#FF453A', 'note_right': '#0A84FF', 'note_left': '#FF6B35',
        'note_active': '#30D158', 'note_vocal': '#FF6B35',
        'sheet_bg': '#1A1A2E', 'sheet_card_bg': '#1A1A2E',
        'card_hover_bg': '#1A2040', 'card_hover_border': '#0A84FF', 'card_normal_border': '#38383A',
        'card_title_text': '#F5F5F7', 'card_desc_text': '#98989D',
        'toggle_btn_bg': 'rgba(255,255,255,0.08)', 'toggle_btn_hover': 'rgba(255,255,255,0.15)', 'toggle_icon': '#F5F5F7',
        'page_bg': '#0D0D1A',
        'denoise_auto_bg': '#0A84FF', 'denoise_manual_bg': '#252540', 'denoise_manual_text': '#98989D',
        'denoise_manual_hover': '#353550', 'denoise_disabled_bg': '#252540',
        'denoise_disabled_handle': '#555570', 'denoise_disabled_subpage': '#555570',
        'zoom_btn_bg': '#1A1A2E', 'zoom_btn_border': '#38383A', 'zoom_btn_text': '#98989D',
        'info_diff_level': '#555570', 'info_diff_name': '#98989D', 'info_diff_detail': '#98989D',
        'info_stats_text': '#F5F5F7',
        'back_btn_bg': '#1A1A2E', 'back_btn_border': '#38383A', 'back_btn_text': '#F5F5F7',
        'audio_label_color': '#98989D', 'progress_label_color': '#98989D',
    }
}


def get_theme():
    return THEMES[_current_theme_name]


def get_stylesheet(theme_name=None):
    if theme_name is None:
        theme_name = _current_theme_name
    t = THEMES[theme_name]
    return f"""
QMainWindow {{ background-color: {t['bg']}; }}
QWidget {{ font-family: "HarmonyOS Sans", "Microsoft YaHei", "Segoe UI", sans-serif; color: {t['text_primary']}; }}
QGroupBox {{ background-color: {t['card_bg']}; border-radius: 16px; border: none; padding: 20px; }}
QFrame#cardFrame {{ background-color: {t['card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}
QPushButton {{ border-radius: 20px; padding: 8px 24px; font-size: 14px; background-color: {t['surface']}; border: 1px solid {t['border']}; color: {t['text_primary']}; min-height: 20px; }}
QPushButton:hover {{ background-color: {t['surface_hover']}; }}
QPushButton:pressed {{ background-color: {t['surface_pressed']}; }}
QPushButton:disabled {{ background-color: {t['surface_disabled']}; color: {t['label_disabled']}; border-color: {t['divider']}; }}
QPushButton#primary {{ background-color: {t['accent']}; color: white; border: none; }}
QPushButton#primary:hover {{ background-color: {t['accent_hover']}; }}
QPushButton#primary:pressed {{ background-color: {t['accent_pressed']}; }}
QPushButton#primary:disabled {{ background-color: {t['accent_disabled']}; color: white; }}
QPushButton#btnPlay {{ background-color: {t['accent']}; color: white; border: none; border-radius: 20px; padding: 8px 20px; font-weight: bold; }}
QPushButton#btnPlay:hover {{ background-color: {t['accent_hover']}; }}
QPushButton#btnPlay:pressed {{ background-color: {t['accent_pressed']}; }}
QPushButton#btnPlay:disabled {{ background-color: {t['accent_disabled']}; color: white; }}
QPushButton#btnStop {{ background-color: {t['danger']}; color: white; border: none; border-radius: 20px; padding: 8px 20px; font-weight: bold; }}
QPushButton#btnStop:hover {{ background-color: {t['danger_hover']}; }}
QPushButton#btnStop:pressed {{ background-color: {t['danger_pressed']}; }}
QPushButton#btnStop:disabled {{ background-color: {t['danger_disabled']}; color: white; }}
QPushButton#btnExport {{ background-color: {t['success']}; color: white; border: none; border-radius: 20px; padding: 8px 20px; font-weight: bold; }}
QPushButton#btnExport:hover {{ background-color: {t['success_hover']}; }}
QPushButton#btnExport:pressed {{ background-color: {t['success_pressed']}; }}
QPushButton#btnExport:disabled {{ background-color: {t['success_disabled']}; color: white; }}
QPushButton#diffBtn {{ border-radius: 18px; padding: 6px 18px; font-size: 13px; background-color: {t['surface']}; border: 1.5px solid {t['diff_btn_border']}; color: {t['diff_btn_text']}; min-height: 18px; }}
QPushButton#diffBtn:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
QPushButton#diffBtnSelected {{ border-radius: 18px; padding: 6px 18px; font-size: 13px; background-color: {t['accent']}; color: white; border: none; font-weight: bold; min-height: 18px; }}
QPushButton#diffBtnSelected:hover {{ background-color: {t['accent_hover']}; }}
QProgressBar {{ border: none; border-radius: 4px; background-color: {t['progress_bg']}; height: 8px; text-align: center; font-size: 11px; color: {t['text_secondary']}; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t['accent']}, stop:1 #00C4FF); border-radius: 4px; }}
QSlider::groove:horizontal {{ border: none; height: 6px; background: {t['slider_groove']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {t['slider_handle']}; border: none; width: 18px; margin: -6px 0; border-radius: 9px; }}
QSlider::handle:horizontal:hover {{ background: {t['accent_hover']}; }}
QMenuBar {{ background-color: {t['menubar_bg']}; color: {t['text_primary']}; border-bottom: 1px solid {t['divider']}; padding: 2px; }}
QMenuBar::item {{ padding: 6px 16px; border-radius: 8px; }}
QMenuBar::item:selected {{ background-color: {t['surface_hover']}; }}
QMenu {{ background-color: {t['card_bg']}; color: {t['text_primary']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 8px; }}
QMenu::item {{ padding: 8px 24px; border-radius: 8px; }}
QMenu::item:selected {{ background-color: {t['menu_hover_bg']}; color: {t['menu_hover_text']}; }}
QStatusBar {{ background-color: {t['status_bg']}; color: {t['status_text']}; border-top: 1px solid {t['divider']}; font-size: 11px; }}
QSplitter::handle {{ background-color: {t['divider']}; width: 2px; }}
QScrollArea {{ border: none; }}
QLabel#cardTitle {{ font-size: 15px; font-weight: bold; color: {t['text_primary']}; padding: 0px; }}
QLabel#cardSubtitle {{ font-size: 12px; color: {t['text_secondary']}; }}
QLabel#statValue {{ font-size: 13px; color: {t['text_primary']}; }}
QPushButton#themeToggle {{ background-color: {t['toggle_btn_bg']}; border: none; border-radius: 16px; padding: 6px; font-size: 18px; color: {t['toggle_icon']}; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; }}
QPushButton#themeToggle:hover {{ background-color: {t['toggle_btn_hover']}; }}
"""

STYLESHEET = get_stylesheet()


# ============================================================
#  MODE CARD (HarmonyOS 6.1 style with hover animation)
# ============================================================
class ModeCard(QFrame):
    """A selectable mode card with icon, title, description and hover animation."""
    clicked = Signal(str)  # emits mode name

    _NORMAL_STYLE = None  # Deprecated - using _apply_normal_style()
    _HOVER_STYLE = None   # Deprecated - using _apply_hover_style()

    def __init__(self, icon, title, desc, mode_name, parent=None):
        super().__init__(parent)
        self.mode_name = mode_name
        self._hovered = False
        self.setFixedSize(220, 180)
        self._apply_normal_style()
        self.setCursor(QCursor(Qt.PointingHandCursor))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 20)
        layout.setSpacing(8)

        t = get_theme()

        # Icon
        self._icon_label = QLabel(icon)
        self._icon_label.setStyleSheet("font-size: 40px; border: none; background: transparent;")
        self._icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon_label)

        # Title
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {t['card_title_text']}; border: none; background: transparent;")
        self._title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title_label)

        # Description
        self._desc_label = QLabel(desc)
        self._desc_label.setStyleSheet(
            f"font-size: 12px; color: {t['card_desc_text']}; border: none; background: transparent;")
        self._desc_label.setAlignment(Qt.AlignCenter)
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)

        layout.addStretch()

    def _apply_normal_style(self):
        t = get_theme()
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {t['card_bg']};
                border-radius: 20px;
                border: 1px solid {t['card_normal_border']};
            }}
        """)

    def _apply_hover_style(self):
        t = get_theme()
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {t['card_hover_bg']};
                border-radius: 20px;
                border: 2.5px solid {t['card_hover_border']};
            }}
        """)

    def update_theme(self, theme_name):
        t = THEMES[theme_name]
        self._title_label.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {t['card_title_text']}; border: none; background: transparent;")
        self._desc_label.setStyleSheet(
            f"font-size: 12px; color: {t['card_desc_text']}; border: none; background: transparent;")
        if self._hovered:
            self._apply_hover_style()
        else:
            self._apply_normal_style()

    def enterEvent(self, event):
        self._hovered = True
        self._apply_hover_style()
        # Micro lift animation on hover
        geo = self.geometry()
        self._hover_anim = QPropertyAnimation(self, b"geometry")
        self._hover_anim.setDuration(150)
        self._hover_anim.setStartValue(geo)
        self._hover_anim.setEndValue(QRectF(geo.x(), geo.y() - 4, geo.width(), geo.height()).toRect())
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_normal_style()
        # Restore position on leave
        geo = self.geometry()
        self._leave_anim = QPropertyAnimation(self, b"geometry")
        self._leave_anim.setDuration(150)
        self._leave_anim.setStartValue(geo)
        self._leave_anim.setEndValue(QRectF(geo.x(), geo.y() + 4, geo.width(), geo.height()).toRect())
        self._leave_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._leave_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.mode_name)
        super().mousePressEvent(event)


# ============================================================
#  WORKER SIGNALS
# ============================================================
class WorkerSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(str)
    error = Signal(str)


class _SynthesisDoneBridge(QObject):
    """Bridge to emit synthesis-done signal from background thread to main thread."""
    done = Signal()


# Global singleton - must be created on main thread
_synthesis_bridge = _SynthesisDoneBridge()


# ============================================================
#  DIFFICULTY GRADING
# ============================================================
def grade_difficulty(midi_path):
    midi = pretty_midi.PrettyMIDI(midi_path)
    all_notes = []
    for inst in midi.instruments:
        all_notes.extend(inst.notes)
    if not all_notes:
        return 1, "No notes", "#888", "--"
    duration = midi.get_end_time()
    if duration <= 0:
        return 1, "Empty", "#888", "--"

    density = len(all_notes) / duration
    density_score = min(10, density / 8.0 * 10)

    starts = sorted([n.start for n in all_notes])
    max_sim = 0
    for t in starts[:200]:
        c = sum(1 for n in all_notes if n.start <= t + 0.05 and n.end >= t)
        max_sim = max(max_sim, c)
    poly_score = min(10, max_sim / 8.0 * 10)

    pitches = [n.pitch for n in all_notes]
    pitch_range = max(pitches) - min(pitches)
    range_score = min(10, pitch_range / 60.0 * 10)

    short_notes = sum(1 for n in all_notes if n.end - n.start < 0.1)
    short_ratio = short_notes / len(all_notes)
    rhythm_score = min(10, short_ratio * 20)

    sorted_notes = sorted(all_notes, key=lambda n: n.start)
    if len(sorted_notes) > 1:
        jumps = [abs(sorted_notes[i + 1].pitch - sorted_notes[i].pitch)
                 for i in range(len(sorted_notes) - 1)
                 if sorted_notes[i + 1].start - sorted_notes[i].start < 0.5]
        avg_jump = np.mean(jumps) if jumps else 0
    else:
        avg_jump = 0
    jump_score = min(10, avg_jump / 7.0 * 10)

    total = (density_score * 0.25 + poly_score * 0.20 + range_score * 0.15 +
             rhythm_score * 0.20 + jump_score * 0.20)
    level = max(1, min(10, int(round(total))))

    labels = {
        1: ("入门", "#64BB5C"), 2: ("初级", "#64BB5C"),
        3: ("初级+", "#8BC34A"), 4: ("中级", "#CDDC39"),
        5: ("中级+", "#FFC107"), 6: ("高级", "#FF9800"),
        7: ("高级+", "#FF5722"), 8: ("专业", "#E84026"),
        9: ("大师", "#9C27B0"), 10: ("超凡", "#673AB7")
    }
    name, color = labels.get(level, ("--", "#888"))
    detail = (f"密度 {density:.1f}音/秒\n"
              f"同时 {max_sim}键\n"
              f"音域 {pitch_range}半音\n"
              f"短音 {short_ratio:.0%}\n"
              f"跳跃 {avg_jump:.1f}半音")
    return level, name, color, detail


# ============================================================
#  NOTE SIMPLIFICATION BY DIFFICULTY
# ============================================================
def simplify_notes(all_notes, difficulty):
    """Simplify notes based on selected difficulty level."""
    if difficulty == '专业':
        return list(all_notes)

    sorted_notes = sorted(all_notes, key=lambda n: n['start'])

    if difficulty == '入门':
        result = []
        for n in sorted_notes:
            simultaneous = [x for x in sorted_notes
                            if abs(x['start'] - n['start']) < 0.05
                            and x['end'] > n['start']]
            if len(simultaneous) <= 1:
                result.append(n)
            else:
                highest = max(simultaneous, key=lambda x: x['pitch'])
                if n == highest and n not in result:
                    result.append(n)
        return result

    if difficulty == '初级':
        result = []
        for n in sorted_notes:
            simultaneous = [x for x in result
                            if abs(x['start'] - n['start']) < 0.05
                            and x['end'] > n['start']]
            if len(simultaneous) < 3:
                result.append(n)
        return result

    if difficulty == '中级':
        result = []
        for n in sorted_notes:
            if n['end'] - n['start'] < 0.05 and n['velocity'] < 40:
                continue
            simultaneous = [x for x in result
                            if abs(x['start'] - n['start']) < 0.05
                            and x['end'] > n['start']]
            if len(simultaneous) < 5:
                result.append(n)
        return result

    # 高级: 保留所有音符但删除velocity最低的20%
    if difficulty == '高级':
        if not all_notes:
            return []
        sorted_by_vel = sorted(all_notes, key=lambda n: n['velocity'])
        cutoff = int(len(sorted_by_vel) * 0.2)
        low_vel_set = set(id(n) for n in sorted_by_vel[:cutoff])
        return [n for n in all_notes if id(n) not in low_vel_set]

    return list(all_notes)


# ============================================================
#  SHEET MUSIC WIDGET (LilyPond + SVG + QSvgRenderer)
# ============================================================
class SheetMusicWidget(QGraphicsView):
    """Professional sheet music rendering using LilyPond → SVG → QSvgRenderer.
    Provides the same interface as the old VexFlow-based widget."""

    rendering_done = Signal()
    _svg_ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger('SheetMusicWidget')
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        self.midi_data = None
        self.all_notes = []
        self.display_notes = []
        self.glissandi = []
        self.duration = 0
        self.bpm = 120
        self._zoom = 1.0
        self.is_playing = False
        self.cursor_time = 0.0
        self.play_start_time = 0.0
        self.play_start_real = 0.0

        self.play_timer = QTimer(self)
        self.play_timer.setInterval(16)
        self.play_timer.timeout.connect(self._tick_cursor)

        # Cursor line overlay
        self._cursor_line = None

        # SVG pages
        self._svg_items = []
        self._svg_dir = None  # directory containing SVG pages

        # LilyPond paths
        self._lilypond_exe = os.path.join(
            APP_DIR,
            'lilypond-2.24.4', 'bin', 'lilypond.exe')

        self.setMinimumSize(400, 250)
        self._update_bg_style()

        # Connect signal for thread-safe SVG loading
        self._svg_ready.connect(self._load_svg_pages)

        # Track render thread for concurrency control
        self._render_thread = None

    def _update_bg_style(self):
        t = get_theme()
        self.setStyleSheet(f"background: {t['sheet_bg']};")

    def update_theme(self, theme_name):
        self._update_bg_style()

    @property
    def zoom(self):
        return self._zoom

    @zoom.setter
    def zoom(self, value):
        self._zoom = value
        self.resetTransform()
        self.scale(value, value)

    def load_midi(self, midi_path, difficulty='高级'):
        """Load MIDI file and render as sheet music via LilyPond."""
        self.midi_data = pretty_midi.PrettyMIDI(midi_path)
        self.all_notes = []
        for inst in self.midi_data.instruments:
            for n in inst.notes:
                self.all_notes.append({
                    'pitch': n.pitch,
                    'start': n.start,
                    'end': n.end,
                    'velocity': n.velocity
                })
        self.all_notes.sort(key=lambda n: n['start'])
        self.duration = self.midi_data.get_end_time()

        self.glissandi = []
        for inst in self.midi_data.instruments:
            if inst.pitch_bends:
                sorted_pbs = sorted(inst.pitch_bends, key=lambda pb: pb.time)
                if len(sorted_pbs) < 2:
                    continue
                seq_start = None
                seq_start_time = None
                for k, pb in enumerate(sorted_pbs):
                    if seq_start is None and pb.pitch != 0:
                        seq_start = pb
                        seq_start_time = pb.time
                    elif seq_start is not None and pb.pitch == 0:
                        self.glissandi.append({
                            'start_time': seq_start_time,
                            'end_time': pb.time,
                        })
                        seq_start = None
                        seq_start_time = None
                if seq_start is not None:
                    self.glissandi.append({
                        'start_time': seq_start_time,
                        'end_time': sorted_pbs[-1].time,
                    })

        # Estimate BPM
        self.bpm = 120
        tempo_changes = self.midi_data.get_tempo_changes()
        if len(tempo_changes[1]) > 0:
            self.bpm = float(tempo_changes[1][0])

        self.apply_difficulty(difficulty)
        self.reset_cursor()

        # Render via LilyPond in background thread
        self._render_lilypond(midi_path)

    def _render_lilypond(self, midi_path):
        """Convert MIDI to SVG via music21 + LilyPond (runs in background thread)."""
        # Wait for any previous render thread to finish
        if self._render_thread and self._render_thread.is_alive():
            self._render_thread.join(timeout=5)

        self._svg_dir = os.path.join(tempfile.gettempdir(), f'_piano_svg_{os.getpid()}')
        os.makedirs(self._svg_dir, exist_ok=True)

        # Run LilyPond compilation in background thread
        self._render_thread = threading.Thread(
            target=self._lilypond_worker,
            args=(midi_path,),
            daemon=True
        )
        self._render_thread.start()

    def _lilypond_worker(self, midi_path):
        """Background worker: MIDI → music21 → LilyPond → SVG."""
        import music21
        import subprocess
        import copy

        music21.environment.set('lilypondPath', self._lilypond_exe)

        # Parse MIDI with music21
        try:
            score = music21.converter.parse(midi_path)
        except Exception as e:
            self.logger.error(f'music21解析失败: {e}')
            return

        # Split into treble and bass parts for grand staff
        try:
            # Try to split at middle C (MIDI 60)
            treble_part = music21.stream.Part()
            treble_part.id = 'Treble'
            treble_part.insert(0, music21.clef.TrebleClef())

            bass_part = music21.stream.Part()
            bass_part.id = 'Bass'
            bass_part.insert(0, music21.clef.BassClef())

            # Get all notes from the score
            for elem in score.flatten().notes:
                elem_copy = copy.deepcopy(elem)
                if hasattr(elem_copy, 'pitch'):
                    if elem_copy.pitch.midi >= 60:
                        treble_part.append(elem_copy)
                    else:
                        bass_part.append(elem_copy)
                elif hasattr(elem_copy, 'pitches'):  # chord
                    if any(p.midi >= 60 for p in elem_copy.pitches):
                        treble_part.append(elem_copy)
                    else:
                        bass_part.append(elem_copy)

            # Create new score with grand staff
            new_score = music21.stream.Score()

            # Add time signature and tempo
            if score.flatten().getElementsByClass(music21.meter.TimeSignature):
                ts = score.flatten().getElementsByClass(music21.meter.TimeSignature)[0]
                treble_part.insert(0, copy.deepcopy(ts))
                bass_part.insert(0, copy.deepcopy(ts))
            else:
                treble_part.insert(0, music21.meter.TimeSignature('4/4'))
                bass_part.insert(0, music21.meter.TimeSignature('4/4'))

            # Add tempo marking
            tempo = music21.tempo.MetronomeMark(number=self.bpm)
            new_score.insert(0, tempo)

            new_score.insert(0, treble_part)
            new_score.insert(0, bass_part)
            score = new_score
        except Exception as e:
            self.logger.warning(f'大谱表分割失败，使用原始布局: {e}')

        # Write LilyPond file
        ly_base = os.path.join(self._svg_dir, 'score')
        ly_path = ly_base + '.ly'
        try:
            result_path = score.write('lilypond', fp=ly_base)
            # music21 may write without .ly extension - rename if needed
            if not os.path.exists(ly_path) and os.path.exists(result_path):
                os.rename(result_path, ly_path)
        except Exception as e:
            self.logger.error(f'LilyPond文件生成失败: {e}')
            return

        if not os.path.exists(ly_path):
            self.logger.error('.ly文件未生成')
            return

        # Post-process .ly file to add measure numbers and compact formatting
        ly_path = ly_base + '.ly'
        if os.path.exists(ly_path):
            try:
                with open(ly_path, 'r', encoding='utf-8') as f:
                    ly_content = f.read()
                # Add measure number engraver and compact layout (replace ALL \layout occurrences)
                # Use a replacement function to avoid re.sub interpreting backslashes
                # in the replacement string as regex escape sequences (e.g. \l, \c, \S)
                def _layout_replacer(m):
                    return (
                        '\\layout {\n'
                        '  \\context {\\Score \\override BarNumber.break-visibility = #end-of-line-invisible }\n'
                        '  \\context {\\Score barNumberVisibility = #(every-nth-bar-number-visible 1) }\n'
                        '  \\context {\\Score \\override SpacingSpanner.base-shortest-duration = #(ly:make-moment 1/16) }\n'
                        '  \\context {\\Score \\override SpacingSpanner.common-shortest-duration = #(ly:make-moment 1/8) }\n'
                    )
                ly_content = re.sub(r'\\layout\s*\{', _layout_replacer, ly_content)
                # Use smaller page size and tighter margins for more content per page
                if '\\paper' not in ly_content:
                    ly_content = ly_content.replace(
                        '\\header',
                        '\\paper {\n'
                        '  page-breaking = #ly:minimal-breaking\n'
                        '  system-system-spacing = #((padding . 4))\n'
                        '  top-margin = 10\n'
                        '  bottom-margin = 10\n'
                        '  left-margin = 10\n'
                        '  right-margin = 10\n'
                        '}\n\\header'
                    )
                with open(ly_path, 'w', encoding='utf-8') as f:
                    f.write(ly_content)
            except Exception as e:
                self.logger.warning(f'.ly文件后处理失败: {e}')

        # Compile with LilyPond
        try:
            result = subprocess.run(
                [self._lilypond_exe, '-dbackend=svg', '-dno-point-and-click',
                 '--output', ly_base, ly_path],
                capture_output=True, timeout=120,
                cwd=self._svg_dir
            )
            self.logger.info(f'LilyPond编译完成, exit={result.returncode}')
            if result.returncode != 0 and result.stderr:
                self.logger.warning(f'LilyPond错误: {result.stderr[:500]}')
        except Exception as e:
            self.logger.error(f'LilyPond编译失败: {e}')
            return

        # Load SVG pages on the main thread via signal
        self._svg_ready.emit()

    def _load_svg_pages(self):
        """Load all SVG pages into the scene."""
        self._scene.clear()
        self._svg_items.clear()
        self._cursor_line = None

        if not self._svg_dir:
            return

        # Find all SVG files (score-1.svg, score-2.svg, etc.)
        svg_files = sorted([
            f for f in os.listdir(self._svg_dir)
            if f.startswith('score-') and f.endswith('.svg')
        ], key=lambda f: int(f.split('-')[1].split('.')[0]))

        if not svg_files:
            # Try single-page output
            single = os.path.join(self._svg_dir, 'score.svg')
            if os.path.exists(single):
                svg_files = ['score.svg']

        y_offset = 0
        # Limit pages to avoid memory issues (load first 20 pages)
        max_pages = 20
        for svg_file in svg_files[:max_pages]:
            svg_path = os.path.join(self._svg_dir, svg_file)
            item = QGraphicsSvgItem(svg_path)
            if item.boundingRect().width() <= 0:
                continue
            item.setPos(0, y_offset)
            self._scene.addItem(item)
            self._svg_items.append(item)
            y_offset += item.boundingRect().height() + 20  # 20px gap between pages

        if len(svg_files) > max_pages:
            # Add a text item indicating more pages
            from PySide6.QtWidgets import QGraphicsTextItem
            more_text = QGraphicsTextItem(f"... 共 {len(svg_files)} 页，显示前 {max_pages} 页 ...")
            more_text.setPos(0, y_offset)
            self._scene.addItem(more_text)

        if self._svg_items:
            self.fitInView(self._scene.itemsBoundingRect(), Qt.KeepAspectRatio)
            self._zoom = self.transform().m11()
            self.rendering_done.emit()

    def apply_difficulty(self, difficulty):
        """Filter notes based on difficulty level."""
        self.display_notes = simplify_notes(self.all_notes, difficulty)

    def zoom_in(self):
        self.zoom = min(5.0, self._zoom * 1.2)

    def zoom_out(self):
        self.zoom = max(0.2, self._zoom / 1.2)

    def zoom_fit(self):
        if self._svg_items:
            self.fitInView(self._scene.itemsBoundingRect(), Qt.KeepAspectRatio)
            self._zoom = self.transform().m11()

    def start_playback(self):
        if not self.display_notes:
            return
        self.stop_playback()
        self.is_playing = True
        self.play_start_time = self.cursor_time
        self.play_start_real = time.time()
        self.play_timer.start()

    def stop_playback(self):
        self.is_playing = False
        self.play_timer.stop()
        # Remove cursor line
        if self._cursor_line:
            self._scene.removeItem(self._cursor_line)
            self._cursor_line = None

    def reset_cursor(self):
        """Reset cursor time to 0 and remove cursor line."""
        self.cursor_time = 0.0
        if self._cursor_line:
            self._scene.removeItem(self._cursor_line)
            self._cursor_line = None

    def _tick_cursor(self):
        if not self.is_playing:
            return
        elapsed = time.time() - self.play_start_real
        self.cursor_time = self.play_start_time + elapsed
        if self.cursor_time >= self.duration:
            self.cursor_time = self.duration
            self.stop_playback()

        if self._svg_items:
            # Cursor is a VERTICAL line sweeping left-to-right
            x_ratio = self.cursor_time / max(self.duration, 0.001)
            page_width = self._svg_items[0].boundingRect().width() if self._svg_items else 800
            cursor_x = x_ratio * page_width

            if self._cursor_line:
                self._scene.removeItem(self._cursor_line)

            # Vertical line spanning all pages
            t = get_theme()
            total_height = sum(item.boundingRect().height() + 20 for item in self._svg_items)
            self._cursor_line = self._scene.addLine(
                cursor_x, 0, cursor_x, total_height,
                QPen(QColor(t['cursor_color']), 2)
            )

            # Auto-scroll to cursor
            self.ensureVisible(cursor_x, 0, 100, 100)

    def wheelEvent(self, event):
        """Zoom with Ctrl+wheel, scroll otherwise."""
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.zoom = self._zoom * factor
        else:
            super().wheelEvent(event)


# ============================================================
#  PIANO ROLL WIDGET (Synthesia-style with real piano layout)
# ============================================================
class PianoRollWidget(QWidget):
    """Piano roll visualization with realistic 88-key keyboard at the bottom.
    Notes fall from top to the keyboard. Dark background."""

    # 88 keys: A0 (MIDI 21) to C8 (MIDI 108)
    MIDI_LOW = 21
    MIDI_HIGH = 108
    NUM_KEYS = 88

    # Which pitches are black keys (semitone offset within octave)
    BLACK_KEYS = {1, 3, 6, 8, 10}
    # White key semitone offsets: C=0, D=2, E=4, F=5, G=7, A=9, B=11
    WHITE_KEY_INDICES = [0, 2, 4, 5, 7, 9, 11]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger('PianoRollWidget')
        self.display_notes = []
        self.duration = 0
        self.cursor_time = 0.0
        self.is_playing = False
        self.zoom = 1.0
        self.scroll_y = 0.0  # vertical scroll in seconds
        self.track_info = {}  # note_index -> track_index (0=accomp, 1=vocal)

        self.keyboard_height = 60
        self.white_key_width = 22
        self.black_key_width = 14
        self.pixels_per_second = 80

        # Precompute key positions
        self._key_positions = {}  # pitch -> (x, is_white)
        self._total_width = 0
        self._compute_key_positions()

        self.play_timer = QTimer(self)
        self.play_timer.setInterval(16)
        self.play_timer.timeout.connect(self._tick)
        self.play_start_time = 0.0
        self.play_start_real = 0.0

        self.setMinimumSize(400, 200)
        self.setMouseTracking(True)
        self._drag_start = None
        self._drag_scroll_y = 0

    def _compute_key_positions(self):
        """Precompute x positions for all 88 keys using real piano layout."""
        self._key_positions = {}
        white_key_count = 0
        for pitch in range(self.MIDI_LOW, self.MIDI_HIGH + 1):
            note_in_octave = pitch % 12
            if note_in_octave not in self.BLACK_KEYS:
                # White key
                x = white_key_count * self.white_key_width
                self._key_positions[pitch] = (x, True)
                white_key_count += 1
            else:
                # Black key - position between surrounding white keys
                x = white_key_count * self.white_key_width - self.black_key_width // 2
                self._key_positions[pitch] = (x, False)
        self._total_width = white_key_count * self.white_key_width

    def _pitch_to_x(self, pitch):
        """Convert MIDI pitch to (x_position, is_white_key)."""
        if pitch in self._key_positions:
            return self._key_positions[pitch]
        # Fallback for out-of-range pitches
        return ((pitch - self.MIDI_LOW) * self.white_key_width * 7 // 12, True)

    def _is_black_key(self, pitch):
        return (pitch % 12) in self.BLACK_KEYS

    def _get_active_pitches(self):
        """Get set of pitches currently being played."""
        active = set()
        for note in self.display_notes:
            if note['start'] <= self.cursor_time <= note['end']:
                active.add(note['pitch'])
        return active

    def load_notes(self, notes, duration, track_info=None):
        self.display_notes = notes
        self.duration = duration
        self.track_info = track_info or {}
        self.cursor_time = 0
        self.scroll_y = 0
        self.update()

    def start_playback(self, start_time=0.0):
        self.is_playing = True
        self.play_start_time = start_time
        self.play_start_real = time.time()
        self.play_timer.start()

    def stop_playback(self):
        self.is_playing = False
        self.play_timer.stop()
        self.update()

    def set_cursor_time(self, t):
        self.cursor_time = t
        self.update()

    def _tick(self):
        if not self.is_playing:
            return
        elapsed = time.time() - self.play_start_real
        self.cursor_time = self.play_start_time + elapsed
        if self.cursor_time >= self.duration:
            self.cursor_time = self.duration
            self.stop_playback()
        # Auto-scroll: cursor line is at the keyboard top
        # scroll_y = cursor_time so notes at current time are at the keyboard
        self.scroll_y = self.cursor_time
        self.update()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.ControlModifier:
            if delta > 0:
                self.pixels_per_second = min(400, self.pixels_per_second * 1.2)
            else:
                self.pixels_per_second = max(20, self.pixels_per_second / 1.2)
        else:
            scroll_delta = delta / self.pixels_per_second * 0.3
            self.scroll_y = max(0, self.scroll_y - scroll_delta)
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.RightButton:
            self._drag_start = event.position().y()
            self._drag_scroll_y = self.scroll_y

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_start is not None:
            dy = self._drag_start - event.position().y()
            self.scroll_y = max(0, self._drag_scroll_y + dy / self.pixels_per_second)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_start = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if not painter.isActive():
            return  # Prevent "QPainter::begin: A paint device can only be painted by one painter"
        painter.setRenderHint(QPainter.Antialiasing)

        t = get_theme()

        w = self.width()
        h = self.height()
        kb_h = self.keyboard_height
        roll_h = h - kb_h

        # Scale factor: make total keyboard width fill the widget width
        scale_x = w / max(self._total_width, 1)

        # Dark background for roll area
        painter.fillRect(0, 0, w, roll_h, QColor(t['roll_bg']))

        # Keyboard background
        painter.fillRect(0, roll_h, w, kb_h, QColor(t['keyboard_bg']))

        pps = self.pixels_per_second
        active_pitches = self._get_active_pitches()

        # === Draw piano roll grid and notes ===
        # Clip to roll area
        painter.setClipRect(0, 0, w, roll_h)

        # Draw vertical grid lines for each white key (separating white key columns)
        for pitch in range(self.MIDI_LOW, self.MIDI_HIGH + 1):
            pos = self._pitch_to_x(pitch)
            x, is_white = pos
            x = int(x * scale_x)
            if is_white:
                # Light separator between white key columns
                pen = QPen(QColor(t['roll_grid']), 0.5)
                painter.setPen(pen)
                painter.drawLine(x, 0, x, roll_h)
            else:
                bw = int(self.black_key_width * scale_x)
                painter.fillRect(x, 0, bw, roll_h, QColor(t['roll_black_col']))

        # Draw note blocks using real piano layout
        for note_idx, note in enumerate(self.display_notes):
            pitch = note['pitch']
            start = note['start']
            end = note['end']

            pos = self._pitch_to_x(pitch)
            x, is_white = pos
            x = int(x * scale_x)

            if is_white:
                note_w = int(self.white_key_width * scale_x) - 2
                note_x = x + 1
            else:
                note_w = int(self.black_key_width * scale_x) - 2
                note_x = x + 1

            # Y: time flows from bottom (keyboard) upward
            # Notes at time T appear at y = roll_h - (T - scroll_y) * pps
            note_y_top = roll_h - (end - self.scroll_y) * pps
            note_y_bottom = roll_h - (start - self.scroll_y) * pps
            note_h_px = max(2, note_y_bottom - note_y_top)

            # Skip if not visible
            if note_y_bottom < 0 or note_y_top > roll_h:
                continue

            # Color: use track_info if available, otherwise pitch-based
            is_active = pitch in active_pitches and note['start'] <= self.cursor_time <= note['end']
            if is_active:
                color = QColor(t['note_active'])
            elif self.track_info:
                # Multi-track: track 0 (accomp) = blue, track 1 (vocal) = orange
                track_idx = self.track_info.get(note_idx, 0)
                if track_idx == 1:  # Vocal
                    color = QColor(t['note_vocal'])
                else:  # Accompaniment
                    color = QColor(t['note_right'])
            elif pitch >= 60:  # Right hand (treble)
                color = QColor(t['note_right'])
            else:  # Left hand (bass)
                color = QColor(t['note_left'])

            painter.fillRect(int(note_x), int(note_y_top),
                             note_w, int(note_h_px), color)

            # Slight border
            painter.setPen(QPen(color.darker(120), 0.5))
            painter.drawRect(int(note_x), int(note_y_top),
                             note_w, int(note_h_px))

        # Draw playback cursor line (red horizontal line at keyboard top)
        if self.cursor_time > 0 or self.is_playing:
            cursor_y = roll_h - (self.cursor_time - self.scroll_y) * pps
            if 0 <= cursor_y <= roll_h:
                pen = QPen(QColor(t['cursor_color']), 2)
                painter.setPen(pen)
                painter.drawLine(0, int(cursor_y), w, int(cursor_y))

        painter.setClipping(False)

        # === Draw 88-key piano keyboard at bottom ===
        self._draw_keyboard(painter, 0, roll_h, w, kb_h, active_pitches, scale_x)

    def _draw_keyboard(self, painter, x_offset, y_offset, width, height, active_pitches, scale_x=1.0):
        """Draw 88-key piano keyboard with realistic layout."""
        t = get_theme()
        black_key_height = int(height * 0.6)

        scaled_white_w = int(self.white_key_width * scale_x)
        scaled_black_w = int(self.black_key_width * scale_x)

        # First pass: draw white keys
        for pitch in range(self.MIDI_LOW, self.MIDI_HIGH + 1):
            pos = self._pitch_to_x(pitch)
            x, is_white = pos
            if not is_white:
                continue

            x = int(x * scale_x) + x_offset
            if x > width or x + scaled_white_w < 0:
                continue

            is_active = pitch in active_pitches
            if is_active:
                color = QColor(t['keyboard_active'])
            else:
                color = QColor(t['keyboard_bg'])

            painter.fillRect(x, y_offset, scaled_white_w, height, color)
            painter.setPen(QPen(QColor(t['keyboard_border']), 0.5))
            painter.drawRect(x, y_offset, scaled_white_w, height)

            # Note name on C keys
            if pitch % 12 == 0:
                painter.setPen(QColor(t['keyboard_note_name']) if not is_active else QColor('#FFFFFF'))
                font = QFont("Microsoft YaHei", max(6, min(8, scaled_white_w - 4)))
                painter.setFont(font)
                octave = pitch // 12 - 1
                painter.drawText(x, y_offset + height - 4, scaled_white_w, 14,
                                 Qt.AlignCenter, f"C{octave}")

        # Second pass: draw black keys (on top of white keys)
        for pitch in range(self.MIDI_LOW, self.MIDI_HIGH + 1):
            pos = self._pitch_to_x(pitch)
            x, is_white = pos
            if is_white:
                continue

            x = int(x * scale_x) + x_offset
            if x > width or x + scaled_black_w < 0:
                continue

            is_active = pitch in active_pitches
            if is_active:
                color = QColor(t['keyboard_active'])
            else:
                color = QColor(t['keyboard_black_key'])

            painter.fillRect(x, y_offset, scaled_black_w, black_key_height, color)
            painter.setPen(QPen(QColor(t['keyboard_black_border']), 0.5))
            painter.drawRect(x, y_offset, scaled_black_w, black_key_height)


# ============================================================
#  EDITABLE PIANO ROLL WIDGET
# ============================================================
class EditablePianoRollWidget(PianoRollWidget):
    """Piano roll with full editing capabilities: select, pencil, eraser tools,
    box selection, note move/resize, copy/paste, keyboard shortcuts."""

    # ── 编辑工具常量 ──
    SELECT = 0
    PENCIL = 1
    ERASER = 2

    # ── 信号 ──
    notes_changed = Signal()          # 音符被修改后发射
    notes_about_to_change = Signal()  # 音符修改前发射（用于撤销保存）
    selection_changed = Signal()      # 选中状态变化时发射
    note_hovered = Signal(int)        # 鼠标悬停音符索引变化时发射（-1=无）

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── 编辑工具 ──
        self._edit_tool = self.SELECT  # 0=选择, 1=铅笔, 2=橡皮

        # ── 吸附 ──
        self.snap_enabled = False
        self.snap_grid = 0.25  # 秒，60bpm的四分音符

        # ── 剪贴板 ──
        self._clipboard = []

        # ── 选中系统 ──
        self.selected_indices = set()

        # ── 悬停系统 ──
        self._hover_note_idx = -1

        # ── 拖拽状态 ──
        self._drag_mode = None  # None / 'move' / 'resize_top' / 'resize_bottom' / 'box_select'
        self._drag_start_pos = None
        self._drag_origins = {}  # idx -> original note dict（移动/缩放前快照）
        self._drag_resize_idx = None  # 正在缩放的音符索引
        self._drag_resize_orig = None  # 缩放前的原始音符
        self._box_select_start = None  # 框选起点
        self._box_select_rect = None  # 框选矩形 (QRectF)

        # ── 父类右键拖拽（非编辑模式下保留） ──
        self._right_drag_note_idx = None
        self._right_drag_start = None
        self._right_drag_orig_note = None

        self.setFocusPolicy(Qt.StrongFocus)

    # ================================================================
    #  属性
    # ================================================================
    @property
    def edit_tool(self):
        return self._edit_tool

    @edit_tool.setter
    def edit_tool(self, value):
        self._edit_tool = max(0, min(2, int(value)))
        self._update_cursor()
        self.update()

    # ================================================================
    #  辅助方法
    # ================================================================
    @staticmethod
    def get_note_name(pitch):
        """将 MIDI 音高转换为音名，如 C4, F#5。"""
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        octave = pitch // 12 - 1
        name = note_names[pitch % 12]
        return f"{name}{octave}"

    def _snap_time(self, t):
        """将时间吸附到网格。"""
        if self.snap_enabled and self.snap_grid > 0:
            return round(t / self.snap_grid) * self.snap_grid
        return t

    def _pos_to_pitch_time(self, pos):
        """将位置转换为 (pitch, time) 元组。"""
        w = self.width()
        h = self.height()
        kb_h = self.keyboard_height
        roll_h = h - kb_h
        scale_x = w / max(self._total_width, 1)
        pps = self.pixels_per_second

        x = pos.x()
        y = pos.y()

        # 从 y 计算时间
        t = self.scroll_y + (roll_h - y) / max(pps, 1)

        # 从 x 计算音高
        best_pitch = 60
        best_dist = float('inf')
        for pitch in range(self.MIDI_LOW, self.MIDI_HIGH + 1):
            px, is_white = self._pitch_to_x(pitch)
            px = int(px * scale_x)
            if is_white:
                kw = int(self.white_key_width * scale_x)
            else:
                kw = int(self.black_key_width * scale_x)
            center_x = px + kw / 2
            dist = abs(x - center_x)
            if dist < best_dist:
                best_dist = dist
                best_pitch = pitch

        return best_pitch, max(0.0, t)

    def _find_note_at(self, pos):
        """查找给定位置处的音符索引，返回索引或 None。"""
        w = self.width()
        h = self.height()
        kb_h = self.keyboard_height
        roll_h = h - kb_h
        scale_x = w / max(self._total_width, 1)
        pps = self.pixels_per_second

        x = pos.x()
        y = pos.y()

        if y >= roll_h:
            return None

        # 从后往前遍历，优先选中上层音符
        for note_idx in range(len(self.display_notes) - 1, -1, -1):
            note = self.display_notes[note_idx]
            pitch = note['pitch']
            start = note['start']
            end = note['end']

            px, is_white = self._pitch_to_x(pitch)
            px = int(px * scale_x)
            if is_white:
                note_w = int(self.white_key_width * scale_x) - 2
                note_x = px + 1
            else:
                note_w = int(self.black_key_width * scale_x) - 2
                note_x = px + 1

            note_y_top = roll_h - (end - self.scroll_y) * pps
            note_y_bottom = roll_h - (start - self.scroll_y) * pps

            if (note_x <= x <= note_x + note_w and
                    note_y_top <= y <= note_y_bottom):
                return note_idx

        return None

    def _find_note_edge_at(self, pos):
        """检测鼠标是否在音符边缘（用于缩放）。
        返回 (note_idx, 'top'|'bottom'|None)。
        top = 音符末端（时间大的），bottom = 音符始端（时间小的）。
        在钢琴卷帘中，top 在视觉上方，bottom 在视觉下方。
        """
        w = self.width()
        h = self.height()
        kb_h = self.keyboard_height
        roll_h = h - kb_h
        scale_x = w / max(self._total_width, 1)
        pps = self.pixels_per_second

        x = pos.x()
        y = pos.y()

        if y >= roll_h:
            return None, None

        for note_idx in range(len(self.display_notes) - 1, -1, -1):
            note = self.display_notes[note_idx]
            pitch = note['pitch']
            start = note['start']
            end = note['end']

            px, is_white = self._pitch_to_x(pitch)
            px = int(px * scale_x)
            if is_white:
                note_w = int(self.white_key_width * scale_x) - 2
                note_x = px + 1
            else:
                note_w = int(self.black_key_width * scale_x) - 2
                note_x = px + 1

            note_y_top = roll_h - (end - self.scroll_y) * pps
            note_y_bottom = roll_h - (start - self.scroll_y) * pps
            note_h_px = note_y_bottom - note_y_top

            if not (note_x <= x <= note_x + note_w and
                    note_y_top <= y <= note_y_bottom):
                continue

            # 检测是否在边缘 20% 区域
            edge_zone = max(4, note_h_px * 0.2)
            if y - note_y_top <= edge_zone:
                return note_idx, 'top'
            elif note_y_bottom - y <= edge_zone:
                return note_idx, 'bottom'
            else:
                return note_idx, None

        return None, None

    def _get_note_rect(self, note_idx):
        """获取音符在 widget 中的像素矩形 (x, y, w, h)。"""
        note = self.display_notes[note_idx]
        w = self.width()
        h = self.height()
        kb_h = self.keyboard_height
        roll_h = h - kb_h
        scale_x = w / max(self._total_width, 1)
        pps = self.pixels_per_second

        pitch = note['pitch']
        start = note['start']
        end = note['end']

        px, is_white = self._pitch_to_x(pitch)
        px = int(px * scale_x)
        if is_white:
            note_w = int(self.white_key_width * scale_x) - 2
            note_x = px + 1
        else:
            note_w = int(self.black_key_width * scale_x) - 2
            note_x = px + 1

        note_y_top = roll_h - (end - self.scroll_y) * pps
        note_y_bottom = roll_h - (start - self.scroll_y) * pps

        return note_x, note_y_top, note_w, note_y_bottom - note_y_top

    def _rebuild_track_info_after_delete(self, deleted_indices):
        """删除音符后重建 track_info，保留未删除音符的轨道信息。"""
        new_track_info = {}
        offset = 0
        sorted_deleted = sorted(deleted_indices)
        del_set = set(sorted_deleted)
        for old_idx in sorted(k for k in self.track_info if k not in del_set):
            while offset < len(sorted_deleted) and sorted_deleted[offset] < old_idx:
                offset += 1
            new_idx = old_idx - offset
            new_track_info[new_idx] = self.track_info[old_idx]
        self.track_info = new_track_info

    def _rebuild_track_info_after_sort(self, old_notes, old_track_info):
        """排序后重建 track_info：根据音符内容匹配旧索引。"""
        if not old_track_info:
            return
        # 构建旧音符到轨道的映射
        old_map = {}
        for idx, track in old_track_info.items():
            if idx < len(old_notes):
                n = old_notes[idx]
                key = (n['pitch'], round(n['start'], 6), round(n['end'], 6), n['velocity'])
                old_map[key] = track
        # 为新音符查找轨道
        new_track_info = {}
        for idx, n in enumerate(self.display_notes):
            key = (n['pitch'], round(n['start'], 6), round(n['end'], 6), n['velocity'])
            if key in old_map:
                new_track_info[idx] = old_map[key]
        self.track_info = new_track_info

    def _update_cursor(self):
        """根据当前工具和悬停状态更新鼠标光标。"""
        if self._edit_tool == self.SELECT:
            if self._hover_note_idx >= 0 and self._hover_note_idx in self.selected_indices:
                self.setCursor(QCursor(Qt.SizeAllCursor))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))
        elif self._edit_tool == self.PENCIL:
            if self._drag_mode == 'resize_top' or self._drag_mode == 'resize_bottom':
                self.setCursor(QCursor(Qt.SizeVerCursor))
            elif self._hover_note_idx >= 0 and self._drag_mode != 'resize_top' and self._drag_mode != 'resize_bottom':
                self.setCursor(QCursor(Qt.SizeAllCursor))
            else:
                self.setCursor(QCursor(Qt.CrossCursor))
        elif self._edit_tool == self.ERASER:
            self.setCursor(QCursor(Qt.PointingHandCursor))
        else:
            self.setCursor(QCursor(Qt.ArrowCursor))

    # ================================================================
    #  选中操作
    # ================================================================
    def _select_note(self, idx, additive=False):
        """选中音符，additive=True 时不取消其他选中。"""
        if additive:
            if idx in self.selected_indices:
                self.selected_indices.discard(idx)
            else:
                self.selected_indices.add(idx)
        else:
            self.selected_indices = {idx}
        self.selection_changed.emit()
        self.update()

    def _deselect_all(self):
        """取消所有选中。"""
        if self.selected_indices:
            self.selected_indices = set()
            self.selection_changed.emit()
            self.update()

    def _select_all(self):
        """全选。"""
        self.selected_indices = set(range(len(self.display_notes)))
        self.selection_changed.emit()
        self.update()

    def _notes_in_rect(self, rect):
        """返回与矩形相交的音符索引集合。"""
        result = set()
        for idx in range(len(self.display_notes)):
            nx, ny, nw, nh = self._get_note_rect(idx)
            # 检查矩形相交
            if (rect.x() < nx + nw and rect.x() + rect.width() > nx and
                    rect.y() < ny + nh and rect.y() + rect.height() > ny):
                result.add(idx)
        return result

    # ================================================================
    #  音符编辑操作
    # ================================================================
    def _add_note(self, pitch, start, end, velocity=80):
        """添加音符并保持排序。返回新音符的索引。"""
        new_note = {'pitch': pitch, 'start': start, 'end': end, 'velocity': velocity}
        self.notes_about_to_change.emit()
        old_notes = list(self.display_notes)
        old_track_info = dict(self.track_info)

        self.display_notes.append(new_note)
        self.display_notes.sort(key=lambda n: (n['start'], n['pitch']))
        self._rebuild_track_info_after_sort(old_notes, old_track_info)

        # 找到新音符的索引
        idx = self.display_notes.index(new_note)
        self.logger.info(f'编辑-新增音符: {self.get_note_name(pitch)}, start={start:.3f}, end={end:.3f}')
        self.update()
        self.notes_changed.emit()
        return idx

    def _delete_notes(self, indices):
        """删除指定索引的音符。"""
        if not indices:
            return
        self.notes_about_to_change.emit()
        sorted_indices = sorted(indices, reverse=True)
        for idx in sorted_indices:
            if 0 <= idx < len(self.display_notes):
                del self.display_notes[idx]
        self._rebuild_track_info_after_delete(indices)
        self.selected_indices -= set(indices)
        self.logger.info(f'编辑-删除 {len(indices)} 个音符')
        self.update()
        self.notes_changed.emit()

    def _move_selected_notes(self, dpitch, dtime):
        """移动选中音符的音高和时间偏移。"""
        if not self.selected_indices:
            return
        self.notes_about_to_change.emit()
        for idx in list(self.selected_indices):
            if 0 <= idx < len(self.display_notes):
                note = self.display_notes[idx]
                duration = note['end'] - note['start']
                new_pitch = max(self.MIDI_LOW, min(self.MIDI_HIGH, note['pitch'] + dpitch))
                new_start = max(0.0, note['start'] + dtime)
                new_start = self._snap_time(new_start)
                new_end = new_start + duration
                self.display_notes[idx] = {
                    'pitch': new_pitch,
                    'start': new_start,
                    'end': new_end,
                    'velocity': note['velocity']
                }
        # 排序并重建 track_info
        old_notes = list(self.display_notes)
        old_track_info = dict(self.track_info)
        self.display_notes.sort(key=lambda n: (n['start'], n['pitch']))
        self._rebuild_track_info_after_sort(old_notes, old_track_info)
        self.logger.info(f'编辑-移动音符: dpitch={dpitch}, dtime={dtime:.3f}')
        self.update()
        self.notes_changed.emit()

    def quantize_selected(self, grid_seconds=None):
        """将选中音符的起始时间量化到网格。"""
        if grid_seconds is None:
            grid_seconds = self.snap_grid
        if grid_seconds <= 0 or not self.selected_indices:
            return
        self.notes_about_to_change.emit()
        for idx in list(self.selected_indices):
            if 0 <= idx < len(self.display_notes):
                note = self.display_notes[idx]
                duration = note['end'] - note['start']
                new_start = round(note['start'] / grid_seconds) * grid_seconds
                new_start = max(0.0, new_start)
                self.display_notes[idx] = {
                    'pitch': note['pitch'],
                    'start': new_start,
                    'end': new_start + duration,
                    'velocity': note['velocity']
                }
        old_notes = list(self.display_notes)
        old_track_info = dict(self.track_info)
        self.display_notes.sort(key=lambda n: (n['start'], n['pitch']))
        self._rebuild_track_info_after_sort(old_notes, old_track_info)
        self.logger.info(f'编辑-量化 {len(self.selected_indices)} 个音符, grid={grid_seconds}')
        self.update()
        self.notes_changed.emit()

    # ================================================================
    #  复制/粘贴
    # ================================================================
    def _copy_selected(self):
        """复制选中音符到剪贴板。"""
        if not self.selected_indices:
            return
        notes = []
        min_start = min(self.display_notes[i]['start'] for i in self.selected_indices if i < len(self.display_notes))
        for idx in sorted(self.selected_indices):
            if idx < len(self.display_notes):
                note = self.display_notes[idx]
                notes.append({
                    'pitch': note['pitch'],
                    'start': note['start'] - min_start,
                    'end': note['end'] - min_start,
                    'velocity': note['velocity']
                })
        self._clipboard = notes
        self.logger.info(f'编辑-复制 {len(notes)} 个音符')

    def _paste_clipboard(self):
        """在当前光标时间位置粘贴剪贴板音符。"""
        if not self._clipboard:
            return
        self.notes_about_to_change.emit()
        old_notes = list(self.display_notes)
        old_track_info = dict(self.track_info)

        new_indices = []
        for cn in self._clipboard:
            new_note = {
                'pitch': cn['pitch'],
                'start': self._snap_time(cn['start'] + self.cursor_time),
                'end': cn['end'] + self.cursor_time,
                'velocity': cn['velocity']
            }
            self.display_notes.append(new_note)
            new_indices.append(len(self.display_notes) - 1)

        self.display_notes.sort(key=lambda n: (n['start'], n['pitch']))
        self._rebuild_track_info_after_sort(old_notes, old_track_info)

        # 选中新粘贴的音符
        self.selected_indices = set()
        for cn in self._clipboard:
            target = {
                'pitch': cn['pitch'],
                'start': self._snap_time(cn['start'] + self.cursor_time),
                'end': cn['end'] + self.cursor_time,
                'velocity': cn['velocity']
            }
            for idx, n in enumerate(self.display_notes):
                if (n['pitch'] == target['pitch'] and
                        abs(n['start'] - target['start']) < 0.001 and
                        abs(n['end'] - target['end']) < 0.001):
                    self.selected_indices.add(idx)
                    break

        self.logger.info(f'编辑-粘贴 {len(self._clipboard)} 个音符')
        self.selection_changed.emit()
        self.update()
        self.notes_changed.emit()

    def _cut_selected(self):
        """剪切选中音符。"""
        if not self.selected_indices:
            return
        self._copy_selected()
        self._delete_notes(self.selected_indices)

    # ================================================================
    #  鼠标事件
    # ================================================================
    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()

        # ── 右键拖拽滚动（保留父类行为） ──
        if event.button() == Qt.RightButton:
            self._drag_start = pos.y()
            self._drag_scroll_y = self.scroll_y
            event.accept()
            return

        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        # ── SELECT 工具 ──
        if self._edit_tool == self.SELECT:
            idx = self._find_note_at(pos)
            if idx is not None:
                if event.modifiers() & Qt.ControlModifier:
                    # Ctrl+点击：切换选中
                    self._select_note(idx, additive=True)
                else:
                    if idx not in self.selected_indices:
                        self._select_note(idx)
                    # 开始拖拽移动
                    self._drag_mode = 'move'
                    self._drag_start_pos = pos
                    self._drag_origins = {}
                    for si in self.selected_indices:
                        if si < len(self.display_notes):
                            self._drag_origins[si] = dict(self.display_notes[si])
                    self.notes_about_to_change.emit()
            else:
                # 点击空白区域：开始框选
                if not (event.modifiers() & Qt.ControlModifier):
                    self.selected_indices = set()
                self._drag_mode = 'box_select'
                self._box_select_start = pos
                self._box_select_rect = None
                self.selection_changed.emit()
            event.accept()
            return

        # ── PENCIL 工具 ──
        elif self._edit_tool == self.PENCIL:
            edge_idx, edge_type = self._find_note_edge_at(pos)
            if edge_idx is not None and edge_type is not None:
                # 在音符边缘：开始缩放
                self._drag_mode = 'resize_top' if edge_type == 'top' else 'resize_bottom'
                self._drag_resize_idx = edge_idx
                self._drag_resize_orig = dict(self.display_notes[edge_idx])
                self._drag_start_pos = pos
                self.notes_about_to_change.emit()
            elif edge_idx is not None:
                # 在音符中间：开始移动
                self._drag_mode = 'move'
                self._drag_start_pos = pos
                self.selected_indices = {edge_idx}
                self._drag_origins = {edge_idx: dict(self.display_notes[edge_idx])}
                self.selection_changed.emit()
                self.notes_about_to_change.emit()
            else:
                # 空白区域：添加音符
                pitch, t = self._pos_to_pitch_time(pos)
                t = self._snap_time(t)
                new_idx = self._add_note(pitch, t, t + 0.25, 80)
                self.selected_indices = {new_idx}
                self.selection_changed.emit()
            event.accept()
            return

        # ── ERASER 工具 ──
        elif self._edit_tool == self.ERASER:
            idx = self._find_note_at(pos)
            if idx is not None:
                self._delete_notes({idx})
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()

        # ── 右键拖拽滚动 ──
        if event.buttons() & Qt.RightButton and self._drag_start is not None:
            dy = self._drag_start - pos.y()
            self.scroll_y = max(0, self._drag_scroll_y + dy / self.pixels_per_second)
            self.update()
            event.accept()
            return

        # ── 框选 ──
        if self._drag_mode == 'box_select' and self._box_select_start is not None:
            x1 = min(self._box_select_start.x(), pos.x())
            y1 = min(self._box_select_start.y(), pos.y())
            x2 = max(self._box_select_start.x(), pos.x())
            y2 = max(self._box_select_start.y(), pos.y())
            self._box_select_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            # 实时更新选中
            self.selected_indices = self._notes_in_rect(self._box_select_rect)
            self.selection_changed.emit()
            self.update()
            event.accept()
            return

        # ── 移动音符 ──
        if self._drag_mode == 'move' and self._drag_start_pos is not None:
            dx = pos.x() - self._drag_start_pos.x()
            dy = pos.y() - self._drag_start_pos.y()

            w = self.width()
            scale_x = w / max(self._total_width, 1)
            pps = self.pixels_per_second

            # 垂直拖拽 = 时间偏移（y 向上 = 时间增大）
            dt = -dy / max(pps, 1)
            # 水平拖拽 = 音高偏移
            white_w = self.white_key_width * scale_x
            dp = round(dx / max(white_w, 1))

            if dt == 0 and dp == 0:
                event.accept()
                return

            for idx, orig in self._drag_origins.items():
                if idx < len(self.display_notes):
                    duration = orig['end'] - orig['start']
                    new_pitch = max(self.MIDI_LOW, min(self.MIDI_HIGH, orig['pitch'] + dp))
                    new_start = max(0.0, self._snap_time(orig['start'] + dt))
                    new_end = new_start + duration
                    self.display_notes[idx] = {
                        'pitch': new_pitch,
                        'start': new_start,
                        'end': new_end,
                        'velocity': orig['velocity']
                    }
            self.update()
            event.accept()
            return

        # ── 缩放音符 ──
        if self._drag_mode in ('resize_top', 'resize_bottom') and self._drag_resize_idx is not None:
            idx = self._drag_resize_idx
            if idx >= len(self.display_notes):
                event.accept()
                return

            dy = pos.y() - self._drag_start_pos.y()
            pps = self.pixels_per_second
            dt = -dy / max(pps, 1)

            orig = self._drag_resize_orig
            note = self.display_notes[idx]

            if self._drag_mode == 'resize_top':
                # 调整末端时间
                new_end = max(orig['start'] + 0.05, self._snap_time(orig['end'] + dt))
                self.display_notes[idx] = {
                    'pitch': note['pitch'],
                    'start': note['start'],
                    'end': new_end,
                    'velocity': note['velocity']
                }
            else:
                # 调整起始时间
                new_start = max(0.0, min(orig['end'] - 0.05, self._snap_time(orig['start'] + dt)))
                self.display_notes[idx] = {
                    'pitch': note['pitch'],
                    'start': new_start,
                    'end': note['end'],
                    'velocity': note['velocity']
                }
            self.update()
            event.accept()
            return

        # ── 悬停检测 ──
        old_hover = self._hover_note_idx
        if self._edit_tool == self.PENCIL:
            edge_idx, _ = self._find_note_edge_at(pos)
            self._hover_note_idx = edge_idx if edge_idx is not None else -1
        else:
            self._hover_note_idx = self._find_note_at(pos) or -1

        if self._hover_note_idx != old_hover:
            self.note_hovered.emit(self._hover_note_idx)
            self._update_cursor()
            # 更新工具提示
            if self._hover_note_idx >= 0 and self._hover_note_idx < len(self.display_notes):
                note = self.display_notes[self._hover_note_idx]
                dur = note['end'] - note['start']
                self.setToolTip(
                    f"{self.get_note_name(note['pitch'])}  "
                    f"起始: {note['start']:.3f}s  "
                    f"时长: {dur:.3f}s  "
                    f"力度: {note['velocity']}"
                )
            else:
                self.setToolTip('')
            self.update()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        pos = event.position()

        # ── 右键释放 ──
        if event.button() == Qt.RightButton:
            self._drag_start = None
            event.accept()
            return

        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return

        # ── 框选结束 ──
        if self._drag_mode == 'box_select':
            self._box_select_start = None
            self._box_select_rect = None
            self._drag_mode = None
            self.update()
            event.accept()
            return

        # ── 移动结束 ──
        if self._drag_mode == 'move':
            # 排序并重建 track_info
            old_notes = list(self.display_notes)
            old_track_info = dict(self.track_info)
            self.display_notes.sort(key=lambda n: (n['start'], n['pitch']))
            self._rebuild_track_info_after_sort(old_notes, old_track_info)
            # 更新选中索引
            self.selected_indices = set()
            for orig in self._drag_origins.values():
                for idx, n in enumerate(self.display_notes):
                    if (n['pitch'] == orig['pitch'] and
                            abs(n['start'] - orig['start']) < 0.001):
                        self.selected_indices.add(idx)
                        break
            self._drag_mode = None
            self._drag_origins = {}
            self._drag_start_pos = None
            self.logger.info('编辑-音符移动完成')
            self.selection_changed.emit()
            self.update()
            self.notes_changed.emit()
            event.accept()
            return

        # ── 缩放结束 ──
        if self._drag_mode in ('resize_top', 'resize_bottom'):
            if self._drag_resize_idx is not None and self._drag_resize_idx < len(self.display_notes):
                modified = self.display_notes[self._drag_resize_idx]
                self.logger.info(
                    f'编辑-缩放音符: {self.get_note_name(modified["pitch"])}, '
                    f'start={modified["start"]:.3f}, end={modified["end"]:.3f}'
                )
            self._drag_mode = None
            self._drag_resize_idx = None
            self._drag_resize_orig = None
            self._drag_start_pos = None
            self.update()
            self.notes_changed.emit()
            event.accept()
            return

        self._drag_mode = None
        super().mouseReleaseEvent(event)

    # ================================================================
    #  键盘事件
    # ================================================================
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        # Delete / Backspace: 删除选中音符
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_notes(self.selected_indices)
            event.accept()
            return

        # Ctrl+A: 全选
        if mods & Qt.ControlModifier and key == Qt.Key_A:
            self._select_all()
            event.accept()
            return

        # Ctrl+C: 复制
        if mods & Qt.ControlModifier and key == Qt.Key_C:
            self._copy_selected()
            event.accept()
            return

        # Ctrl+X: 剪切
        if mods & Qt.ControlModifier and key == Qt.Key_X:
            self._cut_selected()
            event.accept()
            return

        # Ctrl+V: 粘贴
        if mods & Qt.ControlModifier and key == Qt.Key_V:
            self._paste_clipboard()
            event.accept()
            return

        # Escape: 取消选中
        if key == Qt.Key_Escape:
            self._deselect_all()
            event.accept()
            return

        # 方向键：微调选中音符
        if self.selected_indices:
            if key == Qt.Key_Up:
                self._move_selected_notes(1, 0)
                event.accept()
                return
            elif key == Qt.Key_Down:
                self._move_selected_notes(-1, 0)
                event.accept()
                return
            elif key == Qt.Key_Right:
                self._move_selected_notes(0, 0.1)
                event.accept()
                return
            elif key == Qt.Key_Left:
                self._move_selected_notes(0, -0.1)
                event.accept()
                return

        super().keyPressEvent(event)

    # ================================================================
    #  绘制增强
    # ================================================================
    def paintEvent(self, event):
        # 先调用父类绘制
        super().paintEvent(event)

        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.Antialiasing)

        t = get_theme()
        w = self.width()
        h = self.height()
        kb_h = self.keyboard_height
        roll_h = h - kb_h

        painter.setClipRect(0, 0, w, roll_h)

        # ── 1. 框选矩形 ──
        if self._box_select_rect is not None:
            rect = self._box_select_rect
            fill_color = QColor(t.get('select_fill', '#3399FF'))
            fill_color.setAlpha(40)
            border_color = QColor(t.get('select_border', '#3399FF'))
            border_color.setAlpha(180)
            painter.fillRect(rect, fill_color)
            painter.setPen(QPen(border_color, 1.5, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

        # ── 2. 选中音符高亮边框 ──
        for idx in self.selected_indices:
            if 0 <= idx < len(self.display_notes):
                nx, ny, nw, nh = self._get_note_rect(idx)
                highlight = QColor(t.get('select_highlight', '#FFFF00'))
                painter.setPen(QPen(highlight, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(int(nx) - 1, int(ny) - 1, int(nw) + 2, int(nh) + 2)

        # ── 3. 悬停音符高亮 ──
        if 0 <= self._hover_note_idx < len(self.display_notes) and self._hover_note_idx not in self.selected_indices:
            nx, ny, nw, nh = self._get_note_rect(self._hover_note_idx)
            hover_color = QColor(255, 255, 255, 100)
            painter.setPen(QPen(QColor(255, 255, 255, 160), 1.5))
            painter.setBrush(hover_color)
            painter.drawRect(int(nx), int(ny), int(nw), int(nh))

        # ── 4. 缩放光标指示线（铅笔模式，悬停在音符边缘时） ──
        if self._edit_tool == self.PENCIL and self._hover_note_idx >= 0:
            edge_idx, edge_type = self._find_note_edge_at(self.mapFromGlobal(self.cursor().pos()))
            if edge_idx is not None and edge_type is not None:
                nx, ny, nw, nh = self._get_note_rect(edge_idx)
                indicator_y = int(ny) if edge_type == 'top' else int(ny + nh)
                pen = QPen(QColor(255, 255, 255, 200), 2)
                painter.setPen(pen)
                painter.drawLine(int(nx) - 2, indicator_y, int(nx + nw) + 2, indicator_y)

        painter.setClipping(False)
        painter.end()

    # ================================================================
    #  MIDI 文件操作
    # ================================================================
    def load_midi_file(self, midi_path):
        """加载 MIDI 文件进行编辑，保留多轨道信息。"""
        midi = pretty_midi.PrettyMIDI(midi_path)
        notes = []
        track_info = {}
        note_idx = 0
        for track_idx, inst in enumerate(midi.instruments):
            for n in inst.notes:
                notes.append({
                    'pitch': n.pitch,
                    'start': n.start,
                    'end': n.end,
                    'velocity': n.velocity
                })
                track_info[note_idx] = track_idx
                note_idx += 1
        notes.sort(key=lambda n: (n['start'], n['pitch']))
        duration = midi.get_end_time()
        self.load_notes(notes, duration, track_info)
        self.selected_indices = set()
        self.selection_changed.emit()
        self.logger.info(f'加载MIDI: {len(notes)} 个音符, {len(midi.instruments)} 个轨道')

    def save_midi_file(self, midi_path):
        """保存当前音符到 MIDI 文件，保留多轨道信息。"""
        midi = pretty_midi.PrettyMIDI()

        if self.track_info:
            # 有轨道信息：按轨道分组保存
            max_track = max(self.track_info.values()) if self.track_info else 0
            instruments = []
            for i in range(max_track + 1):
                instruments.append(pretty_midi.Instrument(program=0))
            for idx, note in enumerate(self.display_notes):
                track_idx = self.track_info.get(idx, 0)
                if track_idx < len(instruments):
                    instruments[track_idx].notes.append(pretty_midi.Note(
                        velocity=note['velocity'], pitch=note['pitch'],
                        start=note['start'], end=note['end']
                    ))
            midi.instruments = instruments
        else:
            # 无轨道信息：单轨道保存
            inst = pretty_midi.Instrument(program=0)
            for n in self.display_notes:
                inst.notes.append(pretty_midi.Note(
                    velocity=n['velocity'], pitch=n['pitch'],
                    start=n['start'], end=n['end']
                ))
            midi.instruments.append(inst)

        midi.write(midi_path)
        self.logger.info(f'保存MIDI: {len(self.display_notes)} 个音符 -> {midi_path}')


def enhance_midi_for_display(midi_path, audio_path=None):
    """Smart note filtering using multi-criteria scoring.
    Each note gets a confidence score (0-1). Only notes scoring below
    a strict threshold are removed. This ensures high precision:
   宁可多保留假阳性，也不误删真实音符。
    
    Scoring criteria:
    1. Spectral energy at note frequency (if audio available)
    2. Temporal consistency: nearby notes in pitch/time
    3. Velocity consistency within chord
    4. Duration reasonableness
    """
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(midi_path)

    # Load audio for spectral verification if available
    y, sr = None, None
    if audio_path and os.path.exists(audio_path):
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=22050)
        except Exception as e:
            _enhance_logger = logging.getLogger('PianoApp')
            _enhance_logger.warning(f'音频加载失败: {e}')

    for inst in midi.instruments:
        notes = sorted(inst.notes, key=lambda n: (n.start, n.pitch))
        if not notes:
            continue

        velocities = [n.velocity for n in notes]
        median_vel = sorted(velocities)[len(velocities) // 2]

        # Score each note: 1.0 = definitely real, 0.0 = definitely fake
        scores = []
        for i, note in enumerate(notes):
            score = 1.0  # Start at max confidence

            # === Criterion 1: Duration ===
            dur = note.end - note.start
            if dur < 0.03:  # < 30ms: very suspicious
                score *= 0.5
            elif dur < 0.05:  # < 50ms: somewhat suspicious
                score *= 0.7
            elif dur < 0.08:  # < 80ms: mildly suspicious
                score *= 0.85
            # else: no penalty

            # === Criterion 2: Temporal consistency ===
            # Check if there are nearby notes (within 0.3s and 12 semitones)
            has_nearby_pitch = False
            has_nearby_time = False
            for j, other in enumerate(notes):
                if i == j:
                    continue
                dt = abs(other.start - note.start)
                dp = abs(other.pitch - note.pitch)
                if dt < 0.3 and dp <= 12:
                    has_nearby_pitch = True
                    break
                if dt < 0.3:
                    has_nearby_time = True

            if not has_nearby_pitch and not has_nearby_time:
                # Isolated note: no musical context nearby
                score *= 0.6
            elif not has_nearby_pitch:
                # Has temporal neighbors but no pitch neighbors
                score *= 0.8

            # === Criterion 3: Velocity consistency within chord ===
            # Find simultaneous notes (within 30ms)
            chord_velocities = [note.velocity]
            for j, other in enumerate(notes):
                if i == j:
                    continue
                if abs(other.start - note.start) < 0.03:
                    chord_velocities.append(other.velocity)

            if len(chord_velocities) >= 2:
                chord_median = sorted(chord_velocities)[len(chord_velocities) // 2]
                if chord_median > 0:
                    vel_ratio = note.velocity / chord_median
                    if vel_ratio < 0.3:  # Much quieter than chord mates
                        score *= 0.6
                    elif vel_ratio < 0.5:
                        score *= 0.8

            # === Criterion 4: Spectral verification ===
            if y is not None and dur < 0.15:
                try:
                    freq = 440.0 * (2.0 ** ((note.pitch - 69) / 12.0))
                    start_sample = int(note.start * sr)
                    end_sample = min(int((note.end + 0.05) * sr), len(y))
                    if start_sample < end_sample and start_sample < len(y):
                        segment = y[start_sample:end_sample]
                        if len(segment) >= 256:
                            fft = np.abs(np.fft.rfft(segment * np.hanning(len(segment))))
                            fft_freqs = np.fft.rfftfreq(len(segment), 1.0 / sr)

                            # Check energy at fundamental + harmonics 2,3
                            note_energy = 0
                            for harmonic in range(1, 4):
                                h_freq = freq * harmonic
                                if h_freq > sr / 2:
                                    break
                                h_idx = np.argmin(np.abs(fft_freqs - h_freq))
                                win_lo = max(0, h_idx - 2)
                                win_hi = min(len(fft), h_idx + 3)
                                note_energy += np.max(fft[win_lo:win_hi])

                            total_energy = np.sum(fft[1:])
                            if total_energy > 1e-10:
                                ratio = note_energy / total_energy
                                if ratio < 0.01:
                                    score *= 0.3  # Almost no spectral support
                                elif ratio < 0.03:
                                    score *= 0.6
                                elif ratio < 0.05:
                                    score *= 0.8
                except Exception:
                    pass  # Skip spectral check on error

            scores.append(score)

        # Only remove notes with VERY low combined score
        # Threshold 0.25: only delete if multiple criteria all agree it's fake
        to_remove = set()
        for i, (note, score) in enumerate(zip(notes, scores)):
            if score < 0.25:
                to_remove.add(i)

        if to_remove:
            inst.notes = [n for i, n in enumerate(notes) if i not in to_remove]
            _enhance_logger2 = logging.getLogger('PianoApp')
            _enhance_logger2.info(f'多维度评分移除了 {len(to_remove)} 个杂音 (阈值<0.25, '
                                  f'分数分布: {sorted([f"{s:.2f}" for s in scores])[:5]}...)')
    midi.write(midi_path)
    return midi_path


# ============================================================
#  MAIN WINDOW (HarmonyOS 6.1 Style)
# ============================================================
class PianoApp(QMainWindow):
    def __init__(self):
        super().__init__()

        # Setup logging
        log_dir = os.path.join(APP_DIR, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f'piano_app_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

        logging.basicConfig(
            level=logging.DEBUG,
            format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        # Silence noisy third-party loggers
        for noisy in ['numba', 'numba.core', 'numba.core.byteflow', 'numba.core.interpreter',
                       'librosa', 'torch', 'urllib3', 'matplotlib', 'PIL',
                       'tensorflow', 'absl', 'h5py']:
            logging.getLogger(noisy).setLevel(logging.WARNING)
        # Suppress root logger warnings from tflite/coreml etc.
        logging.getLogger().setLevel(logging.WARNING)
        self.logger = logging.getLogger('PianoApp')
        self.logger.setLevel(logging.DEBUG)  # 应用自身日志保留DEBUG级别
        self.logger.info(f'应用启动，日志文件: {log_file}')

        self.setWindowTitle("PianoScribe - 钢琴乐谱生成器")
        # Set window icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pianoscribe_icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QPixmap(icon_path))
        self.setMinimumSize(1280, 860)
        self.resize(1440, 920)

        # Theme state
        self.current_theme = 'light'

        self.audio_path = None
        self.midi_path = None
        self.is_processing = False
        self.current_difficulty = '中级'
        self.current_mode = 'standard'  # 'standard', 'accomp', 'vocal', 'edit'
        self.work_dir = os.path.join(os.path.expanduser("~"), "PianoSheetOutput")
        os.makedirs(self.work_dir, exist_ok=True)

        # Audio playback state
        self.audio_data = None
        self.audio_sr = 44100
        self._audio_lock = threading.Lock()
        self._playback_tmp_wav = None  # Track temp WAV file for cleanup

        # Connect synthesis-done bridge signal (thread-safe: signal crosses threads)
        _synthesis_bridge.done.connect(self._enable_play_after_synthesis)

        # Page transition animation state
        self._page_opacity_out = None
        self._page_opacity_in = None
        self._pending_page_index = None

        # Denoise settings
        self.denoise_mode = 'auto'  # 'auto' or 'manual'
        self.denoise_params = {
            'threshold': 0.25,
            'min_duration_ms': 80,
            'chord_strictness': 0.25,
            'max_jump': 12,
            'max_polyphony': 6,
        }

        # Edit mode debounce timer for sheet music re-rendering
        self._edit_render_timer = QTimer()
        self._edit_render_timer.setSingleShot(True)
        self._edit_render_timer.setInterval(500)
        self._edit_render_timer.timeout.connect(self._refresh_edit_sheet_music)

        # Edit mode undo history
        self._edit_history = []  # list of (notes_copy, track_info_copy, selection_copy)
        self._edit_redo_history = []  # 重做栈
        self._edit_history_max = 50

        self._setup_ui()
        self._setup_menu()
        self.setAcceptDrops(True)

    def _show_status(self, msg, timeout=0):
        try:
            self.statusBar().showMessage(msg, timeout or 0)
        except Exception:
            pass

    # ================================================================
    #  THEME MANAGEMENT
    # ================================================================
    def _toggle_theme(self):
        """Toggle between light and dark themes with smooth fade animation."""
        global _current_theme_name
        new_theme = 'dark' if self.current_theme == 'light' else 'light'

        # Fade out animation
        central = self.centralWidget()
        self._theme_opacity_effect = QGraphicsOpacityEffect(central)
        central.setGraphicsEffect(self._theme_opacity_effect)
        anim_out = QPropertyAnimation(self._theme_opacity_effect, b"opacity")
        anim_out.setDuration(150)
        anim_out.setStartValue(1.0)
        anim_out.setEndValue(0.0)
        anim_out.setEasingCurve(QEasingCurve.OutCubic)
        anim_out.finished.connect(lambda: self._apply_theme(new_theme))
        anim_out.start()
        self._theme_anim_out = anim_out  # keep reference

    def _apply_theme(self, theme_name):
        """Apply the given theme and fade back in."""
        global _current_theme_name
        self.current_theme = theme_name
        _current_theme_name = theme_name

        # Update global stylesheet
        self.setStyleSheet(get_stylesheet(theme_name))

        # Update theme toggle button icons
        icon = '🌙' if theme_name == 'light' else '☀️'
        for btn_attr in ['_theme_toggle_btn', '_theme_btn_analysis', '_theme_btn_edit']:
            if hasattr(self, btn_attr):
                getattr(self, btn_attr).setText(icon)

        # Update ModeCards
        if hasattr(self, '_cards'):
            for card in self._cards:
                card.update_theme(theme_name)

        # Update main page background
        if hasattr(self, '_main_page'):
            t = THEMES[theme_name]
            self._main_page.setStyleSheet(f"background-color: {t['page_bg']};")

        # Update sheet music widgets
        if hasattr(self, 'sheet_widget'):
            self.sheet_widget.update_theme(theme_name)
        if hasattr(self, 'edit_sheet_widget'):
            self.edit_sheet_widget.update_theme(theme_name)

        # Refresh all inline styles
        self._refresh_inline_styles(theme_name)

        # Trigger repaint on piano roll widgets
        if hasattr(self, 'piano_roll'):
            self.piano_roll.update()
        if hasattr(self, 'edit_piano_roll'):
            self.edit_piano_roll.update()

        # Fade in animation
        central = self.centralWidget()
        if hasattr(self, '_theme_opacity_effect') and self._theme_opacity_effect:
            anim_in = QPropertyAnimation(self._theme_opacity_effect, b"opacity")
            anim_in.setDuration(200)
            anim_in.setStartValue(0.0)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QEasingCurve.InCubic)
            anim_in.finished.connect(lambda: central.setGraphicsEffect(None))
            anim_in.start()
            self._theme_anim_in = anim_in  # keep reference

    def _refresh_inline_styles(self, theme_name):
        """Refresh all inline stylesheets for the given theme."""
        t = THEMES[theme_name]

        # === Main page widgets ===
        if hasattr(self, '_main_title'):
            self._main_title.setStyleSheet(
                f"font-size: 32px; font-weight: bold; color: {t['accent']}; border: none; background: transparent;")
        if hasattr(self, '_main_subtitle'):
            self._main_subtitle.setStyleSheet(
                f"font-size: 16px; color: {t['text_secondary']}; border: none; background: transparent;")
        if hasattr(self, '_version_label'):
            self._version_label.setStyleSheet(
                f"font-size: 11px; color: {t['hint_text']}; border: none; background: transparent;")

        # === Analysis page widgets ===
        if hasattr(self, 'btn_back_analysis'):
            self.btn_back_analysis.setStyleSheet(f"""
                QPushButton {{
                    border-radius: 20px; padding: 8px 16px; font-size: 14px;
                    background-color: {t['back_btn_bg']}; border: 1px solid {t['back_btn_border']}; color: {t['back_btn_text']};
                }}
                QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
            """)
        if hasattr(self, 'mode_indicator'):
            self.mode_indicator.setStyleSheet(
                f"font-size: 14px; color: {t['accent']}; font-weight: bold; border: none;")

        # Input card
        if hasattr(self, '_input_card'):
            self._input_card.setStyleSheet(
                f"QFrame#cardFrame {{ background-color: {t['card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        if hasattr(self, 'audio_label'):
            color = t['accent'] if self.audio_path else t['audio_label_color']
            weight = 'bold' if self.audio_path else 'normal'
            self.audio_label.setStyleSheet(f"font-size: 14px; color: {color}; font-weight: {weight}; border: none;")
        if hasattr(self, 'progress_label'):
            self.progress_label.setStyleSheet(f"color: {t['progress_label_color']}; font-size: 12px;")

        # Sheet card
        if hasattr(self, '_sheet_card'):
            self._sheet_card.setStyleSheet(
                f"QFrame#cardFrame {{ background-color: {t['sheet_card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        if hasattr(self, '_sheet_title'):
            self._sheet_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {t['text_primary']}; border: none;")
        if hasattr(self, 'zoom_label'):
            self.zoom_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px; min-width: 40px; border: none;")
        if hasattr(self, '_sheet_hint'):
            self._sheet_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none;")

        # Zoom buttons
        for btn_attr in ['_btn_zout', '_btn_zin', '_btn_fit']:
            if hasattr(self, btn_attr):
                btn = getattr(self, btn_attr)
                if btn_attr == '_btn_fit':
                    btn.setStyleSheet(f"""
                        QPushButton {{ border-radius: 15px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};
                        font-size: 12px; color: {t['zoom_btn_text']}; padding: 4px 12px; }}
                        QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}""")
                else:
                    btn.setStyleSheet(f"""
                        QPushButton {{ border-radius: 15px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};
                        font-size: 16px; font-weight: bold; color: {t['zoom_btn_text']}; }}
                        QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}""")

        # Roll card
        if hasattr(self, '_roll_card'):
            self._roll_card.setStyleSheet(
                f"QFrame#cardFrame {{ background-color: {t['roll_card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        if hasattr(self, '_roll_title'):
            self._roll_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {t['roll_title']}; border: none;")
        if hasattr(self, '_roll_hint'):
            self._roll_hint.setStyleSheet(f"font-size: 10px; color: {t['roll_hint']}; border: none;")

        # Info card
        if hasattr(self, '_info_card'):
            self._info_card.setStyleSheet(
                f"QFrame#cardFrame {{ background-color: {t['card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        if hasattr(self, 'diff_level'):
            dc = self.diff_level.property("dynamic_color") or t['info_diff_level']
            self.diff_level.setStyleSheet(f"font-size: 56px; font-weight: bold; color: {dc}; border: none;")
        if hasattr(self, 'diff_name'):
            dc = self.diff_name.property("dynamic_color") or t['info_diff_name']
            self.diff_name.setStyleSheet(f"font-size: 18px; color: {dc}; font-weight: bold; border: none;")
        if hasattr(self, 'diff_detail'):
            self.diff_detail.setStyleSheet(f"font-size: 11px; color: {t['info_diff_detail']}; border: none;")
        if hasattr(self, '_diff_select_label'):
            self._diff_select_label.setStyleSheet(f"font-size: 12px; color: {t['text_secondary']}; border: none;")

        # Separators
        for sep_attr in ['_sep1', '_sep2', '_sep_denoise']:
            if hasattr(self, sep_attr):
                getattr(self, sep_attr).setStyleSheet(f"background-color: {t['sep_color']}; border: none;")

        # Denoise section
        if hasattr(self, '_denoise_title'):
            self._denoise_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {t['text_primary']}; border: none;")
        self._refresh_denoise_styles(theme_name)

        # Tempo and cursor labels
        if hasattr(self, '_tempo_label'):
            self._tempo_label.setStyleSheet(f"font-size: 12px; color: {t['text_secondary']}; border: none;")
        if hasattr(self, 'tempo_value_label'):
            self.tempo_value_label.setStyleSheet(f"font-size: 12px; color: {t['text_primary']}; border: none; min-width: 40px;")
        if hasattr(self, 'cursor_time_label'):
            self.cursor_time_label.setStyleSheet(f"font-size: 12px; color: {t['text_secondary']}; border: none;")
        if hasattr(self, 'stats_label'):
            self.stats_label.setStyleSheet(f"font-size: 13px; color: {t['info_stats_text']}; border: none;")

        # === Edit page widgets ===
        if hasattr(self, 'btn_back_edit'):
            self.btn_back_edit.setStyleSheet(f"""
                QPushButton {{
                    border-radius: 20px; padding: 8px 16px; font-size: 14px;
                    background-color: {t['back_btn_bg']}; border: 1px solid {t['back_btn_border']}; color: {t['back_btn_text']};
                }}
                QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
            """)
        if hasattr(self, '_edit_title'):
            self._edit_title.setStyleSheet(f"font-size: 14px; color: {t['accent']}; font-weight: bold; border: none;")
        if hasattr(self, 'btn_undo_edit'):
            self.btn_undo_edit.setStyleSheet(f"""
                QPushButton {{
                    border-radius: 20px; padding: 8px 16px; font-size: 14px;
                    background-color: {t['back_btn_bg']}; border: 1px solid {t['back_btn_border']}; color: {t['back_btn_text']};
                }}
                QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
                QPushButton:pressed {{ background-color: {t['surface_pressed']}; }}
                QPushButton:disabled {{ background-color: {t['surface_disabled']}; color: {t['label_disabled']}; border-color: {t['divider']}; }}
            """)
        if hasattr(self, '_edit_sheet_card'):
            self._edit_sheet_card.setStyleSheet(
                f"QFrame#cardFrame {{ background-color: {t['sheet_card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        if hasattr(self, '_edit_sheet_title'):
            self._edit_sheet_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {t['text_primary']}; border: none;")
        if hasattr(self, 'edit_zoom_label'):
            self.edit_zoom_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px; min-width: 40px; border: none;")
        for btn_attr in ['_btn_edit_zout', '_btn_edit_zin']:
            if hasattr(self, btn_attr):
                getattr(self, btn_attr).setStyleSheet(f"""
                    QPushButton {{ border-radius: 15px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};
                    font-size: 16px; font-weight: bold; color: {t['zoom_btn_text']}; }}
                    QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}""")
        if hasattr(self, '_edit_roll_card'):
            self._edit_roll_card.setStyleSheet(
                f"QFrame#cardFrame {{ background-color: {t['roll_card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        if hasattr(self, '_edit_roll_title'):
            self._edit_roll_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {t['roll_title']}; border: none;")
        if hasattr(self, '_edit_roll_hint'):
            self._edit_roll_hint.setStyleSheet(f"font-size: 10px; color: {t['roll_hint']}; border: none;")

    def _refresh_denoise_styles(self, theme_name):
        """Refresh denoise section inline styles."""
        t = THEMES[theme_name]
        is_manual = self.denoise_mode == 'manual'

        if hasattr(self, 'btn_denoise_auto'):
            self.btn_denoise_auto.setStyleSheet(f"""
                QPushButton {{
                    border-radius: 14px 0 0 14px; padding: 4px 14px; font-size: 11px;
                    background-color: {t['denoise_auto_bg']}; color: white; border: none; font-weight: bold; min-height: 16px;
                }}
                QPushButton:!checked {{ background-color: {t['denoise_manual_bg']}; color: {t['denoise_manual_text']}; font-weight: normal; }}
                QPushButton:hover:!checked {{ background-color: {t['denoise_manual_hover']}; }}
            """)
        if hasattr(self, 'btn_denoise_manual'):
            self.btn_denoise_manual.setStyleSheet(f"""
                QPushButton {{
                    border-radius: 0 14px 14px 0; padding: 4px 14px; font-size: 11px;
                    background-color: {t['denoise_manual_bg']}; color: {t['denoise_manual_text']}; border: none; min-height: 16px;
                }}
                QPushButton:checked {{ background-color: {t['denoise_auto_bg']}; color: white; font-weight: bold; }}
                QPushButton:hover:!checked {{ background-color: {t['denoise_manual_hover']}; }}
            """)

        denoise_slider_style = f"""
            QSlider::groove:horizontal {{ border: none; height: 4px; background: {t['slider_groove']}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: {t['slider_handle']}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}
            QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
            QSlider::groove:horizontal:disabled {{ background: {t['denoise_disabled_bg']}; }}
            QSlider::handle:horizontal:disabled {{ background: {t['denoise_disabled_handle']}; }}
            QSlider::sub-page:horizontal:disabled {{ background: {t['denoise_disabled_subpage']}; }}
        """
        for slider_attr in ['slider_threshold', 'slider_min_duration', 'slider_chord_strictness',
                            'slider_max_jump', 'slider_max_polyphony']:
            if hasattr(self, slider_attr):
                getattr(self, slider_attr).setStyleSheet(denoise_slider_style)

        label_color = t['text_primary'] if is_manual else t['label_disabled']
        for lbl_attr in ['label_threshold_val', 'label_min_duration_val',
                         'label_chord_val', 'label_max_poly_val']:
            if hasattr(self, lbl_attr):
                getattr(self, lbl_attr).setStyleSheet(f"font-size: 11px; color: {label_color}; border: none; min-width: 32px;")
        if hasattr(self, 'label_max_jump_val'):
            self.label_max_jump_val.setStyleSheet(f"font-size: 11px; color: {label_color}; border: none; min-width: 38px;")

        for lbl_attr in ['_threshold_label', '_min_dur_label', '_chord_label', '_jump_label', '_poly_label']:
            if hasattr(self, lbl_attr):
                getattr(self, lbl_attr).setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 60px;")
        for hint_attr in ['_threshold_hint', '_min_dur_hint', '_chord_hint', '_jump_hint', '_poly_hint']:
            if hasattr(self, hint_attr):
                getattr(self, hint_attr).setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 64px;")

        if hasattr(self, 'btn_apply_denoise'):
            self.btn_apply_denoise.setStyleSheet(f"""
                QPushButton#primary {{
                    background-color: {t['accent']}; color: white; border: none; border-radius: 16px;
                    padding: 6px 16px; font-size: 12px; font-weight: bold; min-height: 18px;
                }}
                QPushButton#primary:hover {{ background-color: {t['accent_hover']}; }}
                QPushButton#primary:disabled {{ background-color: {t['accent_disabled']}; color: white; }}
            """)
        if hasattr(self, 'btn_reset_denoise'):
            self.btn_reset_denoise.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t['surface']}; color: {t['diff_btn_text']}; border: 1px solid {t['border']};
                    border-radius: 16px; padding: 6px 16px; font-size: 12px; min-height: 18px;
                }}
                QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
                QPushButton:disabled {{ background-color: {t['surface_disabled']}; color: {t['label_disabled']}; border-color: {t['divider']}; }}
            """)

    # ================================================================
    #  ANIMATION HELPERS
    # ================================================================
    def _animate_button_click(self, button):
        """HarmonyOS 6.1 button click: shrink then restore."""
        anim = QPropertyAnimation(button, b"geometry")
        geo = button.geometry()
        anim.setKeyValueAt(0, geo)
        anim.setKeyValueAt(0.3, geo.adjusted(2, 2, -2, -2))
        anim.setKeyValueAt(1, geo)
        anim.setDuration(150)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._btn_anim = anim  # keep reference

    def _animate_cards_entrance(self):
        """Animate mode cards sliding in from below with fade-in."""
        if not hasattr(self, '_cards'):
            return
        self._card_anims = []
        for i, card in enumerate(self._cards):
            # Set initial state: transparent and offset down
            opacity_effect = QGraphicsOpacityEffect(card)
            opacity_effect.setOpacity(0)
            card.setGraphicsEffect(opacity_effect)

            original_geo = card.geometry()
            offset_geo = QRectF(original_geo.x(), original_geo.y() + 40,
                                original_geo.width(), original_geo.height())
            card.setGeometry(offset_geo.toRect())

            # Create animations with staggered delay
            delay = 100 + i * 80  # 100ms, 180ms, 260ms, 340ms

            # Opacity animation
            opacity_anim = QPropertyAnimation(opacity_effect, b"opacity")
            opacity_anim.setDuration(300)
            opacity_anim.setStartValue(0.0)
            opacity_anim.setEndValue(1.0)
            opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            # Position animation (slide up)
            pos_anim = QPropertyAnimation(card, b"geometry")
            pos_anim.setDuration(300)
            pos_anim.setStartValue(offset_geo.toRect())
            pos_anim.setEndValue(original_geo)
            pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            # Keep references to prevent garbage collection
            self._card_anims.append((opacity_anim, pos_anim))

            QTimer.singleShot(delay, lambda oa=opacity_anim, pa=pos_anim: (oa.start(), pa.start()))

    def _switch_page(self, index):
        """Switch page with fade-out/fade-in animation."""
        current = self.stacked_widget.currentWidget()
        if current is None or self.stacked_widget.currentIndex() == index:
            self.stacked_widget.setCurrentIndex(index)
            return

        # Fade out current page
        self._page_opacity_out = QGraphicsOpacityEffect(current)
        current.setGraphicsEffect(self._page_opacity_out)
        anim_out = QPropertyAnimation(self._page_opacity_out, b"opacity")
        anim_out.setDuration(200)
        anim_out.setStartValue(1.0)
        anim_out.setEndValue(0.0)
        anim_out.setEasingCurve(QEasingCurve.OutCubic)
        self._pending_page_index = index
        anim_out.finished.connect(self._do_show_page)
        anim_out.start()
        self._anim_out = anim_out  # keep reference

    def _do_show_page(self):
        """Show the pending page with fade-in."""
        index = self._pending_page_index
        if index is None:
            return
        self._pending_page_index = None

        # Clear opacity effect on old page
        old_widget = self.stacked_widget.currentWidget()
        if old_widget:
            old_widget.setGraphicsEffect(None)

        self.stacked_widget.setCurrentIndex(index)

        # Fade in new page
        new_widget = self.stacked_widget.currentWidget()
        self._page_opacity_in = QGraphicsOpacityEffect(new_widget)
        new_widget.setGraphicsEffect(self._page_opacity_in)
        anim_in = QPropertyAnimation(self._page_opacity_in, b"opacity")
        anim_in.setDuration(200)
        anim_in.setStartValue(0.0)
        anim_in.setEndValue(1.0)
        anim_in.setEasingCurve(QEasingCurve.InCubic)
        anim_in.start()
        self._anim_in = anim_in  # keep reference

        if index == 0:
            self._animate_cards_entrance()

    def _animate_progress(self, value):
        """Smooth progress bar animation."""
        anim = QPropertyAnimation(self.progress_bar, b"value")
        anim.setDuration(300)
        anim.setEndValue(value)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._progress_anim = anim  # keep reference

    # ================================================================
    #  UI SETUP
    # ================================================================
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Stacked widget for page management
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)

        # Page 0: Main menu (mode selection)
        self._build_main_page()

        # Page 1: Analysis page (existing analysis UI)
        self._build_analysis_page()

        # Page 2: Edit page
        self._build_edit_page()

        # Start on main page
        self.stacked_widget.setCurrentIndex(0)

    # ================================================================
    #  PAGE 0: MAIN MENU (Mode Selection)
    # ================================================================
    def _build_main_page(self):
        t = get_theme()
        page = QWidget()
        self._main_page = page
        page.setStyleSheet(f"background-color: {t['page_bg']};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 60, 40, 40)
        layout.setSpacing(40)

        # Top bar with theme toggle
        top_bar = QHBoxLayout()
        top_bar.addStretch()

        # Theme toggle button (sun/moon)
        self._theme_toggle_btn = QPushButton('🌙')
        self._theme_toggle_btn.setObjectName('themeToggle')
        self._theme_toggle_btn.setToolTip('切换深色/浅色主题')
        self._theme_toggle_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._theme_toggle_btn.clicked.connect(self._toggle_theme)
        top_bar.addWidget(self._theme_toggle_btn)
        layout.addLayout(top_bar)

        # Title with gradient effect
        title_layout = QVBoxLayout()
        title_layout.setSpacing(8)

        title = QLabel("PianoScribe")
        title.setAlignment(Qt.AlignCenter)
        self._main_title = title
        title.setStyleSheet(
            f"font-size: 38px; font-weight: bold; color: {t['accent']}; border: none; background: transparent; letter-spacing: 2px;")
        title_layout.addWidget(title)

        subtitle = QLabel("专业AI钢琴乐谱转录工具")
        subtitle.setAlignment(Qt.AlignCenter)
        self._main_subtitle = subtitle
        subtitle.setStyleSheet(
            f"font-size: 16px; color: {t['text_secondary']}; border: none; background: transparent;")
        title_layout.addWidget(subtitle)

        layout.addLayout(title_layout)
        layout.addSpacing(20)

        # Mode cards in 2x2 grid
        grid_layout = QGridLayout()
        grid_layout.setSpacing(24)
        grid_layout.setAlignment(Qt.AlignCenter)

        cards = [
            ("🎤", "弹唱模式", "仅伴奏", "accomp"),
            ("🎹", "人声模式", "仅人声", "vocal"),
            ("🎵", "标准模式", "伴奏+人声", "standard"),
            ("✏️", "编辑模式", "导入编辑", "edit"),
        ]

        self._cards = []
        for i, (icon, title, desc, mode) in enumerate(cards):
            card = ModeCard(icon, title, desc, mode)
            card.clicked.connect(self._on_mode_selected)
            row = i // 2
            col = i % 2
            grid_layout.addWidget(card, row, col)
            self._cards.append(card)

        layout.addLayout(grid_layout)
        layout.addStretch()

        # Version label at bottom
        version_label = QLabel("v7.0 | 钢琴乐谱生成器")
        version_label.setAlignment(Qt.AlignCenter)
        self._version_label = version_label
        version_label.setStyleSheet(
            f"font-size: 11px; color: {t['hint_text']}; border: none; background: transparent;")
        layout.addWidget(version_label)

        self.stacked_widget.addWidget(page)

    def _on_mode_selected(self, mode_name):
        """Handle mode card click."""
        self.current_mode = mode_name
        self.logger.info(f'模式选择: {self._mode_label(mode_name)}模式 ({mode_name})')

        if mode_name == 'edit':
            self._switch_page(2)
        else:
            # Switch to analysis page
            self._switch_page(1)
            self._show_status(f"已选择: {self._mode_label(mode_name)}模式")

    def _mode_label(self, mode):
        labels = {'standard': '标准', 'accomp': '弹唱', 'vocal': '人声', 'edit': '编辑'}
        return labels.get(mode, mode)

    # ================================================================
    #  PAGE 1: ANALYSIS PAGE
    # ================================================================
    def _build_analysis_page(self):
        t = get_theme()
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(20, 16, 20, 16)
        page_layout.setSpacing(12)

        # Top bar with back button and theme toggle
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        self.btn_back_analysis = QPushButton("← 返回")
        self.btn_back_analysis.setFixedWidth(100)
        self.btn_back_analysis.setStyleSheet(f"""
            QPushButton {{
                border-radius: 20px; padding: 8px 16px; font-size: 14px;
                background-color: {t['back_btn_bg']}; border: 1px solid {t['back_btn_border']}; color: {t['back_btn_text']};
            }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
        """)
        self.btn_back_analysis.clicked.connect(lambda: self._go_back(0))
        top_bar.addWidget(self.btn_back_analysis)

        self.mode_indicator = QLabel("标准模式")
        self.mode_indicator.setStyleSheet(
            f"font-size: 14px; color: {t['accent']}; font-weight: bold; border: none;")
        top_bar.addWidget(self.mode_indicator)
        top_bar.addStretch()

        # Theme toggle on analysis page
        theme_btn_analysis = QPushButton('🌙')
        theme_btn_analysis.setObjectName('themeToggle')
        theme_btn_analysis.setToolTip('切换深色/浅色主题')
        theme_btn_analysis.setCursor(QCursor(Qt.PointingHandCursor))
        theme_btn_analysis.clicked.connect(self._toggle_theme)
        top_bar.addWidget(theme_btn_analysis)
        self._theme_btn_analysis = theme_btn_analysis

        page_layout.addLayout(top_bar)

        # === Input Section (card) ===
        input_card = QFrame()
        input_card.setObjectName("cardFrame")
        self._input_card = input_card
        input_card.setStyleSheet(
            f"QFrame#cardFrame {{ background-color: {t['card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        input_card.setFixedHeight(64)
        input_layout = QHBoxLayout(input_card)
        input_layout.setContentsMargins(20, 12, 20, 12)
        input_layout.setSpacing(12)

        icon_label = QLabel("🎵")
        icon_label.setStyleSheet("font-size: 22px; border: none;")
        input_layout.addWidget(icon_label)

        self.audio_label = QLabel("选择音频文件开始分析")
        self.audio_label.setStyleSheet(
            f"font-size: 14px; color: {t['audio_label_color']}; border: none;")
        input_layout.addWidget(self.audio_label, 1)

        self.btn_select = QPushButton("选择音频")
        self.btn_select.setFixedWidth(110)
        self.btn_select.clicked.connect(self.select_audio)
        input_layout.addWidget(self.btn_select)

        self.btn_analyze = QPushButton("开始分析")
        self.btn_analyze.setObjectName("primary")
        self.btn_analyze.setFixedWidth(140)
        self.btn_analyze.clicked.connect(lambda checked=False, b=self.btn_analyze: self._animate_button_click(b))
        self.btn_analyze.clicked.connect(self.start_analysis)
        input_layout.addWidget(self.btn_analyze)

        page_layout.addWidget(input_card)

        # === Progress ===
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_bar, 1)
        self.progress_label = QLabel("就绪")
        self.progress_label.setMinimumWidth(300)
        self.progress_label.setStyleSheet(f"color: {t['progress_label_color']}; font-size: 12px;")
        progress_layout.addWidget(self.progress_label)
        page_layout.addLayout(progress_layout)

        # === Middle: Splitter (Sheet + PianoRoll on left, Info on right) ===
        splitter = QSplitter(Qt.Horizontal)

        # Left side: Sheet music + Piano roll (vertical split)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Sheet music card
        sheet_card = QFrame()
        sheet_card.setObjectName("cardFrame")
        self._sheet_card = sheet_card
        sheet_card.setStyleSheet(
            f"QFrame#cardFrame {{ background-color: {t['sheet_card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        sheet_layout = QVBoxLayout(sheet_card)
        sheet_layout.setContentsMargins(8, 8, 8, 4)
        sheet_layout.setSpacing(4)

        # Sheet toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)

        title = QLabel("五线谱")
        title.setObjectName("cardTitle")
        self._sheet_title = title
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {t['text_primary']}; border: none;")
        toolbar.addWidget(title)

        toolbar.addStretch()

        btn_zout = QPushButton("−")
        btn_zout.setFixedSize(30, 30)
        self._btn_zout = btn_zout
        btn_zout.setStyleSheet(
            f"QPushButton {{ border-radius: 15px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 16px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        btn_zout.clicked.connect(lambda: (self.sheet_widget.zoom_out(), self._update_zoom_label()))
        toolbar.addWidget(btn_zout)

        self.zoom_label = QLabel("1.0x")
        self.zoom_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px; min-width: 40px; border: none;")
        toolbar.addWidget(self.zoom_label)

        btn_zin = QPushButton("+")
        btn_zin.setFixedSize(30, 30)
        self._btn_zin = btn_zin
        btn_zin.setStyleSheet(
            f"QPushButton {{ border-radius: 15px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 16px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        btn_zin.clicked.connect(lambda: (self.sheet_widget.zoom_in(), self._update_zoom_label()))
        toolbar.addWidget(btn_zin)

        btn_fit = QPushButton("适应")
        self._btn_fit = btn_fit
        btn_fit.setStyleSheet(
            f"QPushButton {{ border-radius: 15px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 12px; color: {t['zoom_btn_text']}; padding: 4px 12px; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        btn_fit.clicked.connect(lambda: (self.sheet_widget.zoom_fit(), self._update_zoom_label()))
        toolbar.addWidget(btn_fit)

        toolbar.addStretch()

        hint = QLabel("LilyPond 专业乐谱渲染 | 滚轮滚动 | Ctrl+滚轮缩放")
        hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none;")
        self._sheet_hint = hint
        toolbar.addWidget(hint)

        sheet_layout.addLayout(toolbar)

        # Sheet music widget (LilyPond + SVG + QSvgRenderer)
        self.sheet_widget = SheetMusicWidget()
        self.sheet_widget.rendering_done.connect(
            lambda: self._show_status("乐谱渲染完成", 3000))
        sheet_layout.addWidget(self.sheet_widget, 1)

        left_layout.addWidget(sheet_card, 3)

        # Piano roll card
        roll_card = QFrame()
        roll_card.setObjectName("cardFrame")
        self._roll_card = roll_card
        roll_card.setStyleSheet(
            f"QFrame#cardFrame {{ background-color: {t['roll_card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        roll_layout = QVBoxLayout(roll_card)
        roll_layout.setContentsMargins(8, 8, 8, 8)
        roll_layout.setSpacing(4)

        # Roll toolbar
        roll_toolbar = QHBoxLayout()
        roll_toolbar.setContentsMargins(8, 2, 8, 2)

        roll_title = QLabel("钢琴卷帘")
        self._roll_title = roll_title
        roll_title.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {t['roll_title']}; border: none;")
        roll_toolbar.addWidget(roll_title)

        roll_toolbar.addStretch()

        roll_hint = QLabel("滚轮滚动 | Ctrl+滚轮缩放 | 右键拖拽")
        self._roll_hint = roll_hint
        roll_hint.setStyleSheet(f"font-size: 10px; color: {t['roll_hint']}; border: none;")
        roll_toolbar.addWidget(roll_hint)

        roll_layout.addLayout(roll_toolbar)

        # Piano roll widget
        self.piano_roll = PianoRollWidget()
        roll_layout.addWidget(self.piano_roll, 1)

        left_layout.addWidget(roll_card, 2)

        splitter.addWidget(left_widget)

        # Right: Info panel (card)
        info_card = QFrame()
        info_card.setObjectName("cardFrame")
        self._info_card = info_card
        info_card.setStyleSheet(
            f"QFrame#cardFrame {{ background-color: {t['card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        info_card.setFixedWidth(340)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(20, 20, 20, 20)
        info_layout.setSpacing(12)

        # Difficulty display
        diff_title = QLabel("难度分级")
        diff_title.setObjectName("cardTitle")
        info_layout.addWidget(diff_title)

        self.diff_level = QLabel("--")
        self.diff_level.setAlignment(Qt.AlignCenter)
        self.diff_level.setStyleSheet(
            f"font-size: 56px; font-weight: bold; color: {t['info_diff_level']}; border: none;")
        info_layout.addWidget(self.diff_level)

        self.diff_name = QLabel("等待分析")
        self.diff_name.setAlignment(Qt.AlignCenter)
        self.diff_name.setStyleSheet(
            f"font-size: 18px; color: {t['info_diff_name']}; font-weight: bold; border: none;")
        info_layout.addWidget(self.diff_name)

        self.diff_detail = QLabel("")
        self.diff_detail.setWordWrap(True)
        self.diff_detail.setMinimumWidth(280)
        self.diff_detail.setStyleSheet(f"font-size: 11px; color: {t['info_diff_detail']}; border: none;")
        info_layout.addWidget(self.diff_detail)

        # Difficulty button group
        diff_select_label = QLabel("难度选择:")
        self._diff_select_label = diff_select_label
        diff_select_label.setStyleSheet(f"font-size: 12px; color: {t['text_secondary']}; border: none;")
        info_layout.addWidget(diff_select_label)

        diff_btn_layout = QHBoxLayout()
        diff_btn_layout.setSpacing(6)
        self.diff_buttons = {}
        self.diff_button_group = QButtonGroup(self)
        self.diff_button_group.setExclusive(True)

        difficulties = ["入门", "初级", "中级", "高级", "专业"]
        for i, diff in enumerate(difficulties):
            btn = QPushButton(diff)
            btn.setCheckable(True)
            btn.setObjectName("diffBtn")
            if diff == self.current_difficulty:
                btn.setObjectName("diffBtnSelected")
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, d=diff: self._on_difficulty_button_clicked(d))
            self.diff_buttons[diff] = btn
            self.diff_button_group.addButton(btn, i)
            diff_btn_layout.addWidget(btn)

        info_layout.addLayout(diff_btn_layout)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        self._sep1 = sep
        sep.setStyleSheet(f"background-color: {t['sep_color']}; border: none;")
        info_layout.addWidget(sep)

        # Stats
        stats_title = QLabel("分析信息")
        stats_title.setObjectName("cardTitle")
        info_layout.addWidget(stats_title)

        self.stats_label = QLabel("选择音频文件开始分析")
        self.stats_label.setWordWrap(True)
        self.stats_label.setMinimumWidth(280)
        self.stats_label.setObjectName("statValue")
        info_layout.addWidget(self.stats_label)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFixedHeight(1)
        self._sep2 = sep2
        sep2.setStyleSheet(f"background-color: {t['sep_color']}; border: none;")
        info_layout.addWidget(sep2)

        # Playback controls
        play_title = QLabel("播放控制")
        play_title.setObjectName("cardTitle")
        info_layout.addWidget(play_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setObjectName("btnPlay")
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(lambda checked=False, b=self.btn_play: self._animate_button_click(b))
        self.btn_play.clicked.connect(self.play_midi)
        btn_row.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_midi)
        btn_row.addWidget(self.btn_stop)

        self.btn_export = QPushButton("📤 导出")
        self.btn_export.setObjectName("btnExport")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(lambda checked=False, b=self.btn_export: self._animate_button_click(b))
        self.btn_export.clicked.connect(self.export_midi)
        btn_row.addWidget(self.btn_export)

        info_layout.addLayout(btn_row)

        # Velocity mode toggle: original velocity vs uniform velocity
        vel_mode_row = QHBoxLayout()
        vel_mode_row.setSpacing(6)
        vel_mode_label = QLabel("音量模式:")
        vel_mode_label.setStyleSheet(f"font-size: 12px; color: {t['text_secondary']}; border: none;")
        vel_mode_row.addWidget(vel_mode_label)

        self.btn_vel_original = QPushButton("原始力度")
        self.btn_vel_original.setCheckable(True)
        self.btn_vel_original.setChecked(True)
        self.btn_vel_original.setObjectName("velModeBtn")
        vel_mode_row.addWidget(self.btn_vel_original)

        self.btn_vel_uniform = QPushButton("统一音量")
        self.btn_vel_uniform.setCheckable(True)
        self.btn_vel_uniform.setObjectName("velModeBtn")
        vel_mode_row.addWidget(self.btn_vel_uniform)

        self._vel_mode_group = QButtonGroup(self)
        self._vel_mode_group.addButton(self.btn_vel_original, 0)
        self._vel_mode_group.addButton(self.btn_vel_uniform, 1)

        vel_mode_style = f"""
            QPushButton#velModeBtn {{
                border-radius: 4px; padding: 3px 10px; font-size: 11px;
                background-color: {t['surface']}; border: 1px solid {t['border']};
                color: {t['text_secondary']};
            }}
            QPushButton#velModeBtn:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
            QPushButton#velModeBtn:checked {{
                background-color: {t['accent']}; color: white; border-color: {t['accent']};
            }}
        """
        self.btn_vel_original.setStyleSheet(vel_mode_style)
        self.btn_vel_uniform.setStyleSheet(vel_mode_style)

        # Uniform velocity slider (only visible when uniform mode is selected)
        self._uniform_vel_slider = QSlider(Qt.Horizontal)
        self._uniform_vel_slider.setRange(1, 127)
        self._uniform_vel_slider.setValue(100)
        self._uniform_vel_slider.setFixedWidth(80)
        self._uniform_vel_slider.setVisible(False)
        self._uniform_vel_slider.setToolTip("统一力度值")
        self._uniform_vel_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border: 1px solid {t['slider_groove']}; height: 4px;
                background: {t['slider_groove']}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {t['slider_handle']}; border: none; width: 12px;
                margin: -4px 0; border-radius: 6px;
            }}
        """)
        vel_mode_row.addWidget(self._uniform_vel_slider)

        self._uniform_vel_label = QLabel("100")
        self._uniform_vel_label.setFixedWidth(24)
        self._uniform_vel_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none;")
        self._uniform_vel_label.setVisible(False)
        vel_mode_row.addWidget(self._uniform_vel_label)

        self._vel_mode_group.idToggled.connect(self._on_vel_mode_changed)
        self._uniform_vel_slider.valueChanged.connect(
            lambda v: self._uniform_vel_label.setText(str(v)))

        vel_mode_row.addStretch()
        info_layout.addLayout(vel_mode_row)

        # ---- Denoise settings panel ----
        sep_denoise = QFrame()
        sep_denoise.setFrameShape(QFrame.HLine)
        sep_denoise.setFixedHeight(1)
        self._sep_denoise = sep_denoise
        sep_denoise.setStyleSheet(f"background-color: {t['sep_color']}; border: none;")
        info_layout.addWidget(sep_denoise)

        denoise_title = QLabel("降噪设置")
        denoise_title.setObjectName("cardTitle")
        self._denoise_title = denoise_title
        denoise_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {t['text_primary']}; border: none;")
        info_layout.addWidget(denoise_title)

        # Mode toggle: Auto / Manual
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(0)
        self.btn_denoise_auto = QPushButton("自动")
        self.btn_denoise_auto.setCheckable(True)
        self.btn_denoise_auto.setChecked(True)
        self.btn_denoise_auto.setObjectName("denoiseModeBtn")
        self.btn_denoise_auto.setStyleSheet(f"""
            QPushButton {{
                border-radius: 14px 0 0 14px;
                padding: 4px 14px;
                font-size: 11px;
                background-color: {t['denoise_auto_bg']};
                color: white;
                border: none;
                font-weight: bold;
                min-height: 16px;
            }}
            QPushButton:!checked {{
                background-color: {t['denoise_manual_bg']};
                color: {t['denoise_manual_text']};
                font-weight: normal;
            }}
            QPushButton:hover:!checked {{
                background-color: {t['denoise_manual_hover']};
            }}
        """)
        self.btn_denoise_manual = QPushButton("手动")
        self.btn_denoise_manual.setCheckable(True)
        self.btn_denoise_manual.setObjectName("denoiseModeBtn")
        self.btn_denoise_manual.setStyleSheet(f"""
            QPushButton {{
                border-radius: 0 14px 14px 0;
                padding: 4px 14px;
                font-size: 11px;
                background-color: {t['denoise_manual_bg']};
                color: {t['denoise_manual_text']};
                border: none;
                min-height: 16px;
            }}
            QPushButton:checked {{
                background-color: {t['denoise_auto_bg']};
                color: white;
                font-weight: bold;
            }}
            QPushButton:hover:!checked {{
                background-color: {t['denoise_manual_hover']};
            }}
        """)
        self._denoise_mode_group = QButtonGroup(self)
        self._denoise_mode_group.setExclusive(True)
        self._denoise_mode_group.addButton(self.btn_denoise_auto)
        self._denoise_mode_group.addButton(self.btn_denoise_manual)
        self.btn_denoise_auto.clicked.connect(lambda: self._on_denoise_mode_changed('auto'))
        self.btn_denoise_manual.clicked.connect(lambda: self._on_denoise_mode_changed('manual'))
        mode_layout.addWidget(self.btn_denoise_auto)
        mode_layout.addWidget(self.btn_denoise_manual)
        info_layout.addLayout(mode_layout)

        # Denoise parameter sliders container
        self._denoise_sliders_widget = QWidget()
        self._denoise_sliders_layout = QVBoxLayout(self._denoise_sliders_widget)
        self._denoise_sliders_layout.setContentsMargins(0, 8, 0, 0)
        self._denoise_sliders_layout.setSpacing(6)

        denoise_slider_style = f"""
            QSlider::groove:horizontal {{
                border: none;
                height: 4px;
                background: {t['slider_groove']};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {t['slider_handle']};
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }}
            QSlider::sub-page:horizontal {{
                background: {t['accent']};
                border-radius: 2px;
            }}
            QSlider::groove:horizontal:disabled {{
                background: {t['denoise_disabled_bg']};
            }}
            QSlider::handle:horizontal:disabled {{
                background: {t['denoise_disabled_handle']};
            }}
            QSlider::sub-page:horizontal:disabled {{
                background: {t['denoise_disabled_subpage']};
            }}
        """

        # a. Removal threshold (0.0 - 0.5, default 0.25)
        threshold_layout = QHBoxLayout()
        threshold_layout.setSpacing(4)
        threshold_label = QLabel("删除阈值")
        self._threshold_label = threshold_label
        threshold_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 60px;")
        threshold_layout.addWidget(threshold_label)
        self.slider_threshold = QSlider(Qt.Horizontal)
        self.slider_threshold.setRange(0, 50)
        self.slider_threshold.setValue(25)
        self.slider_threshold.setStyleSheet(denoise_slider_style)
        self.slider_threshold.setEnabled(False)
        threshold_layout.addWidget(self.slider_threshold, 1)
        self.label_threshold_val = QLabel("0.25")
        self.label_threshold_val.setStyleSheet(f"font-size: 11px; color: {t['label_disabled']}; border: none; min-width: 32px;")
        threshold_layout.addWidget(self.label_threshold_val)
        self._denoise_sliders_layout.addLayout(threshold_layout)
        threshold_hint = QLabel("低于此分数的音符将被删除")
        self._threshold_hint = threshold_hint
        threshold_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 64px;")
        self._denoise_sliders_layout.addWidget(threshold_hint)
        self.slider_threshold.valueChanged.connect(
            lambda v: self.label_threshold_val.setText(f"{v / 100:.2f}"))

        # b. Min note duration (20ms - 200ms, default 80ms)
        min_dur_layout = QHBoxLayout()
        min_dur_layout.setSpacing(4)
        min_dur_label = QLabel("最短音符")
        self._min_dur_label = min_dur_label
        min_dur_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 60px;")
        min_dur_layout.addWidget(min_dur_label)
        self.slider_min_duration = QSlider(Qt.Horizontal)
        self.slider_min_duration.setRange(20, 200)
        self.slider_min_duration.setValue(80)
        self.slider_min_duration.setStyleSheet(denoise_slider_style)
        self.slider_min_duration.setEnabled(False)
        min_dur_layout.addWidget(self.slider_min_duration, 1)
        self.label_min_duration_val = QLabel("80ms")
        self.label_min_duration_val.setStyleSheet(f"font-size: 11px; color: {t['label_disabled']}; border: none; min-width: 32px;")
        min_dur_layout.addWidget(self.label_min_duration_val)
        self._denoise_sliders_layout.addLayout(min_dur_layout)
        min_dur_hint = QLabel("短于此的音符将被删除")
        self._min_dur_hint = min_dur_hint
        min_dur_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 64px;")
        self._denoise_sliders_layout.addWidget(min_dur_hint)
        self.slider_min_duration.valueChanged.connect(
            lambda v: self.label_min_duration_val.setText(f"{v}ms"))

        # c. Chord strictness (0.0 - 1.0, default 0.25)
        chord_layout = QHBoxLayout()
        chord_layout.setSpacing(4)
        chord_label = QLabel("和弦严格度")
        self._chord_label = chord_label
        chord_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 60px;")
        chord_layout.addWidget(chord_label)
        self.slider_chord_strictness = QSlider(Qt.Horizontal)
        self.slider_chord_strictness.setRange(0, 100)
        self.slider_chord_strictness.setValue(25)
        self.slider_chord_strictness.setStyleSheet(denoise_slider_style)
        self.slider_chord_strictness.setEnabled(False)
        chord_layout.addWidget(self.slider_chord_strictness, 1)
        self.label_chord_val = QLabel("0.25")
        self.label_chord_val.setStyleSheet(f"font-size: 11px; color: {t['label_disabled']}; border: none; min-width: 32px;")
        chord_layout.addWidget(self.label_chord_val)
        self._denoise_sliders_layout.addLayout(chord_layout)
        chord_hint = QLabel("越高则越严格要求符合和弦")
        self._chord_hint = chord_hint
        chord_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 64px;")
        self._denoise_sliders_layout.addWidget(chord_hint)
        self.slider_chord_strictness.valueChanged.connect(
            lambda v: self.label_chord_val.setText(f"{v / 100:.2f}"))

        # d. Max jump (6 - 24 semitones, default 12)
        jump_layout = QHBoxLayout()
        jump_layout.setSpacing(4)
        jump_label = QLabel("最大跳跃")
        self._jump_label = jump_label
        jump_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 60px;")
        jump_layout.addWidget(jump_label)
        self.slider_max_jump = QSlider(Qt.Horizontal)
        self.slider_max_jump.setRange(6, 24)
        self.slider_max_jump.setValue(12)
        self.slider_max_jump.setStyleSheet(denoise_slider_style)
        self.slider_max_jump.setEnabled(False)
        jump_layout.addWidget(self.slider_max_jump, 1)
        self.label_max_jump_val = QLabel("12半音")
        self.label_max_jump_val.setStyleSheet(f"font-size: 11px; color: {t['label_disabled']}; border: none; min-width: 38px;")
        jump_layout.addWidget(self.label_max_jump_val)
        self._denoise_sliders_layout.addLayout(jump_layout)
        jump_hint = QLabel("超过此的音程将被视为噪声")
        self._jump_hint = jump_hint
        jump_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 64px;")
        self._denoise_sliders_layout.addWidget(jump_hint)
        self.slider_max_jump.valueChanged.connect(
            lambda v: self.label_max_jump_val.setText(f"{v}半音"))

        # e. Max polyphony (2 - 10, default 6)
        poly_layout = QHBoxLayout()
        poly_layout.setSpacing(4)
        poly_label = QLabel("同时发音上限")
        self._poly_label = poly_label
        poly_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 60px;")
        poly_layout.addWidget(poly_label)
        self.slider_max_polyphony = QSlider(Qt.Horizontal)
        self.slider_max_polyphony.setRange(2, 10)
        self.slider_max_polyphony.setValue(6)
        self.slider_max_polyphony.setStyleSheet(denoise_slider_style)
        self.slider_max_polyphony.setEnabled(False)
        poly_layout.addWidget(self.slider_max_polyphony, 1)
        self.label_max_poly_val = QLabel("6")
        self.label_max_poly_val.setStyleSheet(f"font-size: 11px; color: {t['label_disabled']}; border: none; min-width: 32px;")
        poly_layout.addWidget(self.label_max_poly_val)
        self._denoise_sliders_layout.addLayout(poly_layout)
        poly_hint = QLabel("超过此数量的和弦将被精简")
        self._poly_hint = poly_hint
        poly_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 64px;")
        self._denoise_sliders_layout.addWidget(poly_hint)
        self.slider_max_polyphony.valueChanged.connect(
            lambda v: self.label_max_poly_val.setText(str(v)))

        # Apply & Reset buttons
        denoise_btn_layout = QHBoxLayout()
        denoise_btn_layout.setSpacing(8)
        self.btn_apply_denoise = QPushButton("应用降噪")
        self.btn_apply_denoise.setObjectName("primary")
        self.btn_apply_denoise.setStyleSheet(f"""
            QPushButton#primary {{
                background-color: {t['accent']};
                color: white;
                border: none;
                border-radius: 16px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: bold;
                min-height: 18px;
            }}
            QPushButton#primary:hover {{
                background-color: {t['accent_hover']};
            }}
            QPushButton#primary:disabled {{
                background-color: {t['accent_disabled']};
                color: white;
            }}
        """)
        self.btn_apply_denoise.setEnabled(False)
        self.btn_apply_denoise.clicked.connect(self._apply_denoise)
        denoise_btn_layout.addWidget(self.btn_apply_denoise)

        self.btn_reset_denoise = QPushButton("重置默认")
        self.btn_reset_denoise.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['surface']};
                color: {t['diff_btn_text']};
                border: 1px solid {t['border']};
                border-radius: 16px;
                padding: 6px 16px;
                font-size: 12px;
                min-height: 18px;
            }}
            QPushButton:hover {{
                border-color: {t['accent']};
                color: {t['accent']};
            }}
            QPushButton:disabled {{
                background-color: {t['surface_disabled']};
                color: {t['label_disabled']};
                border-color: {t['divider']};
            }}
        """)
        self.btn_reset_denoise.setEnabled(False)
        self.btn_reset_denoise.clicked.connect(self._reset_denoise)
        denoise_btn_layout.addWidget(self.btn_reset_denoise)
        self._denoise_sliders_layout.addLayout(denoise_btn_layout)

        info_layout.addWidget(self._denoise_sliders_widget)

        # Tempo slider
        tempo_layout = QHBoxLayout()
        tempo_label = QLabel("速度:")
        self._tempo_label = tempo_label
        tempo_label.setStyleSheet(f"font-size: 12px; color: {t['text_secondary']}; border: none;")
        tempo_layout.addWidget(tempo_label)
        self.tempo_slider = QSlider(Qt.Horizontal)
        self.tempo_slider.setRange(50, 200)
        self.tempo_slider.setValue(100)
        self.tempo_slider.setTickInterval(10)
        tempo_layout.addWidget(self.tempo_slider)
        self.tempo_value_label = QLabel("100%")
        self.tempo_value_label.setStyleSheet(f"font-size: 12px; color: {t['text_primary']}; border: none; min-width: 40px;")
        self.tempo_slider.valueChanged.connect(
            lambda v: self.tempo_value_label.setText(f"{v}%"))
        tempo_layout.addWidget(self.tempo_value_label)
        info_layout.addLayout(tempo_layout)

        # Cursor time display
        self.cursor_time_label = QLabel("光标: 0.0秒")
        self.cursor_time_label.setStyleSheet(f"font-size: 12px; color: {t['text_secondary']}; border: none;")
        info_layout.addWidget(self.cursor_time_label)

        info_layout.addStretch()

        splitter.addWidget(info_card)

        splitter.setSizes([1000, 300])
        page_layout.addWidget(splitter, 1)

        # Cursor time update timer
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(100)
        self._cursor_timer.timeout.connect(self._update_cursor_display)

        self.stacked_widget.addWidget(page)

    # ================================================================
    #  PAGE 2: EDIT PAGE
    # ================================================================
    def _build_edit_page(self):
        t = get_theme()
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(16, 12, 16, 12)
        page_layout.setSpacing(8)

        # ════════════════════════════════════════════════════
        #  顶部导航栏
        # ════════════════════════════════════════════════════
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.btn_back_edit = QPushButton("← 返回")
        self.btn_back_edit.setFixedWidth(90)
        self.btn_back_edit.setStyleSheet(f"""
            QPushButton {{
                border-radius: 20px; padding: 6px 14px; font-size: 13px;
                background-color: {t['back_btn_bg']}; border: 1px solid {t['back_btn_border']};
                color: {t['back_btn_text']};
            }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
        """)
        self.btn_back_edit.clicked.connect(lambda: self._go_back(0))
        top_bar.addWidget(self.btn_back_edit)

        edit_title = QLabel("编辑模式")
        self._edit_title = edit_title
        edit_title.setStyleSheet(
            f"font-size: 13px; color: {t['accent']}; font-weight: bold; border: none;")
        top_bar.addWidget(edit_title)
        top_bar.addStretch()

        # 导入/导出
        self.btn_import_mid = QPushButton("导入")
        self.btn_import_mid.setObjectName("primary")
        self.btn_import_mid.setFixedSize(70, 32)
        self.btn_import_mid.clicked.connect(self._import_midi_edit)
        top_bar.addWidget(self.btn_import_mid)

        self.btn_export_mid = QPushButton("导出")
        self.btn_export_mid.setObjectName("btnExport")
        self.btn_export_mid.setFixedSize(70, 32)
        self.btn_export_mid.setEnabled(False)
        self.btn_export_mid.clicked.connect(self._export_midi_edit)
        top_bar.addWidget(self.btn_export_mid)

        # 主题切换
        theme_btn_edit = QPushButton('🌙')
        theme_btn_edit.setObjectName('themeToggle')
        theme_btn_edit.setToolTip('切换深色/浅色主题')
        theme_btn_edit.setCursor(QCursor(Qt.PointingHandCursor))
        theme_btn_edit.clicked.connect(self._toggle_theme)
        top_bar.addWidget(theme_btn_edit)
        self._theme_btn_edit = theme_btn_edit

        page_layout.addLayout(top_bar)

        # ════════════════════════════════════════════════════
        #  工具栏（选择/铅笔/橡皮 + 撤销/重做 + 播放 + 量化 + 吸附 + 缩放）
        # ════════════════════════════════════════════════════
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        # 工具按钮组
        tool_group_style = f"""
            QPushButton {{
                border-radius: 6px; padding: 5px 12px; font-size: 12px;
                background-color: {t['surface']}; border: 1px solid {t['border']};
                color: {t['text_secondary']}; min-width: 50px;
            }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
            QPushButton:checked {{
                background-color: {t['accent']}; color: white; border-color: {t['accent']};
            }}
        """

        self.btn_tool_select = QPushButton("选择")
        self.btn_tool_select.setCheckable(True)
        self.btn_tool_select.setChecked(True)
        self.btn_tool_select.setStyleSheet(tool_group_style)
        self.btn_tool_select.setToolTip("选择工具 (V) — 框选/移动音符")
        toolbar.addWidget(self.btn_tool_select)

        self.btn_tool_pencil = QPushButton("铅笔")
        self.btn_tool_pencil.setCheckable(True)
        self.btn_tool_pencil.setStyleSheet(tool_group_style)
        self.btn_tool_pencil.setToolTip("铅笔工具 (P) — 添加/移动/缩放音符")
        toolbar.addWidget(self.btn_tool_pencil)

        self.btn_tool_eraser = QPushButton("橡皮")
        self.btn_tool_eraser.setCheckable(True)
        self.btn_tool_eraser.setStyleSheet(tool_group_style)
        self.btn_tool_eraser.setToolTip("橡皮工具 (E) — 点击删除音符")
        toolbar.addWidget(self.btn_tool_eraser)

        self._edit_tool_group = QButtonGroup(self)
        self._edit_tool_group.addButton(self.btn_tool_select, 0)
        self._edit_tool_group.addButton(self.btn_tool_pencil, 1)
        self._edit_tool_group.addButton(self.btn_tool_eraser, 2)
        self._edit_tool_group.idClicked.connect(self._on_edit_tool_changed)

        # 分隔线
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet(f"color: {t['divider']}; border: none; background-color: {t['divider']}; max-width: 1px; margin: 4px 4px;")
        toolbar.addWidget(sep1)

        # 撤销/重做
        undo_redo_style = f"""
            QPushButton {{
                border-radius: 6px; padding: 5px 8px; font-size: 13px;
                background-color: {t['surface']}; border: 1px solid {t['border']};
                color: {t['text_secondary']}; min-width: 32px;
            }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
            QPushButton:disabled {{
                background-color: {t['surface_disabled']}; color: {t['label_disabled']};
                border-color: {t['divider']};
            }}
        """

        self.btn_undo_edit = QPushButton("↩")
        self.btn_undo_edit.setToolTip("撤销 (Ctrl+Z)")
        self.btn_undo_edit.setEnabled(False)
        self.btn_undo_edit.setStyleSheet(undo_redo_style)
        self.btn_undo_edit.clicked.connect(self._undo_edit)
        toolbar.addWidget(self.btn_undo_edit)

        self.btn_redo_edit = QPushButton("↪")
        self.btn_redo_edit.setToolTip("重做 (Ctrl+Y)")
        self.btn_redo_edit.setEnabled(False)
        self.btn_redo_edit.setStyleSheet(undo_redo_style)
        self.btn_redo_edit.clicked.connect(self._redo_edit)
        toolbar.addWidget(self.btn_redo_edit)

        # 分隔线
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet(f"color: {t['divider']}; border: none; background-color: {t['divider']}; max-width: 1px; margin: 4px 4px;")
        toolbar.addWidget(sep2)

        # 播放/停止
        play_style = f"""
            QPushButton {{
                border-radius: 6px; padding: 5px 10px; font-size: 12px;
                background-color: {t['success']}; color: white; border: none;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {t['success_hover']}; }}
            QPushButton:pressed {{ background-color: {t['success_pressed']}; }}
            QPushButton:disabled {{
                background-color: {t['success_disabled']}; color: white;
            }}
        """
        stop_style = f"""
            QPushButton {{
                border-radius: 6px; padding: 5px 10px; font-size: 12px;
                background-color: {t['danger']}; color: white; border: none;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {t['danger_hover']}; }}
            QPushButton:pressed {{ background-color: {t['danger_pressed']}; }}
            QPushButton:disabled {{
                background-color: {t['danger_disabled']}; color: white;
            }}
        """

        self.btn_edit_play = QPushButton("▶ 播放")
        self.btn_edit_play.setStyleSheet(play_style)
        self.btn_edit_play.setToolTip("播放试听 (Space)")
        self.btn_edit_play.setEnabled(False)
        self.btn_edit_play.clicked.connect(self._play_edit_audio)
        toolbar.addWidget(self.btn_edit_play)

        self.btn_edit_stop = QPushButton("■ 停止")
        self.btn_edit_stop.setStyleSheet(stop_style)
        self.btn_edit_stop.setToolTip("停止播放")
        self.btn_edit_stop.setEnabled(False)
        self.btn_edit_stop.clicked.connect(self._stop_edit_audio)
        toolbar.addWidget(self.btn_edit_stop)

        # 分隔线
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.VLine)
        sep3.setStyleSheet(f"color: {t['divider']}; border: none; background-color: {t['divider']}; max-width: 1px; margin: 4px 4px;")
        toolbar.addWidget(sep3)

        # 量化按钮
        self.btn_quantize = QPushButton("量化")
        self.btn_quantize.setStyleSheet(f"""
            QPushButton {{
                border-radius: 6px; padding: 5px 10px; font-size: 12px;
                background-color: {t['surface']}; border: 1px solid {t['border']};
                color: {t['text_secondary']};
            }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
        """)
        self.btn_quantize.setToolTip("将选中音符对齐到网格 (Q)")
        self.btn_quantize.clicked.connect(self._quantize_edit_notes)
        toolbar.addWidget(self.btn_quantize)

        # 吸附开关
        self.btn_snap = QPushButton("吸附")
        self.btn_snap.setCheckable(True)
        self.btn_snap.setStyleSheet(f"""
            QPushButton {{
                border-radius: 6px; padding: 5px 10px; font-size: 12px;
                background-color: {t['surface']}; border: 1px solid {t['border']};
                color: {t['text_secondary']};
            }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
            QPushButton:checked {{
                background-color: {t['accent']}; color: white; border-color: {t['accent']};
            }}
        """)
        self.btn_snap.setToolTip("启用网格吸附 (S)")
        self.btn_snap.toggled.connect(self._on_snap_toggled)
        toolbar.addWidget(self.btn_snap)

        toolbar.addStretch()

        # 缩放控制
        self.btn_roll_zout = QPushButton("−")
        self.btn_roll_zout.setFixedSize(28, 28)
        self.btn_roll_zout.setStyleSheet(
            f"QPushButton {{ border-radius: 14px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 14px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        self.btn_roll_zout.clicked.connect(lambda: self._edit_roll_zoom(-1))
        toolbar.addWidget(self.btn_roll_zout)

        self.edit_roll_zoom_label = QLabel("1.0x")
        self.edit_roll_zoom_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px; min-width: 36px; border: none;")
        toolbar.addWidget(self.edit_roll_zoom_label)

        self.btn_roll_zin = QPushButton("+")
        self.btn_roll_zin.setFixedSize(28, 28)
        self.btn_roll_zin.setStyleSheet(
            f"QPushButton {{ border-radius: 14px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 14px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        self.btn_roll_zin.clicked.connect(lambda: self._edit_roll_zoom(1))
        toolbar.addWidget(self.btn_roll_zin)

        page_layout.addLayout(toolbar)

        # ════════════════════════════════════════════════════
        #  属性面板 + 状态栏
        # ════════════════════════════════════════════════════
        props_bar = QHBoxLayout()
        props_bar.setSpacing(12)

        # 选中音符信息
        self._edit_info_label = QLabel("未选中音符")
        self._edit_info_label.setStyleSheet(
            f"font-size: 11px; color: {t['text_secondary']}; border: none; padding: 2px 8px;"
            f" background-color: {t['surface']}; border-radius: 4px;")
        props_bar.addWidget(self._edit_info_label)

        # 音符数量
        self._edit_count_label = QLabel("音符: 0")
        self._edit_count_label.setStyleSheet(
            f"font-size: 11px; color: {t['text_secondary']}; border: none;")
        props_bar.addWidget(self._edit_count_label)

        props_bar.addStretch()

        # 力度编辑（选中音符时可用）
        vel_label = QLabel("力度:")
        vel_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none;")
        props_bar.addWidget(vel_label)

        self._edit_vel_slider = QSlider(Qt.Horizontal)
        self._edit_vel_slider.setRange(1, 127)
        self._edit_vel_slider.setValue(80)
        self._edit_vel_slider.setFixedWidth(100)
        self._edit_vel_slider.setEnabled(False)
        self._edit_vel_slider.setToolTip("调整选中音符力度")
        self._edit_vel_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border: 1px solid {t['slider_groove']}; height: 4px;
                background: {t['slider_groove']}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {t['slider_handle']}; border: none; width: 12px;
                margin: -4px 0; border-radius: 6px;
            }}
            QSlider::handle:horizontal:disabled {{
                background: {t['label_disabled']};
            }}
        """)
        self._edit_vel_slider.valueChanged.connect(self._on_edit_vel_changed)
        props_bar.addWidget(self._edit_vel_slider)

        self._edit_vel_label = QLabel("80")
        self._edit_vel_label.setFixedWidth(24)
        self._edit_vel_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none;")
        props_bar.addWidget(self._edit_vel_label)

        page_layout.addLayout(props_bar)

        # ════════════════════════════════════════════════════
        #  主内容区：五线谱 + 钢琴卷帘
        # ════════════════════════════════════════════════════
        splitter = QSplitter(Qt.Vertical)

        # ── 五线谱卡片 ──
        sheet_card = QFrame()
        sheet_card.setObjectName("editSheetCard")
        self._edit_sheet_card = sheet_card
        sheet_card.setStyleSheet(
            f"QFrame#editSheetCard {{ background-color: {t['sheet_card_bg']}; border-radius: 12px; border: 1px solid {t['card_border']}; }}")
        sheet_layout = QVBoxLayout(sheet_card)
        sheet_layout.setContentsMargins(6, 6, 6, 2)
        sheet_layout.setSpacing(2)

        sheet_toolbar = QHBoxLayout()
        sheet_toolbar.setContentsMargins(6, 2, 6, 2)
        sheet_title = QLabel("五线谱预览")
        self._edit_sheet_title = sheet_title
        sheet_title.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {t['text_primary']}; border: none;")
        sheet_toolbar.addWidget(sheet_title)
        sheet_toolbar.addStretch()

        btn_edit_zout = QPushButton("−")
        btn_edit_zout.setFixedSize(26, 26)
        self._btn_edit_zout = btn_edit_zout
        btn_edit_zout.setStyleSheet(
            f"QPushButton {{ border-radius: 13px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 14px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        btn_edit_zout.clicked.connect(lambda: (self.edit_sheet_widget.zoom_out(),
                                               self._update_edit_zoom_label()))
        sheet_toolbar.addWidget(btn_edit_zout)

        self.edit_zoom_label = QLabel("1.0x")
        self.edit_zoom_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 10px; min-width: 32px; border: none;")
        sheet_toolbar.addWidget(self.edit_zoom_label)

        btn_edit_zin = QPushButton("+")
        btn_edit_zin.setFixedSize(26, 26)
        self._btn_edit_zin = btn_edit_zin
        btn_edit_zin.setStyleSheet(
            f"QPushButton {{ border-radius: 13px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 14px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        btn_edit_zin.clicked.connect(lambda: (self.edit_sheet_widget.zoom_in(),
                                               self._update_edit_zoom_label()))
        sheet_toolbar.addWidget(btn_edit_zin)

        sheet_layout.addLayout(sheet_toolbar)

        self.edit_sheet_widget = SheetMusicWidget()
        self.edit_sheet_widget.rendering_done.connect(
            lambda: self._show_status("编辑乐谱渲染完成", 3000))
        sheet_layout.addWidget(self.edit_sheet_widget, 1)

        splitter.addWidget(sheet_card)

        # ── 可编辑钢琴卷帘卡片 ──
        roll_card = QFrame()
        roll_card.setObjectName("editRollCard")
        self._edit_roll_card = roll_card
        roll_card.setStyleSheet(
            f"QFrame#editRollCard {{ background-color: {t['roll_card_bg']}; border-radius: 12px; border: 1px solid {t['card_border']}; }}")
        roll_layout = QVBoxLayout(roll_card)
        roll_layout.setContentsMargins(4, 4, 4, 4)
        roll_layout.setSpacing(0)

        self.edit_piano_roll = EditablePianoRollWidget()
        self.edit_piano_roll.notes_about_to_change.connect(self._pre_edit_save)
        self.edit_piano_roll.notes_changed.connect(self._on_edit_notes_changed)
        self.edit_piano_roll.selection_changed.connect(self._on_edit_selection_changed)
        self.edit_piano_roll.note_hovered.connect(self._on_edit_note_hovered)
        roll_layout.addWidget(self.edit_piano_roll, 1)

        splitter.addWidget(roll_card)

        splitter.setSizes([350, 450])
        page_layout.addWidget(splitter, 1)

        self.stacked_widget.addWidget(page)

    def _update_edit_zoom_label(self):
        self.edit_zoom_label.setText(f"{self.edit_sheet_widget.zoom:.1f}x")

    def _edit_roll_zoom(self, direction):
        """缩放编辑钢琴卷帘。direction: 1=放大, -1=缩小"""
        roll = self.edit_piano_roll
        if direction > 0:
            roll.pixels_per_second = min(400, roll.pixels_per_second * 1.2)
        else:
            roll.pixels_per_second = max(20, roll.pixels_per_second / 1.2)
        zoom_val = roll.pixels_per_second / 80.0
        self.edit_roll_zoom_label.setText(f"{zoom_val:.1f}x")
        roll.update()

    def _on_edit_tool_changed(self, tool_id):
        """编辑工具切换回调。"""
        self.edit_piano_roll.edit_tool = tool_id
        tool_names = {0: '选择', 1: '铅笔', 2: '橡皮'}
        self.logger.info(f'编辑工具切换: {tool_names.get(tool_id, "?")}')

    def _on_snap_toggled(self, checked):
        """吸附开关切换。"""
        self.edit_piano_roll.snap_enabled = checked

    def _on_edit_selection_changed(self):
        """选中状态变化回调。"""
        sel = self.edit_piano_roll.selected_indices
        notes = self.edit_piano_roll.display_notes
        count = len(sel)

        if count == 0:
            self._edit_info_label.setText("未选中音符")
            self._edit_vel_slider.setEnabled(False)
        elif count == 1:
            idx = next(iter(sel))
            if idx < len(notes):
                n = notes[idx]
                name = EditablePianoRollWidget.get_note_name(n['pitch'])
                dur = n['end'] - n['start']
                self._edit_info_label.setText(
                    f"{name}  起始:{n['start']:.2f}s  时长:{dur:.2f}s  力度:{n['velocity']}")
                self._edit_vel_slider.setEnabled(True)
                self._edit_vel_slider.blockSignals(True)
                self._edit_vel_slider.setValue(n['velocity'])
                self._edit_vel_label.setText(str(n['velocity']))
                self._edit_vel_slider.blockSignals(False)
        else:
            self._edit_info_label.setText(f"已选中 {count} 个音符")
            # 多选时显示平均力度
            vels = [notes[i]['velocity'] for i in sel if i < len(notes)]
            if vels:
                avg_vel = int(sum(vels) / len(vels))
                self._edit_vel_slider.setEnabled(True)
                self._edit_vel_slider.blockSignals(True)
                self._edit_vel_slider.setValue(avg_vel)
                self._edit_vel_label.setText(str(avg_vel))
                self._edit_vel_slider.blockSignals(False)

        self._edit_count_label.setText(f"音符: {len(notes)}")
        # 更新播放按钮状态
        self.btn_edit_play.setEnabled(len(notes) > 0)

    def _on_edit_note_hovered(self, idx):
        """音符悬停回调。"""
        # 信息由 selection_changed 处理，此处仅用于日志
        pass

    def _on_edit_vel_changed(self, value):
        """力度滑块变化回调。"""
        sel = self.edit_piano_roll.selected_indices
        if not sel:
            return
        self.edit_piano_roll.notes_about_to_change.emit()
        for idx in sel:
            if idx < len(self.edit_piano_roll.display_notes):
                note = self.edit_piano_roll.display_notes[idx]
                self.edit_piano_roll.display_notes[idx] = {
                    'pitch': note['pitch'],
                    'start': note['start'],
                    'end': note['end'],
                    'velocity': value
                }
        self._edit_vel_label.setText(str(value))
        self.edit_piano_roll.update()
        self.edit_piano_roll.notes_changed.emit()

    def _quantize_edit_notes(self):
        """量化选中音符。"""
        roll = self.edit_piano_roll
        if not roll.selected_indices:
            self._show_status("请先选中音符再量化", 2000)
            return
        roll.quantize_selected()
        self._show_status(f"已量化 {len(roll.selected_indices)} 个音符", 2000)

    def _play_edit_audio(self):
        """播放编辑页面的音频（合成当前音符）。"""
        roll = self.edit_piano_roll
        if not roll.display_notes:
            return

        # 保留原始velocity（保留音色），统一音量在合成后处理
        notes = list(roll.display_notes)
        need_normalize = hasattr(self, '_vel_mode_group') and self._vel_mode_group.checkedId() == 1

        # 合成音频
        try:
            import pygame
            midi = pretty_midi.PrettyMIDI()
            inst = pretty_midi.Instrument(program=0)
            for n in notes:
                inst.notes.append(pretty_midi.Note(
                    velocity=n['velocity'], pitch=n['pitch'],
                    start=n['start'], end=n['end']
                ))
            midi.instruments.append(inst)

            # 合成音频：优先高质量加法合成，有大SF2时用FluidSynth
            sf2_path = self._find_best_soundfont()
            audio = None
            if sf2_path and os.path.getsize(sf2_path) > 10 * 1024 * 1024:
                try:
                    import io
                    _old_stderr = sys.stderr
                    sys.stderr = io.StringIO()
                    try:
                        audio = midi.fluidsynth(fs=self.audio_sr, synthesizer=sf2_path)
                    finally:
                        sys.stderr = _old_stderr
                    if len(audio.shape) > 1:
                        audio = audio.mean(axis=1)
                    audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
                except Exception:
                    audio = None

            if audio is None:
                try:
                    audio = self._synthesize_piano_from_notes(notes, fs=self.audio_sr)
                except Exception:
                    audio = midi.synthesize(fs=self.audio_sr)
                    audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)

            # 统一音量模式：对合成后音频做音量归一化
            if need_normalize and audio is not None:
                try:
                    audio = self._normalize_audio_volume(audio)
                except Exception:
                    pass

            # 写入临时 WAV
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=self.audio_sr, size=-16, channels=1, buffer=4096)
            pygame.mixer.music.stop()
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass

            tmp = os.path.join(tempfile.gettempdir(), f'_edit_playback_{os.getpid()}.wav')
            with wave.open(tmp, 'w') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.audio_sr)
                wf.writeframes(audio.tobytes())
            self._edit_playback_wav = tmp
            pygame.mixer.music.load(tmp)
            pygame.mixer.music.play()

            # 启动钢琴卷帘播放动画
            roll.start_playback(0)
            self.btn_edit_stop.setEnabled(True)
            self.btn_edit_play.setEnabled(False)
            self._show_status("正在播放...")

            # 监控播放结束
            self._edit_play_timer = QTimer(self)
            self._edit_play_timer.setInterval(200)
            self._edit_play_timer.timeout.connect(self._check_edit_playback)
            self._edit_play_timer.start()

        except Exception as e:
            self.logger.error(f'编辑播放失败: {e}')
            self._show_status(f"播放失败: {e}", 3000)

    def _stop_edit_audio(self):
        """停止编辑页面播放。"""
        self.edit_piano_roll.stop_playback()
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
        except Exception:
            pass

        # 清理临时文件
        if hasattr(self, '_edit_playback_wav') and self._edit_playback_wav:
            try:
                os.remove(self._edit_playback_wav)
            except Exception:
                pass
            self._edit_playback_wav = None

        if hasattr(self, '_edit_play_timer') and self._edit_play_timer:
            self._edit_play_timer.stop()

        self.btn_edit_play.setEnabled(len(self.edit_piano_roll.display_notes) > 0)
        self.btn_edit_stop.setEnabled(False)
        self._show_status("已停止")

    def _check_edit_playback(self):
        """检查编辑播放是否结束。"""
        try:
            import pygame
            if not pygame.mixer.music.get_busy():
                self._stop_edit_audio()
        except Exception:
            self._stop_edit_audio()

    def _on_edit_notes_changed(self):
        """音符修改后回调：更新UI状态和重新渲染五线谱。"""
        self.btn_undo_edit.setEnabled(len(self._edit_history) > 0)
        self.btn_redo_edit.setEnabled(len(self._edit_redo_history) > 0)
        self._edit_render_timer.start()
        # 更新音符计数和播放按钮
        count = len(self.edit_piano_roll.display_notes)
        self._edit_count_label.setText(f"音符: {count}")
        self.btn_edit_play.setEnabled(count > 0)
        self.btn_export_mid.setEnabled(count > 0)

    def _pre_edit_save(self):
        """编辑前保存状态（用于撤销）。"""
        import copy
        current_notes = copy.deepcopy(self.edit_piano_roll.display_notes)
        current_track_info = dict(self.edit_piano_roll.track_info)
        current_selection = set(self.edit_piano_roll.selected_indices)
        self._edit_history.append((current_notes, current_track_info, current_selection))
        if len(self._edit_history) > self._edit_history_max:
            self._edit_history.pop(0)
        # 新操作清空重做栈
        self._edit_redo_history.clear()
        self.btn_redo_edit.setEnabled(False)

    def _undo_edit(self):
        """撤销。"""
        if not self._edit_history:
            return
        import copy
        # 保存当前状态到重做栈
        current_notes = copy.deepcopy(self.edit_piano_roll.display_notes)
        current_track_info = dict(self.edit_piano_roll.track_info)
        current_selection = set(self.edit_piano_roll.selected_indices)
        self._edit_redo_history.append((current_notes, current_track_info, current_selection))

        notes, track_info, selection = self._edit_history.pop()
        self.edit_piano_roll.display_notes = notes
        self.edit_piano_roll.track_info = track_info
        self.edit_piano_roll.selected_indices = selection
        self.edit_piano_roll.update()
        self.btn_undo_edit.setEnabled(len(self._edit_history) > 0)
        self.btn_redo_edit.setEnabled(len(self._edit_redo_history) > 0)
        self._edit_render_timer.start()
        self._on_edit_selection_changed()

    def _redo_edit(self):
        """重做。"""
        if not self._edit_redo_history:
            return
        import copy
        # 保存当前状态到撤销栈
        current_notes = copy.deepcopy(self.edit_piano_roll.display_notes)
        current_track_info = dict(self.edit_piano_roll.track_info)
        current_selection = set(self.edit_piano_roll.selected_indices)
        self._edit_history.append((current_notes, current_track_info, current_selection))

        notes, track_info, selection = self._edit_redo_history.pop()
        self.edit_piano_roll.display_notes = notes
        self.edit_piano_roll.track_info = track_info
        self.edit_piano_roll.selected_indices = selection
        self.edit_piano_roll.update()
        self.btn_undo_edit.setEnabled(len(self._edit_history) > 0)
        self.btn_redo_edit.setEnabled(len(self._edit_redo_history) > 0)
        self._edit_render_timer.start()
        self._on_edit_selection_changed()

    def keyPressEvent(self, event):
        """处理全局快捷键。"""
        if self.stacked_widget.currentIndex() == 2:  # 编辑页面
            key = event.key()
            mods = event.modifiers()

            # Ctrl+Z: 撤销
            if mods & Qt.ControlModifier and key == Qt.Key_Z and not (mods & Qt.ShiftModifier):
                self._undo_edit()
                return
            # Ctrl+Y 或 Ctrl+Shift+Z: 重做
            if (mods & Qt.ControlModifier and key == Qt.Key_Y) or \
               (mods & Qt.ControlModifier and mods & Qt.ShiftModifier and key == Qt.Key_Z):
                self._redo_edit()
                return
            # V: 选择工具
            if key == Qt.Key_V and not mods:
                self._edit_tool_group.button(0).setChecked(True)
                self._on_edit_tool_changed(0)
                return
            # P: 铅笔工具
            if key == Qt.Key_P and not mods:
                self._edit_tool_group.button(1).setChecked(True)
                self._on_edit_tool_changed(1)
                return
            # E: 橡皮工具
            if key == Qt.Key_E and not mods:
                self._edit_tool_group.button(2).setChecked(True)
                self._on_edit_tool_changed(2)
                return
            # Q: 量化
            if key == Qt.Key_Q and not mods:
                self._quantize_edit_notes()
                return
            # S: 吸附切换
            if key == Qt.Key_S and not mods:
                self.btn_snap.toggle()
                return
            # Space: 播放/停止
            if key == Qt.Key_Space and not mods:
                if self.btn_edit_stop.isEnabled():
                    self._stop_edit_audio()
                elif self.btn_edit_play.isEnabled():
                    self._play_edit_audio()
                return

            # 其他快捷键交给 EditablePianoRollWidget 处理
            self.edit_piano_roll.keyPressEvent(event)
            return

        super().keyPressEvent(event)

    def _refresh_edit_sheet_music(self):
        """Re-render the edit page sheet music from current edit notes."""
        notes = self.edit_piano_roll.display_notes
        if not notes:
            return

        # Create a temporary MIDI file from the current edit notes
        try:
            tmp_mid = os.path.join(tempfile.gettempdir(), f'_edit_preview_{os.getpid()}.mid')
            self.edit_piano_roll.save_midi_file(tmp_mid)
            self.edit_sheet_widget.load_midi(tmp_mid, '专业')
        except Exception as e:
            self.logger.error(f'编辑乐谱刷新失败: {e}')

    def _import_midi_edit(self):
        """Import a MIDI file into the edit page."""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入MIDI文件", "",
            "MIDI文件 (*.mid *.midi);;所有文件 (*)"
        )
        if path:
            try:
                self.edit_piano_roll.load_midi_file(path)
                self.btn_export_mid.setEnabled(True)
                self._refresh_edit_sheet_music()
                self._show_status(f"已导入: {os.path.basename(path)}")
                self.logger.info(f'导入MIDI: {path}')
            except Exception as e:
                self.logger.error(f'导入MIDI失败: {path}, 错误: {e}')
                QMessageBox.critical(self, "导入失败", f"无法导入MIDI文件:\n{e}")

    def _export_midi_edit(self):
        """Export the edited notes as a MIDI file."""
        if not self.edit_piano_roll.display_notes:
            QMessageBox.warning(self, "提示", "没有可导出的音符")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出MIDI", "edited.mid",
            "MIDI文件 (*.mid);;所有文件 (*)"
        )
        if save_path:
            try:
                self.edit_piano_roll.save_midi_file(save_path)
                self._show_status(f"已导出: {save_path}")
                self.logger.info(f'导出MIDI(编辑): {save_path}')
                QMessageBox.information(self, "导出成功", f"MIDI已保存到:\n{save_path}")
            except Exception as e:
                self.logger.error(f'导出MIDI失败: {save_path}, 错误: {e}')
                QMessageBox.critical(self, "导出失败", f"无法导出MIDI文件:\n{e}")

    # ================================================================
    #  NAVIGATION
    # ================================================================
    def _go_back(self, target_page):
        """Go back to the specified page (typically main menu)."""
        # Stop any playback before navigating
        self.stop_midi()
        self._switch_page(target_page)

    # ================================================================
    #  MENU
    # ================================================================
    def _setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        file_menu.addAction("选择音频", self.select_audio, "Ctrl+O")
        file_menu.addAction("导出 MIDI", self.export_midi, "Ctrl+S")
        file_menu.addSeparator()
        file_menu.addAction("返回主页", lambda: self._go_back(0))
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close, "Ctrl+Q")
        help_menu = menubar.addMenu("帮助")
        help_menu.addAction("关于", self.show_about)

    def _update_zoom_label(self):
        self.zoom_label.setText(f"{self.sheet_widget.zoom:.1f}x")

    def _update_cursor_display(self):
        t = self.sheet_widget.cursor_time
        dur = self.sheet_widget.duration
        self.cursor_time_label.setText(
            f"光标: {t:.1f}秒 / {dur:.1f}秒")
        # Sync piano roll cursor
        self.piano_roll.cursor_time = t
        if self.sheet_widget.is_playing:
            # Auto-scroll piano roll: cursor at keyboard top (no look-ahead)
            self.piano_roll.scroll_y = t
            self.piano_roll.update()

    def _build_track_info(self, midi_path, display_notes=None):
        """Build track_info dict mapping note index to track index.
        Returns empty dict if MIDI has only 1 instrument (use pitch-based coloring).
        Returns {note_index: track_index} for multi-instrument MIDI.
        If display_notes is provided, rebuilds track_info for the filtered subset."""
        try:
            midi = pretty_midi.PrettyMIDI(midi_path)
            if len(midi.instruments) <= 1:
                return {}
            # Build mapping: collect all notes with their instrument index,
            # sort by start time (matching display_notes order), then map
            all_notes_with_track = []
            for inst_idx, inst in enumerate(midi.instruments):
                for n in inst.notes:
                    all_notes_with_track.append({
                        'pitch': n.pitch,
                        'start': n.start,
                        'end': n.end,
                        'velocity': n.velocity,
                        'track': inst_idx
                    })
            all_notes_with_track.sort(key=lambda n: (n['start'], n['pitch']))

            if display_notes is None:
                # No filtering: build track_info for all notes
                track_info = {}
                for idx, note in enumerate(all_notes_with_track):
                    track_info[idx] = note['track']
                return track_info

            # Build track_info for the filtered display_notes subset
            # For each note in display_notes, find its instrument by matching pitch/start/end
            track_info = {}
            for idx, dn in enumerate(display_notes):
                best_match = None
                for orig in all_notes_with_track:
                    if (abs(orig['pitch'] - dn['pitch']) < 0.5 and
                            abs(orig['start'] - dn['start']) < 0.001 and
                            abs(orig['end'] - dn['end']) < 0.001):
                        best_match = orig['track']
                        break
                if best_match is not None:
                    track_info[idx] = best_match
                else:
                    track_info[idx] = 0
            return track_info
        except Exception:
            return {}

    # === Denoise settings ===
    def _on_denoise_mode_changed(self, mode):
        """Switch between auto and manual denoise mode."""
        self.denoise_mode = mode
        manual_enabled = (mode == 'manual')
        has_midi = self.midi_path is not None
        self.slider_threshold.setEnabled(manual_enabled and has_midi)
        self.slider_min_duration.setEnabled(manual_enabled and has_midi)
        self.slider_chord_strictness.setEnabled(manual_enabled and has_midi)
        self.slider_max_jump.setEnabled(manual_enabled and has_midi)
        self.slider_max_polyphony.setEnabled(manual_enabled and has_midi)
        self.btn_reset_denoise.setEnabled(manual_enabled and has_midi)
        # Update label colors using theme
        t = get_theme()
        label_color = t['text_primary'] if manual_enabled else t['label_disabled']
        for lbl in [self.label_threshold_val, self.label_min_duration_val,
                     self.label_chord_val, self.label_max_poly_val]:
            lbl.setStyleSheet(f"font-size: 11px; color: {label_color}; border: none; min-width: 32px;")
        self.label_max_jump_val.setStyleSheet(f"font-size: 11px; color: {label_color}; border: none; min-width: 38px;")
        # Apply button is enabled only when we have a midi_path and manual mode
        self.btn_apply_denoise.setEnabled(manual_enabled and self.midi_path is not None)

    def _reset_denoise(self):
        """Reset all denoise sliders to default values."""
        self.slider_threshold.setValue(25)
        self.slider_min_duration.setValue(80)
        self.slider_chord_strictness.setValue(25)
        self.slider_max_jump.setValue(12)
        self.slider_max_polyphony.setValue(6)

    def _apply_denoise(self):
        """Re-run denoising with current parameters and reload the result."""
        if not self.midi_path:
            return

        # Determine work directory and file names
        work_dir = self.work_dir
        audio_name = os.path.splitext(os.path.basename(self.audio_path or self.midi_path))[0]

        # Find the original accomp MIDI (before cleaning)
        accomp_mid = os.path.join(work_dir, f"{audio_name}_accomp.mid")
        if not os.path.exists(accomp_mid):
            # Fallback: use the current midi_path as input
            self.logger.warning("降噪: 未找到原始伴奏MIDI，使用当前MIDI作为输入")
            accomp_mid = self.midi_path

        accomp_cleaned = accomp_mid.replace('.mid', '_cleaned.mid')

        # Get parameters
        if self.denoise_mode == 'auto':
            params = {
                'removal_threshold': 0.25,
                'min_duration_ms': 80,
                'chord_strictness': 0.25,
                'max_jump_semitones': 12,
                'max_polyphony': 6,
            }
        else:
            params = {
                'removal_threshold': self.slider_threshold.value() / 100.0,
                'min_duration_ms': self.slider_min_duration.value(),
                'chord_strictness': self.slider_chord_strictness.value() / 100.0,
                'max_jump_semitones': self.slider_max_jump.value(),
                'max_polyphony': self.slider_max_polyphony.value(),
            }

        self.btn_apply_denoise.setEnabled(False)
        self._show_status("正在应用降噪...")

        def _worker():
            try:
                sys.path.insert(0, APP_DIR)
                from split_transcribe_merge import clean_accompaniment_strict, merge_midi_smart

                # Re-run denoising with custom parameters (only the strict clean step)
                clean_accompaniment_strict(
                    accomp_mid, accomp_cleaned,
                    removal_threshold=params['removal_threshold'],
                    min_duration_ms=params['min_duration_ms'],
                    chord_strictness=params['chord_strictness'],
                    max_jump_semitones=params['max_jump_semitones'],
                    max_polyphony=params['max_polyphony'],
                )

                # Skip clean_midi_post for speed — it's the slow part due to
                # gap protection with audio RMS checking, and it keeps restoring
                # notes that the user just removed. Use the merged result directly.
                if self.current_mode == 'accomp':
                    output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                    shutil.copy2(accomp_cleaned, output_mid)
                else:
                    # Standard mode: re-merge with vocals, skip post-clean
                    vocal_mid = os.path.join(work_dir, f"{audio_name}_vocal.mid")
                    if os.path.exists(vocal_mid):
                        merged_mid = os.path.join(work_dir, f"{audio_name}_merged.mid")
                        merge_midi_smart(accomp_cleaned, vocal_mid, merged_mid)
                        output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                        shutil.copy2(merged_mid, output_mid)
                    else:
                        output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                        shutil.copy2(accomp_cleaned, output_mid)

                # Emit result on main thread
                self.signals_denoise.finished.emit(output_mid)

            except Exception as e:
                self.logger.error(f'降噪出错: {str(e)}\n{traceback.format_exc()}')
                self.signals_denoise.error.emit(f"降噪出错: {str(e)}")

        # Create signals for denoise worker — keep strong references to prevent GC
        signals = WorkerSignals()
        signals.finished.connect(self._on_denoise_finished)
        signals.error.connect(self._on_denoise_error)
        self.signals_denoise = signals  # Also keep as instance attr for easy access

        thread = threading.Thread(target=_worker, daemon=True)
        # Store (thread, signals) tuple to prevent GC while thread is running
        if not hasattr(self, '_denoise_workers'):
            self._denoise_workers = []
        self._denoise_workers.append((thread, signals))
        # Clean up completed workers
        self._denoise_workers = [(t, s) for t, s in self._denoise_workers if t.is_alive()]
        thread.start()

    def _on_denoise_finished(self, midi_path):
        """Handle denoise completion - reload MIDI into displays."""
        self.midi_path = midi_path
        self.btn_apply_denoise.setEnabled(self.denoise_mode == 'manual')

        # Clear old audio and disable play until new synthesis completes
        with self._audio_lock:
            self.audio_data = None
        self.btn_play.setEnabled(False)

        # Reload into sheet widget
        self.sheet_widget.load_midi(midi_path, self.current_difficulty)

        # Reload into piano roll
        track_info = self._build_track_info(midi_path, self.sheet_widget.display_notes)
        self.piano_roll.load_notes(self.sheet_widget.display_notes,
                                   self.sheet_widget.duration,
                                   track_info)

        # Re-synthesize audio
        self._synthesize_for_playback()

        # Update stats
        midi = pretty_midi.PrettyMIDI(midi_path)
        all_notes = []
        for inst in midi.instruments:
            all_notes.extend(inst.notes)
        duration = midi.get_end_time()
        if all_notes:
            self.stats_label.setText(
                f"音符: {len(all_notes)}\n"
                f"时长: {duration:.1f}秒 ({duration / 60:.1f}分钟)\n"
                f"密度: {len(all_notes) / max(duration, 1):.1f} 音/秒\n"
                f"音域: {min(n.pitch for n in all_notes)}-"
                f"{max(n.pitch for n in all_notes)} "
                f"({max(n.pitch for n in all_notes) - min(n.pitch for n in all_notes)} 半音)"
            )
        t = get_theme()
        self.stats_label.setStyleSheet(f"font-size: 13px; color: {t['accent']}; border: none;")

        self._show_status("降噪完成", 3000)

    def _on_denoise_error(self, message):
        """Handle denoise error."""
        self.btn_apply_denoise.setEnabled(self.denoise_mode == 'manual')
        self._show_status("降噪失败")
        self.logger.error(f'降噪错误: {message}')
        QMessageBox.critical(self, "降噪错误", message)

    def _on_difficulty_button_clicked(self, difficulty):
        """Handle difficulty button group click."""
        self.current_difficulty = difficulty
        self.logger.info(f'难度切换: {difficulty}')
        # Update button styles
        for diff, btn in self.diff_buttons.items():
            if diff == difficulty:
                btn.setObjectName("diffBtnSelected")
                btn.setChecked(True)
            else:
                btn.setObjectName("diffBtn")
                btn.setChecked(False)
            # Force style refresh
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

        if self.midi_path:
            # Stop any current playback first to release audio resources
            self.stop_midi()

            # Clear old audio and disable play until new synthesis completes
            with self._audio_lock:
                self.audio_data = None
            self.btn_play.setEnabled(False)

            # Step 1: Apply difficulty - updates display_notes
            self.sheet_widget.apply_difficulty(difficulty)
            # Step 2: Load simplified notes into piano roll
            track_info = self._build_track_info(self.midi_path, self.sheet_widget.display_notes) if self.midi_path else {}
            self.piano_roll.load_notes(self.sheet_widget.display_notes,
                                       self.sheet_widget.duration,
                                       track_info)
            # Step 3: Re-synthesize audio from the UPDATED display_notes
            self._synthesize_for_playback()

    # === Drag & Drop ===
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith(('.wav', '.mp3', '.flac', '.ogg', '.m4a')):
                self.audio_path = path
                name = os.path.basename(path)
                self.audio_label.setText(name)
                t = get_theme()
                self.audio_label.setStyleSheet(
                    f"font-size: 14px; color: {t['accent']}; font-weight: bold; border: none;")
                self._show_status(f"已选择: {name}")
                self.logger.info(f'拖放音频: {path}')

    # === Actions ===
    def select_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择音频文件", "",
            "音频文件 (*.wav *.mp3 *.flac *.ogg *.m4a);;所有文件 (*)"
        )
        if path:
            self.audio_path = path
            name = os.path.basename(path)
            self.audio_label.setText(name)
            t = get_theme()
            self.audio_label.setStyleSheet(
                f"font-size: 14px; color: {t['accent']}; font-weight: bold; border: none;")
            self._show_status(f"已选择: {name}")
            self.logger.info(f'音频选择: {path}')

    def start_analysis(self):
        if not self.audio_path:
            QMessageBox.warning(self, "提示", "请先选择音频文件")
            return
        if self.is_processing:
            return

        self.logger.info(f'分析开始: 音频={self.audio_path}, 模式={self.current_mode}, 难度={self.current_difficulty}')

        self.is_processing = True
        self.btn_analyze.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("正在分析...")
        self.stats_label.setText("正在分析中，请稍候...")
        t = get_theme()
        self.stats_label.setStyleSheet(f"font-size: 13px; color: {t['accent']}; border: none;")

        # Update mode indicator
        self.mode_indicator.setText(f"{self._mode_label(self.current_mode)}模式")

        self.signals = WorkerSignals()
        self.signals.progress.connect(self._on_progress)
        self.signals.finished.connect(self._on_finished)
        self.signals.error.connect(self._on_error)

        thread = threading.Thread(target=self._run_analysis, daemon=True)
        thread.start()

    def _run_analysis(self):
        try:
            sys.path.insert(0, APP_DIR)
            from split_transcribe_merge import (
                separate_audio, transcribe_accompaniment, transcribe_vocals,
                merge_midi_smart, clean_midi_post, clean_accompaniment_strict
            )

            audio_name = os.path.splitext(os.path.basename(self.audio_path))[0]
            work_dir = self.work_dir

            self.signals.progress.emit(5, "正在分离人声和伴奏 (BS-RoFormer)...")
            vocals_path, accomp_path = separate_audio(
                self.audio_path, work_dir, skip_if_exists=True)
            if not vocals_path or not accomp_path:
                self.signals.error.emit("音频分离失败")
                return

            # Mode-dependent analysis
            if self.current_mode == 'accomp':
                # Accompaniment only mode
                self.signals.progress.emit(25, "正在转录伴奏 (Transkun)...")
                accomp_mid = os.path.join(work_dir, f"{audio_name}_accomp.mid")
                result = transcribe_accompaniment(accomp_path, accomp_mid)
                if not result:
                    self.signals.error.emit("伴奏转录失败")
                    return
                # Apply strict accompaniment cleaning
                self.signals.progress.emit(60, "正在降噪优化伴奏...")
                accomp_cleaned = accomp_mid.replace('.mid', '_cleaned.mid')
                clean_accompaniment_strict(accomp_mid, accomp_cleaned)
                # Skip vocal transcription and merge, use cleaned accomp directly
                output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                clean_midi_post(accomp_cleaned, output_mid)
                self.signals.progress.emit(100, "分析完成!")
                self.signals.finished.emit(output_mid)
                return

            elif self.current_mode == 'vocal':
                # Vocal only mode
                self.signals.progress.emit(25, "正在转录人声 (Basic Pitch)...")
                vocal_mid = os.path.join(work_dir, f"{audio_name}_vocal.mid")
                result = transcribe_vocals(vocals_path, vocal_mid)
                if not result:
                    self.signals.error.emit("人声转录失败")
                    return
                output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                clean_midi_post(vocal_mid, output_mid)
                self.signals.progress.emit(100, "分析完成!")
                self.signals.finished.emit(output_mid)
                return

            # Standard mode: full analysis
            self.signals.progress.emit(25, "正在转录伴奏 (Transkun)...")
            accomp_mid = os.path.join(work_dir, f"{audio_name}_accomp.mid")
            result = transcribe_accompaniment(accomp_path, accomp_mid)
            if not result:
                self.signals.error.emit("伴奏转录失败")
                return

            # Apply strict accompaniment cleaning
            self.signals.progress.emit(40, "正在降噪优化伴奏...")
            accomp_cleaned = accomp_mid.replace('.mid', '_cleaned.mid')
            clean_accompaniment_strict(accomp_mid, accomp_cleaned)
            accomp_mid = accomp_cleaned

            self.signals.progress.emit(55, "正在转录人声 (Basic Pitch)...")
            vocal_mid = os.path.join(work_dir, f"{audio_name}_vocal.mid")
            result = transcribe_vocals(vocals_path, vocal_mid)
            if not result:
                self.signals.error.emit("人声转录失败")
                return

            self.signals.progress.emit(80, "正在合并乐谱...")
            merged_mid = os.path.join(work_dir, f"{audio_name}_merged.mid")
            merge_midi_smart(accomp_mid, vocal_mid, merged_mid)

            self.signals.progress.emit(95, "正在清理和优化...")
            output_mid = os.path.join(work_dir, f"{audio_name}.mid")
            clean_midi_post(merged_mid, output_mid)

            self.signals.progress.emit(100, "分析完成!")
            self.signals.finished.emit(output_mid)

        except Exception as e:
            self.logger.error(f'分析出错: {str(e)}\n{traceback.format_exc()}')
            self.signals.error.emit(f"分析出错: {str(e)}\n{traceback.format_exc()}")

    def _on_progress(self, percent, message):
        self._animate_progress(percent)
        self.progress_label.setText(message)
        self.logger.debug(f'分析进度: {percent}% - {message}')

    def _on_finished(self, midi_path):
        self.midi_path = midi_path
        self.is_processing = False

        # Clear old audio data immediately so playback doesn't use stale data
        with self._audio_lock:
            self.audio_data = None

        self.logger.info(f'分析完成: 输出文件={midi_path}')
        self.btn_analyze.setEnabled(True)
        self.btn_select.setEnabled(True)
        self.btn_play.setEnabled(False)  # Disabled until synthesis completes
        self.btn_export.setEnabled(True)
        self.btn_apply_denoise.setEnabled(self.denoise_mode == 'manual')

        self._show_status("正在渲染乐谱 (LilyPond)...")

        # Load into sheet widget with current difficulty
        # Note: LilyPond rendering is async, zoom_fit will be called after SVG loads
        self.sheet_widget.load_midi(midi_path, self.current_difficulty)

        # Start cursor timer if not already running
        if not self._cursor_timer.isActive():
            self._cursor_timer.start()

        # Load into piano roll
        # Build track_info from MIDI: map note index to track index
        track_info = self._build_track_info(midi_path, self.sheet_widget.display_notes)
        self.piano_roll.load_notes(self.sheet_widget.display_notes,
                                   self.sheet_widget.duration,
                                   track_info)

        # Synthesize audio for playback (uses sheet_widget.display_notes
        # which was set by apply_difficulty inside load_midi)
        self._synthesize_for_playback()

        # Grade difficulty
        level, name, color, detail = grade_difficulty(midi_path)
        self.diff_level.setText(str(level))
        self.diff_level.setStyleSheet(
            f"font-size: 56px; font-weight: bold; color: {color}; border: none;")
        self.diff_level.setProperty("dynamic_color", color)
        self.diff_name.setText(name)
        self.diff_name.setStyleSheet(
            f"font-size: 18px; color: {color}; font-weight: bold; border: none;")
        self.diff_name.setProperty("dynamic_color", color)
        self.diff_detail.setText(detail)
        t = get_theme()
        self.diff_detail.setStyleSheet(f"font-size: 11px; color: {t['info_diff_detail']}; border: none;")

        # Stats
        midi = pretty_midi.PrettyMIDI(midi_path)
        all_notes = []
        for inst in midi.instruments:
            all_notes.extend(inst.notes)
        duration = midi.get_end_time()
        if all_notes:
            self.stats_label.setText(
                f"音符: {len(all_notes)}\n"
                f"时长: {duration:.1f}秒 ({duration / 60:.1f}分钟)\n"
                f"密度: {len(all_notes) / max(duration, 1):.1f} 音/秒\n"
                f"音域: {min(n.pitch for n in all_notes)}-"
                f"{max(n.pitch for n in all_notes)} "
                f"({max(n.pitch for n in all_notes) - min(n.pitch for n in all_notes)} 半音)"
            )
        else:
            self.stats_label.setText(
                f"音符: 0\n"
                f"时长: {duration:.1f}秒 ({duration / 60:.1f}分钟)\n"
                f"密度: 0 音/秒\n"
                f"音域: 无"
            )
        self.stats_label.setStyleSheet(f"font-size: 13px; color: {t['info_stats_text']}; border: none;")

        self._show_status(f"分析完成 - {os.path.basename(midi_path)}")

    def _on_error(self, message):
        self.is_processing = False
        self.btn_analyze.setEnabled(True)
        self.btn_select.setEnabled(True)
        self.progress_label.setText("分析失败")
        self.stats_label.setText("分析失败，请重试")
        t = get_theme()
        self.stats_label.setStyleSheet(f"font-size: 13px; color: {t['danger']}; border: none;")
        self.logger.error(f'分析错误: {message}')
        QMessageBox.critical(self, "错误", message)
        self._show_status("分析失败")

    def _on_vel_mode_changed(self, btn_id, checked):
        """音量模式切换回调。"""
        if not checked:
            return
        uniform = (btn_id == 1)
        self._uniform_vel_slider.setVisible(uniform)
        self._uniform_vel_label.setVisible(uniform)
        # 切换模式时重新合成
        if self.sheet_widget.display_notes:
            self._synthesize_for_playback()

    def _apply_velocity_mode(self, notes):
        """根据音量模式处理音符力度。
        原始力度模式：保留原始velocity（保留音色差异）
        统一音量模式：也保留原始velocity（保留音色），但标记需要在合成后做音量归一化
        """
        return notes

    def _normalize_audio_volume(self, audio):
        """对音频做音量归一化，使所有时刻的音量趋于一致，同时保留音色。"""
        if audio is None or len(audio) == 0:
            return audio
        # 使用短时能量归一化：将音频分帧，每帧归一化到相同RMS
        frame_len = int(self.audio_sr * 0.05)  # 50ms帧
        hop = frame_len // 2
        if len(audio) < frame_len:
            return audio

        # 计算每帧RMS
        n_frames = (len(audio) - frame_len) // hop + 1
        target_rms = np.sqrt(np.mean(audio.astype(np.float64) ** 2))  # 全局RMS作为目标
        if target_rms < 1:
            return audio

        # 逐帧计算增益并平滑
        gains = np.ones(len(audio), dtype=np.float64)
        for i in range(n_frames):
            start = i * hop
            end = start + frame_len
            frame = audio[start:end].astype(np.float64)
            rms = np.sqrt(np.mean(frame ** 2))
            if rms > 10:  # 只对有声部分做归一化
                gain = target_rms / rms
                gain = min(gain, 4.0)  # 限制最大增益，避免过度放大
                gains[start:end] = gain

        # 平滑增益曲线（避免咔嗒声）
        from scipy.ndimage import uniform_filter1d
        gains = uniform_filter1d(gains, size=hop * 2)

        result = (audio.astype(np.float64) * gains)
        result = np.clip(result, -32768, 32767).astype(np.int16)
        return result

    def _synthesize_for_playback(self, notes=None):
        """Synthesize audio from the current difficulty-simplified notes.
        Runs in a background thread to avoid UI freezing.

        Args:
            notes: Optional list of note dicts to synthesize. If None,
                   reads from self.sheet_widget.display_notes (may cause
                   thread safety issues if called from a background thread).
        """
        self.logger.info(f'[_synthesize_for_playback] 开始, notes={"None" if notes is None else len(notes)}')
        if notes is None:
            notes = list(self.sheet_widget.display_notes) if self.sheet_widget.display_notes else None
        if not notes:
            with self._audio_lock:
                self.audio_data = None
            return

        # 应用音量模式
        notes = self._apply_velocity_mode(notes)

        # 检查是否需要统一音量
        need_normalize = hasattr(self, '_vel_mode_group') and self._vel_mode_group.checkedId() == 1

        def _worker():
            # Create a new PrettyMIDI from simplified notes (保留原始velocity以保留音色)
            midi = pretty_midi.PrettyMIDI()
            inst = pretty_midi.Instrument(program=0)  # Acoustic Grand Piano
            for n in notes:
                inst.notes.append(pretty_midi.Note(
                    velocity=n['velocity'], pitch=n['pitch'],
                    start=n['start'], end=n['end']
                ))
            midi.instruments.append(inst)

            audio = None
            # 优先使用高质量加法合成（比 FluidSynth+TimGM6mb 音色更好）
            # 如果有高质量 SF2 文件，则优先 FluidSynth
            sf2_path = self._find_best_soundfont()
            if sf2_path and os.path.getsize(sf2_path) > 10 * 1024 * 1024:
                # 大于10MB的SF2音色库，使用FluidSynth
                try:
                    import io
                    _old_stderr = sys.stderr
                    sys.stderr = io.StringIO()
                    try:
                        audio = midi.fluidsynth(fs=self.audio_sr, synthesizer=sf2_path)
                    finally:
                        sys.stderr = _old_stderr
                    if len(audio.shape) > 1:
                        audio = audio.mean(axis=1)
                    audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
                    self.logger.info(f'使用 FluidSynth+{os.path.basename(sf2_path)} 合成 ({len(notes)} 音符)')
                except Exception as e:
                    self.logger.warning(f'FluidSynth 合成失败 ({e})，使用加法合成')
                    audio = None

            if audio is None:
                try:
                    audio = self._synthesize_piano_from_notes(notes, fs=self.audio_sr)
                    self.logger.info(f'使用高质量加法合成 ({len(notes)} 音符)')
                except Exception as e2:
                    self.logger.warning(f'加法合成失败 ({e2})，使用基础合成')
                    try:
                        audio = midi.synthesize(fs=self.audio_sr)
                        audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
                    except Exception:
                        audio = None

            # 统一音量模式：对合成后音频做音量归一化（保留音色，只拉平音量）
            if audio is not None and need_normalize:
                try:
                    audio = self._normalize_audio_volume(audio)
                    self.logger.info('已应用统一音量归一化')
                except Exception as e:
                    self.logger.warning(f'音量归一化失败 ({e})，使用原始音频')

            with self._audio_lock:
                self.audio_data = audio

            # Enable play button after synthesis completes (thread-safe via signal bridge)
            try:
                _synthesis_bridge.done.emit()
            except Exception:
                pass

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    @Slot()
    def _enable_play_after_synthesis(self):
        """Called on main thread after audio synthesis completes."""
        with self._audio_lock:
            has_audio = self.audio_data is not None
        self.btn_play.setEnabled(has_audio)
        self.logger.info(f'合成完成回调: has_audio={has_audio}, btn_enabled={has_audio}')
        if has_audio:
            self._show_status("音频合成完成，可以播放", 3000)

    def _find_best_soundfont(self):
        """查找系统中可用的最佳 SF2 音色库文件。"""
        import glob
        candidates = []

        # 1. 应用目录下的 sf2 文件
        app_dir = os.path.dirname(os.path.abspath(__file__))
        for f in glob.glob(os.path.join(app_dir, '*.sf2')):
            candidates.append(f)

        # 2. pretty_midi 自带的音色库
        try:
            import pretty_midi
            pm_dir = os.path.dirname(pretty_midi.__file__)
            for f in glob.glob(os.path.join(pm_dir, '*.sf2')):
                candidates.append(f)
        except Exception:
            pass

        # 3. FluidSynth 默认安装目录
        for d in [os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp', 'fluidsynth', 'share', 'soundfonts'),
                   r'C:\Program Files\FluidSynth\share\soundfonts',
                   r'C:\Program Files (x86)\FluidSynth\share\soundfonts']:
            if os.path.isdir(d):
                for f in glob.glob(os.path.join(d, '*.sf2')):
                    candidates.append(f)

        if not candidates:
            return None

        # 选择最大的文件（通常音色更好）
        candidates.sort(key=lambda f: os.path.getsize(f), reverse=True)
        best = candidates[0]
        size_mb = os.path.getsize(best) / 1024 / 1024
        self.logger.info(f'找到音色库: {os.path.basename(best)} ({size_mb:.1f} MB)')
        return best

    def _synthesize_piano_from_notes(self, notes, fs=44100):
        """高质量加法合成钢琴音色，模拟真实钢琴的谐波结构、力度响应和衰减特性。"""
        if not notes:
            return np.zeros(0, dtype=np.int16)

        max_end = max(n['end'] for n in notes)
        duration = max_end + 2.0
        audio = np.zeros(int(duration * fs), dtype=np.float64)

        # 真实钢琴的谐波幅度（基于 Steinway D 测量数据）
        # 不同力度下谐波比例不同：弱音时基波占比高，强音时高次谐波更丰富
        for note in notes:
            freq = 440.0 * (2.0 ** ((note['pitch'] - 69) / 12.0))
            vel = note['velocity'] / 127.0
            note_dur = note['end'] - note['start']
            n_samples = int(note_dur * fs)
            if n_samples <= 0 or freq < 20 or freq > 8000:
                continue

            t = np.arange(n_samples) / fs

            # ── 力度相关的谐波结构 ──
            # 弱音(vel~0.2): 基波为主，高次谐波弱
            # 强音(vel~1.0): 高次谐波丰富，模拟锤击力度增大
            base_harmonics = [1.0, 0.58, 0.35, 0.20, 0.12, 0.07, 0.04, 0.025,
                              0.015, 0.01, 0.006, 0.004]
            # 强音时增强高次谐波
            brightness = 0.3 + 0.7 * vel  # 0.3~1.0
            harmonics = []
            for i, h in enumerate(base_harmonics):
                # 高次谐波随力度增强
                boost = brightness ** (i * 0.3)
                harmonics.append(h * boost)

            # ── 非谐波成分（琴弦刚度导致的泛音偏移）──
            # 真实钢琴的高次泛音频率略高于整数倍
            inharmonicity_B = 0.00004  # 典型值，高音区更大
            if note['pitch'] > 60:
                inharmonicity_B *= (1 + (note['pitch'] - 60) * 0.02)

            signal = np.zeros(n_samples)
            for h_idx, h_amp in enumerate(harmonics):
                partial_num = h_idx + 1
                # 非谐波频率偏移: f_n = n * f1 * sqrt(1 + B*n^2)
                h_freq = partial_num * freq * np.sqrt(1 + inharmonicity_B * partial_num ** 2)
                if h_freq > fs / 2:
                    break
                signal += h_amp * np.sin(2 * np.pi * h_freq * t)

            # ── ADSR 包络（模拟钢琴锤击-衰减特性）──
            # 钢琴特点：无持续 sustain，只有衰减
            # 攻击时间极短（锤击），然后指数衰减
            attack_time = 0.003  # 3ms 极短攻击
            # 衰减时间与音高相关：低音衰减慢，高音衰减快
            decay_rate = 3.0 + (note['pitch'] - 21) * 0.08  # 低音~3s, 高音~9s
            decay_time = min(note_dur, 8.0)  # 最长8秒衰减

            envelope = np.zeros(n_samples)
            attack_samples = int(attack_time * fs)
            if attack_samples > 0 and attack_samples < n_samples:
                envelope[:attack_samples] = np.linspace(0, 1, attack_samples)
                envelope[attack_samples:] = np.exp(
                    -decay_rate * (t[attack_samples:] - t[attack_samples]))
            else:
                envelope = np.exp(-decay_rate * t)

            # 释放段：音符结束时快速衰减
            release_time = 0.03  # 30ms 释放
            release_samples = int(release_time * fs)
            if release_samples > 0 and release_samples < n_samples:
                envelope[-release_samples:] *= np.linspace(1, 0, release_samples)

            signal *= envelope * vel * 0.12

            # ── 添加微量噪声模拟锤击噪声 ──
            hammer_noise = np.random.randn(n_samples) * 0.002 * vel
            hammer_env = np.exp(-80 * t)  # 极快衰减
            signal += hammer_noise * hammer_env

            start_sample = int(note['start'] * fs)
            end_sample = start_sample + n_samples
            if end_sample <= len(audio):
                audio[start_sample:end_sample] += signal

        # 归一化
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.9

        return np.clip(audio * 32767, -32768, 32767).astype(np.int16)

    def play_midi(self):
        if not self.sheet_widget.display_notes:
            return

        self.logger.info(f'播放开始: 光标时间={self.sheet_widget.cursor_time:.1f}秒')

        # Check if currently playing (before stopping)
        was_playing = self.sheet_widget.is_playing

        # Stop any current playback first (does not reset cursor_time)
        self.stop_midi()

        # If not previously playing and cursor is at/past end, reset to beginning
        if not was_playing and self.sheet_widget.cursor_time >= self.sheet_widget.duration:
            self.sheet_widget.reset_cursor()
            self.piano_roll.cursor_time = 0

        # Start sheet music playback
        self.sheet_widget.start_playback()

        # Start piano roll playback
        self.piano_roll.start_playback(self.sheet_widget.cursor_time)

        # Play audio using pygame
        with self._audio_lock:
            audio_data = self.audio_data
        self.logger.info(f'播放音频: audio_data={"None" if audio_data is None else f"{len(audio_data)} samples"}')
        if audio_data is not None:
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init(frequency=self.audio_sr, size=-16,
                                      channels=1, buffer=4096)
                    self.logger.info(f'pygame.mixer 初始化: freq={self.audio_sr}, size=-16, channels=1')
                else:
                    self.logger.info(f'pygame.mixer 已初始化: {pygame.mixer.get_init()}')
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass

                start_sample = int(self.sheet_widget.cursor_time * self.audio_sr)
                segment = audio_data[start_sample:]
                self.logger.info(f'播放片段: start_sample={start_sample}, segment_len={len(segment)}, peak={np.max(np.abs(segment)) if len(segment) > 0 else 0}')
                if len(segment) > 0:
                    # Use unique temp file to avoid permission conflicts
                    tmp = os.path.join(tempfile.gettempdir(),
                                       f'_piano_playback_{os.getpid()}.wav')
                    with wave.open(tmp, 'w') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(self.audio_sr)
                        wf.writeframes(segment.tobytes())
                    self._playback_tmp_wav = tmp
                    self.logger.info(f'写入WAV: {tmp}, size={os.path.getsize(tmp)} bytes')
                    pygame.mixer.music.load(tmp)
                    pygame.mixer.music.play()
                    self.logger.info(f'pygame.mixer.music.play() 已调用, busy={pygame.mixer.music.get_busy()}')
                else:
                    self.logger.warning('播放片段为空，跳过音频播放')
            except Exception as e:
                self.logger.error(f'音频播放失败: {e}')
                import traceback
                self.logger.error(traceback.format_exc())
        else:
            self.logger.warning('audio_data 为 None，无法播放音频')

        self.btn_stop.setEnabled(True)
        self._show_status("正在播放...")

    def stop_midi(self):
        self.logger.info('播放停止')
        self.sheet_widget.stop_playback()
        self.piano_roll.stop_playback()
        self._cursor_timer.stop()

        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
        except Exception:
            pass

        # Clean up temp WAV file
        if self._playback_tmp_wav:
            try:
                os.remove(self._playback_tmp_wav)
            except Exception:
                pass
            self._playback_tmp_wav = None

        self.btn_stop.setEnabled(False)
        self._show_status("已停止")

    def export_midi(self):
        if not self.midi_path:
            return

        # Export the current difficulty-simplified MIDI
        notes = self.sheet_widget.display_notes
        if not notes:
            QMessageBox.warning(self, "提示", "没有可导出的音符")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出 MIDI",
            os.path.splitext(os.path.basename(self.midi_path))[0] +
            f"_{self.current_difficulty}.mid",
            "MIDI文件 (*.mid);;所有文件 (*)"
        )
        if save_path:
            # Create MIDI from simplified notes
            midi = pretty_midi.PrettyMIDI()
            track_info = self.piano_roll.track_info
            if track_info:
                # Multi-track export: split notes by track
                accomp_inst = pretty_midi.Instrument(program=0, name="Accompaniment")
                vocal_inst = pretty_midi.Instrument(program=0, name="Vocals")
                for idx, n in enumerate(notes):
                    note = pretty_midi.Note(
                        velocity=n['velocity'], pitch=n['pitch'],
                        start=n['start'], end=n['end']
                    )
                    if track_info.get(idx, 0) == 1:
                        vocal_inst.notes.append(note)
                    else:
                        accomp_inst.notes.append(note)
                midi.instruments.append(accomp_inst)
                midi.instruments.append(vocal_inst)
            else:
                # Single-track export
                inst = pretty_midi.Instrument(program=0)
                for n in notes:
                    inst.notes.append(pretty_midi.Note(
                        velocity=n['velocity'], pitch=n['pitch'],
                        start=n['start'], end=n['end']
                    ))
                midi.instruments.append(inst)
            midi.write(save_path)
            self._show_status(f"已导出: {save_path}")
            self.logger.info(f'导出MIDI: {save_path}, 难度={self.current_difficulty}')
            QMessageBox.information(self, "导出成功",
                                    f"MIDI已保存到:\n{save_path}\n难度: {self.current_difficulty}")

    def show_about(self):
        QMessageBox.about(self, "关于",
                          "钢琴乐谱生成器 v7.0\n\n"
                          "基于深度学习的音频转钢琴乐谱工具\n\n"
                          "模式:\n"
                          "- 标准模式: 伴奏+人声完整分析\n"
                          "- 弹唱模式: 仅伴奏转录\n"
                          "- 人声模式: 仅人声转录\n"
                          "- 编辑模式: 导入MIDI编辑\n\n"
                          "技术栈:\n"
                          "- BS-RoFormer: 人声/伴奏分离\n"
                          "- Transkun: 钢琴转录\n"
                          "- Basic Pitch: 人声转录模型\n"
                          "- LilyPond: 专业五线谱渲染\n"
                          "- 泛音链过滤 + 智能后处理\n\n"
                          "UI: HarmonyOS 6.1 风格"
                          )


class SplashWidget(QWidget):
    """Animated splash screen: icon falls from top, then explodes into blue-green flowers and grass.
    White background, ~5 second total animation."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedSize(640, 480)
        self.setStyleSheet("background: white;")

        self._icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pianoscribe_splash_icon.png')
        self._icon_pixmap = QPixmap(self._icon_path) if os.path.exists(self._icon_path) else None

        # Animation state - timing designed for ~5 seconds total
        # Phase 0: falling ~1.5s, Phase 1: bounce ~0.5s, Phase 2: flowers grow ~2.5s, Phase 3: hold ~0.5s
        self._phase = 0  # 0=falling, 1=impact, 2=flowers, 3=hold, 4=done
        self._time = 0
        self._icon_y = -200.0
        self._icon_target_y = 180.0
        self._icon_x = 320.0
        self._fall_speed = 0.0
        self._particles = []
        self._flowers = []
        self._grass = []
        self._impact_done = False
        self._hold_frames = 0

        # Timer at 60fps
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._time += 1
        if self._phase == 0:
            # Falling with gentle gravity (~1.5s)
            self._fall_speed += 0.6
            self._icon_y += self._fall_speed
            if self._icon_y >= self._icon_target_y:
                self._icon_y = self._icon_target_y
                self._phase = 1
                self._impact_done = False
                self._create_explosion()
        elif self._phase == 1:
            # Impact bounce (~0.5s)
            if not self._impact_done:
                self._impact_done = True
                self._fall_speed = -5
            self._fall_speed += 0.8
            self._icon_y += self._fall_speed
            if self._icon_y >= self._icon_target_y:
                self._icon_y = self._icon_target_y
                if self._fall_speed > 0:
                    self._phase = 2
                    self._spawn_flowers_and_grass()
        elif self._phase == 2:
            # Grow flowers and grass (~2.5s = ~150 frames at 60fps)
            for f in self._flowers:
                f['growth'] = min(f['growth'] + 0.015, 1.0)
                f['sway'] = math.sin(self._time * 0.04 + f['phase']) * 4
            for g in self._grass:
                g['growth'] = min(g['growth'] + 0.02, 1.0)
                g['sway'] = math.sin(self._time * 0.06 + g['phase']) * 3
            # Fade particles
            for pt in self._particles:
                pt['life'] -= 0.012
                pt['x'] += pt['vx']
                pt['y'] += pt['vy']
                pt['vy'] += 0.12
            self._particles = [pt for pt in self._particles if pt['life'] > 0]
            # Check if growth is done
            if all(f['growth'] >= 1.0 for f in self._flowers) and all(g['growth'] >= 1.0 for g in self._grass):
                self._phase = 3
                self._hold_frames = 0
        elif self._phase == 3:
            # Hold for ~0.5s then finish
            self._hold_frames += 1
            # Keep swaying
            for f in self._flowers:
                f['sway'] = math.sin(self._time * 0.04 + f['phase']) * 4
            for g in self._grass:
                g['sway'] = math.sin(self._time * 0.06 + g['phase']) * 3
            if self._hold_frames >= 30:
                self._phase = 4
                self._timer.stop()
        self.update()

    def _create_explosion(self):
        """Create explosion particles on impact."""
        import random
        for _ in range(50):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(2, 10)
            self._particles.append({
                'x': self._icon_x,
                'y': self._icon_y + 90,
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed - 3,
                'life': 1.0,
                'color': random.choice([
                    QColor(80, 210, 180, 255),
                    QColor(100, 240, 200, 255),
                    QColor(60, 190, 160, 255),
                    QColor(120, 230, 210, 255),
                    QColor(160, 245, 200, 255),
                    QColor(90, 200, 230, 255),
                ]),
                'size': random.uniform(4, 10),
            })

    def _spawn_flowers_and_grass(self):
        """Spawn blue-green flowers and grass around the icon."""
        import random
        # Flowers
        for _ in range(14):
            self._flowers.append({
                'x': self._icon_x + random.uniform(-240, 240),
                'y': self._icon_y + 90 + random.uniform(20, 90),
                'size': random.uniform(14, 30),
                'petals': random.randint(5, 8),
                'color': random.choice([
                    QColor(60, 200, 170),
                    QColor(80, 230, 200),
                    QColor(100, 195, 245),
                    QColor(130, 220, 200),
                    QColor(70, 185, 155),
                    QColor(110, 210, 245),
                ]),
                'center_color': QColor(255, 225, 80),
                'growth': 0.0,
                'phase': random.uniform(0, math.pi * 2),
                'sway': 0,
                'stem_h': random.uniform(35, 65),
            })
        # Grass blades
        for _ in range(35):
            self._grass.append({
                'x': self._icon_x + random.uniform(-280, 280),
                'y': self._icon_y + 90 + random.uniform(40, 110),
                'height': random.uniform(25, 55),
                'width': random.uniform(2, 5),
                'color': random.choice([
                    QColor(50, 175, 120),
                    QColor(65, 195, 140),
                    QColor(85, 215, 155),
                    QColor(55, 185, 125),
                    QColor(40, 155, 100),
                ]),
                'growth': 0.0,
                'phase': random.uniform(0, math.pi * 2),
                'sway': 0,
            })

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()

        # White background with subtle warm gradient
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor('#ffffff'))
        bg.setColorAt(0.6, QColor('#f8fffe'))
        bg.setColorAt(1, QColor('#f0faf7'))
        p.fillRect(0, 0, w, h, bg)

        # Subtle radial glow behind icon area
        glow = QRadialGradient(w * 0.5, self._icon_target_y + 90, 200)
        glow.setColorAt(0, QColor(80, 200, 180, 25))
        glow.setColorAt(0.5, QColor(60, 180, 160, 8))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, glow)

        # Draw grass (behind icon)
        for g in self._grass:
            if g['growth'] <= 0:
                continue
            p.setPen(Qt.NoPen)
            alpha = int(255 * min(g['growth'] * 1.5, 1.0))
            c = QColor(g['color'])
            c.setAlpha(alpha)
            p.setBrush(QBrush(c))
            cur_h = g['height'] * g['growth']
            sway = g['sway'] * g['growth']
            path = QPainterPath()
            bx = g['x']
            by = g['y']
            path.moveTo(bx, by)
            path.quadTo(bx + sway, by - cur_h * 0.5, bx + sway * 1.5, by - cur_h)
            path.quadTo(bx + sway + g['width'], by - cur_h * 0.5, bx + g['width'], by)
            path.closeSubpath()
            p.drawPath(path)

        # Draw flowers
        for f in self._flowers:
            if f['growth'] <= 0:
                continue
            alpha = int(255 * min(f['growth'] * 1.5, 1.0))
            # Stem
            stem_c = QColor(50, 155, 100, alpha)
            p.setPen(QPen(stem_c, 2.5))
            stem_top_x = f['x'] + f['sway']
            stem_top_y = f['y'] - f['stem_h'] * f['growth']
            p.drawLine(QPointF(f['x'], f['y']), QPointF(stem_top_x, stem_top_y))

            # Petals
            petal_size = f['size'] * f['growth']
            if petal_size > 1:
                p.setPen(Qt.NoPen)
                c = QColor(f['color'])
                c.setAlpha(alpha)
                p.setBrush(QBrush(c))
                for i in range(f['petals']):
                    angle = (2 * math.pi * i / f['petals']) + self._time * 0.008
                    px = stem_top_x + math.cos(angle) * petal_size * 0.55
                    py = stem_top_y + math.sin(angle) * petal_size * 0.55
                    p.drawEllipse(QPointF(px, py), petal_size * 0.4, petal_size * 0.28)

                # Center
                cc = QColor(f['center_color'])
                cc.setAlpha(alpha)
                p.setBrush(QBrush(cc))
                p.drawEllipse(QPointF(stem_top_x, stem_top_y), petal_size * 0.22, petal_size * 0.22)

        # Draw explosion particles
        for pt in self._particles:
            alpha = int(255 * pt['life'])
            c = QColor(pt['color'])
            c.setAlpha(alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(pt['x'], pt['y']), pt['size'] * pt['life'], pt['size'] * pt['life'])

        # Draw falling/landed icon
        icon_size = 180
        icon_x = self._icon_x - icon_size / 2
        icon_y = self._icon_y
        if self._icon_pixmap and not self._icon_pixmap.isNull():
            p.drawPixmap(QRectF(icon_x, icon_y, icon_size, icon_size), self._icon_pixmap, QRectF(self._icon_pixmap.rect()))
        else:
            # Fallback: draw a circle with "PS"
            grad = QRadialGradient(self._icon_x, self._icon_y + icon_size / 2, icon_size / 2)
            grad.setColorAt(0, QColor(80, 200, 180))
            grad.setColorAt(1, QColor(40, 120, 100))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(grad))
            p.drawEllipse(QPointF(self._icon_x, self._icon_y + icon_size / 2), icon_size / 2, icon_size / 2)
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Segoe UI", 36, QFont.Bold))
            p.drawText(QRectF(icon_x, icon_y, icon_size, icon_size), Qt.AlignCenter, "PS")

        # Title text - dark teal on white
        title_font = QFont("Segoe UI", 36, QFont.Bold)
        p.setFont(title_font)
        title_grad = QLinearGradient(w * 0.15, 0, w * 0.85, 0)
        title_grad.setColorAt(0, QColor('#2dd4bf'))
        title_grad.setColorAt(0.5, QColor('#22d3ee'))
        title_grad.setColorAt(1, QColor('#34d399'))
        p.setPen(QPen(QBrush(title_grad), 1))
        p.drawText(QRectF(0, 25, w, 50), Qt.AlignCenter, "PianoScribe")

        # Subtitle
        sub_font = QFont("Segoe UI", 13)
        p.setFont(sub_font)
        p.setPen(QColor(80, 140, 130, 200))
        p.drawText(QRectF(0, 72, w, 25), Qt.AlignCenter, "专业AI钢琴乐谱生成器")

        # Version
        ver_font = QFont("Segoe UI", 10)
        p.setFont(ver_font)
        p.setPen(QColor(120, 160, 150, 150))
        p.drawText(QRectF(0, h - 28, w, 20), Qt.AlignCenter, "v8.0")

        p.end()

    def finish(self, window):
        """Close splash when main window is ready."""
        self._timer.stop()
        self.close()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Show animated splash screen (runs for ~5 seconds)
    splash = SplashWidget()
    splash.show()
    splash.repaint()
    app.processEvents()

    # Set palette from current theme
    t = get_theme()
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(t['bg']))
    palette.setColor(QPalette.WindowText, QColor(t['text_primary']))
    palette.setColor(QPalette.Base, QColor(t['card_bg']))
    palette.setColor(QPalette.AlternateBase, QColor(t['surface']))
    palette.setColor(QPalette.Text, QColor(t['text_primary']))
    palette.setColor(QPalette.Button, QColor(t['surface']))
    palette.setColor(QPalette.ButtonText, QColor(t['text_primary']))
    palette.setColor(QPalette.Highlight, QColor(t['accent']))
    palette.setColor(QPalette.HighlightedText, QColor('#FFFFFF'))
    app.setPalette(palette)

    app.setStyleSheet(STYLESHEET)

    # Pre-create main window (hidden) while splash animates
    window = PianoApp()

    # After splash animation finishes (~5s), show main window and close splash
    def _on_splash_done():
        window.show()
        splash.close()

    # Use a single-shot timer to ensure splash plays full 5 seconds
    QTimer.singleShot(5000, _on_splash_done)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
