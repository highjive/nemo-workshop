"""Nemo's desktop window.

Sized for a 1366x768 laptop screen. All behaviour lives in controller.py;
this file only draws it and wires up the controls.
"""

from __future__ import annotations

import math
import os
import sys
import re
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from . import controller as C
from . import theme as T
from .worker import Job


def _when(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d %b %Y, %H:%M") if ts else ""


def light_button(win, text: str) -> bool:
    """Find the button reading `text` in `win`, light it and put the keyboard
    on it, without pressing it (nemo/skills.py: a skill never acts unasked).
    False where the window has no such button."""
    stack = [win]
    while stack:
        w = stack.pop()
        try:
            if isinstance(w, (ttk.Button, tk.Button)) and w.cget("text") == text:
                if isinstance(w, ttk.Button):
                    w.configure(style="Primary.TButton")
                else:
                    w.configure(bg=T.ACTION, fg="white")
                w.focus_set()
                return True
            stack.extend(w.winfo_children())
        except tk.TclError:
            continue
    return False


def _saved_height(geometry: str | None) -> int:
    """The height in a saved "WxH+X+Y", 0 if there is none to read."""
    m = re.match(r"\s*\d+x(\d+)", geometry or "")
    return int(m.group(1)) if m else 0


# ====================================================================
#  The traveller: the route card that follows a job through each station
# ====================================================================

class Traveller(tk.Canvas):
    ROW = 66
    TOP = 18

    def __init__(self, master, fonts, on_select):
        super().__init__(master, bg=T.PANEL, highlightthickness=1,
                         highlightbackground=T.RULE, width=330)
        self.fonts = fonts
        self.on_select = on_select
        self.rows: list[C.StepRow] = []
        self.selected = 0
        self.running_stage: str | None = None
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Up>", lambda e: self._move(-1))
        self.bind("<Down>", lambda e: self._move(1))
        self.configure(takefocus=1)

    def set_rows(self, rows, running: str | None = None):
        self.rows, self.running_stage = rows, running
        self.draw()

    def _move(self, d):
        if self.rows:
            self.selected = max(0, min(len(self.rows) - 1, self.selected + d))
            self.draw(); self.on_select(self.selected)

    def _click(self, e):
        self.focus_set()
        i = int((e.y - self.TOP) // self.ROW)
        if 0 <= i < len(self.rows):
            self.selected = i
            self.draw(); self.on_select(i)

    def _stamp(self, cx, cy, word, colour):
        # A rubber stamp: outline and word, turned a few degrees.
        w, h, a = 76, 22, math.radians(-5)
        pts = []
        for dx, dy in ((-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)):
            pts += [cx + dx*math.cos(a) - dy*math.sin(a),
                    cy + dx*math.sin(a) + dy*math.cos(a)]
        self.create_polygon(pts, outline=colour, fill="", width=2)
        self.create_text(cx, cy, text=word, fill=colour, angle=5,
                         font=self.fonts["stamp"])

    def draw(self):
        self.delete("all")
        W = int(self.winfo_width()) or 330
        if not self.rows:
            return
        x0 = 30
        # the route line joining the stations
        ys = [self.TOP + i*self.ROW + self.ROW/2 for i in range(len(self.rows))]
        for i in range(len(ys) - 1):
            done = self.rows[i].status in ("passed", "done", "unchecked")
            self.create_line(x0, ys[i] + 14, x0, ys[i+1] - 14, width=2,
                             fill=T.PASS if done else T.RULE)
        for i, (row, y) in enumerate(zip(self.rows, ys)):
            if i == self.selected:
                self.create_rectangle(2, y - self.ROW/2 + 3, W - 2,
                                      y + self.ROW/2 - 3, fill=T.SELECT,
                                      outline="")
            status = "running" if row.stage == self.running_stage else row.status
            col = T.STATUS_COLOUR.get(status, T.INK2)
            filled = status in ("passed", "done")
            self.create_oval(x0-13, y-13, x0+13, y+13, width=2, outline=col,
                             fill=col if filled else T.PANEL)
            self.create_text(x0, y, text=str(row.number),
                             fill=T.PANEL if filled else col,
                             font=self.fonts["strong"])
            self.create_text(x0 + 26, y - 9, text=row.name, anchor="w",
                             fill=T.INK, font=self.fonts["strong"])
            from ..staff import owner
            who = owner(row.stage).label
            sub = ("written by you or Nemo"
                   if row.stage == "brief" else
                   "uses the language model" if row.needs_model
                   else "no model needed")
            if row.when:
                sub = _when(row.when)
            sub = f"{who} \u00b7 {sub}"
            self.create_text(x0 + 26, y + 10, text=sub, anchor="w",
                             fill=T.INK2, font=self.fonts["small"])
            words = {"passed": "Passed", "done": "Done", "failed": "Failed",
                     "unchecked": "Unchecked", "running": "Running"}
            if status in words:
                self._stamp(W - 52, y, words[status], col)


# ====================================================================
#  The main window
# ====================================================================

def _press_focused(event):
    """Enter on a focused button or tick box presses it (Space already did)."""
    try:
        if str(event.widget.cget("state")) != "disabled":
            event.widget.invoke()
    except (tk.TclError, AttributeError):
        return None
    return "break"


class NemoApp(tk.Tk):
    def __init__(self):
        if sys.platform.startswith("win"):
            # Nemo's own entry on the taskbar, with its cog, not grouped
            # under Python's (owner, 2026-10-29). Before the first window.
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Nemo.Assistant")
            except (AttributeError, OSError):
                pass
        super().__init__()
        self.title("Nemo")
        if sys.platform.startswith("win") and C.logo_ico().is_file():
            try:
                self.iconbitmap(default=str(C.logo_ico()))   # the title bar and Alt+Tab, crisp
            except tk.TclError:
                pass
        # Nemo's cog on every window: True gives it to the windows opened later.
        try:
            self._icons = [tk.PhotoImage(file=str(C.logo(n))) for n in (64, 32, 16)]
            self.iconphoto(True, *self._icons)
        except (tk.TclError, OSError):
            self._icons = []
        self.settings = C.load_settings()
        self.text_percent = T.text_size(C.load_settings().get("text_size", 100))
        self.fonts = T.pick_fonts(self, self.text_percent)
        # Find and replace in every text box, as Notepad has it (nemo/gui/findbar.py).
        from .findbar import install as _install_find
        _install_find(self)
        self.cfg = C.config()
        self.library = C.parts_catalog(self.cfg)
        self.project = None
        self.loaded_brief = None
        self.job: Job | None = None
        self.job_kind = ""
        self.pending_after_job = None
        self.running_stage = None

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(self.settings.get("geometry") or
                      f"{min(1366, sw)}x{min(740, sh - 40)}+0+0")
        self.minsize(1024, 620)
        # Owner, 2026-11-04 (full screen, more user friendly): 740 tall on a
        # 768 screen put the bottom 30 pixels under Windows' taskbar, hiding
        # each room's buttons and the last sidebar buttons. Maximised, Windows
        # keeps it inside the work area; it opens so unless it was left
        # un-maximised, and a saved size taller than the screen is not kept.
        if sys.platform.startswith("win") and (self.settings.get("zoomed", True) or
                             _saved_height(self.settings.get("geometry")) > sh - 48):
            self.state("zoomed")
        self.configure(bg=T.PAPER)
        self._style()
        self._header()
        self._statusbar()
        self._body()
        self._keys()
        self.protocol("WM_DELETE_WINDOW", self._close)

        try:                                     # the paintings into Nemo's own folder, once
            from .. import art
            art.migrate(self.cfg.path("paths.storeroom"))
        except OSError:
            pass
        self.refresh_projects(select=self.settings.get("last_project"))
        self._timers = {}
        self._timers["mem"] = self.after(200, self._tick_memory)
        self._timers["job"] = self.after(150, self._tick_job)

    # ---------------------------------------------------------- style
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        f = self.fonts
        s.configure(".", background=T.PAPER, foreground=T.INK, font=f["body"],
                    bordercolor=T.RULE, lightcolor=T.PAPER, darkcolor=T.PAPER,
                    troughcolor=T.PANEL, focuscolor=T.BLUE)
        s.configure("TNotebook", background=T.PAPER, borderwidth=0)
        s.configure("TNotebook.Tab", padding=(16, 6), font=f["body"],
                    background=T.PAPER, foreground=T.INK2)
        s.map("TNotebook.Tab", background=[("selected", T.PANEL)],
              foreground=[("selected", T.INK)])
        s.configure("TFrame", background=T.PAPER)
        s.configure("Panel.TFrame", background=T.PANEL)
        s.configure("TLabel", background=T.PAPER, foreground=T.INK)
        s.configure("Panel.TLabel", background=T.PANEL)
        s.configure("Muted.TLabel", foreground=T.INK2, font=f["small"])
        s.configure("PanelMuted.TLabel", background=T.PANEL,
                    foreground=T.INK2, font=f["small"])
        s.configure("H2.TLabel", font=f["h2"])
        s.configure("PanelH2.TLabel", font=f["h2"], background=T.PANEL)
        s.configure("Title.TLabel", font=f["title"], background=T.PANEL)
        s.configure("TButton", padding=(12, 5), background=T.PANEL)
        s.configure("Narrow.TButton", padding=(4, 5), background=T.PANEL)
        # Every combobox and its drop-down list in Nemo's (named, sizeable) font.
        self.option_add("*TCombobox*Listbox.font", f["body"])
        self.option_add("*TCombobox.font", f["body"])
        s.map("TButton", background=[("active", T.SELECT)])
        s.configure("Primary.TButton", background=T.BLUE, foreground="white",
                    bordercolor=T.BLUE)
        s.map("Primary.TButton", background=[("active", T.ACTION_DOWN),
                                             ("disabled", T.RULE)])
        s.configure("Treeview", background=T.PANEL, fieldbackground=T.PANEL,
                    rowheight=24, font=f["body"])
        s.configure("Treeview.Heading", font=f["small"], background=T.PAPER,
                    foreground=T.INK2, relief="flat")
        s.map("Treeview", background=[("selected", T.SELECT)],
              foreground=[("selected", T.INK)])
        s.configure("TEntry", fieldbackground="white", padding=4)
        s.configure("TCombobox", fieldbackground="white", padding=3)
        s.configure("Field.TCombobox", fieldbackground="white",
                    background="white", padding=3)
        s.map("Field.TCombobox", fieldbackground=[("readonly", "white")],
              foreground=[("readonly", T.INK)])
        s.configure("TCheckbutton", background=T.PANEL)
        s.configure("Horizontal.TProgressbar", background=T.BLUE,
                    troughcolor=T.PANEL, bordercolor=T.RULE)

    # --------------------------------------------------------- header
    def _header(self):
        h = self.header = tk.Frame(self, bg=T.SHELL, height=48)
        h.pack(fill="x", side="top"); h.pack_propagate(False)
        tk.Label(h, text="Nemo", bg=T.SHELL, fg=T.BRASS,
                 font=self.fonts["brand"]).pack(side="left", padx=(16, 12))
        self.head_project = tk.Label(h, text="", bg=T.SHELL, fg=T.SHELL_INK,
                                     font=self.fonts["body"])
        self.head_project.pack(side="left")

        right = tk.Frame(h, bg=T.SHELL); right.pack(side="right", padx=12)
        tk.Button(right, text="Check this machine", command=self.open_doctor,
                  bg=T.SHELL_2, fg=T.SHELL_INK, activebackground=T.ACTION,
                  activeforeground="white", relief="flat", padx=10, pady=3,
                  font=self.fonts["small"], cursor="hand2").pack(side="right")
        # The Linguist says when a long job ends (owner, 2026-10-21); this
        # switch is kept in gui.json, not in config.yaml.
        self.voice_on = tk.BooleanVar(value=C.load_settings().get("voice", True))
        from .. import voice as _voice
        _voice.set_rate(C.load_settings().get("voice_rate", _voice.DEFAULT_RATE))
        # Audio cues (owner, 2026-10-23; nemo/cues.py), their own switch.
        self.sounds_on = tk.BooleanVar(value=C.load_settings().get("sounds", True))
        # The Technician loads the next step's model ahead (nemo/technician.py).
        self.load_ahead = tk.BooleanVar(value=C.load_settings().get("load_ahead", True))
        tk.Checkbutton(right, text="Load ahead", variable=self.load_ahead,
                       command=self._ahead_switched,
                       bg=T.SHELL, fg=T.SHELL_INK, selectcolor=T.SHELL_2,
                       activebackground=T.SHELL, activeforeground="white",
                       font=self.fonts["small"]).pack(side="right", padx=(0, 10))
        tk.Checkbutton(right, text="Sounds", variable=self.sounds_on, command=self._sounds_switched,
                       bg=T.SHELL, fg=T.SHELL_INK, selectcolor=T.SHELL_2,
                       activebackground=T.SHELL, activeforeground="white",
                       font=self.fonts["small"]).pack(side="right", padx=(0, 10))
        # The voice's speed: each press a step faster, round to the slowest.
        self.speed_button = tk.Button(right, text=self._speed_text(),
                                      command=self.change_voice_speed,
                                      bg=T.SHELL_2, fg=T.SHELL_INK, relief="flat", padx=8, pady=1,
                                      font=self.fonts["small"], cursor="hand2")
        self.speed_button.pack(side="right", padx=(0, 10))
        tk.Checkbutton(right, text="Voice", variable=self.voice_on, command=self._voice_switched,
                       bg=T.SHELL, fg=T.SHELL_INK, selectcolor=T.SHELL_2,
                       activebackground=T.SHELL, activeforeground="white",
                       font=self.fonts["small"]).pack(side="right", padx=(0, 4))
        # Text size (2026-11-08): this button or Ctrl + / Ctrl - / Ctrl 0.
        self.text_button = tk.Button(right, text=f"Text {self.text_percent}%",
                                     command=lambda: self.change_text_size(+1, wrap=True),
                                     bg=T.SHELL, fg=T.SHELL_INK, activebackground=T.SHELL_2,
                                     activeforeground="white", relief="flat", padx=8,
                                     font=self.fonts["small"], cursor="hand2")
        self.text_button.pack(side="right", padx=(0, 10))
        for seq, step in (("<Control-plus>", +1), ("<Control-equal>", +1),
                          ("<Control-KP_Add>", +1), ("<Control-minus>", -1),
                          ("<Control-KP_Subtract>", -1), ("<Control-Key-0>", 0)):
            self.bind_all(seq, lambda e, s=step: (self.change_text_size(s), "break")[1])
        # Keyboard only (2026-11-08): Enter presses the button that has the
        # keyboard, as Space already did. "break": a dialog's own Enter (its
        # OK) is not pressed as well when the keyboard is on Cancel.
        for cls in ("TButton", "Button", "TCheckbutton", "Checkbutton"):
            for key in ("<Return>", "<KP_Enter>"):
                self.bind_class(cls, key, _press_focused, add="+")
        self.meter = tk.Canvas(right, width=190, height=34, bg=T.SHELL,
                               highlightthickness=0)
        self.meter.pack(side="right", padx=(14, 14))
        self.mode_box = ttk.Combobox(right, state="readonly", width=30,
                                     values=[m[1] for m in C.MODES])
        self.mode_box.pack(side="right")
        self.mode_box.bind("<<ComboboxSelected>>", self._mode_chosen)
        tk.Label(right, text="Model", bg=T.SHELL, fg=T.SHELL_INK,
                 font=self.fonts["small"]).pack(side="right", padx=(0, 6))

    def _statusbar(self):
        self.status = tk.Label(self, text="", anchor="w", bg=T.PAPER,
                               fg=T.INK2, font=self.fonts["small"], padx=12)
        self.status.pack(side="bottom", fill="x", pady=(0, 3))

    def say(self, text, colour=None):
        self.status.config(text=text, fg=colour or T.INK2)

    def announce(self, text, colour=None, cue=None):
        """Say it in the status line, with a cue (Sounds on) and, with Voice
        on, aloud (the Linguist)."""
        self.say(text, colour)
        from .. import cues
        if cue is None:                    # a job's end: by its colour, else done
            cue = cues.for_colour(colour, T) if colour is not None else "done"
        if cue:
            self.cue(cue)
        if self.voice_on.get():
            from .. import voice
            voice.speak(text)

    def _ahead_switched(self):
        settings = C.load_settings()
        settings["load_ahead"] = bool(self.load_ahead.get())
        C.save_settings(settings)

    def load_next_model(self):
        """The Technician: after a step passes, load what the next one needs."""
        if not (self.project and self.load_ahead.get()) or (self.job and self.job.running):
            return None
        from .. import technician
        p = technician.plan(self.cfg, self.project)
        if p.mode is None:
            return None
        label = next(lab for k, lab, _ in C.MODES if k == p.mode)
        self.mode_box.set(label)
        self.start_job(C.nemo_argv("mode", p.mode), "ahead")
        self.say(f"Technician: {p.why}.", T.BLUE)
        return p

    def cue(self, name: str) -> bool:
        """An audio cue, if Sounds is on (nemo/cues.py)."""
        if not getattr(self, "sounds_on", None) or not self.sounds_on.get():
            return False
        from .. import cues
        return cues.play(name)

    def tool_columns(self) -> tuple[int, int]:
        """(columns, sidebar width) for the department buttons at this text
        size: two, as drawn for 768-pixel screens; three from 150 %, where two
        left the project list no room (2026-11-08), if every name fits."""
        width = T.scaled(272, self.text_percent)
        if self.text_percent < 150 or not getattr(self, "_tool_buttons", None):
            return 2, width
        # "Narrow.TButton": 4 pixels each side, against TButton's 12.
        need = max(self.fonts["body"].measure(b.cget("text")) for b in self._tool_buttons) + 14
        room = int(self.winfo_screenwidth() * 0.45)          # the rest for the work
        return (3, max(width, 3 * need + 8)) if 3 * need + 8 <= room else (2, width)

    def _lay_out_tools(self):
        cols, width = self.tool_columns()
        for c in range(3):
            self._tools.columnconfigure(c, weight=1 if c < cols else 0,
                                        uniform="tools" if c < cols else "")
        for i, b in enumerate(self._tool_buttons):
            b.configure(style="Narrow.TButton" if cols == 3 else "TButton")
            c = i % cols
            b.grid(row=i // cols, column=c, sticky="ew", pady=2,
                   padx=(0 if c == 0 else 2, 0 if c == cols - 1 else 2))
        if getattr(self, "_side", None):
            self._side.configure(width=width)

    def change_text_size(self, step: int, wrap: bool = False) -> int:
        """One size larger (+1), smaller (-1), or back to Nemo's own (0), in
        TEXT_SIZES; the header's button (wrap) goes from the largest to 100."""
        sizes = T.TEXT_SIZES
        at = sizes.index(self.text_percent)
        if step == 0 or (wrap and step > 0 and at == len(sizes) - 1):
            new = 100
        else:
            new = sizes[max(0, min(len(sizes) - 1, at + step))]
        self.text_percent = T.set_text_size(self.fonts, new)
        try:
            ttk.Style(self).configure("Treeview", rowheight=T.scaled(24, self.text_percent))
        except tk.TclError:
            pass
        if getattr(self, "text_button", None):
            self.text_button.config(text=f"Text {self.text_percent}%")
        if getattr(self, "_tool_buttons", None):
            self._lay_out_tools()
        settings = C.load_settings()
        settings["text_size"] = self.text_percent
        C.save_settings(settings)
        return self.text_percent

    def _sounds_switched(self):
        settings = C.load_settings()
        settings["sounds"] = bool(self.sounds_on.get())
        C.save_settings(settings)

    @staticmethod
    def _speed_text() -> str:
        from .. import voice
        r = voice.rate()
        return "Speed " + ("normal" if r == 0 else f"{r:+d}")

    def change_voice_speed(self, step: int | None = None):
        """The next speed (or `step`), kept in gui.json, and said at that speed."""
        from .. import voice
        steps = voice.RATE_STEPS
        nxt = step if step is not None else steps[(steps.index(voice.rate()) + 1) % len(steps)]
        voice.set_rate(nxt)
        settings = C.load_settings()
        settings["voice_rate"] = voice.rate()
        C.save_settings(settings)
        self.speed_button.config(text=self._speed_text())
        if self.voice_on.get():
            voice.speak("This is how fast I speak now.")

    def _voice_switched(self):
        settings = C.load_settings()
        settings["voice"] = bool(self.voice_on.get())
        C.save_settings(settings)
        if not self.voice_on.get():
            from .. import voice
            voice.stop()

    # ----------------------------------------------------------- body
    def _body(self):
        body = ttk.Frame(self); body.pack(fill="both", expand=True)
        self.body, self._embedded, self._stage = body, None, None
        self._stood_aside = False
        # Back (owner, 2026-11-11: "in each department method back to previous
        # menus"): how to reopen each screen left for another, newest last.
        self._back: list = []
        self._going_back = False
        side = ttk.Frame(body, width=T.scaled(272, self.text_percent))
        side.pack(side="left", fill="y", padx=(12, 0), pady=12)
        side.pack_propagate(False)
        self._side = side
        ttk.Label(side, text="Projects", style="H2.TLabel").pack(anchor="w")
        # The buttons are packed from the foot first, so that with larger
        # text the project list gives way, not the departments (2026-11-08:
        # at 150 % Print Shop to Help were pushed out of the window).
        tools = ttk.Frame(side); tools.pack(side="bottom", fill="x", pady=(10, 0))
        new = ttk.Button(side, text="New project", style="Primary.TButton",
                         command=self.new_project)
        new.pack(side="bottom", fill="x")
        self.proj_list = tk.Listbox(side, bg=T.PANEL, fg=T.INK, relief="flat",
                                    highlightthickness=1,
                                    highlightbackground=T.RULE,
                                    highlightcolor=T.BLUE,
                                    selectbackground=T.SELECT,
                                    selectforeground=T.INK,
                                    activestyle="none", font=self.fonts["body"],
                                    exportselection=False)
        self.proj_list.pack(fill="both", expand=True, pady=(8, 8))
        self.proj_list.bind("<<ListboxSelect>>", self._project_clicked)
        # Two columns, so all sixteen departments and the tools fit a
        # 768-pixel-high screen (owner, 2026-10-25: one column ran off it).
        self._tools, self._tool_buttons = tools, []
        from .. import storage
        stick = (("Save to stick", self.save_to_stick),) if storage.has_stick() else ()
        for i, (text, cmd) in enumerate((("Story", lambda: StoryList(self)),
                          ("Storeroom", lambda: VideoStore(self)),
                          ("Art Studio", lambda: ArtStudio(self)),
                          ("Theatre", lambda: Theatre(self)),
                          ("Gaming", lambda: Gaming(self)),
                          ("Music Room", lambda: MusicRoom(self)),
                          ("Audio", lambda: AudioRoom(self)),
                          ("Test Bench", lambda: TestBench(self)),
                          ("Print Shop", lambda: PrintShop(self)),
                          ("Film Studio", lambda: FilmStudio(self)),
                          ("Home", lambda: HomeRoom(self)),
                          ("Communications", lambda: CommsRoom(self)),
                          ("Science", lambda: ScienceRoom(self)),
                          ("Doctors", lambda: Clinic(self)),
                          *stick,
                          ("Researcher key", lambda: ResearcherKey(self)),
                          ("Work offline", lambda: OfflineDialog(self)),
                          ("Datasheets", lambda: DatasheetDialog(self)),
                          ("Help", lambda: HelpDialog(self)))):
            self._tool_buttons.append(ttk.Button(tools, text=text, command=cmd, width=1))
        self._lay_out_tools()

        self.main = ttk.Frame(body)
        self.main.pack(side="left", fill="both", expand=True, padx=12, pady=12)
        self.empty = ttk.Frame(self.main, style="Panel.TFrame")
        ttk.Label(self.empty, text="Start your first project",
                  style="Title.TLabel").pack(pady=(140, 6))
        ttk.Label(self.empty, style="PanelMuted.TLabel", justify="center",
                  text="Describe what you want to build. Nemo works out the "
                       "parts, schematic,\nwiring, enclosure and firmware, and "
                       "checks each one before moving on.").pack()
        ttk.Button(self.empty, text="New project", style="Primary.TButton",
                   command=self.new_project).pack(pady=18)

        self.tabs = ttk.Notebook(self.main)
        self.tab_brief = ttk.Frame(self.tabs, style="Panel.TFrame", padding=14)
        self.tab_steps = ttk.Frame(self.tabs, style="Panel.TFrame", padding=12)
        self.tab_files = ttk.Frame(self.tabs, style="Panel.TFrame", padding=14)
        self.tab_sign = ttk.Frame(self.tabs, style="Panel.TFrame", padding=14)
        self.tabs.add(self.tab_brief, text="Brief")
        self.tabs.add(self.tab_steps, text="Build")
        self.tabs.add(self.tab_files, text="Files")
        self.tabs.add(self.tab_sign, text="Sign-off")
        self._brief_tab(); self._steps_tab(); self._files_tab(); self._sign_tab()

    # ----------------------------------------------------- brief tab
    def _brief_tab(self):
        f = self.tab_brief
        f.columnconfigure(0, weight=1, minsize=600)
        f.columnconfigure(1, weight=0, minsize=380)
        form = ttk.Frame(f, style="Panel.TFrame")
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        form.columnconfigure(1, weight=1)
        self.fields = {}

        def row(r, label, widget):
            ttk.Label(form, text=label, style="Panel.TLabel").grid(
                row=r, column=0, sticky="nw", pady=5, padx=(0, 14))
            widget.grid(row=r, column=1, sticky="ew", pady=4)

        def text(h):
            return tk.Text(form, height=h, width=40, wrap="word",
                           relief="flat", font=self.fonts["body"],
                           highlightthickness=1, highlightbackground=T.RULE,
                           highlightcolor=T.BLUE, padx=6, pady=4, undo=True)

        def short(key, width, unit):
            # A short field with its unit right beside it, not in a far column.
            box = ttk.Frame(form, style="Panel.TFrame")
            self.fields[key] = ttk.Entry(box, width=width)
            self.fields[key].pack(side="left")
            ttk.Label(box, text=unit, style="PanelMuted.TLabel").pack(
                side="left", padx=(8, 0))
            return box

        self.fields["name"] = ttk.Entry(form)
        self.fields["function"] = text(3)
        self.fields["user"] = ttk.Entry(form)
        self._mcu_names = {p.name: p.ref for p in self.library
                           if p.category == "mcu"}
        self.fields["mcu"] = ttk.Combobox(form, state="readonly",
                                          values=list(self._mcu_names))
        self.fields["done_when"] = text(2)
        self.fields["constraints"] = text(3)

        row(0, "Name", self.fields["name"])
        row(1, "What it does", self.fields["function"])
        row(2, "Who uses it, and where", self.fields["user"])
        pbox = ttk.Frame(form, style="Panel.TFrame")
        pbox.columnconfigure(0, weight=1)
        self.fields["power"] = ttk.Entry(pbox)
        self.fields["power"].grid(row=0, column=0, sticky="ew")
        ttk.Button(pbox, text="Suggest power", command=self.suggest_power).grid(
            row=0, column=1, padx=(8, 0))
        self.no_power = tk.BooleanVar(value=False)
        ttk.Checkbutton(pbox, text="No power needed", variable=self.no_power,
                        command=self._ticks_changed).grid(row=0, column=2, padx=(8, 0))
        row(3, "Power source", pbox)
        row(4, "Supply rating", short("supply_ma", 8, "mA"))
        row(5, "Voltage rails", short("rails", 12, "volts, e.g. 5, 3.3"))
        row(6, "Inside size", short("envelope_mm", 16,
                                    "mm, length x width x height"))
        # A shaped object's own size (2026-11-05): no field for it, the window
        # could not give one, and Save brief dropped it.
        row(7, "Real size", short("shape_size_mm", 16,
                                  "mm, long x wide x high, of a shaped object; 0 = not known"))
        # Its own figures for its kind (nemo/anatomy.py), e.g. a gun's barrel:
        # the brief asked for them and the window had nowhere to put them.
        self.fields["shape_facts"] = ttk.Entry(form)
        row(8, "Its own figures", self.fields["shape_facts"])
        row(9, "Microcontroller", self.fields["mcu"])
        row(10, "It works when", self.fields["done_when"])
        row(11, "Constraints", self.fields["constraints"])
        ttk.Label(form, text="one per line", style="PanelMuted.TLabel").grid(
            row=12, column=1, sticky="w")

        self.questions = ttk.Label(form, text="", style="Panel.TLabel",
                                   foreground=T.SKIP, wraplength=560,
                                   justify="left")
        # D162: things that draw current and are not in the parts library.
        self.fields["extra_loads"] = text(2)
        row(13, "Other loads", self.fields["extra_loads"])
        ttk.Label(form, text="not in the parts list: one per line, name then "
                  "peak mA, e.g. fan, 200", style="PanelMuted.TLabel").grid(
            row=14, column=1, sticky="w")
        self.questions.grid(row=15, column=0, columnspan=2, sticky="w",
                            pady=(8, 0))

        # ---- parts picker
        side = ttk.Frame(f, style="Panel.TFrame")
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        ttk.Label(side, text="Parts", style="PanelH2.TLabel").grid(
            row=0, column=0, sticky="w")
        self.no_parts = tk.BooleanVar(value=False)
        ttk.Checkbutton(side, text="No parts needed", variable=self.no_parts,
                        command=self._ticks_changed).grid(row=0, column=0, sticky="e")
        srch = ttk.Frame(side, style="Panel.TFrame")
        srch.grid(row=1, column=0, sticky="ew", pady=(6, 4))
        ttk.Label(srch, text="Search", style="PanelMuted.TLabel").pack(
            side="left", padx=(0, 8))
        self.part_search = ttk.Entry(srch)
        self.part_search.pack(side="left", fill="x", expand=True)
        self.part_search.insert(0, "")
        self.part_search.bind("<KeyRelease>", lambda e: self._fill_catalog())
        ttk.Button(srch, text="New part...",
                   command=self.new_part).pack(side="left", padx=(8, 0))
        lb = dict(bg="white", relief="flat", highlightthickness=1,
                  highlightbackground=T.RULE, highlightcolor=T.BLUE,
                  selectbackground=T.SELECT, selectforeground=T.INK,
                  activestyle="none", font=self.fonts["body"],
                  exportselection=False)
        self.catalog = tk.Listbox(side, height=8, width=44, **lb)
        self.catalog.grid(row=2, column=0, sticky="nsew")
        self.catalog.bind("<<ListboxSelect>>",
                          lambda e: self._show_part(self.catalog))
        self.catalog.bind("<Double-Button-1>", lambda e: self._add_part())
        btns = ttk.Frame(side, style="Panel.TFrame")
        btns.grid(row=3, column=0, sticky="w", pady=6)
        ttk.Button(btns, text="Add part", command=self._add_part).pack(side="left")
        ttk.Button(btns, text="Remove part",
                   command=self._remove_part).pack(side="left", padx=6)
        ttk.Label(side, text="In this project", style="PanelMuted.TLabel").grid(
            row=4, column=0, sticky="w")
        self.chosen = tk.Listbox(side, height=5, width=44, **lb)
        self.chosen.grid(row=5, column=0, sticky="nsew", pady=(2, 6))
        self.chosen.bind("<<ListboxSelect>>",
                         lambda e: self._show_part(self.chosen))
        self.part_note = ttk.Label(side, text="Select a part to see what to "
                                   "watch out for.", style="PanelMuted.TLabel",
                                   wraplength=370, justify="left")
        self.part_note.grid(row=6, column=0, sticky="nw")
        side.rowconfigure(2, weight=1)

        bar = ttk.Frame(f, style="Panel.TFrame")
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(bar, text="Save brief", style="Primary.TButton",
                   command=self.save_brief).pack(side="left")
        ttk.Button(bar, text="Draft it with Nemo",
                   command=self.draft_brief).pack(side="left", padx=8)
        self.brief_state = ttk.Label(bar, text="", style="Panel.TLabel")
        self.brief_state.pack(side="left", padx=10)
        f.rowconfigure(0, weight=1)
        self._fill_catalog()

    def _fill_catalog(self):
        q = self.part_search.get().strip().lower()
        self.catalog.delete(0, "end")
        self._catalog_refs = []
        for p in sorted(self.library, key=lambda p: (p.category, p.name)):
            if q and q not in p.name.lower() and q not in p.ref:
                continue
            self.catalog.insert("end", f"{p.name}  ({p.category})")
            self._catalog_refs.append(p.ref)

    def _chosen_refs(self):
        return list(getattr(self, "_chosen", []))

    def _set_chosen(self, refs):
        self._chosen = list(dict.fromkeys(refs))
        self.chosen.delete(0, "end")
        for r in self._chosen:
            p = self.library.get(r)
            self.chosen.insert("end", p.name if p else f"{r} (not in library)")

    def _add_part(self):
        sel = self.catalog.curselection()
        if sel:
            self._set_chosen(self._chosen_refs() + [self._catalog_refs[sel[0]]])

    def _remove_part(self):
        sel = self.chosen.curselection()
        if sel:
            refs = self._chosen_refs(); refs.pop(sel[0]); self._set_chosen(refs)

    def brand(self, win):
        """Nemo's cog on a window's title bar (and its taskbar button):
        the defaults set on the main window did not reach windows opened
        while it is hidden, as the home window is (2026-10-29)."""
        try:
            if sys.platform.startswith("win") and C.logo_ico().is_file():
                win.wm_iconbitmap(str(C.logo_ico()))
            if self._icons:
                win.iconphoto(False, *self._icons)
        except tk.TclError:
            pass

    # ------------------------------------------------- one window
    # Departments open INSIDE Nemo's window, not as windows of their own
    # (owner, 2026-10-25). A department window is made as before, then shown
    # without a frame of its own, laid exactly over the space the Workshop's
    # body fills, and kept there as Nemo's window moves, resizes or is
    # minimised. (Taking it out of the window manager, `wm forget`, drew it in
    # the wrong place on Windows.) Home and Workshop on the bar above bring
    # those back. NEMO_ONE_WINDOW=off keeps separate windows.
    def one_window(self) -> bool:
        return os.environ.get("NEMO_ONE_WINDOW") != "off"

    def embed_later(self, win):
        if not self.one_window():
            return
        win.withdraw()                     # not seen as a window of its own, even briefly
        self.after_idle(lambda: self.embed(win))

    def embed(self, win):
        if not win.winfo_exists():
            return
        if self._embedded is not None and self._embedded is not win and self._embedded.winfo_exists():
            again = None if self._going_back else self._reopener(self._embedded)
            if again is not None:
                self._back.append(again)
            self._embedded.destroy()
        self._going_back = False
        if self._stage is None:
            self._stage = tk.Frame(self, bg=T.SHELL)
            self._back_button = tk.Button(
                self._stage, text="\u2190 Back", command=self.go_back, bg=T.BRASS, fg=T.INK,
                relief="flat", padx=12, pady=3, cursor="hand2", font=self.fonts["small"])
            self._back_button.pack(side="left", padx=(12, 6), pady=4)
            tk.Button(self._stage, text="Home", command=self.go_home, bg=T.SHELL_2,
                      fg=T.SHELL_INK, relief="flat", padx=10, pady=3, cursor="hand2",
                      font=self.fonts["small"]).pack(side="left", padx=(0, 6), pady=4)
            tk.Button(self._stage, text="Workshop", command=self.back_to_workshop, bg=T.SHELL_2,
                      fg=T.SHELL_INK, relief="flat", padx=10, pady=3, cursor="hand2",
                      font=self.fonts["small"]).pack(side="left", pady=4)
            self._stage_label = tk.Label(self._stage, bg=T.SHELL, fg=T.SHELL_INK,
                                         font=self.fonts["body"])
            self._stage_label.pack(side="left", padx=14)
            # Each department's own box (owner, 2026-11-09): what it is asked is
            # done here, never sent back to the home screen (nemo/asks.py).
            from .askbar import AskBar
            self.ask_bar = AskBar(self)
            self._slot = tk.Frame(self, bg=T.PAPER)          # the space a department covers
            self.bind("<Configure>", lambda e: self._place_embedded(), add="+")
            self.bind("<Unmap>", lambda e: self._embedded and self._embedded.winfo_exists()
                      and self._embedded.wm_withdraw(), add="+")
            self.bind("<Map>", lambda e: self._place_embedded(), add="+")
        self._stage_label.config(text=win.wm_title())
        # Its title goes on the bar; its own geometry calls no longer move it.
        win.title = lambda text=None: self._stage_label.config(text=text) if text else \
            self._stage_label.cget("text")
        win.geometry = lambda *a, **k: ""
        win.wm_overrideredirect(True)
        self.body.pack_forget()
        # In a department only its people are in view (owner, 2026-11-04: "hide
        # background windows when user enters department"): Nemo's header and
        # status line go, and so do the home windows; back on leaving it.
        self.header.pack_forget()
        self.status.pack_forget()
        self._hide_home_windows(win)
        self._stage.pack(fill="x")
        if self.ask_bar.show_for(department_of(win)):
            self.ask_bar.pack(fill="x")
        else:
            self.ask_bar.pack_forget()
        self._slot.pack(fill="both", expand=True)
        self._embedded = win
        win.bind("<Destroy>", lambda e: self._unembed(win) if e.widget is win else None, add="+")
        if self.state() == "withdrawn":
            self.deiconify()
        self.lift()
        self._place_embedded()

    def _place_embedded(self):
        win = self._embedded
        if win is None or not win.winfo_exists() or self.state() in ("withdrawn", "iconic"):
            return
        if self._stood_aside:
            return                         # a dialog is up: see stand_aside
        self.update_idletasks()
        s = self._slot
        win.wm_geometry(f"{s.winfo_width()}x{s.winfo_height()}+{s.winfo_rootx()}+{s.winfo_rooty()}")
        win.wm_deiconify()
        win.lift()

    def stand_aside(self):
        """D205. On Linux an embedded department is an overrideredirect
        window, which the window manager does not stack: a dialog could open
        under it holding Nemo's grab, so nothing answered and nothing could
        be clicked (the Nurse's question, on a booted stick, 2026-10-31).
        So the department steps out of the way until come_back. Windows
        stacks them correctly and is left alone."""
        win = self._embedded
        if self._stood_aside or win is None or not win.winfo_exists() \
                or self.tk.call("tk", "windowingsystem") != "x11":
            return False
        self._stood_aside = True
        win.wm_withdraw()
        return True

    def come_back(self):
        if self._stood_aside:
            self._stood_aside = False
            self._place_embedded()

    def _unembed(self, win):
        if self._embedded is not win:
            return
        self._embedded = None
        try:
            self._stage.pack_forget()
            self.ask_bar.pack_forget()
            self._slot.pack_forget()
            # Back in the order they were first packed: header, status line, body.
            self.header.pack(fill="x", side="top")
            self.status.pack(side="bottom", fill="x", pady=(0, 3))
            self.body.pack(fill="both", expand=True)
        except tk.TclError:
            pass                           # the app itself is closing

    def project_issues(self) -> dict:
        """{employee key: its issues} for the open project (nemo/issues.py);
        {} with no project, or where they cannot be read."""
        if not self.project:
            return {}
        from .. import issues
        try:
            return issues.for_project(self.project.root, self.project.load_brief(), self.library,
                                      float(self.cfg.get("hardware.min_wall_mm", 1.2)))
        except Exception:                                    # noqa: BLE001
            return {}

    def _hide_home_windows(self, keep=None):
        """Nemo Mode and the prompt window step out of sight while a
        department is open; Home brings its own back."""
        from .nemomode import NemoMode
        from .prompt import PromptWindow
        for w in self.winfo_children():
            if w is not keep and isinstance(w, (NemoMode, PromptWindow)) and w.winfo_exists():
                try:
                    w.withdraw()
                except tk.TclError:
                    pass

    def _reopener(self, win):
        """How to open again a department's room or window being left, or None."""
        if type(win).__name__ == "IllustratedRoom":
            return lambda key=win.key: IllustratedRoom(self, key)
        cls = type(win)
        if cls.__name__ in WINDOW_OF.values():
            return lambda: cls(self)
        return None

    def go_back(self):
        """The screen before this one: the department's room from its own
        window, the room or window before that, and Home when there is none."""
        while self._back:
            again = self._back.pop()
            self._going_back = True
            try:
                return again()
            except Exception:                        # noqa: BLE001  that one cannot open: the one before
                self._going_back = False
        return self.go_home()

    def back_to_workshop(self):
        self._back.clear()
        if self._embedded is not None and self._embedded.winfo_exists():
            self._embedded.destroy()

    def go_home(self):
        """The home screen: Nemo Mode, the departments' full-screen shelf
        (owner, 2026-11-04, after Bazzite's Gaming Mode), the Workshop
        behind it. gui.json "home": "prompt" keeps the cog and the prompt."""
        self.back_to_workshop()
        if C.load_settings().get("home", "nemo_mode") != "prompt":
            from .nemomode import NemoMode, find
            self.withdraw()
            mode = find(self)
            if mode is not None:
                mode.come_back()
                return mode
            return NemoMode(self)
        from .prompt import PromptWindow
        self.withdraw()
        for w in self.winfo_children():
            if isinstance(w, PromptWindow) and w.winfo_exists():
                w.deiconify(); w.lift()
                return w
        return PromptWindow(self)

    def open_department(self, key: str):
        """Open a department's own window, as its side-panel button does (the
        prompt window's Go there). The Workshop and the Computer Lab are this
        main window; a department not in the table opens nothing."""
        self.cue("open")
        return IllustratedRoom(self, key)

    def real_window(self, key: str):
        """The department's own working window, opened from its pixel room."""
        window = {k: globals()[name] for k, name in WINDOW_OF.items()}.get(key)
        if window is None:                         # the Workshop and the Computer Lab: this window
            self.deiconify(); self.lift()
            return None
        return window(self)

    def save_to_stick(self):
        from .. import storage
        ok, msg = storage.save_now()
        self.say(("Saved: " if ok else "Not saved: ") + msg, T.PASS if ok else T.FAIL)

    def new_part(self):
        NewPartDialog(self)

    def part_added(self, ref: str, add_to_project: bool):
        """Called by NewPartDialog once a part has actually been saved."""
        self.library = C.parts_catalog(self.cfg)   # reload with the addition
        self._fill_catalog()
        if add_to_project:
            self._set_chosen(self._chosen_refs() + [ref])
        self.say(f"Added '{ref}' to your parts library.", T.PASS)

    def _show_part(self, box):
        sel = box.curselection()
        if not sel:
            return
        ref = (self._catalog_refs if box is self.catalog
               else self._chosen_refs())[sel[0]]
        p = self.library.get(ref)
        if not p:
            return
        bits = [p.name]
        if p.supply_v:
            bits.append(f"Supply {'/'.join(str(v) for v in p.supply_v)} V, "
                        f"logic {p.logic_v} V, peak {p.draw_ma:.0f} mA.")
        if p.notes:
            bits.append(" ".join(p.notes.split()))
        self.part_note.config(text="\n".join(bits))

    def _get(self, key):
        w = self.fields[key]
        return (w.get("1.0", "end").strip() if isinstance(w, tk.Text)
                else w.get().strip())

    def _put(self, key, value):
        w = self.fields[key]
        if isinstance(w, tk.Text):
            w.delete("1.0", "end"); w.insert("1.0", value or "")
        elif isinstance(w, ttk.Combobox):
            w.set(value or "")
        else:
            w.delete(0, "end"); w.insert(0, value or "")

    def _fill_brief(self, b):
        self._put("name", b.name)
        self._put("function", b.function)
        self._put("user", b.user)
        self._put("power", b.power)
        self._put("supply_ma", f"{b.supply_ma:g}" if b.supply_ma else "")
        self._put("rails", ", ".join(f"{r:g}" for r in b.rails))
        self._put("envelope_mm", " x ".join(f"{v:g}" for v in b.envelope_mm))
        self._put("shape_size_mm", " x ".join(f"{v:g}" for v in (b.shape_size_mm or [])))
        self._put("shape_facts", C.format_facts(b.shape_facts))
        ref_to_name = {v: k for k, v in self._mcu_names.items()}
        self.fields["mcu"].set(ref_to_name.get(b.mcu, b.mcu))
        self._put("done_when", b.done_when)
        self._put("constraints", "\n".join(b.constraints))
        self._put("extra_loads", C.format_extra_loads(b.extra_loads))
        self._set_chosen(b.parts)
        self.no_power.set(bool(b.no_power))
        self.no_parts.set(bool(b.no_parts))
        self._apply_ticks()
        q = b.open_questions
        self.questions.config(text=("Open questions:\n  " + "\n  ".join(q))
                              if q else "")
        self._brief_status(b)

    def _form_brief(self):
        from ..project import Brief
        nums = C.parse_numbers
        parts = self._chosen_refs()
        mcu = self._mcu_names.get(self._get("mcu"), self._get("mcu"))
        if self.no_parts.get():
            parts, mcu = [], ""                  # D189: the tick rules
        if mcu and mcu not in parts:
            parts = [mcu] + parts
        supply = nums(self._get("supply_ma"))
        return Brief(
            name=self._get("name") or (self.project.root.name if self.project else ""),
            function=self._get("function"), user=self._get("user"),
            power=self._get("power"), supply_ma=supply[0] if supply else 0.0,
            rails=nums(self._get("rails")) or [5.0, 3.3],
            envelope_mm=nums(self._get("envelope_mm"))[:3], parts=parts,
            mcu=mcu, done_when=self._get("done_when"),
            constraints=[c.strip() for c in self._get("constraints").splitlines()
                         if c.strip()],
            open_questions=list(self.loaded_brief.open_questions
                                if self.loaded_brief else []),
            extra_loads=C.parse_extra_loads(self._get("extra_loads")),
            # Not on the form, so kept from the saved brief: saving here
            # dropped them, and a Reviewer stop the owner had accepted came
            # back on the next Save brief.
            accepted=list(self.loaded_brief.accepted if self.loaded_brief else []),
            no_power=bool(self.no_power.get()), no_parts=bool(self.no_parts.get()),
            shape_size_mm=nums(self._get("shape_size_mm"))[:3],
            shape_facts=C.parse_facts(self._get("shape_facts")))

    def _ticks_changed(self):
        """D189: a tick is the owner's answer and the form follows it. With
        No parts needed, the parts and the board are cleared (after asking,
        if there are any) and the picker is greyed; with No power needed,
        the power source and supply rating are. On the AH531 the board left
        in the Microcontroller box went back into the parts at every Save,
        so No parts needed could never hold."""
        if self.no_parts.get() and (self._chosen_refs() or self._get("mcu")):
            n = len(self._chosen_refs())
            if not messagebox.askyesno(
                    "No parts needed", f"Clear the {n} part(s) and the microcontroller "
                    "from this brief?", parent=self):
                self.no_parts.set(False)
            else:
                self._set_chosen([])
                self.fields["mcu"].set("")
        if self.no_power.get():
            self._put("power", "")
            self._put("supply_ma", "")
        self._apply_ticks()
        self._brief_status(self._form_brief())

    def _apply_ticks(self):
        """Grey out what the ticks say is not needed."""
        parts_state = "disabled" if self.no_parts.get() else "normal"
        for w in (self.fields["mcu"], self.chosen, getattr(self, "catalog", None)):
            if w is None:
                continue
            try:
                if w is self.fields["mcu"]:
                    w.config(state="disabled" if self.no_parts.get() else "readonly")
                else:
                    w.config(state=parts_state)
            except tk.TclError:
                pass
        power_state = "disabled" if self.no_power.get() else "normal"
        for name in ("power", "supply_ma"):
            try:
                self.fields[name].config(state=power_state)
            except (KeyError, tk.TclError):
                pass

    def _brief_status(self, b):
        missing = C.brief_problems(b)
        if missing:
            self.brief_state.config(foreground=T.SKIP,
                                    text="Still needed: " + ", ".join(missing))
        else:
            self.brief_state.config(foreground=T.PASS,
                                    text="Ready for the next step.")

    def brief_changed(self):
        if not self.project or not self.loaded_brief:
            return False
        from dataclasses import asdict
        return asdict(self._form_brief()) != asdict(self.loaded_brief)

    def save_brief(self, quiet=False):
        if not self.project:
            return
        b = self._form_brief()
        self.project.save_brief(b)
        self.project.commit("brief", "edited in the desktop interface")
        self.loaded_brief = b
        self._set_chosen(b.parts)
        self._brief_status(b)
        self.refresh_steps()
        if not quiet:
            self.say("Brief saved.", T.PASS)

    def suggest_power(self):
        if not self.project:
            return
        brief = self._form_brief()
        if not [r for r in brief.parts if self.library.get(r)]:
            messagebox.showinfo("Suggest power", "Add the parts first. Power "
                                "suggestions are worked out from what they "
                                "draw.", parent=self)
            return
        PowerDialog(self, brief)

    def use_power(self, brief):
        """Called by the power dialog with the chosen option applied."""
        self._put("power", brief.power)
        self._put("supply_ma", f"{brief.supply_ma:g}")
        self._put("rails", ", ".join(f"{r:g}" for r in brief.rails))
        self._set_chosen(brief.parts)
        self._brief_status(self._form_brief())
        self.say("Power updated. Save the brief to keep it.", T.BLUE)

    def draft_brief(self):
        if not self.project:
            return
        desc = self._get("function")
        if not desc:
            messagebox.showinfo("Draft it with Nemo", "Write a sentence or two "
                                "under 'What it does' first. Nemo drafts the "
                                "rest of the brief from it.", parent=self)
            return
        self.save_brief(quiet=True)
        self.start_job(C.nemo_argv("--project", self.project.root.name,
                                   "draft", desc, "--json"), "draft")

    # ----------------------------------------------------- build tab
    def _steps_tab(self):
        f = self.tab_steps
        f.columnconfigure(1, weight=1); f.rowconfigure(0, weight=1)
        self.traveller = Traveller(f, self.fonts, self._step_selected)
        self.traveller.grid(row=0, column=0, sticky="ns", padx=(0, 14))

        d = ttk.Frame(f, style="Panel.TFrame")
        d.grid(row=0, column=1, sticky="nsew")
        d.columnconfigure(0, weight=1); d.rowconfigure(5, weight=1)
        self.step_title = ttk.Label(d, text="", style="PanelH2.TLabel")
        self.step_title.grid(row=0, column=0, sticky="w")
        self.step_help = ttk.Label(d, text="", style="PanelMuted.TLabel")
        self.step_help.grid(row=1, column=0, sticky="w", pady=(2, 8))

        self.checks = ttk.Treeview(d, columns=("result", "check", "detail"),
                                   show="headings", height=5)
        for col, w, text in (("result", 90, "Result"), ("check", 200, "Check"),
                             ("detail", 400, "Detail")):
            self.checks.heading(col, text=text, anchor="w")
            self.checks.column(col, width=w, stretch=(col == "detail"),
                               anchor="w")
        for tag, col in (("PASS", T.PASS), ("FAIL", T.FAIL), ("SKIP", T.SKIP)):
            self.checks.tag_configure(tag, foreground=col)
        self.checks.grid(row=2, column=0, sticky="ew")
        self.checks.bind("<<TreeviewSelect>>", self._check_selected)

        # Shown only when the selected step has something to suggest.
        self.fix_box = ttk.Frame(d, style="Panel.TFrame")
        self.fix_box.columnconfigure(1, weight=1)
        ttk.Label(self.fix_box, text="Suggested fixes",
                  style="Panel.TLabel", font=self.fonts["strong"]).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(10, 4))
        self.fix_list = tk.Listbox(
            self.fix_box, height=3, width=34, bg="white", relief="flat",
            highlightthickness=1, highlightbackground=T.RULE,
            highlightcolor=T.BLUE, selectbackground=T.SELECT,
            selectforeground=T.INK, activestyle="none",
            font=self.fonts["body"], exportselection=False)
        self.fix_list.grid(row=1, column=0, sticky="nsw")
        self.fix_list.bind("<<ListboxSelect>>", lambda e: self._fix_selected())
        right = ttk.Frame(self.fix_box, style="Panel.TFrame")
        right.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        self.fix_why = ttk.Label(right, text="", style="Panel.TLabel",
                                 wraplength=440, justify="left")
        self.fix_why.pack(anchor="w")
        self.fix_changes = ttk.Label(right, text="", style="PanelMuted.TLabel",
                                     wraplength=440, justify="left")
        self.fix_changes.pack(anchor="w", pady=(4, 6))
        fb = ttk.Frame(right, style="Panel.TFrame"); fb.pack(anchor="w")
        self.btn_fix_run = ttk.Button(fb, text="Apply and run again",
                                      style="Primary.TButton",
                                      command=lambda: self.apply_fix(True))
        self.btn_fix_run.pack(side="left")
        self.btn_fix = ttk.Button(fb, text="Apply only",
                                  command=lambda: self.apply_fix(False))
        self.btn_fix.pack(side="left", padx=8)
        self._fixes = []

        def rewrap(e):
            for lab in (self.fix_why, self.fix_changes):
                lab.config(wraplength=max(200, e.width - 8))
        right.bind("<Configure>", rewrap)

        self.out_label = ttk.Label(d, text="", style="PanelMuted.TLabel")
        self.out_label.grid(row=4, column=0, sticky="w", pady=(10, 2))
        logf = ttk.Frame(d, style="Panel.TFrame")
        logf.grid(row=5, column=0, sticky="nsew")
        logf.columnconfigure(0, weight=1); logf.rowconfigure(0, weight=1)
        self.log = tk.Text(logf, height=8, wrap="word", relief="flat",
                           font=self.fonts["mono"], bg=T.PANEL, fg=T.INK,
                           highlightthickness=1, highlightbackground=T.RULE,
                           padx=8, pady=6, state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.config(yscrollcommand=sb.set)
        for tag, col in (("fail", T.FAIL), ("skip", T.SKIP), ("pass", T.PASS),
                         ("head", T.BLUE)):
            self.log.tag_configure(tag, foreground=col)

        bar = ttk.Frame(d, style="Panel.TFrame")
        bar.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self.btn_run = ttk.Button(bar, text="Run this step",
                                  style="Primary.TButton",
                                  command=lambda: self.run_step(only=True))
        self.btn_run.pack(side="left")
        self.btn_run_all = ttk.Button(bar, text="Run to the end",
                                      command=lambda: self.run_step(only=False))
        self.btn_run_all.pack(side="left", padx=8)
        self.btn_stop = ttk.Button(bar, text="Stop", command=self.stop_job,
                                   state="disabled")
        self.btn_stop.pack(side="left")
        ttk.Button(bar, text="Work log", command=lambda: WorkLog(self)).pack(side="left", padx=(8, 0))
        # Shown only on the Concept step: the Artist's two concepts, to choose from.
        self.btn_concept = ttk.Button(bar, text="Choose a concept...",
                                      command=self.open_concepts)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.elapsed = ttk.Label(bar, text="", style="PanelMuted.TLabel")
        self.elapsed.pack(side="right")

    def _step_selected(self, i):
        rows = self.traveller.rows
        if not rows:
            return
        r = rows[i]
        self.step_title.config(text=f"Step {r.number}: {r.name}")
        extra = ("  Uses the language model, which takes several minutes "
                 "per step on this laptop." if r.needs_model and r.stage != "brief"
                 else "")
        from ..staff import owner
        crew = (f"  The {owner(r.stage).label} does it; the Inspector checks it can "
                "start, first." if r.stage != "brief" else "")
        self.step_help.config(text=r.help + extra + crew)
        if not (self.job and self.job.running):
            self.btn_run.config(text="Open the brief" if r.stage == "brief"
                                else "Run this step")
        if r.stage == "concept":
            self.btn_concept.pack(side="left", padx=(8, 0))
        else:
            self.btn_concept.pack_forget()
        self.checks.delete(*self.checks.get_children())
        rec = r.record or {}
        self._check_items = {}
        for c in rec.get("checks", []):
            iid = self.checks.insert("", "end", tags=(c["status"],), values=(
                {"PASS": "Passed", "FAIL": "Failed", "SKIP": "Not checked"}
                .get(c["status"], c["status"]), C.check_name(c["name"]),
                c["detail"]))
            self._check_items[iid] = c
        if not rec.get("checks"):
            self.checks.insert("", "end", values=(
                "", "", "Not run yet." if r.status == "not run" else
                "This step produces files rather than checks."))
        if not (self.job and self.job.running):
            self._show_details(rec)
        self._refresh_fixes(r.stage)
        if rec.get("go_back_to"):
            self.checks.insert("", "end", tags=("FAIL",), values=(
                "Next", "", f"Fix this at the '{C.STEP_NAMES.get(rec['go_back_to'], rec['go_back_to'])}' "
                            "step, then run again from there."))

    def _show_details(self, rec):
        """Everything the checks found, in words, without having to click."""
        self._log_clear()
        self.out_label.config(text="What the checks found")
        any_ = False
        for c in rec.get("checks", []):
            items = [C.plain_item(i) for i in c.get("items", [])]
            if not items:
                continue
            any_ = True
            tag = {"FAIL": "fail", "SKIP": "skip"}.get(c["status"], "head")
            self._log(f"{C.check_name(c['name'])}: {c['detail']}", tag)
            for i in items:
                self._log("    " + i, "skip" if i.startswith(("Note", "Needs"))
                          else "fail" if i.startswith("Blocked") else "plain")
            self._log("", "plain")
        for n in rec.get("notes", []):
            any_ = True
            self._log(n, "plain")
        if self.project:
            from ..reviews import pending, reviews_for
            stage = rec.get("stage") or self.traveller.rows[self.traveller.selected].stage
            waiting = [p for p in pending()
                       if (p.get("context") or {}).get("project") == str(self.project.root)
                       and (p.get("context") or {}).get("stage") == stage]
            if waiting:
                any_ = True
                self._log("A second opinion on this step is waiting to be sent "
                          "when you are online (Work offline).", "skip")
            notes = reviews_for(self.project.root, stage)
            if notes:
                any_ = True
                self._log("Second opinion (advice only; nothing was changed):", "head")
                for line in notes[-1].read_text(encoding="utf-8", errors="replace").splitlines()[4:]:
                    self._log("    " + line, "plain")
        if not any_:
            self._log("Nothing further to report." if rec else
                      "Run this step to see what its checks find.", "plain")
        self.log.see("1.0")

    def _refresh_fixes(self, stage):
        self._fixes = (C.fixes_for(self.project, stage, self.library, self.cfg)
                       if self.project else [])
        self.fix_list.delete(0, "end")
        if not self._fixes:
            self.fix_box.grid_forget()
            return
        self.fix_box.grid(row=3, column=0, sticky="ew")
        for f in self._fixes:
            self.fix_list.insert("end", f.title if f.kind == "change"
                                 else f"{f.title} (advice)")
        self.fix_list.selection_set(0)
        self._fix_selected()

    def _fix_selected(self):
        sel = self.fix_list.curselection()
        if not sel:
            return
        f = self._fixes[sel[0]]
        self.fix_why.config(text=f.why)
        if f.kind == "change":
            ch = f.changes
            self.fix_changes.config(text=("Changes the brief: " + "; ".join(ch))
                                    if ch else "Changes nothing; runs the step again.")
            state = "normal" if not (self.job and self.job.running) else "disabled"
        elif getattr(f, "url", ""):
            self.fix_changes.config(text=f.url)
            self.btn_fix_run.config(state="disabled")
            self.btn_fix.config(text="Open the link", state="normal")
            return
        elif getattr(f, "brief_field", ""):
            # D175: advice whose remedy is a value in the brief opens the
            # brief at that field, rather than leaving both buttons grey.
            self.fix_changes.config(text="Only you can give this value.")
            self.btn_fix_run.config(state="disabled")
            self.btn_fix.config(text="Open the brief", state="normal")
            return
        else:
            self.fix_changes.config(text="Advice only. Nothing to apply "
                                         "automatically.")
            state = "disabled"
        self.btn_fix.config(text="Apply only")
        self.btn_fix_run.config(state=state); self.btn_fix.config(state=state)

    def apply_fix(self, run):
        sel = self.fix_list.curselection()
        if not sel or not self.project:
            return
        f = self._fixes[sel[0]]
        if getattr(f, "url", "") and f.kind != "change":
            import webbrowser
            webbrowser.open(f.url)
            return
        if getattr(f, "brief_field", "") and f.kind != "change":
            self.open_brief_at(f.brief_field)
            return
        if f.kind != "change":
            return
        if self.brief_changed():
            self.save_brief(quiet=True)
        C.apply_fix_to_project(self.project, f)
        self.loaded_brief = self.project.load_brief()
        self._fill_brief(self.loaded_brief)
        self.say(f"Applied: {f.title}.", T.PASS)
        if run:
            self.run_stage(f.rerun or self.traveller.rows[self.traveller.selected].stage)
        else:
            self.refresh_steps()

    def open_brief_at(self, field: str):
        """Show the Brief tab with the cursor in one of its fields."""
        self.tabs.select(self.tab_brief)
        w = self.fields.get(field)
        if w is not None:
            try:
                w.focus_set()
            except tk.TclError:
                pass
        label = {"supply_ma": "Supply rating", "envelope_mm": "Inside size",
                 "shape_size_mm": "Real size"}.get(field, field)
        self.say(f"Fill in '{label}', press Save brief, then run step 2 again.", T.BLUE)

    def run_stage(self, stage, only=True):
        if not self.project or stage == "brief":
            return
        for i, r in enumerate(self.traveller.rows):
            if r.stage == stage:
                self.traveller.selected = i
        self._log_clear()
        self.out_label.config(text="Live output")
        self.start_job(C.nemo_argv("--project", self.project.root.name, "run",
                                   "--only" if only else "--from", stage,
                                   "--json"), "run")

    def _check_selected(self, _):
        sel = self.checks.selection()
        c = self._check_items.get(sel[0]) if sel else None
        if c and c.get("items") and not (self.job and self.job.running):
            self._log_clear()
            self._log(f"{C.check_name(c['name'])}: {c['detail']}", "head")
            for item in c["items"]:
                self._log("    " + C.plain_item(item), "plain")

    def _log(self, line, tag=None):
        self.log.config(state="normal")
        if tag == "plain":
            tag = None
        elif tag is None:
            low = line.lower()
            tag = ("fail" if ("fail" in low or "error" in low) else
                   "skip" if "skip" in low else
                   "pass" if line.strip().startswith("PASS") else None)
        self.log.insert("end", line + "\n", tag or ())
        self.log.see("end")
        self.log.config(state="disabled")

    def _log_clear(self):
        self.log.config(state="normal"); self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def refresh_steps(self):
        if not self.project:
            return
        rows = C.step_rows(self.project)
        keep = self.traveller.selected
        self.traveller.set_rows(rows, self.running_stage)
        self.traveller.selected = min(keep, len(rows) - 1)
        self._step_selected(self.traveller.selected)

    def open_concepts(self):
        if not self.project:
            return
        try:
            drawn = C.concept_state(self.project, self.library)[0]
        except Exception as exc:                              # noqa: BLE001
            self.say(f"The concepts could not be read: {exc}", T.FAIL)
            return
        if not drawn:
            self.say("No concepts for these parts and this size yet: run the Concept step.",
                     T.SKIP)
            return
        ConceptDialog(self)

    def run_step(self, only: bool):
        if not self.project:
            return
        if self.brief_changed():
            self.save_brief(quiet=True)
        stage = self.traveller.rows[self.traveller.selected].stage
        if stage == "brief":
            self.tabs.select(self.tab_brief)
            self.say("The brief is written on the Brief tab, by you or with "
                     "'Draft it with Nemo'.")
            return
        flag = "--only" if only else "--from"
        self._log_clear()
        self.out_label.config(text="Live output")
        self.start_job(C.nemo_argv("--project", self.project.root.name, "run",
                                   flag, stage, "--json"), "run")

    # ----------------------------------------------------- files tab
    def _files_tab(self):
        f = self.tab_files
        f.columnconfigure(0, weight=1); f.rowconfigure(1, weight=1)
        ttk.Label(f, text="Everything this project has produced so far.",
                  style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w",
                                                  pady=(0, 8))
        self.files = ttk.Treeview(f, columns=("size", "changed"),
                                  show="tree headings")
        self.files.heading("#0", text="File", anchor="w")
        self.files.heading("size", text="Size", anchor="w")
        self.files.heading("changed", text="Changed", anchor="w")
        self.files.column("#0", width=420)
        self.files.column("size", width=90, stretch=False)
        self.files.column("changed", width=170, stretch=False)
        self.files.grid(row=1, column=0, sticky="nsew")
        self.files.bind("<Double-Button-1>", lambda e: self.open_file())
        bar = ttk.Frame(f, style="Panel.TFrame")
        bar.grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Button(bar, text="Open", style="Primary.TButton",
                   command=self.open_file).pack(side="left")
        ttk.Button(bar, text="Open project folder",
                   command=lambda: self.project and C.open_path(self.project.root)
                   ).pack(side="left", padx=8)
        ttk.Button(bar, text="View the housing",
                   command=self.view_housing).pack(side="left")
        self._file_paths = {}

    def refresh_files(self):
        self.files.delete(*self.files.get_children())
        self._file_paths = {}
        if not self.project:
            return
        groups = {}
        items = C.project_files(self.project)
        if not items:
            self.files.insert("", "end", text="Files appear here as each "
                              "step produces them.")
            return
        for group, path in items:
            if group not in groups:
                groups[group] = self.files.insert("", "end", text=group,
                                                  open=True)
            st = path.stat()
            size = (f"{st.st_size} B" if st.st_size < 2048
                    else f"{st.st_size / 1024:.0f} KB")
            iid = self.files.insert(groups[group], "end",
                                    text=str(path.relative_to(self.project.root)),
                                    values=(size, _when(int(st.st_mtime))))
            self._file_paths[iid] = path

    def view_housing(self):
        """Draw the real enclosure from its STL and show it.

        The drawing is a pure-Python loop over triangles: a detailed housing
        takes seconds natively and tens of seconds on the target, so it runs
        in a worker thread and the window stays alive. The worker touches no
        Tk object; the result is picked up here by polling.
        """
        if not self.project:
            self.say("Choose a project first.", T.SKIP)
            return
        if getattr(self, "_rendering", False):
            return
        import threading
        from ..render import RenderError, render_stl
        stl, out = self.project.housing_stl, self.project.root / "renders"
        env = self.project.load_brief().envelope_mm
        box: dict = {}

        def work():
            try:
                # 250 px views make a 500 px sheet, exactly the size the dialog shows, so
                # nothing is resampled (Tk's resampling left ragged edges).
                box["res"] = render_stl(stl, out, size=250, envelope_mm=env)
            except RenderError as exc:
                box["err"] = str(exc)
            except Exception as exc:                       # noqa: BLE001
                box["err"] = f"Could not draw it: {exc}"

        self._rendering = True
        self.say("Drawing the housing from its STL...", T.BLUE)
        th = threading.Thread(target=work, daemon=True)
        th.start()
        self._timers["housing"] = self.after(150, lambda: self._housing_done(th, box))

    def _housing_done(self, th, box):
        if not self.winfo_exists():
            return              # belt and braces: see destroy() for the actual fix
        if th.is_alive():
            self._timers["housing"] = self.after(200, lambda: self._housing_done(th, box))
            return
        self._timers.pop("housing", None)
        self._rendering = False
        if "err" in box:
            self.say(box["err"], T.FAIL)
            return
        self.say("Done.", T.PASS)
        self.refresh_files()
        RenderDialog(self, box["res"])

    def open_file(self):
        sel = self.files.selection()
        if sel and sel[0] in self._file_paths:
            try:
                C.open_path(self._file_paths[sel[0]])
            except OSError as exc:
                self.say(f"Could not open it: {exc}", T.FAIL)

    # --------------------------------------------------- sign-off tab
    def _sign_tab(self):
        f = self.tab_sign
        f.columnconfigure(0, weight=1)
        top = ttk.Frame(f, style="Panel.TFrame"); top.grid(row=0, column=0,
                                                           sticky="w")
        ttk.Label(top, text="Your name", style="Panel.TLabel").pack(side="left")
        self.signer = ttk.Entry(top, width=28)
        self.signer.pack(side="left", padx=10)
        self.signer.insert(0, self.settings.get("signer", ""))
        ttk.Label(f, style="PanelMuted.TLabel", wraplength=760, justify="left",
                  text="Nemo can't stop a print, an order or a battery being "
                       "connected. These are the record that a person looked "
                       "first. Each signature and withdrawal is written to the "
                       "tamper-evident audit log.").grid(
            row=1, column=0, sticky="w", pady=(8, 14))
        self.sign_box = ttk.Frame(f, style="Panel.TFrame")
        self.sign_box.grid(row=2, column=0, sticky="nw")

    def refresh_signoffs(self):
        for w in self.sign_box.winfo_children():
            w.destroy()
        if not self.project:
            return
        done = C.signoffs(self.project)
        for r, (key, text) in enumerate(C.signoff_items(self.project)):
            var = tk.BooleanVar(value=key in done)
            cb = ttk.Checkbutton(self.sign_box, text=text, variable=var,
                                 command=lambda k=key, v=var: self._sign(k, v))
            cb.grid(row=r*2, column=0, sticky="w", pady=(6, 0))
            rec = done.get(key)
            note = (f"Signed by {rec['by']}, {_when(rec['when'])}" if rec
                    else "Not signed")
            lab = ttk.Label(self.sign_box, text=note, style="PanelMuted.TLabel")
            if not rec:
                lab.configure(foreground=T.SKIP)
            lab.grid(row=r*2 + 1, column=0, sticky="w", padx=(24, 0))

    def _sign(self, key, var):
        try:
            C.set_signoff(self.project, key, self.signer.get(), var.get())
        except ValueError as exc:
            var.set(False)
            messagebox.showinfo("Sign-off", str(exc), parent=self)
            self.signer.focus_set()
            return
        self.settings["signer"] = self.signer.get().strip()
        C.save_settings(self.settings)
        self.refresh_signoffs()
        self.say("Signed." if var.get() else "Signature withdrawn.")

    # ------------------------------------------------------- projects
    def refresh_projects(self, select=None):
        names = C.list_projects(self.cfg)
        self.proj_list.delete(0, "end")
        for n in names:
            self.proj_list.insert("end", C.display_name(n, self.cfg))
        self._project_names = names
        if not names:
            self.tabs.pack_forget(); self.empty.pack(fill="both", expand=True)
            self.head_project.config(text="")
            return
        self.empty.pack_forget(); self.tabs.pack(fill="both", expand=True)
        idx = names.index(select) if select in names else 0
        self.proj_list.selection_clear(0, "end")
        self.proj_list.selection_set(idx)
        self.load_project(names[idx])

    def _project_clicked(self, _):
        sel = self.proj_list.curselection()
        if not sel:
            return
        name = self._project_names[sel[0]]
        if self.project and name == self.project.root.name:
            return
        if self.brief_changed() and messagebox.askyesno(
                "Unsaved brief", "Save your changes to this brief first?",
                parent=self):
            self.save_brief(quiet=True)
        self.load_project(name)

    def load_project(self, name):
        self.project = C.open_project(name, self.cfg)
        try:
            self.loaded_brief = self.project.load_brief()
        except (FileNotFoundError, TypeError) as exc:
            self.say(f"Could not read this project's brief: {exc}", T.FAIL)
            return
        self._fill_brief(self.loaded_brief)
        self.head_project.config(text=self.loaded_brief.name or name)
        self.traveller.selected = max(0, [r.stage for r in C.step_rows(
            self.project)].index(C.next_step(self.project) or "pack"))
        self.refresh_steps(); self.refresh_files(); self.refresh_signoffs()
        self.settings["last_project"] = name
        C.save_settings(self.settings)

    def new_project(self):
        NewProject(self)

    # ---------------------------------------------------------- modes
    def _mode_chosen(self, _):
        label = self.mode_box.get()
        key = next(k for k, lab, _ in C.MODES if lab == label)
        if self.job and self.job.running:
            self.say("Wait for the current step to finish first.", T.SKIP)
            self._tick_memory(once=True)
            return
        self.start_job(C.nemo_argv("mode", key), "mode")

    def _tick_memory(self, once=False):
        from ..modes import current
        from ..platform_probe import mem_available_mb, mem_total_mb
        total, free = mem_total_mb(), mem_available_mb()
        c = self.meter; c.delete("all")
        if total:
            used = max(0.0, min(1.0, 1 - free / total))
            c.create_rectangle(0, 6, 190, 14, fill=T.SHELL_2, outline="")
            c.create_rectangle(0, 6, 190 * used, 14, outline="",
                               fill=T.FAIL if free < 1200 else
                               T.SKIP if free < 2500 else T.BRASS)
            c.create_text(0, 26, anchor="w", fill=T.SHELL_INK,
                          font=self.fonts["small"],
                          text=f"{free / 1024:.1f} of {total / 1024:.1f} GB free")
        if not (self.job and self.job.running and self.job_kind in ("mode", "ahead")):
            st = current()
            key = st.name if st.running else "off"
            self.mode_box.set(next(lab for k, lab, _ in C.MODES if k == key))
        if not once:
            self._timers["mem"] = self.after(3000, self._tick_memory)

    # ------------------------------------------------------------ jobs
    def start_job(self, argv, kind):
        if self.job and self.job.running:
            self.say("Something is already running.", T.SKIP)
            return
        self.job_kind = kind
        self.job = Job(argv).start()
        self.btn_stop.config(state="normal")
        self.btn_run.config(state="disabled")
        self.btn_run_all.config(state="disabled")
        self.progress.pack(side="right", padx=8); self.progress.start(12)
        self.say({"run": "Running.", "draft": "Nemo is drafting the brief.",
                  "mode": "Loading the model.", "ahead": "The Technician is loading the next model.",
                  "eval": "The Quality Inspector is asking both models the task file's questions.",
                  "story": "The employees are writing the story. Each chapter takes "
                           "a few minutes.",
                  "cover": "The Artist is painting the cover. On this laptop that "
                           "takes many minutes; Stop ends it."}.get(kind, "Working."), T.BLUE)
        if kind in ("run", "draft"):
            self.tabs.select(self.tab_steps)

    def stop_job(self):
        if self.job:
            self.job.stop()

    def _tick_job(self):
        job = self.job
        if job:
            for line in job.drain():
                ev = C.parse_event(line)
                if ev:
                    self._event(ev)
                else:
                    self._log(line)
            if job.running:
                m, s = divmod(int(job.elapsed), 60)
                self.elapsed.config(text=f"Running for {m}:{s:02d}")
            else:
                # D174: cleared BEFORE, not after. Finishing a run that
                # needs the model starts the mode job from in there; cleared
                # afterwards, that new job was thrown away here, never
                # polled, and the window stayed on "Loading the model." with
                # Run greyed out and a Stop that had nothing to stop.
                self.job = None
                self._job_finished(job)
        self._timers["job"] = self.after(150, self._tick_job)

    def destroy(self):
        # Cancel every tracked repeating/rescheduling timer first (memory and
        # job polling, and any slow background task like a housing render):
        # left pending, Tk prints "invalid command name ..." for each one
        # once it fires against a widget that no longer has that command.
        for k, tid in list(getattr(self, "_timers", {}).items()):
            try:
                self.after_cancel(tid)
            except Exception:                            # noqa: BLE001
                pass
        super().destroy()

    def _event(self, ev):
        if ev.get("state") == "running":
            self.running_stage = ev.get("stage")
            self.refresh_steps()
        elif ev.get("state") == "done":
            self.running_stage = None
            self.refresh_steps()
        elif ev.get("state") == "needs_model":
            self.pending_after_job = ("needs_model", ev.get("stage"),
                                      ev.get("mode"))

    def _job_finished(self, job):
        self.progress.stop(); self.progress.pack_forget()
        self.btn_stop.config(state="disabled")
        self.btn_run.config(state="normal"); self.btn_run_all.config(state="normal")
        self.elapsed.config(text="")
        self.running_stage = None
        kind, rc = self.job_kind, job.returncode
        if self.project:
            if kind == "draft":
                self.loaded_brief = self.project.load_brief()
                self._fill_brief(self.loaded_brief)
            self.refresh_steps(); self.refresh_files(); self.refresh_signoffs()
        self._tick_memory(once=True)

        if job.stopped:
            self.say("Stopped.", T.SKIP); return
        pending, self.pending_after_job = self.pending_after_job, None
        if pending and pending[0] == "needs_model":
            _, stage, mode = pending
            label = next(lab for k, lab, _ in C.MODES if k == mode)
            if messagebox.askyesno(
                    "Load the model?",
                    f"The {C.STEP_NAMES.get(stage, stage)} step needs the "
                    f"language model.\n\nLoad {label} now?", parent=self):
                self.mode_box.set(label)
                self.start_job(C.nemo_argv("mode", mode), "mode")
            else:
                self.say("Not run: no model loaded.", T.SKIP)
            return
        if kind == "ahead":
            if rc == 0:
                self.say("Technician: the next step's model is loaded.", T.PASS)
            else:
                self.say("Technician: the next step's model did not load ahead; "
                         "it will load when you run the step.", T.SKIP)
            return
        if kind == "mode":
            if rc == 0:
                self.announce("Model loaded." if self.mode_box.get() != "Off"
                              else "Model unloaded; memory freed.", T.PASS)
            else:
                tail = self.log.get("1.0", "end").strip().splitlines()[-3:]
                messagebox.showwarning("Could not load the model",
                                       "\n".join(tail) or "No reason given.",
                                       parent=self)
                self.announce("The model did not load.", T.FAIL)
            return
        if kind == "run" and self.project and C.concept_waiting(self.project, self.library):
            # The Artist has drawn; the owner chooses before the Designer goes on.
            self.announce("The Artist has drawn two concepts. Choose one to go on.", T.BLUE)
            ConceptDialog(self)
            return
        if kind == "pcb":
            # The PCB Designer (nemo/pcb.py): 0 a clean board, 1 made with problems, 2 not made.
            self.announce({0: "The PCB Designer has made the board: routed, checked, with its Gerbers.",
                           1: "The PCB Designer made the board, but not cleanly: the output says what."
                           }.get(rc, "The PCB Designer could not make the board: the output says which "
                                     "parts still need a footprint."),
                          {0: T.PASS, 1: T.SKIP}.get(rc, T.FAIL))
            return
        if kind == "second":
            # The Second Opinion (nemo/second.py): 0 agrees, 1 doubts some.
            if rc == 0:
                self.announce("The Second Opinion agrees with every connection.", T.PASS)
            elif rc == 1:
                from .. import second
                n = len(second.doubts(self.project.root)) if self.project else 0
                self.announce(f"The Second Opinion doubts {n} connection(s): click it in the Workshop "
                              "to see which and why. It changes nothing; Nemo's checks still decide.",
                              T.SKIP)
            else:
                self.announce("The Second Opinion could not look: the output says why.", T.FAIL)
            return
        if kind == "draft_part":
            self.announce("The Datasheet Reader has drafted a part: check it in the parts folder's "
                          "drafts before moving it up." if rc == 0 else
                          "The Datasheet Reader could not read it: the output says why.",
                          T.PASS if rc == 0 else T.FAIL)
            return
        if kind == "eval":
            # The Quality Inspector's verdict (nemo/shipcheck.py): 0 SHIP, 1 DON'T SHIP.
            from .. import shipcheck
            last = next(iter(shipcheck.history(n=1)), None)
            if rc in (0, 1) and last:
                self.announce(f"The Quality Inspector says {last['verdict']}: {last['candidate']} "
                              f"{last['candidate_passed']} of {last['of']}, {last['base']} "
                              f"{last['base_passed']}.", T.PASS if rc == 0 else T.SKIP)
            else:
                self.announce("The Quality Inspector could not run the check: the output says why.",
                              T.FAIL)
            return
        if rc == 0 and kind == "run":
            self.after(1500, self.load_next_model)
        if rc == 0:
            self.announce({"draft": "Brief drafted. Check it, then save.",
                           "run": "Finished.",
                           "story": "Story written: find it with the Story button.",
                           "cover": "Cover painted: see it in the Story list."
                           }.get(kind, "Done."), T.PASS)
        elif rc == 1:
            # The employee whose step it is says so (owner, 2026-11-04), and
            # its card in its room holds the fixes.
            first = next(iter(sum(self.project_issues().values(), [])), None)
            if first is not None:
                from ..staff import DEPARTMENTS, STAFF
                e = STAFF[first.owner]
                self.announce(f"The {e.label} has a problem: {first.headline()}. Click the "
                              f"{e.title} in the {DEPARTMENTS[e.department].name} for the fix.",
                              T.FAIL)
            else:
                self.announce("A check failed. The results show what, and where to "
                              "fix it.", T.FAIL)
        else:
            self.announce(f"Stopped with an error (code {rc}). The output shows "
                          "why.", T.FAIL)

    # --------------------------------------------------------- doctor
    def open_doctor(self):
        Doctor(self)

    # ------------------------------------------------------ keys/close
    def _keys(self):
        self.bind_all("<Control-n>", lambda e: self.new_project())
        self.bind_all("<Control-s>", lambda e: self.save_brief())
        self.bind_all("<F5>", lambda e: self.run_step(only=True))
        self.bind_all("<Escape>", lambda e: self.stop_job())

    def _close(self):
        if self.job and self.job.running and not messagebox.askyesno(
                "Quit Nemo?", "A step is still running. Stop it and quit?",
                parent=self):
            return
        if self.brief_changed() and messagebox.askyesno(
                "Unsaved brief", "Save your changes to the brief first?",
                parent=self):
            self.save_brief(quiet=True)
        self.stop_job()
        zoomed = self.state() == "zoomed"
        self.settings["zoomed"] = zoomed
        if not zoomed:                     # the maximised size is the screen's, not a choice
            self.settings["geometry"] = self.geometry()
        C.save_settings(self.settings)
        self.destroy()


# ====================================================================
#  Dialogs
# ====================================================================

class NewProject(tk.Toplevel):
    def __init__(self, app: NemoApp):
        super().__init__(app)
        self.app = app
        self.title("New project")
        self.configure(bg=T.PANEL, padx=20, pady=18, highlightthickness=1,
                       highlightbackground=T.RULE)
        self.resizable(False, False)
        self.transient(app); self.grab_set()
        ttk.Label(self, text="Name", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w")
        self.name = ttk.Entry(self, width=48)
        self.name.grid(row=1, column=0, sticky="ew", pady=(2, 12))
        ttk.Label(self, text="What should it do? (optional)",
                  style="Panel.TLabel").grid(row=2, column=0, sticky="w")
        self.desc = tk.Text(self, height=5, width=56, wrap="word",
                            relief="flat", font=app.fonts["body"],
                            highlightthickness=1, highlightbackground=T.RULE,
                            highlightcolor=T.BLUE, padx=6, pady=4)
        self.desc.grid(row=3, column=0, sticky="ew", pady=(2, 6))
        self.err = ttk.Label(self, text="", style="Panel.TLabel",
                             foreground=T.FAIL)
        self.err.grid(row=4, column=0, sticky="w")
        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.grid(row=5, column=0, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Create and draft with Nemo",
                   command=lambda: self.create(True)).pack(side="right", padx=8)
        ttk.Button(bar, text="Create", style="Primary.TButton",
                   command=lambda: self.create(False)).pack(side="right")
        self.bind("<Return>", lambda e: self.create(False)
                  if e.widget is not self.desc else None)
        self.name.focus_set()

    def create(self, draft):
        name = self.name.get()
        desc = self.desc.get("1.0", "end").strip()
        if draft and not desc:
            self.err.config(text="Describe it first, so Nemo has something "
                                 "to draft from.")
            return
        try:
            proj = C.create_project(name, self.app.cfg)
        except ValueError as exc:
            self.err.config(text=str(exc)); return
        if desc:
            b = proj.load_brief(); b.function = desc; proj.save_brief(b)
        self.destroy()
        self.app.refresh_projects(select=proj.root.name)
        self.app.tabs.select(self.app.tab_brief)
        if draft:
            self.app.draft_brief()
        else:
            self.app.say("Project created. Fill in the brief, then save it.")


class RenderDialog(tk.Toplevel):
    """The four views of the housing, drawn from its STL, with the numbers.

    The report sits beside the picture, not under it, and the picture is
    scaled to fit: stacked, the first version was 844 px tall and its
    buttons fell off the bottom of a 768 px screen.
    """
    MAX_SIDE = 500

    def __init__(self, app: NemoApp, res):
        super().__init__(app)
        _dialog(self, app, "The housing, from its STL", "+60+20")
        self.transient(app)
        img = tk.PhotoImage(file=str(res.files[0]))
        if img.width() > self.MAX_SIDE:                 # integer zoom / subsample = a fraction
            img = img.zoom(3).subsample(max(1, round(3 * img.width() / self.MAX_SIDE)))
        self.img = img                                  # kept: Tk drops unreferenced images
        tk.Label(self, image=self.img, bg=T.PANEL, bd=0).grid(row=0, column=0, rowspan=2)
        side = ttk.Frame(self, style="Panel.TFrame")
        side.grid(row=0, column=1, sticky="nsew", padx=(16, 0))
        self.columnconfigure(1, weight=1)
        ttk.Label(side, text=res.report, style="Panel.TLabel", justify="left",
                  wraplength=290).pack(anchor="w")
        ttk.Label(side, text="Drawn from the file, not imagined: a wall, cutout or boss is "
                  "where the STL has it. Top left is the isometric view; then top, "
                  "front and right.", style="PanelMuted.TLabel", wraplength=290,
                  justify="left").pack(anchor="w", pady=(10, 0))
        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.grid(row=1, column=1, sticky="se", pady=(8, 0))
        ttk.Button(bar, text="Open folder", command=lambda: C.open_path(res.files[0].parent)
                   ).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="left")


class ConceptDialog(tk.Toplevel):
    """The Artist's two concepts side by side: the model rendered, and its
    floor plan with the parts named. The owner picks one, may change its
    corners, its cable opening and (in words) where the parts go, and the
    Designer then builds that (owner's request, 2026-10-20)."""
    # Sized for the AH531's 1366 x 768 screen: at 300 px the dialog stood
    # taller than the screen, and its buttons would fall off the bottom.
    PIC = 240                                       # widest a picture is shown
    PLAN = 240

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Choose a concept", "+40+20")
        self.transient(app)
        self.app = app
        drawn, pick, _, folder, box, parts = C.concept_state(app.project, app.library)
        self.drawn = {c.key: c for c in drawn}
        self.box, self.parts = box, {p.ref: p for p in parts}
        self.images = []                            # kept: Tk drops unreferenced images
        # A shaped object (a replica, a prop) gets two blueprints from the Art
        # Studio's kit of shapes instead of two trays (owner, 2026-10-28;
        # painted impressions before, which the Designer could not build).
        kind = drawn[0].kind if drawn else "tray"
        self.painted = kind in ("painted", "blockout")
        self.blockout = kind == "blockout"
        intro = ("Nemo built the object two ways from its parts (the main forms, and more "
                 "detail), from its real size, each drawn as a "
                 "blueprint: front, top and side views at one scale with the size marked, an "
                 "isometric view, and dashed lines for any shape hidden inside another. One "
                 "too big for the printer shows, in amber, the pieces it is printed in and "
                 "the pinned joints between them. The one you choose is what the Art "
                 "Studio's Designer builds; say what to change." if self.blockout else
                 "The Artist painted two impressions of the object. Nemo makes only "
                 "rectangular trays, so the shape is modelled in a CAD program; choose the "
                 "one to work from and say what to change." if self.painted else
                 "The Artist drew two ways the case could be, from geometry the Designer "
                 "can build. Choose one; change it if you like.")
        ttk.Label(self, text=intro, style="Panel.TLabel", wraplength=900,
                  justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.key = tk.StringVar(value=(pick.concept if pick else "A"))
        from ..concept import picture
        for col, c in enumerate(drawn):
            box_ = ttk.Frame(self, style="Panel.TFrame")
            box_.grid(row=1, column=col, sticky="n", padx=(0 if col == 0 else 14, 0))
            ttk.Radiobutton(box_, text=f"{c.key}: {c.title}", value=c.key, variable=self.key,
                            command=self._picked).pack(anchor="w")
            # The rendered model and the floor plan side by side: stacked,
            # the dialog stood 733 px tall on a 768 px screen.
            pics = ttk.Frame(box_, style="Panel.TFrame"); pics.pack(anchor="w", pady=(4, 4))
            png = picture(app.project.root, c)
            side = 600 if self.blockout else self.PIC + self.PLAN if self.painted else self.PIC
            # As tall as the screen leaves room for: the text, the choices and
            # the Use button take about 360 px (2026-11-04: at full size the
            # chooser stood 740 high on a 768 screen, its button under the taskbar).
            top_, bottom_ = work_area(self)[1::2]
            tall = max(200, bottom_ - top_ - 360)
            if png.exists():
                try:
                    from PIL import Image, ImageTk
                    im = Image.open(png).convert("RGB")
                    k = min(1.0, side / im.width, tall / im.height)
                    if k < 1.0:
                        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
                    img = ImageTk.PhotoImage(im)
                    self.images.append(img)
                    tk.Label(pics, image=img, bg=T.PANEL, bd=0).pack(side="left", padx=(0, 6))
                except (tk.TclError, OSError):
                    pass
            else:
                ttk.Label(pics, text="Not painted yet.", style="PanelMuted.TLabel").pack(
                    side="left")
            if not self.painted:
                self._plan(pics, c).pack(side="left", anchor="n")
            ttk.Label(box_, text=" ".join(c.said), style="PanelMuted.TLabel",
                      wraplength=2 * self.PIC, justify="left").pack(anchor="w")

        ch = ttk.Frame(self, style="Panel.TFrame")
        ch.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(ch, text="Changes", style="Panel.TLabel",
                  font=app.fonts["strong"]).grid(row=0, column=0, sticky="w", columnspan=4)
        self.corners = ttk.Combobox(ch, state="readonly", width=12,
                                    values=["Square", "Rounded"])
        self.notch = ttk.Combobox(ch, state="readonly", width=12,
                                  values=["Left wall", "Front wall"])
        if not self.painted:
            ttk.Label(ch, text="Corners", style="Panel.TLabel").grid(row=1, column=0, sticky="w")
            self.corners.grid(row=1, column=1, sticky="w", padx=(6, 18), pady=4)
            ttk.Label(ch, text="Cable opening", style="Panel.TLabel").grid(row=1, column=2,
                                                                            sticky="w")
            self.notch.grid(row=1, column=3, sticky="w", padx=(6, 0), pady=4)
        ttk.Label(ch, text=("What to change (optional; the Designer is told)" if self.blockout else
                            "What to change from the picture (optional; it goes into the "
                            "build guide)" if self.painted else
                            "Anything about where the parts go (optional; the Designer "
                            "is told, and the model is asked for an order)"),
                  style="Panel.TLabel").grid(row=2, column=0, columnspan=4, sticky="w",
                                             pady=(6, 2))
        self.notes = tk.Text(ch, height=3, width=70, wrap="word", relief="flat",
                             font=app.fonts["body"], highlightthickness=1,
                             highlightbackground=T.RULE, highlightcolor=T.BLUE,
                             padx=6, pady=4)
        self.notes.grid(row=3, column=0, columnspan=4, sticky="ew")
        self.err = ttk.Label(self, text="", style="Panel.TLabel", foreground=T.FAIL)
        self.err.grid(row=3, column=0, columnspan=2, sticky="w")
        bar = ttk.Frame(self, style="Panel.TFrame")
        bar.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Use this concept", style="Primary.TButton",
                   command=self.use).pack(side="right", padx=8)
        if pick:
            self.notes.insert("1.0", pick.notes)
        self._picked(pick)

    def _plan(self, parent, c) -> tk.Canvas:
        """The floor plan, parts named; y = 0 (the front wall) at the bottom."""
        box = self.box
        cv = tk.Canvas(parent, width=self.PLAN, height=1, bg=T.PANEL, highlightthickness=0)
        if box is None:
            return cv
        s = (self.PLAN - 4) / box.length
        h = box.width * s + 4
        cv.config(height=h)

        def X(x):
            return 2 + x * s

        def Y(y):
            return 2 + (box.width - y) * s

        from ..enclosure import corner_radius
        r = corner_radius(box) if c.corners == "rounded" else 0.0
        self._rect(cv, X(0), Y(box.width), X(box.length), Y(0), r * s,
                   fill="#9CB0C6", outline="#33475B")
        self._rect(cv, X(box.wall), Y(box.width - box.wall), X(box.length - box.wall),
                   Y(box.wall), max(r - box.wall, 0) * s, fill="#DCE4EC", outline="#33475B")
        placed = c.layout()
        for a in placed:
            x, y = box.wall + a.x, box.wall + a.y
            cv.create_rectangle(X(x), Y(y + a.dy), X(x + a.dx), Y(y), fill="white",
                                outline="#1F3A5F", width=1.5)
            from ..concept import label_for
            label = label_for(self.parts.get(a.ref), a.ref, a.dx * s / 6)
            from tkinter import font as tkfont
            wide = tkfont.Font(font=self.app.fonts["small"]).measure(label)
            if wide > a.dx * s - 2:         # wider than its box: start at its left edge
                cv.create_text(X(x) + 2, Y(y + a.dy / 2), text=label, fill="#1F3A5F",
                               font=self.app.fonts["small"], anchor="w")
            else:
                cv.create_text(X(x + a.dx / 2), Y(y + a.dy / 2), text=label, fill="#1F3A5F",
                               font=self.app.fonts["small"])
        from ..enclosure import NOTCH
        mcu = next((a for a in placed if self.parts.get(a.ref) is not None
                    and self.parts[a.ref].category == "mcu"), placed[0] if placed else None)
        if mcu is not None:
            nw = NOTCH[0]
            if c.notch_wall == "front":
                cx = box.wall + mcu.x + mcu.dx / 2
                cv.create_rectangle(X(cx - nw / 2), Y(box.wall), X(cx + nw / 2), Y(0),
                                    fill="#E07A1F", outline="")
            else:
                cy = box.wall + mcu.y + mcu.dy / 2
                cv.create_rectangle(X(0), Y(cy + nw / 2), X(box.wall), Y(cy - nw / 2),
                                    fill="#E07A1F", outline="")
        return cv

    @staticmethod
    def _rect(cv, x0, y0, x1, y1, r, **kw):
        """A rectangle, its corners rounded by r pixels (Tk has no such shape)."""
        if r <= 0.5:
            return cv.create_rectangle(x0, y0, x1, y1, **kw)
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return cv.create_polygon(pts, smooth=True, **kw)

    def _picked(self, pick=None):
        """Fill the changes with the chosen concept's own style (or, on
        opening, the earlier choice's)."""
        c = self.drawn.get(self.key.get())
        corners = pick.corners if pick else (c.corners if c else "square")
        notch = pick.notch_wall if pick else (c.notch_wall if c else "left")
        self.corners.set(corners.capitalize())
        self.notch.set("Front wall" if notch == "front" else "Left wall")

    def use(self):
        corners = self.corners.get().lower()
        notch = "front" if self.notch.get().startswith("Front") else "left"
        try:
            pick = C.choose_concept(self.app.project, self.app.library, self.key.get(),
                                    corners, notch, self.notes.get("1.0", "end").strip())
        except ValueError as exc:
            self.err.config(text=str(exc))
            return
        self.destroy()
        from ..concept import describe
        self.app.say("Chosen. " + describe(pick), T.PASS)
        self.app.run_stage("concept")


class NewPartDialog(tk.Toplevel):
    """Add a part to your own parts library -- never the bundled one.

    Every field the checks actually use is here, with the units they're in
    right beside them, so nothing has to be guessed at. What is required
    (name, category, and where the figures came from) is enforced before
    Save does anything; everything else defaults to blank or zero rather
    than a guessed number, because a blank is honest and a guessed 100 mA
    is not.
    """

    def __init__(self, app: NemoApp, add_to_project: bool = True):
        super().__init__(app)
        self.app = app
        self.add_to_project = add_to_project
        _dialog(self, app, "New part", "+260+30")
        self.transient(app); self.grab_set()

        wrap = ttk.Frame(self, style="Panel.TFrame")
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(1, weight=1)
        self.fields = {}
        r = 0

        def row(label, key, width=None, hint=None):
            # Entry and hint share one frame, so the hint sits right beside
            # its own field instead of in a distant far-right column.
            nonlocal r
            ttk.Label(wrap, text=label, style="Panel.TLabel").grid(
                row=r, column=0, sticky="nw", pady=4, padx=(0, 12))
            cell = ttk.Frame(wrap, style="Panel.TFrame")
            cell.grid(row=r, column=1, sticky="w", pady=4)
            e = ttk.Entry(cell, width=width or 30)
            e.pack(side="left")
            self.fields[key] = e
            if hint:
                ttk.Label(cell, text=hint, style="PanelMuted.TLabel").pack(
                    side="left", padx=(8, 0))
            r += 1
            return e

        row("Reference *", "ref", 22,
            "short id, e.g. bme280 -- letters, numbers, underscores")
        row("Name *", "name", 56)
        cat = ttk.Combobox(wrap, values=C.known_categories(), width=18)
        cat.grid(row=r, column=1, sticky="w", pady=4)
        ttk.Label(wrap, text="Category *", style="Panel.TLabel").grid(
            row=r, column=0, sticky="nw", pady=4)
        self.fields["category"] = cat
        r += 1
        row("Supply voltage(s)", "supply_v", 18, "volts, comma-separated, e.g. 3.3, 5.0")
        row("Logic voltage", "logic_v", 10, "volts -- leave blank if not applicable")
        row("Typical current", "current_ma", 10, "mA")
        row("Peak current", "peak_ma", 10, "mA -- used for the safety margin check")
        row("Size (L x W x H)", "size_mm", 18, "mm, comma-separated")
        mount = ttk.Combobox(wrap, values=["", "holes", "slot", "panel", "loose"],
                             state="readonly", width=12,
                             style="Field.TCombobox")
        mount.grid(row=r, column=1, sticky="w", pady=4)
        ttk.Label(wrap, text="Mount", style="Panel.TLabel").grid(
            row=r, column=0, sticky="nw", pady=4)
        self.fields["mount"] = mount
        r += 1
        row("Interfaces", "interfaces", 30, "comma-separated, e.g. spi, i2c")

        ttk.Label(wrap, text="Source *", style="Panel.TLabel").grid(
            row=r, column=0, sticky="nw", pady=4)
        ds = ttk.Entry(wrap)
        ds.grid(row=r, column=1, columnspan=2, sticky="ew", pady=4)
        self.fields["datasheet"] = ds
        ttk.Label(wrap, text="datasheet name and revision, or 'estimated, "
                  "not yet verified'", style="PanelMuted.TLabel").grid(
            row=r + 1, column=1, columnspan=2, sticky="w")
        r += 2

        ttk.Label(wrap, text="Notes", style="Panel.TLabel").grid(
            row=r, column=0, sticky="nw", pady=(4, 0))
        notes = tk.Text(wrap, height=4, width=40, wrap="word", relief="flat",
                        font=app.fonts["body"], highlightthickness=1,
                        highlightbackground=T.RULE, highlightcolor=T.BLUE,
                        padx=6, pady=4)
        notes.grid(row=r, column=1, columnspan=2, sticky="ew", pady=(4, 0))
        self.fields["notes"] = notes
        r += 1

        self.err = tk.Text(wrap, height=3, wrap="word", relief="flat",
                           bg=T.PANEL, fg=T.FAIL, font=app.fonts["small"],
                           highlightthickness=0, padx=0)
        self.err.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        self.err.config(state="disabled")
        r += 1

        self.overwrite_note = ttk.Label(wrap, text="", style="Panel.TLabel",
                                        foreground=T.SKIP, wraplength=560,
                                        justify="left")
        self.overwrite_note.grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        self._pending_overwrite = False

        bar = ttk.Frame(wrap, style="Panel.TFrame")
        bar.grid(row=r, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        self.save_btn = ttk.Button(bar, text="Save", style="Primary.TButton",
                                   command=self.save)
        self.save_btn.pack(side="right", padx=8)
        self.fields["ref"].focus_set()

        # Size to what the form actually needs. A fixed guess (640x640) was
        # 260 px too narrow and 23 px too short: the Name field was cut off
        # and Save sat on the bottom edge. Capped to the screen so a small
        # display still gets a usable, reachable window.
        self.update_idletasks()
        w = min(self.winfo_reqwidth() + 8, self.winfo_screenwidth() - 40)
        h = min(self.winfo_reqheight() + 8, self.winfo_screenheight() - 80)
        self.geometry(f"{w}x{h}+260+30")
        self.minsize(w, h)

    def _get(self, key):
        w = self.fields[key]
        return (w.get("1.0", "end").strip() if isinstance(w, tk.Text)
                else w.get().strip())

    def _collect(self) -> dict:
        def nums(s):
            return [float(x.strip()) for x in s.split(",") if x.strip()]
        return {
            "ref": self._get("ref").lower(), "name": self._get("name"),
            "category": self._get("category"),
            "supply_v": nums(self._get("supply_v")),
            "logic_v": (float(self._get("logic_v"))
                       if self._get("logic_v") else None),
            "current_ma": (float(self._get("current_ma"))
                          if self._get("current_ma") else 0.0),
            "peak_ma": (float(self._get("peak_ma"))
                       if self._get("peak_ma") else 0.0),
            "size_mm": nums(self._get("size_mm")),
            "mount": self._get("mount"),
            "interfaces": [x.strip() for x in self._get("interfaces").split(",")
                          if x.strip()],
            "datasheet": self._get("datasheet"),
            "notes": self._get("notes"),
        }

    def _show_errors(self, lines):
        self.err.config(state="normal"); self.err.delete("1.0", "end")
        self.err.insert("end", "\n".join(f"\u2022 {l}" for l in lines))
        self.err.config(state="disabled")

    def save(self):
        try:
            data = self._collect()
        except ValueError:
            self._show_errors(["Voltage, current and size fields must be "
                               "numbers."])
            return
        problems = C.check_new_part(data, self.app.cfg,
                                    allow_overwrite=self._pending_overwrite)
        dup = [p for p in problems if "already in the library" in p]
        other = [p for p in problems if p not in dup]
        if other:
            self._show_errors(other)
            return
        if dup and not self._pending_overwrite:
            self._pending_overwrite = True
            self.overwrite_note.config(
                text=f"'{data['ref']}' already exists. Press Save again to "
                     "replace it, or change the reference.")
            self._show_errors([])
            return
        try:
            C.add_new_part(data, self.app.cfg,
                           allow_overwrite=self._pending_overwrite)
        except ValueError as exc:
            self._show_errors(str(exc).split("\n"))
            return
        self.destroy()
        self.app.part_added(data["ref"], self.add_to_project)


class PowerDialog(tk.Toplevel):
    """Supplies that suit the chosen parts, with the reasoning shown."""

    COLOURS = {"recommended": T.PASS, "enough": T.INK,
               "too small": T.SKIP, "not suitable": T.FAIL}

    def __init__(self, app: NemoApp, brief):
        super().__init__(app)
        self.app, self.brief = app, brief
        self.title("Suggest power")
        self.configure(bg=T.PANEL, padx=18, pady=16, highlightthickness=1,
                       highlightbackground=T.RULE)
        self.transient(app); self.grab_set()
        self.plan = C.power_plan_for(brief, app.library)
        p = self.plan
        ttk.Label(self, text="Power for this design", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="Panel.TLabel", wraplength=640, justify="left",
                  text=f"Your parts draw {p.peak_ma:.0f} mA at peak "
                       f"({p.typical_ma:.0f} mA typically). With Nemo's "
                       f"safety margin, the supply must give at least "
                       f"{p.need_ma} mA.").pack(anchor="w", pady=(4, 10))
        self.tree = ttk.Treeview(self, columns=("gives", "spare", "runtime", "verdict"),
                                 show="tree headings", height=len(p.options))
        self.tree.heading("#0", text="Option", anchor="w")
        for col, w, text in (("gives", 80, "Gives"), ("spare", 64, "Spare"),
                             ("runtime", 76, "Runs for"), ("verdict", 118, "Verdict")):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=w, stretch=False, anchor="w")
        self.tree.column("#0", width=380)
        for v, col in self.COLOURS.items():
            self.tree.tag_configure(v, foreground=col)
        self._opts = {}
        for o in p.options:
            iid = self.tree.insert("", "end", text=o.supply.label, tags=(o.verdict,), values=(
                f"{o.supply.ma:.0f} mA", f"{o.margin:.0%}" if o.margin > 0 else "none",
                f"{o.runtime_h:g} h" if o.runtime_h and o.verdict in
                ("recommended", "enough") else "", o.verdict.capitalize()))
            self._opts[iid] = o
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._selected())
        self.why = ttk.Label(self, text="", style="Panel.TLabel", wraplength=640,
                             justify="left")
        self.why.pack(anchor="w", pady=(10, 0))
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x", pady=(14, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        self.use = ttk.Button(bar, text="Use this option", style="Primary.TButton",
                              command=self._use)
        self.use.pack(side="right", padx=8)
        first = next(iter(self._opts), None)
        if first:
            self.tree.selection_set(first); self._selected()

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        o = self._opts[sel[0]]
        extra = (f" Adds to the parts: {', '.join(o.add_parts)}." if o.add_parts else "")
        self.why.config(text=o.why + extra)
        self.use.config(state="normal" if o.verdict in ("recommended", "enough")
                        else "disabled")

    def _use(self):
        from ..fixes import apply_power
        sel = self.tree.selection()
        if sel:
            self.app.use_power(apply_power(self.brief, self._opts[sel[0]]))
        self.destroy()


