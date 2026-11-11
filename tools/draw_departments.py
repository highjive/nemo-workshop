"""The Designer's department cards (owner, 2026-10-22: "visual concepts for
each department ... nemo loads to home scene showing the cog, then asks what
the user wants, and gives back a visual of the department").

One card per department on the roster, in the cog's style: a brass medallion
with its laser-etched mark, its name on a nameplate, what it does, and its
team as brass tags; and the scene the Artist would paint behind it (SCENES,
a prompt for the image engine). Drawn by code, so every name is right.

    python tools/draw_departments.py <folder> [<scenes>]
        -> <key>.jpg each, and sheet.jpg; with a folder of painted scenes
           (<key>.png, tools/paint_scenes.py), each card is laid on its scene.
Nemo ships them in nemo/data/departments (the prompt window's home scene).
"""
import math
import random
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from logo_marks import LOGOS, font  # noqa: E402
from nemo.staff import DEPARTMENTS, team  # noqa: E402

W, H = 960, 600
# Each department's light, so the cards tell apart at a glance.
TINT = {"library": (90, 60, 30), "art_studio": (110, 50, 70), "workshop": (70, 70, 60),
        "computer_lab": (30, 70, 80), "storeroom": (80, 60, 40), "theatre": (100, 30, 30),
        "gaming": (40, 50, 100), "music": (90, 40, 100), "audio": (60, 40, 90),
        "bench": (30, 80, 50), "printshop": (90, 70, 30), "film": (60, 40, 30),
        "home": (40, 80, 70), "comms": (30, 60, 100), "science": (40, 90, 60),
        "doctors": (100, 40, 40), "studio": (70, 40, 110)}
# What the Artist would paint behind each card (owner's steampunk, warm light).
SCENES = {
    "library": "a lamplit steampunk library, brass ladders, tall shelves of books, a reading desk",
    "art_studio": "a sunlit steampunk artist's studio, easels, brass armatures, small sculptures",
    "workshop": "a steampunk electronics workshop bench, soldering iron, brass vices, coloured wires",
    "computer_lab": "a steampunk computer room, brass terminals with green screens, cables, valves",
    "storeroom": "a steampunk storeroom, brass drawers and labelled boxes, shelves of parts",
    "theatre": "a small steampunk cinema, red velvet seats, a brass projector beam",
    "gaming": "a steampunk arcade corner, brass game cabinets, glowing screens",
    "music": "a steampunk music room, gramophone, brass horns, records on shelves",
    "audio": "a steampunk sound studio, brass microphone, dials and speakers",
    "bench": "a steampunk test bench, oscilloscope, probes, a small circuit board",
    "printshop": "a steampunk 3D print shop, a brass framed printer, spools of filament",
    "film": "a steampunk film studio, brass camera on a tripod, film reels, lights",
    "home": "a cosy steampunk house at dusk, warm windows, small brass devices",
    "comms": "a steampunk post room, brass telegraph, letters, pigeonholes",
    "science": "a steampunk laboratory, brass instruments, flasks, a blackboard of equations",
    "doctors": "a steampunk clinic for machines, brass tools on a tray, a calm warm light",
    "studio": "a steampunk game designer's studio, brass joysticks, sketches of levels pinned up",
}


