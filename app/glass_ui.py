# -*- coding: utf-8 -*-
"""
glass_ui.py — 真·Liquid Glass UI 组件库（Windows 原生 Acrylic 方案）

基于网上真实实现方法构建（业界标准方案）：
1. BlurWindow 库：调用 Windows 原生 SetWindowCompositionAttribute API
   - ACCENT_ENABLE_ACRYLICBLURBEHIND 系统级硬件加速模糊
   - 零 CPU 开销（模糊由 DWM 桌面窗口管理器在 GPU 完成）
   - 这是 Win11 Acrylic 效果的官方实现方式
2. Apple Liquid Glass 规范（WWDC 2025）：
   - 半透明背景 rgba(255,255,255,0.15)
   - 1px solid rgba(255,255,255,0.2) 玻璃边框
   - inset highlight (内边缘高光)
   - 135deg gradient border (边缘折射)
3. HarmonyOS 7 沉浸光感（API 26）：
   - 柔光渐变 linearGradient
   - 立体景深
   - 流光动画

性能策略：
  - 模糊由 Windows DWM 在 GPU 完成（零 CPU 开销）
  - 子部件不做任何模糊计算，仅用半透明背景"透出"原生模糊
  - Pygame 仅渲染一次静态光斑壁纸（不实时更新），作为窗口背景图
  - 动态光感用 QPainter 轻量动画（drawPixmap 平移，不重新模糊）
"""
import logging
import math
import random
from typing import Optional, Tuple

_gl_log = logging.getLogger(__name__)

import numpy as np

from PySide6.QtCore import (
    Qt, QTimer, QRectF, QPointF, QSize, QPropertyAnimation,
    QEasingCurve, Signal, QPoint, QEvent,
)
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPixmap, QImage,
    QPainterPath, QLinearGradient, QRadialGradient, QConicalGradient,
    QFont, QCursor, QIcon, QPalette,
)
from PySide6.QtWidgets import (
    QWidget, QFrame, QPushButton, QLabel, QHBoxLayout, QVBoxLayout,
    QApplication, QMainWindow, QGraphicsBlurEffect, QSizePolicy,
)

# Lazy import design_tokens and app_icons to avoid circular imports.
# These are imported inside functions to allow glass_ui to be imported
# standalone (e.g. in tests without piano_app loaded).


# ============================================================
#  THEME HELPERS
# ============================================================
def _is_light_theme():
    """根据 design_tokens 当前主题名推断（与 piano_app 主题切换同步）。"""
    try:
        from design_tokens import get_current_theme_name
        return get_current_theme_name() == 'light'
    except Exception:
        return True


def _theme_colors():
    """返回 (bg_color, accent, tint, luminosity) 四元组。

    Backward-compatible signature — bg/accent now sourced from
    `design_tokens`. tint/luminosity keep their original alpha values
    (design_tokens `glass_highlight` differs; original alphas preserved
    for visual parity).
    """
    from design_tokens import tokens, qcolor, get_current_theme_name
    t = tokens(get_current_theme_name()).color
    bg = qcolor(t.bg)
    accent = qcolor(t.accent)
    if _is_light_theme():
        # Original alpha values preserved (tokens.glass_highlight is brighter).
        tint = QColor(255, 255, 255, 38)
        luminosity = QColor(255, 255, 255, 26)
    else:
        tint = QColor(40, 40, 45, 60)
        luminosity = QColor(255, 255, 255, 15)
    return (bg, accent, tint, luminosity)