class FinishedWork(tk.Toplevel):
    """The Storeroom's Finished shelf (owner, 2026-11-11; nemo/finished.py):
    every department's finished work on the left, every part of the one
    chosen on the right, each part opened by double-clicking it."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        from .. import finished as F
        self.app, self.F = app, F
        _dialog(self, app, "Finished work", "980x560")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=900, justify="left",
                  text="Each department's finished work comes here by itself. Choose one on the "
                       "left to see every part of it; double-click a part to open it.").pack(anchor="w")
        panes = ttk.Frame(self, style="Panel.TFrame"); panes.pack(fill="both", expand=True, pady=8)
        self.pieces = ttk.Treeview(panes, columns=("when", "parts"), height=18)
        self.pieces.heading("#0", text="Department and work")
        self.pieces.heading("when", text="Finished"); self.pieces.heading("parts", text="Parts")
        self.pieces.column("#0", width=330); self.pieces.column("when", width=120)
        self.pieces.column("parts", width=50, anchor="e")
        self.pieces.pack(side="left", fill="both", expand=True)
        self.parts = ttk.Treeview(panes, columns=("size",), height=18)
        self.parts.heading("#0", text="Its parts"); self.parts.heading("size", text="Size")
        self.parts.column("#0", width=340); self.parts.column("size", width=80, anchor="e")
        self.parts.pack(side="left", fill="both", expand=True, padx=(8, 0))
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x")
        ttk.Button(bar, text="Open the part", command=self.open_part).pack(side="left")
        ttk.Button(bar, text="Open its folder", command=self.open_folder).pack(side="left", padx=8)
        ttk.Button(bar, text="Look again", command=self.fill).pack(side="left")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.pieces.bind("<<TreeviewSelect>>", lambda e: self.show())
        self.parts.bind("<Double-1>", lambda e: self.open_part())
        self._by_iid: dict = {}
        self._files: dict = {}
        self.fill()

    def fill(self):
        self.pieces.delete(*self.pieces.get_children())
        self._by_iid.clear()
        found = self.F.gather(self.app.cfg)
        for dept, items in self.F.by_department(found).items():
            top = self.pieces.insert("", "end", text=f"{self.F.department_name(dept)} ({len(items)})",
                                     open=True)
            for x in items:
                iid = self.pieces.insert(top, "end", text=x.title, values=(x.finished, x.parts))
                self._by_iid[iid] = x
        if not found:
            self.pieces.insert("", "end", text="Nothing finished yet")

    def chosen(self):
        sel = self.pieces.selection()
        return self._by_iid.get(sel[0]) if sel else None

    def show(self):
        self.parts.delete(*self.parts.get_children())
        self._files.clear()
        piece = self.chosen()
        if piece is None:
            return
        groups: dict = {}
        for g, f in self.F.parts(piece):
            if g not in groups:
                groups[g] = self.parts.insert("", "end", text=(g or "(the top folder)") + "/", open=True)
            try:
                kb = f"{max(1, f.stat().st_size // 1024)} KB"
            except OSError:
                kb = ""
            iid = self.parts.insert(groups[g], "end", text=f.name, values=(kb,))
            self._files[iid] = f

    def open_part(self):
        sel = self.parts.selection()
        f = self._files.get(sel[0]) if sel else None
        if f is not None:
            C.open_path(f)

    def open_folder(self):
        piece = self.chosen()
        if piece is not None:
            C.open_path(piece.path)


class VideoStore(tk.Toplevel):
    """The Storeroom as a 90s video store (owner, 2026-10-21;
    nemo/videostore.py): books, games, videos, pictures and parts on their
    aisles. Click a case to read, play, cast or see it."""

    # In Nemo's own walnut and brass (owner, 2026-11-04: the theme throughout).
    # It was a neon 90s store: purple floor, magenta and cyan signs. The
    # store and its aisles stay; each aisle keeps its own colour, as an
    # enamel sign would, painted warmer. The neon values, to go back:
    # BG 1B1530, title FF3DF5, line 36F9F6, sign panel 2A2140, empty 9C93B5 (hex).
    BG, SHELF, INK = "#1A120B", "#5A3E2B", "#F2E6C8"
    TITLE, LINE, PANEL, EMPTY = "#E0B868", "#C49A52", "#2B1E13", "#B39A72"
    SIGNS = {"BOOKS": "#E8C15A", "GAMES": "#7FB069", "VIDEOS": "#D9694F", "MUSIC": "#B08AC4",
             "AUDIO": "#7FB8A4",
             "PICTURES": "#6FA8C8", "PARTS": "#E0954A"}
    CASES = {"BOOKS": "#7A3B2E", "GAMES": "#2F4F2A", "VIDEOS": "#2A1A12", "MUSIC": "#4A2F57",
             "AUDIO": "#24504A",
             "PICTURES": "#2E4E5E", "PARTS": "#4B3F33"}
    W, CW, CH, GAP = 940, 104, 120, 12

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Storeroom", "980x660+160+40")
        from .. import storeroom, videostore
        self.app, self.V, self.S = app, videostore, storeroom
        storeroom.make_shelves(app.cfg.path("paths.storeroom"))
        self.canvas = tk.Canvas(self, bg=self.BG, highlightthickness=0)
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(side="bottom", fill="x", pady=(8, 0))
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-e.delta // 120, "units"))
        ttk.Button(bar, text="Parts catalogue...", command=lambda: StoreroomDialog(self.app)
                   ).pack(side="left")
        ttk.Button(bar, text="Open the shelves", command=lambda: C.open_path(
            self.app.cfg.path("paths.storeroom"))).pack(side="left", padx=8)
        ttk.Button(bar, text="Look again", command=self.draw).pack(side="left")
        ttk.Button(bar, text="Drives and space...", command=lambda: DrivesRoom(self.app)
                   ).pack(side="left", padx=8)
        ttk.Button(bar, text="Vault...", command=lambda: VaultRoom(self.app)).pack(side="left")
        ttk.Button(bar, text="Finished work...", command=lambda: FinishedWork(self.app)
                   ).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Credits...", command=self.credits).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(bar, style="PanelMuted.TLabel", text="", wraplength=480, justify="left")
        self.note.pack(side="left", padx=12)
        self.draw()
        # A drive plugged in while the Storeroom is open is picked up (owner, 2026-10-23).
        from .. import drives
        self._drives, self._drive_job = drives.drives(), None
        self._watch()

    def _watch(self):
        from .. import drives
        now = drives.drives()
        for d in drives.new_since(self._drives, now):
            self.note.config(text=f"{d.name} plugged in.")
            self.app.cue("drive")
            DrivesRoom(self.app, d)
        self._drives = now
        self._drive_job = self.after(4000, self._watch)

    def destroy(self):
        if getattr(self, "_drive_job", None):
            self.after_cancel(self._drive_job); self._drive_job = None
        super().destroy()

    def credits(self):
        """Who made what Nemo is built from (nemo/credits.py), as a page."""
        from .. import credits
        try:
            C.open_path(credits.write(self.app.cfg))
        except OSError as exc:
            self.note.config(text=f"The credits could not be written: {exc}")

    def _box_art(self, case):
        """A picture for the case's front: a story's cover, or the picture
        itself. None where there is none, or no Pillow to shrink it."""
        from pathlib import Path as _P
        path = None
        if case.aisle == "BOOKS" and case.thing is not None and (_P(case.thing) / "cover.png").is_file():
            path = _P(case.thing) / "cover.png"
        elif case.aisle == "PICTURES" and case.thing is not None:
            path = case.thing.path
        if path is None:
            return None
        try:
            from PIL import Image, ImageTk
            im = Image.open(path)
            im.thumbnail((self.CW - 12, 62))
            tkim = ImageTk.PhotoImage(im)
        except Exception:                                       # noqa: BLE001
            return None
        self._thumbs.append(tkim)               # Tk shows only what is kept
        return tkim

    def draw(self):
        c = self.canvas
        c.delete("all")
        self.cases, self._thumbs = [], []
        c.create_text(self.W // 2, 34, text="*** NEMO VIDEO ***", fill=self.TITLE,
                      font=("Courier New", 26, "bold"))
        c.create_text(self.W // 2, 64, text="be kind, rewind  -  open every day",
                      fill=self.LINE, font=("Courier New", 11, "italic"))
        y = 96
        per_row = max(1, (self.W - 150) // (self.CW + self.GAP))
        for aisle, cases in self.V.shelves(self.app.cfg).items():
            rows = max(1, -(-len(cases) // per_row))
            h = rows * (self.CH + self.GAP) + 14
            c.create_rectangle(14, y, 124, y + h - 10, fill=self.PANEL, outline=self.SIGNS[aisle], width=2)
            c.create_text(69, y + (h - 10) // 2, text=aisle, fill=self.SIGNS[aisle],
                          font=("Courier New", 13, "bold"))
            if not cases:
                c.create_text(150, y + 40, anchor="w", text=self.V.EMPTY[aisle],
                              fill=self.EMPTY, font=self.app.fonts["small"])
            for n, case in enumerate(cases):
                r, col = divmod(n, per_row)
                x0 = 150 + col * (self.CW + self.GAP)
                y0 = y + r * (self.CH + self.GAP)
                tag = f"case{len(self.cases)}"
                self.cases.append(case)
                c.create_rectangle(x0, y0, x0 + self.CW, y0 + self.CH, fill=self.CASES[aisle],
                                   outline=self.SIGNS[aisle], width=1, tags=(tag,))
                art = self._box_art(case)
                if art is not None:
                    c.create_image(x0 + self.CW // 2, y0 + 44, image=art, tags=(tag,))
                    short = case.title if len(case.title) <= 15 else case.title[:14] + "…"
                    c.create_text(x0 + self.CW // 2, y0 + 88, text=short,
                                  width=self.CW - 10, fill=self.INK, font=self.app.fonts["small"],
                                  tags=(tag,))
                else:
                    c.create_rectangle(x0 + 6, y0 + 10, x0 + self.CW - 6, y0 + 24,
                                       fill=self.SIGNS[aisle], outline="", tags=(tag,))
                    c.create_text(x0 + self.CW // 2, y0 + 60, text=case.title[:40],
                                  width=self.CW - 12, fill=self.INK, font=self.app.fonts["small"],
                                  tags=(tag,))
                c.create_text(x0 + self.CW // 2, y0 + self.CH - 10, text=case.subtitle[:30],
                              width=self.CW - 8, fill="#C9C2DA", font=("Courier New", 7),
                              tags=(tag,))
                c.tag_bind(tag, "<Button-1>", lambda e, i=len(self.cases) - 1: self.clicked(i, e))
            c.create_line(140, y + h - 8, self.W, y + h - 8, fill=self.SHELF, width=6)
            y += h + 10
        c.configure(scrollregion=(0, 0, self.W, y + 10))

    def clicked(self, i: int, event=None):
        case = self.cases[i]
        if not case.actions:
            self.note.config(text=f"{case.title}: {case.subtitle}")
            return
        menu = tk.Menu(self, tearoff=False)
        for act in case.actions:
            menu.add_command(label=act, command=lambda a=act: self.act(i, a))
        if event is not None:
            menu.tk_popup(event.x_root, event.y_root)
        return menu

    def act(self, i: int, action: str):
        case, t = self.cases[i], self.cases[i].thing
        try:
            if action == "Read":
                C.open_path(t / "story.md")
            elif action == "Show cover":
                C.open_path(t / "cover.png")
            elif action == "Open the folder":
                C.open_path(t)
            elif action == "Play":
                from .. import gaming
                gaming.play(t, self.app.cfg)
                self.note.config(text=f"The {t.console.name} Emulator is playing {t.name}. Esc quits.")
                return
            elif action == "Play here" and case.aisle == "AUDIO":
                from .. import music
                self.note.config(text=f"{case.title}: playing with {music.play_here([t])}.")
                return
            elif action == "Cast..." and case.aisle == "AUDIO":
                AudioRoom(self.app)
                self.note.config(text=f"In Audio: choose {case.title}, Find Chromecasts, Cast.")
                return
            elif action == "Play here" and case.aisle == "MUSIC":
                from .. import music
                self.note.config(text=f"{case.title}: playing with {music.play_here([t])}.")
                return
            elif action == "Cast..." and case.aisle == "MUSIC":
                MusicRoom(self.app)
                self.note.config(text=f"In the Music Room: choose {t.title}, Find Chromecasts, Cast.")
                return
            elif action in ("Play here", "Show"):
                from .. import theatre
                self.note.config(text=f"{case.title}: opened with {theatre.play_here(t)}.")
                return
            elif action == "Cast...":
                Theatre(self.app)
                self.note.config(text=f"In the Theatre: choose {t.name}, Find Chromecasts, Cast.")
                return
            elif action == "Details":
                self.note.config(text=f"{t.name}: {t.quantity} on hand"
                                      + (f", in {t.where}" if t.where else "")
                                      + (f"; library part {t.part}" if t.part else "; not linked to a library part")
                                      + (f". {t.notes}" if t.notes else "."))
                return
            self.note.config(text=f"{case.title}: opened.")
        except Exception as exc:                                # noqa: BLE001
            self.note.config(text=f"{case.title}: {exc}.")


class StoreroomDialog(tk.Toplevel):
    """The Storeroom: the parts you have to hand, how many, and where
    (owner, 2026-10-21; nemo/storeroom.py). On the stick they are in
    NemoData/nemo-storeroom."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Storeroom", "860x540+200+60")
        from .. import storeroom
        self.S, self.app = storeroom, app
        self.root_dir = app.cfg.path("paths.storeroom")
        ttk.Label(self, text="Storeroom", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=780, justify="left", text=(
            "The parts you have to hand. A name that is exactly a library part's is "
            "linked to it; choose the library part to link one that is not.")
                  ).pack(anchor="w", pady=(2, 6))
        # Search, sort and group (owner, 2026-10-29; storeroom.view).
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Search", style="PanelMuted.TLabel").pack(side="left")
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *a: self.show())
        ttk.Entry(bar, textvariable=self.query, width=28).pack(side="left", padx=(6, 18))
        ttk.Label(bar, text="Group by", style="PanelMuted.TLabel").pack(side="left")
        self.group = ttk.Combobox(bar, state="readonly", width=16,
                                  values=["Nothing", "Where it is kept", "Kind of part"])
        self.group.set("Nothing")
        self.group.bind("<<ComboboxSelected>>", lambda e: self.show())
        self.group.pack(side="left", padx=6)
        self.count = ttk.Label(bar, text="", style="PanelMuted.TLabel")
        self.count.pack(side="right")
        self.sort_col, self.descending = "name", False
        mid = ttk.Frame(self, style="Panel.TFrame"); mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=("qty", "name", "part", "where", "notes"),
                                 show="headings", height=12)
        self.HEADINGS = {"qty": "Have", "name": "Part", "part": "Library part",
                         "where": "Where", "notes": "Notes"}
        for col, w in (("qty", 50), ("name", 190), ("part", 160), ("where", 130), ("notes", 220)):
            self.tree.heading(col, text=self.HEADINGS[col], anchor="w",
                              command=lambda c=col: self.sort_by(c))
            self.tree.column(col, width=w, stretch=(col == "notes"), anchor="w")
        self.tree.column("#0", width=170, stretch=False)
        scroll = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._picked)

        form = ttk.Frame(self, style="Panel.TFrame"); form.pack(fill="x", pady=(8, 0))
        self.fields = {}
        refs = [""] + sorted(p.ref for p in app.library)
        for i, (key, label, width) in enumerate((("name", "Part", 24), ("qty", "How many", 6),
                                                 ("where", "Where", 14), ("part", "Library part", 22),
                                                 ("notes", "Notes", 24))):
            ttk.Label(form, text=label, style="PanelMuted.TLabel").grid(row=0, column=i, sticky="w", padx=(0, 6))
            w = (ttk.Combobox(form, values=refs, width=width, state="readonly") if key == "part"
                 else ttk.Entry(form, width=width))
            w.grid(row=1, column=i, sticky="w", padx=(0, 6))
            self.fields[key] = w
        self.fields["qty"].insert(0, "1")

        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="Add", style="Primary.TButton", command=self.add).pack(side="left")
        ttk.Button(row, text="Take", command=self.take).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Remove", command=self.remove).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Suggest", command=self.suggest).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Link", command=self.link).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(row, text="Back up Nemo...", command=self.ask_backup).pack(side="right", padx=(0, 8))
        self.note = ttk.Label(row, style="PanelMuted.TLabel", text="", wraplength=360,
                              justify="left")
        self.note.pack(side="left", padx=12)
        self.refresh()

    def refresh(self):
        try:
            self.items = self.S.load(self.root_dir)
        except self.S.StoreroomError as exc:
            self.items = []
            self.note.config(text=str(exc))
        self.show()

    def sort_by(self, col: str):
        """A column heading pressed: sort by it; pressed again, the other way."""
        self.descending = (not self.descending) if col == self.sort_col else False
        self.sort_col = col
        self.show()

    def show(self):
        """The items as the search, sort and grouping say; the file is not read again."""
        group = {"Where it is kept": "where", "Kind of part": "kind"}.get(self.group.get(), "none")
        groups = self.S.view(self.items, self.query.get(), self.sort_col, self.descending,
                             group, self.app.library)
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(show=("headings" if group == "none" else "tree headings"))
        for col, text in self.HEADINGS.items():
            mark = (" \u25bc" if self.descending else " \u25b2") if col == self.sort_col else ""
            self.tree.heading(col, text=text + mark)
        shown = 0
        for label, items in groups:
            parent = ""
            if label:
                parent = self.tree.insert("", "end", iid=f"group:{label}", open=True,
                                          text=f"{label} ({len(items)})")
            for i in items:
                self.tree.insert(parent, "end", iid=i.key,
                                 values=(i.quantity, i.name, i.part, i.where, i.notes))
                shown += 1
        total = len(self.items)
        self.count.config(text=(f"{total} item(s)" if shown == total
                                else f"{shown} of {total} item(s)"))

    def _picked(self, _e=None):
        sel = self.tree.selection()
        item = next((i for i in self.items if sel and i.key == sel[0]), None)
        if item is None:
            return
        for key, value in (("name", item.name), ("where", item.where), ("notes", item.notes)):
            self.fields[key].delete(0, "end"); self.fields[key].insert(0, value)
        self.fields["part"].set(item.part)

    def _qty(self) -> int | None:
        try:
            return int(self.fields["qty"].get().strip())
        except ValueError:
            self.note.config(text="How many must be a whole number.")
            return None

    def _do(self, fn, done: str):
        try:
            item = fn()
        except self.S.StoreroomError as exc:
            self.note.config(text=str(exc)[:1].upper() + str(exc)[1:] + ".")
            return
        self.refresh()
        self.note.config(text=done.format(item=item))

    def add(self):
        qty = self._qty()
        if qty is None:
            return
        f = self.fields
        self._do(lambda: self.S.add(self.root_dir, f["name"].get(), qty, part=f["part"].get(),
                                    where=f["where"].get(), notes=f["notes"].get(),
                                    library=self.app.library),
                 "{item.name}: {item.quantity} on hand.")

    def take(self):
        qty = self._qty()
        if qty is None:
            return
        self._do(lambda: self.S.take(self.root_dir, self.fields["name"].get(), qty),
                 "{item.name}: {item.quantity} left.")

    def suggest(self):
        """The Researcher: the library parts this item may be. It puts the
        likeliest in the Library part box; nothing is linked until Link."""
        name = self.fields["name"].get().strip()
        if not name:
            self.note.config(text="Pick an item, or type its name, first."); return
        found = self.S.suggest(name, self.app.library)
        if not found:
            self.note.config(text=f"Researcher: nothing in the library is like {name!r}."); return
        self.fields["part"].set(found[0].ref)
        self.note.config(text="Researcher: " + "; ".join(f"{s.ref} ({s.why})" for s in found)
                         + ". Press Link to link the one in the box.")

    def link(self):
        self._do(lambda: self.S.link(self.root_dir, self.fields["name"].get(),
                                     self.fields["part"].get(), self.app.library),
                 "{item.name} is now linked to {item.part}.")

    def remove(self):
        name = self.fields["name"].get()
        if self.S.remove(self.root_dir, name):
            self.refresh()
            self.note.config(text=f"Removed {name.strip()}.")
        else:
            self.note.config(text=f"There is no {name.strip()!r} in the Storeroom.")

    def ask_backup(self):
        """Choose a folder, then back up there (owner, 2026-10-21)."""
        from tkinter import filedialog
        from .. import backup
        dest = filedialog.askdirectory(parent=self, title="Where should the backup go?",
                                       initialdir=str(backup.default_folder()), mustexist=False)
        if dest:
            self.backup(Path(dest))

    def backup(self, dest: Path):
        """Your work and settings, in one zip with each file's hash; never
        the program, the models, the Researcher's key or the safety store."""
        from .. import backup
        self.note.config(text="Backing up..."); self.update_idletasks()
        try:
            made = backup.make(self.app.cfg, dest)
        except backup.BackupError as exc:
            self.note.config(text=f"Backup failed: {exc}.")
            return None
        self.note.config(text=f"Backed up {made.files} file(s) to {made.path.name}, in "
                              f"{made.path.parent}. Not in it: the program, models, "
                              "Researcher's key and safety store.")
        return made


