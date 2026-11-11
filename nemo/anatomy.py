"""Concepts built by code from an object's anatomy (owner, 2026-11-04:
"concept drawings dont look like what its supposed to"; then "remove
blockout", and he chose code-built shapes).

Until then the language model placed plain shapes by coordinates, and an 8B
model could not compose a recognisable object that way: its blunderbuss was a
635 x 55 x 139 mm box with a barrel half inside it and every other part piled
at one point (docs/design-rules.md 4d: ask the model for a bounded choice, never for
geometry). Now Nemo's code knows a few families of object, their parts and
where each part sits, and builds two concepts from the object's real sizes:
A, the main forms; B, more detail. The model is asked nothing.

The sizes the brief gives (shape_size_mm: long, wide, high; shape_facts: a
family's own figures, such as a gun's barrel length and bore) are used as
they are. Every other proportion is an ESTIMATE, a rule of thumb written
here as a fraction of the overall size, and each concept says which of its
sizes are estimates. Nothing here is a measurement of any particular object.

An object no family knows is said plainly: no shapes are guessed for it.
Families so far: long guns (a blunderbuss, a musket, a rifle), as props.
A long gun here is a solid prop: its barrel is solid, with only a shallow
recess at the muzzle for its look (nemo/safety.py lets a declared prop
through; nothing here makes a working bore).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# Raise it whenever the anatomy changes what it builds: concepts drawn by an older
# one are drawn again (concept.painted_signature carries it).
VERSION = 6


class UnknownObject(ValueError):
    """No family knows this object; the message says which ones there are."""


@dataclass(frozen=True)
class Family:
    key: str
    title: str
    words: tuple[str, ...]          # what in a brief names one
    facts: tuple[str, ...]          # its own figures a brief may give (shape_facts)
    # Its usual proportions, long : wide : high: an ESTIMATE, used only for a
    # size the brief does not give, and said so.
    ratio: tuple[float, float, float] = (1.0, 0.086, 0.22)


# In the order they are tried: a "flintlock pistol" is a pistol, not a long gun.
FAMILIES = {f.key: f for f in (
    Family("pistol", "pistol",
           ("pistol", "handgun", "duelling pistol", "dueling pistol", "dragon pistol"),
           ("barrel_mm", "muzzle_bore_mm"), (1.0, 0.13, 0.42)),
    Family("long_gun", "long gun",
           ("blunderbuss", "blunderbust", "musketoon", "musket", "flintlock", "rifle",
            "carbine", "shotgun", "long gun", "longarm", "fowling piece", "matchlock"),
           ("barrel_mm", "muzzle_bore_mm"), (1.0, 0.086, 0.22)),
    Family("sword", "sword",
           ("sword", "sabre", "saber", "cutlass", "broadsword", "longsword", "rapier",
            "dagger", "claymore", "gladius"),
           ("blade_mm",), (1.0, 0.22, 0.035)),
    Family("lighthouse", "lighthouse", ("lighthouse",), (), (0.36, 0.36, 1.0)),
    Family("rocket", "rocket", ("rocket", "rocketship", "space rocket", "spacecraft"),
           (), (0.3, 0.3, 1.0)),
    Family("house", "house",
           ("house", "cottage", "cabin", "barn", "shed", "dollhouse", "doll's house", "hut",
            "bungalow"), (), (1.0, 0.7, 0.85)),
)}

# A flared (bell) mouth: only these long guns have one.
BELLMOUTH = ("blunderbuss", "blunderbust", "musketoon", "bellmouth", "bell mouth", "flared")


def family_of(text: str) -> Family | None:
    """The family a brief's words name, or None."""
    t = (text or "").lower()
    for f in FAMILIES.values():
        if any(re.search(rf"\b{re.escape(w)}", t) for w in f.words):
            return f
    return None


def known() -> str:
    return ", ".join(f.title for f in FAMILIES.values())


