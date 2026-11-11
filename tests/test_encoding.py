"""Text files are UTF-8, whatever the machine's own default is.

D122, measured on the real AH531 (Windows 11, default encoding cp1252).
82 text reads and writes in the package named no encoding, so on Windows
they used the code page:

  - writing model output that contains a character outside cp1252 raised
    UnicodeEncodeError. Tried there: an arrow, a less-or-equal sign, an
    omega and a tick each crashed a plain write_text. Those are the
    writes that save firmware, CAD scripts, the wiring harness and the
    build guide, and small models write arrows constantly;
  - a bundled part (bme280) loaded with its "µA-scale" note mangled;
  - what did get written was cp1252, which Python, compilers and KiCad
    then read as UTF-8.

Linux defaults to UTF-8, so none of this showed in the sandbox. The first
class scans the source and fails on the unfixed code anywhere. The rest
fail on the unfixed code on Windows.
"""
from __future__ import annotations

import ast, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo.parts import PartsLibrary
from nemo.project import Brief
from nemo.prompts import load_prompt
from test_pipeline import PipelineCase, StubRouter

PACKAGE = Path(__file__).resolve().parent.parent / "nemo"
# The one text-looking open() that is binary: its mode is chosen at run time.
BINARY = {("offline.py", "part.open(mode)")}
NOT_FILES = {"os", "webbrowser", "Image", "tarfile", "zipfile", "urllib", "wave", "gzip"}


def unencoded_calls() -> list[str]:
    out = []
    for f in sorted(PACKAGE.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        lines = src.splitlines()
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in ("read_text", "write_text", "open"):
                continue
            if any(k.arg == "encoding" for k in node.keywords):
                continue
            line = lines[node.lineno - 1]
            if name == "open":
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) \
                        and fn.value.id in NOT_FILES:
                    continue
                args = node.args[1:] if not isinstance(fn, ast.Attribute) else node.args
                mode = next((a.value for a in args[:1] if isinstance(a, ast.Constant)
                             and isinstance(a.value, str)), None)
                for k in node.keywords:
                    if k.arg == "mode" and isinstance(k.value, ast.Constant):
                        mode = k.value.value
                if mode and "b" in mode:
                    continue
                if any(f.name == n and frag in line for n, frag in BINARY):
                    continue
            out.append(f"{f.relative_to(PACKAGE)}:{node.lineno}: {line.strip()[:80]}")
    return out


class TestEveryTextFileNamesItsEncoding(unittest.TestCase):
    def test_no_read_or_write_is_left_to_the_machines_default(self):
        self.assertEqual(unencoded_calls(), [])

    def test_tool_output_that_cannot_be_decoded_is_not_a_traceback(self):
        from nemo.checks import runners
        rc, out, err = runners._run([sys.executable, "-c",
                                     "import sys; sys.stdout.buffer.write(b'ok \\x9d\\x81 end')"])
        self.assertEqual(rc, 0)
        self.assertIn("ok", out); self.assertIn("end", out)


class TestShippedFilesLoadUnmangled(unittest.TestCase):
    def test_the_bundled_part_with_a_micro_sign(self):
        part = PartsLibrary.load().get("bme280")
        text = " ".join(str(v) for v in vars(part).values())
        self.assertIn("µA", text)
        self.assertNotIn("Â", text)                 # the mark of UTF-8 read as cp1252

    def test_prompts_reach_the_model_as_written(self):
        for name in ("brief", "schematic", "wiring", "enclosure", "firmware"):
            raw = (PACKAGE / "prompts" / f"{name}.md").read_bytes().decode("utf-8")
            loaded = (PACKAGE / "prompts" / f"{name}.md").read_text(encoding="utf-8")
            self.assertEqual(raw.replace("\r\n", "\n"), loaded.replace("\r\n", "\n"), name)
        self.assertNotIn("Â", load_prompt("brief", known_parts="x"))


OUTSIDE_CP1252 = "GPIO5 → LED via 330 Ω, current ≤ 20 mA ✓"
INSIDE_CP1252 = "25 °C, 10 µF"


class TestModelOutputIsWrittenAsUtf8(PipelineCase):
    def _seed(self):
        self.project.create(Brief(
            name="t", function="f", power="USB 5 V 1 A", supply_ma=1000,
            rails=[5.0, 3.3], envelope_mm=[140, 100, 70],
            parts=["esp32_devkit_v1", "rc522"], mcu="esp32", done_when="reads a card"))

    def test_a_script_with_an_arrow_in_it_is_saved_and_runs(self):
        # Before: UnicodeEncodeError at the write. And a script saved in
        # cp1252 with a degree sign in it is not valid Python source at all.
        self._seed()
        script = ("```python\n"
                  f"# {OUTSIDE_CP1252}\n"
                  f"# {INSIDE_CP1252}\n"
                  'open("schematic.kicad_sch", "w").write("(kicad_sch)")\n'
                  "```")
        self.pipe(StubRouter(script)).stage_electrical()
        saved = (self.project.root / "electrical" / "schematic.py").read_bytes()
        self.assertIn(OUTSIDE_CP1252.encode("utf-8"), saved)
        self.assertIn(INSIDE_CP1252.encode("utf-8"), saved)
        self.assertTrue(self.project.schematic.exists(), "the saved script did not run")

    def test_a_brief_the_model_could_not_format_is_kept_as_it_wrote_it(self):
        text = f"- {OUTSIDE_CP1252}"                  # a list, not the mapping asked for
        self.project.root.mkdir(parents=True)         # `nemo new` has done this by now
        r = self.pipe(StubRouter(text)).stage_brief("a thing")
        self.assertFalse(r.ok)
        raw = (self.project.root / "brief.raw.txt").read_bytes()
        self.assertIn(OUTSIDE_CP1252.encode("utf-8"), raw)


class TestOldFilesStillOpen(unittest.TestCase):
    def test_a_file_this_install_wrote_in_cp1252_degrades_and_does_not_crash(self):
        # Reads outside the security modules replace what they cannot decode.
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "housing.py"
            f.write_bytes("# wall 2 mm ± 0.1 at 25 °C\nx = 1\n".encode("cp1252"))
            text = f.read_text(encoding="utf-8", errors="replace")
        self.assertIn("x = 1", text)

    def test_the_security_modules_read_strictly(self):
        for name in ("admin.py", "lockdown.py", "maintenance.py", "master.py", "signing.py"):
            src = (PACKAGE / name).read_text(encoding="utf-8")
            self.assertNotIn('errors="replace"', src, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
