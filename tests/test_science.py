"""Science (owner, 2026-10-22): units, maths, physics, statistics and
spreadsheets, worked out by the libraries and shown step by step.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import science as S
from nemo import staff

HAVE = all(__import__("importlib").util.find_spec(m) for m in ("pint", "sympy", "openpyxl"))


@unittest.skipUnless(HAVE, "Pint, sympy or openpyxl not installed")
class TestTheCalculator(unittest.TestCase):
    def test_conversions_with_the_working(self):
        a = S.convert("10 inch", "mm")
        self.assertEqual(a.result, "254 mm")
        self.assertIn("1 in = 25.4 mm", a.steps)
        self.assertEqual(S.convert("2000 mAh * 3.7 V", "Wh").result, "7.4 Wh")
        t = S.convert("100 degF", "degC")
        self.assertTrue(t.result.startswith("37.7778"))
        self.assertIn("offset", t.steps[-1])                     # not a plain multiplication

    def test_what_cannot_be_converted(self):
        with self.assertRaises(S.ScienceError) as e:
            S.convert("3 m", "kg")
        self.assertIn("[length]", str(e.exception))
        with self.assertRaises(S.ScienceError):
            S.convert("3 wibbles", "m")


@unittest.skipUnless(HAVE, "Pint, sympy or openpyxl not installed")
class TestTheMathematician(unittest.TestCase):
    def test_solving_with_steps(self):
        a = S.maths("x^2-5x+6=0")
        self.assertEqual(a.result, "x = 2, x = 3")
        self.assertIn("factorise: (x - 3)*(x - 2) = 0", a.steps)
        self.assertEqual(S.maths("2x+3=11").result, "x = 4")
        self.assertEqual(S.maths("x^2=2").result,
                         "x = -sqrt(2) (about -1.41421), x = sqrt(2) (about 1.41421)")

    def test_the_other_actions(self):
        self.assertEqual(S.maths("sin(x)^2+cos(x)^2", "simplify").result, "1")
        self.assertEqual(S.maths("x^3", "differentiate").result, "3*x**2")
        integ = S.maths("3x^2+2", "integrate")
        self.assertEqual(integ.result, "x**3 + 2*x")
        self.assertIn("plus a constant, C", integ.steps)
        self.assertEqual(S.maths("x^2-1", "factor").result, "(x - 1)*(x + 1)")
        self.assertTrue(S.maths("sqrt(2)", "evaluate").result.startswith("1.41421356"))

    def test_only_maths_is_read(self):
        # sympy's reader runs what it is given as Python: nothing else may reach it.
        for bad in ("__import__('os')", "os.system(1)", "open(1)", "x; 1", "lambda: 1"):
            with self.assertRaises(S.ScienceError, msg=bad):
                S.maths(bad, "evaluate")
        with self.assertRaises(S.ScienceError):
            S.maths("1=2=3")
        with self.assertRaises(S.ScienceError):
            S.maths("4=4")                                       # nothing to solve for


@unittest.skipUnless(HAVE, "Pint, sympy or openpyxl not installed")
class TestThePhysicist(unittest.TestCase):
    def test_a_formula_solved_for_what_is_missing(self):
        self.assertEqual(S.formula("ohm", {"I": "20 mA", "R": "220 ohm"}).result, "V = 4.4 V")
        self.assertEqual(S.formula("ohm", {"V": "5 V", "I": "20 mA"}).result, "R = 250 Ω")
        self.assertEqual(S.formula("rc", {"R": "10 kohm", "C": "100 uF"}).result, "tau = 1 s")
        k = S.formula("kinetic", {"m": "2 kg", "E": "100 J"})
        self.assertEqual(k.result, "v = 10 m/s")                 # the root that is not negative
        self.assertIn("v = sqrt(2)*sqrt(E/m)", k.steps[-1])
        self.assertEqual(S.formula("potential", {"m": "1 kg", "h": "2 m"}).result, "E = 19.6133 J")

    def test_the_one_asked_for_may_be_written_as_a_question_mark(self):
        # 2026-11-06: the help's own form, V=? I="20 mA", was refused ("give
        # all but one of V, I, R"): "?" was taken as V's value.
        self.assertEqual(S.formula("ohm", {"V": "?", "I": "20 mA", "R": "220 ohm"}).result,
                         "V = 4.4 V")
        self.assertEqual(S.formula("ohm", {"V": "", "I": "20 mA", "R": "220 ohm"}).result,
                         "V = 4.4 V")

    def test_wrong_units_and_missing_values_are_said(self):
        with self.assertRaises(S.ScienceError) as e:
            S.formula("ohm", {"I": "20 mA", "R": "3 kg"})
        self.assertIn("R must be in", str(e.exception))
        with self.assertRaises(S.ScienceError):
            S.formula("ohm", {"I": "20 mA"})
        with self.assertRaises(S.ScienceError):
            S.formula("warp", {})


class TestTheStatistician(unittest.TestCase):
    def test_a_column_of_readings(self):
        with tempfile.TemporaryDirectory() as t:
            a = S.stats([20.1, 20.3, 20.2, 20.6, 20.9, 21.0, 21.4], Path(t) / "c.png")
            self.assertIn("mean 20.6429", a.steps)
            self.assertIn("a clear trend", " ".join(a.steps))
            if a.chart:
                self.assertTrue(a.chart.is_file())
        far = S.stats([10] * 20 + [500])
        self.assertIn("500", far.steps[-1])
        with self.assertRaises(S.ScienceError):
            S.stats([1])


@unittest.skipUnless(HAVE, "Pint, sympy or openpyxl not installed")
class TestTheBookkeeperAndWriter(unittest.TestCase):
    def test_a_sheet_written_with_formulas_and_read_back(self):
        with tempfile.TemporaryDirectory() as t:
            p = S.write_sheet(Path(t) / "r.xlsx", "Readings", ["Reading", "Value"],
                              [[1, 20.5], [2, 21.0], [3, 21.5]])
            rows = S.read_sheet(p)["Readings"]
            self.assertEqual(rows[0], ["Reading", "Value"])
            self.assertEqual(rows[4], ["Total", "=SUM(B2:B4)"])
            self.assertEqual(rows[5], ["Average", "=AVERAGE(B2:B4)"])
            (Path(t) / "bad.xlsx").write_text("not a spreadsheet", encoding="utf-8")
            with self.assertRaises(S.ScienceError):
                S.read_sheet(Path(t) / "bad.xlsx")

    def test_the_worked_sheet(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            from nemo.config import Config
            cfg = Config.load(Path("/nonexistent"))
            path = S.keep(cfg, S.maths("2x+3=11"))
            text = path.read_text(encoding="utf-8")
            self.assertIn("## Working", text)
            self.assertIn("## Answer\n\nx = 4", text)

    def test_the_team(self):
        self.assertEqual([e.title for e in staff.team("science")],
                         ["Calculator", "Mathematician", "Physicist", "Statistician", "Bookkeeper", "Writer"])


@unittest.skipUnless(_sandbox.has_display() and HAVE, "no display, or no Science libraries")
class TestTheWindow(unittest.TestCase):
    def test_work_it_out(self):
        try:
            from nemo.gui import app as A
        except ImportError:
            self.skipTest("tkinter not installed")
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, _sandbox.home_env(t)):
            app = A.NemoApp(); app.update()
            try:
                w = A.ScienceRoom(app); app.update()
                w.entry.insert(0, "x^2-5x+6=0")
                self.assertEqual(w.run().result, "x = 2, x = 3")
                w.action.set("Physics formula"); w.formula.set("ohm")
                w.entry.delete(0, "end"); w.entry.insert(0, "I=20 mA R=220 ohm")
                self.assertEqual(w.run().result, "V = 4.4 V")
                w.action.set("Statistics")
                w.entry.delete(0, "end"); w.entry.insert(0, "1 2 3 4")
                out = w.save_sheet(path=str(Path(t) / "n.xlsx"))
                self.assertIn("n.xlsx", str(out))
                self.assertIn("Readings", w.open_sheet(path=str(out)))
                w.destroy()
            finally:
                app.destroy()


ROOT = Path(__file__).resolve().parent.parent


def _pins(text: str) -> set[str]:
    """The package names on the science line's --no-deps install."""
    import re
    line = next(l for l in text.splitlines() if "--no-deps" in l and '"Pint==' in l)
    return {re.sub(r"[-_.]+", "-", n).lower() for n in re.findall(r'"([A-Za-z0-9_.\-]+)==', line)}


