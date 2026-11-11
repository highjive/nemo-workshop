"""Nemo's employees, in sixteen departments (owner, 2026-10-21).

There is one language model and it takes turns: 8 GB holds one. An
employee is a job, not a model: a description of what it is for, the
steps it owns, and what it hands on.

Each department works alone, with its own team (owner's words: "each
department works alone but writer will have role in all departments,
designer in the computer lab and art studio for 3d models for printing").
So the same title can be on more than one team: the Workshop's Designer and
the Art Studio's Designer are two jobs. A key is "<department>.<role>".

The Workshop's Inspector (the Reviewer until 2026-10-21) owns no step; it
checks every handoff, before a step starts and after it ends
(nemo/review.py), so a fault is caught at the door rather than as a failed
step.

An employee with `working=False` is on the roster with its job described
but not built yet. Of the five added for speed on 2026-10-21 (Timekeeper,
Archivist, Foreman, Clerk, Technician), none is built: each asks the model
nothing, and is there to save the model work.
"""
from __future__ import annotations

from dataclasses import dataclass

from .steps import STEPS


@dataclass(frozen=True)
class Department:
    key: str
    name: str
    job: str


@dataclass(frozen=True)
class Employee:
    key: str                        # "<department>.<role>"
    title: str
    department: str                 # a DEPARTMENTS key
    job: str
    steps: tuple[str, ...] = ()
    working: bool = True            # False: on the roster, not built yet

    @property
    def label(self) -> str:
        """'Workshop Designer': the title with its department, for the window."""
        return f"{DEPARTMENTS[self.department].name} {self.title}"


DEPARTMENTS: dict[str, Department] = {d.key: d for d in (
    Department("library", "Library",
               "Stories and books: looks things up, writes, illustrates and checks."),
    Department("art_studio", "Art Studio",
               "Pictures and models: paintings, concepts, and 3D models to print, "
               "such as replicas."),
    Department("workshop", "Workshop",
               "Hardware: from the brief to the parts, schematic, wiring, case and "
               "build guide."),
    Department("computer_lab", "Computer Lab",
               "Code and the machine: firmware, 3D printed parts, and keeping the "
               "model and tools running."),
    Department("storeroom", "Storeroom",
               "The parts you have to hand: what, how many, and where they are kept."),
    Department("theatre", "Theatre",
               "Watching: your videos and photos here or on the Chromecast, and websites "
               "streamed from Chrome."),
    Department("gaming", "Gaming",
               "Retro games from the Storeroom, each console's emulator its own employee."),
    Department("music", "Music Room",
               "Your music, played here or cast to the Chromecast, and your playlists."),
    Department("audio", "Audio",
               "Making and keeping sound: audiobooks read from stories, recordings, "
               "sounds readied for a project's sound board, and the listening shelf."),
    Department("bench", "Test Bench",
               "Proving a design runs: the firmware put on the board, and what it says."),
    Department("printshop", "Print Shop",
               "A model made ready for the Kobra 3: G-code, print time and filament."),
    Department("film", "Film Studio",
               "Films from stories, your own clips joined, and slideshows of pictures "
               "with music, for the Theatre."),
    Department("home", "Home",
               "The devices on your home network, and what Nemo may do with each: "
               "only what you allow."),
    Department("comms", "Communications",
               "The web, letters, email and social media; Nemo drafts and opens, you "
               "send and post."),
    Department("science", "Science",
               "Units, maths, physics, statistics and spreadsheets, worked out and shown "
               "step by step."),
    Department("doctors", "Doctors",
               "Diagnose what has gone wrong with the machine, the model, a design or "
               "the stick, and suggest a remedy; nothing is changed without your yes."),
    # The Game Studio (owner, 2026-11-09; nemo/gamestudio.py). Games made in Godot from
    # the owner's own idea; from Claude Code Game Studios (MIT) only its process: idea,
    # design, build, test. The desktop's only: Godot is not proven on the AH531.
    Department("studio", "Game Studio",
               "Your game ideas made into games you can play, in the Godot engine: "
               "designed, built and tested here."),
)}


def _owns(key: str) -> tuple[str, ...]:
    # Who owns a step is said once, in nemo/steps.py.
    return tuple(s.key for s in STEPS if s.owner == key)


def _e(dept: str, role: str, title: str, job: str, working: bool = True) -> Employee:
    key = f"{dept}.{role}"
    return Employee(key, title, dept, job, _owns(key), working)


# The speed jobs (2026-10-21). None asks the model; each saves it work.
_TIMEKEEPER = ("Times every job from the model server's own figures (~/.nemo/<mode>.log), "
               "so what is slow is measured, not guessed.")