# ============================================================
#  WINDOWS NATIVE ACRYLIC（BlurWindow 封装）
# ============================================================
def enable_native_acrylic(window: QMainWindow,
                          tint_color: Optional[QColor] = None,
                          dark_mode: Optional[bool] = None):
    """对主窗口应用 Windows 原生 Acrylic 模糊（系统级硬件加速）。

    调用 BlurWindow 库 → SetWindowCompositionAttribute API
    → ACCENT_ENABLE_ACRYLICBLURBEHIND

    优势：
      - 模糊由 DWM 在 GPU 完成，零 CPU 开销
      - 真正的 Win11 亚克力效果（非模拟）
      - 子部件用半透明背景即可"透出"原生模糊

    Args:
        window: 主窗口（需已设置 WA_TranslucentBackground）
        tint_color: 叠加色（默认浅色半透明）
        dark_mode: 是否深色模式（None=自动检测）
    """
    try:
        from BlurWindow.blurWindow import GlobalBlur
    except ImportError:
        return False

    # 自动检测深色模式
    if dark_mode is None:
        dark_mode = not _is_light_theme()

    # 构造 hex 颜色（Acrylic 模式下第一字节是 noise opacity）
    if tint_color is None:
        if dark_mode:
            # 深色：低 noise + 深色底
            hex_color = 0x01202020
        else:
            # 浅色：低 noise + 浅色底
            hex_color = 0x01F5F5F7
    else:
        # 转换 QColor 到 Acrylic hex 格式
        noise = 0x01
        r, g, b = tint_color.red(), tint_color.green(), tint_color.blue()
        hex_color = (noise << 24) | (b << 16) | (g << 8) | r

    try:
        hwnd = int(window.winId())
        GlobalBlur(hwnd, hexColor=hex_color, Acrylic=True, Dark=dark_mode,
                   QWidget=window)
        return True
    except Exception:
        import traceback
        _gl_log.warning("enable_native_acrylic() failed: %s", traceback.format_exc())
        return False


def enable_window_blur(window: QMainWindow, dark_mode: Optional[bool] = None):
    """对窗口应用原生模糊（需配合 WA_TranslucentBackground）。

    这是 enable_native_acrylic 的别名，语义更清晰。
    """
    return enable_native_acrylic(window, dark_mode=dark_mode)


# ============================================================
#  PYGAME STATIC WALLPAPER（仅渲染一次的静态光斑壁纸）
# ============================================================
class PygameWallpaper:
    """Pygame 渲染的静态光斑壁纸（仅渲染一次，不实时更新）。

    用途：作为窗口背景图，提供"流动光斑"的视觉基底。
    原生 Acrylic 模糊会作用于这张壁纸，呈现彩色光晕透过玻璃的效果。

    性能：仅在初始化和窗口 resize 时渲染一次，无持续 CPU 开销。
    """

    _instance = None

    def __init__(self, width: int = 1600, height: int = 1000,
                 num_blobs: int = 6):
        import pygame
        if not pygame.get_init():
            pygame.init()
        self._pygame = pygame
        self._width = width
        self._height = height
        self._surface = pygame.Surface((width, height))
        self._num_blobs = num_blobs
        self._cached_pixmap: Optional[QPixmap] = None
        self._render()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _render(self):
        """渲染一次静态光斑壁纸。"""
        pg = self._pygame
        # 底色（淡蓝绿基调，与主题色一致）
        self._surface.fill((230, 240, 242))

        # 蓝绿渐变柔和色板（与 brand_gradient 同色系，偏淡）
        palette = [
            (140, 200, 230),  # 淡天蓝
            (130, 210, 215),  # 淡青蓝
            (140, 225, 200),  # 淡青绿
            (160, 230, 195),  # 淡薄荷绿
            (175, 235, 200),  # 淡草绿
            (200, 240, 215),  # 浅翡翠
        ]

        # 生成随机但稳定的光斑位置
        rng = random.Random(42)  # 固定种子保证可复现
        for i in range(self._num_blobs):
            x = rng.uniform(self._width * 0.1, self._width * 0.9)
            y = rng.uniform(self._height * 0.1, self._height * 0.9)
            radius = rng.uniform(150, 280)
            color = palette[i % len(palette)]
            self._draw_blob(x, y, radius, color)

        # 转 QPixmap 缓存
        self._cached_pixmap = self._surface_to_pixmap()

    def _draw_blob(self, x, y, radius, color):
        """绘制径向渐变光斑。"""
        pg = self._pygame
        x, y = int(x), int(y)
        steps = 14
        for i in range(steps, 0, -1):
            r = int(radius * i / steps)
            if r <= 0:
                continue
            t = i / steps
            alpha = int(95 * (1 - t) ** 1.5)
            if alpha <= 0:
                continue
            blob_surf = pg.Surface((r * 2, r * 2), pg.SRCALPHA)
            pg.draw.circle(blob_surf, (*color, alpha), (r, r), r)
            self._surface.blit(blob_surf, (x - r, y - r),
                               special_flags=pg.BLEND_ALPHA_SDL2)

    def _surface_to_pixmap(self) -> QPixmap:
        """pygame Surface 转 QPixmap。"""
        pg = self._pygame
        try:
            arr = pg.surfarray.array3d(self._surface)  # (W, H, 3)
            # 转 (H, W, 3)
            arr = arr.transpose(1, 0, 2).copy()
            h, w = arr.shape[0], arr.shape[1]
            img = QImage(arr.tobytes(), w, h, w * 3,
                         QImage.Format_RGB888).copy()
            return QPixmap.fromImage(img)
        except Exception:
            return QPixmap()

    def get_pixmap(self) -> QPixmap:
        """获取缓存的壁纸 QPixmap。"""
        if self._cached_pixmap is None or self._cached_pixmap.isNull():
            self._render()
        return self._cached_pixmap if self._cached_pixmap else QPixmap()

    def rerender(self):
        """重新渲染（窗口尺寸变化时调用）。"""
        self._render()


