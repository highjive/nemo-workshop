"""What each employee can help with (owner, 2026-11-04: "when clicked on
individual employees they ask what can they help with in their skill tree").

A skill is something Nemo can already do, put in the hands of the employee
whose job it is; none is new behaviour:

  step      a step of the project it owns (steps.py): run on the open project
  window    a control of its department's own window, by the button's text:
            the window opens with that control lit and the keyboard on it.
            A skill never presses it: most need a choice first (which video,
            which board), and some must never happen unasked (casting to a
            television on the owner's network: docs/design-rules.md).
  ask       the department's own box (gui/askbar.py), for work that starts
            from words
  dialog    one of Nemo's own dialogs, by its class in gui/app.py (the
            Workshop sidebar's Researcher key, Datasheets, Work offline)
  job       a nemo command run as a background job (`nemo eval`)
  verdicts  the SHIP check's past verdicts (shipcheck.history)
  needs     its own tools check (profiles.py)

Every employee has at least its department's window and "What do you need?".
A test holds every window skill to a button that exists.
"""
from __future__ import annotations

from dataclasses import dataclass

STEP, WINDOW, ASK, DIALOG, JOB, VERDICTS, NEEDS = ("step", "window", "ask", "dialog", "job",
                                                  "verdicts", "needs")


@dataclass(frozen=True)
class Skill:
    label: str
    kind: str
    target: str = ""          # a step key, or a button's text ("" = just open the window)


# employee key -> (label, button text) on its department's own window.
WINDOW_SKILLS: dict[str, tuple[tuple[str, str], ...]] = {
    "library.artist": (("Paint a story's cover", "Paint a cover"),),
    "library.editor": (("Open a story's folder", "Open its folder"),),
    "art_studio.designer": (("Add a shape to the model", "Add shape"),),
    "art_studio.clerk": (("Make one from a list", "From a list..."),),
    "art_studio.foreman": (("Queue the model to build", "Queue it"),),
    "art_studio.writer": (("Write the model's card", "Card..."),),
    "storeroom.storekeeper": (("Open the shelves", "Open the shelves"),
                              ("Drives and space", "Drives and space..."),
                              ("The vault", "Vault...")),
    "storeroom.researcher": (("Look through the parts catalogue", "Parts catalogue..."),),
    "theatre.projectionist": (("Play it here", "Play here"), ("Cast it to a Chromecast", "Cast"),
                              ("Stop casting", "Stop")),
    "theatre.streamer": (("Open Chrome to stream", "Open Chrome"),),
    "theatre.curator": (("Show a picture", "Play here"),),
    "theatre.writer": (("Give it a title and a line", "Title and line..."),),
    "music.player": (("Play it here", "Play here"), ("Next track", "Next")),
    "music.dj": (("Find the Chromecasts", "Find Chromecasts"), ("Cast the music", "Cast")),
    "music.writer": (("Save the chosen as a playlist", "Save the chosen as a playlist"),
                     ("Choose a playlist's tracks", "Choose its tracks")),
    "audio.narrator": (("Make the audiobook", "Make the audiobook"),),
    "audio.recorder": (("Record", "Record"),),
    "audio.engineer": (("Ready a sound card", "Choose sounds and ready the card..."),),
    "audio.librarian": (("Play it here", "Play here"),),
    "bench.flasher": (("Flash the board", "Flash it"),),
    "bench.monitor": (("Listen to the board for 10 s", "Listen 10 s"),),
    "bench.writer": (("Look for boards again", "Look again"),),
    "printshop.slicer": (("Slice a model for the printer", "Slice it"),),
    "film.director": (("Plan the film", "Plan"),),
    "film.editor": (("Make the film", "Make the film"), ("Join clips", "Join these")),
    "film.artist": (("A slideshow of pictures", "Slideshow of these"),),
    "film.narrator": (("Make the film with narration", "Make the film"),),
    "home.surveyor": (("Look around the network", "Look around"),),
    "home.gatekeeper": (("Say what a device is", "Set platform"),),
    "home.writer": (("Write the list of devices", "Write the list"),),
    "comms.browser": (("Open a site", "Open"), ("Add a site", "Add a site...")),
    "comms.postman": (("Add a contact", "Add a contact..."),),
    "comms.social": (("Copy it for a post", "Copy for a post"),),
    "comms.writer": (("Check the spelling", "Check spelling"), ("Make it a letter", "Make it a letter")),
    "science.calculator": (("Work it out", "Work it out"),),
    "science.mathematician": (("Work it out", "Work it out"),),
    "science.physicist": (("Work it out", "Work it out"),),
    "science.statistician": (("Work it out", "Work it out"),),
    "science.bookkeeper": (("Open a spreadsheet", "Open a spreadsheet..."),),
    "doctors.nurse": (("Undo the last treatment", "Undo the last treatment"),),
    "doctors.clerk": (("Read the case notes", "Case notes"),),
    "doctors.writer": (("Write a report", "Write a report"),),
    "doctors.gp": (("See the Doctors again", "See the Doctors again"),),
    "doctors.gpu": (("Look at the graphics card now", "See the Doctors again"),),
}

