# Model candidates for Nemo (2026-11-11)

Asked: "look at different LLMs that may be useful to use and run through REA".
The desktop only (RTX 3050, 8 GB): the AH531's own trial of Qwen3.5 2B/4B on
2026-10-19 found no gain, and nothing here was tried on it.

## What Nemo runs now (REA, header only: what each file declares)

| File | Architecture | Parameters | Declared context | Quantisation | Used as |
|---|---|---|---|---|---|
| qwen3-8b.gguf | qwen3 | 8.19 B | 40,960 | Q4_K_M | desktop Design / Deep / Roomy |
| qwen3-4b.gguf | qwen3 | 4.02 B | 40,960 | Q4_K_M | desktop Talk; laptop Design |
| qwen2.5-coder-3b.gguf | qwen2 | 3.40 B | 32,768 | Q4_K_M | Build |
| qwen3-1.7b.gguf | qwen3 | 1.72 B | 40,960 | Q4_K_M | laptop Talk |
| gemma3-1b.gguf | gemma3 | 1.00 B | 32,768 | Q4_K_M | Tiny |
| qwen3-0.6b-draft.gguf | qwen3 | 0.60 B | 40,960 | Q8_0 | draft model |

Every one carries its own chat template. REA reads declarations only: how well a
model does Nemo's work is measured by running it, below.

## Can Nemo's engines load the newer ones?

The architecture names each llama.cpp engine knows, read from its own `llama.dll`
(C:\Nemo\engine-cuda and C:\Nemo\engine, both 3,189,248 bytes): among them `qwen35`,
`qwen35moe`, `qwen3next`, `gemma4`, `gemma3n`, `smollm3`, `lfm2`, `granitehybrid`,
`phi3`, `glm4`, `deepseek4`. So Qwen3.5 and Gemma 4 load with no engine change. The
NemoIso engine (built from build-llama.sh's pinned commit) was NOT checked.

## The three downloaded (owner's yes, 2026-11-11)

Each into its own fresh folder under C:\Nemo\models-trial; size and sha256 checked
against Hugging Face's listing, and REA hashed every byte again (full-file SHA-256).

| File | From | Size | sha256 | Architecture | Parameters | Context | Licence (model card) |
|---|---|---|---|---|---|---|---|
| Qwen3.5-9B-Q4_K_M.gguf | unsloth/Qwen3.5-9B-GGUF (of Qwen/Qwen3.5-9B, 2026-02-27) | 5,680,522,464 | 03b74727...52b7e8 | qwen35 | 8.95 B | 262,144 | Apache-2.0 |
| gemma-4-E4B-it-Q4_K_M.gguf | unsloth/gemma-4-E4B-it-GGUF (of google/gemma-4-E4B-it, 2026-03-02) | 4,977,171,584 | 85a896a0...1fab87 | gemma4 | 7.52 B stored ("effective 4B": per-layer embeddings) | 131,072 | Apache-2.0 |
| Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf | bartowski/Qwen2.5-Coder-7B-Instruct-GGUF (of Qwen/Qwen2.5-Coder-7B-Instruct, 2024-09-17) | 4,683,074,336 | 1664fcca...f956b6 | qwen2 | 7.62 B | 32,768 | Apache-2.0 |

REA evidence: Qwen3.5 ev_d5785d5d..., Gemma 4 ev_00a53a20..., Coder ev_62efabd5...
The licences are the model cards' own field; the licence texts were not read.

Why these three: Qwen3.5 9B is this year's most-cited model for an 8 GB card, the
possible successor to qwen3-8b; Gemma 4 E4B is another family to compare; the Coder
is a dedicated coding model, for the Game Studio's GDScript (O41).

## How they are judged (Nemo first)

All in a trial home (NEMO_HOME=C:\Nemo\trial-home: Nemo's config copied with three trial
modes, the models hard-linked, its own folders), so Nemo's own setup is untouched.

1. The SHIP check (`nemo eval`, 48 tasks from the parts library) against Design mode.
2. The same two briefs as the 2026-11-08 samples (robot car, desk weather display),
   drafted and run through the steps.
3. The same four-chapter story (the canal boat).
4. The Game Studio's boat game (a kind code does not build: the model writes GDScript,
   Godot judges it).