# ------------------------------------------------------------ the long gun
# ESTIMATES: proportions of a long gun's parts, as fractions of the overall
# length L, width W and height H, or of the barrel. Rules of thumb for the
# look of a concept, not measured from any one gun.
LONG_GUN_ESTIMATES = {
    "breech_radius": 0.0185,        # of L: the barrel's outside at the breech
    "flare": 0.22,                  # of the barrel: the length of the bell mouth
    "muzzle_wall": 4.0,             # mm round the bore at the muzzle
    "barrel": 0.52,                 # of L, when the brief gives no barrel length
    "bore": 1.1,                    # of the breech radius, when no bore is given
    "fore_end_short": 0.08,         # of L: the stock stops this far short of the muzzle
    "fore_depth": 0.08,             # of H: the stock below the barrel
    "lock_length": 0.15,            # of L
    "lock_width": 0.62,             # of W
    "lock_depth": 0.24,             # of H, below the barrel's axis
    "wrist_length": 0.10,           # of L
    "wrist_width": 0.50,            # of W
    "wrist_depth": 0.17,            # of H
    "butt_drop": 0.25,              # of H: how far the heel is below the wrist's top
    "toe_flat": 0.06,               # of L: the flat under the butt at its toe
    "guard_radius": 0.075,          # of H
}


def _rounded(name, size, at, radius, rotate=(0, 0, 0)):
    r = min(radius, min(size[:2]) / 2 - 0.6)
    s = {"shape": "rounded_box" if r >= 1 else "box", "op": "add", "size": [round(v, 2) for v in size],
         "at": [round(v, 2) for v in at], "rotate": list(rotate), "label": name}
    if r >= 1:
        s["radius"] = round(r, 2)
    return s


def _box(name, size, at, rotate=(0, 0, 0), op="add"):
    return {"shape": "box", "op": op, "size": [round(v, 2) for v in size],
            "at": [round(v, 2) for v in at], "rotate": list(rotate), "label": name}


def _lying(name, kind, radius, length, x0, y, z, top=None, op="add"):
    """A cylinder or cone along x from x0, its axis at (y, z)."""
    s = {"shape": kind, "op": op, "radius": round(radius, 2), "height": round(length, 2),
         "at": [round(x0, 2), round(y, 2), round(z, 2)], "rotate": [0, 90, 0], "label": name}
    if kind == "cone":
        s["top_radius"] = round(top, 2)
    return s


def _across(name, radius, width, x, z, op="add"):
    """A cylinder across the object (along y), centred on (x, 0, z)."""
    return {"shape": "cylinder", "op": op, "radius": round(radius, 2), "height": round(width, 2),
            "at": [round(x, 2), round(width / 2, 2), round(z, 2)], "rotate": [90, 0, 0],
            "label": name}


