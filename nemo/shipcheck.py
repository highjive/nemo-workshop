"""SHIP or DON'T SHIP: is a model fit for Nemo's jobs? (owner, 2026-11-04:
"run soup zero test", trysoup.dev/zero).

Soup (Apache-2.0) evaluates Hugging Face models and refuses .gguf files; it
cannot test a llama.cpp server, and it needs Python 3.13 or older. Nemo runs
quantised GGUF models through llama-server, and its rule is to check the
real thing. So the same idea is done here, against the models Nemo loads:

  tasks     Soup's own task-file format, one JSON object per line:
            {"prompt", "expected", "category", "scoring"}, scoring one of
            exact | contains | regex | answer, read as Soup reads them, so
            the file can be handed to `soup eval custom` too.
            make_tasks() writes them FROM THE PARTS LIBRARY: every expected
            answer is the library's own fact or a sum code made; none is
            written by hand (docs/design-rules.md: never invent a pin or a figure).
  run       each mode is loaded through modes.start, as Nemo loads it, and
            asked every task at temperature 0, thinking off.
  verdict   SHIP when the candidate scores at least the baseline overall AND
            in every category (a gain bought by a lost skill is not one);
            otherwise DON'T SHIP, with the reasons.
  evidence  ~/.nemo/evals/<run id>.json: every answer, the scores, and the
            sha256 of the task file and of each model file, so a verdict can
            be checked again.

The model writes a few words per task; nothing here asks it for a file.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCORINGS = ("exact", "contains", "regex", "answer")
# Room for a short working before the answer. At 64 (the first run,
# 2026-11-04) both models were cut off mid-sum, "1 + 1 + 15 = **1", and the
# power tasks scored 0/6 and 2/6 for the test's limit, not the models'.
MAX_TOKENS = 256


# ------------------------------------------------------------------ scoring
def _number(text: str) -> float | None:
    found = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(found[-1]) if found else None


def score(output: str, task: dict) -> bool:
    """Soup's four scorings, as its docs describe them."""
    out, want = (output or "").strip(), str(task["expected"]).strip()
    # A whole answer inside one code fence is read inside it, as Nemo's own calls read
    # it (held to a schema, the JSON taken out): Qwen2.5-Coder-7B chose a right pin in
    # all 8 JSON questions, each as ```json ...```, and scored 0 of 8 (2026-11-11).
    fenced = re.fullmatch(r"```[\w-]*\s*\n?(.*?)\n?\s*```", out, re.S)
    if fenced:
        out = fenced.group(1).strip()
    how = task.get("scoring") or "exact"
    if how == "exact":                       # the whole stripped output, case-insensitive
        return out.lower().rstrip(".") == want.lower()
    if how == "contains":                    # a whole alphanumeric-bounded token
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(want)}(?![A-Za-z0-9])", out, re.I) is not None
    if how == "regex":
        return re.search(want, out, re.S) is not None
    if how == "answer":                      # the final answer stated; numbers by value
        a, b = _number(out), _number(want)
        if a is not None and b is not None:
            return abs(a - b) < 1e-6
        lines = [ln for ln in out.splitlines() if ln.strip()]
        return bool(lines) and lines[-1].strip().rstrip(".").lower() == want.lower()
    raise ValueError(f"unknown scoring {how!r}; Soup's are {', '.join(SCORINGS)}")