# Work that starts from the owner's words goes to the department's own box
# (gui/askbar.py; owner, 2026-11-09: not back to the home screen).
ASK_SKILLS: dict[str, str] = {
    "library.writer": "Write me a story",
    "library.linguist": "Talk it through with me",
    "workshop.writer": "Describe a new thing to build",
}

# Nemo's own dialogs (gui/app.py classes), given to the employee whose job they are.
DIALOG_SKILLS: dict[str, tuple[tuple[str, str], ...]] = {
    "workshop.researcher": (("Enter my Mouser key", "ResearcherKey"),
                            ("The datasheet library", "DatasheetDialog")),
    "computer_lab.technician": (("Get ready to work offline", "OfflineDialog"),),
    # "Class:Button": the dialog opens with that button lit.
    "workshop.reader": (("Draft a part from a datasheet", "DatasheetDialog:Draft a part from it"),),
}

# nemo commands run as a background job (gui start_job), and their arguments;
# those in PROJECT_JOBS work on the open project (--project <name>).
JOB_SKILLS: dict[str, tuple[tuple[str, str], ...]] = {
    "computer_lab.quality": (("Run the SHIP check (talk against design)", "eval"),),
    "workshop.second": (("Look again at the design's wiring", "second"),),
    "workshop.pcb": (("Make the circuit board", "pcb"),),
}

PROJECT_JOBS = ("second", "pcb")

# Departments with no window of their own: the Workshop and the Computer
# Lab are Nemo's main window (app.real_window).
MAIN_WINDOW = ("workshop", "computer_lab")


def skills_for(key: str) -> list[Skill]:
    """What the employee `key` offers, in the order it says them."""
    from .staff import DEPARTMENTS, STAFF
    from .steps import STEPS
    e = STAFF[key]
    out: list[Skill] = []
    if key in ASK_SKILLS:
        out.append(Skill(ASK_SKILLS[key], ASK))
    for s in STEPS:
        if s.owner == key:
            out.append(Skill(f"Run '{s.name}' on the open project", STEP, s.key))
    for label, args in JOB_SKILLS.get(key, ()):
        out.append(Skill(label, JOB, args))
    if key == "computer_lab.quality":
        out.append(Skill("The verdicts so far", VERDICTS))
    for label, dialog in DIALOG_SKILLS.get(key, ()):
        out.append(Skill(label, DIALOG, dialog))
    for label, button in WINDOW_SKILLS.get(key, ()):
        out.append(Skill(label, WINDOW, button))
    place = DEPARTMENTS[e.department].name
    if e.department in MAIN_WINDOW:
        out.append(Skill(f"Open the {place} (the project window)", WINDOW, ""))
    elif not any(s.kind == WINDOW for s in out):
        out.append(Skill(f"Open the {place} workbench", WINDOW, ""))
    out.append(Skill("What do you need?", NEEDS))
    return out