_FOREMAN = ("Puts the department's jobs in an order that loads each model once, and "
            "queues long ones, such as pictures, to run overnight.")

STAFF: dict[str, Employee] = {e.key: e for e in (
    # The Library
    _e("library", "researcher", "Researcher",
       "Searches Wikipedia for the facts, names and places a story needs, sending only "
       "the search words, and keeps what it finds with the story (nemo/facts.py)."),
    _e("library", "writer", "Writer",
       "Writes stories: plans them, then writes a chapter at a time, each "
       "spell-checked before the Editor reviews it."),
    _e("library", "artist", "Artist",
       "Makes the book art: a cover for each story now, comics later."),
    _e("library", "linguist", "Linguist",
       "Language and sound: hears what you say (Speak, offline) and says Nemo's news "
       "aloud when a long job ends, or on Read aloud, in a British voice where there "
       "is one (nemo/speech.py, nemo/voice.py). Asks the model nothing."),
    _e("library", "editor", "Editor",
       "Checks all is correct: reviews the plan and each chapter the Writer writes "
       "and sends it back once with the reason."),
    _e("library", "archivist", "Archivist",
       "Remembers answers that passed before, so a department can reuse one instead "
       "of asking the model again; the reused answer is still checked "
       "(nemo/archivist.py)."),
    _e("library", "foreman", "Foreman", _FOREMAN + " (nemo/foreman.py)"),
    _e("library", "timekeeper", "Timekeeper", _TIMEKEEPER + " (nemo/timekeeper.py)"),
    # The Art Studio
    _e("art_studio", "writer", "Writer",
       "Gives each model a title and a line, and writes its card: what it is made "
       "from, its measured size, the Editor's verdict and its slices (nemo/artstudio.py)."),
    _e("art_studio", "artist", "Artist",
       "Draws two concepts to choose from, made from what Nemo can build: a design's "
       "enclosure before the Workshop's Designer models it, or a shaped object as a "
       "blueprint built by code from its parts, which the Art Studio's Designer builds "
       "(nemo/anatomy.py)."),
    _e("art_studio", "designer", "Designer",
       "Makes 3D models to print, such as stands, plaques and simple replicas, from a "
       "kit of shapes added and cut; code writes the CadQuery (nemo/modelkit.py)."),
    _e("art_studio", "editor", "Editor",
       "Checks the work matches what was asked: a closed mesh, walls thick enough, it "
       "fits the printer, and the size the shapes add up to."),
    _e("art_studio", "clerk", "Clerk",
       "Takes the request as choices from lists: a plaque, an open box, a pot, a tag "
       "or a stand, and its sizes, made into the Designer's shapes (nemo/artstudio.py)."),
    _e("art_studio", "foreman", "Foreman", _FOREMAN),
    _e("art_studio", "timekeeper", "Timekeeper", _TIMEKEEPER),
    # The Workshop
    _e("workshop", "researcher", "Researcher",
       "Looks things up: which parts the library has, their pins, sizes and "
       "datasheet figures, and online for what is missing. Finds facts; never "
       "guesses one."),
    _e("workshop", "writer", "Writer",
       "Drafts the brief and checks its spelling, then makes it a clear assignment "
       "for the Designer; at the end, writes the build guide."),
    _e("workshop", "designer", "Designer",
       "Decides the design: the parts and power, which pin goes to which, the "
       "wiring and the case."),
    _e("workshop", "inspector", "Inspector",
       "Checks every handoff: before a step starts, that it has what it needs; "
       "after it ends, what its checks found. Sends work back with the reason."),
    _e("workshop", "clerk", "Clerk",
       "Keeps what you chose from the Brief tab's lists (board, parts, power, size) as "
       "decided: the model is told to leave it out, and code puts it back "
       "(nemo/clerk.py)."),
    _e("workshop", "reader", "Datasheet Reader",
       "Reads a datasheet you add into a draft part: every figure with the page and the very "
       "words it came from, checked by code; what does not hold up is left out, never guessed. "
       "You move a draft into the library yourself (nemo/reader.py; owner, 2026-11-04)."),
    _e("workshop", "second", "Second Opinion",
       "Looks again at the design's pin choices with the other model, one connection at a "
       "time, and says where it thinks one is wrong or is not sure; it changes nothing "
       "(nemo/second.py; owner, 2026-11-04)."),
    _e("workshop", "pcb", "PCB Designer",
       "Lays the design out on a circuit board: places each part's footprint, routes the "
       "copper (Freerouting), has KiCad check it and makes the Gerbers. Only parts whose "
       "footprint and pads are in the library; it names the rest (nemo/pcb.py; owner, 2026-11-04)."),
    _e("workshop", "woodworker", "Woodworker",
       "Told a job and its sizes (flooring, skirting), plans it by code: the area, what "
       "to buy with a waste allowance, the rows and the last one's width, the steps and "
       "the tools; a product's own figures come from its packet (nemo/woodworker.py)."),
    _e("workshop", "foreman", "Foreman",
       _FOREMAN + " Shares the Library's queue (nemo/foreman.py)."),
    _e("workshop", "timekeeper", "Timekeeper",
       _TIMEKEEPER + " Shares the Library's timings (nemo/timekeeper.py)."),
    # The Computer Lab
    _e("computer_lab", "writer", "Writer",
       "Writes each project's firmware guide: which pin goes to which part, what the "
       "code does, how to build, flash and listen to it (nemo/labwriter.py)."),
    _e("computer_lab", "designer", "Designer",
       "Makes 3D printed parts, such as cases, brackets and mounts.", working=False),
    _e("computer_lab", "coder", "Coder",
       "Writes the firmware for the board from the design, and makes it compile."),
    _e("computer_lab", "tester", "Tester",
       "Compiles a project's firmware on its own and reads the build: warnings, RAM "
       "and flash use (nemo/tester.py)."),
    _e("computer_lab", "technician", "Technician",
       "Loads the model the next step needs while you read the last one, only where it "
       "fits in memory (nemo/technician.py)."),
    _e("computer_lab", "rea", "Reverse Engineer",
       "REA: looks inside the programs Nemo runs (Harper, the image engine, RetroArch "
       "and the rest) to say what each is and what it needs, with Ghidra where code must "
       "be read; nothing is run or changed (owner, 2026-10-21)."),
    _e("computer_lab", "quality", "Quality Inspector",
       "Judges a model fit to keep, SHIP or DON'T SHIP, on Nemo's own jobs: asks it the "
       "task file's questions and compares it with the one it would replace, and keeps "
       "every verdict (nemo/shipcheck.py; owner, 2026-11-04)."),
    _e("computer_lab", "foreman", "Foreman", _FOREMAN, working=False),
    _e("computer_lab", "timekeeper", "Timekeeper", _TIMEKEEPER, working=False),
    # The Storeroom (2026-10-21). It asks the model nothing, so it has no
    # Foreman or Timekeeper: there is no model time to order or measure.
    _e("storeroom", "storekeeper", "Storekeeper",
       "Keeps the catalogue of parts you have to hand: how many, where, and which "
       "library part each one is, linked only where the name is exactly that part's; "
       "runs the shop: books, games, videos, pictures and parts on their aisles "
       "(nemo/videostore.py); says what is on hand before any part is asked for; and "
       "makes a backup of your work when you ask (nemo/backup.py)."),
    _e("storeroom", "writer", "Writer",
       "Writes a plain description of each item for its label.", working=False),
    _e("storeroom", "researcher", "Researcher",
       "Suggests which library part an unlinked item is, by its part number and "
       "name and the datasheets that mention it; you choose (nemo/storeroom.py)."),
    # The Theatre (2026-10-21; nemo/theatre.py, nemo/cast.py). Owner's words:
    # "each employee handles different video, streaming, photo".
    _e("theatre", "projectionist", "Projectionist",
       "Video: plays your videos from the Storeroom here, or casts them to the "
       "Chromecast."),
    _e("theatre", "streamer", "Streamer",
       "Streaming: opens Chrome for websites, to cast with Chrome's own Cast button."),
    _e("theatre", "curator", "Photo Curator",
       "Photos: shows your saved pictures, story covers and concept drawings here, or "
       "on the Chromecast."),
    _e("theatre", "writer", "Writer",
       "Keeps a title and a line about each video and photo, yours to write, shown on "
       "the store's cases (theatre.caption)."),
    # Gaming (2026-10-21; nemo/gaming.py): RetroArch, one core per console,
    # each console its own employee (owner's choice). An emulator works on a
    # machine only where its core is installed: gaming.CONSOLES says which.
    _e("gaming", "attendant", "Attendant",
       "Keeps the games shelf in the Storeroom, says which console each game is for, "
       "and hands it to that console's emulator."),
    _e("gaming", "nes", "NES Emulator", "Plays Nintendo Entertainment System games."),
    _e("gaming", "snes", "SNES Emulator", "Plays Super Nintendo games."),
    _e("gaming", "megadrive", "Mega Drive Emulator", "Plays Sega Mega Drive games."),
    _e("gaming", "mastersystem", "Master System Emulator", "Plays Sega Master System games."),
    _e("gaming", "gameboy", "Game Boy Emulator", "Plays Game Boy and Game Boy Color games."),
    _e("gaming", "gba", "Game Boy Advance Emulator", "Plays Game Boy Advance games."),
    _e("gaming", "atari2600", "Atari 2600 Emulator", "Plays Atari 2600 games."),
    _e("gaming", "ps1", "PlayStation Emulator",
       "Plays PlayStation games (PCSX ReARMed); your own BIOS if a game needs one."),
    _e("gaming", "writer", "Writer",
       "Keeps a note card for each game: its controls from RetroArch's own settings, "
       "when it was last played, and your notes (gaming.card)."),
    # The Music Room (owner's choice of a suggested department, 2026-10-21;
    # nemo/music.py, cast.Queue).
    _e("music", "player", "Player",
       "Plays your tracks here, a whole list in order (VLC)."),
    _e("music", "dj", "DJ",
       "Casts a list of tracks to the Chromecast, one after another over one "
       "connection, and lets it go at the end."),
    _e("music", "writer", "Writer",
       "Keeps your playlists, as .m3u files other players read too."),
    # Audio (owner, 2026-10-21; nemo/audio.py): making sound, where the
    # Music Room plays it.
    _e("audio", "narrator", "Narrator",
       "Reads a Library story aloud into an audiobook, a WAV per chapter, in the "
       "British voice, offline."),
    _e("audio", "recorder", "Recorder",
       "Records from the laptop's microphone onto the recordings shelf, and says if "
       "a recording was silent."),
    _e("audio", "engineer", "Sound Engineer",
       "Readies sounds for a DFPlayer Mini's card: numbered folders and files, an "
       "index of which number is which, and a check of each file's kind and rate."),
    _e("audio", "librarian", "Librarian",
       "Keeps the listening shelf (audiobooks, podcasts, recordings) and the place "
       "reached in each when it was cast."),
    _e("audio", "writer", "Writer",
       "Titles each audiobook's chapters in its playlist."),
    # The Test Bench (owner's choice of a suggested department, 2026-10-21;
    # nemo/bench.py).
    _e("bench", "flasher", "Flasher",
       "Puts the project's firmware on the board over USB (PlatformIO's upload)."),
    _e("bench", "monitor", "Serial Monitor",
       "Listens to what the board prints, and says if it crashed or browned out."),
    _e("bench", "writer", "Writer",
       "Keeps a log of every bench run with the project."),
    # The Print Shop (owner's choice of a suggested department, 2026-10-22;
    # nemo/printshop.py).
    _e("printshop", "slicer", "Slicer",
       "Slices the Art Studio's models and the Workshop's enclosures into G-code for "
       "the Kobra 3 with OrcaSlicer and Anycubic's own profiles."),
    _e("printshop", "writer", "Writer",
       "Writes a print card beside the G-code: quality, filament, time, grams, layers."),
    # The Film Studio (owner's choice of a suggested department, 2026-10-22;
    # nemo/filmstudio.py). None asks the model.
    _e("film", "director", "Director",
       "Splits a story into scenes and gives each a picture prompt from its own words; "
       "the plan can be changed before anything is made."),
    _e("film", "artist", "Storyboard Artist",
       "Paints one picture per scene with the image engine, or uses the pictures given."),
    _e("film", "narrator", "Narrator",
       "Reads each scene aloud with Nemo's voice."),
    _e("film", "editor", "Editor",
       "Puts the film together with ffmpeg so every Chromecast plays it; joins your own "
       "clips; makes slideshows of pictures with music."),
    _e("film", "writer", "Writer",
       "Writes the title and credits cards and the subtitles."),
    # Home (owner's choice of a suggested department, 2026-10-22; nemo/home.py).
    _e("home", "surveyor", "Surveyor",
       "Lists the devices on your network from what they announce and the address list "
       "the computer already holds; never connects to one or logs in."),
    _e("home", "gatekeeper", "Gatekeeper",
       "Keeps your permission for each device (hidden, see or use), logs every change, "
       "and is asked before Nemo casts to anything."),
    _e("home", "keeper", "Device Keeper",
       "Your Nemo-built boards: which were flashed, which are seen on the network, and "
       "their status where you allow it."),
    _e("home", "writer", "Writer",
       "Writes the list of your home's devices."),
    # Communications (owner's choice of a suggested department, 2026-10-22;
    # nemo/comms.py). Nothing is sent, posted or logged into by Nemo.
    _e("comms", "browser", "Browser",
       "Opens the web in your own browser and keeps your bookmarks."),
    _e("comms", "postman", "Postman",
       "Keeps your address book and opens your mail program with a draft in it; you "
       "press Send."),
    _e("comms", "social", "Social",
       "Opens your social sites and copies a drafted post for you to paste; never logs "
       "in or posts."),
    _e("comms", "writer", "Writer",
       "Drafts letters, emails and posts from your words, spell-checked, a letter laid out."),
    # Science (owner's choice of a suggested department, 2026-10-22, the
    # spreadsheets put here at his word; nemo/science.py).
    _e("science", "calculator", "Calculator",
       "Converts units with the working shown, and refuses a conversion that cannot be."),
    _e("science", "mathematician", "Mathematician",
       "Solves, simplifies, factors, differentiates and integrates, exact then as a decimal."),
    _e("science", "physicist", "Physicist",
       "Works a physics formula for the missing quantity, the units carried through."),
    _e("science", "statistician", "Statistician",
       "Mean, spread, trend and odd values of a column of numbers, with a chart."),
    _e("science", "bookkeeper", "Bookkeeper",
       "Reads your Excel files and writes new ones with working formulas."),
    _e("science", "writer", "Writer",
       "Writes each answer as a worked sheet: the question, the steps, the answer."),
    # The Doctors (2026-10-21; nemo/clinic.py). They diagnose and advise,
    # changing nothing; the Nurse (phase 2) applies a remedy only on a yes.
    # None asks the model: it may be the patient.
    _e("doctors", "memory", "Memory Checker",
       "Now and then, when asked, checks your recall of five words, kept as a private "
       "trend; not a medical test (nemo/memorycheck.py)."),
    _e("doctors", "gp", "GP",
       "Sees every case first: asks each specialist, and says plainly what is "
       "not known rather than guessing a diagnosis."),
    _e("doctors", "machine", "Machine Specialist",
       "Memory, processor, graphics and missing tools (the machine check)."),
    _e("doctors", "gpu", "GPU Specialist",
       "The graphics card the models run on: how hot and busy it is, and whether a mode "
       "or a painting will fit in what is free on it (owner, 2026-11-04)."),
    _e("doctors", "model", "Model Specialist",
       "Why a model will not load or answer: a stale record, a missing model file, "
       "too little memory, a failed model step, the server's own words."),
    _e("doctors", "design", "Design Specialist",
       "A design step that failed, and where its suggested fixes are."),
    _e("doctors", "stick", "Stick Specialist",
       "Whether work is being kept on the boot stick."),
    _e("doctors", "clerk", "Records Clerk",
       "Keeps the case notes: each visit, what was found and what was advised."),
    _e("doctors", "nurse", "Nurse",
       "Applies a remedy you said yes to, one at a time, and keeps a copy so it can "
       "be undone (nemo/nurse.py)."),
    _e("doctors", "writer", "Writer",
       "Writes a case report you can send: the last visit, treatments and missing tools, "
       "with no briefs, stories or keys, and project names replaced (clinic.report)."),
    # The Game Studio (2026-11-09). Code makes each game of a kind it knows; for an idea
    # of no known kind, the desktop's model writes the script and the Tester judges it.
    _e("studio", "designer", "Game Designer",
       "Reads your idea and chooses the kind of game and its settings: the player, the goal, "
       "what to collect, how many levels, how fast; asks nothing about your gaming history."),
    _e("studio", "level", "Level Designer",
       "Builds each level by code, and checks every jump can be made before it is kept."),
    _e("studio", "programmer", "Programmer",
       "Writes the game's Godot project by code from the Designer's choices; for an idea of "
       "no known kind, has the desktop's model write the script, marked as the model's."),
    _e("studio", "tester", "Tester",
       "Runs every game in Godot without a window before you play it: the scripts load, "
       "the level is built, it runs; says what failed and where."),
    _e("studio", "writer", "Writer",
       "Writes how to play each game: its keys, its goal, and what it was made from."),
)}


def owner(step: str) -> Employee:
    """The employee whose step it is."""
    for e in STAFF.values():
        if step in e.steps:
            return e
    raise KeyError(f"no employee owns the step {step!r}")


def team(department: str) -> list[Employee]:
    """A department's employees, in roster order."""
    if department not in DEPARTMENTS:
        raise KeyError(f"no department called {department!r}; "
                       f"they are {', '.join(DEPARTMENTS)}")
    return [e for e in STAFF.values() if e.department == department]