# -------------------------------------------------------------------- tasks
def make_tasks(lib, seed: int = 7) -> list[dict]:
    """Nemo's own kinds of question, answered from the parts library."""
    rnd = random.Random(seed)
    parts = sorted(lib, key=lambda p: p.ref)
    mcus = [p for p in parts if p.category == "mcu"]
    tasks: list[dict] = []

    # Pins: is this pin on this board? (the model's main job is choosing pins)
    for m in mcus:
        names = [q.name for q in m.pins]
        gpios = sorted(int(n[4:]) for n in names if re.fullmatch(r"GPIO\d+", n))
        if not gpios:
            continue
        present = rnd.sample(gpios, min(2, len(gpios)))
        # A missing pin inside the board's range where there is one (GPIO24
        # between 23 and 25), the hard case; else one just past it. As many
        # noes as yeses, so answering "yes" every time scores half.
        gaps = [n for n in range(min(gpios), max(gpios)) if n not in gpios]
        past = [max(gpios) + k for k in range(1, 3)]
        absent = (rnd.sample(gaps, min(len(present), len(gaps))) + past)[:len(present)]
        for n, want in [(p, "yes") for p in present] + [(a, "no") for a in absent]:
            tasks.append({"prompt": (f"The {m.name} has exactly these pins: {', '.join(names)}. "
                                     f"Is GPIO{n} one of them? Answer only yes or no."),
                          "expected": want, "category": "pins", "scoring": "exact"})

    # Power: the sum of the parts' current draw, in mA (the power budget).
    drawn = [p for p in parts if p.category not in ("power", "mcu") and (p.current_ma or 0) > 0]
    for _ in range(6):
        pick = rnd.sample(drawn, min(3, len(drawn)))
        lines = "; ".join(f"{p.name}: {p.current_ma:g} mA" for p in pick)
        total = sum(p.current_ma for p in pick)
        tasks.append({"prompt": (f"A design has these parts and their current draw: {lines}. "
                                 "What is their total current in mA? End with the number."),
                      "expected": f"{total:g}", "category": "power", "scoring": "answer"})

    # Logic voltage: do two parts share one logic level? (level shifters)
    logic = [p for p in parts if p.logic_v]
    same = [(a, b) for i, a in enumerate(logic) for b in logic[i + 1:]
            if abs(float(a.logic_v) - float(b.logic_v)) < 1e-9]
    differ = [(a, b) for i, a in enumerate(logic) for b in logic[i + 1:]
              if abs(float(a.logic_v) - float(b.logic_v)) >= 1e-9]
    # Three of each, so a model that always says one word scores half.
    for a, b in rnd.sample(same, min(3, len(same))) + rnd.sample(differ, min(3, len(differ))):
        if rnd.random() < 0.5:
            a, b = b, a
        want = "yes" if abs(float(a.logic_v) - float(b.logic_v)) < 1e-9 else "no"
        tasks.append({"prompt": (f"{a.name} uses {a.logic_v:g} V logic. {b.name} uses {b.logic_v:g} V "
                                 "logic. Do they use the same logic voltage? Answer only yes or no."),
                      "expected": want, "category": "voltage", "scoring": "exact"})

    # Harder kinds (owner, 2026-11-04: both models scored 32/32 on the rest,
    # so those could not tell them apart).
    # Supply: which of a board's pins gives a voltage (the library's pin table).
    for m in mcus:
        supply = [q for q in m.pins if q.function == "power" and q.voltage]
        volts = sorted({float(q.voltage) for q in supply})
        for v in volts:
            right = [q.name for q in supply if abs(float(q.voltage) - v) < 1e-9]
            table = "; ".join(f"{q.name} ({q.function}{', ' + format(q.voltage, 'g') + ' V' if q.voltage else ''})"
                              for q in m.pins)
            tasks.append({"prompt": (f"The {m.name} has these pins: {table}. Which power pin supplies "
                                     f"{v:g} V? Answer with the pin name only."),
                          "expected": rf"^\s*\**({'|'.join(re.escape(n) for n in right)})\**\.?\s*$",
                          "category": "supply", "scoring": "regex"})

    # Runtime: a two-step sum, the battery's capacity over the parts' draw.
    cells = [p for p in parts if p.category == "power" and "mAh" in p.name]
    for _ in range(4):
        cell = rnd.choice(cells)
        mah = float(re.search(r"(\d+)\s*mAh", cell.name).group(1))
        pick = rnd.sample(drawn, min(3, len(drawn)))
        total = sum(p.current_ma for p in pick)
        hours = int(mah // total)
        lines = "; ".join(f"{p.name}: {p.current_ma:g} mA" for p in pick)
        tasks.append({"prompt": (f"A {mah:g} mAh battery powers these parts, all drawing their current all "
                                 f"the time: {lines}. Ignoring losses, for how many whole hours does it "
                                 "last, rounded down? End with the number."),
                      "expected": str(hours), "category": "runtime", "scoring": "answer"})

    # A choice under a constraint: some pins are taken already.
    for m in mcus[:4]:
        ios = [q.name for q in m.pins if q.function == "io"][:6]
        if len(ios) < 4:
            continue
        taken = rnd.sample(ios, 2)
        free = [n for n in ios if n not in taken]
        alts = "|".join(re.escape(n) for n in free)
        tasks.append({"prompt": (f"The board has these pins: {', '.join(ios)}. {taken[0]} and "
                                 f"{taken[1]} are already used by a display. Choose one pin for a button "
                                 "that is not already used. Reply with only JSON in this shape: "
                                 '{"pin": "<one pin>"}'),
                      "expected": rf'^\s*\{{\s*"pin"\s*:\s*"({alts})"\s*\}}\s*$',
                      "category": "constraint", "scoring": "regex"})

    # JSON: choose from a list and reply in the shape asked (the schema jobs).
    for m in mcus[:4]:
        ios = [q.name for q in m.pins if q.function == "io"][:6]
        if len(ios) < 2:
            continue
        alts = "|".join(re.escape(n) for n in ios)
        tasks.append({"prompt": (f"Choose one pin for an LED from this list: {', '.join(ios)}. "
                                 'Reply with only JSON in this shape: {"pin": "<one pin from the list>"}'),
                      "expected": rf'^\s*\{{\s*"pin"\s*:\s*"({alts})"\s*\}}\s*$',
                      "category": "json", "scoring": "regex"})
    return tasks


def write_tasks(tasks: list[dict], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks), encoding="utf-8")
    return path