def long_gun(size, facts: dict, words: str, detail: bool) -> tuple[list[dict], list[str]]:
    """A long gun's shapes, muzzle at +x, butt at -x, its butt resting on the
    ground; and the sizes that are estimates, said."""
    E = LONG_GUN_ESTIMATES
    L, W, H = size
    estimated = []
    Lb = float(facts.get("barrel_mm") or 0)
    if not Lb:
        Lb = E["barrel"] * L
        estimated.append("barrel length")
    rb = E["breech_radius"] * L
    bore = float(facts.get("muzzle_bore_mm") or 0)
    if not bore:
        bore = E["bore"] * rb
        estimated.append("bore")
    flared = any(w in words.lower() for w in BELLMOUTH)
    rm = bore / 2 + E["muzzle_wall"] if flared else rb
    lf = E["flare"] * Lb if flared else 0.0
    xm = L / 2
    xb = xm - Lb                                    # the breech
    zb = H - max(rm, rb)                            # the barrel's axis: its top is H
    shapes = [_lying("Barrel", "cylinder", rb, Lb - lf, xb, 0, zb)]
    if flared:
        shapes.append(_lying("Bell mouth", "cone", rb, lf, xm - lf, 0, zb, top=rm))
    # The muzzle's opening: a shallow recess for the look, not a bore.
    recess = min(25.0, 0.3 * Lb)
    shapes.append(_lying("Muzzle opening", "cone", max(1.5, bore / 2 * 0.55), recess + 0.5,
                         xm - recess, 0, zb, top=bore / 2, op="cut"))
    # The fore-end of the stock, under the barrel almost to the muzzle.
    fore_depth = rb + E["fore_depth"] * H
    fore_x0, fore_x1 = xb, xm - E["fore_end_short"] * L - (lf if flared else 0) * 0.3
    fore_w = 2 * rb + 6
    shapes.append(_rounded("Fore-end", [fore_x1 - fore_x0, fore_w, fore_depth],
                           [(fore_x0 + fore_x1) / 2, 0, zb - fore_depth + rb * 0.15], fore_w / 4))
    # The lock and breech.
    lock_len, lock_w = E["lock_length"] * L, E["lock_width"] * W
    lock_x1 = xb + 0.25 * lock_len
    lock_x0 = lock_x1 - lock_len
    lock_bottom = zb - E["lock_depth"] * H
    lock_top = zb + rb * 0.6
    shapes.append(_rounded("Lock", [lock_len, lock_w, lock_top - lock_bottom],
                           [(lock_x0 + lock_x1) / 2, 0, lock_bottom], lock_w / 4))
    # The wrist, behind the lock, narrower.
    wrist_len, wrist_w = E["wrist_length"] * L, E["wrist_width"] * W
    wrist_depth = E["wrist_depth"] * H
    wrist_x1 = lock_x0 + 2.0
    wrist_x0 = wrist_x1 - wrist_len
    wrist_top = lock_top - 0.04 * H
    shapes.append(_rounded("Wrist", [wrist_len, wrist_w, wrist_depth],
                           [(wrist_x0 + wrist_x1) / 2, 0, wrist_top - wrist_depth], wrist_w / 3))
    # The butt, the widest part: a wedge seen from the side, tallest at the
    # heel. Its toe is on the ground at the back, its belly rises to the wrist's
    # bottom, its comb falls from the wrist's top to the heel; its back is
    # upright, for the butt plate. One prism (a convex outline, given its width).
    # It reaches 10 mm into the wrist, and its comb is 2 mm above the wrist's top
    # where the wrist ends inside it. Flush with the wrist's top it left a 0.45 mm
    # sliver at the join, and a fixed 2 mm lift at the front only moved it, to
    # 0.02 mm (the comb slopes down to the back) (2026-11-05).
    bx0, bx1 = -L / 2, wrist_x0 + 10.0
    heel = wrist_top - E["butt_drop"] * H
    D = bx1 - bx0
    front_top = (wrist_top + 2.0 - (bx1 - wrist_x0) * heel / D) / (1 - (bx1 - wrist_x0) / D)
    wrist_bottom = wrist_top - wrist_depth
    shapes.append({"shape": "prism", "op": "add", "label": "Butt", "width": round(W, 2),
                   # A flat at the toe: without it the toe was a knife-edge, 0.58 mm
                   # thick where the belly met the back (2026-11-04).
                   "points": [[round(bx0, 2), 0.0], [round(bx0 + E["toe_flat"] * L, 2), 0.0],
                              [round(bx1, 2), round(wrist_bottom, 2)],
                              [round(bx1, 2), round(front_top, 2)], [round(bx0, 2), round(heel, 2)]],
                   "at": [0.0, 0.0, 0.0], "rotate": [0, 0, 0]})
    # The trigger guard: a ring under the lock and wrist.
    rg = E["guard_radius"] * H
    gx = lock_x0 + 0.25 * rg
    gz = lock_bottom - rg + 3.0
    shapes.append(_across("Trigger guard", rg, 6.0, gx, gz))
    shapes.append(_across("Guard opening", rg - 3.5, 8.0, gx, gz - 1.0, op="cut"))
    if detail:
        shapes.append(_box("Trigger", [4.0, 4.0, rg * 0.9], [gx + 1.0, 0, lock_bottom - rg * 0.9 + 1.0]))
        plate_len = 0.75 * lock_len
        shapes.append(_box("Lock plate", [plate_len, 3.0, 0.5 * (lock_top - lock_bottom)],
                           [(lock_x0 + lock_x1) / 2, lock_w / 2 + 1.0, lock_bottom + 0.3 * (lock_top - lock_bottom)]))
        shapes.append(_box("Hammer", [12.0, 5.0, 0.07 * H],
                           [lock_x0 + 0.3 * plate_len, lock_w / 2 + 2.0, lock_top - 6.0]))
        shapes.append(_box("Pan", [12.0, 9.0, 8.0],
                           [lock_x1 - 0.25 * lock_len, lock_w / 2 + 2.5, lock_top - 10.0]))
        shapes.append(_box("Side plate", [0.5 * lock_len, 2.0, 0.3 * (lock_top - lock_bottom)],
                           [(lock_x0 + lock_x1) / 2, -(lock_w / 2 + 0.5), lock_bottom + 0.35 * (lock_top - lock_bottom)]))
        shapes.append(_lying("Ramrod", "cylinder", 3.0, (fore_x1 - fore_x0) * 0.9, fore_x0 + 4.0, 0,
                             zb - fore_depth + rb * 0.15 + 2.0))
        shapes.append(_box("Butt plate", [5.0, W + 2.0, heel], [bx0 + 2.5, 0, 0.0]))
        if flared:
            shapes.append(_lying("Muzzle ring", "cylinder", rm + 1.0, 6.0, xm - 6.0, 0, zb))
        else:
            shapes.append(_lying("Muzzle band", "cylinder", rb + 1.5, 8.0, xm - 30.0, 0, zb))
    estimated += ["the stock's parts", "the lock", "the trigger guard"]
    return shapes, estimated


