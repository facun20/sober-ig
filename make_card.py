"""Quote-card renderer for Sober Thoughts IG pipeline.
Input: quote text + wallpaper path -> 4:5 (1080x1350) PNG with overlaid quote.
Reusable: import render_card() or run with args.
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
_FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_QUOTE = os.path.join(_FD, "Newsreader.ttf")          # variable
FONT_ITALIC_F = os.path.join(_FD, "Newsreader-Italic.ttf")  # variable
FONT_HANDLE = os.path.join(_FD, "Manrope.ttf")            # variable
HANDLE = "@soberthoughts.app"
MAX_TEXT_W = 900          # text wrap width
TARGET_LINES = (3, 5)     # aim for this many lines when sizing


def _quote_font(size, weight=600, opsz=72):
    f = ImageFont.truetype(FONT_QUOTE, size)
    try:
        f.set_variation_by_axes([opsz, weight])
    except Exception:
        pass
    return f


def _italic_font(size, opsz=36):
    f = ImageFont.truetype(FONT_ITALIC_F, size)
    try:
        f.set_variation_by_axes([opsz, 500])
    except Exception:
        pass
    return f


def _handle_font(size, weight=500):
    f = ImageFont.truetype(FONT_HANDLE, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def _crop_cover(img, w, h):
    """Center-crop + scale source to exactly cover w x h."""
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        nh = h; nw = int(h * src_ratio)
    else:
        nw = w; nh = int(w / src_ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2; top = (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit_font(draw, text, max_w, max_lines=5):
    """Pick largest font size where text wraps within max_w and <= max_lines."""
    for size in range(66, 33, -2):
        font = _quote_font(size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines:
            return font, lines, size
    font = _quote_font(34)
    return font, _wrap(draw, text, font, max_w), 34


def _draw_centered(draw, lines, font, cx, top_y, line_h, fill=(255, 255, 255)):
    y = top_y
    for ln in lines:
        w = draw.textlength(ln, font=font)
        x = cx - w / 2
        draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, 160))  # shadow
        draw.text((x, y), ln, font=font, fill=fill)
        y += line_h
    return y


def render_card(quote_text, wallpaper_path, out_path, subline=None):
    base = Image.open(wallpaper_path).convert("RGB")
    base = _crop_cover(base, W, H)

    # bottom-weighted dark scrim for legibility. Ramps hard through the
    # text zone (~lower 40%) so white text reads even on light wallpapers.
    scrim = Image.new("L", (1, H))
    for y in range(H):
        t = y / H
        if t < 0.45:
            a = 18 * (t / 0.45)            # faint wash up top
        else:
            u = (t - 0.45) / 0.55          # 0..1 across the text zone
            a = 18 + 215 * (u ** 0.85)     # ramp to strong dark at bottom
        scrim.putpixel((0, y), int(min(233, a)))
    scrim = scrim.resize((W, H))
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    base = Image.composite(dark, base, scrim)

    img = base.convert("RGBA")
    draw = ImageDraw.Draw(img)

    font, lines, size = _fit_font(draw, quote_text, MAX_TEXT_W,
                                  max_lines=TARGET_LINES[1])
    line_h = int(size * 1.42)
    block_h = len(lines) * line_h
    sub_font = _italic_font(max(26, int(size * 0.6)))
    sub_h = int(sub_font.size * 1.5) if subline else 0

    # place block so it sits in lower third, bottom anchored ~1230
    bottom_anchor = 1240
    top_y = bottom_anchor - block_h - sub_h
    end_y = _draw_centered(draw, lines, font, W / 2, top_y, line_h)

    if subline:
        sw = draw.textlength(subline, font=sub_font)
        sx = W / 2 - sw / 2
        draw.text((sx + 2, end_y + 18 + 2), subline, font=sub_font, fill=(0, 0, 0, 150))
        draw.text((sx, end_y + 18), subline, font=sub_font, fill=(255, 255, 255))

    # handle
    hf = _handle_font(23, weight=500)
    hw = draw.textlength(HANDLE, font=hf)
    draw.text((W / 2 - hw / 2, 1292), HANDLE, font=hf, fill=(255, 255, 255, 215))

    img.convert("RGB").save(out_path, "PNG", quality=95)
    return out_path


if __name__ == "__main__":
    # quick test
    q = sys.argv[1] if len(sys.argv) > 1 else "You have survived every single one of your hardest days."
    wp = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\Facundo\Projects\sober-thoughts\assets\wallpapers\05-mountain-sunrise.png"
    out = sys.argv[3] if len(sys.argv) > 3 else r"C:\Users\Facundo\Downloads\card_test.png"
    print(render_card(q, wp, out))
