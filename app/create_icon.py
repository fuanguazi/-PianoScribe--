"""Generate PianoScribe application icon: staff + piano + wordmark."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QLinearGradient, QRadialGradient,
    QPen, QBrush, QFont, QPainterPath, QPolygonF,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

SIZE = 512  # 高分辨率，缩放成各档尺寸
pm = QPixmap(SIZE, SIZE)
pm.fill(Qt.transparent)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing)
p.setRenderHint(QPainter.TextAntialiasing)

# --- 背景圆角 + 渐变 ---
path = QPainterPath()
path.addRoundedRect(0, 0, SIZE, SIZE, 80, 80)
p.setClipPath(path)

bg = QLinearGradient(0, 0, SIZE, SIZE)
bg.setColorAt(0, QColor('#0a1e2a'))
bg.setColorAt(0.5, QColor('#0d2e30'))
bg.setColorAt(1, QColor('#0a1e1a'))
p.fillRect(0, 0, SIZE, SIZE, bg)

# 顶部光晕（青绿色，匹配主界面 brand_gradient）
glow = QRadialGradient(SIZE * 0.5, SIZE * 0.35, 280)
glow.setColorAt(0, QColor(80, 200, 180, 60))
glow.setColorAt(1, QColor(0, 0, 0, 0))
p.fillRect(0, 0, SIZE, SIZE, glow)


# --- 顶部：五线谱 + 音符 ---
staff_top = 60
staff_bot = 130
line_spacing = (staff_bot - staff_top) / 4
staff_left = 60
staff_right = SIZE - 60

staff_pen = QPen(QColor(180, 195, 235, 200), 2)
p.setPen(staff_pen)
for i in range(5):
    y = staff_top + i * line_spacing
    p.drawLine(int(staff_left), int(y), int(staff_right), int(y))

# 高音谱号风格的渐变线 + 几个音符（用主界面 brand_gradient 配色）
accent_grad = QLinearGradient(staff_left, 0, staff_right, 0)
accent_grad.setColorAt(0, QColor(63, 149, 192, 0))    # #3F95C0 透明
accent_grad.setColorAt(0.5, QColor(63, 176, 160, 220)) # #3FB0A0
accent_grad.setColorAt(1, QColor(82, 189, 142, 0))     # #52BD8E 透明
p.setPen(QPen(QBrush(accent_grad), 3))
p.drawLine(int(staff_left), int(staff_top - 6),
           int(staff_right), int(staff_top - 6))

# 4 个音符（翠绿色，匹配主界面强调色）
note_color = QColor('#52BD8E')
stem_pen = QPen(note_color, 3)
p.setPen(stem_pen)
p.setBrush(QBrush(note_color))
note_xs = [110, 180, 260, 340]
note_ys = [staff_top + line_spacing * 1.5,
          staff_top + line_spacing * 0.5,
          staff_top + line_spacing * 2.5,
          staff_top + line_spacing * 1.0]
for nx, ny in zip(note_xs, note_ys):
    p.drawEllipse(QPointF(nx, ny), 10, 7)
    # 符干向上
    p.drawLine(QPointF(nx + 8, ny - 2), QPointF(nx + 8, ny - 36))


# --- 中部：钢琴键盘 ---
key_top = 175
key_bot = 320
key_h = key_bot - key_top
num_white = 14
white_w = (SIZE - 120) / num_white
start_x = 60

# 白键
white_grad = QLinearGradient(0, key_top, 0, key_bot)
white_grad.setColorAt(0, QColor(235, 238, 250))
white_grad.setColorAt(1, QColor(195, 200, 220))
p.setPen(QPen(QColor(140, 150, 175, 100), 1))
p.setBrush(QBrush(white_grad))
for i in range(num_white):
    x = start_x + i * white_w
    p.drawRoundedRect(QRectF(x, key_top, white_w - 1.5, key_h), 3, 3)

# 黑键（按自然音阶排列：2-3-2-3）
black_grad = QLinearGradient(0, key_top, 0, key_top + key_h * 0.62)
black_grad.setColorAt(0, QColor(45, 48, 70))
black_grad.setColorAt(1, QColor(20, 22, 38))
p.setPen(Qt.NoPen)
p.setBrush(QBrush(black_grad))
black_pattern = [1, 1, 0, 1, 1, 1, 0]  # 7-key period, 1=黑键
bw = white_w * 0.6
bh = key_h * 0.62
for i in range(num_white - 1):
    if black_pattern[i % 7]:
        x = start_x + (i + 1) * white_w - bw / 2
        p.drawRoundedRect(QRectF(x, key_top, bw, bh), 2, 2)

# 键盘顶部高光线（绿蓝渐变）
top_grad = QLinearGradient(start_x, 0, start_x + num_white * white_w, 0)
top_grad.setColorAt(0, QColor(63, 149, 192, 0))    # #3F95C0 透明
top_grad.setColorAt(0.5, QColor(63, 176, 160, 220)) # #3FB0A0
top_grad.setColorAt(1, QColor(82, 189, 142, 0))     # #52BD8E 透明
p.setPen(QPen(QBrush(top_grad), 3))
p.drawLine(int(start_x), int(key_top - 1),
          int(start_x + num_white * white_w), int(key_top - 1))


# --- 底部：PianoScribe 字样 ---
title_font = QFont("Segoe UI", 44, QFont.Bold)
p.setFont(title_font)
title_grad = QLinearGradient(SIZE * 0.2, 0, SIZE * 0.8, 0)
title_grad.setColorAt(0, QColor('#3F95C0'))   # 深蓝
title_grad.setColorAt(0.5, QColor('#3FB0A0')) # 青绿
title_grad.setColorAt(1, QColor('#52BD8E'))   # 翠绿
p.setPen(QPen(QBrush(title_grad), 1))
p.drawText(QRectF(0, 340, SIZE, 90), Qt.AlignCenter, "PianoScribe")

# 一行细标语
sub_font = QFont("Segoe UI", 14, QFont.Light)
p.setFont(sub_font)
p.setPen(QPen(QColor(160, 170, 200, 200), 1))
p.drawText(QRectF(0, 430, SIZE, 30), Qt.AlignCenter, "AI Piano Transcription")

p.end()

# --- 保存 PNG / ICO ---
out_dir = os.path.dirname(os.path.abspath(__file__))
png_path = os.path.join(out_dir, 'pianoscribe_icon.png')
pm.save(png_path, 'PNG')
print(f'PNG saved: {png_path}')

ico_path = os.path.join(out_dir, 'pianoscribe_icon.ico')
sizes = [16, 24, 32, 48, 64, 128, 256, 512]
images = [pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation) for s in sizes]
first = images[0].toImage()
first.save(ico_path, 'ICO', quality=100)
print(f'ICO saved: {ico_path}')

# 同时生成 splash 版本（去掉 Pianoscribe 文字）
splash = QPixmap(SIZE, SIZE)
splash.fill(Qt.transparent)
sp = QPainter(splash)
sp.setRenderHint(QPainter.Antialiasing)
sp.setRenderHint(QPainter.TextAntialiasing)
splash_path = QPainterPath()
splash_path.addRoundedRect(0, 0, SIZE, SIZE, 80, 80)
sp.setClipPath(splash_path)
sp.fillRect(0, 0, SIZE, SIZE, bg)
sp.fillRect(0, 0, SIZE, SIZE, glow)
# 五线谱
sp.setPen(staff_pen)
for i in range(5):
    y = staff_top + i * line_spacing
    sp.drawLine(int(staff_left), int(y), int(staff_right), int(y))
sp.setPen(QPen(QBrush(accent_grad), 3))
sp.drawLine(int(staff_left), int(staff_top - 6),
            int(staff_right), int(staff_top - 6))
for nx, ny in zip(note_xs, note_ys):
    sp.setBrush(QBrush(note_color))
    sp.setPen(QPen(note_color, 3))
    sp.drawEllipse(QPointF(nx, ny), 10, 7)
    sp.drawLine(QPointF(nx + 8, ny - 2), QPointF(nx + 8, ny - 36))
# 钢琴（垂直居中到 splash）
splash_key_top = 200
white_grad2 = QLinearGradient(0, splash_key_top, 0, splash_key_top + key_h)
white_grad2.setColorAt(0, QColor(235, 238, 250))
white_grad2.setColorAt(1, QColor(195, 200, 220))
sp.setPen(QPen(QColor(140, 150, 175, 100), 1))
sp.setBrush(QBrush(white_grad2))
for i in range(num_white):
    x = start_x + i * white_w
    sp.drawRoundedRect(QRectF(x, splash_key_top, white_w - 1.5, key_h), 3, 3)
sp.setPen(Qt.NoPen)
sp.setBrush(QBrush(black_grad))
for i in range(num_white - 1):
    if black_pattern[i % 7]:
        x = start_x + (i + 1) * white_w - bw / 2
        sp.drawRoundedRect(QRectF(x, splash_key_top, bw, bh), 2, 2)
sp.setPen(QPen(QBrush(top_grad), 3))
sp.drawLine(int(start_x), int(splash_key_top - 1),
            int(start_x + num_white * white_w), int(splash_key_top - 1))
sp.end()
splash_path_png = os.path.join(out_dir, 'pianoscribe_splash_icon.png')
splash.save(splash_path_png, 'PNG')
print(f'Splash saved: {splash_path_png}')