def _upright(name, kind, radius, height, x, y, z0, top=None, op="add"):
    """A cylinder or cone standing up from z0, its axis at (x, y)."""
    s = {"shape": kind, "op": op, "radius": round(radius, 2), "height": round(height, 2),
         "at": [round(x, 2), round(y, 2), round(z0, 2)], "rotate": [0, 0, 0], "label": name}
    if kind == "cone":
        s["top_radius"] = round(top, 2)
    return s


def _ball(name, radius, at):
    return {"shape": "sphere", "op": "add", "radius": round(radius, 2),
            "at": [round(v, 2) for v in at], "rotate": [0, 0, 0], "label": name}


def _prism(name, points, width, at=(0.0, 0.0, 0.0), rotate=(0, 0, 0)):
    """A convex outline in (x, z), given its width across y; turned by rotate."""
    return {"shape": "prism", "op": "add", "label": name, "width": round(width, 2),
            "points": [[round(x, 2), round(z, 2)] for x, z in points],
            "at": [round(v, 3) for v in at], "rotate": list(rotate)}


# ------------------------------------------------------------ the pistol
PISTOL_ESTIMATES = {
    "barrel": 0.58,                 # of L, when the brief gives no barrel length
    "breech_radius": 0.034,         # of L
    "fore_end_short": 0.06,         # of L
    "lock_length": 0.24,            # of L
    "lock_width": 0.70,             # of W
    "lock_depth": 0.30,             # of H, below the barrel's axis
    "grip_width": 0.62,             # of W
    "grip_reach": 0.42,             # of L: how far back the grip runs
    "grip_depth": 0.26,             # of L: the grip measured across
    "cap_radius": 0.07,             # of H: the butt cap
    "guard_radius": 0.10,           # of H
}


