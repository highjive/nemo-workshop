"""The box under a department's bar (owner, 2026-11-09: "Nemo needs input method in
each department as to what is needed to be done in each department, not being directed
back to home screen").

What is typed is read by nemo/asks.py (code, no model) for the department in view,
and done there: a `nemo` command runs in this bar's own job, its words shown below
the box; a design or a story starts from the words; a window control is lit, never
pressed. Nothing here opens the home screen.

docs/design-rules.md, mistake 2: the poll timer is tracked and cancelled in destroy().
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import controller as C
from . import theme as T
from .worker import Job

POLL_MS = 150
KEEP_LINES = 400            # the reply area keeps the last this many lines


class AskBar(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=T.SHELL_2)
        self.app, self.key, self.job, self._poll = app, None, None, None
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

    # ------------------------------------------------------------------ in view
    def show_for(self, key: str | None):
        """The bar for the department `key`; hidden for a window that is none."""
        from .. import asks
        if key is None:
            self.key = None
            return False
        if key != self.key:
            self.key = key
            self.clear()
        here = asks.called(key)
        self.label.config(text=f"Ask {here}:")
        return True

    def focus(self):
        self.entry.focus_set()

    # ------------------------------------------------------------------ talking
    def clear(self):
        self.reply.config(state="normal")
        self.reply.delete("1.0", "end")
        self.reply.config(state="disabled")

    def tell(self, text: str):
        if not text:
            return
        self.reply.config(state="normal")
        self.reply.insert("end", text.rstrip() + "\n")
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
            self.tell("Still working on the last one: Stop it first, or wait.")
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
    def run(self, argv: list[str]):
        self.job = Job(C.nemo_argv(*argv)).start()
        self.stop_btn.config(state="normal")
        self._poll = self.after(POLL_MS, self._drain)

    def _drain(self):
        self._poll = None
        job = self.job
        if job is None:
            return
        for line in job.drain():
            if not line.startswith("@@NEMO "):
                self.tell(line)
        if job.running:
            self._poll = self.after(POLL_MS, self._drain)
            return
        for line in job.drain():
            if not line.startswith("@@NEMO "):
                self.tell(line)
        self.stop_btn.config(state="disabled")
        if job.stopped:
            self.tell("Stopped.")
        elif job.returncode not in (0, None):
            self.tell("(It did not finish cleanly: what it said is above.)")
        self.job = None
        if getattr(self.app, "project", None) is not None:
            try:
                self.app.refresh_steps(); self.app.refresh_files()
            except (AttributeError, tk.TclError):
                pass

    def stop(self):
        if self.job is not None:
            self.job.stop()

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
