"""The departments' marks, as laser-etched on Nemo's cog (tools/draw_logo.py)
and on the department cards (tools/draw_departments.py). Each draws white
lines into a mask, about 80 pixels across, centred on (x, y). Pillow only."""
import math

from PIL import ImageFont


def font(size):
    for name in ("georgiab.ttf", "timesbd.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def book(m, x, y):
    m.polygon([(x - 38, y - 22), (x - 3, y - 14), (x - 3, y + 28), (x - 38, y + 20)], outline=255, width=4)
    m.polygon([(x + 38, y - 22), (x + 3, y - 14), (x + 3, y + 28), (x + 38, y + 20)], outline=255, width=4)
    for k in (-4, 4, 12):
        m.line([(x - 31, y + k - 6), (x - 9, y + k)], fill=255, width=2)
        m.line([(x + 31, y + k - 6), (x + 9, y + k)], fill=255, width=2)


def palette(m, x, y):
    m.ellipse([x - 38, y - 28, x + 38, y + 28], outline=255, width=4)
    m.ellipse([x + 8, y + 2, x + 24, y + 18], outline=255, width=3)
    for dx, dy in ((-20, -10), (-2, -16), (16, -10), (-22, 8)):
        m.ellipse([x + dx - 6, y + dy - 6, x + dx + 6, y + dy + 6], fill=255)
    m.line([(x - 4, y + 34), (x + 30, y - 2)], fill=255, width=4)    # a brush across it


def hammer(m, x, y):
    m.rectangle([x - 5, y - 12, x + 5, y + 38], outline=255, width=3)
    m.polygon([(x - 34, y - 34), (x + 26, y - 34), (x + 40, y - 26), (x + 40, y - 18),
               (x + 26, y - 12), (x - 34, y - 12)], outline=255, width=4)


def computer(m, x, y):
    m.rectangle([x - 38, y - 30, x + 38, y + 18], outline=255, width=4)
    m.text((x - 22, y - 22), ">_", font=font(22), fill=255)
    m.line([(x, y + 18), (x, y + 30)], fill=255, width=4)
    m.line([(x - 22, y + 32), (x + 22, y + 32)], fill=255, width=4)


def box(m, x, y):
    for pts in (((x - 34, y - 14), (x, y - 30), (x + 34, y - 14), (x, y + 2)),
                ((x - 34, y - 14), (x, y + 2), (x, y + 36), (x - 34, y + 20)),
                ((x + 34, y - 14), (x, y + 2), (x, y + 36), (x + 34, y + 20))):
        m.polygon(pts, outline=255, width=3)


def clapper(m, x, y):
    m.rectangle([x - 36, y - 8, x + 36, y + 32], outline=255, width=4)
    m.polygon([(x - 38, y - 14), (x + 32, y - 34), (x + 36, y - 22), (x - 34, y - 2)], outline=255, width=3)
    for k in range(4):
        x0 = x - 28 + k * 18
        m.line([(x0, y - 9 - k * 5), (x0 + 10, y - 20 - k * 5)], fill=255, width=4)


def gamepad(m, x, y):
    m.rounded_rectangle([x - 40, y - 20, x + 40, y + 22], radius=18, outline=255, width=4)
    m.line([(x - 28, y), (x - 12, y)], fill=255, width=5)
    m.line([(x - 20, y - 8), (x - 20, y + 8)], fill=255, width=5)
    m.ellipse([x + 12, y - 9, x + 21, y], fill=255)
    m.ellipse([x + 22, y, x + 31, y + 9], fill=255)


def cross(m, x, y):
    m.polygon([(x - 11, y - 34), (x + 11, y - 34), (x + 11, y - 11), (x + 34, y - 11), (x + 34, y + 11),
               (x + 11, y + 11), (x + 11, y + 34), (x - 11, y + 34), (x - 11, y + 11), (x - 34, y + 11),
               (x - 34, y - 11), (x - 11, y - 11)], outline=255, width=4)


# The departments added after the first eight (2026-10-21 and 22), and the
# three approved next (Home, Communications, Science), so each has one ready.
def note(m, x, y):
    m.ellipse([x - 30, y + 10, x - 6, y + 30], fill=255)
    m.ellipse([x + 8, y + 2, x + 32, y + 22], fill=255)
    m.line([(x - 8, y + 18), (x - 8, y - 30)], fill=255, width=5)
    m.line([(x + 30, y + 10), (x + 30, y - 38)], fill=255, width=5)
    m.polygon([(x - 8, y - 30), (x + 30, y - 38), (x + 30, y - 26), (x - 8, y - 18)], fill=255)


def speaker(m, x, y):
    m.polygon([(x - 34, y - 12), (x - 18, y - 12), (x + 2, y - 30), (x + 2, y + 30),
               (x - 18, y + 12), (x - 34, y + 12)], outline=255, width=4)
    for r in (16, 28):
        m.arc([x + 2 - r, y - r, x + 2 + r, y + r], -45, 45, fill=255, width=4)


def chip(m, x, y):
    m.rectangle([x - 22, y - 22, x + 22, y + 22], outline=255, width=4)
    for k in (-12, 0, 12):
        m.line([(x - 34, y + k), (x - 22, y + k)], fill=255, width=3)
        m.line([(x + 22, y + k), (x + 34, y + k)], fill=255, width=3)
        m.line([(x + k, y - 34), (x + k, y - 22)], fill=255, width=3)
        m.line([(x + k, y + 22), (x + k, y + 34)], fill=255, width=3)
    m.ellipse([x - 6, y - 6, x + 6, y + 6], fill=255)


def printer(m, x, y):
    m.rectangle([x - 36, y - 36, x + 36, y + 34], outline=255, width=4)       # the frame
    m.line([(x - 36, y - 18), (x + 36, y - 18)], fill=255, width=3)          # the gantry
    m.polygon([(x - 6, y - 18), (x + 6, y - 18), (x + 2, y - 6), (x - 2, y - 6)], fill=255)
    m.rectangle([x - 24, y + 22, x + 24, y + 26], fill=255)                   # the bed
    for k in range(3):                                                         # a print rising
        m.line([(x - 12, y + 18 - k * 6), (x + 12, y + 18 - k * 6)], fill=255, width=3)


def reel(m, x, y):
    m.ellipse([x - 34, y - 34, x + 34, y + 34], outline=255, width=4)
    m.ellipse([x - 6, y - 6, x + 6, y + 6], fill=255)
    for k in range(5):
        a = k * 2 * math.pi / 5
        cx, cy = x + 19 * math.sin(a), y - 19 * math.cos(a)
        m.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=255, width=3)