class DrivesRoom(tk.Toplevel):
    """The Storeroom's space and drives (owner, 2026-10-23; nemo/drives.py):
    what each shelf takes, a plugged-in drive's files by extension with the
    shelf each goes on, moved over only when he says; a backup offered."""

    def __init__(self, app: NemoApp, drive=None):
        super().__init__(app)
        _dialog(self, app, "Storeroom: drives and space", "760x560+200+60")
        from .. import drives
        self.app, self.D = app, drives
        self.root_dir = app.cfg.path("paths.storeroom")
        self.space = ttk.Label(self, style="Panel.TLabel", text="", justify="left")
        self.space.pack(anchor="w")
        top = ttk.Frame(self, style="Panel.TFrame"); top.pack(fill="x", pady=(10, 4))
        ttk.Label(top, text="Drive:", style="Panel.TLabel").pack(side="left")
        self.pick = ttk.Combobox(top, state="readonly", width=40)
        self.pick.pack(side="left", padx=6)
        self.pick.bind("<<ComboboxSelected>>", lambda e: self.look())
        ttk.Button(top, text="Look again", command=self.refresh).pack(side="left")
        self.tree = ttk.Treeview(self, columns=("files", "size", "shelf"), height=12)
        for col, text, w in (("#0", "Kind", 120), ("files", "Files", 80), ("size", "Size", 100),
                             ("shelf", "Goes on", 220)):
            self.tree.heading(col, text=text); self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True)
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(8, 0))
        self.move_btn = ttk.Button(row, text="Move the chosen kinds over", command=self.move)
        self.move_btn.pack(side="left")
        self.backup_btn = ttk.Button(row, text="Back up Nemo to this drive", command=self.backup)
        self.backup_btn.pack(side="left", padx=8)
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=700, justify="left")
        self.note.pack(anchor="w", pady=(6, 0))
        self.groups, self.found = [], []
        self.refresh(drive)

    def refresh(self, drive=None):
        D = self.D
        use, free, total = D.space(self.root_dir)
        parts = ", ".join(f"{k} {D.human(v)}" for k, v in use.items() if v)
        self.space.config(text=f"The Storeroom's disk: {D.human(free)} free of {D.human(total)}.\n"
                               f"On the shelves: {parts or 'nothing yet'}.")
        self.found = D.drives()
        self.pick["values"] = [d.name for d in self.found]
        if not self.found:
            self.pick.set(""); self.tree.delete(*self.tree.get_children())
            self.note.config(text="No external drive is plugged in. The system disk and the boot "
                                  "stick are never shown here.")
            return
        names = [d.name for d in self.found]
        self.pick.set(drive.name if drive is not None and drive.name in names else names[0])
        self.look()

    def drive(self):
        return next((d for d in self.found if d.name == self.pick.get()), None)

    def look(self):
        d = self.drive()
        if d is None:
            return
        self.note.config(text=f"Looking at {d.name}..."); self.update_idletasks()
        self.groups, cut = self.D.survey(d.path)
        self.tree.delete(*self.tree.get_children())
        for i, g in enumerate(self.groups):
            self.tree.insert("", "end", iid=str(i), text=g.ext,
                             values=(len(g.files), self.D.human(g.bytes), g.shelf or "no shelf: stays"))
        size, fits = self.D.backup_fits(self.app.cfg, d)
        self.note.config(text=(f"{d.name}: {self.D.human(d.free)} free. " + ("Stopped looking at "
                               "20000 files. " if cut else "") + "Choose the kinds to move (Ctrl+click "
                               "for more); nothing moves until you press Move. A backup of Nemo is "
                               f"about {self.D.human(size)} before packing"
                               + ("." if fits else ": it does NOT fit on this drive.")))

    def move(self):
        from tkinter import messagebox
        chosen = [self.groups[int(i)] for i in self.tree.selection() if self.groups[int(i)].shelf]
        if not chosen:
            self.note.config(text="Choose one or more kinds with a shelf first."); return
        n = sum(len(g.files) for g in chosen)
        size = self.D.human(sum(g.bytes for g in chosen))
        if not messagebox.askyesno("Move them over?", f"Move {n} file(s), {size}, onto the "
                                   "Storeroom's shelves? Each is copied, checked by hash, and only "
                                   "then removed from the drive.", parent=self):
            return
        self.note.config(text="Moving..."); self.update_idletasks()
        try:
            done = self.D.move(chosen, self.root_dir)
        except OSError as exc:
            self.note.config(text=f"Nothing moved: {exc}."); return
        kept = "".join(f"\nKept on the drive: {f.name} ({why})" for f, why in done.kept[:5])
        self.note.config(text=f"Moved {len(done.moved)} file(s) onto the shelves." + kept)
        self.refresh(self.drive())

    def backup(self):
        from tkinter import messagebox
        from .. import backup
        d = self.drive()
        if d is None:
            return
        if not messagebox.askyesno("Back up Nemo?", f"Back up your work and settings to "
                                   f"{d.name}, folder nemo-backups?", parent=self):
            return
        self.note.config(text="Backing up..."); self.update_idletasks()
        try:
            made = backup.make(self.app.cfg, d.path / "nemo-backups")
        except backup.BackupError as exc:
            self.note.config(text=f"Backup failed: {exc}."); return
        self.note.config(text=f"Backed up {made.files} file(s) to {made.path}. The vault goes in "
                              "sealed; its passphrase never does.")


