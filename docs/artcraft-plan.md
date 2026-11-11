# ArtCraft for Nemo: scan and plan (2026-11-11)

Asked: "https://getartcraft.com/ scan and make plan to use to improve Nemo".
A plan only. Nothing downloaded, installed or run (standing rule: ArtCraft is not
created or tested until the owner asks; downloads only on his yes).

## What ArtCraft is (read from getartcraft.com and the GitHub READMEs, 2026-11-11)

- 17 "Crafting Apps" by the ArtCraft team (github.com/storytold), each written in Rust,
  MIT OR Apache-2.0, for Windows, Linux (.deb, tarball, AppImage, Flatpak), macOS and the
  browser. No account, no subscription.
- Every app has a headless `<app>-cli` (one-shot runs, scripts, JSON commands) and an
  MCP server. This is what matters for Nemo: Nemo drives its tools as programs it runs
  and checks (CadQuery, KiCad, OrcaSlicer, Godot), and a CLI fits that exactly.
- Each release lists SHA256SUMS.txt, so a version can be pinned and hash-checked the
  way NemoDoc pins every other tool.
- Status, in their own words: every app is "early alpha" or "in development".
  CADCraft's README keeps an honest "what works today" table; others were not read
  in full.
- ArtCraft Studio (the AI image/video app) renders with "the latest image and video
  models" on their side. Not local, so not for Nemo.

## What fits Nemo, best first

| # | App (its CLI) | Nemo department | What it would add | Why it ranks here |
|---|---|---|---|---|
| 1 | **CADCraft** (`cadcraft-cli run --script ... --save x.dxf --export x.pdf`, `info`, `convert`) | Workshop, Print Shop, Woodworker | Real dimensioned 2D drawings: an enclosure's panel drawings with hole positions and dimensions; flat parts as **DXF for a laser cutter or CNC**; the Woodworker's floor plan with boards hatched, dimensioned, plotted to PDF at true scale. `cadcraft-cli info` reads the result back, so a gate can check it the way Godot checks a game. | Nemo's blueprints today are pictures (PNG) drawn by its own code: no file a machine can cut from, no dimensions you can measure off a print. The most direct gain for a design assistant. |
| 2 | **MaterialCraft** (`materialcraft-cli render`), **TextureCraft** | Game Studio, Art Studio | Procedural materials exported as PNG (colour, normal, roughness, height): ground, rock, wood, water tiles for the Godot games. | The games use plain coloured boxes, and model-written games failed on pictures that do not exist (`res://player.png`). Code could make the pictures first, then the game. |
| 3 | **WordCraft** (`wordcraft-cli convert story.docx story.pdf`, `text`, `inspect`) | Library (stories), project reports | Stories and the project pack as a laid-out book or document (DOCX/ODT/PDF), and reading a DOCX the owner gives Nemo. | Useful, but plain text and Python already cover most of it. |
| 4 | **PdfCraft** (`combine`, `extract`, `split`, `info`) | Library, Workshop | One PDF of the pack: drawings, BOM, the datasheet pages that matter. | pypdf (already in the image) does combine/split; worth it only with 1 and 3. |
| 5 | **GridCraft** (`run ... --out`, `eval`) | Workshop | BOM and power budget as a real spreadsheet with working formulas. | Small gain; CSV works today. |
| 6 | **AniCraft / EffectCraft** (`gif`, `render --out main.mp4`) | Film Studio, Game Studio | Titles, simple animations, an animated GIF of a game for its README. | Film Studio already has ffmpeg; nice-to-have. |
| 7 | SoundCraft, LightCraft, PhotoCraft, DeckCraft, FigCraft, DesignCraft, VectorCraft | Music, Art Studio, ... | Possible later; no clear gap they close today. | Not planned. |
| - | Craft Anything, ArtCraft Studio | - | - | Not for Nemo: Studio uses hosted models; Craft Anything rebuilds websites with AI. |

## Stage 1: done (2026-11-11, owner's yes)

