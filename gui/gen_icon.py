#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 dircompare GUI 图标 gui/icon.ico（多尺寸，纯 Pillow 绘制）。"""
import os
from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 底板：圆角方块 + 垂直微渐变（手工两段）
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=56, fill=(18, 26, 44, 255))
d.rounded_rectangle([8, 8, S - 8, 118], radius=56, fill=(24, 38, 66, 255))
# 底板内描边
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=56, outline=(64, 108, 190, 255), width=4)

def page(x, y, w, h, tone=255):
    """白色圆角“文件页”：底色 + 3 行内容线。"""
    d.rounded_rectangle([x, y, x + w, y + h], radius=20, fill=(tone, tone, tone, 255))
    lx, ly = x + 34, y + 40
    for i in range(3):
        d.rounded_rectangle([lx, ly + i * 40, lx + (w - 76 if i < 2 else w - 140), ly + i * 40 + 14],
                            radius=7, fill=(122, 138, 168, 255))

# 后页（B）上移、微灰，前页（A）下移白色 —— 层叠文件语义
page(52, 56, 152, 176, tone=226)   # 后页
page(70, 88, 152, 176, tone=255)   # 前页

# 中央 ⇄ 语义：用一对三角箭头表示“双向比对”，青色
def arrow(cx, cy, dx, color, w=26):
    hw = w / 2
    d.polygon([(cx, cy - 14), (cx + dx * 62, cy - 14),
               (cx + dx * 62, cy - 34), (cx + dx * 96, cy + 4),
               (cx + dx * 62, cy + 42), (cx + dx * 62, cy + 22),
               (cx, cy + 22)], fill=color)

arrow(66, 172, +1, (80, 200, 255, 255))
arrow(192, 92, -1, (80, 200, 255, 255))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("saved", out)