class VaultRoom(tk.Toplevel):
    """The vault (owner, 2026-10-23; nemo/vault.py): his letters and
    recordings, sealed with his passphrase; the companion reads letters only
    if he allows it here."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Storeroom: the vault", "640x480+220+80")
        from .. import vault
        self.app, self.V = app, vault
        self.root_dir = app.cfg.path("paths.storeroom")
        self.vault = None
        self.body = ttk.Frame(self, style="Panel.TFrame"); self.body.pack(fill="both", expand=True)
        self.note = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=600, justify="left")
        self.note.pack(anchor="w", pady=(6, 0))
        self.ask()

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def ask(self):
        self._clear()
        new = not self.V.exists(self.root_dir)
        ttk.Label(self.body, style="Panel.TLabel", text=(
            "Make the vault: choose a passphrase of 8 characters or more. If it is forgotten, "
            "what is in the vault cannot be opened by anyone, Nemo included." if new else
            "The vault is locked. Its passphrase:"), wraplength=600, justify="left").pack(anchor="w")
        self.pw = ttk.Entry(self.body, show="*", width=40); self.pw.pack(anchor="w", pady=6)
        self.pw.focus_set()
        self.pw.bind("<Return>", lambda e: self.open_it(new))
        ttk.Button(self.body, text="Make it" if new else "Open",
                   command=lambda: self.open_it(new)).pack(anchor="w")

    def open_it(self, new: bool):
        word = self.pw.get(); self.pw.delete(0, "end")
        self.note.config(text="Working (a few seconds, on purpose)..."); self.update_idletasks()
        try:
            self.vault = (self.V.create if new else self.V.unlock)(self.root_dir, word)
        except self.V.VaultError as exc:
            self.note.config(text=str(exc).capitalize() + "."); return
        self.app.vault = self.vault                   # the companion's way in, while open
        self.note.config(text="")
        self.show()

    def show(self):
        self._clear()
        self.tree = ttk.Treeview(self.body, columns=("kind", "added"), height=12)
        for col, text, w in (("#0", "Name", 300), ("kind", "Kind", 100), ("added", "Added", 140)):
            self.tree.heading(col, text=text); self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True)
        for it in self.vault.items():
            self.tree.insert("", "end", iid=it.id, text=it.name, values=(it.kind, it.added))
        row = ttk.Frame(self.body, style="Panel.TFrame"); row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Put a file in...", command=self.add).pack(side="left")
        ttk.Button(row, text="Open", command=self.open_item).pack(side="left", padx=6)
        ttk.Button(row, text="Lock", command=self.lock).pack(side="right")
        self.allow = tk.BooleanVar(value=self.V.companion_allowed(self.root_dir))
        ttk.Checkbutton(self.body, text="Nemo, as my companion, may read my letters while the "
                        "vault is open", variable=self.allow,
                        command=lambda: self.vault.allow_companion(self.allow.get())
                        ).pack(anchor="w", pady=(8, 0))

    def add(self):
        from tkinter import filedialog, messagebox
        path = filedialog.askopenfilename(parent=self, title="A letter or a recording")
        if not path:
            return
        remove = messagebox.askyesno("The original", "Remove the original once it is sealed in "
                                     "the vault? (It is read back first.)", parent=self)
        try:
            self.vault.add_file(Path(path), remove_original=remove)
        except (OSError, self.V.VaultError) as exc:
            self.note.config(text=f"Not kept: {exc}."); return
        self.show()

    def open_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        path = self.vault.open_copy(sel[0])
        C.open_path(path)
        self.note.config(text="A plain copy is open from a temporary folder; Lock deletes it.")

    def lock(self):
        if self.vault is not None:
            self.vault.lock()
        self.vault = None
        if getattr(self.app, "vault", None) is not None:
            self.app.vault = None
        self.ask()

    def destroy(self):
        if self.vault is not None:
            self.vault.lock()
            self.vault = None
            if getattr(self.app, "vault", None) is not None:
                self.app.vault = None
        super().destroy()


class ResearcherKey(tk.Toplevel):
    """The Mouser Search API key the Researcher uses to look for missing
    parts. Written to a key file (and, on the stick, NemoData/.keys), never
    shown again, never in the config or the image."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Researcher key", "560x230+260+140")
        from .. import research
        self.research = research
        ttk.Label(self, text="Mouser Search API key", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=520, justify="left", text=(
            "With it, the Researcher looks up parts the Inspector finds missing. Only the "
            "missing thing is sent to Mouser, never your brief. Get a free key from "
            "mouser.com (My Mouser, APIs). On the stick it is kept in NemoData/.keys, "
            "which anyone holding the stick can read.")).pack(anchor="w", pady=(4, 8))
        self.entry = ttk.Entry(self, show="\u2022", width=60)
        self.entry.pack(anchor="w")
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="Save", style="Primary.TButton", command=self.save).pack(side="left")
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(row, style="PanelMuted.TLabel", text=(
            "A key is set." if research.key() else "No key yet."))
        self.note.pack(side="left", padx=12)

    def save(self):
        value = self.entry.get().strip()
        if not value:
            self.note.config(text="Paste the key first."); return
        self.research.save_key(value)
        self.entry.delete(0, "end")
        if self.research.key_looks_right(value):
            self.note.config(text="Saved. The Researcher will use it.")
        else:
            self.note.config(text=f"Saved, but it does not look like a Mouser key "
                                  f"({len(value)} characters; theirs are 36, as "
                                  f"8-4-4-4-12). Check it.")


