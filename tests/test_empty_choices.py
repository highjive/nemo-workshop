"""D177, the AH531 on 2026-10-16: step 3 failed with "Bad Request".

llama-server turns the answer format Nemo sends into a grammar, and it
refuses an empty `anyOf` with 400. Nemo sent one whenever no part beyond
the board had a signal pin left for the model to place (a Pico and a LiPo
cell, found by sending every board-and-part format to the real server
b11175). There is nothing to ask then; code wires power and ground.
"""
from __future__ import annotations

import sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.config import Config
from nemo.parts import PartsLibrary
from nemo.pipeline import Pipeline
from nemo.project import Brief, Project
from nemo.router import Reply

LIB = PartsLibrary.load()
BOARDS = [r for r, p in LIB.parts.items() if p.category == "mcu"]
OTHERS = [r for r in LIB.parts if r not in BOARDS]


def empties(node, path="#"):
    """Every place in a JSON schema a list of alternatives is empty."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("anyOf", "oneOf", "allOf", "enum") and isinstance(v, list) and not v:
                out.append(f"{path}/{k}")
            out += empties(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += empties(v, f"{path}/{i}")
    return out


class Recorder:
    """Answers nothing useful; records every schema it was handed."""
    supports_schema = True

    def __init__(self):
        self.schemas = []

    def ask(self, task, system, user, **kw):
        if "schema" in kw:
            self.schemas.append(kw["schema"])
        return Reply('{"cables": []}', "local", "stub")

    def local_up(self):
        return True


class _Stop(Exception):
    pass


def electrical(refs):
    """Step 3 as far as choosing the connections, then stopped: what the
    model was asked is all this looks at, so KiCad is never run."""
    rec = Recorder()
    real = Pipeline._decide_connections

    def decide(self, *a, **kw):
        real(self, *a, **kw)
        raise _Stop()
    with tempfile.TemporaryDirectory() as t,          mock.patch.object(Pipeline, "_decide_connections", decide):
        proj = Project(Path(t) / "p")
        proj.create(Brief(name="probe", function="A probe device.", power="USB 5 V 2 A",
                          supply_ma=3000, rails=[5.0, 3.3], envelope_mm=[200, 150, 80],
                          parts=list(refs), mcu="esp32", done_when="It works."))
        try:
            Pipeline(proj, Config.load(Path("/nonexistent")), rec, LIB).stage_electrical()
        except _Stop:
            pass
    return rec


class TestNoEmptyChoiceIsEverSent(unittest.TestCase):
    def test_every_board_with_every_part(self):
        bad = []
        for b in BOARDS:
            for refs in [(b, o) for o in OTHERS] + [tuple([b] + OTHERS)]:
                for s in electrical(refs).schemas:
                    if empties(s):
                        bad.append(f"{refs}: {empties(s)[0]}")
        self.assertEqual(bad, [])

    def test_a_board_and_a_battery_does_not_ask_the_model(self):
        self.assertEqual(electrical(("rp2040_pico", "lipo_1000")).schemas, [])

    def test_the_checker_finds_an_empty_list(self):
        self.assertEqual(empties({"a": {"anyOf": []}}), ["#/a/anyOf"])