def pistol(size, facts: dict, words: str, detail: bool) -> tuple[list[dict], list[str]]:
    """A flintlock pistol, muzzle at +x, its grip sloping down and back to its
    butt cap, which rests on the ground."""
    E = PISTOL_ESTIMATES
    L, W, H = size
    estimated = []
    Lb = float(facts.get("barrel_mm") or 0) or E["barrel"] * L
    if not facts.get("barrel_mm"):
        estimated.append("barrel length")
    rb = E["breech_radius"] * L
    bore = float(facts.get("muzzle_bore_mm") or 0)
    if not bore:
        estimated.append("bore")
        bore = 1.0 * rb
    flared = any(w in words.lower() for w in BELLMOUTH + ("dragon",))
    rm = bore / 2 + 3.0 if flared else rb
    lf = 0.2 * Lb if flared else 0.0
    xm = L / 2
    xb = xm - Lb
    zb = H - max(rm, rb)
    shapes = [_lying("Barrel", "cylinder", rb, Lb - lf, xb, 0, zb)]
    if flared:
        shapes.append(_lying("Bell mouth", "cone", rb, lf, xm - lf, 0, zb, top=rm))
    recess = min(15.0, 0.25 * Lb)
    shapes.append(_lying("Muzzle opening", "cone", max(1.0, bore / 2 * 0.5), recess + 0.5,
                         xm - recess, 0, zb, top=max(1.5, bore / 2 * 0.9), op="cut"))
    fore_x1 = xm - E["fore_end_short"] * L - lf * 0.3
    fore_w, fore_d = 2 * rb + 4, rb + 0.06 * H
    shapes.append(_rounded("Fore-end", [fore_x1 - xb, fore_w, fore_d],
                           [(xb + fore_x1) / 2, 0, zb - fore_d + rb * 0.15], fore_w / 4))
    lock_len, lock_w = E["lock_length"] * L, E["lock_width"] * W
    lock_x1 = xb + 0.3 * lock_len
    lock_x0 = lock_x1 - lock_len
    lock_bottom, lock_top = zb - E["lock_depth"] * H, zb + rb * 0.6
    shapes.append(_rounded("Lock", [lock_len, lock_w, lock_top - lock_bottom],
                           [(lock_x0 + lock_x1) / 2, 0, lock_bottom], lock_w / 4))
    # The grip: from under the lock's rear, down and back to the butt cap.
    rc = E["cap_radius"] * H
    gx_back = -L / 2 + rc
    gdepth = E["grip_depth"] * L
    pts = [(lock_x0 + 0.35 * lock_len, lock_bottom + 2.0), (lock_x0 + 0.35 * lock_len, lock_top - 2.0),
           (gx_back, rc * 1.4), (gx_back + gdepth * 0.55, rc * 0.3)]
    gw = E["grip_width"] * W
    shapes.append(_prism("Grip", [pts[1], pts[2], pts[3], pts[0]], gw))
    # The butt cap: round seen from the side, across the grip's full width, so
    # the grip's back corner is wholly inside it (a ball narrower than the grip
    # left that corner out as a 0.33 mm wedge, 2026-11-05).
    shapes.append(_across("Butt cap", rc, gw + 2.0, gx_back, rc))
    rg = E["guard_radius"] * H
    gx = lock_x0 + 0.55 * lock_len
    gz = lock_bottom - rg + 3.0
    shapes.append(_across("Trigger guard", rg, 5.0, gx, gz))
    shapes.append(_across("Guard opening", rg - 3.0, 7.0, gx, gz - 1.0, op="cut"))
    if detail:
        shapes.append(_box("Trigger", [3.0, 3.0, rg * 0.9], [gx, 0, lock_bottom - rg * 0.9 + 1.0]))
        shapes.append(_box("Lock plate", [0.75 * lock_len, 2.5, 0.5 * (lock_top - lock_bottom)],
                           [(lock_x0 + lock_x1) / 2, lock_w / 2 + 1.0, lock_bottom + 0.3 * (lock_top - lock_bottom)]))
        shapes.append(_box("Hammer", [9.0, 4.0, 0.06 * H],
                           [lock_x0 + 0.35 * lock_len, lock_w / 2 + 2.0, lock_top - 4.0]))
        shapes.append(_box("Pan", [9.0, 7.0, 6.0], [lock_x1 - 0.2 * lock_len, lock_w / 2 + 2.0, lock_top - 8.0]))
        # Half out under the fore-end, where a ramrod shows (a hair higher, it
        # was hidden inside it).
        shapes.append(_lying("Ramrod", "cylinder", 2.0, (fore_x1 - xb) * 0.9, xb + 3.0, 0,
                             zb - fore_d + rb * 0.15))
        # 2 mm proud and 5 long: at 1 mm proud it left a 0.33 mm lip (2026-11-05).
        shapes.append(_lying("Muzzle ring", "cylinder", rm + 2.0, 5.0, xm - 5.0, 0, zb))
    estimated += ["the lock", "the grip", "the trigger guard"]
    return shapes, estimated


# ------------------------------------------------------------ the sword
# A prop: it lies flat (width across y, thickness up), its edges square and
# at least EDGE_MM thick: nothing here is sharp.
SWORD_ESTIMATES = {
    "blade": 0.75,                  # of L, when the brief gives no blade length
    "blade_width": 0.20,            # of W (the guard's width)
    "point": 0.12,                  # of the blade: the taper to the point
    "grip_radius": 0.38,            # of H
    "guard_thick": 0.035,           # of L, along the sword
    "pommel": 0.62,                 # of H, its radius
}
EDGE_MM = 3.0