class WorkLog(tk.Toplevel):
    """Who had each step, what the Inspector said before it, how it ended
    (nemo/review.py writes it to .nemo/work.jsonl)."""

    WORDS = {"reviewed": "checked by the Inspector", "started": "started",
             "passed": "passed", "failed": "failed",
             "archived": "its answers kept for reuse"}

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Work log", "720x420+240+110")
        from ..review import work_log
        from .controller import STEP_NAMES, check_name
        import datetime as dt
        ttk.Label(self, text="Who did what", style="PanelH2.TLabel").pack(anchor="w")
        text = tk.Text(self, wrap="word", relief="flat", bg="white", font=app.fonts["body"],
                       padx=10, pady=6, highlightthickness=1, highlightbackground=T.RULE)
        text.pack(fill="both", expand=True, pady=8)
        rows = work_log(app.project.root) if app.project else []
        for e in reversed(rows[-200:]):
            when = dt.datetime.fromtimestamp(e.get("at", 0)).strftime("%d %b %H:%M")
            step = STEP_NAMES.get(e.get("step"), e.get("step"))
            # Lines written before the departments (2026-10-21) have none.
            who = " ".join(w for w in (e.get("department"), e.get("by") or e.get("who")) if w)
            line = f"{when}  {step}: {who} - {self.WORDS.get(e.get('event'), e.get('event'))}"
            stops = e.get("stops") or []
            if e.get("event") == "reviewed":
                line += ((", stopped: " + "; ".join(check_name(s) for s in stops))
                         if stops else ", may start")
            text.insert("end", line + "\n")
        if not rows:
            text.insert("end", "Nothing yet. Each step's handoffs appear here once it is run.")
        text.config(state="disabled")
        ttk.Button(self, text="Close", command=self.destroy).pack(anchor="e")


class StoryList(tk.Toplevel):
    """The stories Nemo has kept, newest first (owner's redesign,
    2026-10-17: the Story button locates what was created). On the stick
    they are in NemoData/nemo-stories."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Stories", "760x420+220+90")
        from . import prompt_logic as L
        self.root_dir = app.cfg.path("paths.stories")
        self.items = L.list_stories(self.root_dir)
        ttk.Label(self, text="Stories", style="PanelH2.TLabel").pack(anchor="w")
        mid = ttk.Frame(self, style="Panel.TFrame"); mid.pack(fill="both", expand=True, pady=8)
        self.tree = ttk.Treeview(mid, columns=("name", "changed", "cover", "asked"),
                                 show="headings", height=12)
        for col, w, text in (("name", 150, "Story"), ("changed", 120, "Last changed"),
                             ("cover", 50, "Cover"), ("asked", 260, "What was asked for")):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=w, stretch=(col == "asked"), anchor="w")
        import datetime as dt
        for i, st in enumerate(self.items):
            when = dt.datetime.fromtimestamp(st["changed"]).strftime("%d %b %Y %H:%M")
            has = "yes" if (Path(st["path"]) / "cover.png").is_file() else ""
            self.tree.insert("", "end", iid=str(i), values=(st["name"], when, has, st["asked"]))
        self.tree.pack(side="left", fill="both", expand=True)
        # The selected story's cover, small (the Artist paints it 512 px).
        self.preview = tk.Label(mid, bg=T.PANEL, bd=0, width=172)
        self.preview.pack(side="left", padx=(10, 0), anchor="n")
        self._img = None
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_cover())
        self.tree.bind("<Double-1>", lambda e: self.open_folder())
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x")
        ttk.Button(row, text="Open its folder", command=self.open_folder).pack(side="left")
        ttk.Button(row, text="Write it", style="Primary.TButton",
                   command=self.write).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Paint a cover", command=self.cover).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(row, style="PanelMuted.TLabel", text=(
            f"{len(self.items)} kept in {self.root_dir}" if self.items else
            "No stories yet. Ask for one in Nemo's prompt window."))
        self.note.pack(side="left", padx=12)

    def open_folder(self):
        sel = self.tree.selection()
        if sel:
            C.open_path(self.items[int(sel[0])]["path"])

    def write(self):
        """The employees write the chosen story, as a job in the main
        window: its progress goes to the log there."""
        sel = self.tree.selection()
        if not sel:
            return
        name = self.items[int(sel[0])]["name"]
        self.destroy()
        self.app.start_job(C.nemo_argv("story", "write", name, "--json"), "story")

    def show_cover(self):
        sel = self.tree.selection()
        f = Path(self.items[int(sel[0])]["path"]) / "cover.png" if sel else None
        self._img = None
        if f is not None and f.is_file():
            try:
                img = tk.PhotoImage(file=str(f))
                self._img = img.subsample(max(1, -(-img.width() // 170)))
            except tk.TclError:
                self._img = None
        self.preview.config(image=self._img or "", text="" if self._img else
                            ("No cover yet." if sel else ""))

    def cover(self):
        """The Artist paints the chosen story's cover, as a job in the main
        window. It takes many minutes on this laptop; Stop ends it."""
        sel = self.tree.selection()
        if not sel:
            return
        name = self.items[int(sel[0])]["name"]
        self.destroy()
        self.app.start_job(C.nemo_argv("story", "cover", name, "--json"), "cover")


# The departments' own windows: these open inside Nemo's window (NemoApp.embed).
def _above_department():
    """Every message box and file dialog stands an embedded department
    aside while it is up (D205); they all pass through Dialog.show."""
    from tkinter import commondialog
    show = commondialog.Dialog.show

    def above(self, **options):
        app = getattr(tk, "_default_root", None)
        moved = app is not None and hasattr(app, "stand_aside") and app.stand_aside()
        try:
            return show(self, **options)
        finally:
            if moved:
                app.come_back()
    commondialog.Dialog.show = above


_above_department()


# Each department's own working window (the Workshop and the Computer Lab are the
# main window), by class name: real_window opens it, department_of reads it back.
WINDOW_OF = {"library": "StoryList", "art_studio": "ArtStudio", "storeroom": "VideoStore",
             "theatre": "Theatre", "gaming": "Gaming", "music": "MusicRoom", "audio": "AudioRoom",
             "bench": "TestBench", "printshop": "PrintShop", "film": "FilmStudio",
             "home": "HomeRoom", "comms": "CommsRoom", "science": "ScienceRoom",
             "doctors": "Clinic", "studio": "GameStudio"}


def department_of(win) -> str | None:
    """The department a window in view belongs to, or None."""
    key = getattr(win, "key", None)
    if type(win).__name__ == "IllustratedRoom" and isinstance(key, str):
        return key
    return next((k for k, name in WINDOW_OF.items() if type(win).__name__ == name), None)


DEPARTMENT_WINDOWS = {"StoryList", "VideoStore", "ArtStudio", "Theatre", "Gaming", "MusicRoom",
                      "AudioRoom", "TestBench", "PrintShop", "FilmStudio", "HomeRoom", "CommsRoom",
                      "ScienceRoom", "Clinic", "IllustratedRoom", "GameStudio"}


def _cancel(win, job) -> None:
    # docs/design-rules.md, mistake 2: a pending after() outlives its widget.
    try:
        win.after_cancel(job)
    except (tk.TclError, ValueError):
        pass


def work_area(win) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the screen not under the taskbar."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            r = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):   # SPI_GETWORKAREA
                return r.left, r.top, r.right, r.bottom
        except (AttributeError, OSError):
            pass
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight() - 48


def _fit_on_screen(win) -> None:
    """Move a window that would reach under the taskbar up into view, and cut
    one taller than the work area to its height (2026-11-04: the concept
    chooser opened 740 high at y 20 on a 768 screen, its Use button hidden
    under the taskbar; D214 was the main window's same fault)."""
    try:
        win.update_idletasks()
        left, top, right, bottom = work_area(win)
        # The window manager's title bar and border sit outside the size Tk
        # gives (31 px of title here): the whole frame must fit, not its inside.
        frame_top = max(0, win.winfo_rooty() - win.winfo_y())
        frame_side = max(0, win.winfo_rootx() - win.winfo_x())
        w = min(max(win.winfo_width(), win.winfo_reqwidth()), right - left - 2 * frame_side)
        h = min(max(win.winfo_height(), win.winfo_reqheight()), bottom - top - frame_top - frame_side)
        x = min(max(win.winfo_x(), left), right - w - 2 * frame_side)
        y = min(max(win.winfo_y(), top), bottom - h - frame_top - frame_side)
        win.geometry(f"{w}x{h}+{x}+{y}")
    except tk.TclError:
        pass                                   # closed meanwhile


def _dialog(win, app, title, geometry):
    win.title(title); win.geometry(geometry)
    # Not for a department's window: Nemo's own window places those (embed).
    if type(win).__name__ not in DEPARTMENT_WINDOWS:
        job = win.after(60, lambda: _fit_on_screen(win))
        win.bind("<Destroy>", lambda e: e.widget is win and _cancel(win, job), add="+")
    if hasattr(app, "brand"):
        app.brand(win)
    win.configure(bg=T.PANEL, padx=16, pady=14, highlightthickness=1,
                  highlightbackground=T.RULE)
    win.transient(app)
    if type(win).__name__ in DEPARTMENT_WINDOWS:
        if hasattr(app, "embed_later"):
            app.embed_later(win)
    elif hasattr(app, "stand_aside") and app.stand_aside():      # D205
        win.bind("<Destroy>", lambda e: app.come_back() if e.widget is win else None, add="+")


class OfflineDialog(tk.Toplevel):
    """What works without a connection, and one button to prepare the rest."""

    COLOURS = {"ready": T.PASS, "partial": T.SKIP, "missing": T.FAIL}

    def __init__(self, app: NemoApp):
        super().__init__(app)
        self.app, self.job = app, None
        self._poll_job = None
        _dialog(self, app, "Work offline", "940x640+200+40")
        ttk.Label(self, text="Working without a connection", style="PanelH2.TLabel").pack(anchor="w")
        self.summary = ttk.Label(self, text="", style="Panel.TLabel", wraplength=760,
                                 justify="left")
        self.summary.pack(anchor="w", pady=(4, 8))
        self.tree = ttk.Treeview(self, columns=("status", "detail"), show="tree headings",
                                 height=12)
        self.tree.heading("#0", text="Needed", anchor="w")
        self.tree.heading("status", text="Status", anchor="w")
        self.tree.heading("detail", text="Detail", anchor="w")
        self.tree.column("#0", width=270); self.tree.column("status", width=80, stretch=False)
        self.tree.column("detail", width=530)
        for k, c in self.COLOURS.items():
            self.tree.tag_configure(k, foreground=c)
        self.tree.pack(fill="x")
        self.out = tk.Text(self, height=6, wrap="word", relief="flat", bg=T.PANEL,
                           font=app.fonts["mono"], highlightthickness=1,
                           highlightbackground=T.RULE, padx=6, pady=4, state="disabled")
        self.out.pack(fill="both", expand=True, pady=(10, 8))
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.btn_send = ttk.Button(bar, text="Send waiting reviews",
                                   command=lambda: self._run(["review", "send"]))
        self.btn_send.pack(side="right", padx=8)
        self.btn_prep = ttk.Button(bar, text="Prepare for offline", style="Primary.TButton",
                                   command=lambda: self._run(["offline", "prepare"]))
        self.btn_prep.pack(side="left")
        ttk.Label(bar, text="Needs a connection; can take an hour.",
                  style="PanelMuted.TLabel").pack(side="left", padx=10)
        self._say("Progress appears here.")
        self.refresh()

    def refresh(self):
        from ..offline import readiness, summary
        self.tree.delete(*self.tree.get_children())
        items = readiness(self.app.cfg, self.app.library)
        # Every row visible: the last ones -- waiting reviews -- matter most.
        self.tree.configure(height=min(len(items), 16))
        for i in items:
            self.tree.insert("", "end", text=i.name, tags=(i.status,),
                             values=({"ready": "Ready", "partial": "Partly",
                                      "missing": "Needed"}[i.status], i.detail))
        self.summary.config(text=summary(items))

    def _say(self, line):
        self.out.config(state="normal"); self.out.insert("end", line + "\n")
        self.out.see("end"); self.out.config(state="disabled")

    def _run(self, args):
        if self.job and self.job.running:
            return
        self.job = Job(C.nemo_argv(*args)).start()
        self.btn_prep.config(state="disabled"); self.btn_send.config(state="disabled")
        self._poll()

    def _poll(self):
        if not self.winfo_exists():
            return              # belt and braces: see destroy() for the actual fix
        for line in self.job.drain():
            self._say(line)
        if self.job.running:
            self._poll_job = self.after(200, self._poll)
        else:
            self._poll_job = None
            self.btn_prep.config(state="normal"); self.btn_send.config(state="normal")
            self.refresh()

    def destroy(self):
        # The widget's Tcl command
        # is deleted on destroy, but a pending after() timer pointing at it
        # is not cancelled automatically and fires anyway, hitting "invalid
        # command name ..." once it does. Cancel it here instead.
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:                            # noqa: BLE001
                pass
            self._poll_job = None
        super().destroy()


class DatasheetDialog(tk.Toplevel):
    """Search your datasheets offline; link each one to the part it covers."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        self.app = app
        _dialog(self, app, "Datasheets", "900x620+200+50")
        from ..datasheets import Library
        self.lib = Library()
        self.protocol("WM_DELETE_WINDOW", self._close)
        top = ttk.Frame(self, style="Panel.TFrame"); top.pack(fill="x")
        ttk.Label(top, text="Search", style="Panel.TLabel").pack(side="left")
        self.q = ttk.Entry(top, width=36); self.q.pack(side="left", padx=8)
        self.q.bind("<Return>", lambda e: self.search())
        self.parts = ["All datasheets"] + [p.ref for p in sorted(app.library, key=lambda p: p.ref)]
        self.scope = ttk.Combobox(top, state="readonly", values=self.parts, width=28)
        self.scope.set(self.parts[0]); self.scope.pack(side="left")
        ttk.Button(top, text="Search", style="Primary.TButton",
                   command=self.search).pack(side="left", padx=8)

        self.hits = ttk.Treeview(self, columns=("page", "text"), show="tree headings", height=5)
        self.hits.heading("#0", text="Datasheet", anchor="w")
        self.hits.heading("page", text="Page", anchor="w")
        self.hits.heading("text", text="Where it says so", anchor="w")
        self.hits.column("#0", width=190); self.hits.column("page", width=50, stretch=False)
        self.hits.column("text", width=600)
        self.hits.pack(fill="x", pady=(10, 4))
        self.hits.bind("<Double-Button-1>", lambda e: self.open_hit())
        self.hits.bind("<<TreeviewSelect>>", lambda e: self._hit_selected())
        # The passage in full, wrapped: a one-line row cut the answer off
        # at the edge, which is the one thing a search exists to show.
        self.passage = tk.Text(self, height=4, wrap="word", relief="flat", bg="white",
                               font=app.fonts["body"], highlightthickness=1,
                               highlightbackground=T.RULE, padx=8, pady=6)
        self.passage.tag_configure("match", font=app.fonts["strong"], foreground=T.BLUE)
        self.passage.pack(fill="x")
        self.passage.config(state="disabled")
        self.note = ttk.Label(self, text="Search your datasheets by what you want to "
                              "know, such as 'working voltage'.", style="PanelMuted.TLabel")
        self.note.pack(anchor="w", pady=(2, 0))
        self._hits = {}

        ttk.Label(self, text="Your datasheets", style="Panel.TLabel",
                  font=app.fonts["strong"]).pack(anchor="w", pady=(12, 4))
        self.files = ttk.Treeview(self, columns=("pages", "parts", "note"),
                                  show="tree headings", height=5)
        for col, w, t in (("#0", 220, "File"), ("pages", 60, "Pages"),
                          ("parts", 200, "Linked to"), ("note", 360, "Note")):
            self.files.heading(col, text=t, anchor="w")
            self.files.column(col, width=w, stretch=(col == "note"))
        self.files.tag_configure("warn", foreground=T.SKIP)
        self.files.pack(fill="x")
        link = ttk.Frame(self, style="Panel.TFrame"); link.pack(fill="x", pady=8)
        # Packed first, so a narrow window squeezes the other controls, never Close.
        ttk.Button(link, text="Close", command=self._close).pack(side="right")
        ttk.Button(link, text="Add PDFs", command=self.add).pack(side="left", padx=(0, 16))
        ttk.Label(link, text="This datasheet is for", style="Panel.TLabel").pack(side="left")
        self.link_part = ttk.Combobox(link, state="readonly", values=self.parts[1:], width=20)
        self.link_part.pack(side="left", padx=8)
        ttk.Button(link, text="Link", command=self.link).pack(side="left")
        ttk.Button(link, text="Unlink", command=self.unlink).pack(side="left", padx=6)
        # The Datasheet Reader (owner, 2026-11-04; nemo/reader.py).
        ttk.Button(link, text="Draft a part from it", command=self.draft_part).pack(side="left", padx=6)
        self.files.bind("<<TreeviewSelect>>", lambda e: self._file_selected())
        self.refresh()

    def draft_part(self):
        """The Datasheet Reader reads the chosen datasheet into a draft part
        (every figure with its page and words), as a job; Nemo says when."""
        sel = self.files.selection()
        if not sel:
            self.note.config(text="Choose a datasheet in the list first.")
            return
        name = self.files.item(sel[0], "text")
        self.app.start_job(C.nemo_argv("datasheet", "draft", name), "draft_part")
        self.note.config(text=f"The Datasheet Reader is reading {name}. Its draft goes to "
                              "your parts folder's drafts, never straight into the library.")

    def _close(self):
        self.lib.close(); self.destroy()

    def refresh(self):
        self.files.delete(*self.files.get_children())
        sheets = self.lib.sheets()
        if not sheets:
            self.files.insert("", "end", text="Add datasheet PDFs to search them "
                              "offline.")
        for sh in sheets:
            sug = [] if sh.parts else self.lib.suggest_parts(sh.file, self.app.library)
            if sh.status == "no text":
                note = "Scanned: no text to search"
            elif sh.status != "ok":
                note = "Could not be read"
            else:
                note = (f"Looks like {', '.join(sug)}: select it and choose Link"
                        if sug else ("" if sh.parts else "Not linked to a part yet"))
            self.files.insert("", "end", iid=sh.file, text=sh.file,
                              values=(sh.pages, ", ".join(sh.parts), note),
                              tags=("warn",) if (sh.status != "ok" or not sh.parts) else ())

    def _file_selected(self):
        sel = self.files.selection()
        if sel and self.lib.sheets():
            sug = self.lib.suggest_parts(sel[0], self.app.library)
            if sug:
                self.link_part.set(sug[0])

    def add(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(parent=self, title="Add datasheets",
                                            filetypes=[("PDF files", "*.pdf")])
        if not paths:
            return
        self.note.config(text="Reading the PDFs. Large datasheets take a while on "
                         "this laptop.")
        self.update_idletasks()
        added = self.lib.add(paths)
        self.note.config(text=f"Added {len(added)}. Link each one to its part below.")
        self.refresh()

    def search(self):
        scope = self.scope.get()
        ref = None if scope == self.parts[0] else scope
        self.hits.delete(*self.hits.get_children())
        found = self.lib.search(self.q.get(), ref=ref)
        self._hits = {}
        for h in found:
            iid = self.hits.insert("", "end", text=h.file, values=(h.page, h.snippet))
            self._hits[iid] = h
        self._show_passage(None)
        if found:
            first = self.hits.get_children()[0]
            self.hits.selection_set(first); self._hit_selected()
        if not found:
            msg = ("Nothing found" + (f" in datasheets linked to {ref}" if ref else "")
                   + ("." if self.lib.sheets() else ". Add datasheets first."))
            self.note.config(text=msg)
        else:
            n = len(found)
            self.note.config(text=f"{n} place{'s' if n != 1 else ''}. Double-click a "
                             "result to open the PDF, then go to the page shown.")

    def _hit_selected(self):
        sel = self.hits.selection()
        self._show_passage(self._hits.get(sel[0]) if sel else None)

    def _show_passage(self, hit):
        self.passage.config(state="normal"); self.passage.delete("1.0", "end")
        if hit:
            self.passage.insert("end", f"{hit.file}, page {hit.page}:  ")
            for part in re.split(r"(\[[^\]]*\])", hit.snippet):
                if part.startswith("[") and part.endswith("]"):
                    self.passage.insert("end", part[1:-1], "match")
                else:
                    self.passage.insert("end", part)
        self.passage.config(state="disabled")

    def open_hit(self):
        sel = self.hits.selection()
        if sel:
            C.open_path(self.lib.root / self.hits.item(sel[0], "text"))

    def link(self):
        sel, ref = self.files.selection(), self.link_part.get()
        if sel and ref:
            self.lib.link(sel[0], ref); self.refresh()

    def unlink(self):
        sel, ref = self.files.selection(), self.link_part.get()
        if sel and ref:
            self.lib.unlink(sel[0], ref); self.refresh()


class HelpDialog(tk.Toplevel):
    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Help", "900x620+200+50")
        from .. import help as H
        self.H = H
        self.docs = H.available()
        left = ttk.Frame(self, style="Panel.TFrame"); left.pack(side="left", fill="y")
        self.list = tk.Listbox(left, width=28, bg="white", relief="flat",
                               highlightthickness=1, highlightbackground=T.RULE,
                               selectbackground=T.SELECT, selectforeground=T.INK,
                               activestyle="none", font=app.fonts["body"],
                               exportselection=False)
        self.list.pack(fill="y", expand=True)
        for title, _ in self.docs:
            self.list.insert("end", title)
        self.list.bind("<<ListboxSelect>>", lambda e: self.show())
        if H.report():
            ttk.Button(left, text="Open the technical report",
                       command=lambda: C.open_path(H.report())).pack(fill="x", pady=(8, 0))
        ttk.Button(left, text="Close", command=self.destroy).pack(fill="x", pady=(6, 0))
        self.text = tk.Text(self, wrap="word", relief="flat", bg=T.PANEL,
                            font=app.fonts["body"], padx=16, pady=4, highlightthickness=0)
        self.text.pack(side="left", fill="both", expand=True)
        f = app.fonts
        self.text.tag_configure("h1", font=f["title"], spacing1=6, spacing3=6)
        self.text.tag_configure("h2", font=f["h2"], spacing1=10, spacing3=4)
        self.text.tag_configure("h3", font=f["strong"], spacing1=8)
        self.text.tag_configure("code", font=f["mono"], foreground=T.INK2)
        if self.docs:
            self.list.selection_set(0); self.show()
        else:
            self.text.insert("end", "The help documents were not installed with this "
                             "copy of Nemo. They are in the NemoWin or NemoIso folder.")

    def show(self):
        sel = self.list.curselection()
        if not sel:
            return
        self.text.config(state="normal"); self.text.delete("1.0", "end")
        for chunk, style in self.H.segments(self.docs[sel[0]][1].read_text(encoding="utf-8")):
            self.text.insert("end", chunk, style if style != "body" else ())
        self.text.config(state="disabled")


class Doctor(tk.Toplevel):
    def __init__(self, app: NemoApp):
        super().__init__(app)
        self.app = app
        self.title("Check this machine")
        self.geometry("760x540")
        self.configure(bg=T.PANEL, padx=16, pady=14, highlightthickness=1,
                       highlightbackground=T.RULE)
        self.transient(app)
        self._wait_job = None
        ttk.Label(self, text="What Nemo found on this machine",
                  style="PanelH2.TLabel").pack(anchor="w")
        self.text = tk.Text(self, wrap="word", relief="flat", bg=T.PANEL,
                            font=app.fonts["body"], padx=4, pady=8,
                            highlightthickness=0)
        self.text.pack(fill="both", expand=True, pady=(6, 10))
        for tag, col in (("ok", T.PASS), ("warn", T.SKIP), ("fail", T.FAIL),
                         ("info", T.INK2)):
            self.text.tag_configure(tag, foreground=col,
                                    font=app.fonts["strong"])
        self.text.tag_configure("detail", foreground=T.INK2, lmargin1=22,
                                lmargin2=22, spacing3=6)
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.again = ttk.Button(bar, text="Check again", command=self.run)
        self.again.pack(side="right", padx=8)
        self.run()

    def run(self):
        import threading
        self.again.config(state="disabled")
        self.text.config(state="normal"); self.text.delete("1.0", "end")
        self.text.insert("end", "Checking. This takes a few seconds.\n")
        self.text.config(state="disabled")
        box = {}

        def work():
            from ..doctor import run
            try:
                box["f"] = run()
            except Exception as exc:              # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=work, daemon=True); t.start()

        def wait():
            if not self.winfo_exists():
                return             # dialog closed while the check thread was still running
            if t.is_alive():
                self._wait_job = self.after(200, wait); return
            self._wait_job = None
            self.again.config(state="normal")
            self.text.config(state="normal"); self.text.delete("1.0", "end")
            if "e" in box:
                self.text.insert("end", f"The check itself failed: {box['e']}",
                                 "fail")
            else:
                order = {"fail": 0, "warn": 1, "ok": 2, "info": 3}
                word = {"fail": "Needs attention", "warn": "Worth a look",
                        "ok": "Fine", "info": "Note"}
                for f in sorted(box["f"], key=lambda f: order[f.status]):
                    self.text.insert("end", f"{word[f.status]}: {f.title}\n",
                                     f.status)
                    if f.detail:
                        self.text.insert("end", f.detail + "\n", "detail")
            self.text.config(state="disabled")
        wait()

    def destroy(self):
        if self._wait_job:
            try:
                self.after_cancel(self._wait_job)
            except Exception:                            # noqa: BLE001
                pass
            self._wait_job = None
        super().destroy()


class Clinic(tk.Toplevel):
    """The Doctors (owner, 2026-10-21; nemo/clinic.py): what is wrong and
    what to do about it. Looking changes nothing; a finding with a remedy has
    an "Ask the Nurse" button, which shows exactly what would change and
    applies it only on a yes (nemo/nurse.py)."""

    COLOURS = {"needs attention": T.FAIL, "worth a look": T.SKIP}

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Doctors", "780x560+200+70")
        self.app, self._wait_job = app, None
        from tkinter import messagebox
        from .. import clinic, nurse
        self.C, self.N = clinic, nurse
        self.ask = messagebox.askyesno           # tests put a stand-in here
        ttk.Label(self, text="The Doctors", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=740, justify="left", text=(
            "They look at the machine, the models, your projects and the stick, and "
            "advise. Looking changes nothing. Where the Nurse can apply a remedy, you are "
            "shown exactly what it would change first, and it is done only if you say "
            "yes; a copy is kept so it can be undone.")).pack(anchor="w", pady=(2, 6))
        self.text = tk.Text(self, wrap="word", relief="flat", bg=T.PANEL,
                            font=app.fonts["body"], padx=4, pady=8, highlightthickness=0)
        self.text.pack(fill="both", expand=True, pady=(0, 10))
        for sev, col in self.COLOURS.items():
            self.text.tag_configure(sev, foreground=col, font=app.fonts["strong"])
        self.text.tag_configure("detail", foreground=T.INK2, lmargin1=22, lmargin2=22)
        self.text.tag_configure("seen", foreground=T.INK2, lmargin1=36, lmargin2=36,
                                font=app.fonts["small"])
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Case notes", command=self.show_notes).pack(side="right", padx=8)
        ttk.Button(bar, text="Undo the last treatment", command=self.undo_last).pack(side="left")
        ttk.Button(bar, text="Write a report", command=self.write_report).pack(side="left", padx=(8, 0))
        self.note = ttk.Label(bar, style="PanelMuted.TLabel", text="", wraplength=300,
                              justify="left")
        self.note.pack(side="left", padx=10)
        self.again = ttk.Button(bar, text="See the Doctors again", command=self.run)
        self.again.pack(side="right")
        # 2026-11-11: the one look that goes on the network (nemo/toolupdates.py).
        self.newer = ttk.Button(bar, text="Look for newer tools", command=self.look_for_updates)
        self.newer.pack(side="right", padx=8)
        self.run()

    def look_for_updates(self):
        """Each department's tools against their makers' latest releases, kept for
        the Doctors' visits; then the Doctors look again. Nothing is downloaded."""
        import threading
        from .. import toolupdates
        self.newer.config(state="disabled")
        self.again.config(state="disabled")
        self._put(("Looking for newer versions of the departments' tools on the "
                   "makers' sites. Nothing is downloaded.\n", None))
        box = {}

        def work():
            try:
                box["looks"] = toolupdates.look()
                toolupdates.save(box["looks"])
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=work, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._wait_job = self.after(200, wait); return
            self._wait_job = None
            self.newer.config(state="normal")
            if "e" in box:
                self._put((f"The look could not be made: {box['e']}", "needs attention"))
                self.again.config(state="normal")
                return
            self.run()
        wait()

    def _put(self, *parts):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        for text, tag in parts:
            self.text.insert("end", text, tag)
        self.text.config(state="disabled")

    def run(self):
        import threading
        self.again.config(state="disabled")
        self._put(("The Doctors are looking. This takes a few seconds.\n", None))
        box = {}

        def work():
            try:
                box["case"] = self.C.examine(self.app.cfg)
                self.C.record(box["case"])
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=work, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._wait_job = self.after(200, wait); return
            self._wait_job = None
            self.show(box)
        wait()

    def show(self, box: dict):
        self.again.config(state="normal")
        if "e" in box:
            self._put((f"The Doctors could not look: {box['e']}", "needs attention"))
            return
        case = box["case"]
        from ..staff import STAFF
        self._put()
        self.text.config(state="normal")
        if case.healthy:
            self.text.insert("end", "Nothing found that needs attention.\n")
        for f in case.findings:
            self.text.insert("end", f"{f.severity.capitalize()}: {f.what}\n", f.severity)
            self.text.insert("end", f"{STAFF[f.specialist].title}: {f.diagnosis}\n", "detail")
            self.text.insert("end", f"Advice: {f.advice}\n", "detail")
            if f.evidence:
                self.text.insert("end", f.evidence + "\n", "seen")
            if f.remedy:
                b = ttk.Button(self.text, text="Ask the Nurse...",
                               command=lambda f=f: self.treat(f))
                self.text.insert("end", "  ", "detail")
                self.text.window_create("end", window=b)
                self.text.insert("end", "\n")
            self.text.insert("end", "\n")
        for x in case.failed:
            self.text.insert("end", f"Could not look: {x}\n", "worth a look")
        self.text.insert("end", "Looking changed nothing.", "detail")
        self.text.config(state="disabled")

    def treat(self, finding):
        """One remedy: shown in full, applied only on a yes."""
        p = self.N.plan(self.app.cfg, finding)
        if p is None:
            self.note.config(text="There is nothing to treat now: look again.")
            return None
        if not self.ask("The Nurse", self.N.describe(p) + "\n\nDo it?", parent=self):
            self.note.config(text="Not applied. Nothing has changed.")
            return None
        # D205: a backup takes minutes here, and would hold the window still.
        import threading, time
        self.note.config(text="The Nurse is working. Nemo stays open meanwhile.")
        box = {}

        def work():
            try:
                box["rec"] = self.N.treat(self.app.cfg, finding, p.token, p.stamp)
            except self.N.NurseError as exc:
                box["e"] = exc
        t = threading.Thread(target=work, daemon=True); t.start()
        while t.is_alive():
            try:
                self.app.update()
            except tk.TclError:
                return None                  # closed: the Nurse finishes and records it
            time.sleep(0.05)
        if "rec" not in box:
            self.note.config(text=f"Not done: {box.get('e', 'it stopped')}.")
            return None
        rec = box["rec"]
        self.note.config(text=f"Done: {rec['title']}. It can be undone.")
        self.run()
        return rec

    def write_report(self):
        """The Doctors' Writer: a report to read, then send if you wish."""
        try:
            path = self.C.report(self.app.cfg)
        except OSError as exc:
            self.note.config(text=f"No report: {exc}.")
            return None
        self.note.config(text=f"Written: {path.name}. Read it before you send it.")
        C.open_path(path)
        return path

    def undo_last(self):
        open_ones = [t for t in self.N.treatments() if not t["undone"]]
        if not open_ones:
            self.note.config(text="There is no treatment to undo.")
            return None
        rec = open_ones[0]
        if not self.ask("The Nurse", f"Undo '{rec['title']}'? Every file it changed is "
                                      "put back as it was.", parent=self):
            self.note.config(text="Not undone.")
            return None
        try:
            self.N.undo(rec["id"], agreed=True)
        except self.N.NurseError as exc:
            self.note.config(text=f"Not undone: {exc}.")
            return None
        self.note.config(text=f"Undone: {rec['title']}.")
        self.run()
        return rec

    def show_notes(self):
        import datetime as dt
        visits = self.C.past(30)
        lines = [(f"{dt.datetime.fromtimestamp(v.get('at', 0)):%d %b %H:%M}  "
                  f"{len(v.get('findings', []))} finding(s)\n", None) for v in visits]
        done = [(f"{dt.datetime.fromtimestamp(t['at']):%d %b %H:%M}  {t['title']}"
                 + (" (undone)" if t["undone"] else "") + "\n", None)
                for t in self.N.treatments()[:30]]
        self._put(("Visits, newest first\n\n", "worth a look"),
                  *(lines or [("No visits yet.\n", None)]),
                  ("\nTreatments, newest first\n\n", "worth a look"),
                  *(done or [("None yet.\n", None)]))

    def destroy(self):
        # docs/design-rules.md, mistake 2: a pending after() outlives its widget.
        if self._wait_job:
            try:
                self.after_cancel(self._wait_job)
            except Exception:                                    # noqa: BLE001
                pass
            self._wait_job = None
        super().destroy()


class ArtClerk(tk.Toplevel):
    """The Art Studio's Clerk asking: which kind of thing, and its sizes."""

    def __init__(self, parent):
        super().__init__(parent)
        from .. import artstudio
        self.A, self.result = artstudio, None
        self.title("From a list")
        self.transient(parent)
        self.kind = ttk.Combobox(self, state="readonly", width=40,
                                 values=[f"{k.title}: {k.about}" for k in artstudio.KINDS.values()])
        self.kind.pack(fill="x", padx=10, pady=(10, 6))
        self.kind.bind("<<ComboboxSelected>>", lambda e: self.show())
        self.form = ttk.Frame(self); self.form.pack(fill="x", padx=10)
        bar = ttk.Frame(self); bar.pack(fill="x", padx=10, pady=10)
        ttk.Button(bar, text="Use these", style="Primary.TButton", command=self.ok).pack(side="right")
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        self.kind.current(0); self.show()
        app = self.winfo_toplevel().master                       # D205
        moved = hasattr(app, "stand_aside") and app.stand_aside()
        self.grab_set(); self.wait_window()
        if moved:
            app.come_back()

    def show(self):
        for w in self.form.winfo_children():
            w.destroy()
        key = list(self.A.KINDS)[self.kind.current()]
        self.entries = {}
        for r, f in enumerate(self.A.KINDS[key].fields):
            ttk.Label(self.form, text=f.label).grid(row=r, column=0, sticky="w", pady=2)
            e = ttk.Entry(self.form, width=24); e.grid(row=r, column=1, padx=6)
            v = self.A.last(key)[f.key]
            e.insert(0, v if isinstance(v, str) else f"{v:g}")
            self.entries[f.key] = e

    def ok(self):
        key = list(self.A.KINDS)[self.kind.current()]
        self.result = (key, {k: e.get() for k, e in self.entries.items()})
        self.destroy()


class ArtStudio(tk.Toplevel):
    """The Art Studio's Designer and Editor (owner, 2026-10-21;
    nemo/modelkit.py): a 3D model from a kit of shapes, built by code and
    checked for printing."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Art Studio", "860x600+170+50")
        from .. import modelkit
        self.app, self.K, self.shapes, self._job = app, modelkit, [], None
        ttk.Label(self, text="Art Studio: a model to print", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=820, justify="left", text=(
            "Add shapes one at a time; each is added to the model or cut from it. Sizes in mm; "
            "'at' is x y z of the middle of the shape's foot. It makes plain solids: stands, "
            "plaques, holders, simple replicas; not faces or figures.")).pack(anchor="w", pady=(2, 6))
        top = ttk.Frame(self, style="Panel.TFrame"); top.pack(fill="x")
        ttk.Label(top, text="Name", style="PanelMuted.TLabel").pack(side="left")
        self.name = ttk.Entry(top, width=30); self.name.pack(side="left", padx=6)

        form = ttk.Frame(self, style="Panel.TFrame"); form.pack(fill="x", pady=(8, 0))
        self.kind = ttk.Combobox(form, state="readonly", width=12, values=list(modelkit.SHAPES))
        self.kind.set("box"); self.kind.grid(row=1, column=0, padx=(0, 6))
        self.kind.bind("<<ComboboxSelected>>", lambda e: self._hint())
        ttk.Label(form, text="Shape", style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.fields = {}
        for col, (key, label, width) in enumerate((("dims", "Sizes", 26), ("at", "At x y z", 12),
                                                    ("rotate", "Turn x y z", 10)), 1):
            ttk.Label(form, text=label, style="PanelMuted.TLabel").grid(row=0, column=col, sticky="w")
            e = ttk.Entry(form, width=width); e.grid(row=1, column=col, padx=(0, 6))
            self.fields[key] = e
        self.fields["at"].insert(0, "0 0 0"); self.fields["rotate"].insert(0, "0 0 0")
        self.op = ttk.Combobox(form, state="readonly", width=5, values=["add", "cut"])
        self.op.set("add"); self.op.grid(row=1, column=4, padx=(0, 6))
        ttk.Label(form, text="Add/cut", style="PanelMuted.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Button(form, text="Add shape", command=self.add_shape).grid(row=1, column=5)
        self.hint = ttk.Label(self, style="PanelMuted.TLabel", text="")
        self.hint.pack(anchor="w", pady=(2, 4))

        mid = ttk.Frame(self, style="Panel.TFrame"); mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=("n", "shape", "op", "sizes", "at"),
                                 show="headings", height=7)
        for col, w, text in (("n", 30, "#"), ("shape", 100, "Shape"), ("op", 50, "Add/cut"),
                             ("sizes", 330, "Sizes"), ("at", 150, "At")):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=w, stretch=(col == "sizes"), anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        self.picture = ttk.Label(mid, style="Panel.TLabel")
        self.picture.pack(side="right", padx=(8, 0))

        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Remove shape", command=self.remove_shape).pack(side="left")
        ttk.Button(row, text="From a list...", command=self.from_list).pack(side="left", padx=(8, 0))
        self.btn_build = ttk.Button(row, text="Build and check", style="Primary.TButton",
                                    command=self.build)
        self.btn_build.pack(side="left", padx=8)
        ttk.Button(row, text="Queue it", command=self.queue_it).pack(side="left")
        ttk.Button(row, text="Card...", command=self.write_card).pack(side="left", padx=(8, 0))
        # Too long one way for the printer: cut into pieces, pinned (nemo/joints.py).
        self.btn_split = ttk.Button(row, text="Split to fit", command=self.split, state="disabled")
        self.btn_split.pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        self.made_from = None
        self.built_name = None
        self.result = tk.Text(self, height=7, wrap="word", relief="flat", bg=T.PANEL,
                              font=app.fonts["small"], highlightthickness=0)
        self.result.pack(fill="x", pady=(6, 0))
        self._hint()

    def _hint(self):
        k = self.kind.get()
        need = [n for n in self.K.SHAPES[k] if n != "text"]
        extra = " (and the letters in the next box)" if k == "text" else ""
        self.hint.config(text=f"Sizes for a {k}: " + ", ".join(
            "x y z" if n == "size" and k in ("box", "rounded_box") else
            "x y" if n == "size" and k == "plate" else n for n in need) + extra)

    def _nums(self, text: str) -> list[float]:
        return [float(x) for x in text.replace(",", " ").split()]

    def shape_from_form(self) -> dict:
        k = self.kind.get()
        raw = self.fields["dims"].get().strip()
        s = {"shape": k, "op": self.op.get(), "at": self._nums(self.fields["at"].get()),
             "rotate": self._nums(self.fields["rotate"].get())}
        if k == "text":
            letters, _, nums = raw.rpartition(" ")
            letters, _, size = letters.rpartition(" ")
            s.update(text=letters, size=float(size), depth=float(nums))
            return s
        nums = self._nums(raw)
        keys = self.K.SHAPES[k]
        if k in ("box", "rounded_box"):
            s["size"], rest = nums[:3], nums[3:]
        elif k == "plate":
            s["size"], rest = nums[:2], nums[2:]
        else:
            rest = nums
        for key in [x for x in keys if x != "size"]:
            s[key] = rest.pop(0)
        return s

    def add_shape(self):
        try:
            shape = self.shape_from_form()
            self.K.validate({"name": self.name.get() or "check", "shapes": self.shapes + [shape]})
        except (ValueError, IndexError) as exc:
            self.hint.config(text=f"Not added: {exc or 'give every size as a number'}.")
            return
        self.shapes.append(shape)
        self.refresh()

    def remove_shape(self):
        sel = self.tree.selection()
        if sel:
            del self.shapes[int(sel[0])]
            self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.shapes):
            sizes = ", ".join(f"{k} {s[k]}" for k in self.K.SHAPES[s["shape"]])
            self.tree.insert("", "end", iid=str(i), values=(i + 1, s["shape"], s["op"], sizes,
                                                            " ".join(f"{v:g}" for v in s["at"])))

    def from_list(self, kind: str | None = None, answers=None) -> bool:
        """The Clerk: pick a kind and its sizes; its shapes replace the list.
        `answers` (a dict) stands in for the form, for tests."""
        from .. import artstudio
        if answers is None:
            got = ArtClerk(self).result
            if not got:
                return False
            kind, answers = got
        try:
            name = self.name.get().strip() or artstudio.KINDS[kind].title
            doc = artstudio.request(name, kind, answers,
                                    float(self.app.cfg.get("hardware.min_wall_mm", 1.2)))
        except (ValueError, KeyError) as exc:
            self._say(f"Clerk: not made: {exc}.")
            return False
        self.name.delete(0, "end"); self.name.insert(0, name)
        # validated: every shape then has its op, at and rotate for the list
        self.shapes, self.made_from = self.K.validate(doc).shapes, doc["from"]
        self.refresh()
        self._say(f"Clerk: a {artstudio.KINDS[kind].title.lower()} as {len(self.shapes)} shape(s). "
                  "Build and check it, or change the shapes first.")
        return True

    def _doc(self) -> dict:
        doc = {"name": self.name.get().strip(), "shapes": self.shapes}
        if self.made_from:
            doc["from"] = self.made_from
        return doc

    def queue_it(self):
        """The Foreman: build it later, with the rest of the queue."""
        from .. import foreman
        try:
            job = foreman.model_job(self._doc())
        except ValueError as exc:
            self._say(f"Not queued: {exc}."); return
        foreman.add([job])
        self._say(f"Foreman: {job.owner} is queued ({len(foreman.load())} job(s) in all). "
                  "Run the queue with `nemo queue run`.")

    def write_card(self, ask=None):
        """The Writer: a title and a line for the model, then its card."""
        from .. import artstudio
        from tkinter import simpledialog
        ask = ask or (lambda title, prompt, initial: simpledialog.askstring(
            title, prompt, initialvalue=initial, parent=self))
        name = self.name.get().strip()
        try:
            out = self.K.folder(self.app.cfg, name)
        except ValueError as exc:
            self._say(f"Writer: {exc}."); return None
        if not (out / "spec.json").is_file():
            self._say("Writer: build it first; the card is written from what was made."); return None
        a = artstudio.about(out)
        title = ask("Card", "Title:", a.get("title", name))
        if title is None:
            return None
        line = ask("Card", "A line about it:", a.get("line", ""))
        if line is None:
            return None
        artstudio.write_about(out, title, line)
        text = artstudio.card(out)
        self._say(text)
        return text

    def build(self):
        import threading
        doc = self._doc()
        try:
            self.K.validate(doc)
        except ValueError as exc:
            self._say(f"Not built: {exc}.")
            return
        self.btn_build.config(state="disabled")
        self._say("The Designer is building it; CadQuery takes about half a minute here...")
        box = {}

        def work():
            try:
                box["out"] = self.K.build(self.app.cfg, doc)
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=work, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._job = self.after(300, wait); return
            self._job = None
            self.built(box)
        wait()

    def built(self, box: dict):
        self.btn_build.config(state="normal")
        if "e" in box:
            self._say(f"Not built: {box['e']}.")
            return
        out, results = box["out"]
        lines = [f"[{r.status}] {r.name}: {r.detail}" for r in results]
        ok = all(r.status != "FAIL" for r in results)
        lines.append(("The Editor passed it. " if ok else "The Editor found a problem. ")
                     + f"Files: {out}")
        fits = next((r for r in results if r.name == "fits_printer"), None)
        splittable = bool(fits and fits.status == "FAIL" and any("split" in i for i in fits.items))
        self.built_name = self._doc().get("name") if splittable else None
        self.btn_split.config(state="normal" if splittable else "disabled")
        if splittable:
            lines.append("Too long for the printer: Split to fit cuts it into pieces that fit, "
                         "with pins to join them.")
        self._say("\n".join(lines))
        png = out / "model-iso.png"
        if png.is_file():
            self._img = tk.PhotoImage(file=str(png)).subsample(2, 2)
            self.picture.config(image=self._img)

    def split(self):
        import threading
        from .. import joints
        name = self.built_name
        if not name:
            return
        self.btn_split.config(state="disabled"); self.btn_build.config(state="disabled")
        self._say("The Designer is cutting it into pieces and finding room for pins...")
        box = {}

        def work():
            try:
                box["out"] = joints.split(self.app.cfg, name)
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=work, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._job = self.after(300, wait); return
            self._job = None
            self.btn_build.config(state="normal")
            if "e" in box:
                self._say(f"Not split: {box['e']}.")
                return
            out, results, _ = box["out"]
            lines = [f"[{r.status}] {r.name}: {r.detail}" for r in results]
            lines += [f"    {i}" for r in results for i in r.items]
            lines.append(f"Pieces and pins in {out / 'pieces'}; ASSEMBLY.txt says how they go "
                         "together. The Print Shop lists each one to slice.")
            self._say("\n".join(lines))
        wait()

    def _say(self, text: str):
        self.result.config(state="normal"); self.result.delete("1.0", "end")
        self.result.insert("end", text); self.result.config(state="disabled")

    def destroy(self):
        # docs/design-rules.md, mistake 2: a pending after() outlives its widget.
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:                                    # noqa: BLE001
                pass
            self._job = None
        super().destroy()


class Theatre(tk.Toplevel):
    """The Theatre (owner, 2026-10-21; nemo/theatre.py, nemo/cast.py): the
    Projectionist's videos and the Photo Curator's pictures, here or on the
    Chromecast, and the Streamer's Chrome for websites."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Theatre", "840x560+180+60")
        from .. import cast, storeroom, theatre
        self.app, self.T, self.cast = app, theatre, cast
        self.devices, self.session, self._find_job, self._cast_job = [], None, None, None
        storeroom.make_shelves(app.cfg.path("paths.storeroom"))
        ttk.Label(self, text="Theatre", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=800, justify="left", text=(
            "Videos and pictures from the Storeroom's shelves (videos, pictures), with story "
            "covers and concept drawings. Play one here, or cast it to a Chromecast on the "
            "same network.")).pack(anchor="w", pady=(2, 6))
        mid = ttk.Frame(self, style="Panel.TFrame"); mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=("kind", "name", "source", "cast"),
                                 show="headings", height=12)
        for col, w, text in (("kind", 70, "Kind"), ("name", 380, "Name"),
                             ("source", 120, "From"), ("cast", 90, "Castable")):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=w, stretch=(col == "name"), anchor="w")
        self.tree.pack(fill="both", expand=True)

        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Play here", command=self.play_here).pack(side="left")
        ttk.Button(row, text="Find Chromecasts", command=self.find).pack(side="left", padx=(16, 4))
        self.device_box = ttk.Combobox(row, state="readonly", width=22, values=[])
        self.device_box.pack(side="left")
        self.btn_cast = ttk.Button(row, text="Cast", command=self.cast_it, state="disabled")
        self.btn_cast.pack(side="left", padx=4)
        self.btn_pause = ttk.Button(row, text="Pause", command=self.pause, state="disabled")
        self.btn_pause.pack(side="left")
        self.btn_stop = ttk.Button(row, text="Stop", command=self.stop_cast, state="disabled")
        self.btn_stop.pack(side="left", padx=4)

        web = ttk.Frame(self, style="Panel.TFrame"); web.pack(fill="x", pady=(10, 0))
        ttk.Label(web, text="Website", style="PanelMuted.TLabel").pack(side="left")
        self.url = ttk.Entry(web, width=40); self.url.pack(side="left", padx=6)
        ttk.Button(web, text="Open Chrome", command=self.stream).pack(side="left")
        ttk.Button(web, text="Title and line...", command=self.write_caption).pack(side="left", padx=8)
        ttk.Button(web, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=800,
                              justify="left")
        self.note.pack(anchor="w", pady=(6, 0))
        self.refresh()

    def refresh(self):
        self.items = self.T.videos(self.app.cfg) + self.T.photos(self.app.cfg)
        self.tree.delete(*self.tree.get_children())
        for n, i in enumerate(self.items):
            self.tree.insert("", "end", iid=str(n), values=(
                i.kind, i.name, i.source, "yes" if i.castable else "no"))
        if not self.items:
            self.note.config(text="Nothing yet: put videos and pictures on the Storeroom's "
                                  "videos and pictures shelves.")

    def chosen(self):
        sel = self.tree.selection()
        if not sel:
            self.note.config(text="Choose a video or picture first.")
            return None
        return self.items[int(sel[0])]

    def write_caption(self, ask=None):
        """The Writer: a title and a line for the chosen video or picture."""
        from tkinter import simpledialog
        ask = ask or (lambda title, prompt, initial: simpledialog.askstring(
            title, prompt, initialvalue=initial, parent=self))
        item = self.chosen()
        if item is None:
            return None
        title, line = self.T.caption(self.app.cfg, item)
        new_title = ask("Title", "Its title:", title)
        if new_title is None:
            return None
        new_line = ask("A line about it", "A line about it (or leave empty):", line) or ""
        self.T.write_caption(self.app.cfg, item, new_title, new_line)
        self.note.config(text=f"Writer: {new_title}" + (f": {new_line}" if new_line else "") + ".")
        return new_title

    def play_here(self):
        item = self.chosen()
        if item:
            try:
                self.note.config(text=f"Playing {item.name} with {self.T.play_here(item)}.")
            except (OSError, RuntimeError) as exc:
                self.note.config(text=f"It could not be played here: {exc}.")

    def find(self):
        import threading
        self.note.config(text="Looking for Chromecasts on this network (about 8 s)...")
        box = {}

        def work():
            try:
                box["found"] = self.cast.find()
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=work, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._find_job = self.after(200, wait); return
            self._find_job = None
            self.found(box)
        wait()

    def found(self, box: dict):
        if "e" in box:
            self.note.config(text=f"Could not look for Chromecasts: {box['e']}.")
            return
        self.devices = box["found"]
        names = [d.cast_info.friendly_name for d in self.devices]
        self.device_box.config(values=names)
        if names:
            self.device_box.set(names[0])
            self.btn_cast.config(state="normal")
            self.note.config(text=f"Found {len(names)}: {', '.join(names)}.")
        else:
            self.note.config(text="No Chromecast found. It must be switched on and on the same "
                                  "network as this computer.")

    def cast_it(self):
        item = self.chosen()
        device = next((d for d in self.devices
                       if d.cast_info.friendly_name == self.device_box.get()), None)
        if not item or device is None:
            return
        self.stop_cast()
        from .. import theatre
        ok, lines = theatre.check(item, getattr(device.cast_info, "model_name", None))
        try:
            self.session = self.cast.Session(device, item.path)
        except self.cast.CastError as exc:
            self.note.config(text=f"Not cast: {exc}.")
            return
        self.btn_pause.config(state="normal", text="Pause")
        self.btn_stop.config(state="normal")
        warn = "" if ok else " Projectionist: " + " ".join(lines[1:] or lines)
        self.note.config(text=f"Casting {item.name} to {self.device_box.get()}." + warn)
        self._watch_cast()

    def _watch_cast(self):
        """A video that ends, or someone else taking the Chromecast, lets it
        go by itself (cast.Session.release); the window then says so."""
        s = self.session
        if s is None:
            self._cast_job = None
            return
        if s.released:
            self._cast_job = None
            self.session = None
            self.btn_pause.config(state="disabled", text="Pause")
            self.btn_stop.config(state="disabled")
            self.note.config(text={"FINISHED": "It finished; the Chromecast is let go.",
                                   "INTERRUPTED": "Someone else is casting now; Nemo has stepped away.",
                                   "ERROR": "The Chromecast could not play it; it is let go."
                                   }.get(s.ended, "The Chromecast is let go."))
            return
        self._cast_job = self.after(2000, self._watch_cast)

    def pause(self):
        if not self.session:
            return
        if self.btn_pause.cget("text") == "Pause":
            self.session.pause(); self.btn_pause.config(text="Resume")
        else:
            self.session.resume(); self.btn_pause.config(text="Pause")

    def stop_cast(self):
        if self.session:
            try:
                self.session.stop()
            except Exception:                                    # noqa: BLE001
                pass
            self.session = None
            self.note.config(text="Casting stopped; the Chromecast is let go.")
        self.btn_pause.config(state="disabled", text="Pause")
        self.btn_stop.config(state="disabled")

    def stream(self):
        try:
            which = self.T.stream(self.url.get().strip())
        except RuntimeError as exc:
            self.note.config(text=f"{exc}.")
            return
        self.note.config(text=f"Opened {which}. To cast the page, use its menu, Cast.")

    def destroy(self):
        # docs/design-rules.md, mistake 2; and a cast still lending a file stops with the window.
        for name in ("_find_job", "_cast_job"):
            job = getattr(self, name)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:                                # noqa: BLE001
                    pass
                setattr(self, name, None)
        self.stop_cast()
        super().destroy()


