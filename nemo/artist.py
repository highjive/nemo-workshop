"""The Artist's story covers (owner's request, 2026-10-20).

A cover is painted by a local image model: stable-diffusion.cpp's sd-cli
with SD-Turbo (Stability AI's, under its non-commercial community licence)
and, where present, the tiny TAESD decoder. Nothing leaves the machine.
Enclosure concepts are not made this way (nemo/concept.py): a painting of
a box can promise a box that cannot be built; a cover promises nothing.

Measured on the AH531 (Pentium B960, SSE4.2 backend), one 512 x 512
cover, SD-Turbo in one step (2026-10-20, other work on the CPU part of the
time): with the full decoder, 334 s to sample and 1,254 s to decode, 1,610
s in all; with TAESD, 292 s to sample and 70 s to decode, 680 s from start
to finish, and the picture all but the same. So TAESD is used where it is.

The prompt is written here, from the story's own title and the owner's
request, and not by the language model: it costs nothing, and the model
is not loaded alongside the image model in 8 GB (RAM_MB).

Where it looks (paths.artist, else <NemoDoc's prefix>/artist, C:/Nemo/artist
by default, or /opt/nemo/artist). NemoDoc.ps1 fetches all three on Windows;
on NemoIso the engine is built into the image and nemodoc links the two
model files from the Windows disk or fetches them (fetch-models.sh):
  sd/sd-cli(.exe)       the engine, with its ggml-cpu-*.dll beside it
  sd_turbo*.gguf        the image model
  taesd.safetensors     the tiny decoder (optional)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Peak memory of sd-cli measured on the AH531 (full decoder): 2,735 MB.
RAM_MB = 2900

# What the installers fetch, and the one list they are held to by a test
# (tests/test_artist_install.py), as offline.MODEL_SOURCES holds the language
# models: file name here, url, sha256 and size in bytes. Hashes and sizes are
# of the files fetched on 2026-10-20 and used for the 680 s cover above, and
# agree with what Hugging Face lists for them.
ENGINE_TAG = "master-929-3f8527a"
ENGINE_COMMIT = "3f8527a46c54ecf4cb4ed6003da8e8982283c73c"
# Windows only: the release's CPU build, sd-cli.exe with a ggml-cpu-*.dll per
# CPU generation (sse42 on the B960). There is no Linux CPU build in the
# release; NemoIso builds sd-cli from ENGINE_COMMIT (install/linux/build-sd.sh).
ENGINE_ZIP = ("sd-master-3f8527a-bin-win-cpu-x64.zip",
              "https://github.com/leejet/stable-diffusion.cpp/releases/download/"
              "master-929-3f8527a/sd-master-3f8527a-bin-win-cpu-x64.zip",
              "5e7caca2080321b25a12c1fa4175cb7d953f2b182309f8f73bfc9c725231d26c", 17486440)
SOURCES = {
    "sd_turbo-f16-q8_0.gguf": (
        "https://huggingface.co/Green-Sky/SD-Turbo-GGUF/resolve/main/sd_turbo-f16-q8_0.gguf",
        "d50be7655f0a554cf8041c145d88b210bd5f3c545423119dee62ae08cae51580", 2023745376),
    "taesd.safetensors": (
        "https://huggingface.co/madebyollin/taesd/resolve/main/diffusion_pytorch_model.safetensors",
        "db169d69145ec4ff064e49d99c95fa05d3eb04ee453de35824a6d0f325513549", 9793292),
}
SIZE = 512
STYLE = "storybook cover illustration, painterly, warm light, rich detail"

# The desktop (nemo/machine.py): the same release's CUDA 12 build and its
# runtime, in <artist>/sd-cuda. GitHub's sha256 for each; NemoDoc carries
# the same list (a test). Measured on an RTX 3050 8 GB (2026-11-04): a
# 1344 x 576 scene from a reference picture, 3 steps, in 8.8 s (the AH531:
# about 11 minutes for a 512 square), peaking at 5,028 MiB on the card and
# 619 MB of RAM. So the language model must be off (design holds 7,000).
SD_CUDA = (
    ("sd-master-3f8527a-bin-win-cuda12-x64.zip", 337915440,
     "217d6dead9abd3f827fc338268555cc179234e7e6330ef21ecb1c985e19d2dc7"),
    ("cudart-sd-bin-win-cu12-x64.zip", 563452046,
     "fe20366827d357c00797eebb58244dddab7fd9a348d70090c3871004c320f38d"),
)
GPU_VRAM_MB = 5100
GPU_RAM_MB = 700


class ArtistError(RuntimeError):
    """For the owner: why no cover was drawn, and what to do."""


@dataclass
class Tools:
    engine: Path
    model: Path
    taesd: Path | None
    gpu: bool = False


def home(cfg=None) -> Path:
    configured = cfg.get("paths.artist") if cfg is not None else None
    if configured:
        return Path(str(configured)).expanduser()
    if not sys.platform.startswith("win"):
        return Path("/opt/nemo/artist")
    # NemoDoc puts the artist beside the engine, under its -Prefix, and
    # writes the engine's path into the config (D132); so the artist is
    # found under the same prefix, and not in C:/Nemo when that is another.
    engine = str(cfg.get("paths.llama_server", "") or "") if cfg is not None else ""
    if engine:
        p = Path(engine)
        if p.is_absolute() and p.parent.name.lower() == "engine":
            return p.parent.parent / "artist"
    return Path("C:/Nemo/artist")


def tools(cfg=None) -> Tools:
    d = home(cfg)
    exe = "sd-cli.exe" if sys.platform.startswith("win") else "sd-cli"
    # The desktop paints on its GPU where the CUDA build is installed; the
    # laptop (and a desktop without it) on the CPU, as before.
    from .machine import is_desktop
    cuda = d / "sd-cuda" / exe
    gpu = cuda.is_file() and is_desktop(cfg)
    engine = cuda if gpu else next((p for p in (d / "sd" / exe, d / exe) if p.is_file()), None)
    if engine is None:
        raise ArtistError(f"The image engine is not installed (no {exe} in {d}). Story covers "
                          "need stable-diffusion.cpp and SD-Turbo there.")
    models = sorted(d.glob("sd_turbo*.gguf"))
    if not models:
        raise ArtistError(f"No image model in {d} (sd_turbo*.gguf).")
    taesd = d / "taesd.safetensors"
    # TAESD saved 20 minutes a picture on the CPU; on the GPU the full
    # decoder costs nothing to speak of, so it is used there.
    return Tools(engine, models[0], taesd if taesd.is_file() and not gpu else None, gpu)


def cover_prompt(title: str, request: str) -> str:
    """What to paint: the story's title and the owner's own words, trimmed
    to what the image model reads (its text encoder stops at 77 tokens)."""
    words = re.sub(r"\s+", " ", f"{title}. {request}").strip()
    # The asking, not the subject: "write me a short story about" goes whole.
    # Word by word it left "A about a clockmaker's apprentice" (2026-10-20).
    words = re.sub(r"\b(please\s+)?(write|tell)(\s+me)?\b", "", words, flags=re.I)
    words = re.sub(r"\b(an?\s+)?((short|long|bedtime|little)\s+)?(story|tale|novella|novel)"
                   r"(\s+(about|of|where|in which))?\b", "", words, flags=re.I)
    words = re.sub(r"\b(in\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
                   r"\s+chapters?\b", "", words, flags=re.I)
    words = re.sub(r"\s+", " ", words).strip(" .,")
    words = re.sub(r"\s+([.,])", r"\1", words)
    cut = " ".join(words.split()[:40])
    return f"{STYLE}: {cut}"


def title_and_request(folder: Path) -> tuple[str, str]:
    """The story's title (story.md or outline.md) and the owner's request.
    Read as utf-8-sig: a file saved by Notepad or PowerShell starts with a
    byte-order mark, and then its '# Title' line was not seen and '# Asked'
    went into the picture's prompt (found painting a cover, 2026-10-20)."""
    folder = Path(folder)
    title = ""
    for name in ("story.md", "outline.md"):
        f = folder / name
        if f.is_file():
            first = f.read_text(encoding="utf-8-sig", errors="replace").splitlines()[:1]
            if first and first[0].startswith("# "):
                title = first[0][2:].strip()
                break
    req = folder / "request.md"
    request = ""
    if req.is_file():
        request = "\n".join(l for l in req.read_text(encoding="utf-8-sig", errors="replace")
                            .splitlines() if not l.startswith("#")).strip()
    return title, request


