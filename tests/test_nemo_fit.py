"""nemo-fit (owner, 2026-11-11): NemoDoc on NemoIso builds a llama-server for the CPU it
has booted on and keeps it on the stick; a later boot uses it only on a CPU of the same
level and only while its hash matches. Run for real in bash, with a made-up
/proc/cpuinfo and a stand-in for build-llama.sh."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

APP = Path(__file__).resolve().parent.parent
LINUX = APP / "install" / "linux"
BASH = shutil.which("bash")

PENTIUM = "fpu vme de pse tsc msr pae mce cx8 sse sse2 ssse3 sse4_1 sse4_2 popcnt"
IVY = PENTIUM + " avx f16c"
HASWELL = PENTIUM + " avx avx2 fma f16c bmi1 bmi2"

FAKE_BUILD = """#!/bin/bash
# stands in for build-llama.sh: records its level, "builds" a script
echo "$1" > "$NEMO_HOME/asked-level"
mkdir -p "$2/bin"
printf '#!/bin/sh\\necho "version: fake $1"\\n' > "$2/bin/llama-server"
chmod 755 "$2/bin/llama-server"
"""


@unittest.skipUnless(BASH, "no bash here")
class TestNemoFit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        shutil.copy(LINUX / "nemo-fit", self.bin / "nemo-fit")
        (self.bin / "build-llama.sh").write_text(FAKE_BUILD, encoding="utf-8", newline="\n")
        self.cpu("Intel(R) Core(TM) i5-4590 CPU @ 3.30GHz", HASWELL)

    def cpu(self, name, flags):
        (self.tmp / "cpuinfo").write_text(f"processor\t: 0\nmodel name\t: {name}\nflags\t\t: {flags}\n",
                                          encoding="utf-8", newline="\n")

    def fit(self, *args):
        env = dict(os.environ, NEMO_HOME=self.home.as_posix(),
                   NEMO_CPUINFO=(self.tmp / "cpuinfo").as_posix(),
                   NEMO_FIT_WORK=self.tmp.as_posix())
        p = subprocess.run([BASH, (self.bin / "nemo-fit").as_posix(), *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env, timeout=60)
        return p.returncode, p.stdout.strip(), p.stderr.strip()

    def test_the_level_is_read_from_the_cpus_own_flags(self):
        for flags, want in ((PENTIUM, "sse42"), (IVY, "avx"), (HASWELL, "avx2"),
                            (PENTIUM + " avx avx2 fma f16c", "avx")):    # no BMI2: not avx2
            self.cpu("x", flags)
            self.assertEqual(self.fit("level")[1], want, flags)

    def test_nothing_is_built_for_the_images_own_level(self):
        self.cpu("Intel(R) Pentium(R) CPU B960 @ 2.20GHz", PENTIUM)
        code, out, _ = self.fit("build")
        self.assertEqual(code, 0)
        self.assertIn("image's own llama-server", out)
        self.assertFalse((self.home / "engines").exists())
        self.assertEqual(self.fit("find")[0], 1)

    def test_built_for_this_level_kept_with_its_hash_and_used(self):
        self.assertEqual(self.fit("find")[0], 1)                      # none kept yet
        code, out, err = self.fit("build")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.home / "asked-level").read_text(encoding="utf-8").strip(), "--avx2")
        kept = self.home / "engines" / "b11175-avx2"
        built = (kept / "BUILT.txt").read_text(encoding="utf-8")
        self.assertIn("level avx2", built)
        self.assertIn("i5-4590", built)
        sha = hashlib.sha256((kept / "llama-server").read_bytes()).hexdigest()
        self.assertIn(f"sha256 {sha}", built)
        code, out, err = self.fit("use")
        self.assertEqual((code, Path(out).name), (0, "b11175-avx2"), err)

    def test_a_kept_engine_is_not_used_on_another_level(self):
        self.fit("build")
        self.cpu("Intel(R) Core(TM) i5-3470", IVY)                    # the stick moved
        self.assertEqual(self.fit("find")[0], 1)
        self.cpu("Intel(R) Pentium(R) CPU B960", PENTIUM)
        self.assertEqual(self.fit("use")[0], 1)

    def test_a_damaged_copy_is_not_used(self):
        self.fit("build")
        exe = self.home / "engines" / "b11175-avx2" / "llama-server"
        with exe.open("ab") as f:
            f.write(b"\n# one byte gone wrong on the stick\n")
        code, _, err = self.fit("use")
        self.assertEqual(code, 1)
        self.assertIn("does not match its hash", err)


class TestItsPlaceInTheImage(unittest.TestCase):
    def test_nemodoc_uses_it_and_check_only_changes_nothing(self):
        doc = (LINUX / "nemodoc").read_text(encoding="utf-8")
        self.assertIn("--fit)        WANT_FIT=1", doc)
        self.assertIn('export PATH="$kept:$PATH"', doc)
        check = doc[doc.index('elif [ "$CHECK_ONLY" -eq 1 ]; then\n        if kept'):]
        check = check[:check.index("    else\n")]
        self.assertIn('"$FIT" find', check)                          # reads only
        self.assertNotIn('"$FIT" use', check)
        self.assertNotIn('"$FIT" build', check)

    def test_the_stick_keeps_it_and_the_image_carries_it(self):
        self.assertIn(".nemo/engines", (LINUX / "nemo-sync").read_text(encoding="utf-8"))
        iso = (APP / "install" / "live-build" / "build-iso.sh").read_text(encoding="utf-8")
        self.assertIn("for f in nemodoc nemo-fit build-llama.sh", iso)

    def test_the_build_switches_on_exactly_what_the_level_names(self):
        b = (LINUX / "build-llama.sh").read_text(encoding="utf-8")
        self.assertIn("--avx2) AVX=ON; AVX2=ON ;;", b)
        for flag in ("AVX2", "FMA", "F16C", "BMI2"):
            self.assertIn(f'-DGGML_{flag}="$AVX2"', b)
        self.assertIn("-DGGML_AVX512=OFF", b)


if __name__ == "__main__":
    unittest.main()