class MusicRoom(tk.Toplevel):
    """The Music Room (owner, 2026-10-21; nemo/music.py): the Player plays
    here, the DJ casts a list to the Chromecast, the Writer keeps playlists."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Music Room", "860x580+170+50")
        from .. import cast, music, storeroom
        self.app, self.M, self.cast = app, music, cast
        self.devices, self.queue, self._find_job, self._watch_job = [], None, None, None
        storeroom.make_shelves(app.cfg.path("paths.storeroom"))
        ttk.Label(self, text="Music Room", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=820, justify="left", text=(
            "Your music on the Storeroom's music shelf (folders as Artist / Album / track). "
            "Choose one or more tracks, or a playlist, then play them here or cast them.")
                  ).pack(anchor="w", pady=(2, 6))
        mid = ttk.Frame(self, style="Panel.TFrame"); mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=("title", "artist", "album", "cast"),
                                 show="headings", height=12, selectmode="extended")
        for col, w, text in (("title", 300, "Track"), ("artist", 170, "Artist"),
                             ("album", 170, "Album"), ("cast", 70, "Castable")):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=w, stretch=(col == "title"), anchor="w")
        self.tree.pack(fill="both", expand=True)

        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Play here", command=self.play_here).pack(side="left")
        ttk.Button(row, text="Find Chromecasts", command=self.find).pack(side="left", padx=(16, 4))
        self.device_box = ttk.Combobox(row, state="readonly", width=20, values=[])
        self.device_box.pack(side="left")
        self.btn_cast = ttk.Button(row, text="Cast", command=self.cast_them, state="disabled")
        self.btn_cast.pack(side="left", padx=4)
        self.btn_next = ttk.Button(row, text="Next", command=self.next_track, state="disabled")
        self.btn_next.pack(side="left")
        self.btn_stop = ttk.Button(row, text="Stop", command=self.stop_cast, state="disabled")
        self.btn_stop.pack(side="left", padx=4)

        pl = ttk.Frame(self, style="Panel.TFrame"); pl.pack(fill="x", pady=(8, 0))
        ttk.Label(pl, text="Playlist", style="PanelMuted.TLabel").pack(side="left")
        self.pl_name = ttk.Combobox(pl, width=24, values=[p.stem for p in music.playlists(app.cfg)])
        self.pl_name.pack(side="left", padx=6)
        ttk.Button(pl, text="Save the chosen as a playlist", command=self.save_playlist).pack(side="left")
        ttk.Button(pl, text="Choose its tracks", command=self.load_playlist).pack(side="left", padx=6)
        ttk.Button(pl, text="Open the music shelf", command=lambda: C.open_path(music.shelf(app.cfg))
                   ).pack(side="left")
        ttk.Button(pl, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=820, justify="left")
        self.note.pack(anchor="w", pady=(6, 0))
        self.refresh()

    def refresh(self):
        self.tracks = self.M.tracks(self.app.cfg)
        self.tree.delete(*self.tree.get_children())
        for n, t in enumerate(self.tracks):
            self.tree.insert("", "end", iid=str(n), values=(t.title, t.artist, t.album,
                                                           "yes" if t.castable else "no"))
        if not self.tracks:
            self.note.config(text="No music yet: Open the music shelf and put your music there.")

    def chosen(self):
        sel = [self.tracks[int(i)] for i in self.tree.selection()]
        if not sel:
            self.note.config(text="Choose one or more tracks first.")
        return sel

    def play_here(self):
        sel = self.chosen()
        if sel:
            try:
                self.note.config(text=f"Player: {len(sel)} track(s) with {self.M.play_here(sel)}.")
            except (OSError, RuntimeError, ValueError) as exc:
                self.note.config(text=f"Not played: {exc}.")

    def find(self):
        import threading
        self.note.config(text="Looking for Chromecasts on this network (about 8 s)...")
        box = {}

        def work():
            try:
                box["found"] = self.cast.find()
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=work, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._find_job = self.after(200, wait); return
            self._find_job = None
            self.found(box)
        wait()

    def found(self, box: dict):
        if "e" in box:
            self.note.config(text=f"Could not look for Chromecasts: {box['e']}.")
            return
        self.devices = box["found"]
        names = [d.cast_info.friendly_name for d in self.devices]
        self.device_box.config(values=names)
        if names:
            self.device_box.set(names[0]); self.btn_cast.config(state="normal")
            self.note.config(text=f"Found {len(names)}: {', '.join(names)}.")
        else:
            self.note.config(text="No Chromecast found on this network.")

    def cast_them(self):
        sel = self.chosen()
        device = next((d for d in self.devices
                       if d.cast_info.friendly_name == self.device_box.get()), None)
        if not sel or device is None:
            return
        self.stop_cast()
        try:
            self.queue = self.cast.Queue(device, [t.path for t in sel])
        except self.cast.CastError as exc:
            self.note.config(text=f"DJ: not cast: {exc}.")
            return
        self.btn_next.config(state="normal"); self.btn_stop.config(state="normal")
        self._watch()

    def _watch(self):
        q = self.queue
        if q is None:
            return
        if q.released:
            self.queue = None
            self.btn_next.config(state="disabled"); self.btn_stop.config(state="disabled")
            self.note.config(text={"FINISHED": "DJ: the list has finished; the Chromecast is let go.",
                                   "INTERRUPTED": "Someone else is casting now; the DJ stepped away."
                                   }.get(q.ended, "DJ: stopped; the Chromecast is let go."))
            self._watch_job = None
            return
        cur = q.current
        self.note.config(text=f"DJ: playing {cur.stem if cur else ''} "
                              f"({q.index + 1} of {len(q.paths)}) on {self.device_box.get()}.")
        self._watch_job = self.after(1500, self._watch)

    def next_track(self):
        if self.queue:
            import threading
            threading.Thread(target=self.queue.next, daemon=True).start()

    def stop_cast(self):
        if self.queue:
            try:
                self.queue.stop()
            except Exception:                                    # noqa: BLE001
                pass

    def save_playlist(self):
        sel = self.chosen()
        if not sel:
            return
        try:
            p = self.M.save_playlist(self.app.cfg, self.pl_name.get(), sel)
        except ValueError as exc:
            self.note.config(text=f"Writer: {exc}.")
            return
        self.pl_name.config(values=[x.stem for x in self.M.playlists(self.app.cfg)])
        self.note.config(text=f"Writer: saved {p.name} with {len(sel)} track(s).")

    def load_playlist(self):
        p = next((x for x in self.M.playlists(self.app.cfg) if x.stem == self.pl_name.get()), None)
        if p is None:
            self.note.config(text="Choose a playlist first.")
            return
        wanted = {t.path for t in self.M.load_playlist(self.app.cfg, p)}
        self.tree.selection_set([str(n) for n, t in enumerate(self.tracks) if t.path in wanted])
        self.note.config(text=f"{len(wanted)} track(s) from {p.stem} chosen.")

    def destroy(self):
        # docs/design-rules.md, mistake 2; and a list still being cast stops with the window.
        for name in ("_find_job", "_watch_job"):
            job = getattr(self, name)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:                                # noqa: BLE001
                    pass
                setattr(self, name, None)
        self.stop_cast()
        super().destroy()


class AudioRoom(tk.Toplevel):
    """The Audio department (owner, 2026-10-21; nemo/audio.py): the Narrator,
    the Recorder, the Sound Engineer and the listening shelf."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Audio", "880x640+160+40")
        from .. import audio, cast, storeroom
        from . import prompt_logic
        self.app, self.A, self.cast = app, audio, cast
        self.rec, self.session, self.devices, self._jobs = None, None, [], {}
        storeroom.make_shelves(app.cfg.path("paths.storeroom"))
        ttk.Label(self, text="Audio", style="PanelH2.TLabel").pack(anchor="w")

        nar = ttk.Frame(self, style="Panel.TFrame"); nar.pack(fill="x", pady=(6, 0))
        ttk.Label(nar, text="Narrator: read a story aloud", style="PanelMuted.TLabel").pack(side="left")
        self.stories = {s["name"]: s["path"] for s in prompt_logic.list_stories(app.cfg.path("paths.stories"))}
        self.story = ttk.Combobox(nar, state="readonly", width=28, values=list(self.stories))
        self.story.pack(side="left", padx=6)
        self.btn_read = ttk.Button(nar, text="Make the audiobook", command=self.narrate)
        self.btn_read.pack(side="left")

        rec = ttk.Frame(self, style="Panel.TFrame"); rec.pack(fill="x", pady=(6, 0))
        ttk.Label(rec, text="Recorder: name", style="PanelMuted.TLabel").pack(side="left")
        self.rec_name = ttk.Entry(rec, width=24); self.rec_name.pack(side="left", padx=6)
        self.btn_rec = ttk.Button(rec, text="Record", command=self.toggle_record)
        self.btn_rec.pack(side="left")

        sd = ttk.Frame(self, style="Panel.TFrame"); sd.pack(fill="x", pady=(6, 0))
        ttk.Label(sd, text="Sound Engineer: card", style="PanelMuted.TLabel").pack(side="left")
        self.card = ttk.Entry(sd, width=18); self.card.pack(side="left", padx=6)
        ttk.Button(sd, text="Choose sounds and ready the card...", command=self.ready_card
                   ).pack(side="left")

        ttk.Label(self, text="Listening shelf", style="PanelMuted.TLabel").pack(anchor="w", pady=(10, 0))
        mid = ttk.Frame(self, style="Panel.TFrame"); mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=("title", "kind", "place"), show="headings", height=9)
        for col, w, text in (("title", 480, "Title"), ("kind", 110, "Kind"), ("place", 120, "Reached")):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=w, stretch=(col == "title"), anchor="w")
        self.tree.pack(fill="both", expand=True)
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Play here", command=self.play_here).pack(side="left")
        ttk.Button(row, text="Find Chromecasts", command=self.find).pack(side="left", padx=(16, 4))
        self.device_box = ttk.Combobox(row, state="readonly", width=20, values=[])
        self.device_box.pack(side="left")
        self.btn_cast = ttk.Button(row, text="Cast", command=self.cast_it, state="disabled")
        self.btn_cast.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(row, text="Stop", command=self.stop_cast, state="disabled")
        self.btn_stop.pack(side="left")
        ttk.Button(row, text="Open the audio shelf", command=lambda: C.open_path(audio.shelf(app.cfg))
                   ).pack(side="left", padx=8)
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=840, justify="left")
        self.note.pack(anchor="w", pady=(6, 0))
        self.refresh()

    def refresh(self):
        self.items = self.A.listening(self.app.cfg)
        self.tree.delete(*self.tree.get_children())
        for n, it in enumerate(self.items):
            at = self.A.place(self.app.cfg, it.path)
            self.tree.insert("", "end", iid=str(n), values=(
                it.title, it.kind, f"{int(at // 60)}:{int(at % 60):02d}" if at else ""))

    def _run(self, name, work, done):
        """`work` in a thread; `done(box)` here when it ends (timer tracked)."""
        import threading
        box = {}

        def go():
            try:
                box["out"] = work()
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=go, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._jobs[name] = self.after(250, wait); return
            self._jobs.pop(name, None)
            done(box)
        wait()

    def narrate(self):
        name = self.story.get()
        if not name:
            self.note.config(text="Choose a story first."); return
        self.btn_read.config(state="disabled")
        self.note.config(text=f"Narrator: reading {name} aloud into files...")

        def done(box):
            self.btn_read.config(state="normal")
            if "e" in box:
                self.note.config(text=f"Narrator: {box['e']}.")
            else:
                self.note.config(text=f"Narrator: the audiobook is in {box['out']}.")
                self.refresh()
        self._run("narrate", lambda: self.A.narrate(self.app.cfg, self.stories[name],
                                                    say=lambda s: None), done)

    def toggle_record(self):
        if self.rec is None:
            try:
                self.rec = self.A.Recording(self.app.cfg)
                self.rec.start()
            except Exception as exc:                            # noqa: BLE001
                self.rec = None
                self.note.config(text=f"Recorder: {exc}."); return
            self.btn_rec.config(text="Stop recording")
            self.note.config(text="Recorder: recording...")
            return
        rec, self.rec = self.rec, None
        self.btn_rec.config(text="Record")
        try:
            path, said = rec.stop(self.rec_name.get())
        except Exception as exc:                                # noqa: BLE001
            self.note.config(text=f"Recorder: {exc}."); return
        self.note.config(text=f"Recorder: {said}; kept as {path.name}.")
        self.refresh()

    def ready_card(self, files=None):
        if files is None:
            from tkinter import filedialog
            files = filedialog.askopenfilenames(parent=self, title="The sounds, in order")
        if not files:
            return None
        try:
            out, problems = self.A.ready_sd_card(self.app.cfg, self.card.get(), list(files))
        except ValueError as exc:
            self.note.config(text=f"Sound Engineer: {exc}."); return None
        self.note.config(text=f"Sound Engineer: {len(files)} sound(s) ready in {out}"
                              + (". Notes: " + "; ".join(problems) if problems else
                                 "; copy its numbered folders to the card."))
        return out

    def chosen(self):
        sel = self.tree.selection()
        if not sel:
            self.note.config(text="Choose something on the listening shelf first.")
            return None
        return self.items[int(sel[0])]

    def play_here(self):
        it = self.chosen()
        if it:
            from .. import music
            self.note.config(text=f"{it.title}: playing with {music.play_here([it])} "
                                  "(VLC offers to continue where you left off).")

    def find(self):
        self.note.config(text="Looking for Chromecasts on this network (about 8 s)...")

        def done(box):
            if "e" in box:
                self.note.config(text=f"Could not look for Chromecasts: {box['e']}."); return
            self.devices = box["out"]
            names = [d.cast_info.friendly_name for d in self.devices]
            self.device_box.config(values=names)
            if names:
                self.device_box.set(names[0]); self.btn_cast.config(state="normal")
            self.note.config(text=f"Found: {', '.join(names) or 'none'}.")
        self._run("find", self.cast.find, done)

    def cast_it(self):
        it = self.chosen()
        device = next((d for d in self.devices
                       if d.cast_info.friendly_name == self.device_box.get()), None)
        if not it or device is None:
            return
        self.stop_cast()
        at = self.A.place(self.app.cfg, it.path)
        try:
            self.session = self.cast.Session(device, it.path, start_at=at)
        except self.cast.CastError as exc:
            self.note.config(text=f"Not cast: {exc}."); return
        self.cast_item = it
        self.btn_stop.config(state="normal")
        self.note.config(text=f"Casting {it.title}" + (f" from {int(at // 60)}:{int(at % 60):02d}"
                                                         if at else "") + ".")

    def stop_cast(self):
        if self.session is None:
            return
        s, self.session = self.session, None
        try:
            s.stop()
        except Exception:                                        # noqa: BLE001
            pass
        # The Audio Librarian remembers where it got to (none if it finished).
        self.A.remember(self.app.cfg, self.cast_item.path,
                        None if s.ended == "FINISHED" else getattr(s, "stopped_at", None))
        self.btn_stop.config(state="disabled")
        self.note.config(text="Stopped; the place reached is remembered.")
        self.refresh()

    def destroy(self):
        # docs/design-rules.md, mistake 2: pending after() timers die with the window;
        # a recording stops, a cast is let go.
        for job in list(self._jobs.values()):
            try:
                self.after_cancel(job)
            except Exception:                                    # noqa: BLE001
                pass
        self._jobs.clear()
        if self.rec is not None:
            try:
                self.rec.stop()
            except Exception:                                    # noqa: BLE001
                pass
            self.rec = None
        self.stop_cast()
        super().destroy()


