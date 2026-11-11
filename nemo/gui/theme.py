"""Colours and type for the desktop interface.

Nemo's own look throughout (owner, 2026-11-04: "keep the nemo theme
throughout in all menus"): the walnut, brass and parchment of its logo, its
home window and its painted rooms, where the working windows had a grey-green
drafting palette of their own. Every window reads these names, so the whole
interface changes here. Results keep inspection-stamp colours (green, red,
amber): a skipped check is not a passed one, and that must stay plain.

Text contrast, against WCAG's 4.5 for body text: INK on PAPER 14.6,
INK2 on PAPER 5.6, SHELL_INK on SHELL 13.9, white on ACTION 7.4.
"""

PAPER = "#EFE4CC"      # window background: parchment
PANEL = "#F8F1E2"      # content surfaces: lighter parchment
RULE = "#C9B48A"       # dividers and outlines: brass, faded
SELECT = "#E8D6AE"     # selected row (the home window's highlight)
INK = "#21170F"        # primary text: walnut
INK2 = "#6B5236"       # secondary text
SHELL = "#21170F"      # header band: walnut, as the rooms' bars
SHELL_INK = "#F2E6C8"  # text on the header: parchment
SHELL_2 = "#4A3624"    # a second shade on the header (its buttons)
BRASS = "#C49A52"      # Nemo's brass: the Home button, ring and plate edges
ACTION = "#7A4E1D"     # actions, running: copper
ACTION_DOWN = "#5E3B14"
BLUE = ACTION          # the old name, still read across the interface
PASS = "#3F6B35"
FAIL = "#9E2F1F"
SKIP = "#94640C"

STATUS_COLOUR = {"passed": PASS, "done": PASS, "failed": FAIL,
                 "unchecked": SKIP, "running": BLUE, "not run": INK2}


# Nemo's own sizes, in points, at 100 per cent.
SIZES = {"body": (10, "normal"), "small": (9, "normal"), "strong": (10, "bold"),
         "h2": (12, "bold"), "title": (15, "bold"), "brand": (15, "bold"),
         "stamp": (9, "bold"), "mono": (9, "normal")}
# Text size (2026-11-08, after Claude Code Game Studios' accessibility
# checklist: "text readable at minimum font size"): per cent of SIZES, kept
# in gui.json "text_size", changed with Ctrl + and Ctrl - or the header's
# Text button. The smallest, 9 pt, is small on the AH531's 1366x768 screen.
TEXT_SIZES = (100, 125, 150, 175)


def scaled(points: int, percent: int) -> int:
    return max(1, round(points * percent / 100))


def text_size(percent) -> int:
    """`percent` as one of TEXT_SIZES (the nearest; 100 when unreadable)."""
    try:
        p = int(percent)
    except (TypeError, ValueError):
        return 100
    return min(TEXT_SIZES, key=lambda s: abs(s - p))


def pick_fonts(root, percent: int = 100):
    """Segoe UI on Windows, DejaVu Sans elsewhere; mono only for logs. Named
    fonts: set_text_size() changes every widget and drawing that uses them,
    at once. Each still reads as (family, size, weight) by index."""
    import tkinter.font as tkfont
    have = set(tkfont.families(root))
    ui = next((f for f in ("Segoe UI", "DejaVu Sans", "Liberation Sans")
               if f in have), "TkDefaultFont")
    mono = next((f for f in ("Consolas", "DejaVu Sans Mono",
                             "Liberation Mono") if f in have), "TkFixedFont")

    class NemoFont(tkfont.Font):
        def __getitem__(self, i):
            return (self.cget("family"), self.cget("size"), self.cget("weight"))[i]

    percent = text_size(percent)
    return {name: NemoFont(root, family=mono if name == "mono" else ui,
                           size=scaled(pt, percent), weight=weight)
            for name, (pt, weight) in SIZES.items()}


def set_text_size(fonts: dict, percent: int) -> int:
    """Every Nemo font at `percent` of its own size; returns the size used."""
    percent = text_size(percent)
    for name, (pt, _) in SIZES.items():
        if name in fonts:
            fonts[name].configure(size=scaled(pt, percent))
    return percent
