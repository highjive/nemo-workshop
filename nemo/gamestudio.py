"""The Game Studio (owner, 2026-11-09): games made in Godot from the owner's own idea.

He asked for it built "using Claude Code Game Studio files with the Godot as the
engine", and that "games are created from the ideas I tell it, not the questions
about my gaming history". From the Claude Code Game Studios template (MIT, Donchitos,
read in a folder of the owner's own game) Nemo takes its PROCESS (an idea, a design, a build, a
test before anyone plays) and its Godot 4.4-4.7 notes; its 49 agents and its
onboarding questions are for Claude, not for Nemo's small models, and are not used.

The studio's people:

  Game Designer   reads the idea by CODE: the kind of game, and its settings
                  (title, player, what to collect, the goal, levels, speed, colours).
                  What the idea does not say is chosen by code and said.
  Level Designer  builds each level by code and checks every jump can be made
                  (the arc's height and reach from the game's own gravity and speed)
                  before it is kept.
  Programmer      writes the Godot project by CODE for a kind it knows (docs/design-rules.md 4d:
                  the small model fails at whole files). For an idea of no known kind,
                  the desktop's model writes one script, marked as the model's, and
                  the Tester judges it; it is sent back once with Godot's own words.
  Tester          runs the game in Godot with no window (--headless): every level is
                  built and its player stands on its first platform, or it fails,
                  with Godot's words.
  Writer          README.md: how to play, the keys, what it was made from.

The owner's choices (2026-11-09): kinds built by code, the model for the rest; the
DESKTOP only (Godot 4.7.2 is not proven on the AH531: no AVX, Sandy Bridge graphics);
not in NemoIso yet; the first kind is the platformer.
"""
from __future__ import annotations

import json
import math
import random
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .gui import prompt_logic as L


class StudioError(RuntimeError):
    """What the Game Studio cannot do, for the owner."""


# ------------------------------------------------------------------ Godot
GODOT_DIRS = ("C:/Godot", "C:/Nemo/tools/godot")


def godot(cfg=None, console: bool = True) -> Path | None:
    """Godot's program: paths.godot in config, else the newest in GODOT_DIRS. The
    console one (its words on stdout) for checking, the windowed one for playing."""
    given = cfg.get("paths.godot") if cfg is not None else None
    found = [Path(given)] if given else []
    for d in GODOT_DIRS:
        found += sorted(Path(d).glob("Godot_v4*_win64.exe"), reverse=True)
    for p in found:
        if p.is_file():
            if console:
                c = p.with_name(p.stem + "_console.exe")
                return c if c.is_file() else p
            return p
    return None


def available(cfg=None) -> tuple[bool, str]:
    """(can the Studio work here, why not)."""
    from . import machine
    if not machine.is_desktop(cfg):
        return False, ("the Game Studio is the desktop's: Godot 4.7.2 is not proven on this "
                       "computer (it needs a graphics card and processor not yet tried here)")
    if godot(cfg) is None:
        return False, "Godot is not installed (looked for Godot_v4*_win64.exe in C:\\Godot)"
    return True, ""


def folder(cfg) -> Path:
    return cfg.path("paths.studio")


MODEL_MODE = "game"          # the desktop's mode for model-written games (config.py)


def model_mode(cfg) -> str | None:
    """The mode a game no code builds is written in: Game (Gemma 4 E4B, adopted
    2026-11-11 as the only model whose games passed the Tester), where this machine
    has it; else None, and whatever is loaded is used."""
    from . import machine
    if machine.is_desktop(cfg) and cfg.get(f"modes_desktop.{MODEL_MODE}") is not None:
        return MODEL_MODE
    return None


# ------------------------------------------------------------------ the Designer
@dataclass
class Spec:
    kind: str
    title: str
    player: str = "hero"
    collect: str = "coins"
    goal: str = "the flag"
    levels: int = 3
    speed: float = 1.0               # times the kind's own
    gravity: float = 1.0
    player_colour: str = "orange"
    back: str = "day"
    seed: int = 1
    idea: str = ""
    said: list[str] = field(default_factory=list)   # what was read, and what was chosen


KINDS = {
    "platformer": ("platformer", "platform", "platforms", "jump", "jumping", "jumps",
                   "side-scrolling", "side scrolling", "run and jump", "ledges"),
}

COLOURS = {"red": (0.85, 0.2, 0.2), "orange": (0.95, 0.55, 0.15), "yellow": (0.95, 0.85, 0.2),
           "green": (0.3, 0.75, 0.3), "blue": (0.25, 0.45, 0.9), "purple": (0.6, 0.35, 0.8),
           "pink": (0.95, 0.5, 0.7), "white": (0.95, 0.95, 0.95), "black": (0.12, 0.12, 0.12),
           "brown": (0.55, 0.35, 0.2), "grey": (0.55, 0.55, 0.55), "gray": (0.55, 0.55, 0.55)}