class ScienceRoom(tk.Toplevel):
    """Science (owner, 2026-10-22; nemo/science.py): a question, worked out
    step by step, kept as a worked sheet."""

    ACTIONS = ("Convert units", "Solve", "Simplify", "Factor", "Expand", "Differentiate",
               "Integrate", "Evaluate", "Physics formula", "Statistics")

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Science", "860x600+170+50")
        from .. import science
        self.app, self.S, self.last = app, science, None
        ttk.Label(self, text="Science", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=820, justify="left", text=(
            "Units: 10 inch, then mm. Maths: x^2-5x+6=0. Physics: choose the formula and give "
            "all but one value, like I=20 mA R=220 ohm. Statistics: numbers with spaces.")
                  ).pack(anchor="w", pady=(2, 6))
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x")
        self.action = ttk.Combobox(row, state="readonly", width=16, values=self.ACTIONS)
        self.action.current(1); self.action.pack(side="left")
        self.formula = ttk.Combobox(row, state="readonly", width=12, values=list(science.FORMULAS))
        self.formula.current(0); self.formula.pack(side="left", padx=6)
        self.entry = ttk.Entry(row, width=50); self.entry.pack(side="left", fill="x", expand=True)
        self.to = ttk.Entry(row, width=8); self.to.pack(side="left", padx=6)
        ttk.Button(row, text="Work it out", style="Primary.TButton", command=self.run).pack(side="left")
        self.out = tk.Text(self, height=16, wrap="word", relief="flat", font=app.fonts["body"])
        self.out.pack(fill="both", expand=True, pady=(8, 0))
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="Save the numbers as a spreadsheet...",
                   command=self.save_sheet).pack(side="left")
        ttk.Button(bar, text="Open a spreadsheet...", command=self.open_sheet).pack(side="left", padx=6)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=820)
        self.note.pack(anchor="w")

    def run(self):
        S, text, act = self.S, self.entry.get().strip(), self.action.get()
        try:
            if act == "Convert units":
                ans = S.convert(text, self.to.get().strip())
            elif act == "Physics formula":
                given = dict(p.split("=", 1) for p in re.findall(r"\w+=[^=]+?(?=\s+\w+=|$)", text))
                ans = S.formula(self.formula.get(), {k: v.strip() for k, v in given.items()})
            elif act == "Statistics":
                ans = S.stats([float(x) for x in text.replace(",", " ").split()],
                              self.app.cfg.path("paths.storeroom") / "science" / "chart.png")
            else:
                ans = S.maths(text, act.lower())
        except (S.ScienceError, ValueError) as exc:
            self.note.config(text=f"Not worked out: {exc}."); return None
        sheet = S.keep(self.app.cfg, ans)
        self.out.delete("1.0", "end")
        self.out.insert("end", ans.question + "\n\n" + "\n".join(
            f"{n}. {s}" for n, s in enumerate(ans.steps, 1)) + f"\n\nAnswer: {ans.result}\n")
        self.note.config(text=f"Writer: kept as {sheet.name}.")
        self.last = ans
        return ans

    def save_sheet(self, path: str | None = None):
        from tkinter import filedialog
        nums = [float(x) for x in self.entry.get().replace(",", " ").split()
                if re.fullmatch(r"-?\d+(\.\d+)?", x)]
        if not nums:
            self.note.config(text="Type the numbers first."); return None
        path = path or filedialog.asksaveasfilename(parent=self, defaultextension=".xlsx",
                                                    filetypes=[("Excel", "*.xlsx")])
        if not path:
            return None
        out = self.S.write_sheet(Path(path), "Readings", ["Reading", "Value"],
                                 [[n, v] for n, v in enumerate(nums, 1)])
        self.note.config(text=f"Bookkeeper: {out}, with a total and an average.")
        return out

    def open_sheet(self, path: str | None = None):
        from tkinter import filedialog
        path = path or filedialog.askopenfilename(parent=self, filetypes=[("Excel", "*.xlsx")])
        if not path:
            return None
        try:
            sheets = self.S.read_sheet(Path(path))
        except self.S.ScienceError as exc:
            self.note.config(text=f"Not read: {exc}."); return None
        self.out.delete("1.0", "end")
        for name, rows in sheets.items():
            self.out.insert("end", f"== {name}\n" + "\n".join(
                " | ".join("" if v is None else str(v) for v in r) for r in rows) + "\n\n")
        return sheets


INTRO_POLL_MS = 150         # how often an introduction looks whether the voice has finished
INTRO_BREATH_MS = 600       # the pause between one introduction and the next


class IllustratedRoom(tk.Toplevel):
    """A department as an illustration, the owner's preferred view
    (2026-10-23): its painted scene, its team as round painted portraits,
    a worker's ring glowing while its real job runs. Where a painting is
    not there yet, the drawn card and a brass medallion stand in."""

    W, H, FACE, TICK_MS = 960, 600, 92, 400

    def __init__(self, app: NemoApp, key: str):
        super().__init__(app)
        from .. import busy as P
        from ..staff import DEPARTMENTS, team
        self.app, self.P, self.key, self._job, self.phase = app, P, key, None, 0
        # Short enough for its buttons to show inside Nemo's window on a 768-pixel screen.
        self.H = min(type(self).H, self.winfo_screenheight() - 250)
        name = DEPARTMENTS[key].name
        self.title(f"The {name}"); self.configure(bg=T.SHELL); self.resizable(False, False)
        app.embed_later(self)                                    # inside Nemo's window
        # Nemo's own paintings, not the Storeroom's shelf (owner, 2026-10-29; nemo/art.py).
        from .. import art
        art.migrate(app.cfg.path("paths.storeroom"))
        scene = art.scene(key)
        self._back = scene if scene.is_file() else C.department_card(key)
        self.painted = scene.is_file()
        self._people = team(key)
        self.rings, self._faces = {}, []
        self._intro, self._intro_job, self.speaking, self._resize_job = None, None, None, None
        # An employee's profile card (show_profile): which, its facts, a look at its tools.
        self._profile_role, self._profile, self._profile_cache, self._profile_job = None, None, {}, None
        self._card_view, self._card_note, self._card_buttons = "help", "", 0
        # The team's problems with the open project (nemo/issues.py): a red ring and a "!".
        self._issues = {}
        self.refresh_issues()
        self.canvas = tk.Canvas(self, width=self.W, height=self.H, highlightthickness=0, bg="#21170F")
        self.canvas.pack(fill="both", expand=True)
        self._draw(self.W, self.H)
        bar = tk.Frame(self, bg=T.SHELL); bar.pack(fill="x", pady=4)
        self._bar = bar
        ttk.Button(bar, text=f"Open the {name}", style="Primary.TButton",
                   command=lambda: app.real_window(key)).pack(side="left", padx=6)
        ttk.Button(bar, text="Meet the team", command=self.introduce).pack(side="left", padx=6)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right", padx=6)
        self.skip = ttk.Button(bar, text="Skip the introductions", command=self.end_introductions)
        tk.Label(bar, bg=T.SHELL, fg=T.SELECT, font=app.fonts["small"], text=(
            "" if self.painted else "The Artist's painting of this room is not done yet.")).pack(side="left", padx=8)
        self.canvas.bind("<Button-1>", lambda e: self.next_introduction() if self._intro is not None else None)
        # Full screen (owner, 2026-11-04): the room fills the space Nemo gives
        # it. Embedded, that is the whole window below the bar (1366 wide at
        # full screen here, against the 960 it was drawn at).
        self.bind("<Configure>", self._resized, add="+")
        self.bind("<Escape>", self.hide_profile)
        # Keyboard only (2026-11-08): Left and Right choose a face, Enter or
        # Space opens its card, Escape closes it. A dashed ring shows which.
        self._key_at = None
        for w in (self, self.canvas):
            w.bind("<Left>", lambda e: self.choose_face(-1))
            w.bind("<Right>", lambda e: self.choose_face(+1))
            w.bind("<Return>", lambda e: self.open_chosen_face())
            w.bind("<space>", lambda e: self.open_chosen_face())
        self.canvas.config(takefocus=1)
        self.tick()
        from .. import introductions
        if not introductions.seen(C.load_settings(), key):
            self.introduce()

    def _draw(self, W: int, H: int):
        """The scene, cropped to fill W x H, and the team along its foot."""
        from PIL import Image, ImageDraw, ImageTk
        from .. import art
        self.W, self.H = W, H
        self.canvas.delete("all")
        self.canvas.config(width=W, height=H)
        try:
            im = Image.open(self._back).convert("RGB")
            scale = max(W / im.width, H / im.height)
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            im = im.crop(((im.width - W) // 2, (im.height - H) // 2,
                          (im.width - W) // 2 + W, (im.height - H) // 2 + H))
        except OSError:
            im = Image.new("RGB", (W, H), (33, 23, 15))
        self._bg = ImageTk.PhotoImage(im)
        self.canvas.create_image(0, 0, image=self._bg, anchor="nw")
        people = self._people
        cols = min(len(people), 8)
        gap = W // max(cols, 1)
        self.rings, self._faces = {}, []
        mask = Image.new("L", (self.FACE, self.FACE), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, self.FACE - 1, self.FACE - 1], fill=255)
        for i, e in enumerate(people):
            role = e.key.split(".", 1)[1]
            row, col = divmod(i, 8)
            x = gap // 2 + col * gap
            y = H - 70 - (len(people) - 1) // 8 * 130 + row * 130
            face_path = art.portrait(self.key, role)
            if face_path.is_file():
                face = Image.open(face_path).convert("RGB").resize((self.FACE, self.FACE), Image.LANCZOS)
            else:
                face = Image.new("RGB", (self.FACE, self.FACE), (176, 132, 66))
                ImageDraw.Draw(face).text((self.FACE // 2 - 6, self.FACE // 2 - 8), e.title[0],
                                          fill=(40, 22, 10))
            disc = Image.new("RGBA", (self.FACE, self.FACE), (0, 0, 0, 0))
            disc.paste(face, (0, 0), mask)
            self._faces.append(ImageTk.PhotoImage(disc))
            self.rings[role] = self.canvas.create_oval(x - 50, y - 98, x + 50, y + 2, outline="#C49A52",
                                                       width=4)
            face_item = self.canvas.create_image(x, y - 48, image=self._faces[-1])
            label = self.canvas.create_text(x, y + 16, text=e.title, fill="#F2E6C8",
                                            font=self.app.fonts["small"], width=gap - 8)
            x0, y0, x1, y1 = self.canvas.bbox(label)
            plate = self.canvas.create_rectangle(x0 - 4, y0 - 2, x1 + 4, y1 + 2, fill="#21170F",
                                                 outline="#C49A52")
            self.canvas.tag_raise(label, plate)
            # A click on the face, its ring or its name: its profile (owner, 2026-11-04).
            tag = f"face:{role}"
            items = [self.rings[role], face_item, label, plate]
            if self._issues_of(role):                    # a problem to tell: a red "!" on its ring
                items.append(self.canvas.create_oval(x + 26, y - 104, x + 54, y - 76, fill=T.FAIL,
                                                     outline="white", width=2))
                items.append(self.canvas.create_text(x + 40, y - 90, text="!", fill="white",
                                                     font=self.app.fonts["strong"]))
            for item in items:
                self.canvas.addtag_withtag(tag, item)
            self.canvas.tag_bind(tag, "<Button-1>", lambda ev, r=role: self.show_profile(r))
            self.canvas.tag_bind(tag, "<Enter>", lambda ev: self.canvas.config(cursor="hand2"))
            self.canvas.tag_bind(tag, "<Leave>", lambda ev: self.canvas.config(cursor=""))
        # The caption Nemo introduces the team in (owner, 2026-10-23; nemo/introductions.py),
        # shown again after a redraw if an introduction is under way.
        shown = "normal" if self._intro is not None else "hidden"
        text = self._intro[self._intro_at][1] if self._intro is not None and self._intro_at >= 0 else ""
        self._cap_bg = self.canvas.create_rectangle(20, 16, W - 20, 104, fill="#21170F",
                                                    outline="#C49A52", width=2, state=shown)
        self._cap = self.canvas.create_text(W // 2, 60, text=text, fill="#F2E6C8", width=W - 70,
                                            font=self.app.fonts["body"], state=shown)
        if getattr(self, "_key_at", None) is not None:
            self._mark_chosen()
        if getattr(self, "_profile_role", None):
            self._draw_profile()

    # ---------------------------------------------------------- profiles
    # An employee's card (owner, 2026-11-04): it says any problem with its
    # step and the fixes, then asks what it can help with (nemo/skills.py);
    # "What do you need?" shows its tools (nemo/profiles.py).
    def show_profile(self, role: str, view: str = "help"):
        """The card of the employee `role`. During an introduction a click
        goes to the next line instead."""
        if self._intro is not None:
            return None
        from .. import profiles
        self._profile_role, self._card_view, self._card_note = role, view, ""
        key = f"{self.key}.{role}"
        cached = self._profile_cache.get(key)
        self._profile = cached or profiles.profile(key, self.app.cfg, tools=False, app=self.app)
        self._draw_profile()
        # Esc reaches only what has the keyboard, and an embedded room seldom does.
        self.canvas.bind("<Escape>", self.hide_profile)
        self.canvas.focus_set()
        if cached is None:
            # The tools are looked at once the card is up: one look asks a web site.
            if self._profile_job:
                self.after_cancel(self._profile_job)
            self._profile_job = self.after(60, lambda: self._profile_tools(key))
        return self._profile

    def _profile_tools(self, key: str):
        from .. import profiles
        self._profile_job = None
        p = profiles.profile(key, self.app.cfg, tools=True, app=self.app)
        self._profile_cache[key] = p
        if self._profile_role and f"{self.key}.{self._profile_role}" == key:
            self._profile = p
            self._draw_profile()

    def hide_profile(self, event=None):
        self._profile_role = None
        self.canvas.delete("profile")

    def _roles(self) -> list[str]:
        return [e.key.split(".", 1)[1] for e in self._people]

    def choose_face(self, step: int) -> str | None:
        """The next (or previous) face, marked with a dashed ring."""
        roles = self._roles()
        if not roles:
            return None
        at = -1 if self._key_at is None else self._key_at
        self._key_at = (at + step) % len(roles)
        self._mark_chosen()
        return roles[self._key_at]

    def _mark_chosen(self):
        self.canvas.delete("keyfocus")
        if self._key_at is None:
            return
        role = self._roles()[self._key_at]
        box = self.canvas.coords(self.rings.get(role)) if role in self.rings else None
        if box:
            x0, y0, x1, y1 = box
            self.canvas.create_oval(x0 - 7, y0 - 7, x1 + 7, y1 + 7, outline="white", width=3,
                                    dash=(6, 4), tags=("keyfocus",))

    def open_chosen_face(self):
        if self._intro is not None:
            return self.next_introduction()
        if self._key_at is None:
            self.choose_face(+1)
        return self.show_profile(self._roles()[self._key_at])

    def refresh_issues(self):
        """This department's employees' problems with the open project."""
        from .. import issues
        self._issues = issues.for_department(self.app.project_issues(), self.key)

    def _issues_of(self, role: str) -> list:
        return self._issues.get(f"{self.key}.{role}", [])

    # The card's buttons: brass plates drawn on the canvas, each its own tag.
    def _card_button(self, x, y, text, command, primary=False, width=None):
        c = self.canvas
        self._card_buttons += 1
        tag = f"cardbtn{self._card_buttons}"
        t = c.create_text(x + 12, y + 6, anchor="nw", text=text, width=width,
                          fill="white" if primary else T.INK, font=self.app.fonts["small"],
                          tags=("profile", tag))
        x0, y0, x1, y1 = c.bbox(t)
        r = c.create_rectangle(x, y, x1 + 12, y1 + 6, fill=T.ACTION if primary else T.BRASS,
                               outline="", tags=("profile", tag))
        c.tag_raise(t, r)
        c.tag_bind(tag, "<Button-1>", lambda e: (command(), "break")[1])
        c.tag_bind(tag, "<Enter>", lambda e: c.config(cursor="hand2"))
        c.tag_bind(tag, "<Leave>", lambda e: c.config(cursor=""))
        return x1 + 12, y1 + 6

    def _draw_profile(self):
        from PIL import Image, ImageDraw, ImageTk
        from .. import art, profiles, skills
        c, p, W, H = self.canvas, self._profile, self.W, self.H
        c.delete("profile")
        self._card_buttons = 0
        pw, ph = min(900, W - 60), min(H - 30, 540)
        x0, y0 = (W - pw) // 2, max(10, (H - ph) // 2 - 20)
        veil = c.create_rectangle(0, 0, W, H, fill="#000000", stipple="gray50", outline="",
                                  tags=("profile",))
        c.tag_bind(veil, "<Button-1>", self.hide_profile)              # a click beside it closes it
        c.create_rectangle(x0, y0, x0 + pw, y0 + ph, fill=T.SHELL, outline=T.BRASS, width=3,
                           tags=("profile",))
        # The portrait, large.
        side = 160
        face_path = art.portrait(self.key, self._profile_role)
        try:
            face = Image.open(face_path).convert("RGB").resize((side, side), Image.LANCZOS)
        except OSError:
            face = Image.new("RGB", (side, side), (176, 132, 66))
        mask = Image.new("L", (side, side), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, side - 1, side - 1], fill=255)
        disc = Image.new("RGBA", (side, side), (0, 0, 0, 0)); disc.paste(face, (0, 0), mask)
        self._profile_face = ImageTk.PhotoImage(disc)
        fx, fy = x0 + 26 + side // 2, y0 + 26 + side // 2
        problems = self._issues_of(self._profile_role)
        ring = T.FAIL if problems else T.BRASS
        c.create_oval(fx - side // 2 - 5, fy - side // 2 - 5, fx + side // 2 + 5, fy + side // 2 + 5,
                      outline=ring, width=5, tags=("profile",))
        c.create_image(fx, fy, image=self._profile_face, tags=("profile",))
        state = ("Has a problem" if problems else "Working now" if p.busy else
                 "Checking its tools..." if p.tools is None and p.working else p.status.capitalize())
        colour = (T.FAIL if problems else "#8A6A2E" if p.busy else
                  {profiles.READY: T.PASS, profiles.NEEDS: T.SKIP, profiles.NOT_BUILT: T.INK2}[p.status])
        c.create_rectangle(fx - 76, fy + side // 2 + 14, fx + 76, fy + side // 2 + 40, fill=colour,
                           outline="", tags=("profile",))
        c.create_text(fx, fy + side // 2 + 27, text=state, fill="white", font=self.app.fonts["stamp"],
                      tags=("profile",))
        c.create_text(fx, fy + side // 2 + 58, text=p.title, fill=T.SHELL_INK, width=side + 20,
                      font=(self.app.fonts["title"][0], T.scaled(15, self.app.text_percent), "bold"),
                      tags=("profile",))
        c.create_text(fx, fy + side // 2 + 84, text=p.department, fill=T.BRASS,
                      font=self.app.fonts["strong"], tags=("profile",))
        tx, tw = x0 + side + 64, pw - side - 90
        y = y0 + 24
        say = lambda text, font="body", fill=T.SHELL_INK, gap=8: (            # noqa: E731
            c.bbox(c.create_text(tx, y, anchor="nw", text=text, width=tw, fill=fill,
                                 font=self.app.fonts[font], tags=("profile",)))[3] + gap)
        if self._card_view == "needs":
            y = say("What I need", "h2")
            if p.tools is None:
                y = say("Looking...")
            elif not p.tools:
                y = say("Nothing outside Nemo: I am all code.")
            for t in p.tools or []:
                mark = "✓" if t.ok else "✗"
                y = say(f"{mark} {t.need}" + ("" if t.ok else f": {t.detail}"), "small",
                        T.SHELL_INK if t.ok else "#F0B49A", 4)
            y += 8
            self._card_button(tx, y, "← What I can help with",
                              lambda: self.show_profile(self._profile_role))
        else:
            # A problem first: the owner hears of it from the one whose step it is.
            for issue in problems:
                y = say(f"I have a problem: {issue.headline()}.", "strong", "#F0B49A", 4)
                for line in issue.problems[:3]:
                    y = say(f"• {line}", "small", T.SHELL_INK, 2)
                y += 6
                shown = 0
                for fix in issue.fixes:
                    if shown == 3:
                        break
                    shown += 1
                    y = say(fix.title + (f": {fix.why}" if fix.why else ""), "small", T.SELECT, 4)
                    bx = tx
                    if fix.kind == "change":
                        bx, _ = self._card_button(bx, y, "Do it", lambda f=fix: self.apply_fix(f, False),
                                                  primary=True)
                        bx, by = self._card_button(bx + 8, y, "Do it and run again",
                                                   lambda f=fix, i=issue: self.apply_fix(f, True, i))
                    elif getattr(fix, "url", ""):
                        import webbrowser
                        bx, by = self._card_button(bx, y, "Open the page",
                                                   lambda f=fix: webbrowser.open(f.url))
                    elif getattr(fix, "brief_field", ""):
                        bx, by = self._card_button(bx, y, "Fill it in on the brief",
                                                   lambda f=fix: self.fill_brief(f.brief_field))
                    else:
                        by = y - 4
                    y = by + 10
                if not issue.fixes:
                    y = say("Nemo has no fix to offer for this one: the Workshop's results show "
                            "what happened.", "small", T.SELECT)
                y += 6
            y = say(f"Hello, I'm the {p.title}. What can I help with?" if not problems else
                    "Or, what else can I help with?", "h2")
            for s in skills.skills_for(f"{self.key}.{self._profile_role}"):
                _, by = self._card_button(tx, y, s.label, lambda s=s: self.use_skill(s),
                                          primary=(s.kind != skills.NEEDS and not problems))
                y = by + 6
            if self._card_note:
                say(self._card_note, "small", T.BRASS)
        close = c.create_text(x0 + pw - 16, y0 + 14, anchor="ne", text="✕  Close", fill=T.BRASS,
                              font=self.app.fonts["small"], tags=("profile",))
        c.tag_bind(close, "<Button-1>", self.hide_profile)

    # -------------------------------------------------------------- skills
    def use_skill(self, skill):
        """Do what the employee offered (nemo/skills.py)."""
        from .. import skills
        if skill.kind == skills.NEEDS:
            self.show_profile(self._profile_role, view="needs")
            return
        if skill.kind == skills.ASK:
            # The department's own box, not the home screen (owner, 2026-11-09).
            self.hide_profile()
            bar = getattr(self.app, "ask_bar", None)
            if bar is not None and bar.winfo_ismapped():
                bar.tell(f"{skill.label}: type it here and press Ask.")
                bar.focus()
            return
        if skill.kind == skills.DIALOG:
            cls, _, button = skill.target.partition(":")
            win = globals()[cls](self.app)
            if button:
                self.after(150, lambda: light_button(win, button))
            return
        if skill.kind == skills.JOB:
            args = skill.target.split()
            if self.app.job and self.app.job.running:
                self._card_note = "Something else is running: I will wait until it has finished."
            elif args[0] in skills.PROJECT_JOBS and not self.app.project:
                self._card_note = "Open a project first: there is none open to look at."
            else:
                if args[0] in skills.PROJECT_JOBS:
                    args = ["--project", self.app.project.root.name, *args]
                self.app.start_job(C.nemo_argv(*args), skill.target.split()[0])
                self._card_note = "Started. I will say what I found when it is done."
            self._draw_profile()
            return
        if skill.kind == skills.VERDICTS:
            from .. import shipcheck
            past = shipcheck.history(n=5)
            self._card_note = ("\n".join(f"{r['when']}: {r['verdict']}, {r['candidate']} "
                                         f"{r['candidate_passed']}/{r['of']} against {r['base']} "
                                         f"{r['base_passed']}/{r['of']}" for r in past)
                               or "No verdicts yet: run the SHIP check first.")
            self._draw_profile()
            return
        if skill.kind == skills.STEP:
            if not self.app.project:
                self._card_note = "Open a project first: there is none open to work on."
                self._draw_profile()
                return
            self.app.back_to_workshop()
            self.app.run_stage(skill.target)
            return
        # WINDOW: the department's own window, with the control lit.
        win = self.app.real_window(self.key)
        if win is None:                                       # the Workshop, the Computer Lab
            self.app.back_to_workshop()
            return
        if skill.target:
            self.after(150, lambda: light_button(win, skill.target))

    def apply_fix(self, fix, run: bool, issue=None):
        """A fix from the employee's card, as the Workshop's Apply does."""
        if not self.app.project:
            return
        C.apply_fix_to_project(self.app.project, fix)
        self.app.loaded_brief = self.app.project.load_brief()
        self.app.say(f"Applied: {fix.title}.", T.PASS)
        if run:
            stage = fix.rerun or (issue.stage if issue else "")
            self.app.back_to_workshop()
            if stage:
                self.app.run_stage(stage)
            return
        self._card_note = f"Done: {fix.title}. Run the step again when ready."
        self.refresh_issues()
        if self._profile_role:                     # the card may have been closed meanwhile
            self._draw_profile()

    def fill_brief(self, field):
        self.app.back_to_workshop()
        self.app.open_brief_at(field)

    def _resized(self, event):
        """Redraw at the new size, once it settles (a drag sends many)."""
        if event.widget is not self:
            return
        W, H = event.width, event.height - self._bar.winfo_reqheight() - 8
        if W < 200 or H < 200 or (abs(W - self.W) < 8 and abs(H - self.H) < 8):
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, lambda: (setattr(self, "_resize_job", None),
                                                    self._draw(W, H)))

    # ----------------------------------------------------- introductions
    def introduce(self):
        """Nemo introduces the team, one at a time, each portrait lit; a
        click (or the timer) goes to the next."""
        from .. import introductions
        self._intro = [(None, introductions.welcome(self.key))] + introductions.lines(self.key)
        self._intro_at = -1
        self.skip.pack(side="left", padx=6)
        self.canvas.itemconfig(self._cap_bg, state="normal")
        self.canvas.itemconfig(self._cap, state="normal")
        self.next_introduction()

    def next_introduction(self):
        if self._intro_job:
            self.after_cancel(self._intro_job); self._intro_job = None
        self._intro_at += 1
        if self._intro_at >= len(self._intro):
            self.end_introductions(); return
        role, text = self._intro[self._intro_at]
        self.speaking = role
        self.canvas.itemconfig(self._cap, text=text)
        spoken = False
        if getattr(self.app, "voice_on", None) is not None and self.app.voice_on.get():
            from .. import voice
            spoken = voice.speak(text)[0]
        if spoken:
            # D275: the next line came on a reading-time timer, however long
            # the voice took, and cut it off: "Hello, I'm the Writer." style
            # lines with commas run slow (97 words a minute measured). Now
            # the next waits for the voice to finish, then a breath.
            import time
            self._intro_until = time.monotonic() + 30          # never wait longer than this
            self._intro_job = self.after(INTRO_POLL_MS, self._intro_when_quiet)
        else:
            # Long enough to read it: about 2.6 words a second, and a breath.
            self._intro_job = self.after(1500 + 380 * len(text.split()), self.next_introduction)

    def _intro_when_quiet(self):
        import time
        from .. import voice
        if voice.speaking() and time.monotonic() < self._intro_until:
            self._intro_job = self.after(INTRO_POLL_MS, self._intro_when_quiet)
        else:
            self._intro_job = self.after(INTRO_BREATH_MS, self.next_introduction)

    def end_introductions(self):
        from .. import introductions
        if self._intro_job:
            self.after_cancel(self._intro_job); self._intro_job = None
        self._intro, self.speaking = None, None
        self.canvas.itemconfig(self._cap_bg, state="hidden")
        self.canvas.itemconfig(self._cap, state="hidden")
        self.skip.pack_forget()
        C.save_settings(introductions.mark(C.load_settings(), self.key))

    def tick(self):
        """A working worker's ring glows, brighter and dimmer by turns."""
        self.phase ^= 1
        busy = self.P.signals(self.app, self.key)
        for role, ring in self.rings.items():
            glow = busy.get(role)
            if role == getattr(self, "speaking", None):        # being introduced: lit white
                self.canvas.itemconfig(ring, outline="#FFF6E0", width=8)
                continue
            if self._issues_of(role):                         # a problem: red, pulsing
                self.canvas.itemconfig(ring, outline=T.FAIL if self.phase else "#D9694F", width=7)
                continue
            self.canvas.itemconfig(ring, outline=("#FFD27A" if self.phase else "#E0A040") if glow
                                   else "#C49A52", width=7 if glow else 4)
        self._job = self.after(self.TICK_MS, self.tick)

    def destroy(self):
        # docs/design-rules.md, mistake 2: a pending after() outlives its widget.
        for name in ("_job", "_intro_job", "_resize_job", "_profile_job"):
            job = getattr(self, name, None)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:                                # noqa: BLE001
                    pass
                setattr(self, name, None)
        super().destroy()


