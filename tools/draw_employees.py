"""The Designer's employee cards (owner, 2026-10-22: "show artist renderings
for each department and employee"): one card per employee on the roster, in
its department's colour, with the department's mark, the employee's title
and its job in the roster's own words. Drawn by code, so every word is right;
the Artist's painted portraits (PORTRAIT prompts) can sit beside them.

    python tools/draw_employees.py <folder>  -> <department>/<role>.jpg,
                                                <department>.jpg (a sheet each)
"""
import math
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from draw_departments import TINT, noise  # noqa: E402
from logo_marks import LOGOS, font  # noqa: E402
from nemo.staff import DEPARTMENTS, team  # noqa: E402

W, H = 640, 400


# What each employee holds and does, so the portraits tell them apart
# (owner, 2026-10-23: the first 89, one seed and the title alone, came out
# nearly the same figure). By role; a department's own entry wins.
PROPS = {
    "researcher": "reading a large open atlas through a magnifying glass",
    "writer": "writing with a quill pen on a long sheet of paper",
    "artist": "painting at an easel with a palette of bright colours",
    "linguist": "wearing a brass ear trumpet, sound waves curling from a gramophone horn",
    "editor": "marking a manuscript with a red pencil, spectacles on its nose",
    "archivist": "carrying a stack of labelled boxes in front of filing drawers",
    "foreman": "holding a clipboard and pointing at a chalk board of tasks",
    "timekeeper": "holding up a large open pocket watch, clocks on the wall behind",
    "designer": "drawing plans with compasses and a set square on a drafting table",
    "clerk": "stamping forms at a high desk with pigeon holes",
    "inspector": "peering through a jeweller's loupe at a small circuit board",
    "woodworker": "planing a long oak floorboard at a workbench, wood shavings curling",
    "coder": "typing on a brass typewriter wired to a glowing valve computer",
    "tester": "watching a dial gauge needle while touching probes to a board",
    "technician": "turning a large wrench on a humming engine",
    "rea": "taking apart a clockwork mechanism with tweezers, parts laid out in rows",
    "storekeeper": "climbing a rolling ladder between tall shelves of labelled parts drawers",
    "projectionist": "threading film into a big brass cinema projector",
    "streamer": "tuning a radio set with glowing dials and an aerial",
    "curator": "hanging a framed photograph on a gallery wall",
    "attendant": "handing over a game cartridge across a shop counter",
    "player": "putting a record on a gramophone",
    "dj": "spinning two turntables, headphones round its neck",
    "narrator": "reading aloud from a big book into a ribbon microphone",
    "recorder": "operating a reel-to-reel tape recorder",
    "engineer": "adjusting the faders of a mixing desk",
    "librarian": "shelving audio cassettes and records",
    "flasher": "plugging a cable into a tiny circuit board on a test bench",
    "monitor": "reading scrolling text on a small green screen, oscilloscope beside",
    "slicer": "watching a 3D printer lay down a glowing orange layer",
    "director": "sitting in a director's chair with a megaphone and a clapperboard",
    "surveyor": "looking through a brass theodolite at a map of a house",
    "gatekeeper": "holding a big ring of keys at an iron gate",
    "keeper": "tending small glowing devices on a shelf like a gardener",
    "browser": "looking through a telescope at a wall of newspaper pages",
    "postman": "carrying a leather satchel of letters",
    "social": "pinning notes to a crowded cork notice board",
    "calculator": "working the handle of a mechanical calculating machine",
    "mathematician": "writing equations on a blackboard with chalk",
    "physicist": "watching a swinging pendulum beside a glass bell jar",
    "statistician": "drawing a bar chart on a large sheet of graph paper",
    "bookkeeper": "writing in a thick ledger with columns of figures",
    "gp": "listening with a brass stethoscope",
    "machine": "inspecting the gears of an open machine with a lamp",
    "model": "examining a glowing glass brain in a cabinet",
    "design": "studying a blueprint pinned to a light box",
    "stick": "holding a small USB stick up to a magnifying lamp",
    "memory": "laying out five picture cards on a table for a memory game",
    "nurse": "carrying a medical bag with a red cross, kind face",
    "nes": "holding a grey game controller with a red button",
    "snes": "holding a game controller with four coloured buttons",
    "megadrive": "holding a black game controller, a black console beside it",
    "mastersystem": "holding a small black game pad, a console with a red stripe",
    "gameboy": "holding a small grey handheld game machine",
    "gba": "holding a wide purple handheld game machine",
    "atari2600": "holding a joystick with one red button, a wood-panelled console",
    "ps1": "holding a grey game pad with two handles, a grey disc console",
}
DEPARTMENT_PROPS = {
    ("library", "artist"): "painting a book cover at an easel",
    ("art_studio", "artist"): "sculpting a small clay figure on a turntable",
    ("film", "artist"): "drawing storyboard panels pinned in a row",
    ("music", "writer"): "writing sheet music on a stand",
    ("audio", "writer"): "labelling a row of audio cassettes",
    ("gaming", "writer"): "writing game notes beside a stack of cartridges",
    ("theatre", "writer"): "writing captions on cards for a slideshow",
    ("comms", "writer"): "sealing a letter with red wax",
    ("doctors", "writer"): "writing a case report on a clipboard chart",
    ("science", "writer"): "writing up an experiment in a lab notebook",
    ("home", "writer"): "drawing a floor plan of a house with devices marked",
    ("film", "editor"): "cutting a strip of film at an editing bench",
    ("film", "narrator"): "speaking into a microphone beside a film reel",
    ("art_studio", "editor"): "measuring a 3D printed model with calipers",
    ("bench", "writer"): "writing a log while a circuit board blinks",
    ("printshop", "writer"): "writing a print card beside a stack of printed parts",
    ("storeroom", "writer"): "writing labels for storage drawers",
    ("computer_lab", "writer"): "writing a wiring guide with pin diagrams",
    ("computer_lab", "designer"): "designing a bracket on a drafting table",
    ("art_studio", "designer"): "shaping a 3D model on a glowing drafting screen",
    ("workshop", "writer"): "writing a project brief on a clipboard",
    ("art_studio", "writer"): "writing a card that describes a model",
    ("film", "writer"): "writing a film script on a typewriter",
}
# How each one looks, chosen by its seed, so no two are the same figure.
METALS = ("polished brass", "warm copper", "brushed silver", "dark iron", "bronze with green patina",
          "gold-plated", "pewter", "blued steel")
