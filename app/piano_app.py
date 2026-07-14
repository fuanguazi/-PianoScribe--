"""PianoScribe - Professional AI Piano Sheet Music Generator v0.7 beta

Liquid Glass UI - A modern translucent glass-morphism interface inspired by
Apple's Liquid Glass design language, featuring frosted-glass panels, soft
glows, depth layering and smooth fluid animations.

Features:
- Liquid Glass UI (translucent panels, blur effects, glass highlights, glow)
- Mode selection: Standard / Accompaniment / Vocal / Edit
- Professional staff notation (五线谱) rendering with LilyPond via SVG + QSvgRenderer
- Piano roll visualization with realistic 88-key keyboard (Synthesia-style)
- Editable piano roll (left-click delete, right-click add/drag notes)
- MIDI import/export in edit mode
- Liquid Glass animations (hover glow, lift + scale, page transition, button bounce)
- MIDI playback with FluidSynth / additive synthesis
- Difficulty grading with button group selector
- Difficulty-linked playback (display + audio + export all simplified)
- Zoom, scroll, playback cursor
- Keyboard shortcuts (Space=play/stop, Ctrl+E=export, Ctrl+O=open, Ctrl+T=theme)
- Export options: MIDI, WAV audio, SVG sheet music, LilyPond source (.ly)
- GlassFrame reusable translucent container with shadow & gradient highlight
"""

import sys
import os
import json

# 抑制 TensorFlow/oneDNN 信息输出
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
import shutil
import subprocess
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
    r'C:\tools\fluidsynth\bin',
    r'C:\tools\fluidsynth-temp\bin',
]
# Also search in PyInstaller bundle (sys._MEIPASS)
if getattr(sys, 'frozen', False):
    _meipass = sys._MEIPASS
    _fluidsynth_dll_dirs.insert(0, os.path.join(_meipass, 'fluidsynth_bin'))
    _fluidsynth_dll_dirs.insert(0, _meipass)
else:
    # Development: search project root fluidsynth/bin
    _proj_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _fluidsynth_dll_dirs.insert(0, os.path.join(_proj_dir, 'fluidsynth', 'bin'))
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
    QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QSplashScreen,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QTabWidget,
    QToolButton, QToolBar, QMenu, QRadioButton, QDialog, QLineEdit, QTextEdit
)
from PySide6.QtCore import (
    Qt, Signal, Slot, QObject, QTimer, QRectF, QPointF, QPropertyAnimation,
    QEasingCurve, QSize, QEvent, QParallelAnimationGroup, QPoint, Property
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QDragEnterEvent, QDropEvent,
    QPainter, QPen, QBrush, QWheelEvent, QMouseEvent,
    QPainterPath, QLinearGradient, QCursor, QRadialGradient, QPixmap,
    QConicalGradient, QKeySequence, QIcon, QAction, QShortcut
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene
from PySide6.QtCore import QIODevice

import numpy as np
import pretty_midi

# 确保 APP_DIR 在 sys.path 中，以便 import glass_ui
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# 真·Liquid Glass / 鸿蒙7 光感 UI 组件（基于网上真实实现方法）
from glass_ui import (
    AcrylicContainer, AcrylicBlurEngine, LiquidGlassFrame,
    HarmonyLightButton, CustomTitleBar,
    make_frameless, install_title_bar,
)

# ============================================================
#  THEME SYSTEM (Light / Dark dual-theme)
# ============================================================
_current_theme_name = 'light'

THEMES = {
    'light': {
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
        'cursor_color': '#FF3B30', 'cursor_glow': '#FFD700', 'note_right': '#3FA9C4', 'note_left': '#FF9500',
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
        # --- new design tokens (brand gradient / elevation / skeleton / scrollbar / tooltip / segment / ripple / empty state) ---
        'brand_gradient': 'qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3F95C0, stop:0.5 #3FB0A0, stop:1 #52BD8E)',
        'brand_gradient_hover': 'qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5BB0D8, stop:0.5 #5BC8B8, stop:1 #6FD3A8)',
        'brand_gradient_pressed': 'qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2B80AC, stop:0.5 #2B9080, stop:1 #3FAD7E)',
        'elevation_1': 'rgba(0, 0, 0, 0.04)',
        'elevation_2': 'rgba(0, 0, 0, 0.08)',
        'elevation_3': 'rgba(0, 0, 0, 0.12)',
        'skeleton_base': 'rgba(0, 0, 0, 0.05)',
        'skeleton_shimmer': 'rgba(255, 255, 255, 0.6)',
        'scrollbar_bg': 'rgba(0, 0, 0, 0.0)',
        'scrollbar_handle': 'rgba(0, 0, 0, 0.20)',
        'scrollbar_handle_hover': 'rgba(0, 0, 0, 0.35)',
        'tooltip_bg': 'rgba(28, 28, 30, 0.95)',
        'tooltip_text': '#F5F5F7',
        'tooltip_border': 'rgba(255, 255, 255, 0.10)',
        'segment_active_bg': '#3FA9C4',
        'segment_active_text': 'white',
        'segment_inactive_bg': 'rgba(255, 255, 255, 0.80)',
        'segment_inactive_text': '#86868B',
        'segment_border': 'rgba(0, 0, 0, 0.04)',
        'ripple_primary': 'rgba(255, 255, 255, 0.30)',
        'ripple_secondary': 'rgba(0, 0, 0, 0.08)',
        'empty_state_icon': 'rgba(0, 0, 0, 0.15)',
        'empty_state_text': '#86868B',
    },
    'dark': {
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
        'cursor_color': '#FF453A', 'cursor_glow': '#FFD700', 'note_right': '#4FBFD8', 'note_left': '#FF9F0A',
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
        # --- new design tokens (brand gradient / elevation / skeleton / scrollbar / tooltip / segment / ripple / empty state) ---
        'brand_gradient': 'qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5BA8C8, stop:0.5 #5BC8B8, stop:1 #6FD3A0)',
        'brand_gradient_hover': 'qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #75BBDA, stop:0.5 #75D6C8, stop:1 #89DDB0)',
        'brand_gradient_pressed': 'qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4790AC, stop:0.5 #47B0A0, stop:1 #5BBD8E)',
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
        'segment_active_text': 'white',
        'segment_inactive_bg': 'rgba(44, 44, 46, 0.75)',
        'segment_inactive_text': '#98989D',
        'segment_border': 'rgba(255, 255, 255, 0.06)',
        'ripple_primary': 'rgba(255, 255, 255, 0.30)',
        'ripple_secondary': 'rgba(255, 255, 255, 0.10)',
        'empty_state_icon': 'rgba(255, 255, 255, 0.15)',
        'empty_state_text': '#98989D',
    }
}


def get_theme():
    return THEMES.get(_current_theme_name, THEMES['light'])


def get_stylesheet(theme_name=None):
    if theme_name is None:
        theme_name = _current_theme_name
    t = THEMES[theme_name]
    accent2 = t.get('accent2', '#00C9A7')
    return f"""
/* ============================================================
   BASE
   ============================================================ */
QMainWindow {{ background-color: {t['bg']}; }}
QWidget {{ font-family: "HarmonyOS Sans", "Microsoft YaHei", "Segoe UI", sans-serif; color: {t['text_primary']}; outline: none; }}
*:focus {{ outline: none; }}
QPushButton:focus {{ outline: none; }}

/* ============================================================
   CARDS — unified radius.lg (16px)
   ============================================================ */
QGroupBox {{ background-color: {t['card_bg']}; border-radius: 16px; border: none; padding: 24px; }}
QFrame#cardFrame {{ background-color: {t['card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; padding: 0px; }}
QFrame#editSheetCard {{ background-color: {t['sheet_card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}
QFrame#editRollCard {{ background-color: {t['roll_card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}

/* ============================================================
   BUTTONS — 5 variants: default(secondary) / primary / ghost / danger / success
   Legacy aliases: btnPlay(brand gradient) / btnStop(danger) / btnExport(success)
   ============================================================ */
QPushButton {{ border-radius: 12px; padding: 10px 22px; font-size: 14px; background-color: {t['surface']}; border: 1px solid {t['border']}; color: {t['text_primary']}; min-height: 20px; }}
QPushButton:hover {{ background-color: {t['surface_hover']}; border: 1px solid {t['accent']}; }}
QPushButton:pressed {{ background-color: {t['surface_pressed']}; }}
QPushButton:disabled {{ background-color: {t['surface_disabled']}; color: {t['label_disabled']}; }}

/* primary — brand gradient */
QPushButton#primary {{ background-color: {t['brand_gradient']}; color: white; border: 1px solid {t['accent_pressed']}; border-radius: 12px; }}
QPushButton#primary:hover {{ background-color: {t['brand_gradient_hover']}; border: 1px solid {t['accent']}; }}
QPushButton#primary:pressed {{ background-color: {t['brand_gradient_pressed']}; }}
QPushButton#primary:disabled {{ background-color: {t['accent_disabled']}; color: white; }}

/* ghost — transparent with accent text */
QPushButton#ghost {{ background-color: transparent; color: {t['accent']}; border: none; border-radius: 12px; }}
QPushButton#ghost:hover {{ background-color: {t['accent_glow']}; color: {t['accent']}; }}
QPushButton#ghost:pressed {{ background-color: {t['accent_glow']}; }}
QPushButton#ghost:disabled {{ background-color: transparent; color: {t['label_disabled']}; }}

/* danger */
QPushButton#danger {{ background-color: {t['danger']}; color: white; border: none; border-radius: 12px; }}
QPushButton#danger:hover {{ background-color: {t['danger_hover']}; }}
QPushButton#danger:pressed {{ background-color: {t['danger_pressed']}; }}
QPushButton#danger:disabled {{ background-color: {t['danger_disabled']}; color: white; }}

/* success */
QPushButton#success {{ background-color: {t['success']}; color: white; border: none; border-radius: 12px; }}
QPushButton#success:hover {{ background-color: {t['success_hover']}; }}
QPushButton#success:pressed {{ background-color: {t['success_pressed']}; }}
QPushButton#success:disabled {{ background-color: {t['success_disabled']}; color: white; }}

/* btnPlay — alias using brand gradient */
QPushButton#btnPlay {{ background-color: {t['brand_gradient']}; color: white; border: none; border-radius: 12px; padding: 10px 24px; font-weight: bold; }}
QPushButton#btnPlay:hover {{ background-color: {t['brand_gradient_hover']}; }}
QPushButton#btnPlay:pressed {{ background-color: {t['brand_gradient_pressed']}; }}
QPushButton#btnPlay:disabled {{ background-color: {t['surface_disabled']}; color: {t['label_disabled']}; border: 1px solid {t['border']}; }}

/* btnStop — alias for danger */
QPushButton#btnStop {{ background-color: {t['danger']}; color: white; border: none; border-radius: 12px; padding: 10px 24px; font-weight: bold; }}
QPushButton#btnStop:hover {{ background-color: {t['danger_hover']}; }}
QPushButton#btnStop:pressed {{ background-color: {t['danger_pressed']}; }}
QPushButton#btnStop:disabled {{ background-color: {t['surface_disabled']}; color: {t['label_disabled']}; border: 1px solid {t['border']}; }}

/* btnExport — alias for success */
QPushButton#btnExport {{ background-color: {t['success']}; color: white; border: none; border-radius: 12px; padding: 10px 24px; font-weight: bold; }}
QPushButton#btnExport:hover {{ background-color: {t['success_hover']}; }}
QPushButton#btnExport:pressed {{ background-color: {t['success_pressed']}; }}
QPushButton#btnExport:disabled {{ background-color: {t['surface_disabled']}; color: {t['label_disabled']}; border: 1px solid {t['border']}; }}

/* diffBtn / diffBtnSelected — legacy, kept for backward compat (will migrate to segBtn) */
QPushButton#diffBtn {{ border-radius: 10px; padding: 8px 6px; font-size: 12px; background-color: {t['surface']}; border: 1px solid {t['diff_btn_border']}; color: {t['diff_btn_text']}; min-height: 18px; min-width: 50px; }}
QPushButton#diffBtn:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
QPushButton#diffBtnSelected {{ border-radius: 10px; padding: 8px 6px; font-size: 12px; background-color: {t['accent']}; color: white; border: none; font-weight: bold; min-height: 18px; min-width: 50px; }}
QPushButton#diffBtnSelected:hover {{ background-color: {t['accent_hover']}; }}

/* ============================================================
   SEGMENTED CONTROL — for difficulty selector + denoise mode toggle
   ============================================================ */
/* Standalone variant — each button has its own border */
QPushButton#segBtn {{ background-color: {t['segment_inactive_bg']}; color: {t['segment_inactive_text']}; border: 1px solid {t['segment_border']}; border-radius: 10px; padding: 8px 14px; font-size: 12px; min-height: 18px; }}
QPushButton#segBtn:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
QPushButton#segBtn:checked {{ background-color: {t['segment_active_bg']}; color: {t['segment_active_text']}; border: 1px solid {t['segment_active_bg']}; font-weight: bold; }}

/* Pill variant — group has outer border, buttons are borderless */
QFrame#segmentedControl {{ background-color: {t['segment_inactive_bg']}; border: 1px solid {t['segment_border']}; border-radius: 12px; padding: 4px; }}
QPushButton#segPill {{ background: transparent; border: none; border-radius: 8px; padding: 6px 12px; color: {t['segment_inactive_text']}; font-size: 12px; }}
QPushButton#segPill:hover {{ color: {t['accent']}; }}
QPushButton#segPill:checked {{ background-color: {t['accent']}; color: white; font-weight: bold; }}

/* ============================================================
   TOOL BUTTONS / TOOLBAR (radius.md = 12px)
   ============================================================ */
QToolButton {{ background-color: {t['surface']}; border: none; border-radius: 12px; padding: 8px 14px; color: {t['text_primary']}; }}
QToolButton:hover {{ background-color: {t['surface_hover']}; }}
QToolButton:pressed {{ background-color: {t['surface_pressed']}; }}
QToolButton:checked {{ background-color: {t['accent']}; color: white; border: none; }}
QToolBar {{ background-color: {t['menubar_bg']}; border: none; padding: 8px; spacing: 8px; }}

/* ============================================================
   INPUTS — Combo / Spin / DoubleSpin (radius.md = 12px)
   ============================================================ */
QComboBox {{ background-color: {t['input_bg']}; border: none; border-radius: 12px; padding: 10px 16px; color: {t['text_primary']}; min-height: 20px; }}
QComboBox:hover {{ background-color: {t['surface_hover']}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{ background-color: {t['card_bg']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 8px; selection-background-color: {t['menu_hover_bg']}; selection-color: {t['menu_hover_text']}; outline: none; }}
QSpinBox {{ background-color: {t['input_bg']}; border: none; border-radius: 12px; padding: 10px 14px; color: {t['text_primary']}; min-height: 20px; }}
QSpinBox:hover {{ background-color: {t['surface_hover']}; }}
QDoubleSpinBox {{ background-color: {t['input_bg']}; border: none; border-radius: 12px; padding: 10px 14px; color: {t['text_primary']}; min-height: 20px; }}
QDoubleSpinBox:hover {{ background-color: {t['surface_hover']}; }}

/* ============================================================
   TABS (radius.md = 12px)
   ============================================================ */
QTabWidget::pane {{ background-color: {t['card_bg']}; border: 1px solid {t['card_border']}; border-radius: 16px; padding: 12px; }}
QTabBar::tab {{ background-color: {t['surface']}; border: none; border-radius: 12px; padding: 10px 24px; color: {t['text_secondary']}; margin: 2px; }}
QTabBar::tab:hover {{ background-color: {t['surface_hover']}; color: {t['accent']}; }}
QTabBar::tab:selected {{ background-color: {t['accent']}; color: white; border: none; font-weight: bold; }}

/* ============================================================
   CHECKBOX / RADIO (indicator radius.sm = 8px)
   ============================================================ */
QCheckBox {{ color: {t['text_primary']}; spacing: 8px; }}
QCheckBox::indicator {{ width: 24px; height: 24px; border-radius: 8px; border: none; background-color: {t['input_bg']}; }}
QCheckBox::indicator:hover {{ background-color: {t['surface_hover']}; }}
QCheckBox::indicator:checked {{ background-color: {t['accent']}; border: none; image: none; }}
QRadioButton {{ color: {t['text_primary']}; spacing: 8px; }}
QRadioButton::indicator {{ width: 20px; height: 20px; border-radius: 10px; border: none; background-color: {t['input_bg']}; }}
QRadioButton::indicator:hover {{ background-color: {t['surface_hover']}; }}
QRadioButton::indicator:checked {{ background-color: {t['accent']}; border: none; }}

/* ============================================================
   PROGRESS BAR — gradient chunk + glow + animated stripes
   NOTE: QSS does not support box-shadow or animated stripes.
   Callers wanting glow should add a QGraphicsDropShadowEffect to
   the QProgressBar; for animated stripes/shimmer, animate via a
   QPropertyAnimation on the chunk's border-image or a custom
   paintEvent. The chunk gradient below is the static baseline.
   ============================================================ */
QProgressBar {{ border: none; border-radius: 8px; background-color: {t['progress_bg']}; height: 8px; text-align: center; font-size: 11px; color: {t['text_secondary']}; }}
QProgressBar::chunk {{ background: {t['brand_gradient']}; border-radius: 8px; }}

/* ============================================================
   SLIDER — groove gradient fill + brand-color handle
   ============================================================ */
QSlider::groove:horizontal {{ border: none; height: 6px; background: {t['slider_groove']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {t['brand_gradient']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {t['slider_handle']}; border: 3px solid white; width: 22px; margin: -8px 0; border-radius: 14px; }}
QSlider::handle:horizontal:hover {{ background: {t['accent_hover']}; border: 3px solid white; }}

/* ============================================================
   MENU / MENUBAR / STATUS / SPLITTER / SCROLLAREA
   ============================================================ */
QMenuBar {{ background-color: {t['menubar_bg']}; color: {t['text_primary']}; border-bottom: 1px solid {t['divider']}; padding: 6px; }}
QMenuBar::item {{ padding: 8px 20px; border-radius: 14px; }}
QMenuBar::item:selected {{ background-color: {t['surface_hover']}; }}
QMenu {{ background-color: {t['card_bg']}; color: {t['text_primary']}; border: 1px solid {t['border']}; border-radius: 12px; padding: 10px; }}
QMenu::item {{ padding: 8px 32px; border-radius: 14px; }}
QMenu::item:selected {{ background-color: {t['menu_hover_bg']}; color: {t['menu_hover_text']}; }}
QStatusBar {{ background-color: {t['status_bg']}; color: {t['status_text']}; border-top: 1px solid {t['divider']}; font-size: 11px; }}
QSplitter::handle {{ background-color: {t['divider']}; width: 2px; }}
QScrollArea {{ border: none; }}

/* ============================================================
   CUSTOM SCROLLBAR — thin, expand on hover
   ============================================================ */
QScrollBar:vertical {{ background: {t['scrollbar_bg']}; width: 8px; margin: 0; border-radius: 4px; }}
QScrollBar:vertical:hover {{ width: 12px; }}
QScrollBar::handle:vertical {{ background: {t['scrollbar_handle']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['scrollbar_handle_hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: transparent; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: {t['scrollbar_bg']}; height: 8px; margin: 0; border-radius: 4px; }}
QScrollBar:horizontal:hover {{ height: 12px; }}
QScrollBar::handle:horizontal {{ background: {t['scrollbar_handle']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {t['scrollbar_handle_hover']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; background: transparent; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ============================================================
   CUSTOM TOOLTIP — rounded + shadow + semi-transparent background
   ============================================================ */
QToolTip {{ background-color: {t['tooltip_bg']}; color: {t['tooltip_text']}; border: 1px solid {t['tooltip_border']}; border-radius: 8px; padding: 8px 12px; font-size: 12px; }}

/* ============================================================
   LABELS / THEME TOGGLE
   ============================================================ */
QLabel#cardTitle {{ font-size: 16px; font-weight: bold; color: {t['card_title_text']}; padding: 0px; }}
QLabel#cardSubtitle {{ font-size: 12px; color: {t['card_desc_text']}; }}
QLabel#statValue {{ font-size: 13px; color: {t['info_stats_text']}; }}
QPushButton#themeToggle {{ background-color: {t['toggle_btn_bg']}; border: none; border-radius: 22px; padding: 6px; font-size: 18px; color: {t['toggle_icon']}; min-width: 42px; max-width: 42px; min-height: 42px; max-height: 42px; }}
QPushButton#themeToggle:hover {{ background-color: {t['toggle_btn_hover']}; }}
"""

STYLESHEET = get_stylesheet()

# Global flag: True when a QGraphicsOpacityEffect animation is active,
# prevents QPainter conflicts from overlapping paint events.
_effect_animating = False


# ============================================================
#  PARTICLE BACKGROUND (浮动粒子背景 — 光点漂浮 + 多层辉光)
# ============================================================
def _widget_has_graphics_effect(widget):
    """检查 widget 或其任何父级是否挂载了 QGraphicsEffect（如淡入淡出动画）。
    
    额外检测：当有任何模态对话框打开时也返回 True，避免底层定时器 paintEvent
    与对话框绘制冲突产生 QPainter 刷屏。
    """
    if _effect_animating:
        return True
    if not widget.isVisible():
        return True
    if not widget.updatesEnabled():
        return True
    if QApplication.activeModalWidget() is not None:
        return True
    w = widget
    while w is not None:
        if w.graphicsEffect() is not None:
            return True
        w = w.parentWidget()
    return False


def _safe_update(widget):
    """安全地调用 widget.update()，避免 QPainter 冲突。
    
    在任何定时器驱动的 update() 调用前使用此函数，可防止：
    - 模态对话框打开时底层控件刷屏
    - QGraphicsEffect 渲染期间重复 update()
    - 不可见/已禁用的控件浪费绘制
    """
    if not _widget_has_graphics_effect(widget):
        widget.update()


class ParticleBackground(QWidget):
    """苹果风格浮动粒子背景 — 复刻启动界面的创意配方。

    特性：
    - QTimer 60fps 驱动
    - 多层 QRadialGradient 辉光叠加
    - 正弦运动参数化（每个粒子独立相位/振幅/速度）
    - 透明鼠标事件（不拦截交互）
    """
    def __init__(self, parent=None, particle_count=25):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._particles = []
        self._start_time = time.perf_counter()
        self._init_particles(particle_count)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30fps，时间驱动，帧率不影响速度

    def _init_particles(self, count):
        import random
        for _ in range(count):
            self._particles.append({
                'x': random.random(),
                'y': random.random(),
                'r': random.uniform(2.5, 7),
                'speed': random.uniform(0.00015, 0.0006),
                'phase': random.uniform(0, math.pi * 2),
                'amp': random.uniform(0.008, 0.025),
                'alpha': random.uniform(25, 70),
                'hue_shift': random.uniform(-0.05, 0.05),
            })

    def _tick(self):
        if not self.isVisible() or _widget_has_graphics_effect(self):
            return
        _safe_update(self)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        t = get_theme()
        accent = QColor(t['accent'])
        elapsed = time.perf_counter() - self._start_time  # 帧率无关
        for pt in self._particles:
            x = pt['x'] * w + math.sin(elapsed * 0.9 + pt['phase']) * pt['amp'] * w
            y_frac = (pt['y'] - elapsed * pt['speed']) % 1.0
            y = y_frac * h
            r = pt['r']
            c = QColor(accent)
            c.setHslF(
                (c.hueF() + pt['hue_shift']) % 1.0,
                c.saturationF(),
                c.lightnessF(),
                pt['alpha'] / 255.0
            )
            glow = QRadialGradient(x, y, r * 3.5)
            glow.setColorAt(0, c)
            c2 = QColor(c)
            c2.setAlpha(0)
            glow.setColorAt(1, c2)
            p.setBrush(QBrush(glow))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, y), r * 3.5, r * 3.5)
            # 中心亮点
            c3 = QColor(255, 255, 255)
            c3.setAlpha(int(pt['alpha'] * 1.5))
            p.setBrush(QBrush(c3))
            p.drawEllipse(QPointF(x, y), r * 0.4, r * 0.4)


# ============================================================
#  GLASS FRAME (真·Liquid Glass 容器 — 继承自 glass_ui.LiquidGlassFrame)
# ============================================================
class GlassFrame(LiquidGlassFrame):
    """真玻璃容器：截取父背景 + 高斯模糊 + 苹果 Liquid Glass 多层结构。

    保留原 GlassFrame API（radius 参数默认 20），但底层实现替换为
    真实背景模糊（scipy.ndimage.gaussian_filter）。
    """

    def __init__(self, parent=None, radius=20):
        super().__init__(parent=parent, radius=radius, blur_radius=18.0)

    def _update_style(self):
        # 兼容旧 API（被 _apply_theme 调用）
        self.invalidate_cache()
        self.update()

    def update_theme(self, theme_name):
        # 委托给 LiquidGlassFrame.update_theme
        super().update_theme(theme_name)


# ============================================================
#  GRADIENT TEXT LABEL (paints text with a brand-gradient fill)
# ============================================================
class GradientTextLabel(QLabel):
    """A QLabel that paints its text with a horizontal gradient fill.

    The gradient is supplied via `set_gradient(colors)` where `colors` is a
    list of `QColor` instances evenly spaced across the text width. Falls
    back to the default QLabel paint behaviour (solid `color:` from QSS) when
    no gradient has been set.
    """

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._gradient_stops = []  # list of (pos, QColor)

    def set_gradient(self, colors):
        """Set the gradient stops. `colors` is a list of QColors (evenly spaced)."""
        if not colors:
            self._gradient_stops = []
        else:
            n = max(1, len(colors) - 1)
            self._gradient_stops = [(i / n, c) for i, c in enumerate(colors)]
        self.update()

    def paintEvent(self, event):
        if not self._gradient_stops or not self.text():
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        font = self.font()
        p.setFont(font)
        fm = p.fontMetrics()
        text = self.text()
        text_width = fm.horizontalAdvance(text)

        align = self.alignment()
        if align & Qt.AlignHCenter:
            x = (self.width() - text_width) // 2
        elif align & Qt.AlignRight:
            x = self.width() - text_width
        else:
            x = 0
        if align & Qt.AlignVCenter:
            y = (self.height() + fm.ascent() - fm.descent()) // 2
        elif align & Qt.AlignBottom:
            y = self.height() - fm.descent()
        else:
            y = fm.ascent()

        # Horizontal gradient spanning the text width.
        grad = QLinearGradient(x, 0, x + text_width, 0)
        for pos, color in self._gradient_stops:
            grad.setColorAt(pos, color)

        p.setPen(QPen(QBrush(grad), 1))
        p.drawText(QPointF(x, y), text)


# ============================================================
#  MODE CARD (Liquid Glass style with hover glow + scale animation)
# ============================================================
class ModeCard(AcrylicContainer):
    """真玻璃模式卡片：继承 AcrylicContainer，应用真背景模糊 + 苹果多层高光。

    保留原有 hover 动画、clicked 信号、缩放效果。
    """
    clicked = Signal(str)  # emits mode name

    _NORMAL_STYLE = None  # Deprecated - using _apply_normal_style()
    _HOVER_STYLE = None   # Deprecated - using _apply_hover_style()

    def __init__(self, icon, title, desc, mode_name, parent=None):
        # 初始化真玻璃容器（radius=24, blur=18）
        super().__init__(parent=parent, radius=24, blur_radius=18.0,
                         tint=QColor(255, 255, 255, 38),
                         luminosity=QColor(255, 255, 255, 26))
        self.mode_name = mode_name
        self._hovered = False
        self._radius = 24
        self.setFixedSize(220, 180)
        self._t = 0
        self._glow_timer = QTimer(self)
        self._glow_timer.timeout.connect(self._glow_tick)
        self._glow_timer.start(50)  # ~20fps，始终运行以维持呼吸光效
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 20)
        layout.setSpacing(8)

        t = get_theme()

        # Icon — supports both emoji (legacy) and SVG icon names from app_icons.
        # An SVG name is detected when the first character is alphabetic.
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(56, 56)
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_name = None
        if isinstance(icon, str) and icon and icon[0].isalpha():
            # Treat as SVG icon name — render via app_icons.
            try:
                from app_icons import icon_pixmap
                from design_tokens import qcolor as _qcolor, tokens as _tokens
                _theme = _current_theme_name
                _accent = _qcolor(getattr(_tokens(_theme).color, 'accent', '#3FA9C4'))
                pm = icon_pixmap(icon, size=48, color=_accent, theme_name=_theme)
                self._icon_label.setPixmap(pm)
                self._icon_name = icon
                self._icon_label.setStyleSheet("border: none; background: transparent;")
            except Exception:
                # Fallback to emoji-style text if icon rendering fails.
                emoji_map = {"mic": "🎤", "waveform": "🎵", "piano": "🎹", "edit": "✏️", "music": "🎼", "settings": "⚙️", "play": "▶️", "stop": "⏹️", "export": "📤", "folder": "📁"}
                self._icon_label.setText(emoji_map.get(icon, "🎵"))
                self._icon_label.setStyleSheet("font-size: 40px; border: none; background: transparent;")
        else:
            self._icon_label.setText(icon)
            self._icon_label.setStyleSheet("font-size: 40px; border: none; background: transparent;")
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
        """正常状态：调整 tint 为默认值，触发重绘。"""
        if _current_theme_name == 'light':
            self._tint = QColor(255, 255, 255, 38)
            self._luminosity = QColor(255, 255, 255, 26)
        else:
            self._tint = QColor(40, 40, 45, 60)
            self._luminosity = QColor(255, 255, 255, 15)
        self.invalidate_cache()
        self.update()

    def _apply_hover_style(self):
        """hover 状态：增亮 tint + 强调色边缘，触发重绘。"""
        t = get_theme()
        accent = QColor(t['accent'])
        if _current_theme_name == 'light':
            # hover 时 tint 带轻微 accent 色调
            self._tint = QColor(
                min(255, 255 - 20 + accent.red() // 6),
                min(255, 255 - 10 + accent.green() // 6),
                min(255, 255 + accent.blue() // 12),
                60,
            )
            self._luminosity = QColor(255, 255, 255, 50)
        else:
            self._tint = QColor(
                accent.red() // 4 + 30,
                accent.green() // 4 + 35,
                accent.blue() // 4 + 45,
                90,
            )
            self._luminosity = QColor(255, 255, 255, 30)
        self.invalidate_cache()
        self.update()

    def update_theme(self, theme_name):
        t = THEMES[theme_name]
        self._title_label.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {t['card_title_text']}; border: none; background: transparent;")
        self._desc_label.setStyleSheet(
            f"font-size: 12px; color: {t['card_desc_text']}; border: none; background: transparent;")
        # Refresh SVG icon (if any) with the new theme's accent color.
        if getattr(self, '_icon_name', None):
            try:
                from app_icons import icon_pixmap
                from design_tokens import qcolor as _qcolor, tokens as _tokens
                _accent = _qcolor(getattr(_tokens(theme_name).color, 'accent', t['accent']))
                pm = icon_pixmap(self._icon_name, size=48, color=_accent, theme_name=theme_name)
                self._icon_label.setPixmap(pm)
            except Exception:
                pass
        # 委托给 AcrylicContainer.update_theme（兼容 API）
        if theme_name == 'light':
            self._tint = QColor(255, 255, 255, 38)
            self._luminosity = QColor(255, 255, 255, 26)
        else:
            self._tint = QColor(40, 40, 45, 60)
            self._luminosity = QColor(255, 255, 255, 15)
        self.invalidate_cache()
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self._apply_hover_style()
        # If a leave animation is in-flight, stop it and keep the prior
        # _resting_geo (don't recapture — the mid-leave position isn't resting).
        leave_anim = getattr(self, '_leave_anim', None)
        leave_was_running = (leave_anim is not None
                             and leave_anim.state() == QPropertyAnimation.Running)
        if leave_was_running:
            leave_anim.stop()
        # Capture pre-hover "resting" geometry for exact restoration on leave.
        # Only recapture when no leave was in-flight (prevents drift on rapid
        # hover/unhover cycles and on interrupted hover animations).
        geo = self.geometry()
        if not leave_was_running:
            self._resting_geo = geo
        # Lift + scale animation on hover (8px lift + 1.02 scale).
        self._hover_anim = QPropertyAnimation(self, b"geometry")
        self._hover_anim.setDuration(180)
        self._hover_anim.setStartValue(geo)
        # Scale up ~2% (4px wider/taller) and lift 8px for the microinteraction.
        scaled = QRectF(geo.x() - 2, geo.y() - 8, geo.width() + 4, geo.height() + 4).toRect()
        self._hover_anim.setEndValue(scaled)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.start()
        # Brand-color edge glow via drop shadow
        try:
            from design_tokens import brand_gradient_qcolor_tuple
            brand_colors = brand_gradient_qcolor_tuple()
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(24)
            shadow.setColor(brand_colors[1])
            shadow.setOffset(0, 8)
            self.setGraphicsEffect(shadow)
        except Exception:
            pass
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_normal_style()
        # Restore to the exact pre-hover geometry (prevents drift when the hover
        # animation was interrupted before completing).
        geo = self.geometry()
        resting = getattr(self, '_resting_geo', None)
        if resting is None:
            resting = geo
        self._leave_anim = QPropertyAnimation(self, b"geometry")
        self._leave_anim.setDuration(180)
        self._leave_anim.setStartValue(geo)
        self._leave_anim.setEndValue(resting)
        self._leave_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._leave_anim.start()
        # Remove the hover drop shadow.
        self.setGraphicsEffect(None)
        super().leaveEvent(event)

    def _glow_tick(self):
        # 页面过渡时跳过（避免与 QGraphicsEffect 冲突）
        if _widget_has_graphics_effect(self):
            return
        self._t += 1
        # 平滑跟踪 hover 状态（用于呼吸光效到 hover 高光的过渡）
        target = 1.0 if self._hovered else 0.0
        self._hover_progress = getattr(self, '_hover_progress', 0.0)
        self._hover_progress += (target - self._hover_progress) * 0.12
        _safe_update(self)

    def paintEvent(self, event):
        # 先调用 AcrylicContainer.paintEvent 绘制真玻璃背景
        super().paintEvent(event)

        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.Antialiasing)
        t = get_theme()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._radius
        hp = getattr(self, '_hover_progress', 0.0)

        accent = QColor(t['accent'])
        accent2 = QColor(t.get('accent2', '#00C9A7'))

        # 顶部强调条
        top_alpha = int(40 + 180 * hp)
        if top_alpha > 0:
            grad = QLinearGradient(0, 0, self.width(), 0)
            ac = QColor(accent); ac.setAlpha(top_alpha)
            ac2 = QColor(accent2); ac2.setAlpha(top_alpha)
            grad.setColorAt(0, ac)
            grad.setColorAt(1, ac2)
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(16, 10, self.width() - 32, 3), 2, 2)

        # 边缘脉冲光感
        glow_pulse = 0.5 + 0.5 * math.sin(self._t * 0.08)
        idle_alpha = int(15 + 20 * glow_pulse)
        hover_alpha = int(60 + 50 * glow_pulse)
        edge_alpha = int(idle_alpha + (hover_alpha - idle_alpha) * hp)
        if edge_alpha > 0:
            edge_glow = QColor(accent)
            edge_glow.setAlpha(min(255, edge_alpha))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(edge_glow, 2.0))
            p.drawRoundedRect(r, radius, radius)

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.mode_name)
        super().mousePressEvent(event)


