#!/usr/bin/env python3
"""
Generate favicon assets from the Cloudista brand mark.

Outputs (written next to this script):
  favicon.ico          – 16×16, 32×32, 48×48 (multi-size, for browsers)
  favicon-32x32.png    – 32×32  PNG
  favicon-192x192.png  – 192×192 PNG  (Android / PWA)
  apple-touch-icon.png – 180×180 PNG  (iOS home screen)

Requirements: Pillow  (pip install Pillow)
"""

import math
from pathlib import Path
from PIL import Image, ImageDraw


# ---------------------------------------------------------------------------
# Gradient helpers
# ---------------------------------------------------------------------------

def _lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _gradient_bg(size: int) -> Image.Image:
    """
    Diagonal (top-left → bottom-right) gradient:
      #2563eb  →  #7c3aed
    """
    img = Image.new("RGBA", (size, size))
    src = (37,  99,  235, 255)   # #2563eb
    dst = (124,  58,  237, 255)  # #7c3aed
    for y in range(size):
        for x in range(size):
            t = (x + y) / max(1, 2 * (size - 1))
            img.putpixel((x, y), (
                _lerp(src[0], dst[0], t),
                _lerp(src[1], dst[1], t),
                _lerp(src[2], dst[2], t),
                255,
            ))
    return img


# ---------------------------------------------------------------------------
# Rounded-rect mask
# ---------------------------------------------------------------------------

def _round_mask(size: int, radius_frac: float = 0.22) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    r = max(1, round(size * radius_frac))
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=r, fill=255)
    return mask


# ---------------------------------------------------------------------------
# Cloud shape
# ---------------------------------------------------------------------------
# The SVG path M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z
# resolves to two circles (analysed analytically):
#   Large circle  – center (9, 12) in 24-unit SVG space, r = 8
#   Small circle  – center (18, 15) in 24-unit SVG space, r = 5
# The cloud silhouette = union of those two circles + a filled rectangle
# bridging them at the bottom.

def _draw_cloud(draw: ImageDraw.ImageDraw, work: int, pad_frac: float = 0.175) -> None:
    """Draw a white filled cloud onto `draw` for a `work × work` canvas."""
    pad = pad_frac * work
    S   = (work - 2 * pad) / 24.0   # pixels per SVG unit

    # Circle centres / radii in pixel space
    cx1, cy1, r1 = 9  * S + pad,  12 * S + pad,  8 * S   # large left bump
    cx2, cy2, r2 = 18 * S + pad,  15 * S + pad,  5 * S   # small right bump

    bottom = 20 * S + pad   # bottom edge of cloud in SVG (y = 20)

    W = (255, 255, 255, 255)

    # Two filled circles (the bumps)
    draw.ellipse([cx1 - r1, cy1 - r1, cx1 + r1, cy1 + r1], fill=W)
    draw.ellipse([cx2 - r2, cy2 - r2, cx2 + r2, cy2 + r2], fill=W)

    # Rectangle filling the body between the circles down to the base
    fill_left  = cx1 - r1 * 0.85
    fill_right = cx2 + r2 * 0.85
    fill_top   = min(cy1, cy2) - r2 * 0.1
    draw.rectangle([fill_left, fill_top, fill_right, bottom], fill=W)


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def make_icon(size: int) -> Image.Image:
    """Render one square icon at `size × size` pixels."""
    WORK = size * 4   # 4× supersampling for smooth edges

    # --- background gradient ---
    bg = _gradient_bg(WORK)

    # --- rounded corners ---
    bg.putalpha(_round_mask(WORK))

    # --- cloud overlay ---
    cloud_layer = Image.new("RGBA", (WORK, WORK), (0, 0, 0, 0))
    _draw_cloud(ImageDraw.Draw(cloud_layer), WORK)

    # --- composite ---
    result = Image.new("RGBA", (WORK, WORK), (0, 0, 0, 0))
    result.paste(bg, mask=bg.split()[3])
    result = Image.alpha_composite(result, cloud_layer)

    # --- downscale with high-quality resampling ---
    return result.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent

if __name__ == "__main__":
    sizes   = [16, 32, 48, 180, 192]
    icons   = {s: make_icon(s) for s in sizes}

    # favicon.ico  (multi-size)
    ico_path = HERE / "favicon.ico"
    icons[16].save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=[icons[32], icons[48]],
    )
    print(f"  ✓  {ico_path.name}")

    # PNG assets
    for fname, sz in [
        ("favicon-32x32.png",    32),
        ("favicon-192x192.png", 192),
        ("apple-touch-icon.png", 180),
    ]:
        p = HERE / fname
        icons[sz].save(p, format="PNG")
        print(f"  ✓  {p.name}")

    print("\nDone — all favicon assets written.")