def read_tasks(path: Path) -> list[dict]:
    tasks = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        t = json.loads(line)
        missing = [k for k in ("prompt", "expected") if k not in t]
        if missing:
            raise ValueError(f"{path} line {n}: no {', '.join(missing)}")
        t.setdefault("category", "general")
        t.setdefault("scoring", "exact")
        if t["scoring"] not in SCORINGS:
            raise ValueError(f"{path} line {n}: scoring {t['scoring']!r} is not one of Soup's")
        tasks.append(t)
    return tasks


# --------------------------------------------------------------------- runs
@dataclass
class ModelRun:
    mode: str
    model: str
    model_sha256: str
    answers: list[dict] = field(default_factory=list)

    def by_category(self) -> dict[str, tuple[int, int]]:
        out: dict[str, list[int]] = {}
        for a in self.answers:
            c = out.setdefault(a["category"], [0, 0])
            c[0] += int(a["passed"]); c[1] += 1
        return {k: (v[0], v[1]) for k, v in sorted(out.items())}

    @property
    def passed(self) -> int:
        return sum(int(a["passed"]) for a in self.answers)


def sha256_of(path: Path, cache: Path | None = None) -> str:
    """A model file's sha256, kept by size and time so a 5 GB file is read once."""
    path = Path(path)
    st = path.stat()
    key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    known = {}
    if cache and cache.is_file():
        try:
            known = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
    if key in known:
        return known[key]
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    known[key] = h.hexdigest()
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known, indent=1), encoding="utf-8")
    return known[key]


