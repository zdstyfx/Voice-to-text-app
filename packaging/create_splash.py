"""生成 PyInstaller splash screen 图片（splash.png）。

在 build.bat / build.sh 里自动调用，也可手动运行：
    python create_splash.py

输出：packaging/splash.png  (640 × 280 px)
"""

import os
import sys
from pathlib import Path

OUT = Path(__file__).parent / "splash.png"
W, H = 640, 280

BG     = (22,  22,  19)   # #161613
ORANGE = (255, 92,   0)   # #FF5C00
WHITE  = (240, 239, 234)  # #F0EFEA
GRAY   = (107, 107, 101)  # #6B6B65


def _find_font(size: int):
    """按优先级找系统字体，都找不到就用 PIL 默认字体。"""
    from PIL import ImageFont

    candidates: list[str] = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        candidates = [
            os.path.join(windir, "Fonts", "msyh.ttc"),    # 微软雅黑（中文）
            os.path.join(windir, "Fonts", "msyhbd.ttc"),  # 微软雅黑 Bold
            os.path.join(windir, "Fonts", "Arial.ttf"),
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
        ]

    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass

    # 实在找不到就用内置位图字体（英文，无 AA，但够用）
    return ImageFont.load_default()


def generate() -> None:
    from PIL import Image, ImageDraw

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ── 顶部橙色线条 ──────────────────────────────────
    draw.rectangle([0, 0, W, 5], fill=ORANGE)

    # ── 应用名称 ──────────────────────────────────────
    font_title = _find_font(52)
    draw.text(
        (W // 2, H // 2 - 16),
        "Shokz Type",
        fill=WHITE,
        font=font_title,
        anchor="mm",
    )

    # ── 副标题 ────────────────────────────────────────
    font_sub = _find_font(18)
    draw.text(
        (W // 2, H // 2 + 40),
        "正在启动，请稍候…",
        fill=GRAY,
        font=font_sub,
        anchor="mm",
    )

    # ── 底部橙色线条 ──────────────────────────────────
    draw.rectangle([0, H - 5, W, H], fill=ORANGE)

    img.save(str(OUT))
    print(f"  splash.png 已生成: {OUT}  ({W}x{H})")


if __name__ == "__main__":
    generate()