def sword(size, facts: dict, words: str, detail: bool) -> tuple[list[dict], list[str]]:
    E = SWORD_ESTIMATES
    L, W, H = size
    estimated = []
    blade = float(facts.get("blade_mm") or 0) or E["blade"] * L
    if not facts.get("blade_mm"):
        estimated.append("blade length")
    bw = max(EDGE_MM * 4, E["blade_width"] * W)
    t = max(EDGE_MM, 0.32 * H)                      # the blade's thickness
    zc = H / 2                                      # the sword's middle, above the ground
    xg = L / 2 - blade                              # where the blade meets the guard
    tip = E["point"] * blade
    # The point is blunt: a flat twice EDGE_MM across (a prop; and a true point
    # thins to nothing).
    flat = EDGE_MM
    outline = [(xg, -bw / 2), (L / 2 - tip, -bw / 2), (L / 2, -flat), (L / 2, flat),
               (L / 2 - tip, bw / 2), (xg, bw / 2)]
    # Drawn in (x, z) and turned a quarter about x, so it lies flat: its outline
    # across y, its thickness up.
    shapes = [_prism("Blade", outline, t, at=(0.0, 0.0, zc), rotate=(90, 0, 0))]
    gt = E["guard_thick"] * L
    # With quillon ends (B) the guard stops inside them: a ball just touching a
    # flat end left a seam that was not solid (2026-11-05).
    rq = H * 0.32
    gw = W - rq if detail else W
    shapes.append(_rounded("Crossguard", [gt, gw, H * 0.5], [xg - gt / 2 + 0.5, 0, zc - H * 0.25], gt / 2.5))
    # The grip fills what is left between the guard and the pommel, which ends
    # the sword.
    rp = min(E["pommel"] * H, H / 2)
    xp = -L / 2 + rp
    grip = max(20.0, (xg - gt) - (xp + 0.6 * rp))
    rgr = E["grip_radius"] * H
    shapes.append(_lying("Grip", "cylinder", rgr, grip + 1.0, xg - gt - grip, 0, zc))
    shapes.append(_ball("Pommel", rp, (xp, 0, zc)))
    if detail:
        shapes.append(_ball("Quillon end", rq, (xg - gt / 2 + 0.5, W / 2 - rq, zc)))
        shapes.append(_ball("Quillon end", rq, (xg - gt / 2 + 0.5, -(W / 2 - rq), zc)))
        for k in range(1, 4):
            shapes.append(_lying("Grip wrap", "cylinder", rgr + 1.0, 3.0,
                                 xg - gt - grip * k / 4 - 1.5, 0, zc))
        shapes.append(_rounded("Ricasso", [0.06 * blade, bw * 0.9, t + 2.0],
                               [xg + 0.03 * blade, 0, zc - (t + 2.0) / 2], 1.5))
        # Square-ended where the point's taper starts: tapered with it, it thinned
        # to 1.0 mm (2026-11-05).
        ridge = [(xg + 0.06 * blade, -1.5), (L / 2 - tip, -1.5), (L / 2 - tip, 1.5),
                 (xg + 0.06 * blade, 1.5)]
        shapes.append(_prism("Fuller ridge", ridge, t + 1.6, at=(0.0, 0.0, zc), rotate=(90, 0, 0)))
    estimated += ["the guard", "the grip", "the pommel"]
    return shapes, estimated


# ------------------------------------------------------------ the lighthouse
LIGHTHOUSE_ESTIMATES = {
    "plinth": 0.06,                 # of H
    "tower": 0.68,                  # of H
    "tower_top": 0.62,              # of the tower's foot radius
    "gallery": 0.035,               # of H, its thickness
    "lantern": 0.11,                # of H
    "lantern_radius": 0.55,         # of the tower's top radius... of the gallery's
}