class CommsRoom(tk.Toplevel):
    """Communications (owner, 2026-10-22; nemo/comms.py): your bookmarks and
    sites, and letters, emails and posts drafted here. Nemo opens and copies;
    you send and post."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Communications", "860x600+170+50")
        from .. import comms
        self.app, self.M = app, comms
        ttk.Label(self, text="Communications", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=820, justify="left", text=(
            "Nemo opens your browser and your mail program, and copies what you write; it "
            "never sends, posts or logs in for you.")).pack(anchor="w", pady=(2, 6))
        top = ttk.Frame(self, style="Panel.TFrame"); top.pack(fill="x")
        ttk.Label(top, text="Sites", style="PanelMuted.TLabel").pack(side="left")
        self.sites = ttk.Combobox(top, width=34, state="readonly")
        self.sites.pack(side="left", padx=6)
        ttk.Button(top, text="Open", command=self.open_site).pack(side="left")
        ttk.Button(top, text="Add a site...", command=self.add_site).pack(side="left", padx=6)
        form = ttk.Frame(self, style="Panel.TFrame"); form.pack(fill="x", pady=(10, 0))
        ttk.Label(form, text="To", style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.to = ttk.Combobox(form, width=36)
        self.to.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(form, text="Add a contact...", command=self.add_contact).grid(row=0, column=2)
        ttk.Label(form, text="Subject", style="PanelMuted.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        self.subject = ttk.Entry(form, width=60)
        self.subject.grid(row=1, column=1, columnspan=2, sticky="w", padx=6)
        self.body = tk.Text(self, height=12, wrap="word", relief="flat", font=app.fonts["body"])
        self.body.pack(fill="both", expand=True, pady=(6, 0))
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Check spelling", command=self.check).pack(side="left")
        ttk.Button(row, text="Make it a letter", command=self.make_letter).pack(side="left", padx=6)
        ttk.Button(row, text="Open in my mail program", style="Primary.TButton",
                   command=self.mail).pack(side="left")
        ttk.Button(row, text="Copy for a post", command=self.copy_post).pack(side="left", padx=6)
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=820, justify="left")
        self.note.pack(anchor="w", pady=(6, 0))
        self.refresh()

    def refresh(self):
        self.bm = self.M.bookmarks(self.app.cfg)
        self.sites.config(values=[f"{b.name} ({b.kind})" for b in self.bm])
        if self.bm:
            self.sites.current(0)
        self.to.config(values=[c.name for c in self.M.contacts(self.app.cfg)])

    def _text(self) -> str:
        return self.body.get("1.0", "end").strip()

    def open_site(self):
        i = self.sites.current()
        if 0 <= i < len(self.bm):
            try:
                self.note.config(text=f"Browser: {self.bm[i].name} is open in "
                                      f"{self.M.open_web(self.bm[i].url)}.")
            except (RuntimeError, self.M.CommsError) as exc:
                self.note.config(text=f"Not opened: {exc}.")

    def add_site(self, ask=None):
        from tkinter import simpledialog
        ask = ask or (lambda t, p: simpledialog.askstring(t, p, parent=self))
        name = ask("Add a site", "Its name (say, Facebook):")
        url = name and ask("Add a site", "Its web address:")
        if not url:
            return None
        kind = "social" if any(w in url.lower() for w in ("facebook", "instagram", "twitter", "x.com",
                                                            "tiktok", "reddit", "linkedin")) else \
            "mail" if "mail" in url.lower() else "web"
        try:
            b = self.M.add_bookmark(self.app.cfg, name, url, kind)
        except self.M.CommsError as exc:
            self.note.config(text=f"Not kept: {exc}."); return None
        self.refresh()
        self.note.config(text=f"Browser: kept {b.name} as a {kind} site.")
        return b

    def add_contact(self, ask=None):
        from tkinter import simpledialog
        ask = ask or (lambda t, p: simpledialog.askstring(t, p, parent=self))
        name = ask("Add a contact", "Their name:")
        if not name:
            return None
        email = ask("Add a contact", "Their email address (may be empty):") or ""
        try:
            c = self.M.add_contact(self.app.cfg, name, email)
        except self.M.CommsError as exc:
            self.note.config(text=f"Not kept: {exc}."); return None
        self.refresh(); self.to.set(c.name)
        return c

    def check(self):
        found = self.M.spell(f"{self.subject.get()}\n\n{self._text()}", self.app.cfg)
        self.note.config(text="Writer: " + ("; ".join(found) if found else "no spelling slips found."))

    def make_letter(self):
        if not self._text():
            self.note.config(text="Write what you want to say first."); return
        text = self.M.letter(self.app.cfg, self.to.get(), self._text())
        self.body.delete("1.0", "end"); self.body.insert("1.0", text)
        d = self.M.save_draft(self.app.cfg, self.M.Draft("letter", self.to.get(), "", text))
        self.note.config(text=f"Writer: laid out as a letter and kept as {d.path.name}; print it from there.")

    def mail(self, starter=None):
        try:
            d = self.M.save_draft(self.app.cfg, self.M.Draft("email", self.to.get(),
                                                             self.subject.get(), self._text()))
            self.clipboard_clear(); self.clipboard_append(d.body)
            said = self.M.send_by_mail_program(self.app.cfg, d, starter)
        except (OSError, self.M.CommsError) as exc:
            self.note.config(text=f"Not opened: {exc}."); return None
        self.note.config(text=f"Postman: {said}.")
        return said

    def copy_post(self):
        if not self._text():
            self.note.config(text="Write the post first."); return
        d = self.M.save_draft(self.app.cfg, self.M.Draft("post", self.sites.get(), "", self._text()))
        self.clipboard_clear(); self.clipboard_append(d.body)
        self.note.config(text="Social: the post is copied. Open your site above and paste it there; "
                              "Nemo does not post.")


class HomeRoom(tk.Toplevel):
    """Home (owner, 2026-10-22; nemo/home.py): the devices on the network and
    the permission you give each. Nothing is touched until you say Use."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Home", "860x560+170+60")
        from .. import home
        self.app, self.H, self._job = app, home, None
        ttk.Label(self, text="Home", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=820, justify="left", text=(
            "Look around lists what is on your network from what the devices announce; Nemo "
            "never connects to one or logs in. Each device is See until you choose: Use lets "
            "Nemo talk to it (cast to a Chromecast, read a board's status); Hide takes it off "
            "the list. Every change is logged.")).pack(anchor="w", pady=(2, 6))
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x")
        self.btn_look = ttk.Button(row, text="Look around", style="Primary.TButton", command=self.look)
        self.btn_look.pack(side="left")
        for label, perm in (("Use", "use"), ("See only", "see"), ("Hide", "hidden")):
            ttk.Button(row, text=label, command=lambda p=perm: self.set(p)).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Write the list", command=self.write).pack(side="right")
        # The platform each device is, chosen by you (2026-10-28): what Nemo can do with it.
        prow = ttk.Frame(self, style="Panel.TFrame"); prow.pack(fill="x", pady=(6, 0))
        ttk.Label(prow, text="Platform", style="PanelMuted.TLabel").pack(side="left")
        self.platform_names = {label: key for key, (label, _w, _b) in home.PLATFORMS.items()}
        self.platform = ttk.Combobox(prow, state="readonly", width=52,
                                     values=list(self.platform_names))
        self.platform.pack(side="left", padx=6)
        ttk.Button(prow, text="Set platform", command=self.set_platform).pack(side="left")
        self.tree = ttk.Treeview(self, columns=("perm", "name", "ip", "kind", "can"), show="headings",
                                 height=12)
        for col, text, w in (("perm", "Nemo may", 80), ("name", "Device", 190), ("ip", "Address", 110),
                             ("kind", "What it is", 260), ("can", "Nemo can", 260)):
            self.tree.heading(col, text=text, anchor="w"); self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))
        self.boards = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=820, justify="left")
        self.boards.pack(anchor="w", pady=(6, 0))
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x", pady=(6, 0))
        self.note = ttk.Label(bar, style="PanelMuted.TLabel", text="", wraplength=700, justify="left")
        self.note.pack(side="left")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.refresh()

    def refresh(self):
        words = {"use": "use", "see": "see only", "hidden": "hidden"}
        self.devices = [d for d in self.H.known() if d.permission != "hidden"]
        self.tree.delete(*self.tree.get_children())
        last = self.H.last_survey(self.devices)
        # Found by the latest survey first; then the ones only remembered, said so.
        for d in sorted(self.devices, key=lambda d: (not self.H.present(d, last), d.label.lower())):
            kind = self.H.device_type(d)[0] or "type not known"
            what = (kind if self.H.present(d, last)
                    else f"{kind}; not found by the latest survey, last seen {d.seen or 'unknown'}")
            self.tree.insert("", "end", iid=d.key, values=(words[d.permission], d.label, d.ip, what,
                                                           self.H.can_do(d)))
        found = self.H.boards(self.app.cfg)
        self.boards.config(text="Your boards: " + "; ".join(f"{b.project}: {b.note}" for b in found)
                           if found else "Your boards: none flashed from the Test Bench yet.")

    def look(self):
        import threading
        self.btn_look.config(state="disabled")
        self.note.config(text="Surveyor: looking around the network (about 10 seconds)...")
        box = {}

        def run():
            try:
                box["found"] = self.H.remember(self.H.survey())
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=run, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._job = self.after(300, wait); return
            self._job = None
            self.btn_look.config(state="normal")
            self.refresh()
            self.note.config(text=f"Not done: {box['e']}." if "e" in box else
                             f"Surveyor: {len(box['found'])} device(s) on this network.")
        wait()

    def set(self, permission: str):
        sel = self.tree.selection()
        if not sel:
            self.note.config(text="Choose a device first."); return
        d = self.H.allow(sel[0], permission)
        self.refresh()
        if self.tree.exists(d.key):
            self.tree.selection_set(d.key)                     # still chosen, for the next button
        self.note.config(text=f"Gatekeeper: {d.label} is now "
                              + {"use": "Use", "see": "See only", "hidden": "hidden"}[permission]
                              + ". The change is logged.")

    def set_platform(self):
        sel = self.tree.selection()
        if not sel or not self.platform.get():
            self.note.config(text="Choose a device, then its platform."); return
        d = self.H.set_platform(sel[0], self.platform_names[self.platform.get()])
        self.refresh()
        self.tree.selection_set(d.key)
        self.note.config(text=f"{d.label} is {self.platform.get()}. Nemo can: {self.H.can_do(d)}. "
                              "The change is logged.")

    def write(self):
        self.note.config(text=f"Writer: {self.H.write_list(self.app.cfg)}")

    def destroy(self):
        # docs/design-rules.md, mistake 2: a pending after() outlives its widget.
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:                                    # noqa: BLE001
                pass
            self._job = None
        super().destroy()


class FilmStudio(tk.Toplevel):
    """The Film Studio (owner, 2026-10-22; nemo/filmstudio.py): a film from a
    story, or a slideshow of pictures, or clips joined, for the Theatre."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Film Studio", "860x620+170+40")
        from .. import filmstudio, theatre
        self.app, self.F, self.T, self._job = app, filmstudio, theatre, None
        ttk.Label(self, text="Film Studio", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=820, justify="left", text=(
            "A film from a story: a picture for each scene, read aloud, with titles and "
            "subtitles. Painting takes about 11 minutes a picture here; untick it to use the "
            "story's cover instead. Films go on the videos shelf for the Theatre.")).pack(anchor="w", pady=(2, 6))
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x")
        ttk.Label(row, text="Story", style="PanelMuted.TLabel").pack(side="left")
        self.stories = filmstudio.stories(app.cfg)
        self.story = ttk.Combobox(row, state="readonly", width=34, values=[d.name for d in self.stories])
        self.story.pack(side="left", padx=6)
        if self.stories:
            self.story.current(0)
        ttk.Button(row, text="Plan", command=self.show_plan).pack(side="left")
        self.paint = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Paint the pictures", variable=self.paint).pack(side="left", padx=10)
        self.btn_make = ttk.Button(row, text="Make the film", style="Primary.TButton", command=self.make)
        self.btn_make.pack(side="left")
        self.out = tk.Text(self, height=12, wrap="word", relief="flat", highlightthickness=0,
                           font=app.fonts["small"])
        self.out.pack(fill="both", expand=True, pady=(8, 0))
        low = ttk.Frame(self, style="Panel.TFrame"); low.pack(fill="x", pady=(8, 0))
        self.pics = tk.Listbox(low, selectmode="extended", height=6, exportselection=False)
        self.vids = tk.Listbox(low, selectmode="extended", height=6, exportselection=False)
        self.photos = theatre.photos(app.cfg)
        self.videos = theatre.videos(app.cfg)
        for p in self.photos:
            self.pics.insert("end", p.name)
        for v in self.videos:
            self.vids.insert("end", v.name)
        self.pics.pack(side="left", fill="both", expand=True)
        ttk.Button(low, text="Slideshow of these", command=self.slideshow).pack(side="left", padx=6)
        self.vids.pack(side="left", fill="both", expand=True)
        ttk.Button(low, text="Join these", command=self.join).pack(side="left", padx=6)
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x", pady=(6, 0))
        self.note = ttk.Label(bar, style="PanelMuted.TLabel", text="", wraplength=700, justify="left")
        self.note.pack(side="left")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")

    def _story(self):
        i = self.story.current()
        return self.stories[i] if 0 <= i < len(self.stories) else None

    def show_plan(self):
        story = self._story()
        if story is None:
            self.note.config(text="There is no story to film yet: write one in the Library."); return None
        plan = self.F.plan_for(self.app.cfg, story)
        path = self.F.save_plan(self.app.cfg, plan)
        self.out.delete("1.0", "end")
        for n, s in enumerate(plan.scenes, 1):
            self.out.insert("end", f"Scene {n}: {' '.join(s.text.split()[:24])}...\n\n")
        self.note.config(text=f"{len(plan.scenes)} scene(s). The plan is {path}; change it there if you like.")
        return plan

    def _go(self, work, what: str):
        import threading
        self.btn_make.config(state="disabled")
        self.note.config(text=f"{what}...")
        box = {}

        def run():
            try:
                box["made"] = work()
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=run, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._job = self.after(500, wait); return
            self._job = None
            self.btn_make.config(state="normal")
            if "e" in box:
                self.note.config(text=f"Not made: {box['e']}."); return
            made = box["made"]
            self.note.config(text=" ".join(made.notes) + f". It is {made.film.name} on the videos shelf.")
            self.app.announce(f"Film Studio: {made.film.stem} is ready.")
        wait()

    def make(self):
        plan = self.show_plan()
        if plan is not None:
            paint = self.paint.get()
            self._go(lambda: self.F.make_film(self.app.cfg, plan, paint=paint), "Making the film")

    def slideshow(self):
        chosen = [self.photos[i].path for i in self.pics.curselection()]
        if not chosen:
            self.note.config(text="Choose some pictures first."); return
        self._go(lambda: self.F.slideshow(self.app.cfg, "slideshow " + datetime.now().strftime("%Y-%m-%d %H%M"),
                                          chosen), "Making the slideshow")

    def join(self):
        chosen = [(self.videos[i].path, None, None) for i in self.vids.curselection()]
        if not chosen:
            self.note.config(text="Choose some clips first."); return
        self._go(lambda: self.F.join_clips(self.app.cfg, "joined " + datetime.now().strftime("%Y-%m-%d %H%M"),
                                           chosen), "Joining the clips")

    def destroy(self):
        # docs/design-rules.md, mistake 2: a pending after() outlives its widget.
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:                                    # noqa: BLE001
                pass
            self._job = None
        super().destroy()


class GameStudio(tk.Toplevel):
    """The Game Studio (owner, 2026-11-09; nemo/gamestudio.py): your games, made in
    Godot from your ideas. An idea goes in the department's box above (gui/askbar.py);
    here are the games made, to play, test again, or open."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Game Studio", "820x560+180+60")
        from .. import gamestudio
        self.app, self.G = app, gamestudio
        ttk.Label(self, text="Game Studio: your games, made in Godot",
                  style="PanelH2.TLabel").pack(anchor="w")
        ok, why = gamestudio.available(app.cfg)
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=780, justify="left", text=(
            "Type your game idea in the box above and press Ask: the Game Designer reads it, the "
            "Level Designer and Programmer build it, the Tester runs it before you play. Nothing "
            "is asked about your gaming history." if ok else f"Not here: {why}."
        )).pack(anchor="w", pady=(2, 6))
        self.tree = ttk.Treeview(self, columns=("title", "kind"), show="headings", height=12)
        for col, text, w in (("title", "Game", 480), ("kind", "Kind", 160)):
            self.tree.heading(col, text=text); self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Play it", style="Primary.TButton",
                   command=self.play).pack(side="left")
        ttk.Button(row, text="Test it again", command=self.check).pack(side="left", padx=6)
        ttk.Button(row, text="Open its folder", command=self.open_folder).pack(side="left")
        ttk.Button(row, text="Look again", command=self.refresh).pack(side="right")
        self.note = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=780,
                              justify="left")
        self.note.pack(anchor="w", pady=(6, 0))
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for g in self.G.games(self.app.cfg):
            self.tree.insert("", "end", iid=g["name"], values=(g["title"], g["kind"]))

    def chosen(self):
        sel = self.tree.selection()
        if not sel:
            self.note.config(text="Choose a game first.")
            return None
        return self.G.folder(self.app.cfg) / sel[0]

    def play(self):
        where = self.chosen()
        if where is None:
            return
        try:
            self.G.play(self.app.cfg, where)
            self.note.config(text="Playing in its own window: Left and Right to move, Space or "
                                  "Up to jump; close it to stop.")
        except self.G.StudioError as exc:
            self.note.config(text=str(exc))

    def check(self):
        where = self.chosen()
        if where is not None and getattr(self.app, "ask_bar", None) is not None:
            self.app.ask_bar.send(f"check {where.name}")

    def open_folder(self):
        where = self.chosen()
        if where is not None:
            C.open_path(where)


class PrintShop(tk.Toplevel):
    """The Print Shop (owner, 2026-10-22; nemo/printshop.py): a model sliced
    for the Kobra 3, with what it will take. Nemo never sends the print."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Print Shop", "820x560+180+60")
        from .. import printshop
        self.app, self.P, self._job = app, printshop, None
        ttk.Label(self, text="Print Shop: ready for the Kobra 3", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=780, justify="left", text=(
            "Pick a model from the Art Studio or a Workshop enclosure, a quality and a "
            "filament, and slice it. The G-code and a card go in the model's print folder; "
            "copy the G-code to the printer yourself.")).pack(anchor="w", pady=(2, 6))
        self.tree = ttk.Treeview(self, columns=("name", "where"), show="headings", height=8)
        for col, text, w in (("name", "Model", 420), ("where", "From", 160)):
            self.tree.heading(col, text=text); self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="x")
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(8, 0))
        exe = printshop.orca()
        c = printshop.choices(exe) if exe else {"process": [], "filament": []}
        self.names = c
        ttk.Label(row, text="Quality", style="PanelMuted.TLabel").pack(side="left")
        self.quality = ttk.Combobox(row, width=22, state="readonly",
                                    values=[n.split(" @")[0] for n in c["process"]])
        self.quality.pack(side="left", padx=6)
        ttk.Label(row, text="Filament", style="PanelMuted.TLabel").pack(side="left")
        self.filament = ttk.Combobox(row, width=24, state="readonly",
                                     values=[n.split(" @")[0] for n in c["filament"]])
        self.filament.pack(side="left", padx=6)
        for box, kind, default in ((self.quality, "process", printshop.QUALITY),
                                   (self.filament, "filament", printshop.FILAMENT)):
            if default in c[kind]:
                box.current(c[kind].index(default))
        self.btn = ttk.Button(row, text="Slice it", style="Primary.TButton", command=self.slice)
        self.btn.pack(side="left", padx=(12, 0))
        self.out = tk.Text(self, wrap="word", relief="flat", height=12, font=("Consolas", 10),
                           highlightthickness=0)
        self.out.pack(fill="both", expand=True, pady=(8, 0))
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x", pady=(6, 0))
        self.note = ttk.Label(bar, style="PanelMuted.TLabel", text="", wraplength=640, justify="left")
        self.note.pack(side="left")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.refresh()
        if not exe:
            self.btn.config(state="disabled")
            self.note.config(text="OrcaSlicer is not installed, so nothing can be sliced.")

    def refresh(self):
        self.models = self.P.models(self.app.cfg)
        self.tree.delete(*self.tree.get_children())
        for i, m in enumerate(self.models):
            self.tree.insert("", "end", iid=str(i), values=(m.name, m.where))
        if not self.models:
            self.note.config(text="No models yet: make one in the Art Studio, or build an enclosure.")

    def _pick(self, box, kind: str) -> str:
        i = box.current()
        return self.names[kind][i] if 0 <= i < len(self.names[kind]) else ""

    def slice(self):
        import threading
        sel = self.tree.selection()
        if not sel:
            self.note.config(text="Pick a model first."); return
        model = self.models[int(sel[0])]
        quality, filament = self._pick(self.quality, "process"), self._pick(self.filament, "filament")
        self.btn.config(state="disabled")
        self.note.config(text=f"Slicer: slicing {model.name}...")
        box = {}

        def run():
            try:
                box["job"] = self.P.slice_model(self.app.cfg, model, quality, filament)
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=run, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._job = self.after(300, wait); return
            self._job = None
            self.show(box)
        wait()

    def show(self, box: dict):
        self.btn.config(state="normal")
        if "e" in box:
            self.note.config(text=f"Not sliced: {box['e']}."); return
        job = box["job"]
        self.out.delete("1.0", "end")
        if not job.ok:
            self.note.config(text="Not sliced: " + "; ".join(job.notes[:2])); return
        self.out.insert("end", job.card.read_text(encoding="utf-8"))
        self.note.config(text=f"Sliced in {job.seconds:g} s: {job.gcode}")
        self.app.announce(f"Print Shop: sliced, {job.time_text}.")

    def destroy(self):
        # docs/design-rules.md, mistake 2: a pending after() outlives its widget.
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:                                    # noqa: BLE001
                pass
            self._job = None
        super().destroy()


class TestBench(tk.Toplevel):
    """The Test Bench (owner, 2026-10-21; nemo/bench.py): the open project's
    firmware put on the board, and what the board prints."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Test Bench", "820x560+180+60")
        from .. import bench
        self.app, self.B, self._job = app, bench, None
        ttk.Label(self, text="Test Bench", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=780, justify="left", text=(
            "For the project open in the workshop: put its firmware on the board over USB, "
            "then listen to what it prints. Plug the board in first.")).pack(anchor="w", pady=(2, 6))
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x")
        ttk.Label(row, text="Port", style="PanelMuted.TLabel").pack(side="left")
        self.port = ttk.Combobox(row, width=40, state="readonly", values=[])
        self.port.pack(side="left", padx=6)
        ttk.Button(row, text="Look again", command=self.refresh).pack(side="left")
        self.btn_flash = ttk.Button(row, text="Flash it", style="Primary.TButton", command=self.flash)
        self.btn_flash.pack(side="left", padx=(16, 4))
        self.btn_listen = ttk.Button(row, text="Listen 10 s", command=self.listen)
        self.btn_listen.pack(side="left")
        self.out = tk.Text(self, wrap="none", relief="flat", bg="#10171A", fg="#B8F2C9",
                           font=("Consolas", 10), highlightthickness=0)
        self.out.pack(fill="both", expand=True, pady=(8, 0))
        bar = ttk.Frame(self, style="Panel.TFrame"); bar.pack(fill="x", pady=(6, 0))
        self.note = ttk.Label(bar, style="PanelMuted.TLabel", text="", wraplength=640, justify="left")
        self.note.pack(side="left")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.refresh()

    def refresh(self):
        self.found = self.B.ports()
        self.port.config(values=[f"{p.device}  {p.hint or p.description}" for p in self.found])
        if self.found:
            self.port.current(0)                 # board-like ports come first
            self.note.config(text=f"{len(self.found)} serial port(s)." + (
                "" if self.B.board_port(self.found) else
                " All are Bluetooth links, not a board: is the board plugged in?"))
        else:
            self.note.config(text="No serial port: is the board plugged in?")

    def _port(self) -> str | None:
        i = self.port.current()
        return self.found[i].device if 0 <= i < len(self.found) else None

    def _go(self, work, what: str):
        import threading
        if not self.app.project:
            self.note.config(text="Open a project in the workshop first."); return
        self.btn_flash.config(state="disabled"); self.btn_listen.config(state="disabled")
        self.note.config(text=f"{what}...")
        box = {}

        def run():
            try:
                box["run"] = work()
            except Exception as exc:                            # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=run, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._job = self.after(300, wait); return
            self._job = None
            self.show(box)
        wait()

    def show(self, box: dict):
        self.btn_flash.config(state="normal"); self.btn_listen.config(state="normal")
        if "e" in box:
            self.note.config(text=f"Not done: {box['e']}."); return
        r = box["run"]
        self.out.delete("1.0", "end")
        self.out.insert("end", "\n".join(r.lines[-200:]))
        self.note.config(text=("Done. " if r.ok else "Not done. ") + " ".join(r.notes)
                         + (f" Log: {r.log.name}" if r.log else ""))

    def flash(self):
        self._go(lambda: self.B.flash(self.app.project, self._port()), "Flasher: uploading")

    def listen(self):
        port = self._port()
        if not port:
            self.note.config(text="No serial port to listen on."); return
        self._go(lambda: self.B.listen(self.app.project, port, 10.0), "Serial Monitor: listening")

    def destroy(self):
        # docs/design-rules.md, mistake 2: a pending after() outlives its widget.
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:                                    # noqa: BLE001
                pass
            self._job = None
        super().destroy()


class Gaming(tk.Toplevel):
    """Gaming (owner, 2026-10-21; nemo/gaming.py): your games from the
    Storeroom, each played by its console's emulator."""

    def __init__(self, app: NemoApp):
        super().__init__(app)
        _dialog(self, app, "Gaming", "760x520+200+70")
        from .. import gaming
        self.app, self.G = app, gaming
        gaming.make_shelves(app.cfg)
        ttk.Label(self, text="Gaming", style="PanelH2.TLabel").pack(anchor="w")
        ttk.Label(self, style="PanelMuted.TLabel", wraplength=720, justify="left", text=(
            "Your own game files go on the Storeroom's games shelf, in the folder for their "
            "console. Nemo never downloads games. In a game, Esc quits.")
                  ).pack(anchor="w", pady=(2, 6))
        mid = ttk.Frame(self, style="Panel.TFrame"); mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=("console", "name"), show="headings", height=10)
        for col, w, text in (("console", 160, "Console"), ("name", 420, "Game")):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=w, stretch=(col == "name"), anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.staff = tk.Text(self, height=4, wrap="word", relief="flat", bg=T.PANEL,
                             font=app.fonts["small"], highlightthickness=0)
        self.staff.pack(fill="x", pady=(6, 0))
        row = ttk.Frame(self, style="Panel.TFrame"); row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Play", style="Primary.TButton", command=self.play).pack(side="left")
        self.windowed = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="In a window", variable=self.windowed).pack(side="left", padx=8)
        ttk.Button(row, text="Open the games shelf", command=self.open_shelf).pack(side="left")
        ttk.Button(row, text="Note card", command=self.note_card).pack(side="left", padx=8)
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right")
        self.note = ttk.Label(self, style="PanelMuted.TLabel", text="", wraplength=720,
                              justify="left")
        self.note.pack(anchor="w", pady=(6, 0))
        self.refresh()

    def refresh(self):
        self.games = self.G.games(self.app.cfg)
        self.tree.delete(*self.tree.get_children())
        for n, g in enumerate(self.games):
            self.tree.insert("", "end", iid=str(n), values=(g.console.name, g.name))
        lines = []
        for c in self.G.CONSOLES:
            why = self.G.why_not(c, self.app.cfg)
            lines.append(f"{c.name} Emulator: {'ready' if not why else why}.")
        self.staff.config(state="normal"); self.staff.delete("1.0", "end")
        self.staff.insert("end", "  ".join(lines)); self.staff.config(state="disabled")
        if not self.games:
            self.note.config(text="No games yet: Open the games shelf and put your own game "
                                  "files in their console's folder.")

    def play(self):
        sel = self.tree.selection()
        if not sel:
            self.note.config(text="Choose a game first.")
            return None
        g = self.games[int(sel[0])]
        try:
            proc = self.G.play(g, self.app.cfg, fullscreen=not self.windowed.get())
        except RuntimeError as exc:
            self.note.config(text=f"{g.console.name} Emulator: {exc}.")
            return None
        busy = self.app.job and self.app.job.running
        wrong = self.G.shelf_check(g)
        self.note.config(text=f"The {g.console.name} Emulator is playing {g.name}. Esc quits."
                              + (" A step is running too, so the game may stutter."
                                 if busy else "")
                              + (f" Attendant: {wrong}." if wrong else ""))
        return proc

    def open_shelf(self):
        C.open_path(self.G.shelf(self.app.cfg, self.G.CONSOLES[0]).parent)

    def note_card(self):
        """The Writer's card for the chosen game, with your notes to edit."""
        sel = self.tree.selection()
        if not sel:
            self.note.config(text="Choose a game first.")
            return None
        g = self.games[int(sel[0])]
        win = tk.Toplevel(self)
        _dialog(win, self.app, f"{g.name}: note card", "520x520+260+90")
        text = tk.Text(win, height=16, wrap="word", relief="flat", bg=T.PANEL,
                       font=self.app.fonts["small"], highlightthickness=0)
        text.insert("end", self.G.card(self.app.cfg, g).split("\nNotes:")[0])
        text.config(state="disabled"); text.pack(fill="both", expand=True)
        ttk.Label(win, text="Your notes (where you got to, tips):", style="PanelMuted.TLabel").pack(anchor="w")
        mine = tk.Text(win, height=5, wrap="word", font=self.app.fonts["body"])
        mine.insert("end", self.G.notes(self.app.cfg).get(f"{g.console.key}/{g.path.name}", {}).get("notes", ""))
        mine.pack(fill="x")

        def save():
            self.G.write_note(self.app.cfg, g, mine.get("1.0", "end"))
            win.destroy()
        ttk.Button(win, text="Save", style="Primary.TButton", command=save).pack(side="right", pady=6)
        win.save, win.mine = save, mine             # for the tests
        return win


def main(prompt: bool = False) -> int:
    app = NemoApp()
    if prompt:
        # At boot Nemo opens at its home: Nemo Mode, or the prompt window
        # where gui.json says "home": "prompt". The workshop waits behind.
        app.withdraw()
        if C.load_settings().get("home", "nemo_mode") == "prompt":
            from .prompt import PromptWindow
            app.after(50, lambda: PromptWindow(app))
        else:
            from .nemomode import NemoMode
            app.after(50, lambda: NemoMode(app))
    app.mainloop()
    return 0