def noise(w, h, scale, blur):
    small = Image.effect_noise((max(1, w // scale), max(1, h // scale)), 90).resize((w, h), Image.BICUBIC)
    return small.filter(ImageFilter.GaussianBlur(blur))


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    """The picture filling w x h, cut to fit, as a cover photo is."""
    scale = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def card(key: str, scene: Path | None = None) -> Image.Image:
    random.seed(key)
    d = DEPARTMENTS[key]
    tint = TINT.get(key, (70, 60, 50))
    if scene is not None and Path(scene).is_file():
        # The Artist's painting behind it, darkened and in the department's
        # light, so the brass and the words read over it.
        art = _cover(Image.open(scene).convert("RGB"), W, H)
        img = Image.blend(ImageChops.multiply(art, Image.new("RGB", (W, H), (150, 140, 130))),
                          Image.new("RGB", (W, H), tint), 0.3)
    else:
        img = Image.new("RGB", (W, H), tint)
        grain = noise(W, H, 4, 2).point(lambda v: int(v * 0.22))
        img = ImageChops.add(img, Image.merge("RGB", (grain, grain, grain)))
    vign = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vign).ellipse([-260, -260, W + 260, H + 260], fill=255)
    img = Image.composite(img, Image.new("RGB", (W, H), (12, 8, 6)), vign.filter(ImageFilter.GaussianBlur(140)))
    dr = ImageDraw.Draw(img)

    # The medallion, brass with rust, a soft glow round it.
    cx, cy, r = 250, H // 2, 190
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    img.paste((255, 186, 90), (0, 0), glow.filter(ImageFilter.GaussianBlur(30)).point(lambda v: v // 3))
    disc = Image.new("L", (W, H), 0)
    ImageDraw.Draw(disc).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    brass = Image.new("RGB", (W, H), (176, 132, 66))
    brush = noise(W, H, 2, 1).point(lambda v: int((v - 128) * 0.35 + 128))
    brass = ImageChops.overlay(brass, Image.merge("RGB", (brush, brush, brush)))
    rust = noise(W, H, 14, 9).point(lambda v: 255 if v > 160 else int(v * 0.4))
    brass = Image.composite(Image.new("RGB", (W, H), (122, 52, 22)), brass, rust.filter(ImageFilter.GaussianBlur(3)))
    img.paste(brass, (0, 0), disc)
    dr = ImageDraw.Draw(img)
    dr.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(205, 160, 90), width=8)
    for i in range(16):
        a = i * math.pi / 8
        x, y = cx + (r - 22) * math.sin(a), cy - (r - 22) * math.cos(a)
        dr.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(150, 108, 52), outline=(70, 45, 20), width=2)

    # The mark, etched large: drawn at its own size, enlarged, burnt in.
    tile = Image.new("L", (100, 100), 0)
    LOGOS[key](ImageDraw.Draw(tile), 50, 50)
    tile = tile.resize((240, 240), Image.LANCZOS)
    etch = Image.new("L", (W, H), 0)
    etch.paste(tile, (cx - 120, cy - 120))
    img.paste((96, 52, 22), (0, 0), etch.filter(ImageFilter.GaussianBlur(3)).point(lambda v: v // 2))
    img.paste((34, 18, 8), (0, 0), etch)
    dr = ImageDraw.Draw(img)

    # The nameplate and what it does.
    x0 = 480
    title = font(40)
    tw = dr.textlength(d.name.upper(), font=title)
    dr.rounded_rectangle([x0, 70, x0 + tw + 40, 132], radius=8, fill=(48, 32, 18), outline=(196, 154, 82), width=3)
    for sx in (x0 + 10, x0 + tw + 30):
        dr.ellipse([sx - 4, 97, sx + 4, 105], fill=(196, 154, 82))
    dr.text((x0 + 20, 78), d.name.upper(), font=title, fill=(232, 196, 120))
    body = font(19)
    y = 156
    for line in textwrap.wrap(d.job, 40):
        dr.text((x0, y), line, font=body, fill=(232, 218, 190))
        y += 26

    # The team, as brass tags.
    y += 14
    tag = font(16)
    x = x0
    for e in team(key):
        w = dr.textlength(e.title, font=tag) + 22
        if x + w > W - 30:
            x, y = x0, y + 38
        dr.rounded_rectangle([x, y, x + w, y + 28], radius=6, fill=(60, 42, 24), outline=(170, 130, 70), width=2)
        dr.text((x + 11, y + 5), e.title, font=tag, fill=(222, 190, 128))
        x += w + 8
    return img


def main(out: Path, scenes: Path | None = None):
    out.mkdir(parents=True, exist_ok=True)
    cards = []
    for key in DEPARTMENTS:
        im = card(key, scenes / f"{key}.png" if scenes else None)
        im.save(out / f"{key}.jpg", quality=88)
        cards.append(im)
    cols = 4
    rows = math.ceil(len(cards) / cols)
    sheet = Image.new("RGB", (cols * 480, rows * 300), (12, 8, 6))
    for i, im in enumerate(cards):
        sheet.paste(im.resize((480, 300), Image.LANCZOS), ((i % cols) * 480, (i // cols) * 300))
    sheet.save(out / "sheet.jpg", quality=88)
    print(out / "sheet.jpg")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None)