def lighthouse(size, facts: dict, words: str, detail: bool) -> tuple[list[dict], list[str]]:
    E = LIGHTHOUSE_ESTIMATES
    L, W, H = size
    R = min(L, W) / 2                               # the plinth's radius
    h_pl, h_tw, h_ga, h_la = E["plinth"] * H, E["tower"] * H, E["gallery"] * H, E["lantern"] * H
    r_tw = 0.78 * R
    r_top = E["tower_top"] * r_tw
    r_ga = r_top * 1.35
    r_la = r_ga * E["lantern_radius"] * 1.2
    z = 0.0
    shapes = [_upright("Plinth", "cylinder", R, h_pl, 0, 0, z)]
    z += h_pl
    shapes.append(_upright("Tower", "cone", r_tw, h_tw, 0, 0, z - 0.5, top=r_top))
    z += h_tw - 0.5
    shapes.append(_upright("Gallery", "cylinder", r_ga, h_ga, 0, 0, z - 0.5))
    z += h_ga - 0.5
    shapes.append(_upright("Lantern room", "cylinder", r_la, h_la, 0, 0, z - 0.5))
    z += h_la - 0.5
    roof = H - z - (0.03 * H if detail else 0)
    # An eave under the cone: a cone's own rim thins to nothing (1.08 mm, 2026-11-05).
    eave = max(2.5, 0.012 * H)
    shapes.append(_upright("Eave", "cylinder", r_la * 1.12, eave, 0, 0, z - 0.5))
    shapes.append(_upright("Roof", "cone", r_la * 1.12, roof - eave, 0, 0, z - 0.5 + eave - 0.3,
                           top=r_la * 0.12))
    if detail:
        shapes.append(_ball("Finial", 0.03 * H, (0, 0, H - 0.03 * H)))
        dh = 0.12 * H
        shapes.append(_box("Door", [0.22 * r_tw * 2, 4.0, dh], [r_tw * 0.98 + 1.0, 0, h_pl - 0.5],
                           rotate=(0, 0, 90)))
        for k, f in enumerate((0.35, 0.6, 0.82), 1):
            zf = h_pl + f * h_tw
            rr = r_tw + (r_top - r_tw) * f
            shapes.append(_upright(f"Band {k}", "cone", rr + 1.0, 0.045 * H, 0, 0, zf,
                                   top=r_tw + (r_top - r_tw) * (f + 0.045 * H / h_tw) + 1.0))
        shapes.append(_upright("Railing", "cylinder", r_ga * 0.96, 0.03 * H, 0, 0,
                               h_pl + h_tw + h_ga - 1.5))
    estimated = ["the tower's taper", "the gallery", "the lantern room", "the roof"]
    return shapes, estimated


# ------------------------------------------------------------ the rocket
ROCKET_ESTIMATES = {
    "body_radius": 0.055,           # of H
    "nose": 0.22,                   # of H
    "fin_height": 0.22,             # of H
    "nozzle": 0.05,                 # of H
}


def rocket(size, facts: dict, words: str, detail: bool) -> tuple[list[dict], list[str]]:
    E = ROCKET_ESTIMATES
    L, W, H = size
    rb = E["body_radius"] * H
    h_nz = E["nozzle"] * H
    h_nose = E["nose"] * H
    span = min(L, W) / 2                            # a fin's tip from the middle
    h_fin = E["fin_height"] * H
    # The nozzle sits under the body, on the ground; the fins reach the ground too.
    shapes = [_upright("Nozzle", "cone", rb * 0.55, h_nz + 0.5, 0, 0, 0, top=rb * 0.8)]
    body_z = h_nz
    body_h = H - h_nz - h_nose
    shapes.append(_upright("Body", "cylinder", rb, body_h + 0.5, 0, 0, body_z))
    shapes.append(_upright("Nose cone", "cone", rb, h_nose, 0, 0, body_z + body_h, top=0.6))
    # A fin: its outline from the body's side out to the tip and down to the
    # ground, drawn on +x and turned about z for each of four.
    fin = [(rb * 0.6, h_nz + h_fin), (rb * 0.6, h_nz * 0.5), (span - 4.0, 0.0), (span, 0.0),
           (span, 6.0)]
    t = max(3.0, 0.012 * H)
    for k, ang in enumerate((0, 90, 180, 270), 1):
        shapes.append(_prism(f"Fin {k}", fin, t, rotate=(0, 0, ang)))
    if detail:
        shapes.append(_upright("Band", "cylinder", rb + 1.2, 0.025 * H, 0, 0, body_z + 0.55 * body_h))
        shapes.append(_upright("Band", "cylinder", rb + 1.2, 0.02 * H, 0, 0, body_z + body_h - 0.02 * H))
        shapes.append(_lying("Window", "cylinder", rb * 0.32, 4.0, rb - 1.0, 0, body_z + 0.75 * body_h))
        shapes.append(_ball("Nose tip", max(1.5, rb * 0.12), (0, 0, H - rb * 0.1)))
    estimated = ["the body's thickness", "the nose", "the fins"]
    return shapes, estimated


