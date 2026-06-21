"""Generate PianoScribe application icon from splash screen."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QPixmap, QPainter, QColor, QLinearGradient, QRadialGradient, QPen, QBrush, QFont
from PySide6.QtCore import Qt, QRectF
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

size = 256
pm = QPixmap(size, size)
pm.fill(Qt.transparent)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing)
p.setRenderHint(QPainter.TextAntialiasing)

# Background - rounded rect with gradient
from PySide6.QtGui import QPainterPath
path = QPainterPath()
path.addRoundedRect(0, 0, size, size, 40, 40)
p.setClipPath(path)

bg = QLinearGradient(0, 0, size, size)
bg.setColorAt(0, QColor('#0a0e27'))
bg.setColorAt(0.5, QColor('#1a1a3e'))
bg.setColorAt(1, QColor('#0d1130'))
p.fillRect(0, 0, size, size, bg)

# Glow
glow = QRadialGradient(size * 0.5, size * 0.6, 140)
glow.setColorAt(0, QColor(80, 120, 255, 50))
glow.setColorAt(1, QColor(0, 0, 0, 0))
p.fillRect(0, 0, size, size, glow)

# Mini piano keys at bottom
key_y = size - 70
key_h = 60
white_w = 22
num_white = 10
start_x = (size - num_white * white_w) / 2

for i in range(num_white):
    x = start_x + i * white_w
    grad = QLinearGradient(x, key_y, x, key_y + key_h)
    grad.setColorAt(0, QColor(230, 230, 245))
    grad.setColorAt(1, QColor(190, 195, 215))
    p.setPen(QPen(QColor(150, 155, 175), 0.5))
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(int(x), key_y, white_w - 1, key_h, 1, 1)

black_pattern = [1, 1, 0, 1, 1, 1, 0]
for i in range(num_white - 1):
    if black_pattern[i % 7]:
        x = start_x + (i + 1) * white_w - 7
        grad = QLinearGradient(x, key_y, x, key_y + key_h * 0.6)
        grad.setColorAt(0, QColor(40, 40, 60))
        grad.setColorAt(1, QColor(20, 20, 35))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(int(x), key_y, 14, int(key_h * 0.6), 1, 1)

# Accent line
accent_grad = QLinearGradient(start_x, 0, start_x + num_white * white_w, 0)
accent_grad.setColorAt(0, QColor(80, 120, 255, 0))
accent_grad.setColorAt(0.5, QColor(100, 160, 255, 200))
accent_grad.setColorAt(1, QColor(160, 100, 255, 0))
p.setPen(QPen(QBrush(accent_grad), 2))
p.drawLine(int(start_x), key_y - 1, int(start_x + num_white * white_w), key_y - 1)

# "PS" text
title_font = QFont("Segoe UI", 72, QFont.Bold)
p.setFont(title_font)
title_grad = QLinearGradient(size * 0.15, 0, size * 0.85, 0)
title_grad.setColorAt(0, QColor('#6ea8fe'))
title_grad.setColorAt(0.5, QColor('#c4b5fd'))
title_grad.setColorAt(1, QColor('#818cf8'))
p.setPen(QPen(QBrush(title_grad), 1))
p.drawText(QRectF(0, 10, size, 120), Qt.AlignCenter, "PS")

p.end()

# Save as ICO
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pianoscribe_icon.png')
pm.save(out_path, 'PNG')
print(f'Icon saved to {out_path}')

# Also save as ICO with multiple sizes
ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pianoscribe_icon.ico')
sizes = [16, 24, 32, 48, 64, 128, 256]
images = []
for s in sizes:
    scaled = pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    images.append(scaled)

# Save first image as ICO
from PySide6.QtGui import QImage
first = images[0].toImage()
first.save(ico_path, 'ICO', quality=100)
print(f'ICO saved to {ico_path}')