class TestTheInstallersPins(unittest.TestCase):
    """D208: the Science libraries are installed --no-deps, and the list left out
    typing-extensions, which Pint, flexcache and flexparser all import, so on a
    fresh install the Calculator and Physicist failed with ModuleNotFoundError.
    NemoDoc's probe looked for pint by find_spec only, so it never noticed."""

    def scripts(self):
        found = {}
        for name, places in (("NemoDoc.ps1", (ROOT, ROOT / "install" / "windows")),
                             ("build-iso.sh", (ROOT / "install" / "live-build",))):
            for base in places:
                if (base / name).exists():
                    found[name] = (base / name).read_text(encoding="utf-8")
                    break
        if not found:
            self.skipTest("no installer scripts in this layout")
        return found

    def test_typing_extensions_is_pinned_in_both(self):
        for name, text in self.scripts().items():
            self.assertIn("typing-extensions", _pins(text), name)

    def test_every_pinned_package_has_what_it_needs_pinned_too(self):
        import importlib.metadata as md
        import re
        for name, text in self.scripts().items():
            pins = _pins(text)
            for pkg in pins:
                try:
                    reqs = md.requires(pkg) or []
                except md.PackageNotFoundError:
                    continue                     # not installed here: nothing to read
                for r in reqs:
                    if "extra ==" in r.replace("extra==", "extra =="):
                        continue
                    if ";" in r and "python_version" in r:
                        continue                 # a backport for older Pythons
                    need = re.sub(r"[-_.]+", "-", re.match(r"[A-Za-z0-9_.\-]+", r).group()).lower()
                    self.assertIn(need, pins, f"{name}: {pkg} needs {need}")

    def test_nemodoc_probe_looks_for_typing_extensions(self):
        text = self.scripts().get("NemoDoc.ps1")
        if text is None:
            self.skipTest("NemoDoc.ps1 not in this layout")
        probe = next(l for l in text.splitlines() if "'sympy','pint','openpyxl'" in l)
        self.assertIn("typing_extensions", probe)