CADCraft 0.19.0 (the newest release, two days old; the site still showed 0.18.0),
Windows portable zip, hash checked, in C:\Nemo\tools\cadcraft. The enclosure step
now makes `enclosure/drawings/housing.dxf`, `.pdf` (1:1) and `.png`, and checks them by
reading the DXF back (nemo/drawings.py). Facts found by running it, not from the README:
- `exportpdf` fits the drawing to the page unless given `"fit": false`; with it and
  `"scale": 1` the PDF measured exactly 100.0 mm for 100 mm.
- `entities` returns each dimension's own `measurement`, which the gate compares.
- 44 commands draw, save, export and read back in about 0.4 s on the desktop.
Not done yet: a printout measured with a ruler (the PDF's own numbers were measured);
the Woodworker's floor plan; stage 2 (NemoIso).

## Stages 2 to 4 (2026-11-11, "continue till final stage")

- Stage 1's rest: the Woodworker's floor, to scale (`nemo wood "... 4.2 x 3.1 m" --board 1380x193`).
- Stage 2, done in code: the image fetches CADCraft's Linux build (pinned). Its CLI drew,
  exported and read back under QEMU as a Westmere and as a Sandy Bridge without AVX, where an
  AVX test program was killed with SIGILL. On the AH531 itself: not yet booted.
- Stage 3, NOT built: MaterialCraft 0.3.0 has only atomic nodes (no noise, brick or wood
  generators), so tiles would mean building generator graphs by hand. Look again when its
  library grows (the Doctors' tool look does not list it: not adopted).
- Stage 4, done: WordCraft 0.17.0 binds a story as book.docx and book.pdf and turns BUILD.md
  into the pack PDF; both read back. PdfCraft was not needed: pypdf joins the pages.

## The plan

**Stage 1: CADCraft in the Workshop (one pilot, on the desktop first).** Needs the owner's yes
to download the pinned `cadcraft-cli` (Windows portable zip and Linux tarball, 0.18.0,
checked against its SHA256SUMS.txt).
1. Pin it like every tool: version and sha256 in one list that NemoDoc, build-iso and
   `nemo/toolupdates.py` share (a test holds them together); the Doctors' "look for newer
   tools" gains it. Missing = INFO, never a failure (an optional tool, D206).
2. Nemo writes the drawing as a CADCraft command script, by code, from geometry it
   already has: the enclosure's panels and holes (enclosure.py), the blueprint's three views
   (concept.py), a room's boards (woodworker.py). No model writes it.
3. `cadcraft-cli run --metric --script panel.scr --save panel.dxf --export panel.pdf`.
4. A gate: `cadcraft-cli info panel.dxf` read back, and the extents and hole count compared with
   Nemo's own numbers. A drawing that disagrees stops the step, like the electrical gates.
5. The pack gains `drawings/*.dxf` and `*.pdf`. Tested on one real project (the wireless dock),
   and a printed PDF measured with a ruler at 1:1.

**Stage 2: on the AH531 / NemoIso.** Unknown until tried: whether the Linux tarball
starts on the Pentium B960 (no AVX; which x86-64 level the binaries need), its memory,
and its speed. If the release binary does not start, it can be built from source in the
image (`cargo`, Rust 1.95+, not in the image today), as llama-server is. Not before
Stage 1 works.

**Stage 3, if 1 and 2 earn it: materials for the Game Studio.** `materialcraft-cli` makes
the tiles a game names before the game is written (code first, the model only places
them), so a model game cannot ask for a picture that is not there.

**Stage 4: WordCraft / PdfCraft for the pack and stories**, only if the owner wants printed
books or a single pack PDF.

## Risks, said plainly

- Early software. A pin and a gate are the guard: Nemo checks every file it gets back
  rather than trusting it.
- The CLIs' exact behaviour (units, the PDF's scale, exit codes) is read from READMEs
  only, not run. Stage 1 is where that becomes fact.
- Not adopted for: 3D models (CadQuery stays), PCBs (KiCad stays), slicing (OrcaSlicer
  stays), video encoding (ffmpeg stays).
- MCP is not used: Nemo is not an MCP client, and the CLI does everything planned here.