# ============================================================
#  RIPPLE OVERLAY (button click microinteraction)
# ============================================================
class RippleOverlay(QWidget):
    """Lightweight radial ripple overlay for button clicks.

    A child of the parent ``QPushButton``, sized to the button's rect. Paints
    a radial gradient circle expanding from the click point while fading out.
    Transparent for mouse events so clicks pass through to the button.
    Self-deletes on animation finish.
    """

    def __init__(self, parent_button, click_pos, color):
        super().__init__(parent_button)
        self._button = parent_button
        self._click_pos = QPointF(click_pos)
        self._color = QColor(color)
        self._radius = 0.0
        self._opacity = 1.0
        # Cover the button's full rect; let mouse events pass through.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        btn_rect = parent_button.rect()
        self.setGeometry(btn_rect)
        self.show()
        # The ripple expands to cover the larger button dimension (with margin).
        self._max_radius = float(max(btn_rect.width(), btn_rect.height()) * 1.2)
        # Drive radius (OutCubic) + opacity (InQuad) in parallel.
        self._anim_group = QParallelAnimationGroup(self)
        radius_anim = QPropertyAnimation(self, b"radius")
        radius_anim.setDuration(300)
        radius_anim.setStartValue(0.0)
        radius_anim.setEndValue(self._max_radius)
        radius_anim.setEasingCurve(QEasingCurve.OutCubic)
        opacity_anim = QPropertyAnimation(self, b"opacity")
        opacity_anim.setDuration(300)
        opacity_anim.setStartValue(1.0)
        opacity_anim.setEndValue(0.0)
        opacity_anim.setEasingCurve(QEasingCurve.InQuad)
        self._anim_group.addAnimation(radius_anim)
        self._anim_group.addAnimation(opacity_anim)
        self._anim_group.finished.connect(self.deleteLater)
        self._anim_group.start()

    @Property(float)
    def radius(self):
        return self._radius

    @radius.setter
    def radius(self, value):
        self._radius = float(value)
        self.update()

    @Property(float)
    def opacity(self):
        return self._opacity

    @opacity.setter
    def opacity(self, value):
        self._opacity = float(value)
        self.update()

    def paintEvent(self, event):
        if self._radius <= 0.0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Clip to a rounded rect (best-effort: 8px radius, button-like).
        try:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(self.rect()), 8.0, 8.0)
            p.setClipPath(clip)
        except Exception:
            pass
        # Radial gradient centered at the click point.
        center_color = QColor(self._color)
        center_color.setAlpha(int(80 * self._opacity))
        edge_color = QColor(self._color)
        edge_color.setAlpha(0)
        radius = max(self._radius, 0.001)
        gradient = QRadialGradient(self._click_pos, radius)
        gradient.setColorAt(0.0, center_color)
        gradient.setColorAt(1.0, edge_color)
        p.setBrush(QBrush(gradient))
        p.setPen(Qt.NoPen)
        p.drawRect(self.rect())


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
    if len(all_notes) == 0:
        return 0
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
    rendering_progress = Signal(str, int)  # (message, percentage 0-100)
    page_changed = Signal(int, int)
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
        self.speed_factor = 1.0  # Playback speed multiplier

        self.play_timer = QTimer(self)
        self.play_timer.setInterval(16)
        self.play_timer.timeout.connect(self._tick_cursor)

        # Cursor line overlay
        self._cursor_line = None
        self._cursor_glow = None
        self._note_highlights_prebuilt = []  # Pre-built note highlight rects: (item, start, end)

        # Page navigation
        self._page_count = 0
        self._current_page = 0  # 0-indexed
        self._page_height = 0

        # SVG pages
        self._svg_items = []
        self._svg_dir = None  # directory containing SVG pages

        # LilyPond paths
        # PyInstaller-aware: check sys._MEIPASS first, then system PATH, then APP_DIR
        _lilypond_base = getattr(sys, '_MEIPASS', '')
        if _lilypond_base:
            self._lilypond_exe = os.path.join(_lilypond_base, 'lilypond-2.24.4', 'bin', 'lilypond.exe')
        else:
            _which_lp = shutil.which('lilypond')
            if _which_lp:
                self._lilypond_exe = _which_lp
            else:
                self._lilypond_exe = os.path.join(
                    APP_DIR,
                    'lilypond-2.24.4', 'bin', 'lilypond.exe')

        self.setMinimumSize(400, 250)
        self._update_bg_style()

        # A4 auto-fit: True until first manual zoom/scroll after load
        self._auto_fit = False

        # Connect signal for thread-safe SVG loading
        self._svg_ready.connect(self._load_svg_pages)

        # Track render thread for concurrency control
        self._render_thread = None

    def resizeEvent(self, event):
        """Maintain A4 page proportions on initial resize after load."""
        super().resizeEvent(event)
        if self._auto_fit and self._svg_items:
            first_rect = self._svg_items[0].sceneBoundingRect()
            self.fitInView(first_rect, Qt.KeepAspectRatio)
            self._zoom = self.transform().m11()

    def _update_bg_style(self):
        t = get_theme()
        # Always white background for sheet music readability (LilyPond renders black-on-white)
        self.setStyleSheet(f"background: #FFFFFF; border-radius: 10px; border: 1px solid {t['card_border']};")

    def update_theme(self, theme_name):
        self._update_bg_style()

    @property
    def page_count(self):
        """Total number of pages in the sheet music."""
        return self._page_count

    @property
    def current_page(self):
        """Current displayed page (0-indexed)."""
        return self._current_page

    def go_to_page(self, page_num):
        """Scroll the view to a specific page."""
        if not self._svg_items or page_num < 0 or page_num >= self._page_count:
            return
        self._current_page = page_num
        y = page_num * self._page_height
        self.verticalScrollBar().setValue(int(y))
        # Notify parent about page change
        if hasattr(self, 'page_changed'):
            self.page_changed.emit(page_num, self._page_count)

    def next_page(self):
        """Go to next page."""
        if self._current_page < self._page_count - 1:
            self.go_to_page(self._current_page + 1)

    def prev_page(self):
        """Go to previous page."""
        if self._current_page > 0:
            self.go_to_page(self._current_page - 1)

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

        # Set LilyPond path before starting worker thread (music21.environment.set is not thread-safe)
        try:
            import music21
            music21.environment.set('lilypondPath', self._lilypond_exe)
        except Exception:
            pass

        # Run LilyPond compilation in background thread
        self._render_thread = threading.Thread(
            target=self._lilypond_worker,
            args=(midi_path,),
            daemon=True
        )
        self._render_thread.start()

    def _lilypond_worker(self, midi_path):
        """Background worker: MIDI → music21 → LilyPond → SVG."""
        try:
            import music21
        except ImportError:
            self.logger.error('music21 未安装')
            self.rendering_progress.emit('错误: music21 未安装', 0)
            self.rendering_done.emit()
            return
        import subprocess
        import copy

        self.rendering_progress.emit('正在启动LilyPond...', 1)

        # Parse MIDI with music21
        self.rendering_progress.emit('解析MIDI文件...', 5)
        try:
            score = music21.converter.parse(midi_path)
        except Exception as e:
            self.logger.error(f'music21解析失败: {e}')
            self.rendering_done.emit()
            return

        # Split into treble and bass parts for grand staff
        use_grand_staff = True
        try:
            # Try to split at middle C (MIDI 60)
            treble_part = music21.stream.Part()
            treble_part.id = 'Treble'
            treble_part.insert(0, music21.clef.TrebleClef())

            bass_part = music21.stream.Part()
            bass_part.id = 'Bass'
            bass_part.insert(0, music21.clef.BassClef())

            # Get all notes AND rests from the score, preserving offsets
            # Use .flat.notesAndRests (capital A) to include rests
            for elem in score.flatten().notesAndRests:
                elem_copy = copy.deepcopy(elem)
                original_offset = elem.offset if hasattr(elem, 'offset') else 0
                if hasattr(elem_copy, 'pitch'):
                    if elem_copy.pitch.midi >= 60:
                        treble_part.insert(original_offset, elem_copy)
                    else:
                        bass_part.insert(original_offset, elem_copy)
                elif hasattr(elem_copy, 'pitches'):  # chord
                    if any(p.midi >= 60 for p in elem_copy.pitches):
                        treble_part.insert(original_offset, elem_copy)
                    else:
                        bass_part.insert(original_offset, elem_copy)
                else:
                    # Rest or other — add to both parts at original offset
                    treble_part.insert(original_offset, copy.deepcopy(elem))
                    bass_part.insert(original_offset, copy.deepcopy(elem))

            # Check if bass part has actual notes (not just clef/time sig)
            bass_has_notes = any(
                hasattr(e, 'pitch') or hasattr(e, 'pitches')
                for e in bass_part.flatten().notesAndRests)
            treble_has_notes = any(
                hasattr(e, 'pitch') or hasattr(e, 'pitches')
                for e in treble_part.flatten().notesAndRests)

            if not bass_has_notes or not treble_has_notes:
                # One staff is empty — fall back to original single-staff layout
                self.logger.info('大谱表分割后某声部无音符，使用原始布局')
                score = music21.converter.parse(midi_path)
                use_grand_staff = False
            else:
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
            use_grand_staff = False

        # Write LilyPond file
        self.rendering_progress.emit('生成LilyPond乐谱文件...', 25)
        ly_base = os.path.join(self._svg_dir, 'score')
        ly_path = ly_base + '.ly'
        try:
            result_path = score.write('lilypond', fp=ly_base)
            # music21 may write without .ly extension - rename if needed
            if not os.path.exists(ly_path) and os.path.exists(result_path):
                os.rename(result_path, ly_path)
        except Exception as e:
            self.logger.error(f'LilyPond文件生成失败: {e}')
            # If grand staff split was the culprit, retry with original score
            if use_grand_staff:
                try:
                    original = music21.converter.parse(midi_path)
                    result_path = original.write('lilypond', fp=ly_base)
                    if not os.path.exists(ly_path) and os.path.exists(result_path):
                        os.rename(result_path, ly_path)
                    self.logger.info('回退到原始布局写入成功')
                except Exception as e2:
                    self.logger.error(f'LilyPond回退也失败: {e2}')
                    self.rendering_done.emit()
                    return
            else:
                self.rendering_done.emit()
                return

        if not os.path.exists(ly_path):
            self.logger.error('.ly文件未生成')
            self.rendering_done.emit()
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
                # Use A4 paper with proper layout for full-page rendering
                if '\\paper' not in ly_content:
                    ly_content = ly_content.replace(
                        '\\header',
                        '\\paper {\n'
                        '  #(set-paper-size "a4")\n'
                        '  page-breaking = #ly:optimal-breaking\n'
                        '  ragged-last-bottom = ##f\n'
                        '  ragged-right = ##f\n'
                        '  indent = 0\n'
                        '  short-indent = 0\n'
                        '  line-width = #(- paper-width (* 24 mm))\n'
                        '  system-system-spacing = #((padding . 4) (stretchability . 6))\n'
                        '  top-margin = 15\n'
                        '  bottom-margin = 15\n'
                        '  left-margin = 12\n'
                        '  right-margin = 12\n'
                        '  print-page-number = ##f\n'
                        '}\n\\header'
                    )
                with open(ly_path, 'w', encoding='utf-8') as f:
                    f.write(ly_content)
            except Exception as e:
                self.logger.warning(f'.ly文件后处理失败: {e}')

        # Compile with LilyPond
        self.rendering_progress.emit('LilyPond编译SVG...', 50)
        try:
            result = subprocess.run(
                [self._lilypond_exe, '-dbackend=svg', '-dno-point-and-click',
                 '--output', ly_base, ly_path],
                capture_output=True, text=True, timeout=120,
                cwd=self._svg_dir
            )
            self.logger.info(f'LilyPond编译完成, exit={result.returncode}')
            if result.returncode != 0 and result.stderr:
                self.logger.warning(f'LilyPond错误: {result.stderr[:500]}')
        except Exception as e:
            self.logger.error(f'LilyPond编译失败: {e}')
            self.rendering_done.emit()
            return

        # Load SVG pages on the main thread via signal
        self.rendering_progress.emit('加载渲染结果...', 90)
        self._svg_ready.emit()

    def _find_staff_lines_svg(self, svg_path):
        """Parse SVG to find staff line Y positions for precise note highlighting.

        Returns dict: {
            'treble': {'lines': [y1..y5], 'space': float, 'middle_y': float,
                        'midi_middle': int},
            'bass':   {'lines': [y1..y5], 'space': float, 'middle_y': float,
                        'midi_middle': int},
        } or None if parsing fails.
        """
        import xml.etree.ElementTree as ET
        import re

        try:
            tree = ET.parse(svg_path)
            root = tree.getroot()
            ns = 'http://www.w3.org/2000/svg'

            # Collect all Y positions of horizontal line elements
            y_values = []
            # Look for <line> elements with y1==y2 (horizontal)
            for line_el in root.iter(f'{{{ns}}}line'):
                y1 = line_el.get('y1')
                y2 = line_el.get('y2')
                x1 = line_el.get('x1')
                x2 = line_el.get('x2')
                if y1 and y2:
                    y1, y2 = float(y1), float(y2)
                    if abs(y1 - y2) < 0.5:  # horizontal
                        length = abs(float(x2 or 0) - float(x1 or 0))
                        y_values.append((y1, length))

            # Also look for <path> elements with horizontal segments
            for path_el in root.iter(f'{{{ns}}}path'):
                d = path_el.get('d', '')
                # Find M x y H x2 patterns (horizontal line)
                for match in re.finditer(r'[Mm]\s*[\d.-]+\s+([\d.-]+)\s+[Hh]\s+[\d.-]+', d):
                    y = float(match.group(1))
                    y_values.append((y, 100))  # approximate length

            if not y_values:
                return None

            # Group Y values into clusters (staff lines are ~5 closely spaced)
            y_values.sort()
            # Cluster: lines within 10 units are same staff
            current_group = []
            groups = []
            prev_y = None
            for y, length in y_values:
                if length < 20:  # skip very short lines (bar lines, stems)
                    continue
                if prev_y is not None and (y - prev_y) > 10:
                    if len(current_group) >= 4:  # at least 4 lines to be a staff
                        groups.append(current_group)
                    current_group = []
                # Round to avoid duplicate near-identical Ys
                rounded = round(y, 1)
                if not current_group or abs(rounded - current_group[-1]) > 0.3:
                    current_group.append(rounded)
                prev_y = y
            if len(current_group) >= 4:
                groups.append(current_group)

            # We need at least 2 staves (grand staff)
            if len(groups) < 1:
                return None

            # Sort groups by Y (top to bottom)
            groups.sort(key=lambda g: g[0])

            def _staff_info(lines):
                """Given 5 line Y positions, return staff info."""
                if len(lines) < 5:
                    # Pad to 5 if needed (uniform spacing)
                    space = lines[1] - lines[0] if len(lines) > 1 else 6
                    while len(lines) < 5:
                        lines.append(lines[-1] + space)
                # Take 5 lines centered in the detected group
                if len(lines) > 5:
                    mid = len(lines) // 2
                    lines = lines[mid - 2:mid + 3]
                lines = sorted(lines[:5])
                space = (lines[-1] - lines[0]) / 4
                middle_y = lines[2]  # middle line
                return {'lines': lines, 'space': space, 'middle_y': middle_y}

            if len(groups) >= 2:
                treble = _staff_info(groups[0])
                bass = _staff_info(groups[1])
                # Treble middle line = B4 = MIDI 71
                # Bass middle line = D3 = MIDI 50
                treble['midi_middle'] = 71
                bass['midi_middle'] = 50
                return {'treble': treble, 'bass': bass}
            elif len(groups) == 1:
                # Single staff - use it for all notes
                single = _staff_info(groups[0])
                single['midi_middle'] = 60  # middle C as default
                return {'treble': single, 'bass': single}

            return None

        except Exception as e:
            self.logger.debug(f'SVG staff line parsing failed: {e}')
            return None

    def _load_svg_pages(self):
        """Load all SVG pages into the scene."""
        self._scene.clear()
        self._svg_items.clear()
        self._note_highlights_prebuilt.clear()
        self._page_count = 0
        self._current_page = 0
        self._page_height = 0

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

        self._page_count = len(self._svg_items)
        if self._page_count > 0:
            self._page_height = (
                self._svg_items[0].boundingRect().height() + 20)

        if len(svg_files) > max_pages:
            from PySide6.QtWidgets import QGraphicsTextItem
            more_text = QGraphicsTextItem(f"... 共 {len(svg_files)} 页，显示前 {max_pages} 页 ...")
            more_text.setPos(0, y_offset)
            self._scene.addItem(more_text)

        if self._svg_items:
            # Set explicit scene rect to avoid any clipping
            self.setSceneRect(self._scene.itemsBoundingRect())
            self._auto_fit = True
            # Fit the first page for readability; user can zoom out to see all
            first_rect = self._svg_items[0].sceneBoundingRect()
            self.fitInView(first_rect, Qt.KeepAspectRatio)
            self._zoom = self.transform().m11()

            # Parse first SVG page to find exact staff positions
            first_svg_path = os.path.join(self._svg_dir, svg_files[0])
            staff_info = self._find_staff_lines_svg(first_svg_path)

            # Pre-build note highlight rects using actual staff positions
            if self.display_notes and self._svg_items and self._page_count > 0:
                page_w = self._svg_items[0].boundingRect().width()
                page_h = self._svg_items[0].boundingRect().height()
                dur = max(self.duration, 0.001)
                time_per_page = dur / self._page_count

                if staff_info:
                    # Use actual staff positions from SVG parsing
                    treble = staff_info['treble']
                    bass = staff_info['bass']
                    ts = treble['space']  # staff space in SVG units
                    bs = bass['space']

                    # Note head size proportional to staff space
                    note_h = max(4, ts * 1.6)
                    note_h_bass = max(4, bs * 1.6)
                else:
                    # Fallback: estimated staff regions
                    treble_top = page_h * 0.18
                    treble_bot = page_h * 0.50
                    bass_top = page_h * 0.52
                    bass_bot = page_h * 0.84
                    note_h = max(4, page_h * 0.009)
                    note_h_bass = note_h

                note_min_width = max(4, page_w * 0.003)

                for n in self.display_notes:
                    ns, ne = float(n['start']), float(n['end'])
                    pitch = float(n['pitch'])
                    page_idx = min(int(ns / time_per_page), self._page_count - 1)
                    page_start_time = page_idx * time_per_page
                    nx = ((ns - page_start_time) / time_per_page) * page_w
                    dur_w = max(note_min_width,
                                ((ne - ns) / time_per_page) * page_w)

                    if pitch >= 60:
                        # Treble staff: green highlight
                        if staff_info and treble is not bass:
                            # Map pitch to staff-space offset from middle line
                            offset = (pitch - treble['midi_middle']) / 2.0
                            ny = treble['middle_y'] - offset * ts
                            nh = note_h
                        else:
                            ny = treble_top + (1 - (pitch - 60) / 48) * (
                                        treble_bot - treble_top)
                            nh = note_h_bass
                        color = QColor(80, 200, 80, 150)
                        border = QColor(60, 180, 60, 220)
                    else:
                        # Bass staff: orange highlight
                        if staff_info and treble is not bass:
                            offset = (pitch - bass['midi_middle']) / 2.0
                            ny = bass['middle_y'] - offset * bs
                            nh = note_h_bass
                        else:
                            ny = bass_top + (1 - (pitch - 21) / 39) * (
                                        bass_bot - bass_top)
                            nh = note_h_bass
                        color = QColor(255, 160, 40, 150)
                        border = QColor(255, 140, 20, 220)

                    # Center the highlight on the note head
                    ny = ny - nh / 2

                    rect = self._scene.addRect(
                        nx, page_idx * self._page_height + ny,
                        dur_w, nh,
                        QPen(border, 1),
                        color)
                    rect.setVisible(False)
                    self._note_highlights_prebuilt.append((rect, ns, ne))

            self.rendering_done.emit()

    def apply_difficulty(self, difficulty):
        """Filter notes based on difficulty level."""
        self.display_notes = simplify_notes(self.all_notes, difficulty)

    def zoom_in(self):
        self._auto_fit = False
        self.zoom = min(5.0, self._zoom * 1.2)

    def zoom_out(self):
        self._auto_fit = False
        self.zoom = max(0.2, self._zoom / 1.2)

    def zoom_fit(self):
        self._auto_fit = True
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
        # Hide all note highlights on stop
        for item_tuple in self._note_highlights_prebuilt:
            item_tuple[0].setVisible(False)

    def reset_cursor(self):
        """Reset cursor time to 0."""
        self.cursor_time = 0.0
        # Hide all note highlights on reset
        for item_tuple in self._note_highlights_prebuilt:
            item_tuple[0].setVisible(False)

    def _tick_cursor(self):
        if not self.is_playing:
            return
        elapsed = (time.time() - self.play_start_real) * self.speed_factor
        self.cursor_time = self.play_start_time + elapsed
        if self.cursor_time >= self.duration:
            self.cursor_time = self.duration
            self.stop_playback()

        if self._svg_items:
            # Auto-flip to the correct page based on time
            if self._page_count > 0:
                time_per_page = max(self.duration, 0.001) / self._page_count
                target_page = min(int(self.cursor_time / time_per_page),
                                  self._page_count - 1)
                if target_page != self._current_page:
                    self.go_to_page(target_page)

            # Per-note highlighting: spotlight currently-playing notes
            for item_tuple in self._note_highlights_prebuilt:
                rect, ns, ne = item_tuple
                visible = (ns <= self.cursor_time < ne)
                rect.setVisible(visible)

            # Auto-scroll to cursor position within the current page
            if self._page_count > 0 and self._svg_items:
                time_per_page = max(self.duration, 0.001) / self._page_count
                t = max(self._page_count - 1, 0)
                cp = min(int(self.cursor_time / time_per_page), t)
                page_start = cp * time_per_page
                within_page = (self.cursor_time - page_start) / time_per_page
                within_page = max(0, min(within_page, 1))
                page_width = self._svg_items[cp].boundingRect().width()
                cursor_x = within_page * page_width
                cursor_y = cp * self._page_height
                self.ensureVisible(cursor_x, cursor_y, page_width * 0.3, 60)

    def wheelEvent(self, event):
        """Zoom with Ctrl+wheel, scroll otherwise."""
        if event.modifiers() & Qt.ControlModifier:
            self._auto_fit = False
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
        self.speed_factor = 1.0  # Playback speed multiplier
        self.zoom = 1.0
        self.zoom_x = 1.0  # 水平（音高轴）缩放因子
        self.scroll_y = 0.0  # vertical scroll in seconds
        self.scroll_x = 0.0  # 水平滚动（像素）
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
        self._drag_start_x = None
        self._drag_scroll_y = 0
        self._drag_scroll_x = 0
        # 中键平移状态
        self._pan_start = None
        self._pan_start_scroll = (0.0, 0.0)

    # ── 视图变换辅助方法（支持水平缩放/平移） ──
    def _view_scale_x(self):
        """当前水平方向 key-space -> pixel 的缩放系数（含 zoom_x）。"""
        w = self.width()
        return (w / max(self._total_width, 1)) * self.zoom_x

    def _view_offset_x(self):
        """当前水平平移偏移（像素）。"""
        return -self.scroll_x

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
        elapsed = (time.time() - self.play_start_real) * self.speed_factor
        self.cursor_time = self.play_start_time + elapsed
        if self.cursor_time >= self.duration:
            self.cursor_time = self.duration
            self.stop_playback()
        # Auto-scroll: cursor line is at the keyboard top
        # scroll_y = cursor_time so notes at current time are at the keyboard
        self.scroll_y = self.cursor_time
        _safe_update(self)

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
        if event.button() in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
            self._drag_start = event.position().y()
            self._drag_start_x = event.position().x()
            self._drag_scroll_y = self.scroll_y
            self._drag_scroll_x = self.scroll_x
            self.setCursor(QCursor(Qt.ClosedHandCursor))

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_start is not None:
            dy = self._drag_start - event.position().y()
            dx = event.position().x() - self._drag_start_x
            self.scroll_y = max(0, self._drag_scroll_y + dy / self.pixels_per_second)
            self.scroll_x = max(0, self._drag_scroll_x - dx)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_start = None
        self.setCursor(QCursor(Qt.ArrowCursor))

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
        scale_x = self._view_scale_x()
        offset_x = self._view_offset_x()

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
            x = int(x * scale_x) + offset_x
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
            x = int(x * scale_x) + offset_x

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
        self._draw_keyboard(painter, 0, roll_h, w, kb_h, active_pitches, scale_x, offset_x)

    def _draw_keyboard(self, painter, x_offset, y_offset, width, height, active_pitches, scale_x=1.0, h_offset=0):
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

            x = int(x * scale_x) + h_offset + x_offset
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

            x = int(x * scale_x) + h_offset + x_offset
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
    play_pause_requested = Signal()   # 请求播放/暂停
    undo_redo_changed = Signal()      # 撤销/重做栈变化时发射

    # ── 撤销/重做栈最大深度 ──
    UNDO_MAX_DEPTH = 50

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
        self._drag_mode = None  # None / 'move' / 'resize_top' / 'resize_bottom' / 'box_select' / 'pan'
        self._drag_start_pos = None
        self._drag_origins = {}  # idx -> original note dict（移动/缩放前快照）
        self._drag_resize_idx = None  # 正在缩放的音符索引
        self._drag_resize_orig = None  # 缩放前的原始音符
        self._box_select_start = None  # 框选起点
        self._box_select_rect = None  # 框选矩形 (QRectF)
        self._right_drag_start = None  # 右键拖拽起点（用于区分点击/框选）
        self._context_menu_pending = False  # 右键释放时是否应弹出菜单

        # ── 父类右键拖拽（非编辑模式下保留） ──
        self._right_drag_note_idx = None
        self._right_drag_start = None
        self._right_drag_orig_note = None

        # ── 撤销/重做栈 ──
        # 每项为 (notes_deepcopy, track_info_copy, selection_copy)
        self._undo_stack = []
        self._redo_stack = []
        # 批量操作标记：为 True 时跳过自动保存（由调用方手动控制）
        self._undo_suspend = False

        # ── 属性面板控件引用（由 create_property_panel 创建） ──
        self._prop_panel = None
        self._prop_pitch_spin = None
        self._prop_pitch_label = None
        self._prop_start_spin = None
        self._prop_dur_spin = None
        self._prop_vel_slider = None
        self._prop_vel_label = None
        self._prop_track_combo = None
        self._prop_updating = False  # 正在用程序填充面板时为 True，避免信号回环
        self._prop_undo_saved = False  # 当前属性编辑会话是否已保存撤销状态

        self.setFocusPolicy(Qt.StrongFocus)
        self.setContextMenuPolicy(Qt.PreventContextMenu)

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
        scale_x = self._view_scale_x()
        offset_x = self._view_offset_x()
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
            px = int(px * scale_x) + offset_x
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
        scale_x = self._view_scale_x()
        offset_x = self._view_offset_x()
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
            px = int(px * scale_x) + offset_x
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
        scale_x = self._view_scale_x()
        offset_x = self._view_offset_x()
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
            px = int(px * scale_x) + offset_x
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
        scale_x = self._view_scale_x()
        offset_x = self._view_offset_x()
        pps = self.pixels_per_second

        pitch = note['pitch']
        start = note['start']
        end = note['end']

        px, is_white = self._pitch_to_x(pitch)
        px = int(px * scale_x) + offset_x
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
    #  撤销 / 重做
    # ================================================================
    def _snapshot_state(self):
        """深拷贝当前状态用于撤销/重做栈。"""
        import copy
        return (
            copy.deepcopy(self.display_notes),
            dict(self.track_info),
            set(self.selected_indices),
        )

    def _restore_state(self, state):
        """从快照恢复状态。"""
        notes, track_info, selection = state
        import copy
        self.display_notes = copy.deepcopy(notes)
        self.track_info = dict(track_info)
        self.selected_indices = set(selection)

    def _save_undo_state(self):
        """编辑操作前调用：将当前状态压入撤销栈并清空重做栈。
        若 _undo_suspend 为 True 则跳过（用于批量操作由调用方手动保存）。"""
        if self._undo_suspend:
            return
        self._undo_stack.append(self._snapshot_state())
        if len(self._undo_stack) > self.UNDO_MAX_DEPTH:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self.undo_redo_changed.emit()

    @property
    def can_undo(self):
        return len(self._undo_stack) > 0

    @property
    def can_redo(self):
        return len(self._redo_stack) > 0

    def undo(self):
        """撤销上一次编辑操作。"""
        if not self._undo_stack:
            return
        # 当前状态压入重做栈
        self._redo_stack.append(self._snapshot_state())
        state = self._undo_stack.pop()
        self._restore_state(state)
        self.update()
        self.undo_redo_changed.emit()
        self.selection_changed.emit()
        self.notes_changed.emit()
        self.logger.info('编辑-撤销')

    def redo(self):
        """重做上一次撤销的操作。"""
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot_state())
        if len(self._undo_stack) > self.UNDO_MAX_DEPTH:
            self._undo_stack.pop(0)
        state = self._redo_stack.pop()
        self._restore_state(state)
        self.update()
        self.undo_redo_changed.emit()
        self.selection_changed.emit()
        self.notes_changed.emit()
        self.logger.info('编辑-重做')

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
        self._save_undo_state()
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
        self._save_undo_state()
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
        self._save_undo_state()
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

    def transpose_selected(self, semitones):
        """将选中音符移调指定半音数。"""
        if not self.selected_indices or semitones == 0:
            return
        self._save_undo_state()
        for idx in list(self.selected_indices):
            if 0 <= idx < len(self.display_notes):
                note = self.display_notes[idx]
                new_pitch = max(self.MIDI_LOW, min(self.MIDI_HIGH, note['pitch'] + semitones))
                self.display_notes[idx] = {
                    'pitch': new_pitch,
                    'start': note['start'],
                    'end': note['end'],
                    'velocity': note['velocity']
                }
        self.logger.info(f'编辑-移调 {semitones} 半音, {len(self.selected_indices)} 个音符')
        self.update()
        self.notes_changed.emit()

    def split_selected_notes(self):
        """将选中的每个音符在正中间分割为两个音符。"""
        if not self.selected_indices:
            return
        self._save_undo_state()
        old_notes = list(self.display_notes)
        old_track_info = dict(self.track_info)
        # 记录被分割音符的原始 (pitch, start, end) 用于事后重选
        split_ranges = []
        for idx in sorted(self.selected_indices):
            if 0 <= idx < len(self.display_notes):
                note = self.display_notes[idx]
                mid = (note['start'] + note['end']) / 2.0
                if mid - note['start'] < 0.02:
                    continue  # 太短不分割
                split_ranges.append((note['pitch'], note['start'], note['end']))
                first = {'pitch': note['pitch'], 'start': note['start'], 'end': mid,
                         'velocity': note['velocity']}
                second = {'pitch': note['pitch'], 'start': mid, 'end': note['end'],
                          'velocity': note['velocity']}
                self.display_notes[idx] = first
                self.display_notes.append(second)
        self.display_notes.sort(key=lambda n: (n['start'], n['pitch']))
        self._rebuild_track_info_after_sort(old_notes, old_track_info)
        # 重新选中分割产生的两个半音符
        self.selected_indices = set()
        for i, n in enumerate(self.display_notes):
            for (p, s, e) in split_ranges:
                if n['pitch'] == p and s - 0.001 <= n['start'] and n['end'] <= e + 0.001:
                    self.selected_indices.add(i)
                    break
        self.logger.info(f'编辑-分割 {len(split_ranges)} 个音符')
        self.selection_changed.emit()
        self.update()
        self.notes_changed.emit()

    def invert_selection(self):
        """反转选中状态：未选中的变为选中，选中的变为未选中。"""
        all_indices = set(range(len(self.display_notes)))
        self.selected_indices = all_indices - self.selected_indices
        self.selection_changed.emit()
        self.update()

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
        self._save_undo_state()
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

        # ── 中键：开始平移视图 ──
        if event.button() == Qt.MiddleButton:
            self._drag_mode = 'pan'
            self._pan_start = pos
            self._pan_start_scroll = (self.scroll_x, self.scroll_y)
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            event.accept()
            return

        # ── 右键：开始框选（释放时若未拖拽则弹出上下文菜单） ──
        if event.button() == Qt.RightButton:
            self._drag_mode = 'box_select'
            self._box_select_start = pos
            self._box_select_rect = None
            self._right_drag_start = pos
            self._context_menu_pending = True
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
                    self._save_undo_state()
            else:
                # 左键点击空白：仅取消选中（左键专用于移动，框选改由右键完成）
                if not (event.modifiers() & Qt.ControlModifier):
                    self._deselect_all()
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
                self._save_undo_state()
            elif edge_idx is not None:
                # 在音符中间：开始移动
                self._drag_mode = 'move'
                self._drag_start_pos = pos
                self.selected_indices = {edge_idx}
                self._drag_origins = {edge_idx: dict(self.display_notes[edge_idx])}
                self.selection_changed.emit()
                self._save_undo_state()
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

        # ── 中键拖拽：平移视图 ──
        if self._drag_mode == 'pan' and self._pan_start is not None:
            dx = pos.x() - self._pan_start.x()
            dy = pos.y() - self._pan_start.y()
            sx, sy = self._pan_start_scroll
            self.scroll_x = max(0.0, sx - dx)
            self.scroll_y = max(0.0, sy + dy / max(self.pixels_per_second, 1))
            self.update()
            event.accept()
            return

        # ── 框选（右键拖拽） ──
        if self._drag_mode == 'box_select' and self._box_select_start is not None:
            x1 = min(self._box_select_start.x(), pos.x())
            y1 = min(self._box_select_start.y(), pos.y())
            x2 = max(self._box_select_start.x(), pos.x())
            y2 = max(self._box_select_start.y(), pos.y())
            self._box_select_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            # 拖拽超过阈值则视为框选，不再弹出菜单
            if self._right_drag_start is not None:
                ddx = pos.x() - self._right_drag_start.x()
                ddy = pos.y() - self._right_drag_start.y()
                if (ddx * ddx + ddy * ddy) > 25:  # 5px 阈值
                    self._context_menu_pending = False
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

            scale_x = self._view_scale_x()
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

        # ── 中键释放：结束平移 ──
        if event.button() == Qt.MiddleButton:
            self._drag_mode = None
            self._pan_start = None
            self._update_cursor()
            event.accept()
            return

        # ── 右键释放：结束框选，或弹出上下文菜单 ──
        if event.button() == Qt.RightButton:
            show_menu = self._context_menu_pending
            # 结束框选
            self._box_select_start = None
            self._box_select_rect = None
            self._right_drag_start = None
            self._context_menu_pending = False
            if self._drag_mode == 'box_select':
                self._drag_mode = None
            self.update()
            if show_menu:
                self._show_context_menu(event.globalPosition().toPoint())
            event.accept()
            return

        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return

        # ── 框选结束（左键兜底） ──
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

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """双击音符：将其分割为两半。"""
        if event.button() != Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        pos = event.position()
        idx = self._find_note_at(pos)
        if idx is not None:
            # 仅选中该音符并分割
            self.selected_indices = {idx}
            self.selection_changed.emit()
            self.split_selected_notes()
        event.accept()

    def wheelEvent(self, event: QWheelEvent):
        """滚轮：Ctrl=水平缩放，Shift=垂直缩放，无修饰=垂直滚动。"""
        delta = event.angleDelta().y()
        mods = event.modifiers()
        if mods & Qt.ControlModifier:
            # 水平缩放（音高轴）
            if delta > 0:
                self.zoom_x = min(8.0, self.zoom_x * 1.2)
            else:
                self.zoom_x = max(0.5, self.zoom_x / 1.2)
            self.update()
            event.accept()
            return
        elif mods & Qt.ShiftModifier:
            # 垂直缩放（时间轴）
            if delta > 0:
                self.pixels_per_second = min(400, self.pixels_per_second * 1.2)
            else:
                self.pixels_per_second = max(20, self.pixels_per_second / 1.2)
            self.update()
            event.accept()
            return
        else:
            # 垂直滚动
            scroll_delta = delta / self.pixels_per_second * 0.3
            self.scroll_y = max(0, self.scroll_y - scroll_delta)
            self.update()
            event.accept()
            return

    # ================================================================
    #  右键上下文菜单
    # ================================================================
    def _show_context_menu(self, global_pos):
        """构建并显示右键上下文菜单。"""
        menu = QMenu(self)
        t = get_theme()
        menu.setStyleSheet(
            f"QMenu {{ background-color: {t.get('card_bg', '#FFFFFF')}; "
            f"color: {t.get('text_primary', '#333333')}; border: 1px solid {t.get('border', '#CCCCCC')}; }}"
            f"QMenu::item:selected {{ background-color: {t.get('accent', '#007AFF')}; color: white; }}"
        )

        act_add = menu.addAction("添加音符")
        menu.addSeparator()
        act_delete = menu.addAction("删除选中")
        act_copy = menu.addAction("复制 (Ctrl+C)")
        act_cut = menu.addAction("剪切 (Ctrl+X)")
        act_paste = menu.addAction("粘贴 (Ctrl+V)")
        menu.addSeparator()
        act_select_all = menu.addAction("全选 (Ctrl+A)")
        act_invert = menu.addAction("反转选中")
        menu.addSeparator()
        act_oct_up = menu.addAction("八度移调 ↑")
        act_oct_down = menu.addAction("八度移调 ↓")
        act_split = menu.addAction("分割音符")

        has_sel = bool(self.selected_indices)
        act_delete.setEnabled(has_sel)
        act_copy.setEnabled(has_sel)
        act_cut.setEnabled(has_sel)
        act_invert.setEnabled(len(self.display_notes) > 0)
        act_oct_up.setEnabled(has_sel)
        act_oct_down.setEnabled(has_sel)
        act_split.setEnabled(has_sel)
        act_paste.setEnabled(bool(self._clipboard))

        action = menu.exec(global_pos)
        if action is None:
            return
        if action == act_add:
            # 在当前光标时间、中央音高添加音符
            pitch, _ = self._pos_to_pitch_time(QPointF(self.width() / 2, self.height() / 2))
            new_idx = self._add_note(pitch, self._snap_time(self.cursor_time),
                                     self._snap_time(self.cursor_time) + 0.25, 80)
            self.selected_indices = {new_idx}
            self.selection_changed.emit()
        elif action == act_delete:
            self._delete_notes(self.selected_indices)
        elif action == act_copy:
            self._copy_selected()
        elif action == act_cut:
            self._cut_selected()
        elif action == act_paste:
            self._paste_clipboard()
        elif action == act_select_all:
            self._select_all()
        elif action == act_invert:
            self.invert_selection()
        elif action == act_oct_up:
            self.transpose_selected(12)
        elif action == act_oct_down:
            self.transpose_selected(-12)
        elif action == act_split:
            self.split_selected_notes()

    # ================================================================
    #  键盘事件
    # ================================================================
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        # Ctrl+Z: 撤销（Ctrl+Shift+Z 视为重做，见下）
        if mods & Qt.ControlModifier and key == Qt.Key_Z and not (mods & Qt.ShiftModifier):
            self.undo()
            event.accept()
            return
        # Ctrl+Y 或 Ctrl+Shift+Z: 重做
        if (mods & Qt.ControlModifier and key == Qt.Key_Y) or \
           (mods & Qt.ControlModifier and mods & Qt.ShiftModifier and key == Qt.Key_Z):
            self.redo()
            event.accept()
            return

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

        # Space: 播放/暂停（发射信号）
        if key == Qt.Key_Space and not mods:
            self.play_pause_requested.emit()
            event.accept()
            return

        # 方向键：微调选中音符
        if self.selected_indices and not (mods & Qt.ControlModifier):
            step = self.snap_grid if self.snap_grid > 0 else 0.1
            if mods & Qt.ShiftModifier:
                # Shift+上下：八度移调
                if key == Qt.Key_Up:
                    self.transpose_selected(12)
                    event.accept()
                    return
                elif key == Qt.Key_Down:
                    self.transpose_selected(-12)
                    event.accept()
                    return
            else:
                if key == Qt.Key_Up:
                    self._move_selected_notes(1, 0)
                    event.accept()
                    return
                elif key == Qt.Key_Down:
                    self._move_selected_notes(-1, 0)
                    event.accept()
                    return
                elif key == Qt.Key_Right:
                    self._move_selected_notes(0, step)
                    event.accept()
                    return
                elif key == Qt.Key_Left:
                    self._move_selected_notes(0, -step)
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
    #  音符属性编辑面板
    # ================================================================
    def create_property_panel(self):
        """创建音符属性编辑面板（QFrame）。选中单个音符时显示。
        返回该 QFrame，由外部布局加入编辑页面。"""
        if self._prop_panel is not None:
            return self._prop_panel

        t = get_theme()
        panel = QFrame()
        panel.setObjectName("editPropPanel")
        # Note: QSpinBox / QDoubleSpinBox / QComboBox / QSlider styling is
        # provided by the global stylesheet (Task 4) — only the panel frame
        # and QLabel text color are overridden here.
        panel.setStyleSheet(
            f"QFrame#editPropPanel {{ background-color: {t.get('surface', 'rgba(255,255,255,0.6)')}; "
            f"border: 1px solid {t.get('border', 'rgba(0,0,0,0.06)')}; border-radius: 8px; }}"
            f"QLabel {{ color: {t.get('text_secondary', '#86868B')}; font-size: 11px; border: none; }}"
        )
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 音高
        layout.addWidget(QLabel("音高:"))
        self._prop_pitch_spin = QSpinBox()
        self._prop_pitch_spin.setRange(self.MIDI_LOW, self.MIDI_HIGH)
        self._prop_pitch_spin.setValue(60)
        self._prop_pitch_spin.setFixedWidth(64)
        self._prop_pitch_spin.valueChanged.connect(self._on_prop_pitch_changed)
        layout.addWidget(self._prop_pitch_spin)
        self._prop_pitch_label = QLabel("C4")
        self._prop_pitch_label.setMinimumWidth(28)
        layout.addWidget(self._prop_pitch_label)

        # 起始时间
        layout.addWidget(QLabel("起始(s):"))
        self._prop_start_spin = QDoubleSpinBox()
        self._prop_start_spin.setRange(0.0, 3600.0)
        self._prop_start_spin.setSingleStep(0.05)
        self._prop_start_spin.setDecimals(3)
        self._prop_start_spin.setValue(0.0)
        self._prop_start_spin.setFixedWidth(86)
        self._prop_start_spin.valueChanged.connect(self._on_prop_start_changed)
        layout.addWidget(self._prop_start_spin)

        # 持续时间
        layout.addWidget(QLabel("时长(s):"))
        self._prop_dur_spin = QDoubleSpinBox()
        self._prop_dur_spin.setRange(0.05, 60.0)
        self._prop_dur_spin.setSingleStep(0.05)
        self._prop_dur_spin.setDecimals(3)
        self._prop_dur_spin.setValue(0.25)
        self._prop_dur_spin.setFixedWidth(86)
        self._prop_dur_spin.valueChanged.connect(self._on_prop_dur_changed)
        layout.addWidget(self._prop_dur_spin)

        # 力度
        layout.addWidget(QLabel("力度:"))
        self._prop_vel_slider = QSlider(Qt.Horizontal)
        self._prop_vel_slider.setRange(1, 127)
        self._prop_vel_slider.setValue(80)
        self._prop_vel_slider.setFixedWidth(110)
        self._prop_vel_slider.sliderPressed.connect(self._save_prop_undo)
        self._prop_vel_slider.valueChanged.connect(self._on_prop_vel_changed)
        layout.addWidget(self._prop_vel_slider)
        self._prop_vel_label = QLabel("80")
        self._prop_vel_label.setFixedWidth(24)
        layout.addWidget(self._prop_vel_label)

        # 轨道
        layout.addWidget(QLabel("轨道:"))
        self._prop_track_combo = QComboBox()
        self._prop_track_combo.addItem("Accompaniment", 0)
        self._prop_track_combo.addItem("Vocals", 1)
        self._prop_track_combo.setFixedWidth(120)
        self._prop_track_combo.currentIndexChanged.connect(self._on_prop_track_changed)
        layout.addWidget(self._prop_track_combo)

        layout.addStretch()

        # 安装事件过滤器：FocusIn 保存撤销状态，FocusOut 重置标记
        for w in (self._prop_pitch_spin, self._prop_start_spin,
                  self._prop_dur_spin, self._prop_vel_slider, self._prop_track_combo):
            w.installEventFilter(self)

        panel.setVisible(False)
        self._prop_panel = panel

        # 选中/音符变化时刷新面板
        self.selection_changed.connect(self._update_property_panel)
        self.notes_changed.connect(self._update_property_panel)

        return panel

    def eventFilter(self, obj, event):
        """属性面板控件焦点事件：进入焦点时保存一次撤销状态。"""
        if event.type() == QEvent.FocusIn:
            self._save_prop_undo()
        elif event.type() == QEvent.FocusOut:
            self._prop_undo_saved = False
        return super().eventFilter(obj, event)

    def _save_prop_undo(self):
        """属性编辑会话开始时保存一次撤销状态。"""
        if not self._prop_undo_saved:
            self._save_undo_state()
            self._prop_undo_saved = True

    def _update_property_panel(self):
        """根据当前选中状态刷新属性面板。"""
        if self._prop_panel is None:
            return
        # 仅当选中单个音符时显示
        if len(self.selected_indices) != 1:
            self._prop_panel.setVisible(False)
            return
        idx = next(iter(self.selected_indices))
        if idx >= len(self.display_notes):
            self._prop_panel.setVisible(False)
            return
        note = self.display_notes[idx]
        self._prop_updating = True
        try:
            self._prop_pitch_spin.setValue(note['pitch'])
            self._prop_pitch_label.setText(self.get_note_name(note['pitch']))
            self._prop_start_spin.setValue(note['start'])
            self._prop_dur_spin.setValue(max(0.05, note['end'] - note['start']))
            self._prop_vel_slider.setValue(note['velocity'])
            self._prop_vel_label.setText(str(note['velocity']))
            track = self.track_info.get(idx, 0)
            self._prop_track_combo.setCurrentIndex(1 if track == 1 else 0)
        finally:
            self._prop_updating = False
        self._prop_panel.setVisible(True)

    def _current_prop_note_idx(self):
        """返回属性面板当前编辑的音符索引（仅单选时有效）。"""
        if len(self.selected_indices) != 1:
            return None
        idx = next(iter(self.selected_indices))
        if idx >= len(self.display_notes):
            return None
        return idx

    def _on_prop_pitch_changed(self, value):
        if self._prop_updating:
            return
        idx = self._current_prop_note_idx()
        if idx is None:
            return
        self._save_prop_undo()
        note = self.display_notes[idx]
        self.display_notes[idx] = {'pitch': value, 'start': note['start'],
                                   'end': note['end'], 'velocity': note['velocity']}
        self._prop_pitch_label.setText(self.get_note_name(value))
        self.update()
        self.notes_changed.emit()

    def _on_prop_start_changed(self, value):
        if self._prop_updating:
            return
        idx = self._current_prop_note_idx()
        if idx is None:
            return
        self._save_prop_undo()
        note = self.display_notes[idx]
        duration = max(0.05, note['end'] - note['start'])
        new_start = max(0.0, value)
        self.display_notes[idx] = {'pitch': note['pitch'], 'start': new_start,
                                   'end': new_start + duration, 'velocity': note['velocity']}
        self.update()
        self.notes_changed.emit()

    def _on_prop_dur_changed(self, value):
        if self._prop_updating:
            return
        idx = self._current_prop_note_idx()
        if idx is None:
            return
        self._save_prop_undo()
        note = self.display_notes[idx]
        new_dur = max(0.05, value)
        self.display_notes[idx] = {'pitch': note['pitch'], 'start': note['start'],
                                   'end': note['start'] + new_dur, 'velocity': note['velocity']}
        self.update()
        self.notes_changed.emit()

    def _on_prop_vel_changed(self, value):
        if self._prop_updating:
            return
        idx = self._current_prop_note_idx()
        if idx is None:
            return
        self._save_prop_undo()
        note = self.display_notes[idx]
        self.display_notes[idx] = {'pitch': note['pitch'], 'start': note['start'],
                                   'end': note['end'], 'velocity': value}
        self._prop_vel_label.setText(str(value))
        self.update()
        self.notes_changed.emit()

    def _on_prop_track_changed(self, combo_idx):
        if self._prop_updating:
            return
        idx = self._current_prop_note_idx()
        if idx is None:
            return
        self._save_prop_undo()
        track = self._prop_track_combo.itemData(combo_idx) or 0
        self.track_info[idx] = track
        self.update()
        self.notes_changed.emit()

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
        # Set window icon — compose onto square canvas to avoid stretching
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pianoscribe_icon.ico')
        if os.path.exists(icon_path):
            _icon_pm = QPixmap(icon_path)
            if not _icon_pm.isNull():
                _sq = 256
                _scaled = _icon_pm.scaled(_sq, _sq, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                _square = QPixmap(_sq, _sq)
                _square.fill(Qt.transparent)
                _pntr = QPainter(_square)
                _pntr.drawPixmap((_sq - _scaled.width()) // 2,
                                 (_sq - _scaled.height()) // 2, _scaled)
                _pntr.end()
                self.setWindowIcon(QIcon(_square))
        self.setMinimumSize(1280, 860)
        self.resize(1440, 920)

        # === 启用无边框窗口（真·Liquid Glass 沉浸式体验）===
        # 必须在 _setup_ui 之前调用 setWindowFlags
        make_frameless(self)
        self._window_icon = QIcon(_square) if os.path.exists(icon_path) and not _icon_pm.isNull() else None

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
        # 分离模式: 'standard' = 人声+伴奏(2-stem), 'stems' = 4音轨细化(vocals/drums/bass/other)
        self.separation_mode = 'standard'
        self.denoise_params = {
            'threshold': 0.25,
            'min_duration_ms': 80,
            'chord_strictness': 0.25,
            'max_jump': 12,
            'max_polyphony': 6,
        }

        # 模型灵敏度设置（用户可手动调节）
        # - vocal_onset_threshold: Basic Pitch onset 阈值（越低越灵敏，0.3-0.8，默认 0.5）
        # - vocal_frame_threshold: Basic Pitch frame 阈值（越低越灵敏，0.1-0.6，默认 0.3）
        # - vocal_min_note_length: 最短音符时长（ms，40-200，默认 80）
        # - accomp_sensitivity: Transkun 灵敏度（0-100，默认 50，越高越灵敏）
        self.model_sensitivity = {
            'vocal_onset_threshold': 0.5,
            'vocal_frame_threshold': 0.3,
            'vocal_min_note_length': 80,
            'accomp_sensitivity': 50,
        }

        # Edit mode debounce timer for sheet music re-rendering
        self._edit_render_timer = QTimer(self)
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

        # Initialize ToastManager singleton bound to this main window.
        # Spec: "_show_status transient messages use toast; status bar keeps
        # persistent state." Lazy import to avoid hard dependency.
        try:
            from toast import get_toast_manager as _get_toast_mgr
            self._toast_manager = _get_toast_mgr(self)
        except Exception:
            self._toast_manager = None

        # === 安装自定义标题栏（无边框窗口配套）===
        # 在 _setup_ui 之后插入，避免破坏现有 layout 结构
        self._title_bar = install_title_bar(
            self,
            title="PianoScribe - 钢琴乐谱生成器",
            icon=self._window_icon,
        )

        # === 启用 Windows 原生 Acrylic 模糊（系统级 GPU 加速，零 CPU 开销）===
        # 必须在窗口显示后调用（需要 winId）
        # 用 QTimer.singleShot 延迟一帧，确保 winId 已就绪
        QTimer.singleShot(0, self._apply_native_acrylic)

        # === 渲染 Pygame 静态光斑壁纸作为窗口背景 ===
        # 仅渲染一次（无实时更新），原生 Acrylic 会模糊这张壁纸
        self._wallpaper = None
        QTimer.singleShot(50, self._setup_wallpaper)

        # === 全局快捷键 ===
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.select_audio)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self.export_midi)
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self._toggle_theme)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Space"), self, activated=self._toggle_playback)

        # === 左下角进度条 ===
        self._render_progress_bar = QProgressBar()
        self._render_progress_bar.setRange(0, 100)
        self._render_progress_bar.setValue(0)
        self._render_progress_bar.setFixedWidth(200)
        self._render_progress_bar.setFixedHeight(14)
        self._render_progress_bar.setTextVisible(False)
        self._render_progress_bar.hide()
        self.statusBar().addWidget(self._render_progress_bar)
        self._render_status_label = QLabel('')
        self._render_status_label.setStyleSheet('font-size:11px; color:#888;')
        self._render_status_label.hide()
        self.statusBar().addWidget(self._render_status_label)

    def closeEvent(self, event):
        """Ensure clean shutdown."""
        self.logger.info('应用关闭中...')
        # Stop timers
        for name in ['_cursor_timer', '_edit_render_timer', '_edit_play_timer']:
            t = getattr(self, name, None)
            if t and t.isActive():
                t.stop()
        # Wait for render thread
        if self._render_thread and self._render_thread.is_alive():
            self._render_thread.join(timeout=3)
        # Kill LilyPond subprocess
        try:
            import subprocess
            subprocess.run(['taskkill', '/f', '/im', 'lilypond.exe'],
                           capture_output=True, timeout=5)
        except Exception:
            pass
        # Clean up pygame
        try:
            import pygame
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        # Clean up MCI
        try:
            import ctypes
            for dev in ['pianoplayback', 'splashmidi', 'editplayback']:
                ctypes.windll.winmm.mciSendStringW(f'close {dev}', None, 0, None)
        except Exception:
            pass
        # Clean temp files
        for attr in ['_playback_tmp_wav', '_playback_tmp_mid', '_edit_playback_mid']:
            path = getattr(self, attr, None)
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass
        # Remove SVG temp dir
        if hasattr(self, '_svg_dir') and self._svg_dir and os.path.isdir(self._svg_dir):
            try: import shutil; shutil.rmtree(self._svg_dir, ignore_errors=True)
            except: pass
        event.accept()

    def _show_status(self, msg, timeout=0):
        """Show a transient or persistent status message.

        - ``timeout > 0`` (transient): routed through ``ToastManager`` as an
          info-level toast notification that auto-dismisses after ``timeout``
          milliseconds. Spec: "_show_status transient messages use toast".
        - ``timeout == 0`` (persistent): shown in the status bar (e.g.
          "正在播放...", "正在渲染乐谱 (LilyPond)...") — stays until the
          next status update. Spec: "status bar keeps persistent state".
        """
        try:
            if timeout and timeout > 0:
                # Transient -> toast
                mgr = getattr(self, '_toast_manager', None)
                if mgr is None:
                    try:
                        from toast import get_toast_manager as _gtm
                        mgr = _gtm(self)
                        self._toast_manager = mgr
                    except Exception:
                        mgr = None
                if mgr is not None:
                    mgr.info(msg, duration_ms=int(timeout))
                    return
                # Fallback: status bar if toast unavailable
            self.statusBar().showMessage(msg, timeout or 0)
        except Exception:
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
        global _effect_animating
        _effect_animating = True
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

    def _open_settings(self):
        """打开设置对话框（4 Tab：音色 / 模型 / 高级 / 音频）。"""
        from settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.settings_changed.connect(self._apply_settings_after_change)
        dlg.exec()

    def _apply_settings_after_change(self):
        """用户在设置里点了 应用/确认 后调用：刷新音色、混响、灵敏度滑块。"""
        # 1. 强制 reload settings 缓存（settings_dialog 已在外部写了 JSON）
        try:
            import app_settings
            app_settings.load_settings(force_reload=True)
        except Exception as e:
            self.logger.warning(f'[Settings] reload 失败: {e}')
            return
        # 2. 把灵敏度/降噪滑块同步成 settings 里的值
        self._load_settings_into_sliders()
        # 3. 清掉合成音频缓存（音色/混响/gain 可能变了，下次播放会重新合成）
        with self._audio_lock:
            self.audio_data = None
        # 4. 刷新 SoundFont 引擎（自动检测新下载的音色文件）
        try:
            sf2_path = self._find_best_soundfont()
            self.logger.info(f'[Settings] SoundFont 已切换: {os.path.basename(sf2_path) if sf2_path else "自动检测"}')
        except Exception:
            pass
        self.btn_play.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_export.setEnabled(False)
        self._show_status("已应用新设置")

    def _apply_native_acrylic(self):
        """绘制壁纸作为窗口不透明背景层（按钮/卡片半透明叠加其上）。

        算法变更说明：
          - 不再调用 BlurWindow 原生 Acrylic（原方案使窗口背景透明，
            按钮「透出」的是桌面壁纸而非应用背景图层）
          - 现在窗口背景由 paintEvent 绘制不透明光斑壁纸
          - 按钮/卡片用半透明背景透出底层壁纸，实现「按钮透明到背景图层」
        """
        # 触发一次重绘，让 paintEvent 绘制壁纸
        self.update()

    def _setup_wallpaper(self):
        """渲染 Pygame 静态光斑壁纸作为窗口不透明背景层。

        窗口背景不透明，壁纸由 paintEvent 绘制为实色底图。
        按钮/卡片用半透明背景透出此壁纸。
        """
        try:
            from glass_ui import PygameWallpaper
            self._wallpaper = PygameWallpaper.get_instance()
            # 确保壁纸已渲染
            pm = self._wallpaper.get_pixmap()
            if not pm.isNull():
                # 触发 paintEvent 重绘壁纸
                self.setAutoFillBackground(False)
                self.update()
        except Exception:
            pass

    def _paint_wallpaper(self):
        """绘制 Pygame 壁纸作为窗口不透明背景（在 paintEvent 中调用）。"""
        if self._wallpaper is None:
            return
        pm = self._wallpaper.get_pixmap()
        if pm.isNull():
            return
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scaled = pm.scaled(self.size(), Qt.IgnoreAspectRatio,
                           Qt.SmoothTransformation)
        painter.drawPixmap(0, 0, scaled)
        painter.end()  # 显式结束，确保 super().paintEvent 不会冲突

    def paintEvent(self, event):
        """主窗口 paintEvent：先绘制不透明壁纸背景，再绘制子部件。"""
        # 1. 绘制不透明壁纸背景层（按钮/卡片会透出此层）
        self._paint_wallpaper()
        # 2. 让 QMainWindow 绘制子部件（按钮、卡片等）
        super().paintEvent(event)

    def _apply_theme(self, theme_name):
        """Apply the given theme and fade back in."""
        global _current_theme_name
        self.current_theme = theme_name
        _current_theme_name = theme_name

        # Notify the design-token system so tokens() without an explicit theme
        # arg resolves correctly (glass frames, skeleton loaders, etc.).
        try:
            from design_tokens import set_current_theme_name as _set_dt_theme
            _set_dt_theme(theme_name)
        except Exception:
            pass

        # Update global stylesheet
        self.setStyleSheet(get_stylesheet(theme_name))

        # Update theme toggle button icons (SVG sun/moon, with emoji fallback).
        try:
            from app_icons import icon as _svg_icon
            _icon_name = 'moon' if theme_name == 'light' else 'sun'
            for btn_attr in ['_theme_toggle_btn', '_theme_btn_analysis', '_theme_btn_edit']:
                if hasattr(self, btn_attr):
                    btn = getattr(self, btn_attr)
                    try:
                        btn.setIcon(_svg_icon(_icon_name, size=20, theme_name=theme_name))
                        btn.setIconSize(QSize(20, 20))
                        btn.setText('')
                    except Exception:
                        btn.setText('🌙' if theme_name == 'light' else '☀️')
        except Exception:
            icon = '🌙' if theme_name == 'light' else '☀️'
            for btn_attr in ['_theme_toggle_btn', '_theme_btn_analysis', '_theme_btn_edit']:
                if hasattr(self, btn_attr):
                    getattr(self, btn_attr).setText(icon)

        # Update ModeCards
        if hasattr(self, '_cards'):
            for card in self._cards:
                card.update_theme(theme_name)

        # Update custom title bar (无边框窗口标题栏)
        if hasattr(self, '_title_bar'):
            self._title_bar.update_theme(theme_name)

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

        # Refresh every LiquidGlassFrame / AcrylicContainer so glass borders,
        # highlights, and tints track the new theme tokens.
        self._refresh_glass_frames(theme_name)

        # Refresh active toast notifications so accent bars, card backgrounds,
        # and icons follow the new theme tokens.
        try:
            mgr = getattr(self, '_toast_manager', None)
            if mgr is not None:
                mgr.refresh_theme()
        except Exception:
            pass

        # Trigger repaint on piano roll widgets
        if hasattr(self, 'piano_roll'):
            _safe_update(self.piano_roll)
        if hasattr(self, 'edit_piano_roll'):
            _safe_update(self.edit_piano_roll)

        # Fade in animation
        central = self.centralWidget()
        if hasattr(self, '_theme_opacity_effect') and self._theme_opacity_effect:
            anim_in = QPropertyAnimation(self._theme_opacity_effect, b"opacity")
            anim_in.setDuration(200)
            anim_in.setStartValue(0.0)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QEasingCurve.InCubic)
            def _theme_fade_done():
                global _effect_animating
                _effect_animating = False
                central.setGraphicsEffect(None)
            anim_in.finished.connect(_theme_fade_done)
            anim_in.start()
            self._theme_anim_in = anim_in  # keep reference

    def _refresh_glass_frames(self, theme_name):
        """Walk every LiquidGlassFrame descendant and re-apply theme tokens.

        Covers `LiquidGlassFrame` and its subclass `AcrylicContainer`.
        Lazy import keeps `glass_ui` out of the module top-level so a circular
        import can never crash theme switching. Any per-frame exception is
        swallowed so one bad widget doesn't break the rest of the sweep.
        """
        try:
            from glass_ui import LiquidGlassFrame
        except Exception:
            return
        for frame in self.findChildren(LiquidGlassFrame):
            try:
                frame.update_theme(theme_name)
            except Exception:
                continue

    def _refresh_inline_styles(self, theme_name):
        """Refresh all inline stylesheets for the given theme."""
        t = THEMES[theme_name]

        # === Main page widgets ===
        if hasattr(self, '_main_title'):
            # Brand-gradient title — refresh gradient stops (painter handles color).
            try:
                from design_tokens import brand_gradient_qcolor_tuple as _brand_grad
                self._main_title.set_gradient(list(_brand_grad(theme_name)))
            except Exception:
                # Fallback: solid-color stylesheet for non-gradient QLabel.
                self._main_title.setStyleSheet(
                    f"font-size: 32px; font-weight: bold; color: {t['accent']}; "
                    f"border: none; background: transparent;")
        if hasattr(self, '_main_subtitle'):
            self._main_subtitle.setStyleSheet(
                f"font-size: 16px; color: {t['text_secondary']}; border: none; background: transparent;")
        if hasattr(self, '_main_tagline'):
            self._main_tagline.setStyleSheet(
                f"font-size: 12px; color: {t['hint_text']}; border: none; "
                f"background: transparent; letter-spacing: 1px;")
        if hasattr(self, '_version_label'):
            self._version_label.setStyleSheet(
                f"font-size: 11px; color: {t['hint_text']}; border: none; background: transparent;")
        if hasattr(self, '_monogram_label'):
            try:
                from app_icons import icon_pixmap as _icon_pixmap
                from design_tokens import qcolor as _qcolor, tokens as _tokens
                _accent = _qcolor(getattr(_tokens(theme_name).color, 'accent', t['accent']))
                self._monogram_label.setPixmap(
                    _icon_pixmap('monogram', size=20, color=_accent, theme_name=theme_name))
            except Exception:
                pass

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

        # Zoom buttons — refresh background style and SVG icons.
        # btn_zout / btn_zin use SVG icons; btn_fit keeps its "适应" text.
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
        # Refresh SVG icons on zoom buttons (theme-aware).
        for btn_attr, icon_name in [('_btn_zout', 'zoom_out'), ('_btn_zin', 'zoom_in')]:
            if hasattr(self, btn_attr):
                btn = getattr(self, btn_attr)
                try:
                    from app_icons import icon
                    btn.setIcon(icon(icon_name, size=16, theme_name=theme_name))
                    btn.setIconSize(QSize(16, 16))
                except Exception:
                    pass

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
            # Spec: 64px monospace for difficulty number.
            self.diff_level.setStyleSheet(
                f"font-size: 64px; font-weight: bold; "
                f"font-family: 'JetBrains Mono','Cascadia Mono','Consolas','Menlo','monospace'; "
                f"color: {dc}; border: none;")
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

        # === Analysis page SVG icon refresh ===
        # Input card icon (music_note)
        if hasattr(self, '_input_card_icon'):
            self._refresh_svg_icon(self._input_card_icon, 'music_note', 22, theme_name)
        # Section header icons (difficulty / stats / playback / denoise)
        for attr, icon_name in [
            ('_diff_icon', 'difficulty'),
            ('_stats_icon', 'stats'),
            ('_playback_icon', 'playback'),
            ('_denoise_icon', 'denoise'),
        ]:
            if hasattr(self, attr):
                self._refresh_svg_icon(getattr(self, attr), icon_name, 18, theme_name)
        # Action button icons (play / stop / export)
        for btn_attr, icon_name in [
            ('btn_play', 'play'),
            ('btn_stop', 'stop'),
            ('btn_export', 'download'),
        ]:
            if hasattr(self, btn_attr):
                btn = getattr(self, btn_attr)
                try:
                    from app_icons import icon
                    btn.setIcon(icon(icon_name, size=16, theme_name=theme_name))
                    btn.setIconSize(QSize(16, 16))
                except Exception:
                    pass
        # Empty-state placeholders (sheet music + piano roll)
        if hasattr(self, 'sheet_empty') and self.sheet_empty is not None:
            try:
                self.sheet_empty.update_theme(theme_name)
            except Exception:
                pass
        if hasattr(self, 'roll_empty') and self.roll_empty is not None:
            try:
                self.roll_empty.update_theme(theme_name)
            except Exception:
                pass

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

        # === Edit page SVG icon refresh ===
        # Title icon (music_note)
        if hasattr(self, '_edit_title_icon') and self._edit_title_icon is not None:
            self._refresh_svg_icon(self._edit_title_icon, 'music_note', 16, theme_name)
        # Back button SVG icon
        if hasattr(self, 'btn_back_edit'):
            try:
                from app_icons import icon
                self.btn_back_edit.setIcon(icon('back', size=16, theme_name=theme_name))
                self.btn_back_edit.setIconSize(QSize(16, 16))
            except Exception:
                pass
        # Tool buttons (cursor / pencil / eraser)
        for btn_attr, icon_name in [
            ('btn_tool_select', 'cursor'),
            ('btn_tool_pencil', 'pencil'),
            ('btn_tool_eraser', 'eraser'),
        ]:
            if hasattr(self, btn_attr):
                btn = getattr(self, btn_attr)
                try:
                    from app_icons import icon
                    btn.setIcon(icon(icon_name, size=16, theme_name=theme_name))
                    btn.setIconSize(QSize(16, 16))
                except Exception:
                    pass
        # Undo / redo / play / stop icons
        for btn_attr, icon_name in [
            ('btn_undo_edit', 'undo'),
            ('btn_redo_edit', 'redo'),
            ('btn_edit_play', 'play'),
            ('btn_edit_stop', 'stop'),
        ]:
            if hasattr(self, btn_attr):
                btn = getattr(self, btn_attr)
                try:
                    from app_icons import icon
                    btn.setIcon(icon(icon_name, size=16, theme_name=theme_name))
                    btn.setIconSize(QSize(16, 16))
                except Exception:
                    pass
        # Roll zoom buttons
        for btn_attr, icon_name in [
            ('btn_roll_zout', 'zoom_out'),
            ('btn_roll_zin', 'zoom_in'),
        ]:
            if hasattr(self, btn_attr):
                btn = getattr(self, btn_attr)
                try:
                    from app_icons import icon
                    btn.setIcon(icon(icon_name, size=16, theme_name=theme_name))
                    btn.setIconSize(QSize(16, 16))
                except Exception:
                    pass
        # Sheet zoom buttons
        for btn_attr, icon_name in [
            ('_btn_edit_zout', 'zoom_out'),
            ('_btn_edit_zin', 'zoom_in'),
        ]:
            if hasattr(self, btn_attr):
                btn = getattr(self, btn_attr)
                try:
                    from app_icons import icon
                    btn.setIcon(icon(icon_name, size=14, theme_name=theme_name))
                    btn.setIconSize(QSize(14, 14))
                except Exception:
                    pass
        # Import / export button icons
        if hasattr(self, 'btn_import_mid'):
            try:
                from app_icons import icon
                self.btn_import_mid.setIcon(icon('import', size=14, theme_name=theme_name))
                self.btn_import_mid.setIconSize(QSize(14, 14))
            except Exception:
                pass
        for btn_attr in ['btn_export_mid', 'btn_export_wav', 'btn_export_pdf']:
            if hasattr(self, btn_attr):
                btn = getattr(self, btn_attr)
                try:
                    from app_icons import icon
                    btn.setIcon(icon('download', size=14, theme_name=theme_name))
                    btn.setIconSize(QSize(14, 14))
                except Exception:
                    pass
        # Edit page empty-state placeholder (theme-aware)
        if hasattr(self, 'edit_empty') and self.edit_empty is not None:
            try:
                self.edit_empty.update_theme(theme_name)
            except Exception:
                pass

    def _refresh_denoise_styles(self, theme_name):
        """Refresh denoise section inline styles.

        Note: the three mode-toggle buttons (btn_denoise_auto/manual/off) and
        the parameter sliders no longer carry inline style overrides — they
        rely on the global ``#segPill`` / ``QSlider`` stylesheets. Only the
        per-mode label colors (which depend on ``self.denoise_mode``) and the
        Apply/Reset button styling are refreshed here.
        """
        t = THEMES[theme_name]
        is_manual = self.denoise_mode == 'manual'

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
    #  SVG ICON / SECTION HEADER HELPERS
    # ================================================================
    def _make_icon_button(self, icon_name, text, size=16):
        """Create a QPushButton with an SVG icon + text label.

        Falls back to a plain text button if the icon system is unavailable.
        """
        btn = QPushButton(text)
        try:
            from app_icons import icon
            from design_tokens import get_current_theme_name
            theme = get_current_theme_name()
            btn.setIcon(icon(icon_name, size=size, theme_name=theme))
            btn.setIconSize(QSize(size, size))
        except Exception:
            pass
        return btn

    def _make_section_header(self, icon_name, text):
        """Create a section header row: SVG icon + bold title QLabel.

        Returns ``(row_layout, icon_label, title_label)`` so the caller can
        store references for theme refresh.
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)

        icon_lbl = QLabel()
        icon_lbl.setStyleSheet("border: none; background: transparent;")
        try:
            from app_icons import icon_pixmap
            from design_tokens import qcolor, tokens, get_current_theme_name
            theme = get_current_theme_name()
            accent_color = qcolor(getattr(tokens(theme).color, 'accent'))
            icon_lbl.setPixmap(icon_pixmap(icon_name, size=18,
                                           color=accent_color, theme_name=theme))
        except Exception:
            pass
        icon_lbl._section_icon_name = icon_name
        row.addWidget(icon_lbl)

        title = QLabel(text)
        title.setObjectName("cardTitle")
        row.addWidget(title)
        row.addStretch()

        return row, icon_lbl, title

    def _refresh_svg_icon(self, widget, icon_name, size, theme_name,
                          color_key='accent'):
        """Refresh an SVG icon on a widget (QLabel pixmap or QPushButton icon)."""
        try:
            from app_icons import icon_pixmap, icon
            from design_tokens import qcolor, tokens
            color = qcolor(getattr(tokens(theme_name).color, color_key))
            if hasattr(widget, 'setPixmap'):
                widget.setPixmap(icon_pixmap(icon_name, size=size,
                                             color=color, theme_name=theme_name))
            elif hasattr(widget, 'setIcon'):
                widget.setIcon(icon(icon_name, size=size,
                                        color=color, theme_name=theme_name))
        except Exception:
            pass

    def _show_sheet_content(self, show_actual=True):
        """Switch the sheet-music stack between the actual widget and the
        empty-state placeholder. No-op if the stack hasn't been built yet.
        """
        if hasattr(self, 'sheet_stack'):
            target = self.sheet_widget if show_actual else self.sheet_empty
            self.sheet_stack.setCurrentWidget(target)

    def _show_roll_content(self, show_actual=True):
        """Switch the piano-roll stack between the actual widget and the
        empty-state placeholder. No-op if the stack hasn't been built yet.
        """
        if hasattr(self, 'roll_stack'):
            target = self.piano_roll if show_actual else self.roll_empty
            self.roll_stack.setCurrentWidget(target)

    def _show_edit_content(self, show_actual=True):
        """Switch the edit-page stack between the actual edit view (splitter)
        and the empty-state placeholder. No-op if the stack hasn't been built.
        """
        if hasattr(self, 'edit_stack'):
            if show_actual:
                # Index 1 is the splitter (actual edit view).
                self.edit_stack.setCurrentIndex(1)
            elif self.edit_empty is not None:
                self.edit_stack.setCurrentWidget(self.edit_empty)

    # ================================================================
    #  ANIMATION HELPERS
    # ================================================================
    def _animate_button_click(self, button, click_pos=None):
        """HarmonyOS 6.1 button click: shrink then restore + radial ripple.

        Parameters
        ----------
        button : QPushButton
            The button that was clicked.
        click_pos : QPoint, optional
            The click position in the button's local coordinates. If None,
            defaults to the button's center (since the ``clicked`` signal does
            not carry position info).
        """
        anim = QPropertyAnimation(button, b"geometry")
        geo = button.geometry()
        anim.setKeyValueAt(0, geo)
        anim.setKeyValueAt(0.3, geo.adjusted(2, 2, -2, -2))
        anim.setKeyValueAt(1, geo)
        anim.setDuration(150)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._btn_anim = anim  # keep reference

        # Spawn a radial ripple overlay from the click point.
        try:
            from design_tokens import qcolor, tokens
            ripple_color = qcolor(tokens().color.accent)
            ripple_color.setAlpha(80)
        except Exception:
            ripple_color = QColor(0, 125, 255, 80)
        if click_pos is None:
            click_pos = QPoint(button.width() // 2, button.height() // 2)
        try:
            RippleOverlay(button, click_pos, ripple_color)
        except Exception:
            pass  # ripple is decorative — never break click handling.

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
            pos_anim.setEasingCurve(QEasingCurve.OutCubic)

            # Keep references to prevent garbage collection
            self._card_anims.append((opacity_anim, pos_anim))

            QTimer.singleShot(delay, lambda oa=opacity_anim, pa=pos_anim: (oa.start(), pa.start()))

    def _restore_main_page_anim(self):
        """清理页面过渡后残留的 QGraphicsEffect + 刷新主题样式。"""
        if hasattr(self, '_main_page'):
            self._main_page.setGraphicsEffect(None)
        # 重新应用当前主题到主页与卡片（反复切换页面可能导致缓存过时）
        if hasattr(self, '_main_page'):
            t = THEMES.get(self.current_theme, THEMES['dark'])
            self._main_page.setStyleSheet(f"background-color: {t['page_bg']};")
        if hasattr(self, '_cards'):
            for card in self._cards:
                card.setGraphicsEffect(None)
                card.update_theme(self.current_theme)
                card.invalidate_cache()
                card._glow_timer.start()

    def _clear_page_effects(self, widget):
        """清理页面过渡后残留的 QGraphicsEffect。"""
        if widget is not None:
            widget.setGraphicsEffect(None)

    def _switch_page(self, index):
        """Switch page with fade-out + horizontal slide-left animation."""
        global _effect_animating
        _effect_animating = True

        current = self.stacked_widget.currentWidget()
        if current is None or self.stacked_widget.currentIndex() == index:
            self.stacked_widget.setCurrentIndex(index)
            _effect_animating = False
            return

        # Capture original position so we can restore it after the transient slide.
        self._page_out_original_pos = current.pos()

        # Fade-out + slide-left (30px) in parallel (200ms, OutCubic).
        self._page_opacity_out = QGraphicsOpacityEffect(current)
        current.setGraphicsEffect(self._page_opacity_out)
        opacity_out = QPropertyAnimation(self._page_opacity_out, b"opacity")
        opacity_out.setDuration(200)
        opacity_out.setStartValue(1.0)
        opacity_out.setEndValue(0.0)
        opacity_out.setEasingCurve(QEasingCurve.OutCubic)

        pos_out = QPropertyAnimation(current, b"pos")
        pos_out.setDuration(200)
        pos_out.setStartValue(self._page_out_original_pos)
        pos_out.setEndValue(self._page_out_original_pos + QPoint(-30, 0))
        pos_out.setEasingCurve(QEasingCurve.OutCubic)

        self._page_slide_out = QParallelAnimationGroup()
        self._page_slide_out.addAnimation(opacity_out)
        self._page_slide_out.addAnimation(pos_out)

        self._pending_page_index = index
        self._page_slide_out.finished.connect(self._do_show_page)
        self._page_slide_out.start()
        self._anim_out = opacity_out  # keep reference (backward-compat)

    def _do_show_page(self):
        """Show the pending page with fade-in + slide-from-right animation."""
        index = self._pending_page_index
        if index is None:
            return
        self._pending_page_index = None

        # Restore the old page's position (the slide was a transient visual effect).
        old_widget = self.stacked_widget.currentWidget()
        if old_widget is not None:
            old_widget.setGraphicsEffect(None)
            original_pos = getattr(self, '_page_out_original_pos', None)
            if original_pos is not None:
                old_widget.move(original_pos)
                self._page_out_original_pos = None

        self.stacked_widget.setCurrentIndex(index)

        # Fade-in + slide-from-right (30px -> 0) in parallel (200ms, InCubic).
        new_widget = self.stacked_widget.currentWidget()
        self._page_opacity_in = QGraphicsOpacityEffect(new_widget)
        new_widget.setGraphicsEffect(self._page_opacity_in)
        opacity_in = QPropertyAnimation(self._page_opacity_in, b"opacity")
        opacity_in.setDuration(200)
        opacity_in.setStartValue(0.0)
        opacity_in.setEndValue(1.0)
        opacity_in.setEasingCurve(QEasingCurve.InCubic)

        final_pos = new_widget.pos()
        start_pos = final_pos + QPoint(30, 0)
        new_widget.move(start_pos)
        pos_in = QPropertyAnimation(new_widget, b"pos")
        pos_in.setDuration(200)
        pos_in.setStartValue(start_pos)
        pos_in.setEndValue(final_pos)
        pos_in.setEasingCurve(QEasingCurve.InCubic)

        self._page_slide_in = QParallelAnimationGroup()
        self._page_slide_in.addAnimation(opacity_in)
        self._page_slide_in.addAnimation(pos_in)
        self._page_slide_in.start()
        self._anim_in = opacity_in  # keep reference (backward-compat)

        # Belt-and-suspenders: clear opacity effect after animation + re-enable
        # play button when returning to analysis page with existing notes.
        def _on_slide_in_done():
            global _effect_animating
            _effect_animating = False
            self._clear_page_effects(new_widget)
            # If returning to analysis page with notes, re-check play button
            if index == 1 and hasattr(self, 'sheet_widget') and \
               self.sheet_widget.display_notes:
                if not self.btn_play.isEnabled():
                    self.btn_play.setEnabled(True)
                    self.logger.info('[PageSwitch] 恢复播放按钮')
        self._page_slide_in.finished.connect(_on_slide_in_done)

        if index == 0:
            self._animate_cards_entrance()
            # 卡片入场动画完成后恢复 glow 定时器 + 粒子
            restore_delay = 100 + (len(self._cards) - 1) * 80 + 350
            QTimer.singleShot(restore_delay, self._restore_main_page_anim)

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
        # 粒子背景效果（已移至主页面内，此处仅保留实例但停用）
        self._particle_bg = ParticleBackground(self)
        self._particle_bg.lower()
        self._particle_bg.hide()
        self._particle_bg._timer.stop()
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_particle_bg'):
            self._particle_bg.setGeometry(self.rect())
        if hasattr(self, '_main_particles') and hasattr(self, '_main_page'):
            self._main_particles.setGeometry(self._main_page.rect())

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

        # Theme toggle button — SVG sun/moon icon (replaces legacy emoji).
        self._theme_toggle_btn = QPushButton()
        self._theme_toggle_btn.setObjectName('themeToggle')
        self._theme_toggle_btn.setToolTip('切换深色/浅色主题')
        self._theme_toggle_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._theme_toggle_btn.clicked.connect(self._toggle_theme)
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name as _get_theme_name
            _t_name = _get_theme_name()
            _icon_name = 'moon' if _t_name == 'light' else 'sun'
            self._theme_toggle_btn.setIcon(_svg_icon(_icon_name, size=20, theme_name=_t_name))
            self._theme_toggle_btn.setIconSize(QSize(20, 20))
            self._theme_toggle_btn.setText('')
        except Exception:
            # Non-emoji text fallback (SVG icons unavailable).
            self._theme_toggle_btn.setText('--' if _current_theme_name == 'light' else '==')
        top_bar.addWidget(self._theme_toggle_btn)

        # Settings gear button — opens the 4-tab SettingsDialog.
        self._settings_btn = QPushButton()
        self._settings_btn.setObjectName('settingsGear')
        self._settings_btn.setToolTip('设置（音色 / 模型 / 高级参数 / 音频）')
        self._settings_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._settings_btn.clicked.connect(self._open_settings)
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name as _get_theme_name
            _t_name = _get_theme_name()
            self._settings_btn.setIcon(_svg_icon('settings', size=20, theme_name=_t_name))
            self._settings_btn.setIconSize(QSize(20, 20))
            self._settings_btn.setText('')
        except Exception:
            self._settings_btn.setText('⚙')
        # Match the theme-toggle button's chrome style.
        self._settings_btn.setStyleSheet(
            f"border: none; background: transparent; padding: 4px;")
        top_bar.addWidget(self._settings_btn)
        layout.addLayout(top_bar)

        # Title with brand-gradient fill (painted via GradientTextLabel.paintEvent).
        title_layout = QVBoxLayout()
        title_layout.setSpacing(8)

        title = GradientTextLabel("PianoScribe")
        title.setAlignment(Qt.AlignCenter)
        self._main_title = title
        try:
            from design_tokens import qfont as _qfont, brand_gradient_qcolor_tuple as _brand_grad
            title.setFont(_qfont('display'))
            title.set_gradient(list(_brand_grad()))
        except Exception:
            # Fallback: legacy solid-color style if design_tokens unavailable.
            title.setStyleSheet(
                f"font-size: 38px; font-weight: bold; color: {t['accent']}; "
                f"border: none; background: transparent; letter-spacing: 2px;")
        else:
            # Gradient is painted by QPainter; stylesheet only needs to clear chrome.
            title.setStyleSheet("border: none; background: transparent; letter-spacing: 1px;")
        title_layout.addWidget(title)

        subtitle = QLabel("专业AI钢琴乐谱转录工具")
        subtitle.setAlignment(Qt.AlignCenter)
        self._main_subtitle = subtitle
        subtitle.setStyleSheet(
            f"font-size: 16px; color: {t['text_secondary']}; border: none; background: transparent;")
        title_layout.addWidget(subtitle)

        # Tagline row below the subtitle.
        tagline = QLabel("AI-powered sheet music transcription")
        tagline.setAlignment(Qt.AlignCenter)
        self._main_tagline = tagline
        tagline.setStyleSheet(
            f"font-size: 12px; color: {t['hint_text']}; border: none; "
            f"background: transparent; letter-spacing: 1px;")
        title_layout.addWidget(tagline)

        layout.addLayout(title_layout)
        layout.addSpacing(20)

        # Mode cards in 2x2 grid (SVG icons from app_icons registry).
        grid_layout = QGridLayout()
        grid_layout.setSpacing(24)
        grid_layout.setAlignment(Qt.AlignCenter)

        cards = [
            ("mic", "弹唱模式", "仅伴奏", "accomp"),
            ("waveform", "人声模式", "仅人声", "vocal"),
            ("piano", "标准模式", "伴奏+人声", "standard"),
            ("edit", "编辑模式", "导入编辑", "edit"),
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

        # Version row with brand monogram icon.
        version_row = QHBoxLayout()
        version_row.setSpacing(8)
        version_row.setAlignment(Qt.AlignCenter)

        monogram_label = QLabel()
        monogram_label.setStyleSheet("border: none; background: transparent;")
        self._monogram_label = monogram_label
        try:
            from app_icons import icon_pixmap as _icon_pixmap
            from design_tokens import qcolor as _qcolor, tokens as _tokens
            _accent = _qcolor(getattr(_tokens(_current_theme_name).color, 'accent', t['accent']))
            monogram_label.setPixmap(_icon_pixmap('monogram', size=20, color=_accent,
                                                  theme_name=_current_theme_name))
        except Exception:
            pass
        version_row.addWidget(monogram_label)

        version_label = QLabel("v0.7 beta | 钢琴乐谱生成器")
        version_label.setAlignment(Qt.AlignCenter)
        self._version_label = version_label
        version_label.setStyleSheet(
            f"font-size: 11px; color: {t['hint_text']}; border: none; background: transparent;")
        version_row.addWidget(version_label)

        layout.addLayout(version_row)

        # 主页面内嵌粒子动画（在 ModeCards 下方）— 确保粒子始终可见
        self._main_particles = ParticleBackground(page)
        self._main_particles.lower()

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
        self.btn_back_analysis.setFixedWidth(120)
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

        # 缩放控件（- / 1.0x / + / 适应）— 置于顶栏
        top_bar.addSpacing(16)
        btn_zout = QPushButton()
        btn_zout.setFixedSize(30, 30)
        self._btn_zout = btn_zout
        btn_zout.setStyleSheet(
            f"QPushButton {{ border-radius: 15px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 16px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        try:
            from app_icons import icon
            from design_tokens import get_current_theme_name
            btn_zout.setIcon(icon('zoom_out', size=16, theme_name=get_current_theme_name()))
            btn_zout.setIconSize(QSize(16, 16))
        except Exception:
            pass
        btn_zout.clicked.connect(lambda: (self.sheet_widget.zoom_out(), self._update_zoom_label()))
        top_bar.addWidget(btn_zout)

        self.zoom_label = QLabel("1.0x")
        self.zoom_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px; min-width: 40px; border: none;")
        top_bar.addWidget(self.zoom_label)

        btn_zin = QPushButton()
        btn_zin.setFixedSize(30, 30)
        self._btn_zin = btn_zin
        btn_zin.setStyleSheet(
            f"QPushButton {{ border-radius: 15px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 16px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        try:
            from app_icons import icon
            from design_tokens import get_current_theme_name
            btn_zin.setIcon(icon('zoom_in', size=16, theme_name=get_current_theme_name()))
            btn_zin.setIconSize(QSize(16, 16))
        except Exception:
            pass
        btn_zin.clicked.connect(lambda: (self.sheet_widget.zoom_in(), self._update_zoom_label()))
        top_bar.addWidget(btn_zin)

        btn_fit = QPushButton("适应")
        self._btn_fit = btn_fit
        btn_fit.setStyleSheet(
            f"QPushButton {{ border-radius: 15px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 12px; color: {t['zoom_btn_text']}; padding: 4px 12px; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        btn_fit.clicked.connect(lambda: (self.sheet_widget.zoom_fit(), self._update_zoom_label()))
        top_bar.addWidget(btn_fit)

        top_bar.addStretch()

        # 分离模式提示按钮（右上角 info 图标）
        self._separation_info_btn = QPushButton()
        self._separation_info_btn.setObjectName('separationInfo')
        self._separation_info_btn.setToolTip('分离模式说明')
        self._separation_info_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._separation_info_btn.setFixedSize(36, 36)
        try:
            from app_icons import icon
            from design_tokens import get_current_theme_name
            _t = get_current_theme_name()
            self._separation_info_btn.setIcon(icon('info', size=18, theme_name=_t))
            self._separation_info_btn.setIconSize(QSize(18, 18))
        except Exception:
            self._separation_info_btn.setText('?')
        self._separation_info_btn.setStyleSheet(f"""
            QPushButton#separationInfo {{
                border-radius: 18px; padding: 0; margin: 0;
                background-color: {t['surface']};
                border: 1px solid {t['card_border']};
                color: {t['text_secondary']};
            }}
            QPushButton#separationInfo:hover {{
                border-color: {t['accent']};
                color: {t['accent']};
                background-color: {t['card_hover_bg']};
            }}
        """)
        self._separation_info_btn.clicked.connect(self._show_separation_mode_popup)
        top_bar.addWidget(self._separation_info_btn)

        # Theme toggle on analysis page (SVG sun/moon)
        theme_btn_analysis = QPushButton()
        theme_btn_analysis.setObjectName('themeToggle')
        theme_btn_analysis.setToolTip('切换深色/浅色主题')
        theme_btn_analysis.setCursor(QCursor(Qt.PointingHandCursor))
        theme_btn_analysis.clicked.connect(self._toggle_theme)
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name
            _t = get_current_theme_name()
            _icon_name = 'moon' if _t == 'light' else 'sun'
            theme_btn_analysis.setIcon(_svg_icon(_icon_name, size=20, theme_name=_t))
            theme_btn_analysis.setIconSize(QSize(20, 20))
        except Exception:
            pass
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

        icon_label = QLabel()
        icon_label.setStyleSheet("border: none; background: transparent;")
        try:
            from app_icons import icon_pixmap
            from design_tokens import qcolor, tokens, get_current_theme_name
            _theme = get_current_theme_name()
            _accent_color = qcolor(getattr(tokens(_theme).color, 'accent'))
            icon_label.setPixmap(icon_pixmap('music_note', size=22,
                                              color=_accent_color, theme_name=_theme))
        except Exception:
            # SVG system unavailable — leave the label empty (no emoji fallback
            # per the analysis-page refresh spec).
            pass
        self._input_card_icon = icon_label
        input_layout.addWidget(icon_label)

        self.audio_label = QLabel("选择音频文件开始分析")
        self.audio_label.setStyleSheet(
            f"font-size: 14px; color: {t['audio_label_color']}; border: none;")
        input_layout.addWidget(self.audio_label, 1)

        self.btn_select = QPushButton("选择音频")
        self.btn_select.setFixedWidth(130)
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

        # Sheet music widget (created early so toolbar can reference it)
        self.sheet_widget = SheetMusicWidget()
        self.sheet_widget.rendering_done.connect(self._on_sheet_rendered)
        self.sheet_widget.rendering_progress.connect(self._on_render_progress)
        self.sheet_widget.page_changed.connect(self._on_page_changed)

        # Sheet toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)

        title = QLabel("五线谱")
        title.setObjectName("cardTitle")
        self._sheet_title = title
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {t['text_primary']}; border: none;")
        toolbar.addWidget(title)

        toolbar.addSpacing(12)

        # Page navigation
        self.btn_prev_page = QPushButton("◀")
        self.btn_prev_page.setFixedSize(32, 28)
        self.btn_prev_page.setToolTip("上一页")
        self.btn_prev_page.setStyleSheet(
            f"QPushButton {{ border-radius: 14px; background: {t['zoom_btn_bg']};"
            f" border: 1px solid {t['zoom_btn_border']}; color: {t['zoom_btn_text']};"
            f" font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        self.btn_prev_page.clicked.connect(self.sheet_widget.prev_page)
        self.btn_prev_page.setVisible(False)
        toolbar.addWidget(self.btn_prev_page)

        self.page_label = QLabel("")
        self.page_label.setStyleSheet(
            f"color: {t['text_secondary']}; font-size: 11px;"
            f" min-width: 40px; qproperty-alignment: AlignCenter; border: none;")
        toolbar.addWidget(self.page_label)

        self.btn_next_page = QPushButton("▶")
        self.btn_next_page.setFixedSize(32, 28)
        self.btn_next_page.setToolTip("下一页")
        self.btn_next_page.setStyleSheet(
            f"QPushButton {{ border-radius: 14px; background: {t['zoom_btn_bg']};"
            f" border: 1px solid {t['zoom_btn_border']}; color: {t['zoom_btn_text']};"
            f" font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        self.btn_next_page.clicked.connect(self.sheet_widget.next_page)
        self.btn_next_page.setVisible(False)
        toolbar.addWidget(self.btn_next_page)

        toolbar.addStretch()

        hint = QLabel("LilyPond 专业乐谱渲染 | 滚轮滚动 | Ctrl+滚轮缩放")
        hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none;")
        self._sheet_hint = hint
        toolbar.addWidget(hint)

        sheet_layout.addLayout(toolbar)

        # Wrap in QStackedWidget with EmptyState placeholder
        try:
            from empty_state import EmptyState
            self.sheet_empty = EmptyState(
                illustration='sheet_music',
                title='等待音频加载',
                subtitle='LilyPond 专业五线谱渲染',
                cta_text='选择音频',
                on_cta=self.select_audio,
                parent=self.sheet_widget.parentWidget() if self.sheet_widget.parentWidget() else None,
            )
        except Exception:
            self.sheet_empty = None
        self.sheet_stack = QStackedWidget()
        self.sheet_stack.addWidget(self.sheet_widget)
        if self.sheet_empty is not None:
            self.sheet_stack.addWidget(self.sheet_empty)
            self.sheet_stack.setCurrentWidget(self.sheet_empty)
        sheet_layout.addWidget(self.sheet_stack, 1)

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

        # Piano roll widget — wrapped in a QStackedWidget with an EmptyState
        # placeholder shown until notes are loaded.
        self.piano_roll = PianoRollWidget()

        try:
            from empty_state import EmptyState
            self.roll_empty = EmptyState(
                illustration='piano_roll',
                title='暂无音符数据',
                subtitle='88 键钢琴卷帘可视化',
                parent=self.piano_roll.parentWidget() if self.piano_roll.parentWidget() else None,
            )
        except Exception:
            self.roll_empty = None
        self.roll_stack = QStackedWidget()
        self.roll_stack.addWidget(self.piano_roll)
        if self.roll_empty is not None:
            self.roll_stack.addWidget(self.roll_empty)
            self.roll_stack.setCurrentWidget(self.roll_empty)
        roll_layout.addWidget(self.roll_stack, 1)

        left_layout.addWidget(roll_card, 2)

        splitter.addWidget(left_widget)

        # Right: Info panel (card)
        info_card = QFrame()
        info_card.setObjectName("cardFrame")
        self._info_card = info_card
        info_card.setStyleSheet(
            f"QFrame#cardFrame {{ background-color: {t['card_bg']}; border-radius: 16px; border: 1px solid {t['card_border']}; }}")
        info_card.setFixedWidth(380)
        # 将内容包裹在 QScrollArea 中，超出高度时可滚动查看
        # （避免降噪/灵敏度底部的「恢复默认」按钮被截断）
        scroll_area = QScrollArea(info_card)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(0, 0, 0, 0.2); border-radius: 4px; min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(0, 0, 0, 0.35);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)
        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        content_widget.setMinimumWidth(380 - 8)  # 留滚动条空间

        # info_layout 指向 content_widget 的布局（后续所有 addXxx 不变）
        info_layout = QVBoxLayout(content_widget)
        info_layout.setContentsMargins(18, 18, 18, 18)
        info_layout.setSpacing(10)

        scroll_area.setWidget(content_widget)
        # info_card 外层布局只承载滚动区域
        outer_layout = QVBoxLayout(info_card)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(scroll_area)

        # Difficulty display — section header (SVG icon + bold title)
        diff_header, diff_icon, diff_title = self._make_section_header('difficulty', '难度分级')
        info_layout.addLayout(diff_header)
        self._diff_icon = diff_icon
        self._diff_title_label = diff_title

        self.diff_level = QLabel("--")
        self.diff_level.setAlignment(Qt.AlignCenter)
        # Spec: "难度数字使用 64px 等宽字体居中显示" — 64px monospace, centered.
        self.diff_level.setStyleSheet(
            f"font-size: 64px; font-weight: bold; font-family: 'JetBrains Mono','Cascadia Mono','Consolas','Menlo','monospace'; color: {t['info_diff_level']}; border: none;")
        info_layout.addWidget(self.diff_level)

        self.diff_name = QLabel("等待分析")
        self.diff_name.setAlignment(Qt.AlignCenter)
        self.diff_name.setStyleSheet(
            f"font-size: 18px; color: {t['info_diff_name']}; font-weight: bold; border: none;")
        info_layout.addWidget(self.diff_name)

        self.diff_detail = QLabel("")
        self.diff_detail.setWordWrap(True)
        self.diff_detail.setMinimumWidth(320)
        self.diff_detail.setStyleSheet(f"font-size: 11px; color: {t['info_diff_detail']}; border: none;")
        info_layout.addWidget(self.diff_detail)

        # Difficulty button group — segmented control (#segmentedControl +
        # #segPill). The QButtonGroup exclusivity logic is preserved.
        diff_select_label = QLabel("难度选择:")
        self._diff_select_label = diff_select_label
        diff_select_label.setStyleSheet(f"font-size: 12px; color: {t['text_secondary']}; border: none;")
        info_layout.addWidget(diff_select_label)

        diff_segment = QFrame()
        diff_segment.setObjectName("segmentedControl")
        diff_btn_layout = QHBoxLayout(diff_segment)
        diff_btn_layout.setContentsMargins(4, 4, 4, 4)
        diff_btn_layout.setSpacing(2)
        self.diff_buttons = {}
        self.diff_button_group = QButtonGroup(self)
        self.diff_button_group.setExclusive(True)

        difficulties = ["入门", "初级", "中级", "高级", "专业"]
        for i, diff in enumerate(difficulties):
            btn = QPushButton(diff)
            btn.setCheckable(True)
            btn.setObjectName("segPill")
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            if diff == self.current_difficulty:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, d=diff: self._on_difficulty_button_clicked(d))
            self.diff_buttons[diff] = btn
            self.diff_button_group.addButton(btn, i)
            diff_btn_layout.addWidget(btn)

        info_layout.addWidget(diff_segment)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        self._sep1 = sep
        sep.setStyleSheet(f"background-color: {t['sep_color']}; border: none;")
        info_layout.addWidget(sep)

        # Stats — section header (SVG icon + bold title)
        stats_header, stats_icon, stats_title = self._make_section_header('stats', '分析信息')
        info_layout.addLayout(stats_header)
        self._stats_icon = stats_icon
        self._stats_title_label = stats_title

        self.stats_label = QLabel("选择音频文件开始分析")
        self.stats_label.setWordWrap(True)
        self.stats_label.setMinimumWidth(320)
        self.stats_label.setObjectName("statValue")
        info_layout.addWidget(self.stats_label)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFixedHeight(1)
        self._sep2 = sep2
        sep2.setStyleSheet(f"background-color: {t['sep_color']}; border: none;")
        info_layout.addWidget(sep2)

        # Playback controls — section header (SVG icon + bold title)
        play_header, play_icon, play_title = self._make_section_header('playback', '播放控制')
        info_layout.addLayout(play_header)
        self._playback_icon = play_icon
        self._playback_title_label = play_title

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_play = self._make_icon_button('play', '播放', size=16)
        self.btn_play.setObjectName("btnPlay")
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(lambda checked=False, b=self.btn_play: self._animate_button_click(b))
        self.btn_play.clicked.connect(self.play_midi)
        btn_row.addWidget(self.btn_play)

        self.btn_stop = self._make_icon_button('stop', '停止', size=16)
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_midi)
        btn_row.addWidget(self.btn_stop)

        self.btn_export = self._make_icon_button('download', '导出', size=16)
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

        # Uniform velocity slider (only visible when uniform mode is selected).
        # Inline style override removed — the global QSlider style applies.
        self._uniform_vel_slider = QSlider(Qt.Horizontal)
        self._uniform_vel_slider.setRange(1, 127)
        self._uniform_vel_slider.setValue(100)
        self._uniform_vel_slider.setFixedWidth(80)
        self._uniform_vel_slider.setVisible(False)
        self._uniform_vel_slider.setToolTip("统一力度值")
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

        # Denoise section header (SVG icon + bold title). Keep
        # self._denoise_title pointing at the QLabel for backward compat
        # (_refresh_inline_styles references this attribute).
        denoise_header, denoise_icon, denoise_title = self._make_section_header('denoise', '降噪设置')
        info_layout.addLayout(denoise_header)
        self._denoise_icon = denoise_icon
        self._denoise_title = denoise_title

        # Mode toggle: Auto / Manual / Off — segmented control using
        # #segmentedControl + #segPill global styles. The QButtonGroup and
        # clicked-signal handlers are preserved so _on_denoise_mode_changed
        # continues to work unchanged.
        denoise_mode_segment = QFrame()
        denoise_mode_segment.setObjectName("segmentedControl")
        mode_layout = QHBoxLayout(denoise_mode_segment)
        mode_layout.setContentsMargins(4, 4, 4, 4)
        mode_layout.setSpacing(2)

        self.btn_denoise_auto = QPushButton("自动")
        self.btn_denoise_auto.setCheckable(True)
        self.btn_denoise_auto.setChecked(True)
        self.btn_denoise_auto.setObjectName("segPill")
        self.btn_denoise_manual = QPushButton("手动")
        self.btn_denoise_manual.setCheckable(True)
        self.btn_denoise_manual.setObjectName("segPill")
        self.btn_denoise_off = QPushButton("关闭")
        self.btn_denoise_off.setCheckable(True)
        self.btn_denoise_off.setObjectName("segPill")

        self._denoise_mode_group = QButtonGroup(self)
        self._denoise_mode_group.setExclusive(True)
        self._denoise_mode_group.addButton(self.btn_denoise_auto)
        self._denoise_mode_group.addButton(self.btn_denoise_manual)
        self._denoise_mode_group.addButton(self.btn_denoise_off)
        self.btn_denoise_auto.clicked.connect(lambda: self._on_denoise_mode_changed('auto'))
        self.btn_denoise_manual.clicked.connect(lambda: self._on_denoise_mode_changed('manual'))
        self.btn_denoise_off.clicked.connect(lambda: self._on_denoise_mode_changed('off'))
        mode_layout.addWidget(self.btn_denoise_auto)
        mode_layout.addWidget(self.btn_denoise_manual)
        mode_layout.addWidget(self.btn_denoise_off)
        info_layout.addWidget(denoise_mode_segment)

        # Denoise parameter sliders container.
        # Inline slider style override removed — the global QSlider style
        # (gradient sub-page + brand-color handle) applies.
        self._denoise_sliders_widget = QWidget()
        self._denoise_sliders_layout = QVBoxLayout(self._denoise_sliders_widget)
        self._denoise_sliders_layout.setContentsMargins(0, 8, 0, 0)
        self._denoise_sliders_layout.setSpacing(6)

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

        # ============================================================
        # 模型灵敏度设置区域（用户手动调节伴奏/人声模型灵敏度）
        # ============================================================
        sep_sens = QFrame()
        sep_sens.setFrameShape(QFrame.HLine)
        sep_sens.setStyleSheet(f"color: {t['divider']}; background: {t['divider']}; border: none; max-height: 1px;")
        sep_sens.setFixedHeight(1)
        info_layout.addWidget(sep_sens)

        # Section header
        sens_header, sens_icon, sens_title = self._make_section_header('sliders', '模型灵敏度')
        info_layout.addLayout(sens_header)
        self._sens_icon = sens_icon
        self._sens_title = sens_title

        # 滑块容器
        self._sens_sliders_widget = QWidget()
        self._sens_sliders_layout = QVBoxLayout(self._sens_sliders_widget)
        self._sens_sliders_layout.setContentsMargins(0, 8, 0, 0)
        self._sens_sliders_layout.setSpacing(6)

        # 1. 人声 onset 灵敏度（0.3-0.8，默认 0.5；越低越灵敏）
        vonset_layout = QHBoxLayout()
        vonset_layout.setSpacing(4)
        vonset_label = QLabel("人声 onset")
        self._vonset_label = vonset_label
        vonset_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 64px;")
        vonset_layout.addWidget(vonset_label)
        self.slider_vocal_onset = QSlider(Qt.Horizontal)
        self.slider_vocal_onset.setRange(30, 80)  # 0.30 - 0.80
        self.slider_vocal_onset.setValue(50)     # 默认 0.50
        vonset_layout.addWidget(self.slider_vocal_onset, 1)
        self.label_vocal_onset_val = QLabel("0.50")
        self.label_vocal_onset_val.setStyleSheet(f"font-size: 11px; color: {t['text_primary']}; border: none; min-width: 36px;")
        vonset_layout.addWidget(self.label_vocal_onset_val)
        self._sens_sliders_layout.addLayout(vonset_layout)
        vonset_hint = QLabel("越低越灵敏，识别更多音符（可能含噪）")
        self._vonset_hint = vonset_hint
        vonset_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 68px;")
        self._sens_sliders_layout.addWidget(vonset_hint)
        self.slider_vocal_onset.valueChanged.connect(
            lambda v: self.label_vocal_onset_val.setText(f"{v / 100:.2f}"))

        # 2. 人声 frame 阈值（0.1-0.6，默认 0.3；越低越灵敏）
        vframe_layout = QHBoxLayout()
        vframe_layout.setSpacing(4)
        vframe_label = QLabel("人声 frame")
        self._vframe_label = vframe_label
        vframe_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 64px;")
        vframe_layout.addWidget(vframe_label)
        self.slider_vocal_frame = QSlider(Qt.Horizontal)
        self.slider_vocal_frame.setRange(10, 60)  # 0.10 - 0.60
        self.slider_vocal_frame.setValue(30)      # 默认 0.30
        vframe_layout.addWidget(self.slider_vocal_frame, 1)
        self.label_vocal_frame_val = QLabel("0.30")
        self.label_vocal_frame_val.setStyleSheet(f"font-size: 11px; color: {t['text_primary']}; border: none; min-width: 36px;")
        vframe_layout.addWidget(self.label_vocal_frame_val)
        self._sens_sliders_layout.addLayout(vframe_layout)
        vframe_hint = QLabel("frame 阈值，越低识别音符越多")
        self._vframe_hint = vframe_hint
        vframe_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 68px;")
        self._sens_sliders_layout.addWidget(vframe_hint)
        self.slider_vocal_frame.valueChanged.connect(
            lambda v: self.label_vocal_frame_val.setText(f"{v / 100:.2f}"))

        # 3. 人声最短音符时长（40-200ms，默认 80ms）
        vlen_layout = QHBoxLayout()
        vlen_layout.setSpacing(4)
        vlen_label = QLabel("人声最短音符")
        self._vlen_label = vlen_label
        vlen_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 64px;")
        vlen_layout.addWidget(vlen_label)
        self.slider_vocal_minlen = QSlider(Qt.Horizontal)
        self.slider_vocal_minlen.setRange(40, 200)
        self.slider_vocal_minlen.setValue(80)
        vlen_layout.addWidget(self.slider_vocal_minlen, 1)
        self.label_vocal_minlen_val = QLabel("80ms")
        self.label_vocal_minlen_val.setStyleSheet(f"font-size: 11px; color: {t['text_primary']}; border: none; min-width: 36px;")
        vlen_layout.addWidget(self.label_vocal_minlen_val)
        self._sens_sliders_layout.addLayout(vlen_layout)
        vlen_hint = QLabel("短于此的音符将被丢弃（越短越灵敏）")
        self._vlen_hint = vlen_hint
        vlen_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 68px;")
        self._sens_sliders_layout.addWidget(vlen_hint)
        self.slider_vocal_minlen.valueChanged.connect(
            lambda v: self.label_vocal_minlen_val.setText(f"{v}ms"))

        # 4. 伴奏灵敏度（0-100，默认 50；越高越灵敏）
        asens_layout = QHBoxLayout()
        asens_layout.setSpacing(4)
        asens_label = QLabel("伴奏灵敏度")
        self._asens_label = asens_label
        asens_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 64px;")
        asens_layout.addWidget(asens_label)
        self.slider_accomp_sens = QSlider(Qt.Horizontal)
        self.slider_accomp_sens.setRange(0, 100)
        self.slider_accomp_sens.setValue(50)
        asens_layout.addWidget(self.slider_accomp_sens, 1)
        self.label_accomp_sens_val = QLabel("50")
        self.label_accomp_sens_val.setStyleSheet(f"font-size: 11px; color: {t['text_primary']}; border: none; min-width: 36px;")
        asens_layout.addWidget(self.label_accomp_sens_val)
        self._sens_sliders_layout.addLayout(asens_layout)
        asens_hint = QLabel("越高识别越多音符（减少漏识别，可能含噪）")
        self._asens_hint = asens_hint
        asens_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 68px;")
        self._sens_sliders_layout.addWidget(asens_hint)
        self.slider_accomp_sens.valueChanged.connect(
            lambda v: self.label_accomp_sens_val.setText(str(v)))

        # 5. 伴奏最短音符时长（40-300ms，默认 80ms；短于此的音符被丢弃）
        adur_layout = QHBoxLayout()
        adur_layout.setSpacing(4)
        adur_label = QLabel("伴奏最短音符")
        self._adur_label = adur_label
        adur_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 64px;")
        adur_layout.addWidget(adur_label)
        self.slider_accomp_min_dur = QSlider(Qt.Horizontal)
        self.slider_accomp_min_dur.setRange(40, 300)
        self.slider_accomp_min_dur.setValue(80)
        adur_layout.addWidget(self.slider_accomp_min_dur, 1)
        self.label_accomp_min_dur_val = QLabel("80ms")
        self.label_accomp_min_dur_val.setStyleSheet(f"font-size: 11px; color: {t['text_primary']}; border: none; min-width: 36px;")
        adur_layout.addWidget(self.label_accomp_min_dur_val)
        self._sens_sliders_layout.addLayout(adur_layout)
        adur_hint = QLabel("短于此的音符将被丢弃（越大越干净，但可能丢主音）")
        self._adur_hint = adur_hint
        adur_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 68px;")
        self._sens_sliders_layout.addWidget(adur_hint)
        self.slider_accomp_min_dur.valueChanged.connect(
            lambda v: self.label_accomp_min_dur_val.setText(f"{v}ms"))

        # 6. 伴奏最大和弦数（2-10，默认 6；控制同时发音数）
        apoly_layout = QHBoxLayout()
        apoly_layout.setSpacing(4)
        apoly_label = QLabel("伴奏最大和弦")
        self._apoly_label = apoly_label
        apoly_label.setStyleSheet(f"font-size: 11px; color: {t['text_secondary']}; border: none; min-width: 64px;")
        apoly_layout.addWidget(apoly_label)
        self.slider_accomp_max_poly = QSlider(Qt.Horizontal)
        self.slider_accomp_max_poly.setRange(2, 10)
        self.slider_accomp_max_poly.setValue(6)
        apoly_layout.addWidget(self.slider_accomp_max_poly, 1)
        self.label_accomp_max_poly_val = QLabel("6")
        self.label_accomp_max_poly_val.setStyleSheet(f"font-size: 11px; color: {t['text_primary']}; border: none; min-width: 36px;")
        apoly_layout.addWidget(self.label_accomp_max_poly_val)
        self._sens_sliders_layout.addLayout(apoly_layout)
        apoly_hint = QLabel("同时发声超过此数的和弦会被精简（越小越严格）")
        self._apoly_hint = apoly_hint
        apoly_hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none; margin-left: 68px;")
        self._sens_sliders_layout.addWidget(apoly_hint)
        self.slider_accomp_max_poly.valueChanged.connect(
            lambda v: self.label_accomp_max_poly_val.setText(str(v)))

        # 重置灵敏度按钮 + 应用灵敏度按钮
        sens_btn_layout = QHBoxLayout()
        sens_btn_layout.setSpacing(8)
        self.btn_reset_sensitivity = QPushButton("重置默认")
        self.btn_reset_sensitivity.setStyleSheet(f"""
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
        """)
        self.btn_reset_sensitivity.clicked.connect(self._reset_sensitivity)
        sens_btn_layout.addWidget(self.btn_reset_sensitivity)

        # 应用灵敏度按钮 — 用当前滑块值重新跑分析（删旧 MIDI 强制重转录）
        self.btn_apply_sensitivity = QPushButton("应用并重新分析")
        self.btn_apply_sensitivity.setObjectName("primary")
        self.btn_apply_sensitivity.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['brand_gradient']};
                color: white;
                border: none;
                border-radius: 16px;
                padding: 6px 18px;
                font-size: 12px;
                font-weight: bold;
                min-height: 18px;
            }}
            QPushButton:hover {{ background-color: {t['brand_gradient_hover']}; }}
            QPushButton:pressed {{ background-color: {t['brand_gradient_pressed']}; }}
            QPushButton:disabled {{ background-color: {t['surface_disabled']}; color: {t['label_disabled']}; border: 1px solid {t['border']}; }}
        """)
        self.btn_apply_sensitivity.clicked.connect(self._apply_sensitivity_reanalyze)
        sens_btn_layout.addWidget(self.btn_apply_sensitivity)
        sens_btn_layout.addStretch()
        self._sens_sliders_layout.addLayout(sens_btn_layout)

        info_layout.addWidget(self._sens_sliders_widget)

        # Load persisted sensitivity/denoise defaults into the sliders we just built.
        # (Settings dialog writes to settings.json; this applies them at startup.)
        self._load_settings_into_sliders()

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
        self.tempo_slider.valueChanged.connect(self._on_tempo_changed)
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

        self.btn_back_edit = QPushButton("返回")
        self.btn_back_edit.setFixedWidth(120)
        self.btn_back_edit.setStyleSheet(f"""
            QPushButton {{
                border-radius: 20px; padding: 6px 14px; font-size: 13px;
                background-color: {t['back_btn_bg']}; border: 1px solid {t['back_btn_border']};
                color: {t['back_btn_text']};
            }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
        """)
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name
            _t_name = get_current_theme_name()
            self.btn_back_edit.setIcon(_svg_icon('back', size=16, theme_name=_t_name))
            self.btn_back_edit.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.btn_back_edit.clicked.connect(lambda: self._go_back(0))
        top_bar.addWidget(self.btn_back_edit)

        # Page title with SVG music_note icon
        try:
            from app_icons import icon_pixmap as _icon_pixmap
            from design_tokens import qcolor as _qcolor, tokens as _tokens, get_current_theme_name as _gtn
            _theme = _gtn()
            _accent = _qcolor(getattr(_tokens(_theme).color, 'accent', t['accent']))
            title_icon = QLabel()
            title_icon.setStyleSheet("border: none; background: transparent;")
            title_icon.setPixmap(_icon_pixmap('music_note', size=16, color=_accent, theme_name=_theme))
            self._edit_title_icon = title_icon
            top_bar.addWidget(title_icon)
        except Exception:
            self._edit_title_icon = None

        edit_title = QLabel("编辑模式")
        self._edit_title = edit_title
        edit_title.setStyleSheet(
            f"font-size: 13px; color: {t['accent']}; font-weight: bold; border: none;")
        top_bar.addWidget(edit_title)

        # 缩放控件（- / 1.0x / +）— 置于顶栏
        top_bar.addSpacing(12)
        btn_edit_zout = QPushButton()
        btn_edit_zout.setFixedSize(26, 26)
        self._btn_edit_zout = btn_edit_zout
        btn_edit_zout.setStyleSheet(
            f"QPushButton {{ border-radius: 13px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 14px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        btn_edit_zout.clicked.connect(lambda: (self.edit_sheet_widget.zoom_out(),
                                               self._update_edit_zoom_label()))
        top_bar.addWidget(btn_edit_zout)

        self.edit_zoom_label = QLabel("1.0x")
        self.edit_zoom_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 10px; min-width: 32px; border: none;")
        top_bar.addWidget(self.edit_zoom_label)

        btn_edit_zin = QPushButton()
        btn_edit_zin.setFixedSize(26, 26)
        self._btn_edit_zin = btn_edit_zin
        btn_edit_zin.setStyleSheet(
            f"QPushButton {{ border-radius: 13px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 14px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        btn_edit_zin.clicked.connect(lambda: (self.edit_sheet_widget.zoom_in(),
                                               self._update_edit_zoom_label()))
        top_bar.addWidget(btn_edit_zin)

        # SVG icons for edit zoom buttons
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name
            _t_name = get_current_theme_name()
            btn_edit_zout.setIcon(_svg_icon('zoom_out', size=14, theme_name=_t_name))
            btn_edit_zout.setIconSize(QSize(14, 14))
            btn_edit_zin.setIcon(_svg_icon('zoom_in', size=14, theme_name=_t_name))
            btn_edit_zin.setIconSize(QSize(14, 14))
        except Exception:
            pass

        # 钢琴卷帘缩放（roll zoom）也放在顶栏
        top_bar.addSpacing(4)
        sep_roll = QFrame()
        sep_roll.setFrameShape(QFrame.VLine)
        sep_roll.setStyleSheet(f"color: {t['divider']}; border: none; background-color: {t['divider']}; max-width: 1px; margin: 4px 2px;")
        top_bar.addWidget(sep_roll)

        self.btn_roll_zout = QPushButton()
        self.btn_roll_zout.setFixedSize(28, 28)
        self.btn_roll_zout.setStyleSheet(
            f"QPushButton {{ border-radius: 14px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 14px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        self.btn_roll_zout.clicked.connect(lambda: self._edit_roll_zoom(-1))
        top_bar.addWidget(self.btn_roll_zout)

        self.edit_roll_zoom_label = QLabel("1.0x")
        self.edit_roll_zoom_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px; min-width: 36px; border: none;")
        top_bar.addWidget(self.edit_roll_zoom_label)

        self.btn_roll_zin = QPushButton()
        self.btn_roll_zin.setFixedSize(28, 28)
        self.btn_roll_zin.setStyleSheet(
            f"QPushButton {{ border-radius: 14px; background: {t['zoom_btn_bg']}; border: 1px solid {t['zoom_btn_border']};"
            f" font-size: 14px; font-weight: bold; color: {t['zoom_btn_text']}; }}"
            f"QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}")
        self.btn_roll_zin.clicked.connect(lambda: self._edit_roll_zoom(1))
        top_bar.addWidget(self.btn_roll_zin)

        try:
            self.btn_roll_zout.setIcon(_svg_icon('zoom_out', size=16, theme_name=_t_name))
            self.btn_roll_zout.setIconSize(QSize(16, 16))
            self.btn_roll_zin.setIcon(_svg_icon('zoom_in', size=16, theme_name=_t_name))
            self.btn_roll_zin.setIconSize(QSize(16, 16))
        except Exception:
            pass

        top_bar.addStretch()

        # 导入/导出 (SVG import/download icons, objectNames preserved for QSS)
        self.btn_import_mid = QPushButton("导入")
        self.btn_import_mid.setObjectName("primary")
        self.btn_import_mid.setFixedSize(80, 34)
        self.btn_import_mid.clicked.connect(self._import_midi_edit)
        top_bar.addWidget(self.btn_import_mid)

        self.btn_export_mid = QPushButton("导出")
        self.btn_export_mid.setObjectName("btnExport")
        self.btn_export_mid.setFixedSize(80, 34)
        self.btn_export_mid.setEnabled(False)
        self.btn_export_mid.clicked.connect(self._export_midi_edit)
        top_bar.addWidget(self.btn_export_mid)

        # 导出WAV / 导出PDF
        self.btn_export_wav = QPushButton("导出WAV")
        self.btn_export_wav.setObjectName("btnExport")
        self.btn_export_wav.setFixedSize(90, 34)
        self.btn_export_wav.setEnabled(False)
        self.btn_export_wav.clicked.connect(self._export_wav)
        top_bar.addWidget(self.btn_export_wav)

        self.btn_export_pdf = QPushButton("导出PDF")
        self.btn_export_pdf.setObjectName("btnExport")
        self.btn_export_pdf.setFixedSize(90, 34)
        self.btn_export_pdf.setEnabled(False)
        self.btn_export_pdf.clicked.connect(self._export_pdf)
        top_bar.addWidget(self.btn_export_pdf)

        # Apply SVG icons to import/export buttons (theme-aware)
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name
            _t_name = get_current_theme_name()
            self.btn_import_mid.setIcon(_svg_icon('import', size=14, theme_name=_t_name))
            self.btn_import_mid.setIconSize(QSize(14, 14))
            for _btn in [self.btn_export_mid, self.btn_export_wav, self.btn_export_pdf]:
                _btn.setIcon(_svg_icon('download', size=14, theme_name=_t_name))
                _btn.setIconSize(QSize(14, 14))
        except Exception:
            pass

        # 主题切换 (SVG sun/moon, with emoji fallback handled by _apply_theme)
        theme_btn_edit = QPushButton()
        theme_btn_edit.setObjectName('themeToggle')
        theme_btn_edit.setToolTip('切换深色/浅色主题')
        theme_btn_edit.setCursor(QCursor(Qt.PointingHandCursor))
        theme_btn_edit.clicked.connect(self._toggle_theme)
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name
            _t_name = get_current_theme_name()
            _icon_name = 'moon' if _t_name == 'light' else 'sun'
            theme_btn_edit.setIcon(_svg_icon(_icon_name, size=20, theme_name=_t_name))
            theme_btn_edit.setIconSize(QSize(20, 20))
        except Exception:
            pass
        top_bar.addWidget(theme_btn_edit)
        self._theme_btn_edit = theme_btn_edit

        page_layout.addLayout(top_bar)

        # ════════════════════════════════════════════════════
        #  工具栏（选择/铅笔/橡皮 + 撤销/重做 + 播放 + 提示）← 中层
        # ════════════════════════════════════════════════════
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        # 工具按钮组 (icon-only: cursor/pencil/eraser SVG icons)
        tool_group_style = f"""
            QPushButton {{
                border-radius: 12px; padding: 6px; font-size: 12px;
                background-color: {t['surface']}; border: 1px solid {t['border']};
                color: {t['text_secondary']}; min-width: 36px; min-height: 32px;
            }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
            QPushButton:checked {{
                background-color: {t['accent']}; color: white; border-color: {t['accent']};
            }}
        """

        self.btn_tool_select = QPushButton()
        self.btn_tool_select.setCheckable(True)
        self.btn_tool_select.setChecked(True)
        self.btn_tool_select.setStyleSheet(tool_group_style)
        self.btn_tool_select.setToolTip("选择工具 (V) — 框选/移动音符")
        toolbar.addWidget(self.btn_tool_select)

        self.btn_tool_pencil = QPushButton()
        self.btn_tool_pencil.setCheckable(True)
        self.btn_tool_pencil.setStyleSheet(tool_group_style)
        self.btn_tool_pencil.setToolTip("铅笔工具 (P) — 添加/移动/缩放音符")
        toolbar.addWidget(self.btn_tool_pencil)

        self.btn_tool_eraser = QPushButton()
        self.btn_tool_eraser.setCheckable(True)
        self.btn_tool_eraser.setStyleSheet(tool_group_style)
        self.btn_tool_eraser.setToolTip("橡皮工具 (E) — 点击删除音符")
        toolbar.addWidget(self.btn_tool_eraser)

        # Apply SVG icons to tool buttons (theme-aware)
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name
            _t_name = get_current_theme_name()
            for _btn, _icon_name in [
                (self.btn_tool_select, 'cursor'),
                (self.btn_tool_pencil, 'pencil'),
                (self.btn_tool_eraser, 'eraser'),
            ]:
                _btn.setIcon(_svg_icon(_icon_name, size=16, theme_name=_t_name))
                _btn.setIconSize(QSize(16, 16))
        except Exception:
            pass

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
                border-radius: 12px; padding: 6px 8px; font-size: 13px;
                background-color: {t['surface']}; border: 1px solid {t['border']};
                color: {t['text_secondary']}; min-width: 32px;
            }}
            QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
            QPushButton:disabled {{
                background-color: {t['surface_disabled']}; color: {t['label_disabled']};
                border-color: {t['divider']};
            }}
        """

        self.btn_undo_edit = QPushButton()
        self.btn_undo_edit.setToolTip("撤销 (Ctrl+Z)")
        self.btn_undo_edit.setEnabled(False)
        self.btn_undo_edit.setStyleSheet(undo_redo_style)
        self.btn_undo_edit.clicked.connect(self._undo_edit)
        toolbar.addWidget(self.btn_undo_edit)

        self.btn_redo_edit = QPushButton()
        self.btn_redo_edit.setToolTip("重做 (Ctrl+Y)")
        self.btn_redo_edit.setEnabled(False)
        self.btn_redo_edit.setStyleSheet(undo_redo_style)
        self.btn_redo_edit.clicked.connect(self._redo_edit)
        toolbar.addWidget(self.btn_redo_edit)

        # Apply SVG icons to undo/redo buttons (theme-aware)
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name
            _t_name = get_current_theme_name()
            self.btn_undo_edit.setIcon(_svg_icon('undo', size=16, theme_name=_t_name))
            self.btn_undo_edit.setIconSize(QSize(16, 16))
            self.btn_redo_edit.setIcon(_svg_icon('redo', size=16, theme_name=_t_name))
            self.btn_redo_edit.setIconSize(QSize(16, 16))
        except Exception:
            pass

        # 分隔线
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet(f"color: {t['divider']}; border: none; background-color: {t['divider']}; max-width: 1px; margin: 4px 4px;")
        toolbar.addWidget(sep2)

        # 播放/停止
        play_style = f"""
            QPushButton {{
                border-radius: 12px; padding: 6px 10px; font-size: 12px;
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
                border-radius: 12px; padding: 6px 10px; font-size: 12px;
                background-color: {t['danger']}; color: white; border: none;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {t['danger_hover']}; }}
            QPushButton:pressed {{ background-color: {t['danger_pressed']}; }}
            QPushButton:disabled {{
                background-color: {t['danger_disabled']}; color: white;
            }}
        """

        self.btn_edit_play = QPushButton("播放")
        self.btn_edit_play.setStyleSheet(play_style)
        self.btn_edit_play.setToolTip("播放试听 (Space)")
        self.btn_edit_play.setEnabled(False)
        self.btn_edit_play.clicked.connect(self._play_edit_audio)
        toolbar.addWidget(self.btn_edit_play)

        self.btn_edit_stop = QPushButton("停止")
        self.btn_edit_stop.setStyleSheet(stop_style)
        self.btn_edit_stop.setToolTip("停止播放")
        self.btn_edit_stop.setEnabled(False)
        self.btn_edit_stop.clicked.connect(self._stop_edit_audio)
        toolbar.addWidget(self.btn_edit_stop)

        # Apply SVG icons to play/stop buttons (theme-aware)
        try:
            from app_icons import icon as _svg_icon
            from design_tokens import get_current_theme_name
            _t_name = get_current_theme_name()
            self.btn_edit_play.setIcon(_svg_icon('play', size=16, theme_name=_t_name))
            self.btn_edit_play.setIconSize(QSize(16, 16))
            self.btn_edit_stop.setIcon(_svg_icon('stop', size=16, theme_name=_t_name))
            self.btn_edit_stop.setIconSize(QSize(16, 16))
        except Exception:
            pass

        # 分隔线
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.VLine)
        sep3.setStyleSheet(f"color: {t['divider']}; border: none; background-color: {t['divider']}; max-width: 1px; margin: 4px 4px;")
        toolbar.addWidget(sep3)

        toolbar.addStretch()

        # 小提示
        hint = QLabel("滚轮滚动 | Ctrl+滚轮缩放")
        hint.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none;")
        toolbar.addWidget(hint)

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
        # Slider styling provided by the global stylesheet — no inline override.
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

        hint_label = QLabel("Ctrl+滚轮缩放")
        hint_label.setStyleSheet(f"font-size: 10px; color: {t['hint_text']}; border: none;")
        sheet_toolbar.addWidget(hint_label)

        sheet_layout.addLayout(sheet_toolbar)

        self.edit_sheet_widget = SheetMusicWidget()
        self.edit_sheet_widget.rendering_done.connect(
            lambda: self._show_status("编辑乐谱渲染完成", 3000))
        self.edit_sheet_widget.rendering_progress.connect(self._on_render_progress)
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
        # 撤销/重做由 widget 内部栈管理，PianoApp 仅监听状态以更新按钮
        self.edit_piano_roll.notes_changed.connect(self._on_edit_notes_changed)
        self.edit_piano_roll.selection_changed.connect(self._on_edit_selection_changed)
        self.edit_piano_roll.note_hovered.connect(self._on_edit_note_hovered)
        self.edit_piano_roll.undo_redo_changed.connect(self._update_edit_undo_buttons)
        self.edit_piano_roll.play_pause_requested.connect(self._on_edit_play_pause)
        roll_layout.addWidget(self.edit_piano_roll, 1)
        # 音符属性编辑面板（选中单个音符时显示）
        roll_layout.addWidget(self.edit_piano_roll.create_property_panel())

        splitter.addWidget(roll_card)

        splitter.setSizes([350, 450])

        # Wrap the splitter in a QStackedWidget so an EmptyState placeholder
        # can be shown until a MIDI file is imported.
        self.edit_stack = QStackedWidget()
        try:
            from empty_state import EmptyState
            self.edit_empty = EmptyState(
                illustration='midi_import',
                title='等待导入',
                subtitle='点击导入 MIDI 文件开始编辑',
                cta_text='导入 MIDI',
                on_cta=self._import_midi_edit,
                parent=page,
            )
        except Exception:
            self.edit_empty = None
        if self.edit_empty is not None:
            self.edit_stack.addWidget(self.edit_empty)
        self.edit_stack.addWidget(splitter)
        # Show the empty state by default; switches to the splitter once a
        # MIDI file is loaded (see _show_edit_content).
        if self.edit_empty is not None:
            self.edit_stack.setCurrentWidget(self.edit_empty)
        page_layout.addWidget(self.edit_stack, 1)

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
        self.edit_piano_roll._save_undo_state()
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

    def _play_edit_audio(self):
        """播放编辑页面的音频（使用 Windows MCI MIDI 合成器）。"""
        roll = self.edit_piano_roll
        if not roll.display_notes:
            return

        notes = list(roll.display_notes)

        try:
            import ctypes

            # Close any existing MCI device
            ctypes.windll.winmm.mciSendStringW('close editplayback', None, 0, None)

            # Create MIDI from notes
            midi = pretty_midi.PrettyMIDI()
            inst = pretty_midi.Instrument(program=0)
            for n in notes:
                inst.notes.append(pretty_midi.Note(
                    velocity=int(n['velocity']), pitch=int(n['pitch']),
                    start=float(n['start']), end=float(n['end'])
                ))
            midi.instruments.append(inst)

            # Write to temp MIDI file
            tmp_mid = os.path.join(tempfile.gettempdir(), f'_edit_playback_{os.getpid()}.mid')
            midi.write(tmp_mid)
            self._edit_playback_mid = tmp_mid

            # Open and play through MCI
            r = ctypes.windll.winmm.mciSendStringW(
                f'open "{tmp_mid}" type sequencer alias editplayback', None, 0, None)
            if r != 0:
                raise RuntimeError(f'MCI open failed, code={r}')
            ctypes.windll.winmm.mciSendStringW('play editplayback', None, 0, None)

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

        # Stop MCI playback
        try:
            import ctypes
            ctypes.windll.winmm.mciSendStringW('stop editplayback', None, 0, None)
            ctypes.windll.winmm.mciSendStringW('close editplayback', None, 0, None)
        except Exception:
            pass

        # 清理临时 MIDI 文件
        tmp_mid = getattr(self, '_edit_playback_mid', None)
        if tmp_mid:
            try:
                os.remove(tmp_mid)
            except Exception:
                pass
            self._edit_playback_mid = None

        if hasattr(self, '_edit_play_timer') and self._edit_play_timer:
            self._edit_play_timer.stop()

        self.btn_edit_play.setEnabled(len(self.edit_piano_roll.display_notes) > 0)
        self.btn_edit_stop.setEnabled(False)
        self._show_status("已停止")

    def _check_edit_playback(self):
        """检查编辑播放是否结束。"""
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(128)
            ctypes.windll.winmm.mciSendStringW(
                'status editplayback mode', buf, 128, None)
            if 'playing' not in buf.value:
                self._stop_edit_audio()
        except Exception:
            self._stop_edit_audio()

    def _on_edit_notes_changed(self):
        """音符修改后回调：更新UI状态和重新渲染五线谱。"""
        self._update_edit_undo_buttons()
        self._edit_render_timer.start()
        # 更新音符计数和播放按钮
        count = len(self.edit_piano_roll.display_notes)
        self._edit_count_label.setText(f"音符: {count}")
        self.btn_edit_play.setEnabled(count > 0)
        self.btn_export_mid.setEnabled(count > 0)

    def _update_edit_undo_buttons(self):
        """根据 widget 撤销/重做栈状态更新按钮。"""
        self.btn_undo_edit.setEnabled(self.edit_piano_roll.can_undo)
        self.btn_redo_edit.setEnabled(self.edit_piano_roll.can_redo)

    def _on_edit_play_pause(self):
        """播放/暂停请求槽（由 widget 的 Space 快捷键触发）。"""
        if self.btn_edit_stop.isEnabled():
            self._stop_edit_audio()
        elif self.btn_edit_play.isEnabled():
            self._play_edit_audio()

    def _pre_edit_save(self):
        """编辑前保存状态（已由 widget 内部栈接管，保留为空实现以兼容旧连接）。"""
        pass

    def _undo_edit(self):
        """撤销（委托给 widget 内部撤销栈）。"""
        self.edit_piano_roll.undo()

    def _redo_edit(self):
        """重做（委托给 widget 内部重做栈）。"""
        self.edit_piano_roll.redo()

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
                if hasattr(self, 'btn_export_wav'):
                    self.btn_export_wav.setEnabled(True)
                if hasattr(self, 'btn_export_pdf'):
                    self.btn_export_pdf.setEnabled(True)
                self._refresh_edit_sheet_music()
                # Switch from the empty-state placeholder to the actual edit view.
                self._show_edit_content(show_actual=True)
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

        # === 文件菜单 ===
        file_menu = menubar.addMenu("文件")
        file_menu.addAction("打开音频", self.select_audio, "Ctrl+O")
        file_menu.addAction("导入MIDI", self._import_midi_edit)
        file_menu.addAction("导出MIDI", self.export_midi, "Ctrl+E")
        file_menu.addAction("导出PDF", self._export_pdf)
        file_menu.addAction("导出WAV", self._export_wav)
        file_menu.addSeparator()
        file_menu.addAction("返回主页", lambda: self._go_back(0))
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close, "Ctrl+Q")

        # === 编辑菜单 ===
        edit_menu = menubar.addMenu("编辑")
        edit_menu.addAction("撤销", self._undo_edit, "Ctrl+Z")
        edit_menu.addAction("重做", self._redo_edit, "Ctrl+Y")
        edit_menu.addSeparator()
        edit_menu.addAction("复制",
                            lambda: self.edit_piano_roll._copy_selected()
                            if hasattr(self, 'edit_piano_roll') else None, "Ctrl+C")
        edit_menu.addAction("粘贴",
                            lambda: self.edit_piano_roll._paste_clipboard()
                            if hasattr(self, 'edit_piano_roll') else None, "Ctrl+V")
        edit_menu.addAction("全选",
                            lambda: self.edit_piano_roll._select_all()
                            if hasattr(self, 'edit_piano_roll') else None, "Ctrl+A")

        # === 视图菜单 ===
        view_menu = menubar.addMenu("视图")
        view_menu.addAction("切换主题", self._toggle_theme, "Ctrl+T")
        view_menu.addAction("放大", self._zoom_in_current, "Ctrl++")
        view_menu.addAction("缩小", self._zoom_out_current, "Ctrl+-")
        view_menu.addAction("重置缩放", self._zoom_reset_current, "Ctrl+0")

        # === 帮助菜单 ===
        help_menu = menubar.addMenu("帮助")
        help_menu.addAction("关于", self.show_about)

    def _zoom_in_current(self):
        """Zoom in on the active page's sheet widget."""
        if self.stacked_widget.currentIndex() == 2 and hasattr(self, 'edit_sheet_widget'):
            self.edit_sheet_widget.zoom_in()
        elif hasattr(self, 'sheet_widget'):
            self.sheet_widget.zoom_in()
        if hasattr(self, '_update_zoom_label'):
            self._update_zoom_label()

    def _zoom_out_current(self):
        """Zoom out on the active page's sheet widget."""
        if self.stacked_widget.currentIndex() == 2 and hasattr(self, 'edit_sheet_widget'):
            self.edit_sheet_widget.zoom_out()
        elif hasattr(self, 'sheet_widget'):
            self.sheet_widget.zoom_out()
        if hasattr(self, '_update_zoom_label'):
            self._update_zoom_label()

    def _zoom_reset_current(self):
        """Reset zoom on the active page's sheet widget."""
        if self.stacked_widget.currentIndex() == 2 and hasattr(self, 'edit_sheet_widget'):
            self.edit_sheet_widget.zoom = 1.0
            self.edit_sheet_widget.update()
        elif hasattr(self, 'sheet_widget'):
            self.sheet_widget.zoom = 1.0
            self.sheet_widget.update()
        if hasattr(self, '_update_zoom_label'):
            self._update_zoom_label()

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
            _safe_update(self.piano_roll)

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
        """Switch between auto, manual, and off denoise mode."""
        self.denoise_mode = mode
        manual_enabled = (mode == 'manual')
        sliders_enabled = manual_enabled and (self.midi_path is not None)
        has_midi = self.midi_path is not None
        self.slider_threshold.setEnabled(sliders_enabled)
        self.slider_min_duration.setEnabled(sliders_enabled)
        self.slider_chord_strictness.setEnabled(sliders_enabled)
        self.slider_max_jump.setEnabled(sliders_enabled)
        self.slider_max_polyphony.setEnabled(sliders_enabled)
        self.btn_reset_denoise.setEnabled(sliders_enabled)
        # Update label colors using theme
        t = get_theme()
        label_color = t['text_primary'] if manual_enabled else t['label_disabled']
        for lbl in [self.label_threshold_val, self.label_min_duration_val,
                     self.label_chord_val, self.label_max_poly_val]:
            lbl.setStyleSheet(f"font-size: 11px; color: {label_color}; border: none; min-width: 32px;")
        self.label_max_jump_val.setStyleSheet(f"font-size: 11px; color: {label_color}; border: none; min-width: 38px;")
        # Apply button is enabled only when we have a midi_path and manual mode
        self.btn_apply_denoise.setEnabled(sliders_enabled)
        # Hide/show sliders panel when off
        if hasattr(self, '_denoise_sliders_widget'):
            self._denoise_sliders_widget.setVisible(mode != 'off')
        # 切换到"关闭"模式时，若已有 MIDI，自动重新生成未降噪版本
        # (off 模式下"应用"按钮被禁用，必须自动触发，否则之前的降噪结果不会清除)
        if mode == 'off' and has_midi:
            self._apply_denoise()

    def _reset_denoise(self):
        """Reset all denoise sliders to default values."""
        self.slider_threshold.setValue(25)
        self.slider_min_duration.setValue(80)
        self.slider_chord_strictness.setValue(25)
        self.slider_max_jump.setValue(12)
        self.slider_max_polyphony.setValue(6)

    def _reset_sensitivity(self):
        """重置模型灵敏度滑块到默认值。"""
        self.slider_vocal_onset.setValue(50)     # 0.50
        self.slider_vocal_frame.setValue(30)     # 0.30
        self.slider_vocal_minlen.setValue(80)    # 80ms
        self.slider_accomp_sens.setValue(50)     # 50
        self.slider_accomp_min_dur.setValue(80)  # 80ms
        self.slider_accomp_max_poly.setValue(6)  # 6 voices

    def _load_settings_into_sliders(self):
        """启动时从持久化 settings 加载灵敏度/降噪滑块的值。

        让设置页里改的"启动默认值"在分析页生效。失败时回退到代码默认值。
        """
        try:
            import app_settings
            s = app_settings.get_sensitivity_defaults()
            self.slider_vocal_onset.setValue(int(s.get('vocal_onset', 50)))
            self.slider_vocal_frame.setValue(int(s.get('vocal_frame', 30)))
            self.slider_vocal_minlen.setValue(int(s.get('vocal_minlen', 80)))
            self.slider_accomp_sens.setValue(int(s.get('accomp_sens', 50)))
            self.slider_accomp_min_dur.setValue(int(s.get('accomp_min_dur', 80)))
            self.slider_accomp_max_poly.setValue(int(s.get('accomp_max_poly', 6)))
            self.logger.info('[Settings] 灵敏度滑块已从持久化设置加载')
        except Exception as e:
            self.logger.debug(f'[Settings] 加载灵敏度默认值失败（用代码默认）: {e}')

    def _collect_sensitivity(self):
        """从滑块收集当前模型灵敏度参数。

        Returns:
            dict: {
                'vocal_onset_threshold': float,
                'vocal_frame_threshold': float,
                'vocal_min_note_length': int,
                'accomp_sensitivity': int,
            }
        """
        return {
            'vocal_onset_threshold': self.slider_vocal_onset.value() / 100.0,
            'vocal_frame_threshold': self.slider_vocal_frame.value() / 100.0,
            'vocal_min_note_length': self.slider_vocal_minlen.value(),
            'accomp_sensitivity': self.slider_accomp_sens.value(),
            'accomp_min_duration_ms': self.slider_accomp_min_dur.value(),
            'accomp_max_polyphony': self.slider_accomp_max_poly.value(),
        }

    def _show_separation_mode_popup(self):
        """弹出分离模式选择对话框（右上角 info 按钮触发）。

        提供两种模式：
          - 标准：音频分离成人声+伴奏（2-stem），速度快
          - 细化：音频分离成 4 个音轨（vocals/drums/bass/other），4 轨全部转录
        """
        t = get_theme()

        dlg = QDialog(self)
        dlg.setWindowTitle('分离模式')
        dlg.setFixedSize(420, 380)
        dlg.setStyleSheet(f"""
            QDialog {{ background-color: {t['bg']}; }}
            QLabel {{ color: {t['text_primary']}; border: none; }}
            QLabel#desc {{ color: {t['text_secondary']}; font-size: 12px; }}
            QLabel#title {{ font-size: 16px; font-weight: bold; }}
            QLabel#modeTitle {{ font-size: 14px; font-weight: bold; color: {t['text_primary']}; }}
            QLabel#modeDesc {{ font-size: 11px; color: {t['text_secondary']}; }}
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # 标题
        title = QLabel('分离模式')
        title.setObjectName('title')
        layout.addWidget(title)

        desc = QLabel('选择音频分离方式。细化模式会用 4-stem 模型把伴奏拆成鼓/贝斯/旋律，每轨单独转录。')
        desc.setObjectName('desc')
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 模式1：标准
        mode1_border = t['accent'] if self.separation_mode == 'standard' else t['card_border']
        mode1_widget = QFrame()
        mode1_widget.setStyleSheet(f"""
            QFrame {{ background-color: {t['card_bg']}; border-radius: 12px;
                      border: 2px solid {mode1_border}; }}
        """)
        mode1_layout = QVBoxLayout(mode1_widget)
        mode1_layout.setContentsMargins(16, 12, 16, 12)
        mode1_layout.setSpacing(4)
        mode1_header = QHBoxLayout()
        self._radio_standard = QRadioButton('标准模式（人声 + 伴奏）')
        self._radio_standard.setChecked(self.separation_mode == 'standard')
        mode1_header.addWidget(self._radio_standard)
        mode1_header.addStretch()
        mode1_tag = QLabel('2 音轨 · 速度快')
        mode1_tag.setObjectName('modeDesc')
        mode1_header.addWidget(mode1_tag)
        mode1_layout.addLayout(mode1_header)
        mode1_detail = QLabel('Mel-Band RoFormer 分离为人声 + 伴奏，分别用 Basic Pitch / Transkun 转录。')
        mode1_detail.setObjectName('modeDesc')
        mode1_detail.setWordWrap(True)
        mode1_layout.addWidget(mode1_detail)
        layout.addWidget(mode1_widget)

        # 模式2：细化
        mode2_widget = QFrame()
        mode2_widget.setStyleSheet(f"""
            QFrame {{ background-color: {t['card_bg']}; border-radius: 12px;
                      border: 2px solid {t['accent'] if self.separation_mode == 'stems' else t['card_border']}; }}
        """)
        mode2_layout = QVBoxLayout(mode2_widget)
        mode2_layout.setContentsMargins(16, 12, 16, 12)
        mode2_layout.setSpacing(4)
        mode2_header = QHBoxLayout()
        self._radio_stems = QRadioButton('细化模式（人声 + 鼓 + 贝斯 + 旋律）')
        self._radio_stems.setChecked(self.separation_mode == 'stems')
        mode2_header.addWidget(self._radio_stems)
        mode2_header.addStretch()
        mode2_tag = QLabel('4 音轨 · 全部转录')
        mode2_tag.setObjectName('modeDesc')
        mode2_header.addWidget(mode2_tag)
        mode2_layout.addLayout(mode2_header)
        mode2_detail = QLabel('4-stem 模型一次分离 vocals/drums/bass/other，4 轨全部转录成 MIDI 并合并为多轨乐谱。')
        mode2_detail.setObjectName('modeDesc')
        mode2_detail.setWordWrap(True)
        mode2_layout.addWidget(mode2_detail)
        layout.addWidget(mode2_widget)

        # 互斥
        radio_group = QButtonGroup(dlg)
        radio_group.addButton(self._radio_standard)
        radio_group.addButton(self._radio_stems)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton('确定')
        ok_btn.setFixedSize(80, 36)
        ok_btn.setStyleSheet(f"""
            QPushButton {{
                border-radius: 18px; font-size: 14px; font-weight: bold;
                background-color: {t['accent']}; color: white; border: none;
            }}
            QPushButton:hover {{ background-color: {t['accent_hover']}; }}
        """)
        ok_btn.clicked.connect(dlg.accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        if dlg.exec() == QDialog.Accepted:
            new_mode = 'stems' if self._radio_stems.isChecked() else 'standard'
            self._set_separation_mode(new_mode)

    def _set_separation_mode(self, mode):
        """设置分离模式并更新 UI 指示。"""
        self.separation_mode = mode
        if mode == 'stems':
            self.mode_indicator.setText("细化模式")
            self.mode_indicator.setToolTip('4 音轨分离：vocals/drums/bass/other 全部转录')
        else:
            self.mode_indicator.setText("标准模式")
            self.mode_indicator.setToolTip('2 音轨分离：人声 + 伴奏')
        self.logger.info(f"[PianoApp] 分离模式切换: {mode}")

    # ================================================================
    # 硬件检测 + GPU/模型选择对话框
    # ================================================================
    def _detect_hardware(self):
        """检测硬件信息：GPU、CPU、内存。

        区分两个概念：
          - has_nvidia_gpu: 物理上是否有 NVIDIA 显卡（用 nvidia-smi 检测，不依赖 torch）
          - has_cuda: torch 是否已启用 CUDA（需要安装 CUDA 版 torch）

        Returns:
            dict: {
                'has_nvidia_gpu': bool, 'has_cuda': bool,
                'gpu_name': str, 'gpu_vram_gb': float,
                'cpu_name': str, 'cpu_cores': int, 'ram_gb': float,
            }
        """
        import platform
        import subprocess
        info = {
            'has_nvidia_gpu': False, 'has_cuda': False,
            'gpu_name': '', 'gpu_vram_gb': 0.0,
            'cpu_name': platform.processor() or '未知',
            'cpu_cores': os.cpu_count() or 4,
            'ram_gb': 0.0,
        }

        # 1. 用 nvidia-smi 检测 NVIDIA 显卡（不依赖 torch）
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                line = result.stdout.strip().split('\n')[0]
                parts = [p.strip() for p in line.split(',')]
                info['has_nvidia_gpu'] = True
                info['gpu_name'] = parts[0] if parts else 'NVIDIA GPU'
                if len(parts) > 1:
                    try:
                        info['gpu_vram_gb'] = round(float(parts[1]) / 1024, 1)
                    except (ValueError, IndexError):
                        pass
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

        # 2. 检测 torch 是否已启用 CUDA
        try:
            import torch
            if torch.cuda.is_available():
                info['has_cuda'] = True
                if not info['gpu_name']:
                    info['gpu_name'] = torch.cuda.get_device_name(0)
                    props = torch.cuda.get_device_properties(0)
                    info['gpu_vram_gb'] = round(props.total_memory / 1024**3, 1)
        except Exception:
            pass

        # 3. 内存
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            info['ram_gb'] = round(stat.ullTotalPhys / 1024**3, 1)
        except Exception:
            pass
        return info

    def _estimate_separation_time(self, audio_duration_sec, model_name, has_cuda):
        """估算分离耗时（秒）。

        粗略估算（基于实测经验）：
          - big_beta7 CPU: ~5x 实时
          - big_beta7 GPU: ~0.3x 实时
          - bs_roformer CPU: ~3x 实时
          - scnet CPU: ~1.5x 实时
          - mel_band_roformer_4stems CPU: ~6x 实时
        """
        rates = {
            'big_beta7': 5.0 if not has_cuda else 0.3,
            'bs_roformer_voc_hyperacev2': 3.0 if not has_cuda else 0.25,
            'scnet_checkpoint_musdb18': 1.5 if not has_cuda else 0.15,
            'mel_band_roformer_4stems_large_ver1': 6.0 if not has_cuda else 0.4,
        }
        rate = rates.get(model_name, 4.0)
        return audio_duration_sec * rate

    def _format_time(self, seconds):
        """把秒数格式化为可读时间。"""
        if seconds < 60:
            return f"{int(seconds)} 秒"
        elif seconds < 3600:
            return f"{int(seconds / 60)} 分 {int(seconds % 60)} 秒"
        else:
            h = int(seconds / 3600)
            m = int((seconds % 3600) / 60)
            return f"{h} 时 {m} 分"

    def _create_cuda_terminal(self):
        """创建一个终端式 pip 管理控件，返回 (widget, append_fn, run_pip_fn)。"""
        import threading, subprocess

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        # 终端输出区
        term_frame = QFrame()
        term_frame.setStyleSheet(
            "background-color: #0d1117; border: 1px solid #30363d;"
            "border-radius: 8px;")
        term_fl = QVBoxLayout(term_frame)
        term_fl.setContentsMargins(6, 6, 6, 6)

        term_output = QTextEdit()
        term_output.setReadOnly(True)
        term_output.setFont(QFont("Consolas", 11))
        term_output.setStyleSheet(
            "background-color: #0d1117; color: #c9d1d9; border: none;"
            "selection-background-color: #264f78;")
        term_output.setMinimumHeight(160)
        term_output.setPlaceholderText(
            "点击下方按钮执行操作，输出将显示在这里...")
        term_fl.addWidget(term_output)
        container_layout.addWidget(term_frame)

        def _append_term(text, color='#c9d1d9'):
            term_output.append(f'<span style="color:{color};">{text}</span>')
            sb = term_output.verticalScrollBar()
            sb.setValue(sb.maximum())

        def _run_pip(cmd_parts, on_finish=None):
            _append_term(f'$ {" ".join(cmd_parts)}', '#58a6ff')

            def _worker():
                proc = None
                try:
                    proc = subprocess.Popen(
                        cmd_parts,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True, encoding='utf-8',
                        errors='replace',
                        creationflags=(subprocess.CREATE_NO_WINDOW
                                       if hasattr(subprocess, 'CREATE_NO_WINDOW')
                                       else 0))
                    for line in proc.stdout:
                        line = line.rstrip('\n\r')
                        if line.strip():
                            QTimer.singleShot(
                                0, lambda l=line: _append_term(l, '#8b949e'))
                    proc.wait(timeout=600)
                    rc = proc.returncode
                    if rc == 0:
                        QTimer.singleShot(
                            0, lambda: _append_term('✓ 命令执行成功', '#3fb950'))
                    else:
                        QTimer.singleShot(
                            0, lambda: _append_term(
                                f'✗ 命令退出码: {rc}', '#f85149'))
                except Exception as e:
                    QTimer.singleShot(
                        0, lambda: _append_term(f'✗ 错误: {e}', '#f85149'))
                finally:
                    if proc:
                        try:
                            proc.stdout.close()
                        except Exception:
                            pass
                    if on_finish:
                        QTimer.singleShot(0, on_finish)

            threading.Thread(target=_worker, daemon=True).start()

        def _make_small_btn(text, color=''):
            btn = QPushButton(text)
            btn.setStyleSheet(f"""
                QPushButton {{ padding: 5px 10px; font-size: 11px;
                    font-weight: bold; border-radius: 4px;
                    background-color: #21262d; color: #c9d1d9;
                    border: 1px solid #30363d; }}
                QPushButton:hover {{
                    background-color: #30363d; border-color: #58a6ff; }}
                {color}
            """)
            return btn

        # 按钮行: 检测 + 卸载
        btn_top = QHBoxLayout()
        btn_top.setSpacing(8)

        detect_btn = _make_small_btn('检测环境')
        detect_btn.clicked.connect(lambda: (
            _append_term('--- 环境检测 ---', '#d2a8ff'),
            _run_pip([sys.executable, '-m', 'pip', '--version']),
            _run_pip([sys.executable, '-c',
                      'try:\n'
                      ' import torch\n'
                      ' print(f"torch {torch.__version__}")\n'
                      ' print(f"CUDA 可用: {torch.cuda.is_available()}")\n'
                      ' print(f"CUDA 版本: {torch.version.cuda}")\n'
                      'except ImportError:\n'
                      ' print("torch 未安装")']),
        ))
        btn_top.addWidget(detect_btn)

        uninstall_btn = _make_small_btn('卸载 CUDA torch',
                                         'QPushButton { color: #f85149; }')
        uninstall_btn.clicked.connect(lambda: (
            _append_term('--- 准备卸载现有 torch ---', '#d2a8ff'),
            _run_pip([sys.executable, '-m', 'pip', 'uninstall',
                      'torch', 'torchaudio', '-y']),
        ))
        btn_top.addWidget(uninstall_btn)
        btn_top.addStretch()
        container_layout.addLayout(btn_top)

        # 安装按钮行
        install_row = QHBoxLayout()
        install_row.setSpacing(8)
        install_row.addWidget(self._mklabel('安装:', 'desc'))

        for cu_ver, cu_label in [('cu126', 'CUDA 12.6'),
                                  ('cu124', 'CUDA 12.4'),
                                  ('cu121', 'CUDA 12.1')]:
            inst_btn = _make_small_btn(cu_label)
            inst_btn.clicked.connect(
                lambda _, cv=cu_ver: (
                    _append_term(f'--- 安装 torch ({cv}) ---', '#d2a8ff'),
                    _run_pip([sys.executable, '-m', 'pip', 'install',
                              'torch', 'torchaudio', '--index-url',
                              f'https://download.pytorch.org/whl/{cv}']),
                ))
            install_row.addWidget(inst_btn)

        install_row.addStretch()
        container_layout.addLayout(install_row)

        # 复制命令: 添加说明标签
        copy_label = QLabel('复制终端命令（在系统终端中执行安装 CUDA torch）：')
        copy_label.setStyleSheet("color: #8b949e; font-size: 11px; padding-top: 6px;")
        container_layout.addWidget(copy_label)

        copy_row = QHBoxLayout()
        copy_row.setSpacing(8)
        cuda_cmd = ("pip install torch torchaudio --index-url "
                    "https://download.pytorch.org/whl/cu126")
        cmd_edit = QLineEdit(cuda_cmd)
        cmd_edit.setReadOnly(True)
        cmd_edit.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
            "background: #161b22; color: #c9d1d9; border: 1px solid #30363d;"
            "padding: 4px 8px; border-radius: 4px;")
        cmd_edit.setCursorPosition(0)
        copy_row.addWidget(cmd_edit, 1)
        copy_btn = QPushButton('复制到剪贴板')
        copy_btn.setStyleSheet(
            "padding: 4px 12px; font-size: 11px; font-weight: bold;")
        copy_btn.clicked.connect(
            lambda: (QApplication.clipboard().setText(cuda_cmd),
                     _append_term('已复制到剪贴板', '#3fb950')))
        copy_row.addWidget(copy_btn)
        container_layout.addLayout(copy_row)

        # 删除AI模型缓存
        del_label = QLabel('删除已下载的 AI 模型缓存（释放磁盘空间，下次需要重新下载）：')
        del_label.setStyleSheet("color: #8b949e; font-size: 11px; padding-top: 10px;")
        container_layout.addWidget(del_label)

        del_model_row = QHBoxLayout()
        del_model_row.setSpacing(8)
        del_models_btn = _make_small_btn('删除模型缓存',
                                          'QPushButton { color: #f85149; }')
        def _delete_models():
            _append_term('--- 正在删除 AI 模型缓存 ---', '#d2a8ff')
            cache_dirs = []
            try:
                import torch
                hub_dir = os.path.join(torch.hub.get_dir(), 'checkpoints')
                if os.path.exists(hub_dir):
                    cache_dirs.append(hub_dir)
            except Exception:
                pass
            # pymss / asteroid model cache
            import pathlib
            home = pathlib.Path.home()
            for sub in ['.cache/torch/hub/checkpoints',
                         '.cache/pymss',
                         '.cache/asteroid']:
                p = home / sub
                if p.exists():
                    cache_dirs.append(str(p))
            if not cache_dirs:
                _append_term('未找到模型缓存目录', '#8b949e')
                return
            for d in cache_dirs:
                try:
                    import shutil
                    shutil.rmtree(d)
                    _append_term(f'✓ 已删除: {d}', '#3fb950')
                except Exception as e:
                    _append_term(f'✗ 删除失败 {d}: {e}', '#f85149')
            _append_term('--- 模型缓存清理完成 ---', '#d2a8ff')
        del_models_btn.clicked.connect(_delete_models)
        del_model_row.addWidget(del_models_btn)
        del_model_row.addStretch()
        container_layout.addLayout(del_model_row)

        return container, _append_term, _run_pip

    def _show_gpu_model_dialog(self):
        """显示 GPU/模型选择对话框（含终端式 pip 管理）。

        - 有 GPU + CUDA 已启用：显示正常状态 + 折叠式高级终端
        - 有 GPU 但 CUDA 未启用：终端式管理（检测/安装/卸载）
        - 无 GPU：CPU 估算 + 推荐快模型
        """
        import subprocess

        t = get_theme()
        hw = self._detect_hardware()
        current_model = 'big_beta7'

        audio_dur = 0
        if hasattr(self, 'audio_path') and self.audio_path:
            try:
                result = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'csv=p=0', self.audio_path],
                    capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    audio_dur = float(result.stdout.strip())
            except Exception:
                pass

        dlg = QDialog(self)
        dlg.setWindowTitle('性能与模型')
        dlg.setMinimumSize(560, 620)
        dlg.setStyleSheet(f"""
            QDialog {{ background-color: {t['bg']}; }}
            QLabel {{ color: {t['text_primary']}; border: none; }}
            QLabel#title {{ font-size: 18px; font-weight: bold; }}
            QLabel#section {{ font-size: 14px; font-weight: bold; color: {t['accent']}; }}
            QLabel#desc {{ color: {t['text_secondary']}; font-size: 12px; }}
            QLabel#info {{ color: {t['text_primary']}; font-size: 13px; }}
            QLabel#warning {{ color: #FF6B6B; font-size: 12px; }}
            QLabel#time {{ color: {t['accent']}; font-size: 13px; font-weight: bold; }}
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        layout.addWidget(self._mklabel('性能与模型设置', 'title'))

        # === 硬件信息 ===
        layout.addWidget(self._mklabel('硬件检测', 'section'))
        hw_text = f"CPU: {hw['cpu_name']}\n核心数: {hw['cpu_cores']}  |  内存: {hw['ram_gb']} GB"
        if hw['has_nvidia_gpu']:
            hw_text += f"\nGPU: {hw['gpu_name']}  (VRAM: {hw['gpu_vram_gb']} GB)"
            if hw['has_cuda']:
                hw_text += "  [CUDA 已启用]"
            else:
                hw_text += "  [CUDA 未启用 — 当前用 CPU]"
        else:
            hw_text += "\nGPU: 未检测到 NVIDIA 显卡"
        layout.addWidget(self._mklabel(hw_text, 'info'))

        # ========== 分支 1: CUDA 已启用 ==========
        if hw['has_cuda']:
            layout.addWidget(self._mklabel('✓ CUDA 加速已启用，分离速度正常', 'time'))

            # 折叠式高级终端管理
            adv_toggle = QPushButton('+ 高级：管理 CUDA torch')
            adv_toggle.setStyleSheet(f"""
                QPushButton {{ border: none; background: transparent;
                    color: {t['text_secondary']}; font-size: 12px;
                    text-align: left; padding: 4px 0; }}
                QPushButton:hover {{ color: {t['accent']}; }}
            """)
            adv_toggle.setCursor(Qt.PointingHandCursor)
            layout.addWidget(adv_toggle)

            term_widget, _, _ = self._create_cuda_terminal()
            term_widget.setVisible(False)
            layout.addWidget(term_widget)

            adv_toggle.clicked.connect(
                lambda: term_widget.setVisible(not term_widget.isVisible()))

        # ========== 分支 2: 有 GPU 但无 CUDA → 终端式管理 ==========
        elif hw['has_nvidia_gpu']:
            layout.addWidget(self._mklabel(
                f'检测到 NVIDIA 显卡（{hw["gpu_name"]}），但 CUDA 版 torch 未安装',
                'warning'))

            term_widget, _, _ = self._create_cuda_terminal()
            layout.addWidget(term_widget)

            if audio_dur > 0:
                est_cpu_val = self._estimate_separation_time(
                    audio_dur, current_model, False)
                est_gpu_val = self._estimate_separation_time(
                    audio_dur, current_model, True)
                layout.addWidget(self._mklabel(
                    f'当前音频时长 {self._format_time(audio_dur)}：\n'
                    f'  CPU 预计 {self._format_time(est_cpu_val)}\n'
                    f'  GPU 预计 {self._format_time(est_gpu_val)}', 'time'))

        # ========== 分支 3: 无 GPU ==========
        else:
            layout.addWidget(self._mklabel(
                '⚠ 当前使用 CPU 运行，音频分离会比较慢', 'warning'))

            if audio_dur > 0:
                est_time = self._estimate_separation_time(audio_dur, current_model, False)
                layout.addWidget(self._mklabel(
                    f'当前音频时长 {self._format_time(audio_dur)}，'
                    f'预计分离耗时约 {self._format_time(est_time)}', 'time'))

            layout.addWidget(self._mklabel(
                '推荐切换到更快的模型（质量略降但速度快很多）：', 'desc'))

            models_info = [
                ('big_beta7', 'Mel-Band RoFormer (当前)',
                 '质量最高，速度最慢。CPU 约 5x 实时。', 'big_beta7'),
                ('bs_roformer_voc_hyperacev2', 'BS-RoFormer',
                 '质量接近，速度快 40%。CPU 约 3x 实时。', 'bs_roformer_voc_hyperacev2'),
                ('scnet_checkpoint_musdb18', 'SCNet',
                 '质量略降，速度最快。CPU 约 1.5x 实时。推荐无 GPU 用户。',
                 'scnet_checkpoint_musdb18'),
            ]

            self._model_radio_group = QButtonGroup(dlg)
            for i, (model_id, name, desc, _) in enumerate(models_info):
                row = QFrame()
                border_color = t['accent'] if i == 0 else t['card_border']
                row.setStyleSheet(f"""
                    QFrame {{ background-color: {t['card_bg']}; border-radius: 10px;
                              border: 2px solid {border_color}; }}
                """)
                row_lay = QVBoxLayout(row)
                row_lay.setContentsMargins(14, 10, 14, 10)
                row_lay.setSpacing(3)
                header = QHBoxLayout()
                radio = QRadioButton(name)
                radio.setChecked(i == 0)
                self._model_radio_group.addButton(radio, i)
                header.addWidget(radio)
                header.addStretch()
                if audio_dur > 0:
                    est_val = self._estimate_separation_time(audio_dur, model_id, False)
                    time_label = QLabel(f'约 {self._format_time(est_val)}')
                    time_label.setObjectName('time')
                    header.addWidget(time_label)
                row_lay.addLayout(header)
                desc_label = QLabel(desc)
                desc_label.setObjectName('desc')
                desc_label.setWordWrap(True)
                row_lay.addWidget(desc_label)
                layout.addWidget(row)

        layout.addStretch()

        # 底部按钮
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton('关闭')
        cancel_btn.setFixedSize(80, 36)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ border-radius: 18px; font-size: 14px;
                background-color: {t['surface']}; border: 1px solid {t['border']};
                color: {t['text_primary']}; }}
            QPushButton:hover {{ border-color: {t['accent']}; }}
        """)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)

        if not hw['has_cuda'] and not hw['has_nvidia_gpu']:
            apply_btn = QPushButton('应用并下载模型')
            apply_btn.setFixedSize(140, 36)
            apply_btn.setStyleSheet(f"""
                QPushButton {{ border-radius: 18px; font-size: 14px; font-weight: bold;
                    background-color: {t['accent']}; color: white; border: none; }}
                QPushButton:hover {{ background-color: {t['accent_hover']}; }}
            """)
            apply_btn.clicked.connect(
                lambda: self._on_model_selected(dlg, models_info))
            btn_row.addWidget(apply_btn)

        layout.addLayout(btn_row)
        dlg.exec()

    def _mklabel(self, text, obj_name=''):
        """快捷创建 QLabel。"""
        lbl = QLabel(text)
        if obj_name:
            lbl.setObjectName(obj_name)
        return lbl

    def _on_model_selected(self, dlg, models_info):
        """用户选了模型后，下载并切换。"""
        idx = self._model_radio_group.checkedId()
        if idx < 0:
            return
        model_id, name, _, _ = models_info[idx]
        if model_id == 'big_beta7':
            dlg.accept()
            return
        dlg.accept()
        self._download_and_switch_model(model_id, name)

    def _download_and_switch_model(self, model_id, model_name):
        """后台下载模型并切换配置。"""
        # 先切换配置（pymss 会在首次使用时自动下载）
        try:
            import app_settings
            app_settings.set_many({f'sep.model_name': model_id})
        except Exception as e:
            self.logger.warning(f"保存模型设置失败: {e}")

        QMessageBox.information(self, '模型已切换',
            f'已切换到 {model_name}\n\n'
            f'模型将在下次分析时自动下载（首次使用约需 100-500MB 下载）。\n'
            f'已保存设置，下次启动仍然生效。')

    def _apply_sensitivity_reanalyze(self):
        """应用当前灵敏度参数并重新分析。

        删除已存在的 _accomp.mid / _vocal.mid / .mid（强制重转录，否则 transcribe_*
        函数会因 skip_if_exists 直接复用旧文件，灵敏度参数不会生效），然后调用
        start_analysis() 重新跑整个流水线。
        """
        if not self.audio_path:
            QMessageBox.warning(self, "提示", "请先选择音频文件再应用灵敏度。")
            return
        if self.is_processing:
            QMessageBox.warning(self, "提示", "正在分析中，请等待当前分析完成。")
            return

        audio_name = os.path.splitext(os.path.basename(self.audio_path))[0]
        work_dir = self.work_dir

        # 待删除的中间产物（不删原始音频、不删分离后的 wav）
        candidates = [
            os.path.join(work_dir, f"{audio_name}_accomp.mid"),
            os.path.join(work_dir, f"{audio_name}_accomp_cleaned.mid"),
            os.path.join(work_dir, f"{audio_name}_vocal.mid"),
            os.path.join(work_dir, f"{audio_name}.mid"),
            os.path.join(work_dir, f"{audio_name}_merged.mid"),
        ]
        existing = [p for p in candidates if os.path.exists(p)]
        if not existing:
            QMessageBox.information(self, "提示", "未找到已有 MIDI 文件，请直接点「开始分析」。")
            return

        sens = self._collect_sensitivity()
        msg = (
            f"将删除以下中间 MIDI 并用新灵敏度重新分析：\n\n"
            f"  伴奏灵敏度: {sens['accomp_sensitivity']}\n"
            f"  人声 onset: {sens['vocal_onset_threshold']:.2f}\n"
            f"  人声 frame: {sens['vocal_frame_threshold']:.2f}\n"
            f"  最短音符: {sens['vocal_min_note_length']}ms\n\n"
            f"将删除 {len(existing)} 个文件，整个分析过程约需 1-3 分钟。"
        )
        reply = QMessageBox.question(
            self, "应用灵敏度并重新分析", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        # 持久化灵敏度设置，防止下次启动丢失
        try:
            import app_settings
            app_settings.set_many({
                'sensitivity.vocal_onset': int(sens['vocal_onset_threshold'] * 100),
                'sensitivity.vocal_frame': int(sens['vocal_frame_threshold'] * 100),
                'sensitivity.vocal_minlen': sens['vocal_min_note_length'],
                'sensitivity.accomp_sens': sens['accomp_sensitivity'],
                'sensitivity.accomp_min_dur': self.slider_accomp_min_dur.value(),
                'sensitivity.accomp_max_poly': self.slider_accomp_max_poly.value(),
            })
            self.logger.info('[ApplySens] 灵敏度已保存到持久化设置')
        except Exception as e:
            self.logger.warning(f'[ApplySens] 保存灵敏度失败: {e}')

        for p in existing:
            try:
                os.remove(p)
                self.logger.info(f"[ApplySens] 删除: {p}")
            except Exception as e:
                self.logger.warning(f"[ApplySens] 删除失败 {p}: {e}")

        # 清空当前音频缓存，强制重新合成
        with self._audio_lock:
            self.audio_data = None
        self.btn_play.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_export.setEnabled(False)

        # 触发重新分析（start_analysis 内部会读 _collect_sensitivity）
        self.start_analysis()

    def _apply_denoise(self):
        """Re-run denoising with current parameters and reload the result."""
        if not self.midi_path:
            return

        # Determine work directory and file names
        work_dir = self.work_dir
        audio_name = os.path.splitext(os.path.basename(self.audio_path or self.midi_path))[0]

        # vocal 模式特殊处理：用人声清洗函数 clean_midi_post，不做伴奏合并
        is_vocal = (self.current_mode == 'vocal')
        is_accomp = (self.current_mode == 'accomp')

        # Find the original accomp MIDI (before cleaning) — 仅 standard/accomp 模式需要
        accomp_mid = os.path.join(work_dir, f"{audio_name}_accomp.mid")
        if not os.path.exists(accomp_mid) and not is_vocal:
            # Fallback: use the current midi_path as input
            self.logger.warning("降噪: 未找到原始伴奏MIDI，使用当前MIDI作为输入")
            accomp_mid = self.midi_path

        # vocal 模式直接用原始人声 MIDI
        vocal_mid = os.path.join(work_dir, f"{audio_name}_vocal.mid")
        if is_vocal:
            if not os.path.exists(vocal_mid):
                self.logger.warning("降噪: 未找到原始人声MIDI，使用当前MIDI作为输入")
                vocal_mid = self.midi_path

        accomp_cleaned = accomp_mid.replace('.mid', '_cleaned.mid')
        vocal_cleaned = vocal_mid.replace('.mid', '_cleaned.mid')

        # Get parameters (only needed for auto/manual modes; off mode skips cleaning)
        params = None
        if self.denoise_mode == 'auto':
            params = {
                'removal_threshold': 0.25,
                'min_duration_ms': 80,
                'chord_strictness': 0.25,
                'max_jump_semitones': 12,
                'max_polyphony': 6,
            }
        elif self.denoise_mode == 'manual':
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
                from split_transcribe_merge import clean_accompaniment_strict, merge_midi_smart, clean_midi_post

                if self.denoise_mode == 'off':
                    # 关闭降噪：直接使用原始 MIDI
                    if is_vocal:
                        output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                        shutil.copy2(vocal_mid, output_mid)
                    elif is_accomp:
                        output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                        shutil.copy2(accomp_mid, output_mid)
                    else:
                        # Standard mode: re-merge原始伴奏与人声，不做降噪
                        if os.path.exists(vocal_mid):
                            merged_mid = os.path.join(work_dir, f"{audio_name}_merged.mid")
                            merge_midi_smart(accomp_mid, vocal_mid, merged_mid)
                            output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                            shutil.copy2(merged_mid, output_mid)
                        else:
                            output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                            shutil.copy2(accomp_mid, output_mid)

                # === vocal 模式：用 clean_midi_post（人声专用清洗）===
                elif is_vocal:
                    clean_midi_post(vocal_mid, vocal_cleaned)
                    output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                    shutil.copy2(vocal_cleaned, output_mid)

                else:
                    # auto / manual: 应用降噪 (only the strict clean step)
                    clean_accompaniment_strict(
                        accomp_mid, accomp_cleaned,
                        removal_threshold=params['removal_threshold'],
                        min_duration_ms=params['min_duration_ms'],
                        chord_strictness=params['chord_strictness'],
                        max_jump_semitones=params['max_jump_semitones'],
                        max_polyphony=params['max_polyphony'],
                    )

                    if is_accomp:
                        output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                        shutil.copy2(accomp_cleaned, output_mid)
                    else:
                        # Standard mode: re-merge with vocals, skip post-clean
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
        """Handle difficulty button group click.

        Selection state is driven by the QButtonGroup's exclusive flag plus
        the global ``#segPill:checked`` stylesheet rule, so we only need to
        refresh the buttons (no more object-name swapping).
        """
        self.current_difficulty = difficulty
        self.logger.info(f'难度切换: {difficulty}')
        # Update check state on each button (QButtonGroup exclusivity handles
        # the auto-unchecking, but we set state explicitly for safety).
        for diff, btn in self.diff_buttons.items():
            btn.setChecked(diff == difficulty)
            # Force style refresh — the checked-state styling kicks in here.
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

        # 性能预检：首次分析前弹出 GPU/模型对话框（用户可手动跳过）
        if not getattr(self, '_perf_check_done', False):
            self._perf_check_done = True
            hw = self._detect_hardware()
            # 仅在需要用户决策时弹出（有NVIDIA但未启用CUDA / 无NVIDIA）
            if (hw['has_nvidia_gpu'] and not hw['has_cuda']) or not hw['has_nvidia_gpu']:
                self._show_gpu_model_dialog()

        self.logger.info(f'分析开始: 音频={self.audio_path}, 模式={self.current_mode}, 难度={self.current_difficulty}')

        self.is_processing = True
        self.btn_analyze.setEnabled(False)
        self.btn_select.setEnabled(False)
        self._analysis_start_time = time.time()  # 记录开始时间
        self._step_start_time = time.time()      # 当前步骤开始时间
        self._current_percent = 0
        self._current_message = "正在分析..."
        self._step_history = []                  # 已完成步骤的 [(key, duration, weight), ...]
        self._current_step_key = None
        self._current_step_weight = 0
        self._remaining_weights = 0
        # QTimer 每秒实时更新进度标签（已用时间 + 预计剩余时间）
        if not hasattr(self, '_progress_timer'):
            self._progress_timer = QTimer(self)
            self._progress_timer.timeout.connect(self._update_progress_text)
        self._progress_timer.start(1000)
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
                merge_midi_smart, clean_midi_post, clean_accompaniment_strict,
                separate_audio_stems, transcribe_stems, merge_midi_4stems,
            )

            audio_name = os.path.splitext(os.path.basename(self.audio_path))[0]
            work_dir = self.work_dir
            sens = self._collect_sensitivity()

            # === 细化模式（4-stem）：vocals/drums/bass/other 全部分离+转录 ===
            if self.separation_mode == 'stems' and self.current_mode == 'standard':
                self.signals.progress.emit(5, "正在分离 4 音轨 (Mel-Band RoFormer 4-stem)...")
                stems = separate_audio_stems(self.audio_path, work_dir, skip_if_exists=True)
                if not stems:
                    self.signals.error.emit("4 音轨分离失败（请确认已安装 pymss: pip install pymss）")
                    return

                self.signals.progress.emit(20, "正在转录旋律音轨 (Transkun)...")
                stem_mids = transcribe_stems(stems, work_dir, audio_name, sens, self.denoise_mode)

                self.signals.progress.emit(80, "正在合并多轨乐谱...")
                merged_mid = os.path.join(work_dir, f"{audio_name}_merged.mid")
                merge_midi_4stems(stem_mids, merged_mid)

                output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                if self.denoise_mode != 'off':
                    self.signals.progress.emit(95, "正在清理和优化...")
                    clean_midi_post(merged_mid, output_mid)
                else:
                    shutil.copy(merged_mid, output_mid)

                self.signals.progress.emit(100, "分析完成! (4 音轨)")
                self.signals.finished.emit(output_mid)
                return

            self.signals.progress.emit(5, "正在分离人声和伴奏 (Mel-Band RoFormer)...")
            vocals_path, accomp_path = separate_audio(
                self.audio_path, work_dir, skip_if_exists=True)
            if not vocals_path or not accomp_path:
                self.signals.error.emit("音频分离失败（请确认已安装 pymss: pip install \"pymss>=2.0.9\"）")
                return

            # Mode-dependent analysis
            if self.current_mode == 'accomp':
                # Accompaniment only mode
                self.signals.progress.emit(25, "正在转录伴奏 (Transkun)...")
                accomp_mid = os.path.join(work_dir, f"{audio_name}_accomp.mid")
                result = transcribe_accompaniment(accomp_path, accomp_mid,
                                                  sensitivity=sens['accomp_sensitivity'])
                if not result:
                    self.signals.error.emit("伴奏转录失败")
                    return
                output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                if self.denoise_mode != 'off':
                    self.signals.progress.emit(60, "正在降噪优化伴奏...")
                    accomp_cleaned = accomp_mid.replace('.mid', '_cleaned.mid')
                    clean_accompaniment_strict(
                        accomp_mid, accomp_cleaned,
                        min_duration_ms=sens['accomp_min_duration_ms'],
                        max_polyphony=sens['accomp_max_polyphony'],
                    )
                    clean_midi_post(accomp_cleaned, output_mid)
                else:
                    self.signals.progress.emit(60, "正在应用伴奏参数...")
                    # 即使关闭降噪，也应用灵敏度区的伴奏参数（最短音符 / 和弦数）
                    clean_accompaniment_strict(
                        accomp_mid, output_mid,
                        removal_threshold=0.5,    # 宽松：只删极明显噪声
                        min_duration_ms=sens['accomp_min_duration_ms'],
                        chord_strictness=0.0,     # 不做和弦过滤
                        max_jump_semitones=24,    # 允许大跳
                        max_polyphony=sens['accomp_max_polyphony'],
                    )
                self.signals.progress.emit(100, "分析完成!")
                self.signals.finished.emit(output_mid)
                return

            elif self.current_mode == 'vocal':
                # Vocal only mode
                self.signals.progress.emit(25, "正在转录人声 (Basic Pitch)...")
                vocal_mid = os.path.join(work_dir, f"{audio_name}_vocal.mid")
                result = transcribe_vocals(vocals_path, vocal_mid,
                                           onset_threshold=sens['vocal_onset_threshold'],
                                           frame_threshold=sens['vocal_frame_threshold'],
                                           minimum_note_length=sens['vocal_min_note_length'])
                if not result:
                    self.signals.error.emit("人声转录失败")
                    return
                output_mid = os.path.join(work_dir, f"{audio_name}.mid")
                if self.denoise_mode != 'off':
                    clean_midi_post(vocal_mid, output_mid)
                else:
                    shutil.copy(vocal_mid, output_mid)
                self.signals.progress.emit(100, "分析完成!")
                self.signals.finished.emit(output_mid)
                return

            # Standard mode: full analysis
            self.signals.progress.emit(25, "正在转录伴奏 (Transkun)...")
            accomp_mid = os.path.join(work_dir, f"{audio_name}_accomp.mid")
            result = transcribe_accompaniment(accomp_path, accomp_mid,
                                              sensitivity=sens['accomp_sensitivity'])
            if not result:
                self.signals.error.emit("伴奏转录失败")
                return

            # Apply strict accompaniment cleaning
            if self.denoise_mode != 'off':
                self.signals.progress.emit(40, "正在降噪优化伴奏...")
                accomp_cleaned = accomp_mid.replace('.mid', '_cleaned.mid')
                clean_accompaniment_strict(
                    accomp_mid, accomp_cleaned,
                    min_duration_ms=sens['accomp_min_duration_ms'],
                    max_polyphony=sens['accomp_max_polyphony'],
                )
                accomp_mid = accomp_cleaned
            else:
                self.signals.progress.emit(40, "正在应用伴奏参数...")
                # 即使关闭降噪，也应用灵敏度区的伴奏参数（最短音符 / 和弦数）
                accomp_cleaned = accomp_mid.replace('.mid', '_cleaned.mid')
                clean_accompaniment_strict(
                    accomp_mid, accomp_cleaned,
                    removal_threshold=0.5,
                    min_duration_ms=sens['accomp_min_duration_ms'],
                    chord_strictness=0.0,
                    max_jump_semitones=24,
                    max_polyphony=sens['accomp_max_polyphony'],
                )
                accomp_mid = accomp_cleaned

            self.signals.progress.emit(55, "正在转录人声 (Basic Pitch)...")
            vocal_mid = os.path.join(work_dir, f"{audio_name}_vocal.mid")
            result = transcribe_vocals(vocals_path, vocal_mid,
                                       onset_threshold=sens['vocal_onset_threshold'],
                                       frame_threshold=sens['vocal_frame_threshold'],
                                       minimum_note_length=sens['vocal_min_note_length'])
            if not result:
                self.signals.error.emit("人声转录失败")
                return

            self.signals.progress.emit(80, "正在合并乐谱...")
            merged_mid = os.path.join(work_dir, f"{audio_name}_merged.mid")
            merge_midi_smart(accomp_mid, vocal_mid, merged_mid)

            output_mid = os.path.join(work_dir, f"{audio_name}.mid")
            if self.denoise_mode != 'off':
                self.signals.progress.emit(95, "正在清理和优化...")
                clean_midi_post(merged_mid, output_mid)
            else:
                self.signals.progress.emit(95, "跳过清理（已关闭）")
                shutil.copy(merged_mid, output_mid)

            self.signals.progress.emit(100, "分析完成!")
            self.signals.finished.emit(output_mid)

        except Exception as e:
            self.logger.error(f'分析出错: {str(e)}\n{traceback.format_exc()}')
            self.signals.error.emit(f"分析出错: {str(e)}\n{traceback.format_exc()}")

    def _on_progress(self, percent, message):
        self._current_percent = percent
        self._current_message = message
        # 识别当前步骤并记录
        self._enter_step(message)
        self._animate_progress(percent)
        self._update_progress_text()
        self.logger.debug(f'分析进度: {percent}% - {message}')

    # 步骤权重表（代表相对耗时）：(关键词, 权重)
    _STEP_WEIGHTS = [
        ('分离', 2),         # 分离人声和伴奏
        ('转录伴奏', 5),     # Transkun 伴奏转录（最慢）
        ('降噪', 1),         # 降噪优化
        ('转录人声', 4),     # Whisper + FCPE 人声转录
        ('合并', 1),         # 合并乐谱
        ('清理', 2),         # 清理和优化
    ]

    def _enter_step(self, message):
        """识别当前步骤，记录步骤切换时间和已完成步骤耗时。"""
        now = time.time()
        step_key = None
        step_weight = 0
        remaining_weights = 0
        found = False
        for i, (keyword, weight) in enumerate(self._STEP_WEIGHTS):
            if keyword in message:
                step_key = keyword
                step_weight = weight
                remaining_weights = sum(w for _, w in self._STEP_WEIGHTS[i+1:])
                found = True
                break
        if not found:
            return

        # 如果步骤切换了，记录前一步的耗时
        prev_step = getattr(self, '_current_step_key', None)
        if prev_step is not None and prev_step != step_key:
            prev_duration = now - getattr(self, '_current_step_start', now)
            prev_weight = getattr(self, '_current_step_weight', 0)
            if not hasattr(self, '_step_history'):
                self._step_history = []
            self._step_history.append((prev_step, prev_duration, prev_weight))

        self._current_step_key = step_key
        self._current_step_start = now
        self._current_step_weight = step_weight
        self._remaining_weights = remaining_weights

    def _estimate_remaining(self):
        """基于已完成步骤的实际耗时和权重，估算剩余时间。"""
        now = time.time()
        history = getattr(self, '_step_history', [])
        current_weight = getattr(self, '_current_step_weight', 0)
        remaining_weights = getattr(self, '_remaining_weights', 0)
        step_start = getattr(self, '_current_step_start', now)

        if not history or current_weight == 0:
            return None  # 第一个步骤还没完成，无法估算

        # 已完成步骤的每权重平均耗时
        total_completed_time = sum(d for _, d, _ in history)
        total_completed_weight = sum(w for _, _, w in history)
        if total_completed_weight == 0:
            return None
        time_per_weight = total_completed_time / total_completed_weight

        # 当前步骤预估剩余
        step_elapsed = now - step_start
        step_est_total = time_per_weight * current_weight
        step_remaining = max(0, step_est_total - step_elapsed)

        # 后续步骤预估
        future_est = time_per_weight * remaining_weights

        return step_remaining + future_est

    def _update_progress_text(self):
        """QTimer 每秒调用：实时更新进度标签（已用时间 + 预计剩余时间）。"""
        now = time.time()
        elapsed = now - getattr(self, '_analysis_start_time', now)
        message = getattr(self, '_current_message', '正在分析...')

        def fmt(secs):
            secs = int(max(0, secs))
            if secs >= 60:
                return f"{secs // 60}分{secs % 60}秒"
            return f"{secs}秒"

        remaining = self._estimate_remaining()
        if remaining is not None and remaining > 1:
            self.progress_label.setText(f"{message}  (已用 {fmt(elapsed)}，预计剩余 {fmt(remaining)})")
        else:
            self.progress_label.setText(f"{message}  (已用 {fmt(elapsed)})")

    def _on_finished(self, midi_path):
        self.midi_path = midi_path
        self.is_processing = False

        # 停止进度计时器
        if hasattr(self, '_progress_timer'):
            self._progress_timer.stop()

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
        # Switch the sheet-music stack from the empty-state placeholder to
        # the actual SheetMusicWidget now that notes are loaded.
        self._show_sheet_content(show_actual=True)
        # Update page label (will be refined when SVG renders)
        self._update_page_controls()

        # Start cursor timer if not already running
        if not self._cursor_timer.isActive():
            self._cursor_timer.start()

        # Load into piano roll
        # Build track_info from MIDI: map note index to track index
        track_info = self._build_track_info(midi_path, self.sheet_widget.display_notes)
        self.piano_roll.load_notes(self.sheet_widget.display_notes,
                                   self.sheet_widget.duration,
                                   track_info)
        # Switch the piano-roll stack from the empty-state placeholder to
        # the actual PianoRollWidget now that notes are loaded.
        self._show_roll_content(show_actual=True)

        # Synthesize audio for playback (uses sheet_widget.display_notes
        # which was set by apply_difficulty inside load_midi)
        self._synthesize_for_playback()

        # Grade difficulty
        level, name, color, detail = grade_difficulty(midi_path)
        self.diff_level.setText(str(level))
        # Spec: 64px monospace for difficulty number.
        self.diff_level.setStyleSheet(
            f"font-size: 64px; font-weight: bold; "
            f"font-family: 'JetBrains Mono','Cascadia Mono','Consolas','Menlo','monospace'; "
            f"color: {color}; border: none;")
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
        # 停止进度计时器
        if hasattr(self, '_progress_timer'):
            self._progress_timer.stop()
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
        """Synthesize audio from notes using FluidSynth + FluidR3_GM.sf2.
        Runs in a background thread to avoid UI freezing."""
        self.logger.info(f'[_synthesize_for_playback] 开始, notes={"None" if notes is None else len(notes)}')
        if notes is None:
            notes = list(self.sheet_widget.display_notes) if self.sheet_widget.display_notes else None
        if not notes:
            with self._audio_lock:
                self.audio_data = None
            try:
                _synthesis_bridge.done.emit()
            except Exception:
                pass
            return

        notes = self._apply_velocity_mode(notes)
        need_normalize = hasattr(self, '_vel_mode_group') and self._vel_mode_group.checkedId() == 1

        def _worker():
            audio = None
            # 优先使用优化的 pyfluidsynth 直接渲染（控制 gain/reverb/chorus）
            sf2_path = self._find_best_soundfont()
            if sf2_path:
                try:
                    audio = self._fluidsynth_render_optimized(notes, sf2_path, fs=self.audio_sr)
                    if audio is not None and len(audio) > 0:
                        self.logger.info(f'FluidSynth 优化合成完成 ({len(notes)} 音符, {len(audio)/self.audio_sr:.1f}s, SF2={os.path.basename(sf2_path)})')
                except Exception as e:
                    self.logger.warning(f'FluidSynth 优化合成失败 ({e}), 尝试 pretty_midi 渲染')
                    audio = None

            # 回退：pretty_midi.fluidsynth()
            if audio is None and sf2_path:
                try:
                    midi = pretty_midi.PrettyMIDI()
                    inst = pretty_midi.Instrument(program=0)
                    for n in notes:
                        inst.notes.append(pretty_midi.Note(
                            velocity=int(n['velocity']), pitch=int(n['pitch']),
                            start=float(n['start']), end=float(n['end'])
                        ))
                    midi.instruments.append(inst)
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
                    self.logger.info(f'FluidSynth 基础合成完成 ({len(notes)} 音符)')
                except Exception as e:
                    self.logger.warning(f'FluidSynth 基础合成失败 ({e}), 使用加法合成')
                    audio = None

            # 最终回退：加法合成
            if audio is None:
                try:
                    audio = self._synthesize_piano_from_notes(notes, fs=self.audio_sr)
                except Exception:
                    midi = pretty_midi.PrettyMIDI()
                    inst = pretty_midi.Instrument(program=0)
                    for n in notes:
                        inst.notes.append(pretty_midi.Note(
                            velocity=int(n['velocity']), pitch=int(n['pitch']),
                            start=float(n['start']), end=float(n['end'])
                        ))
                    midi.instruments.append(inst)
                    audio = midi.synthesize(fs=self.audio_sr)
                    audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)

            if audio is not None and need_normalize:
                try:
                    audio = self._normalize_audio_volume(audio)
                except Exception:
                    pass

            with self._audio_lock:
                self.audio_data = audio

            try:
                _synthesis_bridge.done.emit()
            except Exception:
                pass

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _on_sheet_rendered(self):
        """Called when sheet music SVG has finished loading (or rendering failed)."""
        self._on_render_progress('完成', 100)
        QTimer.singleShot(1000, self._hide_render_progress)
        self._show_status("乐谱渲染完成", 3000)
        # Safety net: enable play/stop if notes are ready but synthesis callback didn't fire
        if self.sheet_widget.display_notes and not self.btn_play.isEnabled():
            self.btn_play.setEnabled(True)
            self.btn_stop.setEnabled(True)
            self.logger.info('[Sheet] 安全网启用播放/停止按钮')

        # Show page controls if multi-page
        self._update_page_controls()

    def _on_render_progress(self, msg, pct):
        """Update bottom-left progress bar during LilyPond rendering."""
        self._render_status_label.setText(msg)
        self._render_status_label.show()
        self._render_progress_bar.setValue(pct)
        self._render_progress_bar.show()

    def _hide_render_progress(self):
        """Hide the rendering progress bar."""
        self._render_progress_bar.hide()
        self._render_status_label.hide()

    def _on_page_changed(self, page, total):
        """Update page label when sheet page changes."""
        self.page_label.setText(f"{page + 1} / {total}")
        self.btn_prev_page.setEnabled(page > 0)
        self.btn_next_page.setEnabled(page < total - 1)

    def _update_page_controls(self):
        pc = self.sheet_widget.page_count
        has_pages = pc > 1
        # Always show page label, even for single-page scores
        if pc > 0:
            self.page_label.setVisible(True)
            self._on_page_changed(self.sheet_widget.current_page, pc)
        else:
            self.page_label.setVisible(False)
        self.btn_prev_page.setVisible(has_pages)
        self.btn_next_page.setVisible(has_pages)

    @Slot()
    def _enable_play_after_synthesis(self):
        """Called on main thread after audio synthesis completes."""
        with self._audio_lock:
            has_audio = self.audio_data is not None
        has_notes = bool(self.sheet_widget.display_notes)
        # Enable play if we have notes (MCI fallback) or audio (FluidSynth)
        can_play = has_notes or has_audio
        self.btn_play.setEnabled(can_play)
        self.btn_stop.setEnabled(can_play)
        self.logger.info(f'合成完成回调: has_audio={has_audio}, has_notes={has_notes}, btn_enabled={can_play}')
        if can_play:
            self._show_status("可以播放", 3000)

    def _fluidsynth_render_optimized(self, notes, sf2_path, fs=44100):
        """使用 pyfluidsynth 直接渲染，控制 gain/reverb/chorus 参数以获得更好音色。

        相比 pretty_midi.fluidsynth() 的改进：
        - gain 0.5（避免削波失真）
        - 轻度混响（增加空间感，不过量）
        - polyphony 256（避免复音数不足导致音符丢失）

        音色参数从 app_settings 读取（用户可在设置对话框里改）：
        - audio.gain       合成器增益（0.1-1.0，默认 0.5）
        - audio.reverb.*   混响开关 + room_size
        - sf2.program      乐器 program（0=钢琴 40=小提琴 73=长笛...）
        """
        import fluidsynth
        import app_settings

        audio_cfg = app_settings.get_audio_settings()
        gain = float(audio_cfg.get('gain', 0.5))
        reverb_cfg = audio_cfg.get('reverb', {})
        reverb_active = bool(reverb_cfg.get('active', True))
        room_size = float(reverb_cfg.get('room_size', 0.7))
        program = app_settings.get_instrument_program()

        # 创建合成器，增益从 settings 读取
        synth = fluidsynth.Synth(gain=gain)

        # 设置合成器参数
        try:
            synth.setting('synth.polyphony', 256)
        except Exception:
            pass

        if reverb_active:
            try:
                synth.setting('synth.reverb.active', 1)
                synth.setting('synth.reverb.room-size', room_size)
                synth.setting('synth.reverb.damp', 0.4)
                synth.setting('synth.reverb.level', 0.25)
                synth.setting('synth.reverb.width', 0.5)
            except Exception as e:
                self.logger.debug(f'混响设置失败: {e}')
        else:
            try:
                synth.setting('synth.reverb.active', 0)
            except Exception:
                pass

        # 关闭合唱（合唱容易引入调制杂音）
        try:
            synth.setting('synth.chorus.active', 0)
        except Exception:
            pass

        # 加载 SoundFont 并选择音色（program 从 settings 读取，bank=0）
        sfid = synth.sfload(sf2_path)
        synth.program_select(0, sfid, 0, program)

        # 构建事件时间线（noteon / noteoff）
        events = []
        for n in notes:
            events.append((float(n['start']), 'on', int(n['pitch']), int(n['velocity'])))
            events.append((float(n['end']), 'off', int(n['pitch']), 0))
        events.sort()

        # 总时长 + 1.5s 尾声用于混响衰减
        max_end = max(n['end'] for n in notes) + 1.5
        total_samples = int(max_end * fs)

        # 分块渲染
        buffer_size = 1024
        audio = np.zeros(total_samples, dtype=np.float32)
        current_sample = 0
        event_idx = 0

        try:
            while current_sample < total_samples:
                current_time = current_sample / fs
                # 处理到当前时间为止的所有事件
                while event_idx < len(events) and events[event_idx][0] <= current_time:
                    _, etype, pitch, vel = events[event_idx]
                    if etype == 'on':
                        synth.noteon(0, pitch, vel)
                    else:
                        synth.noteoff(0, pitch)
                    event_idx += 1

                # 获取音频块（返回 int16 交错立体声）
                samples = synth.get_samples(buffer_size)
                if samples is None or len(samples) == 0:
                    break

                # 交错立体声转单声道：先转 float32 再除以 32768 归一化到 [-1.0, 1.0]
                if len(samples) >= buffer_size * 2:
                    left = samples[0:buffer_size * 2:2].astype(np.float32) / 32768.0
                    right = samples[1:buffer_size * 2:2].astype(np.float32) / 32768.0
                    mono = (left + right) * 0.5
                else:
                    mono = samples[::2].astype(np.float32) / 32768.0

                end = min(current_sample + buffer_size, total_samples)
                chunk = min(len(mono), end - current_sample)
                if chunk <= 0:
                    break
                audio[current_sample:current_sample + chunk] = mono[:chunk]
                current_sample += chunk
        finally:
            try:
                synth.delete()
            except Exception:
                pass

        # 归一化：防止削波，保持音量在合理范围
        peak = np.max(np.abs(audio))
        if peak > 0.95:
            audio = audio * (0.95 / peak)

        # 转换为 int16
        audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        return audio

    def _find_best_soundfont(self):
        """查找系统中可用的最佳 SF2 音色库文件。

        优先级（基于音色质量）：
        0. 用户在设置里手动选的 SF2（最高优先级，覆盖自动检测）
        1. TimbresOfHeaven.sf2 (399MB, 最多力度分层，最真实)
        2. SGM*.sf2 (235MB, 日系明亮风格)
        3. FluidR3_GM.sf2 (141MB, 均衡)
        4. GeneralUser*.sf2 (30MB, 轻量但高质量)
        5. Arachno*.sf2 (148MB, 现代有力)
        6. 其他 sf2（按大小排序）
        """
        # 0. 用户手动选的 SF2 优先（settings 里 sf2.selected_path）
        try:
            import app_settings
            user_path = app_settings.get_soundfont_path()
            if user_path and os.path.exists(user_path):
                self.logger.info(f'使用用户选定音色库: {os.path.basename(user_path)}')
                return user_path
        except Exception:
            pass

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

        # 按音色库质量优先级排序
        priority_names = [
            'TimbresOfHeaven', 'Timbres Of Heaven', 'Timbres_of_Heaven',
            'SGM', 'sgm',
            'FluidR3', 'fluidr3',
            'GeneralUser', 'General User', 'generaluser',
            'Arachno', 'arachno',
        ]

        def _priority(path):
            name = os.path.basename(path).lower()
            for i, key in enumerate(priority_names):
                if key.lower() in name:
                    return i
            return len(priority_names)  # 未知音色库排最后

        candidates.sort(key=lambda f: (_priority(f), -os.path.getsize(f)))
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

        # Toggle behavior: if already playing, just stop (pause)
        if self.sheet_widget.is_playing:
            self.stop_midi()
            self._show_status("已暂停")
            return

        self.logger.info(f'播放开始: 光标时间={self.sheet_widget.cursor_time:.1f}秒')

        # Stop any current playback first (does not reset cursor_time)
        self.stop_midi()

        # If cursor is at/past end, reset to beginning
        if self.sheet_widget.cursor_time >= self.sheet_widget.duration:
            self.sheet_widget.reset_cursor()
            self.piano_roll.cursor_time = 0

        # Start sheet music playback
        self.sheet_widget.start_playback()

        # Start piano roll playback
        self.piano_roll.start_playback(self.sheet_widget.cursor_time)

        # Primary: play FluidSynth-synthesized audio through pygame
        played = False
        with self._audio_lock:
            audio_data = self.audio_data
        if audio_data is not None:
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init(frequency=self.audio_sr, size=-16,
                                      channels=1, buffer=4096)
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass

                start_sample = int(self.sheet_widget.cursor_time * self.audio_sr)
                segment = audio_data[start_sample:]
                if len(segment) > 0:
                    tmp = os.path.join(tempfile.gettempdir(),
                                       f'_piano_playback_{os.getpid()}.wav')
                    with wave.open(tmp, 'w') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(self.audio_sr)
                        wf.writeframes(segment.tobytes())
                    self._playback_tmp_wav = tmp
                    pygame.mixer.music.load(tmp)
                    pygame.mixer.music.play()
                    played = True
                    self.logger.info(f'FluidSynth 音频播放: {len(segment)} 样本')
            except Exception as e:
                self.logger.error(f'pygame 播放失败: {e}')
                if self._playback_tmp_wav and os.path.exists(self._playback_tmp_wav):
                    try: os.remove(self._playback_tmp_wav)
                    except: pass
                    self._playback_tmp_wav = None

        # Fallback: MCI MIDI synthesizer
        if not played:
            try:
                import ctypes
                import pretty_midi as _pm

                ctypes.windll.winmm.mciSendStringW('close pianoplayback', None, 0, None)

                notes = self.sheet_widget.display_notes
                pm = _pm.PrettyMIDI()
                inst = _pm.Instrument(program=0)
                for n in notes:
                    inst.notes.append(_pm.Note(
                        velocity=int(n['velocity']), pitch=int(n['pitch']),
                        start=float(n['start']), end=float(n['end'])
                    ))
                pm.instruments.append(inst)

                tmp_mid = os.path.join(tempfile.gettempdir(), f'_piano_playback_{os.getpid()}.mid')
                pm.write(tmp_mid)
                self._playback_tmp_mid = tmp_mid

                r = ctypes.windll.winmm.mciSendStringW(
                    f'open "{tmp_mid}" type sequencer alias pianoplayback', None, 0, None)
                if r == 0:
                    start_ms = int(self.sheet_widget.cursor_time * 1000)
                    if start_ms > 0:
                        ctypes.windll.winmm.mciSendStringW(
                            f'play pianoplayback from {start_ms}', None, 0, None)
                    else:
                        ctypes.windll.winmm.mciSendStringW('play pianoplayback', None, 0, None)
                    self._cursor_timer.start(50)
                    self.logger.info(f'MCI MIDI 回退播放: {len(notes)} 音符')
                else:
                    self.logger.warning(f'MCI open 失败, 错误码={r}')
            except Exception as e:
                self.logger.error(f'MCI 回退播放失败: {e}')

        self.btn_stop.setEnabled(True)
        self._show_status("正在播放...")

    def stop_midi(self):
        self.logger.info('播放停止')
        self.sheet_widget.stop_playback()
        self.piano_roll.stop_playback()
        self._cursor_timer.stop()

        # Stop MCI MIDI playback
        try:
            import ctypes
            ctypes.windll.winmm.mciSendStringW('stop pianoplayback', None, 0, None)
            ctypes.windll.winmm.mciSendStringW('close pianoplayback', None, 0, None)
        except Exception:
            pass

        # Clean up temp MIDI file
        tmp_mid = getattr(self, '_playback_tmp_mid', None)
        if tmp_mid:
            try:
                os.remove(tmp_mid)
            except Exception:
                pass
            self._playback_tmp_mid = None

        # Also stop pygame (in case it was used as fallback)
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

    def _resolve_export_midi_path(self):
        """Resolve the MIDI path to export based on the current page.

        On the edit page, the current edit notes are saved to a temp MIDI
        so that WAV/PDF exports reflect the edited content.
        """
        if self.stacked_widget.currentIndex() == 2 and hasattr(self, 'edit_piano_roll'):
            if self.edit_piano_roll.display_notes:
                tmp_mid = os.path.join(tempfile.gettempdir(),
                                       f'_edit_export_{os.getpid()}.mid')
                try:
                    self.edit_piano_roll.save_midi_file(tmp_mid)
                    return tmp_mid
                except Exception as e:
                    self.logger.error(f'编辑导出准备失败: {e}')
                    return None
            return None
        return self.midi_path

    def _export_wav(self):
        """Export current MIDI as WAV audio file."""
        midi_path = self._resolve_export_midi_path()
        if not midi_path or not os.path.exists(midi_path):
            QMessageBox.warning(self, "提示", "没有可导出的MIDI文件")
            return
        default_name = os.path.splitext(os.path.basename(midi_path))[0] + ".wav"
        path, _ = QFileDialog.getSaveFileName(self, "导出WAV", default_name, "WAV Files (*.wav)")
        if not path:
            return
        try:
            midi_data = pretty_midi.PrettyMIDI(midi_path)
            notes = []
            for inst in midi_data.instruments:
                for n in inst.notes:
                    notes.append({'pitch': n.pitch, 'start': n.start, 'end': n.end, 'velocity': n.velocity})
            if not notes:
                QMessageBox.warning(self, "提示", "MIDI文件中没有音符")
                return
            audio = self._synthesize_piano_from_notes(notes, fs=44100)
            # _synthesize_piano_from_notes already returns int16 data
            with wave.open(path, 'w') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                wf.writeframes(audio.astype(np.int16).tobytes())
            self.logger.info(f'导出WAV: {path}')
            QMessageBox.information(self, "成功", f"WAV已导出到:\n{path}")
        except Exception as e:
            self.logger.error(f'导出WAV失败: {e}')
            QMessageBox.critical(self, "错误", f"导出失败:\n{e}")

    def _export_pdf(self):
        """Export current score as PDF using LilyPond."""
        midi_path = self._resolve_export_midi_path()
        if not midi_path or not os.path.exists(midi_path):
            QMessageBox.warning(self, "提示", "没有可导出的MIDI文件")
            return
        default_name = os.path.splitext(os.path.basename(midi_path))[0] + ".pdf"
        path, _ = QFileDialog.getSaveFileName(self, "导出PDF", default_name, "PDF Files (*.pdf)")
        if not path:
            return
        try:
            # Find LilyPond (PyInstaller-aware: check sys._MEIPASS first, then system PATH, then APP_DIR)
            _lilypond_base = getattr(sys, '_MEIPASS', '')
            if _lilypond_base:
                lilypond_exe = os.path.join(_lilypond_base, "lilypond-2.24.4", "bin", "lilypond.exe")
            else:
                _which_lp = shutil.which("lilypond")
                if _which_lp:
                    lilypond_exe = _which_lp
                else:
                    lilypond_dir = os.path.join(APP_DIR, "lilypond-2.24.4", "bin")
                    lilypond_exe = os.path.join(lilypond_dir, "lilypond.exe") if os.path.isdir(lilypond_dir) else "lilypond"
            if lilypond_exe != "lilypond" and not os.path.exists(lilypond_exe):
                QMessageBox.warning(self, "提示", "未找到LilyPond，无法导出PDF")
                return
            # Generate LilyPond file from MIDI
            midi_data = pretty_midi.PrettyMIDI(midi_path)
            ly_path = path.replace('.pdf', '.ly')
            # Write LilyPond score
            with open(ly_path, 'w', encoding='utf-8') as f:
                f.write('\\version "2.24.0"\n')
                f.write('\\score {\n')
                f.write('  \\new PianoStaff <<\n')
                for inst in midi_data.instruments:
                    f.write('    \\new Staff {\n')
                    f.write('      \\key c \\major\n')
                    f.write('      \\time 4/4\n')
                    for note in sorted(inst.notes, key=lambda n: n.start):
                        note_name = pretty_midi.note_number_to_name(note.pitch)
                        octave = note.pitch // 12 - 1
                        pitch_name = note_name[:-1].replace('#', 'is').replace('b', 'es')
                        f.write(f'      {pitch_name}{octave} ')
                    f.write('\n    }\n')
                f.write('  >>\n')
                f.write('  \\midi {}\n')
                f.write('  \\layout {}\n')
                f.write('}\n')
            # Run LilyPond
            result = subprocess.run([lilypond_exe, '-o', os.path.splitext(path)[0], ly_path],
                                    capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and os.path.exists(path):
                self.logger.info(f'导出PDF: {path}')
                QMessageBox.information(self, "成功", f"PDF已导出到:\n{path}")
            else:
                self.logger.error(f'LilyPond编译失败: {result.stderr[:500]}')
                QMessageBox.critical(self, "错误", f"LilyPond编译失败:\n{result.stderr[:500]}")
        except Exception as e:
            self.logger.error(f'导出PDF失败: {e}')
            QMessageBox.critical(self, "错误", f"导出失败:\n{e}")

    def _on_tempo_changed(self, value):
        """Update playback speed factor when tempo slider changes."""
        self.tempo_value_label.setText(f"{value}%")
        factor = value / 100.0
        if hasattr(self, 'sheet_widget'):
            self.sheet_widget.speed_factor = factor
        if hasattr(self, 'edit_piano_roll'):
            self.edit_piano_roll.speed_factor = factor
        if hasattr(self, 'piano_roll'):
            self.piano_roll.speed_factor = factor

    def _toggle_playback(self):
        """Toggle play/pause."""
        if hasattr(self, 'sheet_widget') and self.sheet_widget.is_playing:
            self.stop_midi()
        else:
            self.play_midi()

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
    """Premium splash: blue-green gradient, staff notation, animated piano keys with sound."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(560, 400)

        # Load icon (center-crop to square)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pianoscribe_splash_icon.png')
        self._icon_pixmap = None
        if os.path.exists(icon_path):
            pm = QPixmap(icon_path)
            if not pm.isNull():
                side = min(pm.width(), pm.height())
                x = (pm.width() - side) // 2
                y = (pm.height() - side) // 2
                self._icon_pixmap = pm.copy(x, y, side, side).scaled(
                    50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Animation state
        self._t = 0
        self._progress = 0.0
        self._sound_played = False
        self._key_glow = 0.0

        # Note frequencies (C major arpeggio)
        self._note_freqs = {
            'C4': 261.63, 'E4': 329.63, 'G4': 392.00, 'C5': 523.25,
        }

        # White key index (from C2=0)
        self._highlighted_keys = {1, 8, 15, 16, 19}  # D2, D3, D4, E4, A4

        # Staff geometry
        self._treble_top = 80
        self._bass_top = 150
        self._staff_x = 95
        self._staff_w = 380
        self._line_gap = 6

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

        self.setWindowOpacity(0.0)
        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(500)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_in.start()

    def _play_chord(self):
        """Play D2+D3+D4+F4+A4 chord with sustain pedal through Windows MIDI synth."""
        try:
            import ctypes
            import tempfile
            import pretty_midi

            # Close any existing MCI device first
            ctypes.windll.winmm.mciSendStringW('close splashmidi', None, 0, None)

            pm = pretty_midi.PrettyMIDI()
            piano = pretty_midi.Instrument(program=0)  # Acoustic Grand Piano

            # Left hand: D2, D3 (two octaves apart, sustained)
            # Right hand: D4, F4, A4 (chord)
            # All with sustain pedal (long duration)
            notes = [
                (38, 0.0, 4.5),   # D2 - left hand
                (50, 0.0, 4.5),   # D3 - left hand
                (62, 0.0, 4.5),   # D4 - right hand (2)
                (64, 0.0, 4.5),   # E4 - right hand (3)
                (69, 0.0, 4.5),   # A4 - right hand (6)
            ]
            for pitch, start, dur in notes:
                piano.notes.append(pretty_midi.Note(
                    velocity=72, pitch=pitch, start=start, end=start + dur))

            # Sustain pedal (CC64 = sustain, value 127 = pressed)
            piano.control_changes.append(pretty_midi.ControlChange(
                number=64, value=127, time=0.0))

            pm.instruments.append(piano)

            midi_path = os.path.join(tempfile.gettempdir(), 'pianoscribe_splash_new.mid')
            pm.write(midi_path)

            ctypes.windll.winmm.mciSendStringW(
                f'open "{midi_path}" type sequencer alias splashmidi', None, 0, None)
            ctypes.windll.winmm.mciSendStringW('play splashmidi', None, 0, None)
        except Exception:
            pass

    def _tick(self):
        self._t += 1
        self._progress = min(self._progress + 1.0 / 300.0, 1.0)

        # Play sound after fade-in
        if self._t == 30 and not self._sound_played:
            self._sound_played = True
            self._play_chord()

        # Key glow pulse
        pulse = 0.5 + 0.5 * math.sin(self._t * 0.05)
        self._key_glow = 0.6 + pulse * 0.4

        self.update()

    def _note_y(self, note, staff_top, clef):
        """Get y position for a note on the staff."""
        step = self._line_gap / 2
        if clef == 'treble':
            positions = {'F5': 0, 'E5': 1, 'D5': 2, 'C5': 3, 'B4': 4,
                         'A4': 5, 'G4': 6, 'F4': 7, 'E4': 8, 'D4': 9, 'C4': 10}
        else:
            positions = {'A3': 0, 'G3': 1, 'F3': 2, 'E3': 3, 'D3': 4,
                         'C3': 5, 'B2': 6, 'A2': 7, 'G2': 8, 'F2': 9, 'E2': 10, 'D2': 11}
        return staff_top + positions.get(note, 0) * step

    def _draw_staff(self, p, staff_top, clef, notes, highlight_last=False):
        """Draw staff lines, clef, and notes with sequential reveal support."""
        if not notes:
            # Still draw staff lines and clef even without notes
            x = self._staff_x
            w = self._staff_w
            lg = self._line_gap
            for i in range(5):
                ly = staff_top + i * lg
                p.setPen(QPen(QColor(0, 0, 0, 60), 1))
                p.drawLine(QPointF(x, ly + 1), QPointF(x + w, ly + 1))
                p.setPen(QPen(QColor(180, 230, 220, 200), 1))
                p.drawLine(QPointF(x, ly), QPointF(x + w, ly))
            if clef == 'treble':
                self._draw_treble_clef(p, x + 12, staff_top, lg)
            else:
                self._draw_bass_clef(p, x + 12, staff_top, lg)
            return

        x = self._staff_x
        w = self._staff_w
        lg = self._line_gap

        # Staff lines with subtle 3D (shadow + highlight)
        for i in range(5):
            ly = staff_top + i * lg
            p.setPen(QPen(QColor(0, 0, 0, 60), 1))
            p.drawLine(QPointF(x, ly + 1), QPointF(x + w, ly + 1))
            p.setPen(QPen(QColor(180, 230, 220, 200), 1))
            p.drawLine(QPointF(x, ly), QPointF(x + w, ly))

        # Clef
        if clef == 'treble':
            self._draw_treble_clef(p, x + 12, staff_top, lg)
        else:
            self._draw_bass_clef(p, x + 12, staff_top, lg)

        # Notes as a chord (stacked, single stem)
        step = lg / 2
        note_x = x + 70
        note_ys = [self._note_y(n, staff_top, clef) for n in notes]

        # Ledger lines for notes below staff
        for ny in note_ys:
            bottom_line = staff_top + 4 * lg  # bottom staff line
            while ny > bottom_line + step:
                bottom_line += step * 2  # skip to next line position
                ledger_y = bottom_line
                if ledger_y < ny + step:  # draw ledger through line positions
                    p.setPen(QPen(QColor(180, 230, 220, 180), 1))
                    p.drawLine(QPointF(note_x - 7, ledger_y), QPointF(note_x + 7, ledger_y))

        # Note glow
        glow_alpha = int(80 * self._key_glow)
        for i, ny in enumerate(note_ys):
            is_last = (i == len(note_ys) - 1) and highlight_last
            glow_r = 16 if is_last else 12
            glow_a = min(255, glow_alpha + (80 if is_last else 0))
            g = QRadialGradient(note_x, ny, glow_r)
            g.setColorAt(0, QColor(0, 255, 200, glow_a))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(note_x, ny), glow_r, glow_r - 2)

        # Note heads (filled ovals, tilted)
        for i, ny in enumerate(note_ys):
            is_last = (i == len(note_ys) - 1) and highlight_last
            if is_last:
                # Highlighted note: brighter color + pulsing ring
                pulse = 0.5 + 0.5 * math.sin(self._t * 0.15)
                ring_r = 8 + pulse * 3
                p.setPen(QPen(QColor(0, 255, 200, int(180 * (1 - pulse))), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(note_x, ny), ring_r, ring_r - 1)
                p.setBrush(QBrush(QColor(180, 255, 240)))
                p.setPen(QPen(QColor(0, 220, 180), 1))
            else:
                p.setBrush(QBrush(QColor(230, 250, 245)))
                p.setPen(QPen(QColor(200, 240, 230), 0.5))
            p.drawEllipse(QPointF(note_x, ny), 4.5, 3.5)

        # Stem (goes up from highest note)
        top_note_y = min(note_ys)
        stem_top = top_note_y - 22
        p.setPen(QPen(QColor(220, 245, 235), 1.5))
        p.drawLine(QPointF(note_x + 4, max(note_ys) - 1), QPointF(note_x + 4, stem_top))

    def _draw_treble_clef(self, p, x, staff_top, lg):
        """Draw simplified treble clef."""
        cy = staff_top + lg * 3  # G4 line (2nd from bottom)
        p.setPen(QPen(QColor(180, 230, 220, 220), 2))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(x, cy - 14)
        path.cubicTo(x + 7, cy - 14, x + 7, cy - 4, x, cy)
        path.cubicTo(x - 7, cy + 4, x - 5, cy + 9, x + 2, cy + 11)
        p.drawPath(path)
        p.drawLine(QPointF(x, cy - 14), QPointF(x, cy + 16))
        p.setBrush(QBrush(QColor(180, 230, 220, 220)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(x, cy + 16), 3, 3)

    def _draw_bass_clef(self, p, x, staff_top, lg):
        """Draw simplified bass clef."""
        cy = staff_top + lg * 1.5  # F3 line (2nd from top)
        p.setBrush(QBrush(QColor(180, 230, 220, 220)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(x, cy), 5, 4)
        p.drawEllipse(QPointF(x + 9, cy - 3), 1.8, 1.8)
        p.drawEllipse(QPointF(x + 9, cy + 3), 1.8, 1.8)

    def _draw_piano(self, p, x, y, width, height):
        """Draw 3D piano keyboard with highlighted keys."""
        nw = 22  # 3 octaves C2-C5
        wk_w = width / nw
        wk_h = height
        bk_w = wk_w * 0.58
        bk_h = height * 0.62

        # White keys
        for i in range(nw):
            kx = x + i * wk_w
            if i in self._highlighted_keys:
                glow = self._key_glow
                kg = QLinearGradient(kx, y, kx, y + wk_h)
                kg.setColorAt(0, QColor(int(60 + glow * 40), int(210 + glow * 30), int(190 + glow * 20)))
                kg.setColorAt(0.5, QColor(int(30 + glow * 30), int(170 + glow * 30), int(150 + glow * 20)))
                kg.setColorAt(1, QColor(int(15 + glow * 20), int(130 + glow * 20), int(115 + glow * 15)))
                p.setBrush(QBrush(kg))
                # Glow around key
                for gi in range(3):
                    ga = int(30 * glow) - gi * 10
                    if ga > 0:
                        p.setPen(QPen(QColor(0, 255, 200, ga), 1))
                        p.setBrush(Qt.NoBrush)
                        p.drawRoundedRect(QRectF(kx - gi, y - gi, wk_w + gi * 2, wk_h + gi * 2), 2, 2)
                p.setBrush(QBrush(kg))
            else:
                kg = QLinearGradient(kx, y, kx, y + wk_h)
                kg.setColorAt(0, QColor(235, 242, 240))
                kg.setColorAt(0.7, QColor(215, 225, 222))
                kg.setColorAt(1, QColor(195, 208, 205))
                p.setBrush(QBrush(kg))
            p.setPen(QPen(QColor(80, 100, 100, 100), 0.5))
            p.drawRect(QRectF(kx, y, wk_w, wk_h))
            # 3D top highlight
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 50)))
            p.drawRect(QRectF(kx + 1, y + 1, wk_w - 2, 3))
            # 3D bottom shadow
            p.setBrush(QBrush(QColor(0, 0, 0, 40)))
            p.drawRect(QRectF(kx + 1, y + wk_h - 3, wk_w - 2, 2))

        # Black keys
        pattern = [0, 1, None, 2, 3, 4, None]
        for octave in range(4):
            for j, pat in enumerate(pattern):
                if pat is None:
                    continue
                wi = octave * 7 + j
                if wi >= nw - 1:
                    continue
                wi = octave * 7 + j
                kx = x + (wi + 1) * wk_w - bk_w / 2
                kg = QLinearGradient(kx, y, kx, y + bk_h)
                kg.setColorAt(0, QColor(55, 65, 75))
                kg.setColorAt(0.5, QColor(28, 35, 42))
                kg.setColorAt(1, QColor(12, 18, 22))
                p.setBrush(QBrush(kg))
                p.setPen(QPen(QColor(0, 0, 0, 120), 0.5))
                p.drawRect(QRectF(kx, y, bk_w, bk_h))
                # 3D top highlight
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(90, 100, 110, 60)))
                p.drawRect(QRectF(kx + 1, y + 1, bk_w - 2, 2))
                # 3D bottom shine
                p.setBrush(QBrush(QColor(255, 255, 255, 15)))
                p.drawRect(QRectF(kx + 1, y + bk_h - 4, bk_w - 2, 2))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()

        # ---- 3D outer shadow ----
        p.setBrush(Qt.NoBrush)
        for i in range(15, 0, -1):
            alpha = int(90 * (1 - i / 15.0) ** 2)
            p.setPen(QPen(QColor(0, 30, 40, alpha), 1))
            p.drawRoundedRect(QRectF(-i, -i, w + i * 2, h + i * 2), 18 + i, 18 + i)

        # ---- Clip ----
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 16, 16)
        p.setClipPath(clip)

        # ---- Blue-green gradient background ----
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor('#003845'))
        bg.setColorAt(0.4, QColor('#004f55'))
        bg.setColorAt(0.7, QColor('#006a6e'))
        bg.setColorAt(1, QColor('#005258'))
        p.fillRect(QRectF(0, 0, w, h), bg)

        # Radial glow center
        glow = QRadialGradient(w / 2, h * 0.35, 220)
        glow.setColorAt(0, QColor(0, 220, 200, 25))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, w, h), glow)

        # Top shine (3D glass effect)
        shine = QLinearGradient(0, 0, 0, h * 0.3)
        shine.setColorAt(0, QColor(255, 255, 255, 15))
        shine.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, w, h * 0.3), shine)

        # ---- Title with icon ----
        icon_cx = 35
        icon_cy = 32
        if self._icon_pixmap and not self._icon_pixmap.isNull():
            # Icon glow
            ig = QRadialGradient(icon_cx, icon_cy, 35)
            ig.setColorAt(0, QColor(0, 220, 200, 40))
            ig.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(ig))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(icon_cx, icon_cy), 35, 35)
            # Icon shadow
            for si in range(3):
                p.setBrush(QBrush(QColor(0, 0, 0, 40 - si * 12)))
                p.drawEllipse(QPointF(icon_cx, icon_cy + 4 + si), 22, 6)
            p.drawPixmap(QPointF(icon_cx - 25, icon_cy - 25), self._icon_pixmap)

        # Title text with glow
        p.setFont(QFont("Segoe UI", 20, QFont.Bold))
        for gi in range(3):
            p.setPen(QColor(0, 220, 200, 30 - gi * 10))
            p.drawText(QRectF(65 - gi, 12 - gi, 200, 20), Qt.AlignLeft | Qt.AlignVCenter, "PianoScribe")
            p.drawText(QRectF(65 + gi, 12 + gi, 200, 20), Qt.AlignLeft | Qt.AlignVCenter, "PianoScribe")
        grad_t = QLinearGradient(65, 12, 265, 32)
        grad_t.setColorAt(0, QColor('#5eead4'))
        grad_t.setColorAt(0.5, QColor('#22d3ee'))
        grad_t.setColorAt(1, QColor('#a7f3d0'))
        p.setPen(QPen(QBrush(grad_t), 1))
        p.drawText(QRectF(65, 12, 200, 20), Qt.AlignLeft | Qt.AlignVCenter, "PianoScribe")

        # ---- Sequential note reveal ----
        # Reveal order: D2, D3 (bass) → D4, E4, A4 (treble)
        # One note every 40 ticks (~0.67s), starting at tick 30
        reveal_count = max(0, min(5, (self._t - 30) // 40 + 1)) if self._t >= 30 else 0
        bass_notes = ['D2', 'D3']
        treble_notes = ['D4', 'E4', 'A4']
        bass_visible = min(reveal_count, len(bass_notes))
        treble_visible = max(0, reveal_count - len(bass_notes))
        # The most recently revealed note gets highlighted
        highlight_bass = bass_visible > 0 and treble_visible == 0
        highlight_treble = treble_visible > 0

        # ---- Bass staff (D2, D3) - notes revealed sequentially ----
        self._draw_staff(p, self._bass_top, 'bass', bass_notes[:bass_visible],
                         highlight_last=highlight_bass)

        # ---- Treble staff (D4, E4, A4) - notes revealed sequentially ----
        self._draw_staff(p, self._treble_top, 'treble', treble_notes[:treble_visible],
                         highlight_last=highlight_treble)

        # Brace connecting staves
        p.setPen(QPen(QColor(180, 230, 220, 120), 2))
        brace_x = self._staff_x - 8
        p.drawLine(QPointF(brace_x, self._treble_top), QPointF(brace_x, self._bass_top + 4 * self._line_gap))

        # ---- Piano keyboard ----
        self._draw_piano(p, x=40, y=225, width=480, height=110)

        # ---- Sustain pedal indicator ----
        ped_x = w - 90
        ped_y = 348
        # Pedal glow
        pg = QRadialGradient(ped_x + 15, ped_y + 6, 25)
        pg.setColorAt(0, QColor(0, 255, 200, int(60 * self._key_glow)))
        pg.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(pg))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(ped_x + 15, ped_y + 6), 25, 12)
        # Pedal body
        p.setBrush(QBrush(QColor(0, 120, 100, 180)))
        p.setPen(QPen(QColor(100, 220, 200, 200), 1))
        p.drawRoundedRect(QRectF(ped_x, ped_y, 30, 10), 3, 3)
        # Label
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QColor(100, 200, 180, 200))
        p.drawText(QRectF(ped_x - 10, ped_y + 12, 50, 10), Qt.AlignCenter, "Sustain")

        # ---- Progress bar with glow ----
        bar_w = w - 140
        bar_h = 3
        bar_x = 40
        bar_y = 353
        p.setBrush(QBrush(QColor(255, 255, 255, 20)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)
        fill_w = bar_w * self._progress
        if fill_w > 1:
            for gi in range(4):
                ga = 40 - gi * 10
                p.setBrush(QBrush(QColor(0, 220, 200, ga)))
                p.drawRoundedRect(QRectF(bar_x, bar_y - gi, fill_w, bar_h + gi * 2), 2, 2)
            fg = QLinearGradient(bar_x, 0, bar_x + fill_w, 0)
            fg.setColorAt(0, QColor('#14b8a6'))
            fg.setColorAt(0.5, QColor('#22d3ee'))
            fg.setColorAt(1, QColor('#a7f3d0'))
            p.setBrush(QBrush(fg))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        # Loading text
        dots = '.' * ((self._t // 15) % 4)
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor(100, 150, 160, 150))
        p.drawText(QRectF(bar_x, 360, bar_w, 14), Qt.AlignLeft, f"Loading{dots}")

        # Version
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QColor(80, 120, 130, 100))
        p.drawText(QRectF(0, h - 14, w - 10, 10), Qt.AlignRight, "v0.7 beta | Powered by TRAE")

        p.end()

    def finish(self, window):
        """Close splash when main window is ready."""
        self._timer.stop()
        try:
            import ctypes
            ctypes.windll.winmm.mciSendStringW('close splashmidi', None, 0, None)
        except Exception:
            pass
        self.close()


def main():
    # Single-instance guard (Windows named mutex)
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = 'PianoScribe_SingleInstance_v0.7'
        mutex = kernel32.CreateMutexW(None, False, mutex_name)
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            QApplication([])  # Need app for QMessageBox
            QMessageBox.information(None, "PianoScribe", "PianoScribe 已经在运行中。")
            return
    except Exception:
        pass  # Allow run if mutex fails

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

    # Construct main window inside the event loop so splash can animate
    def _init_and_show():
        window = PianoApp()
        splash._timer.stop()
        splash.hide()
        splash.close()
        splash.deleteLater()
        window.show()
        window.raise_()
        window.activateWindow()

    QTimer.singleShot(5000, _init_and_show)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