BACKS = {"night": ("night", "dark", "space", "cave", "caves", "underground", "moon", "stars"),
         "day": ("day", "sky", "sunny", "meadow", "garden", "forest", "beach")}
BACK_COLOURS = {"day": (0.55, 0.78, 0.95), "night": (0.08, 0.09, 0.18)}
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10}
MAX_LEVELS = 10


# A thing named in the idea: one word, or two where the second is no joining word
# (2026-11-09: "collects acorns and must reach ..." was read as "acorns and").
_NOUN = (r"([a-z]+(?:\s+(?!(?:and|or|but|to|then|while|before|on|in|at|with|must|who|that|"
         r"which|so|for|from|of|as)\b)[a-z]+)?)")


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text, re.I) for w in words)


def kind_of(idea: str) -> str | None:
    """The kind of game the idea names, or None (then the model writes it)."""
    for kind, words in KINDS.items():
        if _has(idea, *words):
            return kind
    return None


def design(idea: str, kind: str | None = None) -> Spec:
    """The Game Designer: the idea read by code, nothing asked of the owner."""
    t = " ".join(idea.split())
    kind = kind or kind_of(t)
    if kind is None:
        raise StudioError("no kind Nemo builds by code fits that idea")
    said = []
    m = re.search(r"[\"\u201c]([^\"\u201d]{2,40})[\"\u201d]|\b(?:called|named|titled)\s+"
                  r"([A-Z][\w' ]{1,38}?)(?=[,.;]|\s+(?:where|in which|about|with|that)\b|$)", t)
    title = (m.group(1) or m.group(2)).strip() if m else ""
    if title:
        said.append(f"title '{title}' (your words)")
    else:
        title = L.name_for(t).title() or "My Game"
        said.append(f"title '{title}' (from your idea; you gave none)")
    spec = Spec(kind, title, idea=t)
    m = re.search(r"\b(?:play(?:s|ing)?\s+as|you\s+are|starring|about)\s+(?:a|an|the)?\s*"
                  r"((?:[a-z]+\s)?[a-z]+?)\b(?=\s+(?:who|that|which|and|in|on|collect|jump|"
                  r"runs?|must|has|with|to|through)\b|[,.;]|$)", t, re.I)
    if m:
        spec.player = m.group(1).lower()
        said.append(f"you play {spec.player} (your words)")
    else:
        said.append(f"you play a {spec.player} (not said)")
    m = re.search(r"\bcollect(?:s|ing)?\s+(?:all\s+(?:the\s+)?)?(?:\d+\s+)?(?:the\s+)?" + _NOUN,
                  t, re.I)
    if m:
        spec.collect = m.group(1).lower().rstrip(".")
        said.append(f"collect {spec.collect} (your words)")
    else:
        said.append(f"collect {spec.collect} (not said)")
    m = re.search(r"\b(?:reach(?:es)?|get(?:s)?\s+to|find(?:s)?)\s+(?:the\s+)?" + _NOUN, t, re.I)
    if m:
        spec.goal = "the " + m.group(1).lower().rstrip(".")
        said.append(f"the goal is {spec.goal} (your words)")
    else:
        said.append(f"the goal is {spec.goal} at each level's end (not said)")
    m = re.search(r"\b(\d+|" + "|".join(_NUMBERS) + r")\s+levels?\b", t, re.I)
    if m:
        n = m.group(1).lower()
        spec.levels = max(1, min(MAX_LEVELS, int(n) if n.isdigit() else _NUMBERS[n]))
        said.append(f"{spec.levels} levels" + (" (your words)" if spec.levels == (
            int(n) if n.isdigit() else _NUMBERS[n]) else f" (at most {MAX_LEVELS})"))
    else:
        said.append(f"{spec.levels} levels (not said)")
    if _has(t, "fast", "quick", "speedy", "rushing"):
        spec.speed = 1.3; said.append("fast (your words)")
    elif _has(t, "slow", "gentle", "easy", "relaxed"):
        spec.speed = 0.8; said.append("slower (your words)")
    if _has(t, "floaty", "low gravity", "moon", "space", "bouncy"):
        spec.gravity = 0.6; said.append("floaty jumps (your words)")
    elif _has(t, "heavy", "high gravity"):
        spec.gravity = 1.3; said.append("heavy jumps (your words)")
    colour = next((c for c in COLOURS if _has(t, c)), "")
    if colour:
        spec.player_colour = colour
        said.append(f"a {colour} player (your words)")
    spec.back = next((b for b, words in BACKS.items() if _has(t, *words)), "day")
    spec.seed = sum(ord(ch) for ch in t) % 100000 + 1
    spec.said = said
    return spec