def command(t: Tools, prompt: str, out: Path, seed: int = 7, size=(SIZE, SIZE),
            init: Path | None = None, strength: float = 0.40, steps: int = 1) -> list[str]:
    """sd-cli's arguments. `init` paints from a picture (the laptop's own
    painting, for the desktop's full-screen scenes): SD-Turbo works at 512,
    and asked for 1344 x 576 from nothing it repeated the room across the
    width; from the old painting at strength 0.40 and 3 steps it kept the
    room and filled the width (trial, 2026-11-04)."""
    w, h = size
    cmd = [str(t.engine), "-m", str(t.model), "-p", prompt, "-W", str(w), "-H", str(h),
           "--steps", str(steps), "--cfg-scale", "1.0", "--sampling-method", "euler_a",
           "-s", str(seed), "-t", str(os.cpu_count() or 2), "-o", str(out)]
    if init is not None:
        cmd += ["-i", str(init), "--strength", f"{strength:.2f}"]
    if t.taesd is not None:
        cmd[3:3] = ["--taesd", str(t.taesd)]
    return cmd


def fit_reference(src: Path, size, dest: Path) -> Path:
    """The reference picture scaled and centre-cropped to `size`, as sd-cli
    wants its init image the size of the picture it paints."""
    from PIL import Image
    w, h = size
    im = Image.open(src).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    im = im.crop(((im.width - w) // 2, (im.height - h) // 2,
                  (im.width - w) // 2 + w, (im.height - h) // 2 + h))
    im.save(dest)
    return dest


def paint(out: Path, prompt: str, cfg=None, seed: int = 7, say=print,
          available_mb=None, popen=subprocess.Popen, size=(SIZE, SIZE),
          reference: Path | None = None, strength: float = 0.40, steps: int = 1,
          vram_free=None) -> Path:
    """Paint `prompt` to `out` (a PNG). Raises ArtistError, saying why, if it
    cannot: no engine or model, too little memory, or no picture came back.
    `reference`: a picture to paint from (fitted to `size` first)."""
    out = Path(out)
    t = tools(cfg)
    if available_mb is None:
        from .platform_probe import mem_available_mb
        available_mb = mem_available_mb
    have = available_mb()
    need = GPU_RAM_MB if t.gpu else RAM_MB
    if have and have < need:
        raise ArtistError(f"Painting needs about {need} MB free and {have} MB is. "
                          "Unload the language model (Model: Off) and try again.")
    if t.gpu:
        if vram_free is None:
            from .machine import gpu_free_mib
            vram_free = gpu_free_mib
        free = vram_free()
        if free is not None and free < GPU_VRAM_MB:
            raise ArtistError(f"Painting on the GPU needs about {GPU_VRAM_MB} MiB free on it and "
                              f"{free} MiB is. Unload the language model (Model: Off) and try again.")
    part = out.with_name(out.stem + ".partial.png")
    part.unlink(missing_ok=True)
    init = None
    if reference is not None:
        init = fit_reference(Path(reference), size, out.with_name(out.stem + ".reference.png"))
    try:
        proc = popen(command(t, prompt, part, seed, size, init, strength, steps),
                     stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                     cwd=str(t.engine.parent))
        for line in proc.stdout:
            if re.search(r"(get_learned_condition|sampling|decode_first_stage|generate_image) "
                         r"completed", line):
                say("Artist: " + line.split(" - ", 1)[-1].strip())
        rc = proc.wait()
    finally:
        if init is not None:
            init.unlink(missing_ok=True)          # the fitted copy, not the reference itself
    if rc != 0 or not part.is_file() or part.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        part.unlink(missing_ok=True)
        raise ArtistError(f"The image engine stopped without a picture (code {rc}).")
    part.replace(out)
    return out


def draw_cover(folder: Path, cfg=None, seed: int = 7, say=print,
               available_mb=None, popen=subprocess.Popen) -> Path:
    """Paint folder/cover.png. Raises ArtistError, saying why, if it cannot."""
    folder = Path(folder)
    title, request = title_and_request(folder)
    if not (title or request):
        tools(cfg)                   # a missing engine is said first
        raise ArtistError("The story has no title or request to paint from.")
    prompt = cover_prompt(title, request)
    say(f"Artist: painting a cover for '{title or request[:40]}'. On this laptop that takes "
        "many minutes.")
    out = paint(folder / "cover.png", prompt, cfg, seed, say, available_mb, popen)
    (folder / "cover-prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    say(f"Artist: the cover is {out.name}.")
    return out