# ------------------------------------------------------------ the house
HOUSE_ESTIMATES = {
    "walls": 0.55,                  # of H: the walls' height; the roof is the rest
    "eaves": 0.05,                  # of L: the roof overhangs this much
    "chimney": 0.10,                # of L, its side
    "door_w": 0.13, "door_h": 0.55,  # of L, of the walls
    "window": 0.14,                 # of L, a side
}


def house(size, facts: dict, words: str, detail: bool) -> tuple[list[dict], list[str]]:
    E = HOUSE_ESTIMATES
    L, W, H = size
    eave = E["eaves"] * L
    wl, ww = L - 2 * eave, W - 2 * eave
    hw = E["walls"] * H
    shapes = [_box("Walls", [wl, ww, hw], [0, 0, 0])]
    # The gable roof: a triangle across the house (in y, z), run along its length.
    # Drawn as a prism in (x, z) and turned a quarter about z, so x becomes y.
    ridge = 0.93 * H                                # the chimney rises above it, to H
    tri = [(-W / 2, hw - 2.0), (W / 2, hw - 2.0), (0.0, ridge)]
    shapes.append(_prism("Roof", tri, L, rotate=(0, 0, 90)))
    ch = E["chimney"] * L
    shapes.append(_box("Chimney", [ch, ch, 0.33 * H], [wl * 0.28, ww * 0.18, 0.67 * H]))
    dw, dh = E["door_w"] * L, E["door_h"] * hw
    shapes.append(_box("Door", [dw, 3.0, dh], [0, -ww / 2 - 1.0, 0]))
    if detail:
        win = E["window"] * L
        for k, x in enumerate((-wl * 0.3, wl * 0.3), 1):
            shapes.append(_box(f"Window {k}", [win, 2.5, win], [x, -ww / 2 - 0.75, hw * 0.4]))
            shapes.append(_box(f"Back window {k}", [win, 2.5, win], [x, ww / 2 + 0.75, hw * 0.4]))
        shapes.append(_box("Doorstep", [dw * 1.5, 0.06 * W, 3.0], [0, -ww / 2 - 0.03 * W + 0.5, 0]))
        shapes.append(_box("Chimney cap", [ch * 1.3, ch * 1.3, 4.0], [wl * 0.28, ww * 0.18, H - 4.0]))
    estimated = ["the walls' height", "the roof", "the chimney", "the door and windows"]
    return shapes, estimated


BUILDERS = {"long_gun": long_gun, "pistol": pistol, "sword": sword,
            "lighthouse": lighthouse, "rocket": rocket, "house": house}


def build(brief, size_mm, detail: bool) -> tuple[dict, list[str]]:
    """A concept's shapes (a modelkit spec, with labels) and what is said
    about it. UnknownObject where no family knows it, or its size is not
    given."""
    text = " ".join([brief.name or "", brief.function or ""])
    fam = family_of(text)
    if fam is None:
        raise UnknownObject(f"Nemo's code knows how to build only these kinds of object yet: "
                            f"{known()}; this brief names none of them")
    size = ([float(v) for v in (size_mm or [])] + [0.0, 0.0, 0.0])[:3]
    if not any(v > 0 for v in size):
        raise UnknownObject("give the object's real size (Brief: real size, long x wide x "
                            "high in mm; one of them will do) so its parts can be laid out")
    facts = dict(getattr(brief, "shape_facts", None) or {})
    # A size not given: from the first one given, in the family's proportions.
    first = next(i for i in range(3) if size[i] > 0)
    scale = size[first] / fam.ratio[first]
    full = [v if v > 0 else fam.ratio[i] * scale for i, v in enumerate(size)]
    shapes, estimated = BUILDERS[fam.key](full, facts, text, detail)
    given = [w for w, v in zip(("length", "width", "height"), size) if v > 0]
    given += [f.replace("_mm", "").replace("_", " ") for f in fam.facts if facts.get(f)]
    for w, v in reversed(list(zip(("length", "width", "height"), size))):
        if v <= 0:
            estimated.insert(0, w)
    said = [f"Built by code as a {fam.title}: {len(shapes)} shapes."
            f" Measured, from the brief: {', '.join(given)}."
            f" Estimated (rules of thumb, not measured): {', '.join(estimated)}."]
    return {"name": brief.name or "object", "shapes": shapes}, said