# ------------------------------------------------------------------ the Level Designer
GRAVITY, JUMP, SPEED = 1400.0, 620.0, 260.0      # the platformer's own, px and seconds
MARGIN = 0.8                                     # every jump within 80 % of what can be made
TOP, BOTTOM, THICK = 180, 560, 24


@dataclass
class Level:
    start: tuple[int, int]
    platforms: list[tuple[int, int, int]]        # x (left), y (top), width
    coins: list[tuple[int, int]]
    goal: tuple[int, int]


def physics(spec: Spec) -> tuple[float, float, float]:
    return GRAVITY * spec.gravity, JUMP, SPEED * spec.speed


def reach(g: float, v: float, speed: float, rise: float) -> float:
    """How far across a jump carries to land `rise` px higher (negative = lower)."""
    if rise > v * v / (2 * g):
        return 0.0
    t = (v + math.sqrt(v * v - 2 * g * rise)) / g    # coming down onto the higher ledge
    return speed * t


def jump_faults(level: Level, g: float, v: float, speed: float) -> list[str]:
    """Each jump between neighbouring platforms that cannot be made with room to spare."""
    out = []
    ps = level.platforms
    for i, (a, b) in enumerate(zip(ps, ps[1:]), 1):
        gap = b[0] - (a[0] + a[2])
        rise = a[1] - b[1]
        if rise > MARGIN * v * v / (2 * g):
            out.append(f"jump {i}: {rise} px up, more than the jump's height allows")
        elif gap > MARGIN * reach(g, v, speed, rise):
            out.append(f"jump {i}: {gap} px across, further than the jump carries")
    return out