BUILDS = ("tall and slender", "short and round", "broad-shouldered", "small and nimble",
          "elderly and stooped", "sturdy")
HEADS = ("with round goggles", "with a monocle", "with a flat cap", "with a top hat",
         "bare-headed with a glass dome on top", "with a leather apron", "with a bowler hat",
         "with a headlamp")


def seed_for(key: str) -> int:
    """Each employee's own seed: the same every run, different for each."""
    import zlib
    return zlib.crc32(key.encode("utf-8")) % 2_000_000_000


def portrait(e) -> str:
    """What the Artist paints for this employee: a figure of its own, doing its job."""
    role = e.key.split(".", 1)[1]
    n = seed_for(e.key)
    prop = DEPARTMENT_PROPS.get((e.department, role)) or PROPS.get(role) or \
        f"at work as the {e.title.lower()}"
    look = f"{BUILDS[n % len(BUILDS)]} {METALS[n // 7 % len(METALS)]} automaton " \
        f"{HEADS[n // 61 % len(HEADS)]}"
    return (f"steampunk illustration, painterly, warm lamplight, no text: a {look}, the "
            f"{e.title.lower()} of the {DEPARTMENTS[e.department].name.lower()}, {prop}")


def card(e) -> Image.Image:
    tint = TINT.get(e.department, (70, 60, 50))
    img = Image.new("RGB", (W, H), tint)
    grain = noise(W, H, 4, 2).point(lambda v: int(v * 0.2))
    img = ImageChops.add(img, Image.merge("RGB", (grain, grain, grain)))
    vign = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vign).ellipse([-160, -160, W + 160, H + 160], fill=255)
    img = Image.composite(img, Image.new("RGB", (W, H), (12, 8, 6)), vign.filter(ImageFilter.GaussianBlur(90)))
    d = ImageDraw.Draw(img)
    # The department's mark on a small brass disc, top left.
    cx, cy, r = 92, 100, 62
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(176, 132, 66), outline=(205, 160, 90), width=5)
    tile = Image.new("L", (100, 100), 0)
    LOGOS[e.department](ImageDraw.Draw(tile), 50, 50)
    tile = tile.resize((86, 86), Image.LANCZOS)
    img.paste((40, 22, 10), (cx - 43, cy - 43), tile)
    d = ImageDraw.Draw(img)
    # The title on a nameplate, the department under it.
    title = font(30)
    tw = d.textlength(e.title, font=title)
    x0 = 180
    d.rounded_rectangle([x0, 52, x0 + min(tw + 32, W - x0 - 20), 100], radius=7,
                        fill=(48, 32, 18), outline=(196, 154, 82), width=3)
    d.text((x0 + 16, 58), e.title, font=title, fill=(232, 196, 120))
    d.text((x0 + 2, 110), DEPARTMENTS[e.department].name.upper(), font=font(15), fill=(200, 176, 130))
    # Its job, in the roster's words.
    y = 190
    for line in textwrap.wrap(e.job, 52)[:7]:
        d.text((40, y), line, font=font(18), fill=(236, 224, 198))
        y += 26
    if not e.working:
        d.text((40, H - 40), "On the roster, not built yet", font=font(15), fill=(230, 150, 120))
    return img


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for key in DEPARTMENTS:
        people = team(key)
        folder = out / key
        folder.mkdir(exist_ok=True)
        cards = []
        for e in people:
            im = card(e)
            im.save(folder / f"{e.key.split('.', 1)[1]}.jpg", quality=88)
            cards.append(im)
        cols = 3
        rows = math.ceil(len(cards) / cols)
        sheet = Image.new("RGB", (cols * 320, rows * 200), (12, 8, 6))
        for i, im in enumerate(cards):
            sheet.paste(im.resize((320, 200), Image.LANCZOS), ((i % cols) * 320, (i // cols) * 200))
        sheet.save(out / f"{key}.jpg", quality=88)
        total += len(cards)
    print(f"{total} employee cards in {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
