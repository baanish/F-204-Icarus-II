"""Compose one review sheet from the renders of art/blender/review_sheet.py.

Each orthographic render is laid over its reference drawing, the model tinted so both read at once, with the
three-quarter view beside them.

    python -I tools/compose_review.py <render_dir> <reference_dir> <out.png> [title]
"""
import sys

from PIL import Image, ImageDraw, ImageFont

TINT = (230, 120, 30)


def overlay(ref_path, render_path):
    render = Image.open(render_path).convert("RGBA")
    ref = Image.open(ref_path).convert("RGBA").resize(render.size, Image.LANCZOS)
    alpha = render.getchannel("A").point(lambda a: int(a * 0.55))
    tint = Image.new("RGBA", render.size, TINT + (255,))
    shaded = Image.blend(render, tint, 0.35)
    ref.paste(shaded, (0, 0), alpha)
    return ref.convert("RGB")


def label(img, text):
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("segoeui.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    d.rectangle((0, 0, img.width, 36), fill=(30, 30, 30))
    d.text((10, 4), text, fill=(240, 240, 240), font=font)
    return img


def main(render_dir, ref_dir, out, title="Icarus"):
    top = label(overlay(f"{ref_dir}/top.png", f"{render_dir}/top.png"), "Top: model (orange) over reference")
    side = label(overlay(f"{ref_dir}/side.png", f"{render_dir}/side.png"), "Side")
    front = label(overlay(f"{ref_dir}/front.png", f"{render_dir}/front.png"), "Front")
    persp = Image.open(f"{render_dir}/three_quarter.png").convert("RGBA")
    bg = Image.new("RGBA", persp.size, (58, 60, 64, 255))
    bg.alpha_composite(persp)
    persp = label(bg.convert("RGB"), "Three-quarter")

    col_w = max(top.width, side.width)
    scale = lambda im, w: im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    top, side = scale(top, col_w), scale(side, col_w)
    front = scale(front, int(col_w * 0.42))
    persp = scale(persp, col_w)
    sheet_h = 50 + top.height + side.height + max(front.height, persp.height)
    sheet = Image.new("RGB", (col_w + front.width + 30, sheet_h + 20), (20, 20, 22))
    ImageDraw.Draw(sheet).text((12, 10), title, fill=(255, 255, 255), font=ImageFont.truetype("segoeui.ttf", 30))
    y = 50
    sheet.paste(top, (10, y)); y += top.height
    sheet.paste(side, (10, y)); y += side.height
    sheet.paste(persp, (10, y))
    sheet.paste(front, (col_w + 20, 50))
    sheet.save(out)
    print(out, sheet.size)


if __name__ == "__main__":
    main(*sys.argv[1:])
