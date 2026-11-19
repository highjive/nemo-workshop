"""The box under a department's bar (owner, 2026-11-09: "Nemo needs input method in
each department as to what is needed to be done in each department, not being directed
back to home screen").

What is typed is read by nemo/asks.py (code, no model) for the department in view,
and done there: a `nemo` command runs in this bar's own job, its words shown below
the box; a design or a story starts from the words; a window control is lit, never
pressed. Nothing here opens the home screen.

D278 (2026-11-18, on the Lifebook): there is one box, moved from department to
department, and it had one job and one reply area. A story asked for in the Library
went on printing in every department opened after it, and the next department's
request was refused as "still working on the last one". Now each department has its
own Desk: its own job, its own replies; the box shows the Desk of the department in
view, and a job's words go to the Desk that started it.

D279 (same day): a story asked for here needs the language model, and the box only
printed "Load one with: nemo mode talk" and stopped; the Workshop's window asks and
loads it. Here the owner has already asked for the work, so the box loads the mode
the command names (said, in the department's replies), then runs the command again.

docs/design-rules.md, mistake 2: the poll timer is tracked and cancelled in destroy().
"""
from __future__ import annotations

import json
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk

from . import controller as C
from . import theme as T
from .worker import Job

POLL_MS = 150
KEEP_LINES = 400            # each department keeps the last this many lines
NEEDS_MODEL = 3             # the CLI's return code when no model answers (cli.py)
# Commands whose parser takes --json: their "needs_model" event names the mode.
JSON_COMMANDS = ("run", "story", "draft")


def opens_a_window(argv: list[str]) -> bool:
    """Does `nemo <argv>` open another program's window to look at (a player, a viewer,
    an editor)? D282: on Linux that window opened under the department (see
    NemoApp.make_way)."""
    a = [x for x in argv if not x.startswith("--")]
    if a[:1] in (["theatre"], ["music"], ["games"]) and a[1:2] == ["play"]:
        return True
    if a[:2] == ["film", "edit"] and "--no-open" not in argv:
        return True
    if a[:2] == ["film", "animate"] and len(a) == 2:          # OpenToonz opens; a render does not
        return True
    return a[:1] == ["rebuild"] and a[1:2] != ["doctor"]


@dataclass
class Desk:
    """One department's side of the box."""
    lines: list = field(default_factory=list)
    job: Job | None = None
    argv: list = field(default_factory=list)     # what the job runs
    want: str | None = None                      # the mode a command said it needs
    after: list | None = None                    # run again once the mode is up
    loading: bool = False                        # the job is a `nemo mode`
    reloaded: bool = False                       # the job runs again after a load


