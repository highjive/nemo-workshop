"""Installing the Artist's story covers (2026-10-20, D194): the engine and
model were fetched by hand on Windows, and NemoIso carried none of them.

NemoDoc.ps1 fetches all three files on Windows; NemoIso builds sd-cli into
the image (build-sd.sh, run by build-iso.sh) and nemodoc links the model
from the Windows disk or fetches it (fetch-models.sh). As with the language
models (test_offline.TestModelSources), nemo/artist.py holds the one list
and every installer's copy is held to it. Like test_iso_scripts, most of
these read the scripts; the image was not built or booted for them.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _sandbox; _sandbox.activate()   # D112: before any nemo import

from nemo import artist

ROOT = Path(__file__).resolve().parent.parent
LINUX = ROOT / "install" / "linux"
BUILD = ROOT / "install" / "live-build" / "build-iso.sh"


def read(name: str) -> str:
    # NemoDoc.ps1 is top-level in both the tree and NemoWin.zip; the Linux
    # scripts are in install/ (and top-level in /opt/nemo/app on an image).
    for base in (ROOT, LINUX, BUILD.parent):
        if (base / name).exists():
            return (base / name).read_text(encoding="utf-8")
    raise unittest.SkipTest(f"{name} is not in this layout")


class TestOneList(unittest.TestCase):
    def test_the_list_is_well_formed(self):
        for name, (url, sha, size) in artist.SOURCES.items():
            self.assertRegex(sha, r"^[0-9a-f]{64}$", name)
            self.assertTrue(url.startswith("https://huggingface.co/"), name)
            self.assertGreater(size, 0, name)
        # What artist.tools() looks for is what is fetched.
        self.assertTrue(any(Path(n).match("sd_turbo*.gguf") for n in artist.SOURCES))
        self.assertIn("taesd.safetensors", artist.SOURCES)
        zname, zurl, zsha, _ = artist.ENGINE_ZIP
        self.assertRegex(zsha, r"^[0-9a-f]{64}$")
        self.assertTrue(zurl.endswith("/" + zname))
        self.assertIn(f"/download/{artist.ENGINE_TAG}/", zurl)

    def test_the_windows_build_and_the_linux_source_are_one_commit(self):
        short = artist.ENGINE_COMMIT[:7]
        self.assertTrue(artist.ENGINE_TAG.endswith("-" + short))
        self.assertIn(short, artist.ENGINE_ZIP[0])


class TestNemoDoc(unittest.TestCase):
    def setUp(self):
        self.s = read("NemoDoc.ps1")
        self.block = self.s[self.s.index("# --- the Artist"):self.s.index("# --- config")]

    def rows(self):
        return re.findall(r'file = "([^"]+)";\s*url = "([^"]+)";\s*sha256 = "([0-9a-f]+)";'
                          r'\s*bytes = (\d+)', self.block)

    def test_its_copy_agrees_with_the_list(self):
        rows = {f: (u, h, int(b)) for f, u, h, b in self.rows()}
        zname, zurl, zsha, zbytes = artist.ENGINE_ZIP
        self.assertEqual(rows.pop(zname), (zurl, zsha, zbytes))
        self.assertEqual(rows, artist.SOURCES)
        self.assertIn(f'$ArtistBuild = "{artist.ENGINE_TAG}"', self.block)

    def test_every_file_is_hash_checked_before_it_is_put_in_place(self):
        get = self.block[self.block.index("function Get-ArtistFile"):]
        check = get.index("Get-FileHash")
        self.assertLess(get.index("Get-File $A.url $staged"), check)
        # Unpacked or moved where Nemo looks only after the check.
        self.assertLess(check, get.index("Expand-Zip $staged"))
        self.assertLess(check, get.index("Move-Item $staged"))
        mismatch = get[check:get.index("Expand-Zip $staged")]
        self.assertIn("Remove-Item $staged", mismatch)

    def test_it_lands_where_nemo_looks(self):
        self.assertIn('$ArtistDir   = Join-Path $Prefix "artist"', self.block)
        self.assertIn('Join-Path $ArtistDir "sd\\sd-cli.exe"', self.block)

    def test_optional_never_stops_nemo_launching(self):
        self.assertIn("[switch]$SkipArtist", self.s)
        self.assertNotIn('Note "FAIL"', self.block)
        self.assertIn("$SkipArtist -or $SkipModels -or $CheckOnly", self.block)

    def test_the_download_goes_through_bits_like_the_models(self):
        self.assertIn("Get-File $A.url", self.block)


class TestTheArtistFollowsThePrefix(unittest.TestCase):
    """NemoDoc puts the artist under -Prefix and rewrites only the engine's
    path in the config (D132); the artist is found beside the engine."""

    def cfg(self, **values):
        return mock.Mock(get=lambda k, d=None: values.get(k, d))

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows paths")
    def test_another_prefix(self):
        cfg = self.cfg(**{"paths.llama_server": "D:/NemoClean/engine/llama-server.exe"})
        self.assertEqual(artist.home(cfg), Path("D:/NemoClean/artist"))

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows paths")
    def test_the_default_prefix_and_no_config(self):
        cfg = self.cfg(**{"paths.llama_server": "C:/Nemo/engine/llama-server.exe"})
        self.assertEqual(artist.home(cfg), Path("C:/Nemo/artist"))
        self.assertEqual(artist.home(self.cfg(**{"paths.llama_server": "llama-server"})),
                         Path("C:/Nemo/artist"))
        self.assertEqual(artist.home(None), Path("C:/Nemo/artist"))

    def test_paths_artist_still_wins(self):
        cfg = self.cfg(**{"paths.artist": "/somewhere/art",
                          "paths.llama_server": "D:/NemoClean/engine/llama-server.exe"})
        self.assertEqual(artist.home(cfg), Path("/somewhere/art"))

    def test_linux_looks_in_the_image(self):
        with mock.patch.object(artist.sys, "platform", "linux"):
            self.assertEqual(artist.home(self.cfg()), Path("/opt/nemo/artist"))


class TestBuildSd(unittest.TestCase):
    def setUp(self):
        self.s = read("build-sd.sh")

    def test_pinned_to_the_windows_builds_commit(self):
        self.assertIn(f'TAG="{artist.ENGINE_TAG}"', self.s)
        self.assertIn(f'COMMIT="{artist.ENGINE_COMMIT}"', self.s)
        self.assertIn('--branch "$TAG"', self.s)
        # The tag is checked against the commit, not trusted.
        self.assertIn('[ "$got" != "$COMMIT" ]', self.s)

    def test_nothing_newer_than_sse42_and_static(self):
        # As build-llama.sh: every newer option OFF by name (they default ON).
        for opt in ("GGML_NATIVE", "GGML_AVX", "GGML_AVX2", "GGML_FMA", "GGML_F16C",
                    "GGML_BMI2", "GGML_AVX512"):
            self.assertRegex(self.s, rf"-D{opt}=OFF\b", opt)
        self.assertIn("-DGGML_SSE42=ON", self.s)
        self.assertIn("-DBUILD_SHARED_LIBS=OFF", self.s)

    def test_installed_where_artist_tools_looks_and_self_tested(self):
        self.assertIn('"$PREFIX/artist/sd/sd-cli"', self.s)
        self.assertIn('"$PREFIX/artist/sd/sd-cli" --version', self.s)
        self.assertIn("--target sd-cli", self.s)

    def test_only_the_submodule_it_needs(self):
        self.assertIn("submodule update --init --depth 1 ggml", self.s)
        self.assertNotIn("--recursive", self.s)


class TestTheImage(unittest.TestCase):
    def setUp(self):
        self.s = read("build-iso.sh")

    def test_the_engine_is_built_into_the_image(self):
        self.assertIn("build-sd.sh", self.s[self.s.index("for f in nemodoc"):].splitlines()[0])
        self.assertIn("/opt/nemo/app/build-sd.sh /opt/nemo", self.s)
        self.assertIn("in_root /opt/nemo/artist/sd/sd-cli --version", self.s)

    def test_it_can_be_left_out_and_a_minimal_image_leaves_it_out(self):
        self.assertIn("--no-artist) ARTIST=0", self.s)
        self.assertRegex(self.s, r"--minimal\)[^\n]*ARTIST=0")

    def test_built_after_the_compilers_are_installed(self):
        self.assertLess(self.s.index("build-essential cmake"), self.s.index("build-sd.sh /opt/nemo"))

    def test_the_live_user_can_add_the_model_but_not_replace_the_engine(self):
        self.assertIn('chmod 1777 "$ROOT/opt/nemo/artist"', self.s)

    def test_no_image_model_in_the_image(self):
        self.assertNotIn("sd_turbo", self.s)

    def test_before_the_file_list_is_made(self):
        self.assertLess(self.s.index("build-sd.sh /opt/nemo"), self.s.index("manifest.sha256"))


class TestFetchModels(unittest.TestCase):
    def setUp(self):
        self.s = read("fetch-models.sh")

    def rows(self):
        return re.findall(r'"([\w.\-]+)\|(https://[^|"]+)\|([0-9a-f]{64})\|(\d+)"', self.s)

    def test_its_copy_agrees_with_the_list(self):
        self.assertEqual({f: (u, h, int(b)) for f, u, h, b in self.rows()}, artist.SOURCES)

    def test_the_language_model_rows_are_not_mistaken_for_them(self):
        # test_offline reads "name|repo|file"; these have four fields.
        lang = re.findall(r'"([\w.\-]+)\|([\w./\-]+)\|([\w.\-]+)"', self.s)
        self.assertNotIn("sd_turbo-f16-q8_0.gguf", [r[0] for r in lang])

    def test_to_where_the_image_engine_is(self):
        self.assertIn('ARTIST_DEST="${NEMO_ARTIST:-/opt/nemo/artist}"', self.s)


@unittest.skipUnless(shutil.which("sh") and shutil.which("sha256sum"), "needs sh and sha256sum")
class TestFetchModelsRuns(unittest.TestCase):
    """fetch-models.sh run with a stand-in curl (and df), nothing fetched."""

    def setUp(self):
        self.script = LINUX / "fetch-models.sh"
        if not self.script.exists():
            self.skipTest("fetch-models.sh is not in this layout")
        self.t = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.t, True)
        self.bin = self.t / "bin"
        self.bin.mkdir()
        self.dest = self.t / "artist"
        self.calls = self.t / "curl-calls"
        self.stub("curl", '#!/bin/sh\nout=""; url=""\n'
                  'while [ $# -gt 0 ]; do case "$1" in -o) shift; out="$1";; -C|--retry) shift;;'
                  ' -*) ;; *) url="$1";; esac; shift; done\n'
                  f'echo "$url" >> "{self.calls.as_posix()}"\necho not-the-model > "$out"\n')

    def stub(self, name, body):
        p = self.bin / name
        p.write_text(body, encoding="utf-8", newline="\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    def run_it(self, *args):
        env = dict(os.environ, NEMO_ARTIST=self.dest.as_posix(), NEMO_HOME=str(self.t / "home"),
                   PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""))
        return subprocess.run(["sh", str(self.script), *args], env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)

    def test_a_file_with_the_wrong_hash_is_deleted_never_used(self):
        self.stub("df", "#!/bin/sh\necho 'Filesystem 1024-blocks Used Available Capacity'\n"
                        "echo 'disk 99000000 0 99000000 0% /'\n")
        r = self.run_it("artist")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("did not match the expected hash", r.stderr)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), [])

    def test_a_file_already_there_is_kept(self):
        self.dest.mkdir()
        size = artist.SOURCES["taesd.safetensors"][2]
        (self.dest / "taesd.safetensors").write_bytes(b"\0" * size)
        r = self.run_it("artist")
        self.assertIn("have   artist taesd.safetensors", r.stdout)
        urls = self.calls.read_text(encoding="utf-8") if self.calls.exists() else ""
        self.assertNotIn("taesd", urls)

    def test_no_room_fetches_nothing_and_says_why(self):
        # On a live boot /opt/nemo/artist is RAM: df there is what is left.
        self.stub("df", "#!/bin/sh\necho 'Filesystem 1024-blocks Used Available Capacity'\n"
                        "echo 'overlay 4000000 3900000 100000 98% /'\n")
        r = self.run_it("artist")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("persistence", r.stderr)
        self.assertFalse(self.calls.exists(), "nothing may be fetched without room")

    def test_a_failed_language_model_is_a_failed_run(self):
        # D195: the loop ran in a pipe's subshell, so its failed=1 was lost
        # and the script said 0, and nemodoc took a failed fetch for done.
        self.stub("curl", "#!/bin/sh\nexit 22\n")
        r = self.run_it("--no-artist", "gemma3-1b")
        self.assertIn("FAILED gemma3-1b", r.stderr)
        self.assertNotEqual(r.returncode, 0)

    def test_a_model_already_there_is_a_clean_run(self):
        models = self.t / "home" / "models"
        models.mkdir(parents=True)
        (models / "gemma3-1b.gguf").write_bytes(b"GGUF")
        r = self.run_it("--no-artist", "gemma3-1b")
        self.assertIn("have   gemma3-1b", r.stdout)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_artist_leaves_them_alone(self):
        r =self.run_it("--no-artist", "no-such-model")
        self.assertNotIn("artist", r.stdout + r.stderr)
        self.assertFalse(self.dest.exists())


class TestNemodoc(unittest.TestCase):
    def setUp(self):
        self.s = read("nemodoc")
        self.block = self.s[self.s.index("if ! t_artist_engine; then"):self.s.index("for tool in kicad-cli")]

    def test_where_nemo_looks(self):
        self.assertIn('ARTIST_DIR="$PREFIX/artist"', self.s)
        self.assertIn('"$ARTIST_DIR/sd/sd-cli" --version', self.s)

    def test_the_windows_disk_first_read_only_and_linked(self):
        self.assertIn("windows_artist() { windows_folder Nemo/artist 'sd_turbo*.gguf'; }", self.s)
        self.assertLess(self.block.index("windows_artist"), self.block.index("fetch-models.sh"))
        link = self.s[self.s.index("link_artist() {"):]
        link = link[:link.index("\n}\n")]
        self.assertIn("ln -s", link)
        self.assertNotRegex(link, r"\bcp\b")

    def test_check_only_mounts_nothing(self):
        self.assertIn('[ "$CHECK_ONLY" -eq 0 ] && found="$(windows_artist)"', self.block)

    def test_fetched_only_when_asked(self):
        fetch = self.block[:self.block.index("fetch-models.sh")]
        self.assertIn('"$WANT_MODELS" -eq 1', fetch[fetch.rindex("elif"):])
        self.assertIn('NEMO_ARTIST="$ARTIST_DIR"', self.block)

    def test_the_language_models_fetch_does_not_take_it_before_the_disk_is_tried(self):
        f = self.s[self.s.index("f_models() {"):]
        self.assertIn('"$HERE/fetch-models.sh" --no-artist', f[:f.index("\n}\n")])

    def test_optional_never_a_problem(self):
        self.assertNotIn("PROBLEMS", self.block)
        self.assertNotIn("bad ", self.block)


if __name__ == "__main__":
    unittest.main()
