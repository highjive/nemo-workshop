"""D155: `nemo datasheet link --part <part> <file>` ended in a traceback.

Found on the real laptop (2026-10-07) while exercising the datasheet tool
for O19. The command's own help lists --part; with it, args.items held one
thing and the code read a second: IndexError, shown to the owner whole.
"""
from __future__ import annotations

import argparse, contextlib, io, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import cli
from nemo.config import Config


class Recorder:
    def __init__(self):
        self.calls = []

    def sheets(self):
        return [argparse.Namespace(file="sheet.pdf"), argparse.Namespace(file="other.pdf")]

    def link(self, file, part):
        self.calls.append(("link", file, part))

    def unlink(self, file, part):
        self.calls.append(("unlink", file, part))


def run(action, items, part=None):
    lib, out = Recorder(), io.StringIO()
    args = argparse.Namespace(action=action, items=list(items), part=part)
    with contextlib.redirect_stdout(out):
        rc = cli._datasheet(args, Config.load(Path("/nonexistent")), lib)
    return rc, out.getvalue(), lib.calls


class TestLink(unittest.TestCase):
    def test_file_then_part_as_the_tools_own_hint_says(self):
        rc, text, calls = run("link", ["sheet.pdf", "bme280"])
        self.assertEqual((rc, calls), (0, [("link", "sheet.pdf", "bme280")]))
        self.assertIn("linked", text)

    def test_the_part_given_with_the_flag_the_help_offers(self):
        rc, text, calls = run("link", ["sheet.pdf"], part="bme280")
        self.assertEqual((rc, calls), (0, [("link", "sheet.pdf", "bme280")]))

    def test_too_little_is_told_what_to_type_not_shown_a_traceback(self):
        for items, part in (([], None), (["sheet.pdf"], None), ([], "bme280"),
                            (["a.pdf", "b", "c"], None)):
            rc, text, calls = run("link", items, part)
            self.assertEqual((rc, calls), (2, []), (items, part))
            self.assertIn('nemo datasheet link "<file.pdf>" <part>', text)

    def test_a_file_that_was_never_added_is_not_called_linked(self):
        rc, text, calls = run("link", ["nothere.pdf", "bme280"])
        self.assertEqual((rc, calls), (1, []))
        self.assertIn("No datasheet called nothere.pdf has been added", text)
        self.assertIn("sheet.pdf, other.pdf", text)            # what there is to choose from
        self.assertNotIn("linked", text.replace("unlinked", ""))

    def test_a_part_the_library_does_not_have_is_not_called_linked(self):
        rc, text, calls = run("link", ["sheet.pdf", "nosuchpart"])
        self.assertEqual((rc, calls), (1, []))
        self.assertIn("No part called nosuchpart in the parts library", text)

    def test_unlink_the_same(self):
        rc, text, calls = run("unlink", ["sheet.pdf"], part="bme280")
        self.assertEqual((rc, calls), (0, [("unlink", "sheet.pdf", "bme280")]))
        self.assertIn("unlinked", text)
        rc, text, calls = run("unlink", [])
        self.assertEqual((rc, calls), (2, []))
        self.assertIn('nemo datasheet unlink "<file.pdf>" <part>', text)


if __name__ == "__main__":
    unittest.main()