class TestWhatWasMeant(unittest.TestCase):
    """Samples, 2026-11-08."""

    def test_a_lone_f_or_c_is_degrees(self):
        # "100 F" to "C" was read as farads to coulombs and refused.
        a = S.convert("100 F", "C")
        self.assertTrue(a.result.startswith("37.7778"), a.result)
        self.assertIn("read as degrees", " ".join(a.steps))
        self.assertTrue(S.convert("0 C", "F").result.startswith("32"))
        self.assertTrue(S.convert("100 uF", "nF").result.startswith("100000"))   # still farads

    def test_the_formula_is_the_one_its_quantities_name(self):
        # `formula "R=?" V="5 V" I="20 mA"` only listed the formulas.
        a = S.formula("R=?", {"V": "5 V", "I": "20 mA"})
        self.assertTrue(a.result.startswith("R = 250"), a.result)
        with self.assertRaises(S.ScienceError) as e:
            S.formula("V=?", {"I": "2 A"})
        self.assertIn("ohm and power use I, V", str(e.exception))
        with self.assertRaises(S.ScienceError) as e:
            S.formula("zz=?", {})
        self.assertIn("no formula Nemo knows uses zz", str(e.exception))

    def test_the_one_asked_for_is_not_called_missing(self):
        with self.assertRaises(S.ScienceError) as e:
            S.formula("heat", {"Q": "?", "m": "2 kg"})
        self.assertIn("Q is asked for; c, dT are missing", str(e.exception))


if __name__ == "__main__":
    unittest.main()
