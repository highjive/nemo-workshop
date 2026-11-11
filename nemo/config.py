"""Configuration loading for Nemo.

Config lives at ~/.nemo/config.yaml. Every value has a default tuned for a
Fujitsu Lifebook AH531: a Pentium B960 (Sandy Bridge, no AVX), 8 GB DDR3, no GPU compute.
A machine with a GPU that can hold the model runs the modes_desktop table
instead (nemo/machine.py; `machine: auto|laptop|desktop`).
API keys are never read from the config file -- only from the environment.
"""

from __future__ import annotations

import copy
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_HOME = Path(os.environ.get("NEMO_HOME", Path.home() / ".nemo"))
CONFIG_PATH = CONFIG_HOME / "config.yaml"

# Route kinds understood by the router.
LOCAL = "local"
REMOTE = "remote"
LOCAL_THEN_REVIEW = "local_then_review"

DEFAULTS: dict[str, Any] = {
    "engine": {
        "local": "http://127.0.0.1:8080/v1",
        "local_model": "qwen3-4b",
        "review": None,          # e.g. "openrouter/<model>"
        "review_base": "https://openrouter.ai/api/v1",
        "search": None,          # e.g. "querit"
        # How long one model reply may take. Measured on the AH531: the
        # Talk model writes 2 tokens a second and a design reply may run to
        # 2048 tokens, which is 17 minutes before the prompt is even read.
        # At 900 s the enclosure step could not finish. 1800 covers a full
        # reply from the Talk model; the 4B model (0.9 tokens/s) would need
        # about 2600 and is not covered.
        "timeout_s": 1800,
        # Tasks for which the local model is told not to "think" first.
        # Measured on the AH531 with qwen3-1.7b (2.1 tokens/s): asked for a
        # 60-word synopsis with a 220-token limit, the model spent all 220
        # tokens reasoning and returned no text at all, after 129 s. With
        # thinking off the same request returned the whole synopsis in 26 s.
        # Story replies are short and their limits are sized to the words
        # asked for, so reasoning there only ever eats the answer.
        #
        # The design tasks were then measured too (D129): with reasoning on
        # the electrical step ran the full 900 s and returned nothing; with
        # it off the same step returned a script in 13 minutes. Whether
        # reasoning would improve a design reply cannot be known on this
        # machine, because with it on there is never a reply to judge.
        # design_reason is left alone: it goes to a remote model.
        "thinking_off": ["story", "template_fill", "cad_script", "firmware"],
        # Where plain code can write a file from the model's decisions, ask
        # the model for those decisions as JSON held to a schema, instead
        # of for the file. Used by the wiring step (nemo/harness.py). Set
        # false to go back to asking for the whole file.
        "constrain_output": True,
        # Keep the model's reading of each system prompt on disk, so a
        # restarted server does not read it again (nemo/slotcache.py).
        "prompt_cache": True,
        # The Archivist reuses a passed step's answer to an identical request
        # (nemo/archivist.py); false asks the model every time.
        "archive": True,
        # The most llama-server may keep of prompts it has read, in RAM, in
        # MB (its own default is 8192). Inside the 300 MB margin modes.start
        # adds to every mode's figure.
        "cache_ram_mb": 256,
    },
    # Which brain handles which kind of work. The whole point of this file.
    "routing": {
        "template_fill": LOCAL,
        "cad_script": LOCAL_THEN_REVIEW,
        "design_reason": REMOTE,
        "firmware": LOCAL_THEN_REVIEW,
        "offline": "degrade_to_local",
        # Manuscripts are the writer's unpublished work. Story tasks stay on
        # this machine unless routing.story is deliberately changed to
        # local_then_review, which sends each draft to the review provider.
        "story": LOCAL,
    },
    # 8 GB will not hold everything. One mode is resident at a time.
    #
    # ram_mb is the model. tools_mb is what you are about to open alongside
    # it -- reserved up front, because discovering the shortfall after KiCad
    # has loaded means the OOM killer picks, not you.
    "modes": {
        "design": {"model": "qwen3-4b", "ctx": 8192,
                   "ram_mb": 2500, "tools_mb": 1400},
        "build": {"model": "qwen2.5-coder-3b", "ctx": 8192,
                  "ram_mb": 2000, "tools_mb": 900},
        "talk": {"model": "qwen3-1.7b", "ctx": 4096,
                 "ram_mb": 1100, "tools_mb": 200},
    },
    # Windows 11 idles around 3.2 GB on this hardware against roughly 1.2 GB
    # for a trimmed XFCE install, so the same 8 GB machine has about two
    # fewer gigabytes to spend. These override the above on Windows.
    #
    # D136: ram_mb here is what llama-server was MEASURED to hold on the
    # AH531 with the model loaded (design 3111 MB, talk 2070, build 2053,
    # tiny 885), not an estimate. The estimates were 2500 and 1100: talk
    # was allowed to load with 1800 MB free and then held 2070. tools_mb
    # is what the steps' own tools were seen to use over a whole run
    # (Python with CadQuery 409 MB, kicad-cli 139 MB) with a margin. It
    # does NOT cover KiCad's or FreeCAD's window open alongside. Design
    # is the tightest: 3200 + 300 + the 300 every mode adds = 3800. At
    # 4200 it was refused with 4116 MB available, then forced, and the
    # whole pipeline ran with 891 MB to spare (about 3.3 GB used). The
    # Linux figures above and roomy and deep below are still estimates.
    "modes_windows": {
        "design": {"model": "qwen3-4b", "ctx": 4096,
                   "ram_mb": 3200, "tools_mb": 300},
        "build": {"model": "qwen2.5-coder-3b", "ctx": 4096,
                  "ram_mb": 2100, "tools_mb": 700},
        "talk": {"model": "qwen3-1.7b", "ctx": 8192,
                 "ram_mb": 2100, "tools_mb": 400},
        # At 16 GB, raise ctx and stop switching modes -- see doctor.
        # Note that 16 GB buys capacity and context, NOT speed: dual-channel
        # DDR3-1333 is 21.3 GB/s whether the sticks are 4 GB or 8 GB.
        # At 16 GB the constraint stops being "does the model fit" and
        # becomes "how much context can I afford". Bandwidth is unchanged --
        # 2x4 GB and 2x8 GB at DDR3-1333 both give the same 21.3 GB/s -- so
        # tokens come out no faster. What you buy is concurrency and context.
        "roomy": {"model": "qwen3-4b", "ctx": 16384,
                  "ram_mb": 2500, "tools_mb": 3000},
        # Linux only: a 5 GB model does not fit under Windows on 8 GB.
        # Roughly 2 tok/s, so it is for one hard question, not a session.
        "deep": {"model": "qwen3-8b", "ctx": 4096,
                 "ram_mb": 4900, "tools_mb": 400},
        # For a machine with under 8 GB installed. Windows 11 takes ~3.2 GB
        # of that, so a 1B model is not a compromise, it is the ceiling.
        # Gemma 3 1B and Llama 3.2 1B are the realistic picks; both follow
        # a tight template well, which is most of what Nemo asks of them.
        "tiny": {"model": "gemma3-1b", "ctx": 2048,
                 "ram_mb": 900, "tools_mb": 200},
    },
    # auto: the desktop table below where an NVIDIA GPU can hold the design
    # model and the CUDA engine is installed, else the laptop's tables
    # above. laptop or desktop forces one (nemo/machine.py).
    "machine": "auto",
    # The desktop: every layer on the GPU (CUDA build of b11175, -ngl 99,
    # --load-mode none). MEASURED on an i5-12400F + RTX 3050 8 GB, 16 GB
    # DDR4, 2026-11-04, each server loaded and read after it answered:
    #   qwen3-8b          ctx 16384: 779 MB RAM, 6964 MiB GPU, 40 tokens/s written,
    #                     1316/s read (llama-bench pp512/tg128)
    #   qwen3-4b          ctx 16384: 745 MB RAM, 4862 MiB GPU, 68/s written, 2305/s read
    #   qwen2.5-coder-3b  ctx 16384: 603 MB RAM, 2598 MiB GPU
    #   gemma3-1b         ctx  4096: 721 MB RAM,  945 MiB GPU
    # The CPU alone did 14/s (4B) and 7.7/s (8B) on this machine. With the
    # file memory-mapped (llama.cpp's default) the 8B also held 4.9 GB of
    # RAM for nothing, hence --load-mode none. qwen3-8b at ctx 32768 took
    # 7172 MiB, too close to 8 GB with the desktop's own use: 16384 is the
    # ceiling. ram_mb/vram_mb are those figures rounded up; tools_mb is the
    # laptop's, which was measured for the steps' own tools.
    # The design model is the 8B here. It has NOT been run through Nemo's
    # briefs yet (docs/design-rules.md 4e): its first real runs are its test.
    "modes_desktop": {
        "design": {"model": "qwen3-8b", "ctx": 16384, "gpu": True,
                   "ram_mb": 800, "vram_mb": 7000, "tools_mb": 300},
        "deep": {"model": "qwen3-8b", "ctx": 16384, "gpu": True,
                 "ram_mb": 800, "vram_mb": 7000, "tools_mb": 400},
        "roomy": {"model": "qwen3-8b", "ctx": 16384, "gpu": True,
                  "ram_mb": 800, "vram_mb": 7000, "tools_mb": 3000},
        "build": {"model": "qwen2.5-coder-3b", "ctx": 16384, "gpu": True,
                  "ram_mb": 650, "vram_mb": 2650, "tools_mb": 700},
        "talk": {"model": "qwen3-4b", "ctx": 16384, "gpu": True,
                 "ram_mb": 750, "vram_mb": 4900, "tools_mb": 400},
        "tiny": {"model": "gemma3-1b", "ctx": 4096, "gpu": True,
                 "ram_mb": 750, "vram_mb": 950, "tools_mb": 200},
        # The Game Studio's model (owner, 2026-11-11: "adopt only models that are
        # usefull to nemo"). Gemma 4 E4B wrote the only model games that passed the
        # Tester (the boat, twice; 1 of 5 ideas) where qwen3-8b passed 0 of 12; it was
        # no better at briefs, stories or the SHIP check, so it has this one job.
        # MEASURED 2026-11-11 at ctx 16384: 2757 MB RAM (its per-layer embeddings
        # stay in RAM, an inference from its 7.5 B stored for "effective 4B"), 3385 MiB
        # GPU. docs/model-candidates.md.
        "game": {"model": "gemma4-e4b", "ctx": 16384, "gpu": True,
                 "ram_mb": 2800, "vram_mb": 3400, "tools_mb": 300},
    },
    "checks": {
        "tier0": [
            "erc", "drc", "solid", "thickness",
            "compile", "current_sum", "wire_gauge", "xref",
        ],
        "tier1": {"datasheets": "./datasheets", "web": "on_missing_part"},
        "tier2": {"trigger": "before_export",
                  "scope": "contradictions|failure_modes"},
    },
    "hardware": {
        # Printer constraints get injected into every CAD prompt.
        "printer": "Creality Kobra 3",
        "build_volume_mm": [250, 250, 260],
        "nozzle_mm": 0.4,
        "layer_mm": 0.2,
        "min_wall_mm": 1.2,
        "supportless_overhang_deg": 50,
    },
    "paths": {
        "projects": "~/nemo-projects",
        # Bundled parts always load first; this folder is for parts you add
        # yourself, and an entry here with the same ref overrides a bundled
        # one. Not None any more -- "Add a part" needs somewhere of its own
        # to write to that isn't the installed package.
        "parts": "~/nemo-parts",
        "datasheets": "~/nemo-datasheets",
        "stories": "~/nemo-stories",
        # The Storeroom: the parts you have to hand (nemo/storeroom.py).
        "storeroom": "~/nemo-storeroom",
        # The Art Studio Designer's 3D models (nemo/modelkit.py).
        "models": "~/nemo-models",
        # The Game Studio's games, each a Godot project (nemo/gamestudio.py).
        "studio": "~/nemo-studio",
        # RetroArch for the Gaming department, where not found by itself
        # (nemo/gaming.py looks beside the engine and on the PATH too).
        "retroarch": None,
        "llama_server": "llama-server",
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    # DEFAULTS.copy() is shallow: every nested dict (modes, paths, routing...)
    # would be the literal DEFAULTS object, so mutating cfg.data["modes"] on
    # one Config silently mutated DEFAULTS for every Config in the process.
    # No shipped code does that today, but nothing stopped it, and a test
    # that did found DEFAULTS corrupted for the rest of the run.
    data: dict = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    source: Path | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = Path(path) if path else CONFIG_PATH
        if path.exists():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
            return cls(copy.deepcopy(_merge(DEFAULTS, loaded)), path)
        return cls(copy.deepcopy(DEFAULTS), None)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, dotted: str) -> Path:
        raw = self.get(dotted)
        return Path(str(raw)).expanduser()

    def route_for(self, task: str) -> str:
        return self.get(f"routing.{task}", LOCAL)

    def mode(self, name: str) -> dict:
        # The desktop's table first, on the desktop only (nemo/machine.py).
        # The laptop never reads it, so its modes are exactly as before.
        from .machine import is_desktop
        if is_desktop(self):
            m = self.get(f"modes_desktop.{name}")
            if m is not None:
                return m
        # Windows overrides win where they exist. Smaller context mainly:
        # KV cache is real memory, and there is less of it to go round.
        if sys.platform.startswith("win"):
            m = self.get(f"modes_windows.{name}")
            if m is not None:
                return m
        m = self.get(f"modes.{name}")
        if m is None:
            raise KeyError(
                f"unknown mode {name!r}; known: "
                f"{', '.join(self.get('modes', {}))}"
            )
        return m

    @staticmethod
    def api_key(provider: str) -> str | None:
        """Keys come from the environment only.

        Never from the config file, never from the repo, never baked
        into an ISO image.
        """
        for var in (f"NEMO_{provider.upper()}_KEY",
                    f"{provider.upper()}_API_KEY"):
            if os.environ.get(var):
                return os.environ[var]
        return None