Speeds come from the server's own figures. One run is one sample (docs/design-rules.md 4e).

## Results

One sample each, on the desktop (RTX 3050), 2026-11-11.

| Model | SHIP check (48) | Robot car brief | Weather display brief | Story (4 chapters) | Boat game (GDScript) |
|---|---|---|---|---|---|
| qwen3-8b (Design now) | 48 | Nemo fixed 3 slips | Nemo fixed 2 | 1 chapter sent back, 46 s | failed |
| Qwen3.5 9B | 46 | Nemo fixed 1 | clean | clean, 63 s | failed |
| Gemma 4 E4B | 43 | stopped first (no box), then clean after D267/D270 | stopped first (no box, "oled"), then ran to the pack after D267-D269 | clean, 40 s | **passed and plays** |
| Qwen2.5 Coder 7B | 44 (36 before D266) | Nemo fixed 1 | Nemo fixed 2 | repeats kept | failed (no boat.png) |

Every robot run, all four models, then stops at the parts step: the library's 1000 mAh
cell is listed at 1000 mA continuous (1C, "conservative") and the DRV8833 counts 1200 mA,
so the peak is 1590 mA. That is the library's figure doing its job, not a model's slip;
the owner decides (a bigger cell, or the motors' own current).

The Gemma game is C:\Nemo\trial-home\trial-studio\Boat-Stars-3 (blue boat, rocks, stars,
score): the FIRST model-written game to pass Nemo's Tester (O41).

### What Nemo got wrong, found by the trials (fixed, each with a test that fails on the old code)

- D266 the SHIP check scored a JSON answer inside a ```json fence as wrong (the Coder: 0 of 8).
- D267 a draft with no box size stopped the brief; Nemo now sizes the box to hold the parts.
- D268 the Writer called "oled" a misspelling of "old": a part's all-capital words are known small too.
- D269 two I2C parts on different pin pairs passed the electrical step and stopped firmware;
  code now joins them to one bus.
- D270 a part the REQUEST explains ("motors driven by a DRV8833") stopped the Inspector when
  the draft dropped the word; the request's own clause is added to the constraints.

### Reading of it (not a decision: the owner chooses)

- Gemma 4 E4B: fastest story, the only game that passed, the weakest SHIP score (43).
- Qwen3.5 9B: the cleanest briefs, a slower story, 46 on the SHIP check.
- qwen3-8b: still the best SHIP score; its briefs needed the most fixing.
- Qwen2.5 Coder 7B: no gain anywhere, including the game it was brought in for.

### Games again, five ideas each (2026-11-11, before deciding)

The boat, an asteroid dodger, a caterpillar, a brick breaker, a maze; three tries each, Godot judging.

| Model | Passed | How the rest failed |
|---|---|---|
| Gemma 4 E4B | 1 of 5 (the boat, as in the first trial) | scripts that load, then look up nodes they never named (get_node("ColorRect")); an int passed as a Vector2 |
| qwen3-8b | 0 of 5 (0 of 12 over two days) | parse errors, a variable declared twice, picture files that do not exist (res://player.png) |

### Decision (owner, 2026-11-11: "adopt only models that are usefull to nemo")

- **Gemma 4 E4B: adopted for one job**, the Game Studio's model-written games: the desktop's
  Game mode (C:\Nemo\models\gemma4-e4b.gguf, sha256 85a896a0...1fab87, unchanged by the move).
  `nemo studio new` loads it for an idea no code builds. Measured loaded at ctx 16384:
  2757 MB RAM, 3385 MiB GPU. It is not better at briefs, stories or the SHIP check, so it
  does nothing else. One pass in five is still weak: kinds built by code stay the way (O41).
- **Qwen3.5 9B and Qwen2.5 Coder 7B: not adopted, deleted** (10.4 GB; owner's yes).
- qwen3-8b stays the design model, qwen3-4b talk.

## Not done

- The GDScript benchmark found (flockbay/godot-llm-bench, MIT: 15 Godot 4 tasks judged
  headless on 4.7.2) drives only Claude Code or Codex; Nemo would need its own runner.
- Nothing about the AH531 or NemoIso.
