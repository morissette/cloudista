#!/usr/bin/env python3
"""
make_og_image.py — generates og-image.png (1200×630) for Cloudista.

Requires: pip install Pillow
Run:      python3 make_og_image.py
Output:   og-image.png in the current directory
"""

from PIL import Image, ImageDraw, ImageFont
import sys

WIDTH, HEIGHT = 1200, 630

# ── Brand colours ────────────────────────────────────────────────────────────
BLUE   = (37,  99, 235)   # #2563eb
PURPLE = (124, 58, 237)   # #7c3aed
WHITE  = (255, 255, 255)
WHITE_DIM = (255, 255, 255, 180)   # semi-transparent for tagline

# ── Gradient background (blue → purple, diagonal) ────────────────────────────
def make_gradient(width, height, colour_a, colour_b):
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for x in range(width):
        for y in range(height):
            t = (x / width + y / height) / 2
            r = int(colour_a[0] + (colour_b[0] - colour_a[0]) * t)
            g = int(colour_a[1] + (colour_b[1] - colour_a[1]) * t)
            b = int(colour_a[2] + (colour_b[2] - colour_a[2]) * t)
            draw.point((x, y), fill=(r, g, b))
    return img

# ── Cloud icon (SVG path approximated as a polygon fill) ─────────────────────
def draw_cloud(draw, cx, cy, size):
    """Draw a simplified cloud shape centred at (cx, cy) at the given scale."""
    s = size / 24  # scale factor (path is in 24×24 space)

    # Approximate the cloud path with an ellipse + circles
    # Main body
    body_w, body_h = int(18 * s), int(10 * s)
    draw.ellipse([cx - body_w // 2, cy - body_h // 2,
                  cx + body_w // 2, cy + body_h // 2],
                 fill=(255, 255, 255, 200))

    # Top-left bump
    bump_r = int(6 * s)
    draw.ellipse([cx - int(5 * s) - bump_r, cy - int(4 * s) - bump_r,
                  cx - int(5 * s) + bump_r, cy - int(4 * s) + bump_r],
                 fill=(255, 255, 255, 200))

    # Top-right bump
    bump_r2 = int(5 * s)
    draw.ellipse([cx + int(2 * s) - bump_r2, cy - int(5 * s) - bump_r2,
                  cx + int(2 * s) + bump_r2, cy - int(5 * s) + bump_r2],
                 fill=(255, 255, 255, 200))

# ── Helper: try to load a system font, fall back to default ──────────────────
def load_font(size, bold=False):
    candidates_bold = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    candidates_regular = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    candidates = candidates_bold if bold else candidates_regular
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()

# ── Main ──────────────────────────────────────────────────────────────────────
def main(out_path="og-image.png"):
    # 1. Gradient background
    img = make_gradient(WIDTH, HEIGHT, BLUE, PURPLE)

    # 2. Subtle dot-grid overlay
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    dot_spacing = 28
    for gx in range(0, WIDTH, dot_spacing):
        for gy in range(0, HEIGHT, dot_spacing):
            od.ellipse([gx - 1, gy - 1, gx + 1, gy + 1],
                       fill=(255, 255, 255, 25))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img, "RGBA")

    # 3. Cloud icon — centred-left, large
    cloud_cx = 120
    cloud_cy = HEIGHT // 2 - 20
    cloud_size = 120
    draw_cloud(draw, cloud_cx, cloud_cy, cloud_size)

    # 4. "Cloudista" wordmark
    font_title = load_font(96, bold=True)
    title_text = "Cloudista"
    title_x, title_y = 240, HEIGHT // 2 - 90
    draw.text((title_x, title_y), title_text, font=font_title, fill=WHITE)

    # 5. Tagline below the wordmark
    font_tagline = load_font(38)
    tagline_text = "All Things Cloud"
    tagline_x, tagline_y = 244, title_y + 110
    draw.text((tagline_x, tagline_y), tagline_text,
              font=font_tagline, fill=(255, 255, 255, 190))

    # 6. "Coming April 2026" pill badge — bottom-right
    badge_text = "Coming April 2026"
    font_badge = load_font(28, bold=True)
    bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw = bbox[2] - bbox[0]
    bh = bbox[3] - bbox[1]
    pad_x, pad_y = 22, 12
    badge_right, badge_bottom = WIDTH - 48, HEIGHT - 48
    badge_left = badge_right - bw - pad_x * 2
    badge_top  = badge_bottom - bh - pad_y * 2
    # Pill background (semi-transparent white)
    draw.rounded_rectangle(
        [badge_left, badge_top, badge_right, badge_bottom],
        radius=30,
        fill=(255, 255, 255, 45),
        outline=(255, 255, 255, 80),
        width=1,
    )
    draw.text((badge_left + pad_x, badge_top + pad_y), badge_text,
              font=font_badge, fill=WHITE)

    img.save(out_path, "PNG", optimize=True)
    print(f"Saved: {out_path}  ({WIDTH}×{HEIGHT})")

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "og-image.png"
    main(out)