# ============================================================
#  LIQUID GLASS FRAME（半透明容器 — 透出原生模糊）
# ============================================================
class LiquidGlassFrame(QFrame):
    """苹果 Liquid Glass 容器 — 半透明背景透出原生 Acrylic 模糊。

    设计原理：
      - Windows 原生 Acrylic 已对整个窗口背景做模糊（GPU 加速，零 CPU）
      - 本容器仅用半透明背景 + 多层高光边框，让原生模糊"透出来"
      - 无任何模糊计算，性能极佳

    多层结构（Apple Liquid Glass 规范）：
      Layer 1: 半透明背景（透出原生模糊）
      Layer 2: tint (半透明叠加色)
      Layer 3: luminosity (顶部高光带)
      Layer 4: inset highlight (内边缘高光)
      Layer 5: edge refraction (135deg 渐变边框)
      Layer 6: 底部微反光（鸿蒙7立体景深）
    """

    def __init__(self, parent=None, radius: Optional[int] = None):
        super().__init__(parent)
        # Default radius sourced from design_tokens (radius.xl = 24).
        if radius is None:
            try:
                from design_tokens import tokens
                radius = int(tokens().radius.xl)
            except Exception:
                radius = 24
        self._radius = radius
        self._blur_radius = 18.0  # 保留 API 兼容（实际模糊由原生提供）
        # tint/luminosity keep original alpha values (design_tokens
        # `glass_highlight` differs; original alphas preserved for visual
        # parity with the legacy Liquid Glass paint layers).
        self._tint = QColor(255, 255, 255, 38)
        self._luminosity = QColor(255, 255, 255, 26)
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, True)
        # 透明背景，让原生模糊透出来
        self.setStyleSheet("QFrame { background: transparent; border: none; }")

    def invalidate_cache(self):
        """兼容 API（无操作，因无缓存）。"""
        pass

    def update_theme(self, theme_name):
        """主题切换。

        tint/luminosity retain their original alpha values — the new
        `design_tokens.glass_highlight` uses different alphas that would
        alter the visual feel of the multi-layer glass paint.
        """
        if theme_name == 'light':
            self._tint = QColor(255, 255, 255, 38)
            self._luminosity = QColor(255, 255, 255, 26)
        else:
            self._tint = QColor(40, 40, 45, 60)
            self._luminosity = QColor(255, 255, 255, 15)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._radius

        # 裁剪到圆角矩形
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.setClipPath(path)

        # Layer 1: 半透明背景（透出原生 Acrylic 模糊）
        # 不绘制底图，让窗口背景的原生模糊直接透出来
        p.fillRect(r, self._tint)

        # Layer 3: luminosity（顶部高光带）
        lum_grad = QLinearGradient(0, 0, 0, r.height())
        lum_top = QColor(self._luminosity)
        lum_top.setAlpha(min(255, self._luminosity.alpha() + 20))
        lum_bot = QColor(self._luminosity)
        lum_bot.setAlpha(0)
        lum_grad.setColorAt(0, lum_top)
        lum_grad.setColorAt(0.4, self._luminosity)
        lum_grad.setColorAt(1, lum_bot)
        p.fillRect(r, lum_grad)

        # Layer 4: inset highlight（内边缘高光 - 苹果规范核心）
        highlight = QColor(255, 255, 255, 180 if _is_light_theme() else 60)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(highlight, 1.2))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)

        # Layer 5: edge refraction（135deg 渐变边框 - 边缘折射）
        edge_grad = QLinearGradient(r.topLeft(), r.bottomRight())
        edge_top = QColor(255, 255, 255, 100 if _is_light_theme() else 40)
        edge_bot = QColor(255, 255, 255, 0)
        edge_grad.setColorAt(0, edge_top)
        edge_grad.setColorAt(0.5, edge_bot)
        edge_grad.setColorAt(1, QColor(255, 255, 255, 30 if _is_light_theme() else 15))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QBrush(edge_grad), 1.0))
        p.drawRoundedRect(r, radius, radius)

        # Layer 6: 底部微反光（鸿蒙7立体景深）
        bottom_grad = QLinearGradient(0, r.height() * 0.7, 0, r.height())
        _, accent, _, _ = _theme_colors()
        bc = QColor(accent)
        bc.setAlpha(20)
        bottom_grad.setColorAt(0, QColor(0, 0, 0, 0))
        bottom_grad.setColorAt(1, bc)
        p.fillRect(r, bottom_grad)


