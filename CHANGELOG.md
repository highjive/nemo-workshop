# Changes

Nemo's revisions are a letter and a number: B.1, B.2 and so on. When the number reaches
127 the letter moves on (B.127, then C.1). Each commit message starts with its revision.

## 0.2.0 (revision B.7), 19 November 2026

### New

- **Music Room: mixing and mastering.** The Mix Engineer mixes a song's stems (one file per
  instrument or voice) in SoundCraft. Code brings every stem to the same level as a starting
  point, moves any stem you name ("vocals=+3", "guitar=-2,left"), bounces the mix, and keeps
  the SoundCraft session so you can carry on by hand. The Mastering Engineer makes a finished
  mix sound like a reference song you choose (Matchering). Nemo never fetches a reference.
  `nemo music mix`, `nemo music master`.
- **Film Studio: hand editing and animation.** The Finishing Editor turns a finished film
  (its title, scenes, credits and subtitles) into a FilmCraft project and opens it to cut by
  hand: `nemo film edit`. The Animator opens OpenToonz for cel animation and renders a
  saved scene's frames into a video: `nemo film animate`. OpenToonz is Windows only for now.
- **Computer Lab: the Rebuilder** opens Craft Anything, which studies a site, app or game you
  own or may examine and has your own signed-in coding agent build your version. Nemo never
  signs in or sets it up for you. `nemo rebuild`, `nemo rebuild doctor`.
- **Every department laid out like the Workshop:** its own list, a New button, a tab for the
  chosen item with buttons for what can be done with it, and the painted room as the Team tab.
  Each department's ask box keeps its own work and loads the language model a request needs.
- **Art Studio: a relief or lithophane from a picture** on the pictures shelf, checked like
  any model and ready for the Print Shop. `nemo model relief`.
- **Nemo signs its paintings.**
- **NemoIso:** SoundCraft, FilmCraft, Craft Anything and Matchering are in the image. Each
  program was run under an emulated processor without AVX before being added.
- Every new program is pinned by its maker's sha256. NemoDoc fetches them on Windows
  (`-SkipCrafts` leaves them out), and the Doctors' tool check looks for newer releases.

### Fixed

- **Battery designs.** The power planner now counts everything a board feeds through the
  step-up converter the board needs, as the current check does. Before, it could recommend a
  cell the check then failed.
- Choosing a battery option now replaces the old cell instead of adding a second one. If
  the new parts no longer fit, the box grows to fit them.
- The schematic keeps a battery chain's links and negatives as separate nets. They had been
  merged by name, which put the charger's protection out of circuit on the schematic (the
  wiring harness was right).
- The size check now lays parts out the way the concept and enclosure steps do.
- A memory card is described as what the player holds, not listed as a part to wire, and
  questions about it are answered from the maker's rules.
- A USB socket is only kept when a USB device is asked for: "rechargeable over USB" is the
  charger's job.
- A spelling suggestion that only adds or removes a hyphen no longer stops a run.
- A cell feeding a 5 V board now gets the library's boost converter.
- Films: each scene is painted from its own seed, so scenes no longer share one layout, and
  the colours a scene's text gives are put into its picture.
- Theatre: a double-click or Enter plays the chosen video or picture. On Linux, Nemo now
  steps aside so the player window is not hidden behind the department.
- The image build no longer downloads llama.cpp's web page, which had stopped the build.

### Known limits

- New program windows have not yet been tried on the 2011 test laptop. Its graphics have no
  Vulkan; FilmCraft has a software mode.
- OpenToonz has no Linux release, so the Animator is not on NemoIso.
- Craft Anything needs the internet and a coding agent you sign in to yourself.

## 0.1.0, 11 November 2026

First public test release.