class AskBar(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=T.SHELL_2)
        self.app, self.key, self._poll = app, None, None
        self.desks: dict[str, Desk] = {}
        self.label = tk.Label(self, bg=T.SHELL_2, fg=T.SHELL_INK, font=app.fonts["small"])
        self.label.grid(row=0, column=0, sticky="w", padx=(12, 6), pady=(6, 2))
        self.entry = ttk.Entry(self, font=app.fonts["body"])
        self.entry.grid(row=0, column=1, sticky="ew", pady=(6, 2))
        self.entry.bind("<Return>", lambda e: (self.send(), "break")[1])
        self.ask_btn = ttk.Button(self, text="Ask", command=self.send)
        self.ask_btn.grid(row=0, column=2, padx=6, pady=(6, 2))
        self.stop_btn = ttk.Button(self, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.grid(row=0, column=3, padx=(0, 12), pady=(6, 2))
        self.reply = tk.Text(self, height=4, wrap="word", bg=T.PANEL, fg=T.INK, relief="flat",
                             font=app.fonts["small"], state="disabled")
        self.reply.grid(row=1, column=0, columnspan=4, sticky="ew", padx=12, pady=(2, 6))
        self.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------ desks
    def desk(self, key: str | None = None) -> Desk | None:
        key = self.key if key is None else key
        if key is None:
            return None
        return self.desks.setdefault(key, Desk())

    @property
    def job(self) -> Job | None:
        """The job of the department in view (None when it has none)."""
        d = self.desk()
        return d.job if d else None

    def busy(self) -> list[str]:
        """The departments with a job still running."""
        return [k for k, d in self.desks.items() if d.job is not None]

    # ------------------------------------------------------------------ in view
    def show_for(self, key: str | None):
        """The bar for the department `key`; hidden for a window that is none."""
        from .. import asks
        if key is None:
            self.key = None
            return False
        if key != self.key:
            self.key = key
            self._show_desk()
        here = asks.called(key)
        self.label.config(text=f"Ask {here}:")
        return True

    def _show_desk(self):
        d = self.desk()
        self.reply.config(state="normal")
        self.reply.delete("1.0", "end")
        if d and d.lines:
            self.reply.insert("end", "\n".join(d.lines) + "\n")
            self.reply.see("end")
        self.reply.config(state="disabled")
        self.stop_btn.config(state="normal" if d and d.job is not None else "disabled")

    def focus(self):
        self.entry.focus_set()

    # ------------------------------------------------------------------ talking
    def clear(self):
        d = self.desk()
        if d is not None:
            d.lines.clear()
        self._show_desk()

    def tell(self, text: str, key: str | None = None):
        """Add `text` to department `key`'s replies (the one in view if None)."""
        if not text:
            return
        key = self.key if key is None else key
        d = self.desk(key)
        if d is None:
            return
        new = text.rstrip().split("\n")
        d.lines.extend(new)
        del d.lines[:-KEEP_LINES]
        if key != self.key:
            return                      # kept for when that department is opened
        self.reply.config(state="normal")
        self.reply.insert("end", "\n".join(new) + "\n")
        lines = int(self.reply.index("end-1c").split(".")[0])
        if lines > KEEP_LINES:
            self.reply.delete("1.0", f"{lines - KEEP_LINES}.0")
        self.reply.see("end")
        self.reply.config(state="disabled")

    def send(self, text: str | None = None):
        """Do what the owner typed, in this department."""
        from .. import asks
        words = (self.entry.get() if text is None else text).strip()
        if self.key is None:
            return None
        if self.job is not None and self.job.running:
            self.tell("Still working on the last one here: Stop it first, or wait.")
            return None
        self.entry.delete(0, "end")
        project = getattr(self.app, "project", None)
        reply = asks.answer(self.key, words, {"project": project.root.name if project else None})
        if words:
            self.tell(f"> {words}")
        self.tell(reply.say)
        if reply.kind == asks.RUN:
            self.run(reply.argv)
        elif reply.kind == asks.WINDOW:
            self.open_window(reply.button)
        elif reply.kind == asks.STORY:
            self.story(reply.text)
        elif reply.kind == asks.DESIGN:
            self.design(reply.text)
        return reply

    # ------------------------------------------------------------------ doing
    def run(self, argv: list[str], key: str | None = None, loading: bool = False,
            reloaded: bool = False):
        """Run `nemo <argv>` for department `key` (the one in view)."""
        key = self.key if key is None else key
        d = self.desk(key)
        if d is None:
            return
        args = list(argv)
        if args and args[0] in JSON_COMMANDS and "--json" not in args:
            args.append("--json")            # so a missing model is said by name
        d.job, d.argv, d.want = Job(C.nemo_argv(*args)).start(), list(argv), None
        d.loading, d.reloaded = loading, reloaded
        if key == self.key:
            self.stop_btn.config(state="normal")
        if self._poll is None:
            self._poll = self.after(POLL_MS, self._drain)

    def _drain(self):
        self._poll = None
        for key, d in list(self.desks.items()):
            if d.job is not None:
                self._drain_desk(key, d)
        if self.busy():
            self._poll = self.after(POLL_MS, self._drain)

    def _read(self, key: str, d: Desk):
        for line in d.job.drain():
            if line.startswith("@@NEMO "):
                try:
                    ev = json.loads(line[7:])
                except ValueError:
                    continue
                if ev.get("state") == "needs_model" and ev.get("mode"):
                    d.want = ev["mode"]
            else:
                self.tell(line, key)

    def _drain_desk(self, key: str, d: Desk):
        job = d.job
        self._read(key, d)
        if job.running:
            return
        self._read(key, d)
        d.job = None
        if key == self.key:
            self.stop_btn.config(state="disabled")
        if job.stopped:
            d.after = None
            self.tell("Stopped.", key)
        elif d.loading:
            then, d.after = d.after, None
            if job.returncode == 0 and then:
                self.tell("The model is loaded; carrying on.", key)
                self.run(then, key, reloaded=True)
            elif job.returncode not in (0, None):
                self.tell("The model did not load: what it said is above. The Doctors "
                          "can look at why.", key)
        elif job.returncode == NEEDS_MODEL and d.want and d.argv and not d.reloaded:
            self.load_model(d.want, d.argv, key)
        elif job.returncode == NEEDS_MODEL and d.reloaded:
            self.tell("The model was loaded but does not answer. The Doctors can look at "
                      "why.", key)
        elif job.returncode not in (0, None):
            self.tell("(It did not finish cleanly: what it said is above.)", key)
        elif job.returncode == 0 and d.argv and opens_a_window(d.argv):
            make_way = getattr(self.app, "make_way", None)
            if make_way is not None and make_way():
                self.tell("Nemo has stepped aside so you can see it; click Nemo on the taskbar "
                          "to come back.", key)
        room = getattr(self.app, "_embedded", None)          # its list, read again (nemo/desks.py)
        if not d.loading and getattr(room, "key", None) == key and hasattr(room, "refresh_list"):
            try:
                room.refresh_list()
            except tk.TclError:
                pass
        if not d.loading and getattr(self.app, "project", None) is not None:
            try:
                self.app.refresh_steps(); self.app.refresh_files()
            except (AttributeError, tk.TclError):
                pass

    def load_model(self, mode: str, then: list[str], key: str | None = None):
        """Load `mode`, then run `then` again, for department `key`."""
        label = next((lab for k, lab, _ in C.MODES if k == mode), mode)
        self.tell(f"Loading the model first ({label}); then it carries on. On the "
                  "laptop this takes a minute or two.", key)
        box = getattr(self.app, "mode_box", None)
        if box is not None:
            try:
                box.set(label)
            except tk.TclError:
                pass
        d = self.desk(key)
        self.run(["mode", mode], key, loading=True)
        d.after = list(then)

    def stop(self):
        d = self.desk()
        if d is not None and d.job is not None:
            d.after = None
            d.job.stop()

    def open_window(self, button: str):
        from .app import light_button
        win = self.app.real_window(self.key)
        if win is not None and button:
            self.after(150, lambda: light_button(win, button))

    def story(self, text: str):
        from . import prompt_logic as L
        folder = L.file_story(self.app.cfg.path("paths.stories"), text)
        self.tell(f"Kept as the story '{folder.name}'; it is in the Story list.")
        self.run(["story", "write", folder.name])

    def design(self, text: str):
        from . import prompt_logic as L
        name = L.name_for(text, set(C.list_projects(self.app.cfg)))
        try:
            proj = C.create_project(name, self.app.cfg)
        except ValueError as exc:
            self.tell(str(exc))
            return
        b = proj.load_brief(); b.function = text; proj.save_brief(b)
        self.tell(f"Project '{proj.root.name}' made; the Writer drafts its brief in the "
                  "Workshop.")
        self.app.refresh_projects(select=proj.root.name)
        self.app.back_to_workshop()
        self.app.tabs.select(self.app.tab_brief)
        self.app.draft_brief()

    def destroy(self):
        if self._poll is not None:
            try:
                self.after_cancel(self._poll)
            except (tk.TclError, ValueError):
                pass
            self._poll = None
        super().destroy()
