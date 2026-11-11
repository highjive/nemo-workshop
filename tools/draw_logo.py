"""Nemo's cog, steampunk: brass with rust, each department's logo laser-etched
on its tooth, and the N filled with little gears and wires. Pillow only.

One tooth per department, in the roster's order (nemo/staff.py DEPARTMENTS),
so a new department is a new tooth when this is run again (owner,
2026-10-22: "update nemo logo with the new departments"). Each department
needs a logo below in LOGOS; a department with none stops the drawing."""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nemo.staff import DEPARTMENTS  # noqa: E402

OUT = Path(sys.argv[1])
S, C = 1024, 512
random.seed(7)
KEYS = list(DEPARTMENTS)
NAMES = [DEPARTMENTS[k].name for k in KEYS]
N = len(KEYS)
STEP = 2 * math.pi / N                       # the angle from one tooth to the next
# Smaller with more teeth, so every nameplate has room beyond its tooth.
R_BODY, R_TIP = (272, 412) if N <= 8 else (238, 362)
R_LOGO, R_HOLES = R_TIP - 62, R_BODY - 67
HALF = STEP * 0.355                          # 16 degrees of 45, as the first cog had


def polar(r, a):
    return C + r * math.sin(a), C - r * math.cos(a)


def font(size):
    for name in ("georgiab.ttf", "timesbd.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def noise(scale, blur):
    """Soft random blotches, 0..255."""
    small = Image.effect_noise((S // scale, S // scale), 90).resize((S, S), Image.BICUBIC)
    return small.filter(ImageFilter.GaussianBlur(blur))


# ---- the cog's shape, as a mask
shape = Image.new("L", (S, S), 0)
sd = ImageDraw.Draw(shape)
for i in range(N):
    a = i * STEP
    sd.polygon([polar(R_BODY - 10, a - HALF), polar(R_TIP, a - HALF * 0.78),
                polar(R_TIP, a + HALF * 0.78), polar(R_BODY - 10, a + HALF)], fill=255)
sd.ellipse([C - R_BODY, C - R_BODY, C + R_BODY, C + R_BODY], fill=255)
# Rounded teeth: blurring the outline and cutting it again at half rounds every
# corner, the tips outward and the roots inward, as a cast cog's are.
shape = shape.filter(ImageFilter.GaussianBlur(16)).point(lambda v: 255 if v > 127 else 0)
shape = shape.filter(ImageFilter.GaussianBlur(1.2))           # a soft, unjagged edge
sd = ImageDraw.Draw(shape)
holes = []
HOLE = min(28, int(R_HOLES * math.sin(STEP / 2) * 0.55))   # smaller as the teeth crowd in
for i in range(N):
    x, y = polar(R_HOLES, i * STEP + STEP / 2)
    sd.ellipse([x - HOLE, y - HOLE, x + HOLE, y + HOLE], fill=0)
    holes.append((x, y))

# ---- background: dark workshop wood, darker at the corners
bg = Image.new("RGB", (S, S), (38, 26, 18))
grain = noise(4, 2).point(lambda v: int(v * 0.25))
bg = ImageChops.add(bg, Image.merge("RGB", (grain, grain.point(lambda v: v * 3 // 4),
                                            grain.point(lambda v: v // 2))))
vign = Image.new("L", (S, S), 0)
ImageDraw.Draw(vign).ellipse([-200, -200, S + 200, S + 200], fill=255)
vign = vign.filter(ImageFilter.GaussianBlur(160))
bg = Image.composite(bg, Image.new("RGB", (S, S), (10, 7, 5)), vign)

# ---- brass, brushed, with rust worst near the edges
brass = Image.new("RGB", (S, S), (176, 132, 66))
brush = noise(2, 1).point(lambda v: int((v - 128) * 0.35 + 128))
brass = ImageChops.overlay(brass, Image.merge("RGB", (brush, brush, brush)))
edge = shape.filter(ImageFilter.GaussianBlur(26))
edge = ImageChops.invert(edge).point(lambda v: min(255, v * 3))     # strongest at the rim
rust_mask = ImageChops.multiply(noise(16, 10).point(lambda v: 255 if v > 150 else int(v * 0.6)),
                                edge.point(lambda v: min(255, 60 + v)))
rust_mask = rust_mask.filter(ImageFilter.GaussianBlur(3))
rust = Image.new("RGB", (S, S), (122, 52, 22))
rust = ImageChops.multiply(rust, Image.merge("RGB", [noise(1, 0.6).point(lambda v: 150 + v // 3)] * 3))
metal = Image.composite(rust, brass, rust_mask)

img = bg.copy()
# A shadow under the cog, then the cog.
shadow = shape.filter(ImageFilter.GaussianBlur(14))
img.paste((0, 0, 0), (12, 16), shadow.point(lambda v: v * 3 // 4))
img.paste(metal, (0, 0), shape)
d = ImageDraw.Draw(img)

# Bevels and rivets.
d.ellipse([C - 150, C - 150, C + 150, C + 150], fill=(52, 38, 26), outline=(205, 160, 90), width=10)
for i in range(24):
    x, y = polar(R_BODY - 24, i * math.pi / 12 + math.pi / 24)
    d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(150, 108, 52), outline=(70, 45, 20), width=2)
    d.ellipse([x - 4, y - 5, x, y - 1], fill=(235, 205, 140))
for x, y in holes:
    d.ellipse([x - HOLE, y - HOLE, x + HOLE, y + HOLE], outline=(90, 60, 30), width=4)


# ---- logos, laser-etched: drawn white into a mask, then burnt into the metal
from logo_marks import LOGOS  # noqa: E402  (the marks, shared with the cards)

missing = [k for k in KEYS if k not in LOGOS]
if missing:
    sys.exit(f"no logo drawn for: {', '.join(missing)}; add one to LOGOS")

etch = Image.new("L", (S, S), 0)
ed = ImageDraw.Draw(etch)
# A logo a little smaller where the teeth crowd in: drawn at full size into
# its own square, shrunk, and set on its tooth.
SCALE = min(1.0, 2 * R_LOGO * math.sin(STEP / 2) / 120)
for i, key in enumerate(KEYS):
    a = i * STEP
    x, y = polar(R_LOGO, a)
    tile = Image.new("L", (100, 100), 0)
    LOGOS[key](ImageDraw.Draw(tile), 50, 50)
    side = max(1, int(100 * SCALE))
    tile = tile.resize((side, side), Image.LANCZOS)
    etch.paste(255, (int(x - side / 2), int(y - side / 2)), tile)
etch = ImageChops.multiply(etch, shape.point(lambda v: 255 if v else 0))    # only on metal
burn = Image.new("RGB", (S, S), (34, 18, 8))
glow = etch.filter(ImageFilter.GaussianBlur(2)).point(lambda v: v // 2)
img.paste((96, 52, 22), (0, 0), glow)                     # the heat-darkened edge
img.paste(burn, (0, 0), etch)
img.paste((235, 198, 120), (1, 1), ImageChops.subtract(etch.filter(ImageFilter.MaxFilter(3)), etch)
          .point(lambda v: v // 3))                         # a glint on the cut's lip


# ---- a brass nameplate for each department, just beyond its tooth
plate = font(17 if N <= 8 else 13)
for i, name in enumerate(NAMES):
    a = i * STEP
    w = d.textlength(name.upper(), font=plate)
    # Out past the tooth by half the plate's width where the tooth points
    # sideways, so a wide plate does not lie across its own tooth.
    tx, ty = polar((R_TIP + 34) if N <= 8 else (R_TIP + 22 + abs(math.sin(a)) * (w / 2 + 9)), a)
    x0 = min(max(tx - w / 2 - 9, 6), S - w - 24)
    y0 = ty - 14
    d.rounded_rectangle([x0, y0, x0 + w + 18, y0 + 28], radius=5, fill=(48, 32, 18),
                        outline=(196, 154, 82), width=2)
    for rx in (x0 + 5, x0 + w + 13):                         # two tiny screws
        d.ellipse([rx - 2, y0 + 12, rx + 2, y0 + 16], fill=(196, 154, 82))
    d.text((x0 + 9, y0 + 5), name.upper(), font=plate, fill=(222, 184, 112))


# ---- the N, filled with gears and wires
def gear(dr, cx, cy, r, teeth, fill, hub):
    pts = []
    for k in range(teeth * 2):
        rr = r if k % 2 == 0 else r * 0.8
        a0 = k * math.pi / teeth
        pts += [(cx + rr * math.cos(a0 - 0.12), cy + rr * math.sin(a0 - 0.12)),
                (cx + rr * math.cos(a0 + 0.12), cy + rr * math.sin(a0 + 0.12))]
    dr.polygon(pts, fill=fill, outline=(40, 25, 10))
    dr.ellipse([cx - r * 0.35, cy - r * 0.35, cx + r * 0.35, cy + r * 0.35], fill=hub,
               outline=(40, 25, 10), width=2)


inner = Image.new("RGB", (S, S), (28, 20, 14))
idr = ImageDraw.Draw(inner)
for _ in range(24):                          # wires behind
    x0, y0 = random.randint(380, 640), random.randint(360, 660)
    pts = [(x0 + random.randint(-90, 90), y0 + random.randint(-120, 120)) for _ in range(4)]
    col = random.choice([(184, 92, 40), (60, 60, 60), (150, 30, 30), (200, 160, 60)])
    idr.line(pts, fill=col, width=random.choice((4, 5, 6)), joint="curve")
for _ in range(48):                          # gears over them
    cx, cy = random.randint(405, 620), random.randint(415, 610)
    r = random.randint(12, 30)
    fill = random.choice([(196, 150, 70), (170, 110, 60), (140, 140, 130), (205, 120, 60)])
    gear(idr, cx, cy, r, random.randint(8, 14), fill, (60, 40, 20))
big = font(240)
nmask = Image.new("L", (S, S), 0)
nd = ImageDraw.Draw(nmask)
bb = nd.textbbox((0, 0), "N", font=big)
pos = (C - (bb[0] + bb[2]) / 2, C - (bb[1] + bb[3]) / 2)
nd.text(pos, "N", font=big, fill=255)
rim = nmask.filter(ImageFilter.MaxFilter(9))
img.paste((210, 168, 92), (0, 0), rim)                       # a brass rim round the N
img.paste((60, 40, 20), (0, 0), ImageChops.subtract(rim, nmask.filter(ImageFilter.MaxFilter(5))))
img.paste(inner, (0, 0), nmask)
img.save(OUT)
print(OUT)

# The cog alone on a clear background, for icons and the prompt window.
if len(sys.argv) > 2:
    cut = img.convert("RGBA")
    cut.putalpha(shape)
    cut = cut.crop(shape.getbbox())
    cut.save(sys.argv[2])
    print(sys.argv[2])

# The glow masks for the prompt window's loading page (owner, 2026-10-22:
# "a glow effect from around cog with lighter glow on department logos"):
# where light falls round the cog's edge, and round each etched logo. The
# window lights them in turn; the cog itself is never redrawn there.
if len(sys.argv) > 4:
    whole = shape.copy()                     # the outline only: the holes do not glow
    wd = ImageDraw.Draw(whole)
    for x, y in holes:
        wd.ellipse([x - HOLE, y - HOLE, x + HOLE, y + HOLE], fill=255)
    halo = whole.filter(ImageFilter.GaussianBlur(26)).point(lambda v: min(255, int(v * 1.6)))
    halo = ImageChops.subtract(halo, whole)
    halo.save(sys.argv[3])
    print(sys.argv[3])
    logos = ImageChops.lighter(etch.filter(ImageFilter.GaussianBlur(4)).point(lambda v: min(255, v * 2)),
                               etch.point(lambda v: v * 3 // 4))
    logos.save(sys.argv[4])
    print(sys.argv[4])