def house(m, x, y):
    m.polygon([(x - 36, y - 2), (x, y - 34), (x + 36, y - 2)], outline=255, width=4)
    m.rectangle([x - 26, y - 2, x + 26, y + 32], outline=255, width=4)
    m.rectangle([x - 8, y + 12, x + 8, y + 32], outline=255, width=3)


def envelope(m, x, y):
    m.rectangle([x - 38, y - 24, x + 38, y + 24], outline=255, width=4)
    m.line([(x - 38, y - 24), (x, y + 4), (x + 38, y - 24)], fill=255, width=4)


def flask(m, x, y):
    m.polygon([(x - 8, y - 36), (x + 8, y - 36), (x + 8, y - 10), (x + 32, y + 30),
               (x - 32, y + 30), (x - 8, y - 10)], outline=255, width=4)
    m.line([(x - 22, y + 12), (x + 22, y + 12)], fill=255, width=3)          # the liquid
    for bx, by in ((-6, 20), (8, 22), (2, 6)):
        m.ellipse([x + bx - 3, y + by - 3, x + bx + 3, y + by + 3], fill=255)


def level(m, x, y):
    """The Game Studio (2026-11-09): a platformer's level, three ledges rising to a flag."""
    for k, (lx, ly) in enumerate(((-38, 26), (-12, 8), (14, -10))):
        m.rectangle([x + lx, y + ly, x + lx + 22, y + ly + 5], fill=255)
    m.rectangle([x - 32, y + 12, x - 24, y + 24], outline=255, width=3)        # the player
    m.line([(x + 30, y - 10), (x + 30, y - 38)], fill=255, width=3)            # the flag's pole
    m.polygon([(x + 30, y - 38), (x + 44, y - 32), (x + 30, y - 26)], fill=255)


LOGOS = {"library": book, "art_studio": palette, "workshop": hammer, "computer_lab": computer,
         "storeroom": box, "theatre": clapper, "gaming": gamepad, "music": note,
         "audio": speaker, "bench": chip, "printshop": printer, "film": reel,
         "home": house, "comms": envelope, "science": flask, "doctors": cross,
         "studio": level}
