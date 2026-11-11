"""The Artist paints each department's scene, for its card, and (with
--employees) a portrait of each employee (owner, 2026-10-22: "have the Artist
paint each department's scene behind its card", and "show artist renderings
for each department and employee").

    python tools/paint_scenes.py <folder>               -> <department>.png each
    python tools/paint_scenes.py <folder> --employees   -> <department>/<role>.png each

The prompts are tools/draw_departments.py's SCENES and draw_employees.py's
portrait(). A picture already painted is kept, so a stopped run carries on
where it was. The image engine is the Library Artist's (SD-Turbo,
nemo/artist.py): about eleven minutes a picture on the AH531, so the 86
portraits are an overnight run here, and it needs the language model
unloaded and about 2.9 GB free.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from draw_departments import SCENES  # noqa: E402
from draw_employees import portrait, seed_for  # noqa: E402
from nemo import artist  # noqa: E402
from nemo.config import Config  # noqa: E402
from nemo.staff import DEPARTMENTS, STAFF  # noqa: E402

STYLE = "steampunk illustration, painterly, warm lamplight, rich detail, no text"


def jobs(out: Path, employees: bool) -> list[tuple[Path, str, str, int]]:
    """(where the picture goes, its prompt, its name, its seed), for what is
    not painted yet. Each employee has its own seed (draw_employees.seed_for):
    one seed for all made 89 near-identical figures (2026-10-23)."""
    if employees:
        todo = [(out / e.department / f"{key.split('.', 1)[1]}.png", portrait(e),
                 f"{DEPARTMENTS[e.department].name} {e.title}", seed_for(key))
                for key, e in STAFF.items()]
    else:
        todo = [(out / f"{k}.png", f"{STYLE}: {SCENES[k]}", DEPARTMENTS[k].name, 11)
                for k in DEPARTMENTS]
    return [t for t in todo if not t[0].is_file()]


# Full screen (owner, 2026-11-04): a scene fills the room, 1366 wide at full
# screen, so it is painted at that shape (multiples of 64, as SD-Turbo
# wants), from the earlier painting so the room keeps its look. Portraits
# stay square: they are shown 92 pixels across.
FULL_SCREEN = (1344, 576)


def main(out: Path, employees: bool = False, size=None, reference: Path | None = None,
         strength: float = 0.40, steps: int = 3) -> int:
    """Paint what is not in `out` yet. With `reference` (a folder laid out
    like `out`, e.g. the laptop's paintings), each picture is painted from
    its earlier one; a picture with no earlier one is painted from nothing."""
    cfg = Config.load()
    todo = jobs(out, employees)
    size = size or ((artist.SIZE, artist.SIZE) if employees else FULL_SCREEN)
    print(f"{len(todo)} picture(s) to paint at {size[0]} x {size[1]}"
          + (f", from {reference}" if reference else "") + ".", flush=True)
    for n, (path, prompt, name, seed) in enumerate(todo, 1):
        path.parent.mkdir(parents=True, exist_ok=True)
        earlier = reference / path.relative_to(out) if reference else None
        began = time.time()
        try:
            if earlier is not None and earlier.is_file():
                artist.paint(path, prompt, cfg, seed=seed, say=lambda s: None, size=size,
                             reference=earlier, strength=strength, steps=steps)
            else:
                artist.paint(path, prompt, cfg, seed=seed, say=lambda s: None, size=size)
        except artist.ArtistError as exc:
            print(f"{name}: not painted: {exc}", flush=True)
            return 1
        print(f"{n}/{len(todo)} {name}: {time.time() - began:.0f} s", flush=True)
    return 0


def _args(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--employees", action="store_true")
    ap.add_argument("--size", help="W x H, e.g. 1344x576 (scenes default to that, portraits to 512x512)")
    ap.add_argument("--from", dest="reference", type=Path,
                    help="a folder of earlier paintings to paint from (same layout as out)")
    ap.add_argument("--strength", type=float, default=0.40)
    ap.add_argument("--steps", type=int, default=3)
    a = ap.parse_args(argv)
    size = tuple(int(v) for v in a.size.lower().split("x")) if a.size else None
    return a.out, a.employees, size, a.reference, a.strength, a.steps


if __name__ == "__main__":
    sys.exit(main(*_args(sys.argv[1:])))