def build_levels(spec: Spec) -> list[Level]:
    """Every level, each jump checked; a level that fails its check is not kept."""
    g, v, speed = physics(spec)
    rng = random.Random(spec.seed)
    levels = []
    for n in range(spec.levels):
        for _ in range(200):
            x, y = 0, 480
            plats = [(x, y, 320)]
            for _ in range(7 + 2 * n):
                last = plats[-1]
                rise = rng.randint(-120, int(MARGIN * 0.8 * v * v / (2 * g)))
                ny = max(TOP, min(BOTTOM, last[1] - rise))
                rise = last[1] - ny
                far = int(MARGIN * 0.9 * reach(g, v, speed, rise))
                gap = rng.randint(min(60, far), max(min(60, far), far))
                plats.append((last[0] + last[2] + gap, ny, rng.randint(120, 260)))
            lv = Level((60, 480 - 60), plats,
                       [(p[0] + p[2] // 2, p[1] - 48) for p in plats[1:-1]],
                       (plats[-1][0] + plats[-1][2] - 40, plats[-1][1]))
            if not jump_faults(lv, g, v, speed):
                levels.append(lv)
                break
        else:
            raise StudioError(f"level {n + 1}: no layout with every jump possible was found")
    return levels


# ------------------------------------------------------------------ the Programmer
def _colour(rgb) -> str:
    return "Color(%.3f, %.3f, %.3f)" % tuple(rgb)


def _gd_levels(levels: list[Level]) -> str:
    rows = []
    for lv in levels:
        rows.append("\t{\"start\": [%d, %d], \"platforms\": [%s], \"coins\": [%s], \"goal\": [%d, %d]}" % (
            lv.start[0], lv.start[1],
            ", ".join(f"[{x}, {y}, {w}]" for x, y, w in lv.platforms),
            ", ".join(f"[{x}, {y}]" for x, y in lv.coins), lv.goal[0], lv.goal[1]))
    return "[\n" + ",\n".join(rows) + ",\n]"


def _q(text: str) -> str:
    return json.dumps(text)


def platformer_script(spec: Spec, levels: list[Level]) -> str:
    """main.gd, written by code (no model). Godot 4.7: no typed overrides (4.7 wants an
    explicit return from those), every node made here, nothing loaded from files."""
    g, v, speed = physics(spec)
    return f'''# {spec.title}: written by Nemo's Game Studio from the idea:
#   {spec.idea}
# Made by code (nemo/gamestudio.py), not by a language model. Godot 4.7.
extends Node2D

const TITLE = {_q(spec.title)}
const PLAYER = {_q(spec.player)}
const COLLECT = {_q(spec.collect)}
const GOAL = {_q(spec.goal)}
const GRAVITY = {g:.1f}
const JUMP = {v:.1f}
const SPEED = {speed:.1f}
const PLAYER_COLOUR = {_colour(COLOURS[spec.player_colour])}
const BACK_COLOUR = {_colour(BACK_COLOURS[spec.back])}
const FALL_Y = 900.0
const LEVELS = {_gd_levels(levels)}

var level = 0
var score = 0
var world = null
var player = null
var label = null
var message = ""
var testing = false
var frames = 0


func _ready():
	testing = "--nemo-test" in OS.get_cmdline_user_args()
	RenderingServer.set_default_clear_color(BACK_COLOUR)
	var hud = CanvasLayer.new()
	add_child(hud)
	label = Label.new()
	label.position = Vector2(16, 12)
	label.add_theme_font_size_override("font_size", 24)
	hud.add_child(label)
	build(0)


func build(i):
	level = i
	frames = 0
	if world != null:
		world.queue_free()
	world = Node2D.new()
	add_child(world)
	var data = LEVELS[i]
	for p in data["platforms"]:
		add_platform(p[0], p[1], p[2])
	for c in data["coins"]:
		add_coin(c[0], c[1])
	add_goal(data["goal"][0], data["goal"][1])
	player = make_player(data["start"][0], data["start"][1])
	world.add_child(player)
	# Made current once it is in the tree (Godot said "!is_inside_tree()" before).
	player.get_node("Camera").make_current()
	message = ""


func add_platform(x, y, w):
	var body = StaticBody2D.new()
	body.position = Vector2(x + w / 2.0, y + {THICK} / 2.0)
	var shape = CollisionShape2D.new()
	var rect = RectangleShape2D.new()
	rect.size = Vector2(w, {THICK})
	shape.shape = rect
	body.add_child(shape)
	var look = ColorRect.new()
	look.color = Color(0.36, 0.25, 0.14)
	look.size = Vector2(w, {THICK})
	look.position = Vector2(-w / 2.0, -{THICK} / 2.0)
	body.add_child(look)
	world.add_child(body)


func add_coin(x, y):
	var area = Area2D.new()
	area.position = Vector2(x, y)
	var shape = CollisionShape2D.new()
	var circle = CircleShape2D.new()
	circle.radius = 14.0
	shape.shape = circle
	area.add_child(shape)
	var look = Polygon2D.new()
	look.polygon = PackedVector2Array([Vector2(0, -12), Vector2(12, 0), Vector2(0, 12), Vector2(-12, 0)])
	look.color = Color(1.0, 0.8, 0.1)
	area.add_child(look)
	area.body_entered.connect(func(body): collect(area, body))
	world.add_child(area)


func add_goal(x, y):
	var area = Area2D.new()
	area.position = Vector2(x, y - 40)
	var shape = CollisionShape2D.new()
	var rect = RectangleShape2D.new()
	rect.size = Vector2(24, 80)
	shape.shape = rect
	area.add_child(shape)
	var pole = ColorRect.new()
	pole.color = Color(0.9, 0.9, 0.9)
	pole.size = Vector2(6, 80)
	pole.position = Vector2(-3, -40)
	area.add_child(pole)
	var flag = Polygon2D.new()
	flag.polygon = PackedVector2Array([Vector2(3, -40), Vector2(34, -28), Vector2(3, -16)])
	flag.color = Color(0.9, 0.2, 0.2)
	area.add_child(flag)
	area.body_entered.connect(func(body): reach_goal(body))
	world.add_child(area)


func make_player(x, y):
	var body = CharacterBody2D.new()
	body.position = Vector2(x, y)
	var shape = CollisionShape2D.new()
	var rect = RectangleShape2D.new()
	rect.size = Vector2(32, 44)
	shape.shape = rect
	body.add_child(shape)
	var look = ColorRect.new()
	look.color = PLAYER_COLOUR
	look.size = Vector2(32, 44)
	look.position = Vector2(-16, -22)
	body.add_child(look)
	var camera = Camera2D.new()
	camera.name = "Camera"
	body.add_child(camera)
	return body


func collect(area, body):
	if body == player and is_instance_valid(area):
		score += 1
		area.queue_free()


func reach_goal(body):
	if body != player or testing:
		return
	if level + 1 < LEVELS.size():
		call_deferred("build", level + 1)
	else:
		message = "You reached %s on every level! %s: %d" % [GOAL, COLLECT.capitalize(), score]


func _physics_process(delta):
	if player == null or not is_instance_valid(player):
		return
	var dir = 0.0
	if not testing:
		dir = Input.get_axis("ui_left", "ui_right")
	player.velocity.x = dir * SPEED
	if player.is_on_floor():
		player.velocity.y = 0.0
		if not testing and (Input.is_action_just_pressed("ui_accept") or Input.is_action_just_pressed("ui_up")):
			player.velocity.y = -JUMP
	else:
		player.velocity.y += GRAVITY * delta
	player.move_and_slide()
	if player.position.y > FALL_Y:
		call_deferred("build", level)
	label.text = "%s   Level %d of %d   %s: %d   %s" % [TITLE, level + 1, LEVELS.size(), COLLECT.capitalize(), score, message]
	if testing:
		frames += 1
		if frames == 90:
			report()


func report():
	var data = LEVELS[level]
	print("NEMO LEVEL %d of %d: platforms %d, %s %d, standing %s" % [level + 1, LEVELS.size(), data["platforms"].size(), COLLECT, data["coins"].size(), player.is_on_floor()])
	if level + 1 < LEVELS.size():
		call_deferred("build", level + 1)
	else:
		print("NEMO DONE")
		get_tree().quit()
'''


PROJECT = """; Written by Nemo's Game Studio. Godot 4.7.
config_version=5

[application]

config/name={name}
run/main_scene="res://main.tscn"
config/features=PackedStringArray("4.7")

[display]

window/size/viewport_width=1280
window/size/viewport_height=720
window/stretch/mode="canvas_items"
window/stretch/aspect="expand"

[rendering]

renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""

SCENE = """[gd_scene format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node2D"]
script = ExtResource("1")
"""


# For a script the model wrote: Nemo's own test node beside it, so the model writes only
# the game (2026-11-09: asked to handle --nemo-test itself, the 8B wrote Python's
# "args has '--nemo-test'" three times, and the game never loaded).
HARNESS = """# Written by Nemo's Game Studio: its Tester's own node, not the game's.
extends Node

var frames = 0


func _physics_process(_delta):
	if not "--nemo-test" in OS.get_cmdline_user_args():
		return
	frames += 1
	if frames == 90:
		print("NEMO DONE")
		get_tree().quit()
"""

SCENE_WITH_HARNESS = """[gd_scene format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]
[ext_resource type="Script" path="res://nemo_test.gd" id="2"]

[node name="Main" type="Node2D"]
script = ExtResource("1")

[node name="NemoTest" type="Node" parent="."]
script = ExtResource("2")
"""


def write_project(where: Path, spec: Spec, script: str, harness: bool = False) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    (where / "project.godot").write_text(PROJECT.format(name=_q(spec.title)), encoding="utf-8",
                                         newline="\n")
    (where / "main.tscn").write_text(SCENE_WITH_HARNESS if harness else SCENE, encoding="utf-8",
                                     newline="\n")
    if harness:
        (where / "nemo_test.gd").write_text(HARNESS, encoding="utf-8", newline="\n")
    (where / "main.gd").write_text(script, encoding="utf-8", newline="\n")
    (where / "spec.json").write_text(json.dumps(asdict(spec), indent=2), encoding="utf-8")
    return where


# ------------------------------------------------------------------ the Tester
@dataclass
class Check:
    ok: bool
    levels: int = 0
    lines: list[str] = field(default_factory=list)      # Godot's words that matter
    seconds: float = 0.0


_BAD = re.compile(r"SCRIPT ERROR|Parse Error|Parser Error|^ERROR:|Failed to load script|"
                  r"Invalid call|Invalid access|Invalid get|Invalid set", re.M)


QUIT_AFTER = 3000      # frames: Godot stops itself even if the game never quits
_AT = re.compile(r"at: .*\(res://(\w+\.gd):(\d+)\)")


def located(out: str) -> list[str]:
    """Godot's error lines, each with the script line its next "at:" line names
    ("(main.gd line 63)"): told only the error, the model could not find it."""
    lines = out.splitlines()
    found = []
    for i, line in enumerate(lines):
        if not _BAD.search(line.strip()):
            continue
        at = _AT.search(lines[i + 1]) if i + 1 < len(lines) else None
        found.append(line.strip() + (f" ({at.group(1)} line {at.group(2)})" if at else ""))
    return found


def test(where: Path, cfg=None, levels: int | None = None, run=subprocess.run,
         timeout: int = 180) -> Check:
    """Run the game in Godot with no window. `levels`: a game built by code, whose every
    level must be built and stood on; None: a script the model wrote, which must load
    with no error and say NEMO DONE. Godot is told to stop after QUIT_AFTER frames, and
    what it said is kept even if it runs out of time (2026-11-09: a model's script that
    never quit ran the full 180 s, its parse error thrown away)."""
    exe = godot(cfg)
    if exe is None:
        return Check(False, lines=["Godot is not installed"])
    t0 = time.time()
    late = False
    try:
        p = run([str(exe), "--headless", "--quit-after", str(QUIT_AFTER), "--path", str(where),
                 "--", "--nemo-test"], capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as exc:
        late = True
        out = "".join(x.decode("utf-8", "replace") if isinstance(x, bytes) else (x or "")
                      for x in (exc.stdout, exc.stderr))
    took = time.time() - t0
    bad = located(out)
    reports = [l.strip() for l in out.splitlines() if l.startswith("NEMO LEVEL")]
    stood = sum(1 for l in reports if l.endswith("standing true"))
    done = "NEMO DONE" in out
    if levels is None:
        ok = not bad and done and not late
    else:
        ok = not bad and done and not late and stood == levels and levels > 0
    lines = bad[:12] + reports
    if late:
        lines.append(f"Godot did not finish in {timeout} s")
    if not done and not bad:
        lines.append("the game did not reach its end (no NEMO DONE)")
    return Check(ok, stood, lines, round(took, 1))


# ------------------------------------------------------------------ the Writer
def readme(spec: Spec, check: Check, by_model: bool = False) -> str:
    keys = ("Left and Right arrows to move, Space or Up to jump."
            if spec.kind == "platformer" else "See the game's own screen.")
    made = ("The script was WRITTEN BY THE LANGUAGE MODEL (no kind Nemo builds by code fitted "
            "the idea), then run by the Tester." if by_model else
            "Made by Nemo's code: the Level Designer checked every jump can be made.")
    return "\n".join([
        f"# {spec.title}", "", f"Your idea: {spec.idea}", "",
        "## How to play", "", keys,
        f"Collect the {spec.collect}; reach {spec.goal} to finish each level." if spec.kind ==
        "platformer" else "", "",
        "## What Nemo chose", "", *[f"- {s}" for s in spec.said], "",
        "## Made and tested", "", made,
        f"Tester: {'passed' if check.ok else 'FAILED'} in {check.seconds} s.", "",
        *[f"    {l}" for l in check.lines], "",
        "Play: `nemo studio play \"" + spec.title + "\"`, or open this folder in Godot 4.7.", ""])


# ------------------------------------------------------------------ the whole job
@dataclass
class Made:
    where: Path
    spec: Spec
    check: Check
    by_model: bool = False


def make(cfg, idea: str, router=None, say=print) -> Made:
    """An idea to a tested game, in <paths.studio>/<name>. Kinds by code; any other
    idea by the model (router), if one is given and loaded."""
    ok, why = available(cfg)
    if not ok:
        raise StudioError(why)
    root = folder(cfg)
    kind = kind_of(idea)
    taken = {p.name for p in root.iterdir()} if root.is_dir() else set()
    if kind is None:
        if router is None:
            raise StudioError("that idea is no kind Nemo builds by code (it builds: "
                              + ", ".join(KINDS) + "); the model is needed for it: load "
                              "Game mode and ask again")
        return _by_model(cfg, idea, router, root, taken, say)
    spec = design(idea, kind)
    say(f"Game Designer: a {kind}, '{spec.title}': " + "; ".join(spec.said) + ".")
    levels = build_levels(spec)
    say(f"Level Designer: {len(levels)} level(s), every jump checked.")
    where = write_project(root / L.name_for(spec.title, taken).replace(" ", "-"), spec,
                          platformer_script(spec, levels))
    say(f"Programmer: written by code to {where}.")
    check = test(where, cfg, levels=len(levels))
    say(f"Tester: {'passed' if check.ok else 'FAILED'}: " + "; ".join(check.lines[-3:]))
    (where / "README.md").write_text(readme(spec, check), encoding="utf-8")
    _record(cfg, check)
    return Made(where, spec, check)


MODEL_SYSTEM = """You write one Godot 4.7 GDScript file, main.gd, for a small 2D game.
It is attached to a Node2D. Build every node in code (no scenes, no files, no images):
shapes from ColorRect, Polygon2D, CollisionShape2D with RectangleShape2D or CircleShape2D.
Read input with Input.get_axis("ui_left", "ui_right"), Input.is_action_pressed and
Input.is_action_just_pressed on ui_left, ui_right, ui_up, ui_down and ui_accept.
Show the score and how to play with a Label on a CanvasLayer.
Do not give any function a return type. Keep it under 200 lines.
This is Godot 4, not Godot 3. Use the Godot 4 names: Sprite2D (not Sprite),
CharacterBody2D (not KinematicBody2D) whose velocity is a property and whose
move_and_slide() takes no arguments, Marker2D (not Position2D), @export and @onready
(not export and onready), await (not yield), instantiate() (not instance()),
randf_range and randi_range (not rand_range), Time.get_ticks_msec() (not OS's),
an Array's remove_at(index) (not remove), range(a, b) (not a..b).
Connect a signal as its_signal.connect(a_callable), never connect("name", self, "method").
Answer with the script only, in one ```gdscript block."""
# The renames above: Godot 4.0's own, and the template's deprecated-apis.md (Claude Code
# Game Studios, MIT): told none, qwen3-8b wrote Sprite and connect("...", self, "...").


_PLAYS = (r"(?:steer|fly|drive|guide|control|sail|ride|pilot|are|play as|be)\s+(?:a|an|the)?\s*"
          r"(?:(?:little|small|tiny|big|brave|lost|young|old)\s+)?([a-z]+)")


def model_title(idea: str) -> str:
    """A title for a game of no known kind: its quoted or called name, else what you
    play and what you collect ("Boat and the Stars"), else from the idea's words
    (2026-11-09: "Game Where Steer Little")."""
    m = re.search(r"[\"\u201c]([^\"\u201d]{2,40})[\"\u201d]|\b(?:called|named|titled)\s+([A-Z][\w' ]{1,38})", idea)
    if m:
        return (m.group(1) or m.group(2)).strip()
    who = re.search(_PLAYS, idea, re.I)
    what = re.search(r"\bcollect(?:s|ing)?\s+(?:all\s+)?(?:the\s+)?([a-z]+)", idea, re.I)
    if who and what:
        return f"{who.group(1).title()} and the {what.group(1).title()}"
    if who:
        return f"The {who.group(1).title()}"
    words = [w for w in L.name_for(idea).split() if w not in ("game", "games", "where", "which",
                                                              "you", "your", "play")]
    return " ".join(words[:3]).title() or "My Game"


TRIES = 3                      # the model's tries at a script, each judged by Godot


def redeclared(script: str) -> tuple[str, list[str]]:
    """Every 'var x' declared again while an outer 'x' of the same function is still in
    scope, made 'x =', the same variable used again: nothing the game does changes
    (2026-11-09: the 8B could not find it in three tries, and Godot names only the first
    of several). Scope is read from the indentation: a declaration at indent d holds until
    a line indented less than d."""
    rows = script.splitlines()
    done, seen = [], {}                         # name -> indent it was declared at
    for k, row in enumerate(rows):
        if not row.strip() or row.strip().startswith("#"):
            continue
        flat = row.expandtabs(4)
        indent = len(flat) - len(flat.lstrip())
        if indent == 0:
            seen = {}                           # a new function or the script's own level
        seen = {n: d for n, d in seen.items() if indent >= d}
        m = re.match(r"^(\s*)var\s+(\w+)\b(\s*:\s*\w+)?(\s*:?=)", row)
        if not m or indent == 0:
            continue
        name = m.group(2)
        if name in seen and seen[name] < indent:
            rows[k] = m.group(1) + name + (" =" if m.group(4).strip() == ":=" else m.group(4)) + \
                row[m.end():]
            done.append(f"'var {name}' declared again on line {k + 1}, used again")
        else:
            seen.setdefault(name, indent)
    return "\n".join(rows) + "\n", done


# Godot 3 members Godot 4 renamed, by Godot's own "Cannot find member" words.
MEMBERS = {("remove", "Array"): "remove_at"}


def godot_suggests(lines: list[str]) -> dict[str, str]:
    """Godot's own renames in its errors: 'Identifier "Sprite" not declared ... Did you mean
    to use "Sprite2D"?' -> {"Sprite": "Sprite2D"}; 'Cannot find member "remove" in base
    "Array"' -> {".remove(": ".remove_at("} (MEMBERS)."""
    out = {}
    for line in lines:
        m = re.search(r'Identifier "(\w+)" not declared.*?Did you mean to use "(\w+)"', line)
        if m:
            out[m.group(1)] = m.group(2)
        m = re.search(r'Cannot find member "(\w+)" in base "(\w+)"', line)
        if m and (m.group(1), m.group(2)) in MEMBERS:
            out[f".{m.group(1)}("] = f".{MEMBERS[(m.group(1), m.group(2))]}("
    return out


def slips(script: str) -> tuple[str, list[str]]:
    """The model's GDScript with slips put right that change no meaning, and what was
    done (2026-11-09, qwen3-8b): a code fence left in the script ("Unexpected '`'"),
    and Python's `for _ in` (GDScript wants a name: "Expected loop variable name")."""
    fixed = []
    lines = script.splitlines()
    kept = [l for l in lines if not l.strip().startswith("```")]
    if len(kept) != len(lines):
        fixed.append(f"{len(lines) - len(kept)} code fence line(s) taken out")
    text = "\n".join(kept) + "\n"
    text, n = re.subn(r"\bfor\s+_\s+in\b", "for _i in", text)
    if n:
        fixed.append(f"'for _ in' made 'for _i in' ({n})")
    # Python's "if A has B:" is GDScript's "if B in A:" (2026-11-09, three times running).
    text, n = re.subn(r"^(\s*(?:if|elif|while)\s+)(.+?)\s+has\s+(.+?)(\s*:\s*)$", r"\1\3 in \2\4",
                      text, flags=re.M)
    if n:
        fixed.append(f"'A has B' made 'B in A' ({n})")
    # Godot 3's connect("signal", self, "method") is Godot 4's signal.connect(method): the
    # template's deprecated-apis.md (Claude Code Game Studios) gives the mapping.
    text, n = re.subn(r"\b(?:(\w+(?:\.\w+)*)\.)?connect\(\s*\"(\w+)\"\s*,\s*self\s*,\s*\"(\w+)\"\s*\)",
                      lambda m: (f"{m.group(1)}." if m.group(1) else "") + f"{m.group(2)}.connect({m.group(3)})",
                      text)
    if n:
        fixed.append(f"Godot 3's connect(\"signal\", self, \"method\") made signal.connect(method) ({n})")
    # "for i in 0..3:" (another language's range) is GDScript's "for i in range(0, 3):".
    text, n = re.subn(r"^(\s*for\s+\w+\s+in\s+)(\w+)\s*\.\.\s*(\w+)(\s*:)", r"\1range(\2, \3)\4",
                      text, flags=re.M)
    if n:
        fixed.append(f"'for i in a..b' made 'for i in range(a, b)' ({n})")
    text, again = redeclared(text)
    fixed += again
    return text, fixed


def _by_model(cfg, idea, router, root, taken, say) -> Made:
    spec = Spec("by_model", model_title(idea), idea=idea,
                said=["no kind Nemo builds by code fits it: the model wrote the script"])
    where = root / L.name_for(spec.title, taken).replace(" ", "-")
    ask, check, script = idea, Check(False), ""
    for attempt in range(1, TRIES + 1):
        say(f"Programmer: the model writes the script (try {attempt} of {TRIES}).")
        reply = router.ask("template_fill", MODEL_SYSTEM, ask, max_tokens=3000)
        m = re.search(r"```(?:gdscript|gd)?\s*\n(.*?)```", reply.text, re.S)
        script, fixed = slips((m.group(1) if m else reply.text).strip() + "\n")
        if fixed:
            say("Programmer: put right in the model's script: " + "; ".join(fixed) + ".")
        write_project(where, spec, "# WRITTEN BY THE LANGUAGE MODEL, checked by Nemo's Tester.\n"
                      + script, harness=True)
        check = test(where, cfg, levels=None, timeout=90)
        renamed = godot_suggests(check.lines)
        if renamed and not check.ok:
            # Godot's own "Did you mean to use X?", applied by code and run again.
            for old, new in renamed.items():
                script = (script.replace(old, new) if old.startswith(".") else
                          re.sub(rf"\b{re.escape(old)}\b", new, script))
            say("Programmer: put right from Godot's words: " + ", ".join(
                f"{a} -> {b}" for a, b in renamed.items()) + ".")
            write_project(where, spec, "# WRITTEN BY THE LANGUAGE MODEL, checked by Nemo's "
                          "Tester.\n" + script, harness=True)
            check = test(where, cfg, levels=None, timeout=90)
        say(f"Tester: {'passed' if check.ok else 'FAILED'}: " + "; ".join(check.lines[:3]))
        if check.ok:
            break
        # Its own script back, with Godot's words: told only the error, it wrote a new
        # script from nothing and made new mistakes (2026-11-09).
        ask = (idea + "\n\nYour script:\n```gdscript\n" + script + "```\nGodot says: "
               + "; ".join(check.lines[:6]) + ". Put those lines right and give the whole "
               "script again.")
    (where / "README.md").write_text(readme(spec, check, by_model=True), encoding="utf-8")
    _record(cfg, check)
    return Made(where, spec, check, by_model=True)


def _record(cfg, check: Check) -> None:
    from . import timekeeper
    timekeeper.record("studio", "game test", check.seconds, check.ok)


def games(cfg) -> list[dict]:
    root = folder(cfg)
    out = []
    for p in sorted(root.glob("*/project.godot")) if root.is_dir() else []:
        try:
            spec = json.loads((p.parent / "spec.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            spec = {}
        out.append({"name": p.parent.name, "title": spec.get("title", p.parent.name),
                    "kind": spec.get("kind", "?"), "folder": p.parent})
    return out


def find(cfg, name: str) -> Path | None:
    want = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    for g in games(cfg):
        if want and want in (re.sub(r"[^a-z0-9]", "", g["name"].lower()),
                             re.sub(r"[^a-z0-9]", "", g["title"].lower())):
            return g["folder"]
    return None


def play(cfg, where: Path, popen=subprocess.Popen):
    """Open the game in its own window, to play. Nemo waits for nothing."""
    exe = godot(cfg, console=False)
    if exe is None:
        raise StudioError("Godot is not installed")
    return popen([str(exe), "--path", str(where)])