def ask(base: str, prompt: str, post=None) -> tuple[str, bool]:
    """One question, as Nemo asks: temperature 0, thinking off. (answer,
    cut off): cut off is the server saying it stopped at MAX_TOKENS, so a
    failed task can be told apart as wrong or as too long (2026-11-04: the
    4B wrote correct LaTeX working and ran out before the number)."""
    payload = {"model": "local", "messages": [{"role": "user", "content": prompt}],
               "temperature": 0, "max_tokens": MAX_TOKENS,
               "chat_template_kwargs": {"enable_thinking": False}}
    if post is not None:
        got = post(payload)
        return got if isinstance(got, tuple) else (got, False)
    req = urllib.request.Request(f"{base}/chat/completions", json.dumps(payload).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        reply = json.loads(r.read().decode("utf-8"))
    choice = reply["choices"][0]
    text = choice["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip(), choice.get("finish_reason") == "length"


def run_mode(cfg, mode: str, tasks: list[dict], say=print, post=None, start=None,
             model_file=None) -> ModelRun:
    """Load `mode` as Nemo does and ask it every task."""
    from . import modes
    start = start or modes.start
    ok, msg = start(cfg, mode)
    if not ok:
        raise RuntimeError(f"mode {mode!r} would not start: {msg}")
    spec = cfg.mode(mode)
    gguf = model_file or modes.model_path(cfg, spec["model"])
    home = Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo"))
    run = ModelRun(mode, spec["model"], sha256_of(gguf, home / "model-hashes.json"))
    base = cfg.get("engine.local", "http://127.0.0.1:8080/v1")
    for n, t in enumerate(tasks, 1):
        began = time.time()
        out, cut = ask(base, t["prompt"], post)
        run.answers.append({"category": t["category"], "prompt": t["prompt"], "expected": t["expected"],
                            "scoring": t["scoring"], "output": out, "passed": score(out, t),
                            "cut_off": cut, "seconds": round(time.time() - began, 2)})
        if n % 10 == 0:
            say(f"  {mode}: {n}/{len(tasks)}")
    return run


def verdict(base: ModelRun, cand: ModelRun) -> tuple[str, list[str]]:
    """SHIP only if the candidate is no worse overall and in every category."""
    why = []
    b, c = base.by_category(), cand.by_category()
    def cut(run, cat):
        n = sum(1 for a in run.answers if a.get("category") == cat and not a.get("passed")
                and a.get("cut_off"))
        return f" [{n} cut off at {MAX_TOKENS} tokens]" if n else ""
    for cat in sorted(set(b) | set(c)):
        bp, bn = b.get(cat, (0, 0)); cp, cn = c.get(cat, (0, 0))
        mark = "worse" if cp < bp else "better" if cp > bp else "same"
        why.append(f"{cat}: {base.model} {bp}/{bn}{cut(base, cat)}, {cand.model} {cp}/{cn}"
                   f"{cut(cand, cat)} ({mark})")
    lost = [cat for cat in b if c.get(cat, (0, 0))[0] < b[cat][0]]
    if cand.passed < base.passed:
        return "DON'T SHIP", [f"fewer tasks passed overall ({cand.passed} against {base.passed})"] + why
    if lost:
        return "DON'T SHIP", [f"a category got worse: {', '.join(lost)}"] + why
    return "SHIP", why


def history(folder: Path | None = None, n: int = 10) -> list[dict]:
    """The latest verdicts, newest first: when, verdict, the two models,
    passed counts, run id. An unreadable record is left out."""
    folder = folder or Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo")) / "evals"
    out = []
    for f in folder.glob("*.json") if folder.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            b, c = d["base"], d["candidate"]
            out.append({"run": d["run"], "when": d["when"], "verdict": d["verdict"],
                        "base": b["model"], "candidate": c["model"],
                        "base_passed": sum(1 for a in b["answers"] if a["passed"]),
                        "candidate_passed": sum(1 for a in c["answers"] if a["passed"]),
                        "of": len(c["answers"])})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(out, key=lambda r: r["when"], reverse=True)[:n]


def evidence(tasks_path: Path, base: ModelRun, cand: ModelRun, result: str, why: list[str],
             folder: Path | None = None) -> Path:
    folder = folder or Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo")) / "evals"
    folder.mkdir(parents=True, exist_ok=True)
    task_sha = hashlib.sha256(Path(tasks_path).read_bytes()).hexdigest()
    run_id = hashlib.sha256(f"{task_sha}{base.model_sha256}{cand.model_sha256}{time.time()}"
                            .encode()).hexdigest()[:16]
    doc = {"run": run_id, "when": time.strftime("%Y-%m-%d %H:%M:%S"), "verdict": result, "why": why,
           "tasks": str(tasks_path), "tasks_sha256": task_sha,
           "base": asdict(base), "candidate": asdict(cand)}
    out = folder / f"{run_id}.json"
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return out
