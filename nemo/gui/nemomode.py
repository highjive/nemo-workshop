"""Nemo Mode: the departments as a full-screen shelf (owner, 2026-11-04:
"use bazzite as reference for nemo departments interface"; he chose a new
home in the manner of Bazzite's Gaming Mode).

Bazzite's Gaming Mode is Valve's Steam interface, so its PATTERN is taken,
not its look: a full screen worked from the keyboard (or a pad through a
keyboard mapper; Tk reads no pad itself), big artwork tiles on a shelf, the
chosen one large with its picture filling the background, a status line,
and the desktop one key away. In Nemo's walnut and brass, with the
departments' own paintings (~/.nemo/art).

  Left / Right   choose a department (Home / End: first and last)
  Enter, Space   open it (its painted room)
  A              Ask Nemo: the prompt window, as before
  Esc            the desktop: the Workshop window
  F11            full screen on and off
"""
from __future__ import annotations

import time
import tkinter as tk

from . import controller as C
from . import theme as T

TILE = (300, 170)        # a tile on the shelf
BIG = (380, 214)         # the chosen one
GAP = 26
CLOCK_MS = 20_000


class NemoMode(tk.Toplevel):
    def __init__(self, app, fullscreen: bool = True):
        super().__init__(app)
        from ..staff import DEPARTMENTS, team
        if hasattr(app, "brand"):
            app.brand(self)
        self.app, self.team = app, team
        self.title("Nemo")
        self.configure(bg=T.SHELL)
        self.keys = list(DEPARTMENTS)
        self.depts = DEPARTMENTS
        saved = C.load_settings().get("nemo_mode_at")
        self.at = self.keys.index(saved) if saved in self.keys else 0
        self._clock_job = None
        self._tiles, self._big, self._backs = {}, {}, {}
        self.W, self.H = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{self.W}x{self.H}+0+0")
        self.fullscreen = fullscreen
        if fullscreen:
            self.attributes("-fullscreen", True)
        self.canvas = tk.Canvas(self, width=self.W, height=self.H, bg=T.SHELL,
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        for seq, fn in (("<Left>", lambda e: self.move(-1)), ("<Right>", lambda e: self.move(1)),
                        ("<Home>", lambda e: self.choose(0)),
                        ("<End>", lambda e: self.choose(len(self.keys) - 1)),
                        ("<Return>", lambda e: self.go_in()), ("<space>", lambda e: self.go_in()),
                        ("<KeyPress-a>", lambda e: self.ask()), ("<KeyPress-A>", lambda e: self.ask()),
                        ("<Escape>", lambda e: self.desktop()), ("<F11>", lambda e: self.toggle())):
            self.bind(seq, fn)
        self.bind("<Configure>", self._resized, add="+")
        self.protocol("WM_DELETE_WINDOW", self.desktop)
        self.draw()
        self.tick()
        self.focus_force()

    # ------------------------------------------------------------ pictures
    def _scene(self, key: str):
        from .. import art
        p = art.scene(key)
        return p if p.is_file() else C.department_card(key)

    def _fit(self, key: str, size):
        from PIL import Image
        w, h = size
        try:
            im = Image.open(self._scene(key)).convert("RGB")
        except OSError:
            return Image.new("RGB", size, (33, 23, 15))
        s = max(w / im.width, h / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        return im.crop(((im.width - w) // 2, (im.height - h) // 2,
                        (im.width - w) // 2 + w, (im.height - h) // 2 + h))

    def _photo(self, cache: dict, key: str, size, back=False):
        from PIL import ImageEnhance, ImageFilter, ImageTk
        if (key, size) not in cache:
            im = self._fit(key, size)
            if back:            # behind the words: softened and dimmed, so text reads on it
                im = ImageEnhance.Brightness(im.filter(ImageFilter.GaussianBlur(5))).enhance(0.42)
            cache[(key, size)] = ImageTk.PhotoImage(im)
        return cache[(key, size)]

    # ------------------------------------------------------------- drawing
    def draw(self):
        c, W, H = self.canvas, self.W, self.H
        c.delete("all")
        key = self.keys[self.at]
        dept = self.depts[key]
        c.create_image(0, 0, image=self._photo(self._backs, key, (W, H), back=True), anchor="nw")
        # The status line.
        c.create_rectangle(0, 0, W, 56, fill=T.SHELL, outline="")
        c.create_line(0, 56, W, 56, fill=T.BRASS, width=2)
        c.create_text(28, 28, anchor="w", text="Nemo", fill=T.BRASS, font=self.app.fonts["title"])
        self._status = c.create_text(130, 28, anchor="w", text="", fill=T.SHELL_INK,
                                     font=self.app.fonts["small"])
        self._clock = c.create_text(W - 30, 28, anchor="e", text="", fill=T.SHELL_INK,
                                    font=self.app.fonts["h2"])
        self._button("Desktop  (Esc)", W - 130, self.desktop, "desk")
        self._button("Ask Nemo  (A)", W - 300, self.ask, "ask")
        # The chosen department: what it is.
        people = self.team(key)
        c.create_text(60, 120, anchor="nw", text=dept.name, fill=T.SHELL_INK,
                      font=(self.app.fonts["title"][0], T.scaled(34, getattr(self.app, "text_percent", 100)), "bold"))
        c.create_text(62, 186, anchor="nw", text=dept.job, fill=T.SHELL_INK, width=min(760, W - 120),
                      font=(self.app.fonts["body"][0], T.scaled(13, getattr(self.app, "text_percent", 100))))
        c.create_text(62, 186 + 24 * (1 + len(dept.job) // 90), anchor="nw",
                      text=f"{len(people)} on the team  ·  Enter to go in",
                      fill=T.BRASS, font=self.app.fonts["strong"])
        # The shelf, scrolled so the chosen tile is in view.
        y_mid = H - 40 - BIG[1] // 2 - 30
        step = TILE[0] + GAP
        first_x = max(60, W // 2 - BIG[0] // 2 - self.at * step)
        if first_x + self.at * step + BIG[0] > W - 40:
            first_x = W - 40 - BIG[0] - self.at * step
        self._hits = []
        x = first_x
        for i, k in enumerate(self.keys):
            big = i == self.at
            w, h = BIG if big else TILE
            if x > W or x + w < 0:
                x += (w + GAP)
                continue
            y = y_mid - h // 2
            if big:
                c.create_rectangle(x - 6, y - 6, x + w + 6, y + h + 6, outline=T.BRASS, width=4)
            c.create_image(x, y, image=self._photo(self._big if big else self._tiles, k, (w, h)),
                           anchor="nw")
            if not big:
                c.create_rectangle(x, y, x + w, y + h, outline=T.SHELL_2, width=2)
            label = c.create_text(x + w // 2, y + h + 18, text=self.depts[k].name,
                                  fill=T.SHELL_INK if big else T.SELECT,
                                  font=self.app.fonts["strong" if big else "small"])
            self._hits.append((x, y, x + w, y + h, i))
            c.tag_bind(label, "<Button-1>", lambda e, i=i: self.click(i))
            x += w + GAP
        c.create_text(W // 2, H - 14, text="← → choose   ·   Enter open   ·   "
                      "A ask Nemo   ·   Esc desktop   ·   F11 full screen",
                      fill=T.SELECT, font=self.app.fonts["small"])
        c.bind("<Button-1>", self._clicked)
        self._update_status()

    def _button(self, text, x, command, tag):
        c = self.canvas
        t = c.create_text(x, 28, text=text, fill=T.INK, font=self.app.fonts["small"], tags=(tag,))
        x0, y0, x1, y1 = c.bbox(t)
        r = c.create_rectangle(x0 - 12, 14, x1 + 12, 42, fill=T.BRASS, outline="", tags=(tag,))
        c.tag_raise(t, r)
        c.tag_bind(tag, "<Button-1>", lambda e: command())

    def _clicked(self, event):
        for x0, y0, x1, y1, i in getattr(self, "_hits", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.click(i)
                return

    def _update_status(self):
        from ..modes import current
        from ..platform_probe import mem_available_mb, mem_total_mb
        st = current()
        model = f"Model: {st.model} ({st.name})" if st.running else "Model: off"
        total, free = mem_total_mb(), mem_available_mb()
        mem = f"   ·   {free / 1024:.1f} of {total / 1024:.1f} GB free" if total else ""
        self.canvas.itemconfig(self._status, text=model + mem)
        self.canvas.itemconfig(self._clock, text=time.strftime("%H:%M"))

    def tick(self):
        self._update_status()
        self._clock_job = self.after(CLOCK_MS, self.tick)

    def _resized(self, event):
        if event.widget is self and (abs(event.width - self.W) > 8 or abs(event.height - self.H) > 8):
            self.W, self.H = event.width, event.height
            self._backs.clear()
            self.draw()

    # -------------------------------------------------------------- moving
    def choose(self, i: int):
        self.at = max(0, min(len(self.keys) - 1, i))
        settings = C.load_settings()
        settings["nemo_mode_at"] = self.keys[self.at]
        C.save_settings(settings)
        self.draw()

    def move(self, by: int):
        self.choose(self.at + by)

    def click(self, i: int):
        if i == self.at:
            self.go_in()
        else:
            self.choose(i)

    def go_in(self):
        """Into the chosen department's painted room, in Nemo's window."""
        key = self.keys[self.at]
        self.withdraw()
        self.app.deiconify()
        try:
            self.app.state("zoomed")
        except tk.TclError:
            pass
        return self.app.open_department(key)

    def ask(self):
        """The prompt window, as Home was before Nemo Mode."""
        from .prompt import PromptWindow
        self.withdraw()
        for w in self.app.winfo_children():
            if isinstance(w, PromptWindow) and w.winfo_exists():
                w.deiconify(); w.lift()
                return w
        return PromptWindow(self.app)

    def desktop(self):
        """Leave Nemo Mode for the Workshop window (the desktop)."""
        self.withdraw()
        self.app.back_to_workshop()
        self.app.deiconify(); self.app.lift()

    def toggle(self):
        self.fullscreen = not self.fullscreen
        self.attributes("-fullscreen", self.fullscreen)

    def come_back(self):
        self.deiconify(); self.lift(); self.focus_force()
        self.draw()

    def destroy(self):
        # docs/design-rules.md, mistake 2: a pending after() outlives its widget.
        if self._clock_job:
            try:
                self.after_cancel(self._clock_job)
            except Exception:                                    # noqa: BLE001
                pass
            self._clock_job = None
        super().destroy()


def find(app) -> NemoMode | None:
    for w in app.winfo_children():
        if isinstance(w, NemoMode) and w.winfo_exists():
            return w
    return None