# ============================================================
#  ACRYLIC CONTAINER（兼容别名 — 指向 LiquidGlassFrame）
# ============================================================
class AcrylicContainer(LiquidGlassFrame):
    """AcrylicContainer 兼容别名（指向 LiquidGlassFrame）。

    保留旧 API 兼容：ModeCard 等继承此类。
    实际实现与 LiquidGlassFrame 相同（半透明透出原生模糊）。
    """

    def __init__(self, parent=None, radius: int = 20,
                 blur_radius: float = 16.0,
                 tint: Optional[QColor] = None,
                 luminosity: Optional[QColor] = None,
                 noise_opacity: float = 0.03):
        super().__init__(parent=parent, radius=radius)
        if tint is not None:
            self._tint = tint
        if luminosity is not None:
            self._luminosity = luminosity


# 兼容旧 API
AcrylicBlurEngine = type('AcrylicBlurEngine', (), {
    'grab_fluid_region': staticmethod(lambda w, b: None),
    'blur_image': staticmethod(lambda img, r=16, b=0.92: img),
})


# ============================================================
#  HARMONY LIGHT BUTTON（鸿蒙7 沉浸光感按钮）
# ============================================================
class HarmonyLightButton(QPushButton):
    """鸿蒙7 沉浸光感按钮 — 柔光渐变 + 流光动画 + 内发光。

    设计要点（基于 HarmonyOS 7 API 26 沉浸光感规范）：
      1. linearGradient 柔光渐变背景
      2. 流光动画（QTimer 60fps，沿按钮边缘扫光）
      3. 内发光（QPainter inset highlight）
      4. 立体景深（多层 shadow）
      5. hover 时增强光感
    """

    def __init__(self, text: str = "", parent=None,
                 accent: Optional[QColor] = None,
                 radius: int = 24):
        super().__init__(text, parent)
        self._radius = radius
        self._accent = accent or QColor(63, 169, 196)  # 蓝绿色（与主题一致）
        self._t = 0.0
        self._hover_progress = 0.0
        self._is_primary = False
        self._animating = False  # 仅在悬停或过渡期间运行动画

        # 流光动画定时器 — 50ms(20fps) 始终保持流光，不必 hover 才动画
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)  # ~20fps，兼顾流畅与性能

        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: white;
                font-weight: 600;
            }
        """)

    def set_primary(self, primary: bool = True):
        self._is_primary = primary
        self.update()

    def set_accent(self, color: QColor):
        self._accent = color
        self.update()

    def _get_brand_gradient(self) -> Tuple[QColor, QColor, QColor]:
        """Return the 3-stop brand gradient from design_tokens.

        Used by `_paint_primary` for the primary button state. Falls back
        to a gradient derived from `self._accent` if design_tokens is
        unavailable (keeps the button usable in standalone test mode).
        """
        try:
            from design_tokens import brand_gradient_qcolor_tuple
            return brand_gradient_qcolor_tuple()
        except Exception:
            # Fallback: derive a 3-stop gradient from the accent color.
            c1 = self._accent.lighter(115)
            c2 = QColor(self._accent)
            c3 = self._accent.darker(108)
            return (c1, c2, c3)

    def _tick(self):
        # 按钮不可见时跳过动画（省电）
        if not self.isVisible():
            return
        self._t += 0.05
        target = 1.0 if self.underMouse() else 0.0
        self._hover_progress += (target - self._hover_progress) * 0.18
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._radius

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.setClipPath(path)

        if self._is_primary:
            self._paint_primary(p, r, radius)
        else:
            self._paint_secondary(p, r, radius)

        # 流光效果（边缘扫光）
        self._paint_flowing_light(p, r, radius)

        # 内边缘高光
        highlight = QColor(255, 255, 255, int(140 + 60 * self._hover_progress))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(highlight, 1.0))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)

        # 顶部强高光带
        top_grad = QLinearGradient(0, 0, 0, r.height() * 0.4)
        top_grad.setColorAt(0, QColor(255, 255, 255, int(80 + 40 * self._hover_progress)))
        top_grad.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(r.x(), r.y(), r.width(), r.height() * 0.4), top_grad)

        # 绘制文字
        p.setPen(QColor(255, 255, 255) if self._is_primary else
                 QColor(30, 30, 35) if _is_light_theme() else QColor(245, 245, 247))
        font = QFont("HarmonyOS Sans", 10)
        font.setWeight(QFont.DemiBold)
        p.setFont(font)
        p.drawText(r, Qt.AlignCenter, self.text())

    def _paint_primary(self, p: QPainter, r: QRectF, radius: float):
        # Brand gradient (Royal Indigo → Violet → Pink) for the primary
        # state. Falls back to an accent-derived gradient when
        # design_tokens is unavailable.
        c1, c2, c3 = self._get_brand_gradient()
        # Lighten c1 slightly on hover for the "lift" effect.
        hover_lift = int(15 * self._hover_progress)
        if hover_lift > 0:
            c1 = c1.lighter(100 + hover_lift)

        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0.0, c1)
        grad.setColorAt(0.5, c2)
        grad.setColorAt(1.0, c3)
        p.fillRect(r, grad)

        # Glow on hover — use the middle gradient stop as the glow color.
        if self._hover_progress > 0.01:
            glow = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.7)
            gc = QColor(c2)
            gc.setAlpha(int(100 * self._hover_progress))
            glow.setColorAt(0, gc)
            glow.setColorAt(1, QColor(c2.red(), c2.green(), c2.blue(), 0))
            p.fillRect(r, glow)

    def _paint_secondary(self, p: QPainter, r: QRectF, radius: float):
        if _is_light_theme():
            base = QColor(255, 255, 255, int(180 + 40 * self._hover_progress))
            hover_tint = QColor(self._accent.red(), self._accent.green(),
                                self._accent.blue(), int(20 * self._hover_progress))
        else:
            base = QColor(50, 50, 55, int(180 + 40 * self._hover_progress))
            hover_tint = QColor(self._accent.red(), self._accent.green(),
                                self._accent.blue(), int(30 * self._hover_progress))

        grad = QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0, base.lighter(105))
        grad.setColorAt(1, base)
        p.fillRect(r, grad)

        if self._hover_progress > 0.01:
            p.fillRect(r, hover_tint)

    def _paint_flowing_light(self, p: QPainter, r: QRectF, radius: float):
        perimeter = 2 * (r.width() + r.height())
        pos = (self._t * 0.3) % 1.0
        angle = pos * 360

        cg = QConicalGradient(r.center(), angle)
        c1 = QColor(255, 255, 255, 0)
        c2 = QColor(255, 255, 255, int(80 + 60 * self._hover_progress))
        c3 = QColor(255, 255, 255, 0)
        cg.setColorAt(0.0, c1)
        cg.setColorAt(0.08, c2)
        cg.setColorAt(0.16, c3)
        cg.setColorAt(1.0, c1)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QBrush(cg), 2.0))
        p.drawRoundedRect(r, radius, radius)


# ============================================================
#  CUSTOM TITLE BAR（无边框窗口自定义标题栏）
# ============================================================
class CustomTitleBar(QWidget):
    """无边框窗口的自定义标题栏。"""
    WINDOW_BTN_CLICKED = Signal(int)  # 0=min, 1=max, 2=close

    def __init__(self, parent: QWidget, title: str = "",
                 icon: Optional[QIcon] = None):
        super().__init__(parent)
        self._parent = parent
        self._pressing = False
        self._drag_offset = QPoint()
        self._title_text = title

        self.setFixedHeight(36)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        if icon is not None:
            self._icon_label = QLabel()
            self._icon_label.setFixedSize(20, 20)
            self._icon_label.setPixmap(icon.pixmap(20, 20))
            layout.addWidget(self._icon_label)
        else:
            self._icon_label = None

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {'#1D1D1F' if _is_light_theme() else '#F5F5F7'};
                font-size: 13px;
                font-weight: 500;
                background: transparent;
                border: none;
            }}
        """)
        layout.addWidget(self._title_label)
        layout.addStretch()

        self._btn_min = self._make_sys_btn("minimize", 0, is_icon=True)
        self._btn_max = self._make_sys_btn("maximize", 1, is_icon=True)
        self._btn_close = self._make_sys_btn("close", 2, is_close=True, is_icon=True)

        layout.addWidget(self._btn_min)
        layout.addWidget(self._btn_max)
        layout.addWidget(self._btn_close)

    def _make_sys_btn(self, text_or_icon: str, btn_id: int,
                      is_close: bool = False,
                      is_icon: bool = False) -> QPushButton:
        """Build a system button (min / max / close).

        When ``is_icon`` is True, ``text_or_icon`` is treated as an icon
        name from ``app_icons.ICONS`` and rendered as an SVG ``QIcon``
        (text/ASCII fallback is no longer used but the parameter name is
        kept for backward compatibility with subclass overrides).
        """
        btn = QPushButton()
        btn.setFixedSize(40, 28)
        btn.setCursor(QCursor(Qt.PointingHandCursor))

        if is_icon:
            # Stash metadata so _refresh_sys_btn_icons() can re-render
            # on theme change.
            btn._icon_name = text_or_icon
            btn._is_close = is_close
            self._set_sys_btn_icon(btn, text_or_icon, is_close)
            btn.setStyleSheet(self._sys_btn_qss(is_close))
        else:
            btn.setText(text_or_icon)
            btn.setStyleSheet(self._sys_btn_qss(is_close))

        btn.clicked.connect(lambda: self.WINDOW_BTN_CLICKED.emit(btn_id))
        return btn

    def _set_sys_btn_icon(self, btn: QPushButton, name: str,
                          is_close: bool = False):
        """Render the SVG icon and set it on the button.

        Color resolution: by default, ``app_icons.icon()`` picks up the
        current theme's ``text_primary`` color, which gives a dark icon on
        the light title bar and a light icon on the dark title bar. The
        close button keeps the same color even on its red hover background
        (Task 12 may refine this to swap to white on hover).
        """
        from app_icons import icon
        from design_tokens import get_current_theme_name
        theme = get_current_theme_name()
        ic = icon(name, size=14, theme_name=theme)
        btn.setIcon(ic)
        btn.setIconSize(QSize(14, 14))

    def _sys_btn_qss(self, is_close: bool) -> str:
        """Stylesheet for system buttons.

        Icon-only (no text padding) — the icon is rendered via
        ``setIcon()`` so QSS only handles the background hover states.
        """
        if is_close:
            return """
                QPushButton {
                    background: transparent; border: none;
                    border-radius: 6px;
                }
                QPushButton:hover { background: #FF3B30; }
                QPushButton:pressed { background: #C0241C; }
            """
        return """
            QPushButton {
                background: transparent; border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background: rgba(0, 0, 0, 0.08); }
            QPushButton:pressed { background: rgba(0, 0, 0, 0.15); }
        """

    def _refresh_sys_btn_icons(self):
        """Re-render all system button icons for the current theme.

        Called on theme switch (see ``update_theme``) so the SVG icons
        pick up the new ``text_primary`` color.
        """
        from app_icons import icon
        from design_tokens import get_current_theme_name
        theme = get_current_theme_name()
        for btn_attr in ('_btn_min', '_btn_max', '_btn_close'):
            btn = getattr(self, btn_attr, None)
            if btn is None:
                continue
            name = getattr(btn, '_icon_name', None)
            if not name:
                continue
            ic = icon(name, size=14, theme_name=theme)
            btn.setIcon(ic)

    def set_title(self, title: str):
        self._title_text = title
        self._title_label.setText(title)

    def update_theme(self, theme_name):
        color = '#1D1D1F' if theme_name == 'light' else '#F5F5F7'
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 13px;
                font-weight: 500;
                background: transparent;
                border: none;
            }}
        """)
        # Refresh SVG icons for system buttons so they pick up the new
        # theme's text_primary color.
        self._refresh_sys_btn_icons()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressing = True
            self._drag_offset = event.globalPosition().toPoint() - \
                self._parent.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._pressing and (event.buttons() & Qt.LeftButton):
            self._parent.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._pressing = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.WINDOW_BTN_CLICKED.emit(1)
            event.accept()


# ============================================================
#  FRAMELESS WINDOW HELPER
# ============================================================
def make_frameless(window: QMainWindow):
    """将 QMainWindow 设置为无边框窗口（保留不透明背景）。

    关键变更：不再设置 WA_TranslucentBackground。
      - 窗口背景保持不透明（实色壁纸底图，由 paintEvent 绘制）
      - 按钮 / 卡片用半透明背景透出底层壁纸
      - 不再依赖 BlurWindow 原生 Acrylic（避免按钮透出桌面而非壁纸）
    """
    window.setWindowFlags(Qt.FramelessWindowHint)


def install_title_bar(window: QMainWindow,
                      title: str = "",
                      icon: Optional[QIcon] = None,
                      on_btn_clicked=None) -> CustomTitleBar:
    """在 QMainWindow 的中央部件顶部插入自定义标题栏。"""
    central = window.centralWidget()
    if central is None:
        central = QWidget()
        window.setCentralWidget(central)

    layout = central.layout()
    if layout is None:
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    title_bar = CustomTitleBar(window, title=title, icon=icon)

    def _on_btn(btn_id: int):
        if on_btn_clicked is not None:
            on_btn_clicked(btn_id)
        _handle_window_btn(window, btn_id)

    title_bar.WINDOW_BTN_CLICKED.connect(_on_btn)
    layout.insertWidget(0, title_bar)
    window._custom_title_bar = title_bar
    return title_bar


def _handle_window_btn(window: QMainWindow, btn_id: int):
    if btn_id == 0:
        window.showMinimized()
    elif btn_id == 1:
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()
    elif btn_id == 2:
        window.close()


def enable_frameless_window(window: QMainWindow,
                            title: str = "",
                            icon: Optional[QIcon] = None) -> CustomTitleBar:
    """一键启用无边框窗口 + 标题栏（兼容旧 API）。"""
    make_frameless(window)
    return install_title_bar(window, title=title, icon=icon)


# ============================================================
#  EDGE GLOW WIDGET
# ============================================================
class EdgeGlowWidget(QWidget):
    """窗口边缘高光装饰。"""

    def __init__(self, parent=None, glow_width: int = 2):
        super().__init__(parent)
        self._glow_width = glow_width
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        top_color = QColor(255, 255, 255, 160 if _is_light_theme() else 50)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(top_color, 1.0))
        p.drawLine(r.topLeft(), r.topRight())

        side_color = QColor(255, 255, 255, 50 if _is_light_theme() else 20)
        p.setPen(QPen(side_color, 1.0))
        p.drawLine(r.bottomLeft(), r.bottomRight())
        p.drawLine(r.topLeft(), r.bottomLeft())
        p.drawLine(r.topRight(), r.bottomRight())
