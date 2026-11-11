# Nemo Workshop

Nemo is a creative assistant that runs entirely on your own computer, offline,
on modest hardware. It was written for an eleven-year-old laptop with two cores,
8 GB of memory and no graphics card worth the name, and it also uses a desktop's
NVIDIA card where there is one.

Nemo is organised as departments, each with its own staff:

- **Workshop** turns a sentence ("a desk weather display with an OLED") into a
  hardware project: parts, power budget, schematic, wiring, a 3D-printable
  enclosure with a dimensioned drawing, and firmware. Checks run between every
  step: the language model only fills in what code cannot decide, and code
  checks what it says.
- **Library** writes stories chapter by chapter, paints a cover, and binds them
  as a book (PDF and Word).
- **Art Studio**, **Print Shop**, **Game Studio**, **Film Studio**, **Music Room**,
  **Audio**, **Science**, **Theatre**, **Gaming** and more: 3D models, slicing for a
  printer, small Godot games, short films, audio books, and the rest.
- **Storeroom** keeps your parts, and every department's finished work, with
  every part of each piece to open.

Nemo is about helping people make things. It never sends your work anywhere.

## Status: a test release

This is the first public test release, from one developer, **Highjive**. It has
been built and tested on two machines: a Fujitsu Lifebook AH531 (Pentium B960,
8 GB, Windows 11 and the NemoIso stick) and a desktop with an RTX 3050 (8 GB).
On those, over 2,300 automated tests pass. On anything else it is untested, which is
what this release is for.

**What this release is for: real boards.** Nemo designs a project, writes its
firmware and compiles it, but it has never yet flashed a real board. If you have
one of the boards Nemo's parts library has (an ESP32 DevKit V1, an ESP32-C3 or
ESP32-S3 DevKit, the Waveshare ESP32-S3-LCD-1.28, or a Raspberry Pi
Pico), please build a project with Nemo, flash it, and
tell us what happened: the board, the project, each step's result, and what the
board did. A design that works is as useful to hear about as one that does not.

Also not yet tried for real, so expect rough edges: casting to a TV, playing a
video in the Theatre, and the newest NemoIso images booted on real hardware.

## A safety note: read this before you build anything

Nemo designs electronics that can include batteries, chargers and mains-powered
supplies. Its checks catch many mistakes, but **they are not a substitute for
your own judgement or a qualified person's**. Check every design yourself before
you build it, power it or charge a battery in it. Nemo stops at steps that need
a human decision, and its build guide lists every open question. Read them.

Nemo comes with **no warranty** (see the licence below).

## What you need

- Windows 10 or 11, 64-bit, and an internet connection for the first setup
- 8 GB of memory (it was written for exactly that)
- Plenty of free disk space: the language models alone are about 6.5 GB, the
  Artist's image model about 2 GB, and KiCad, Python and the tools come on top.
  As a rough guide, have 20 GB free.
- Optional: an NVIDIA card with 8 GB or more, which Nemo then uses for the
  bigger models.

## Installing on Windows

1. Download this repository (Code, then Download ZIP) and unpack it.
2. Double-click **NemoDoc.cmd**.

NemoDoc checks the machine, installs what is missing (Python, KiCad, Graphviz
and Git through winget where it can), downloads the models and tools into
`C:\Nemo`, checks every download against its pinned hash, and starts Nemo. Run
it again at any time to check and repair. Switches such as `-SkipModels`,
`-SkipGames`, `-SkipArtist`, `-SkipDrawings` and `-SkipBooks` leave the big
optional parts out; `NemoDoc.ps1 -CheckOnly` changes nothing.

At the end of every run NemoDoc gives a link to the credits page.

## NemoIso: Nemo on a USB stick

NemoIso is a Debian 13 live image with Nemo and its tools. It boots from a USB
stick, keeps your work on the stick, and fits a newer CPU's engine by itself
(`nemodoc --fit`).

The image is about 3.6 GB, which is larger than GitHub allows for one release
file. Build it yourself on Debian 13, or in WSL on Windows:

```
sudo ./install/live-build/build-iso.sh --out NemoIso.iso
```

Then write it to a USB stick with Rufus in ISO mode. If a release offers the
image in parts, join them before writing (Windows: `copy /b NemoIso.iso.part* NemoIso.iso`;
Linux: `cat NemoIso.iso.part* > NemoIso.iso`) and check the result against its
published sha256.

## What Nemo downloads, and their licences

Nemo's own code is GPL-3.0. The tools and models it downloads keep their own
licences, which you accept by using them. Among them:

- The language models: Qwen3 (Apache-2.0), and Gemma (Google's terms for Gemma 3;
  Apache-2.0 for Gemma 4).
- The Artist's image model, SD-Turbo, is under **Stability AI's non-commercial
  community licence**: covers and pictures it paints are for non-commercial use.
  The department scenes shipped in `nemo/data/departments` may include such
  painted scenes, so treat them the same way.
- KiCad, Graphviz, llama.cpp, stable-diffusion.cpp, OrcaSlicer, Godot, FFmpeg,
  CADCraft, WordCraft and the rest: each under its own licence.

`nemo credits` (or **Credits...** in the Storeroom) writes a page naming every
program, package, model and game Nemo is built from, and who made each one, as
they name themselves.

## Reporting a problem

Open an issue here. Say what you did, what you expected, and what happened. The
log NemoDoc writes, `C:\Nemo\nemodoc.log`, helps. **Read it before attaching it:**
it can contain folder names from your own computer.

## More

- [Using Nemo](docs/user-guide.md): the full guide to the windows and commands
- [Keeping it secure](docs/security.md), [Boot and disk protection](docs/hardening.md),
  [Master authority and clones](docs/master-authority.md)
- [Design rules](docs/design-rules.md): the lessons learned building Nemo, each
  from a real defect; read these before changing it

## Licence

Nemo Workshop is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. Anyone may use it, study it, change it and share it, and every copy
and every changed version must stay just as free for the next person.

It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE. See [LICENSE](LICENSE) for the full text.

Nemo Workshop was created by Highjive.
