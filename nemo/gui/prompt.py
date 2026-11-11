"""The prompt window: where Nemo opens at boot.

Nemo's cog fills it, glowing, with the prompt in the middle (owner,
2026-10-22): a box to type a request in, and a Speak button (offline,
nemo/speech.py; what is heard goes into the box to be checked and sent). The
glow breathes slowly while Nemo waits, quickly while it works, and brightens
with the voice it hears. A request goes to the workshop window as a new project,
or into the Story list; prompt_logic decides which.
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from . import controller as C
from . import prompt_logic as L
from . import theme as T


class Glow(tk.Canvas):
    """Nemo's cog, filling the window, glowing (owner, 2026-10-22: "remove the
    rings and have a glow effect from around cog with lighter glow on
    department logos"). The light breathes slowly while Nemo waits, quickly
    while it works, and brightens with the microphone's level, so it is
    plain at once whether Nemo can hear you.

    The frames are made once, by Pillow, from the cog and its two glow masks
    (tools/draw_logo.py makes them), and shown in turn. Without the pictures
    or Pillow's Tk bridge it is a plain background and nothing else changes.
    Its timer is kept and cancelled in destroy(): a Tk after() outlives its
    widget otherwise (docs/design-rules.md, mistake 2)."""

    LEVELS = 10
    FRAME_MS = 60

    def __init__(self, master, side=220, bg=T.SHELL):
        super().__init__(master, width=side, height=side, bg=bg, highlightthickness=0)
        self.side, self.phase, self.busy, self.voice = side, 0.0, False, 0.0
        self.frames, self._timer, self._shown = self._make_frames(side), None, None
        self.picture = self.create_image(side // 2, side // 2) if self.frames else None
        self._step()

    @staticmethod
    def _make_frames(side: int) -> list:
        try:
            from PIL import Image, ImageTk
            from . import controller as C
            base = Image.open(C.logo(1024)).convert("RGB").resize((side, side), Image.LANCZOS)
            halo = Image.open(C.logo_part("halo")).convert("L").resize((side, side), Image.LANCZOS)
            logos = Image.open(C.logo_part("logos")).convert("L").resize((side, side), Image.LANCZOS)
        except (ImportError, OSError, tk.TclError):
            return []
        frames = []
        for k in range(Glow.LEVELS):
            level = k / (Glow.LEVELS - 1)
            im = base.copy()
            im.paste((255, 186, 90), (0, 0), halo.point(lambda v: int(v * (0.3 + 0.55 * level))))
            im.paste((255, 232, 168), (0, 0), logos.point(lambda v: int(v * (0.15 + 0.45 * level))))
            frames.append(ImageTk.PhotoImage(im))
        return frames

    def set_busy(self, busy: bool):
        self.busy = busy

    def set_voice(self, level: float):
        """How loud the microphone is, 0 to 1: the glow brightens with it."""
        self.voice = max(0.0, min(1.0, level))

    def level(self) -> float:
        breath = 0.5 + 0.5 * math.sin(self.phase)
        if self.voice:
            return min(1.0, 0.35 + self.voice * 6)
        return breath if self.busy else 0.15 + 0.45 * breath

    def _step(self):
        self.phase += 0.22 if self.busy else 0.05
        if self.frames:
            k = round(self.level() * (len(self.frames) - 1))
            if k != self._shown:
                self.itemconfig(self.picture, image=self.frames[k])
                self._shown = k
        self._timer = self.after(self.FRAME_MS, self._step)

    def destroy(self):
        if self._timer is not None:
            try:
                self.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        super().destroy()


# How far from the middle the panel may reach before it covers a tooth's
# logo, as a share of the picture's side (the logos sit at R_LOGO, 300 of
# 1024, in tools/draw_logo.py, and are about 90 across).
CLEAR = (300 - 48) / 1024


class PromptWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        if hasattr(app, "brand"):
            app.brand(self)                        # the cog on its title bar and taskbar button
        self.app = app
        self.title("Nemo")
        self.configure(bg=T.SHELL)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        side = max(360, min(780, sw - 40, sh - 80))
        self.geometry(f"{side}x{side}+{(sw - side) // 2}+{max(0, (sh - side) // 3)}")
        self.resizable(False, False)

        # The loading page: the cog, glowing, with the prompt in the middle of
        # it (owner, 2026-10-22).
        self.glow = Glow(self, side=side)
        self.glow.pack(fill="both", expand=True)
        self._cog = self.glow.frames[0] if self.glow.frames else None
        # The panel's corners stay inside the circle the logos stand round:
        # the first, square one covered the four diagonal teeth (2026-10-22).
        r = side * CLEAR
        width, height = int(r * 1.74), int(r * 1.0)      # (w/2)^2 + (h/2)^2 = r^2
        bg, ink, muted = "#21170F", "#E8D6AE", "#B39A72"
        panel = tk.Frame(self.glow, bg=bg, highlightthickness=2,
                         highlightbackground="#C49A52", padx=8, pady=4)
        self._panel = self.glow.create_window(side // 2, side // 2, window=panel,
                                              width=width, height=height)
        self._card = None                     # the department card, while one is shown
        self.heading = tk.Label(panel, text="What would you like to do?", bg=bg, fg=ink,
                                font=app.fonts["h2"])
        self.heading.pack(pady=(2, 3))
        self.box = tk.Text(panel, height=2, wrap="word", font=app.fonts["body"],
                           relief="flat", padx=6, pady=4)
        self.box.pack(fill="x")
        self.box.bind("<Control-Return>", lambda e: (self.send(), "break")[1])
        self.box.focus_set()

        row = tk.Frame(panel, bg=bg); row.pack(pady=(5, 2))
        small = app.fonts["small"]

        def button(text, command, main=False):
            b = tk.Button(row, text=text, command=command, font=small, relief="flat", bd=0,
                          padx=7, pady=2, cursor="hand2",
                          bg="#C49A52" if main else "#4A3624", fg="#21170F" if main else ink,
                          activebackground="#E0B868", activeforeground="#21170F")
            b.pack(side="left", padx=2)
            return b
        button("Send", self.send, main=True)
        self.mic = button("Speak", self.toggle_speech)
        self._recorder = None
        self._speech_timer = None
        self._heard = None
        button("Read aloud", self.read_aloud)
        # No Workshop button (owner, 2026-10-25): from home he says what he
        # wants to do and Nemo takes him to its department.
        self._history, self._last_request, self._talk_job = [], "", None

        self.status = tk.Label(panel, text="Tell Nemo what you want to do. Ctrl+Enter sends it.",
                               bg=bg, fg=muted, font=small, wraplength=width - 24, justify="center")
        self.status.pack(pady=(2, 0))
        # The department Nemo suggests, on its own row: pressed, its card
        # comes up; nothing changes department until then (owner, 2026-10-23).
        self.suggest_btn = tk.Button(panel, text="", font=small, relief="flat", bd=0, padx=7,
                                     pady=2, cursor="hand2", bg="#4A3624", fg=ink,
                                     activebackground="#E0B868", activeforeground="#21170F")
        # While Nemo talks the panel grows downwards over the lower teeth:
        # a conversation did not fit in the first, logo-clear size.
        self._panel_size = (side // 2, height, int(r * 1.7))
        self.protocol("WM_DELETE_WINDOW", self.quit_nemo)   # closing home closes Nemo
        try:
            self.offer_update()
        except Exception:                                        # noqa: BLE001
            pass                                                 # an offer never stops the start

    def tell(self, text: str):
        self.status.config(text=text)

    def read_aloud(self):
        """The Linguist reads Nemo's last words out (owner, 2026-10-21)."""
        from .. import voice
        said = self.status.cget("text").strip()
        if not said:
            return
        ok, why = voice.speak(said)
        if not ok:
            self.status.config(text=f"{said}\n(Not read aloud: {why}.)")

    # ------------------------------------------------------------ speech
    def toggle_speech(self):
        """Press to talk, press again to stop. What was heard goes into the
        box to be read and sent by hand; nothing is sent on its own."""
        from .. import speech
        if self._recorder is None:
            ok, why = speech.available()
            if not ok:
                self.tell(f"Speaking is not set up here: {why}. Type instead.")
                return
            self._recorder = speech.Recorder()
            try:
                switched = self._recorder.start()
            except OSError as exc:
                self._recorder = None
                self.tell(str(exc)); return
            self.glow.set_busy(True)
            self.mic.config(text="Stop listening")
            self.tell("Listening: the cog glows brighter when it hears you. Press Stop listening "
                      "when you have finished."
                      + (f" (Microphone switched on: {', '.join(switched)}.)" if switched else ""))
            self._level_timer = self.after(200, self._show_level)
            return
        rec, self._recorder = self._recorder, None
        self._stop_level()
        self.mic.config(text="Speak", state="disabled")
        self.tell("Working out what you said...")
        import threading

        def work():
            try:
                path = rec.stop()
                stats = speech.measure(path)
                text = "" if stats[1] < speech.SILENT else speech.transcribe(path)
                speech.keep_last(path, text, stats)
                self._heard = ("ok", text, stats)
                try:
                    path.unlink()
                except OSError:
                    pass
            except Exception as exc:                         # noqa: BLE001
                self._heard = ("error", str(exc), None)
        threading.Thread(target=work, daemon=True).start()
        self._speech_timer = self.after(200, self._speech_done)

    def _speech_done(self):
        if self._heard is None:
            self._speech_timer = self.after(200, self._speech_done)
            return
        self._speech_timer = None
        kind, text, stats = self._heard
        self._heard = None
        self.glow.set_busy(False)
        self.mic.config(state="normal")
        from .. import speech
        if kind == "error":
            self.tell(f"Could not hear that: {text}")
        elif stats and stats[1] < speech.SILENT:
            self.tell(f"The microphone heard silence ({stats[0]:.0f} s, loudest {stats[1]:.1%}). "
                      "It may be muted or turned down: in a terminal run alsamixer, press F4 "
                      "for the inputs, and turn the microphone up (M unmutes, space "
                      "switches capture on). Then try again.")
        elif not text:
            self.tell(f"It heard sound (loudest {stats[1]:.0%}) but made out no words. Speak "
                      "clearly, close to the laptop, and try again.")
        else:
            current = self.box.get("1.0", "end").strip()
            self.box.insert("end", (" " if current else "") + text)
            self.tell("Check the words, change any that are wrong, then Send.")

    def _show_level(self):
        rec = self._recorder
        if rec is None:
            self._level_timer = None
            return
        level = rec.level()
        if level is not None:
            self.glow.set_voice(level)
        self._level_timer = self.after(200, self._show_level)

    def _stop_level(self):
        if getattr(self, "_level_timer", None) is not None:
            try:
                self.after_cancel(self._level_timer)
            except tk.TclError:
                pass
            self._level_timer = None
        self.glow.set_voice(0.0)

    def destroy(self):
        self._stop_level()
        if getattr(self, "_calm_job", None) is not None:   # the breathing guide
            try:
                self.after_cancel(self._calm_job)
            except tk.TclError:
                pass
            self._calm_job = None
        if getattr(self, "_leave_job", None) is not None:  # D273: into a story's department
            try:
                self.after_cancel(self._leave_job)
            except tk.TclError:
                pass
            self._leave_job = None
        if getattr(self, "_talk_job", None) is not None:   # Nemo's answer, still coming
            try:
                self.after_cancel(self._talk_job)
            except tk.TclError:
                pass
            self._talk_job = None
        if self._speech_timer is not None:
            try:
                self.after_cancel(self._speech_timer)
            except tk.TclError:
                pass
            self._speech_timer = None
        if self._recorder is not None:
            try:
                self._recorder.stop()
            except Exception:                                # noqa: BLE001
                pass
            self._recorder.discard()                         # D274: closed mid-recording
            self._recorder = None
        super().destroy()

    # ------------------------------------------------------------ the home scene
    def send(self):
        """The home scene: he talks with Nemo, his companion (owner,
        2026-10-23). Naming a department brings up its card, carrying his
        last request; anything else Nemo answers as itself, suggesting the
        department that could help without changing to it."""
        request = self.box.get("1.0", "end").strip()
        if not request:
            self.tell("Type what you would like first.")
            return
        self.box.delete("1.0", "end")
        if self.own_tools(request):
            return
        named = L.named_department(request)
        if named:
            self.show_department(self._last_request or request, named, [])
            return
        self._last_request = request
        key, words = L.department_for(request)
        self.talk(request, key, words)

    def own_tools(self, request: str) -> bool:
        """His tools, answered by code before the model (owner's yes,
        2026-10-23): journal, check-in, calm, and the Doctors' memory check."""
        from .. import companion, memorycheck
        low = request.strip().lower()
        if low.startswith("memory check"):
            words = memorycheck.start()
            self.say_back("Remember these five words: " + ", ".join(words) + ". Talk about "
                          "something else for a few minutes, then say recall and the words.")
            return True
        if low.startswith("recall"):
            try:
                score, missed, trend = memorycheck.recall(request[6:])
            except ValueError as exc:
                self.say_back(str(exc).capitalize() + "."); return True
            self.say_back(f"{score} of 5." + (f" Not recalled: {', '.join(missed)}." if missed else "")
                          + " " + trend)
            return True
        if low.startswith(("my letters", "read letter", "read my letter")):
            self.say_back(self.letters(low)); return True
        if low in ("update", "update nemo", "use the update"):
            self.update_nemo(); return True
        cmd = companion.command(request)
        if cmd is None:
            return False
        what, value = cmd
        if what == "journal":
            self.say_back(companion.keep_journal(self.app.cfg, value))
        elif what == "ask-checkin":
            self.say_back("Mood 1 to 5, and sleep 1 to 5? Say it like this: mood 3 sleep 4.")
        elif what == "checkin":
            self.say_back(companion.check_in(self.app.cfg, *value))
        else:
            self.calm(list(companion.CALM_STEPS))
        return True

    def letters(self, low: str) -> str:
        """His letters from the vault: only while it is open and only if he
        allowed the companion in (nemo/vault.py)."""
        v = getattr(self.app, "vault", None)
        if v is None:
            return "The vault is locked. Open it in the Storeroom first."
        from .. import vault
        if not vault.companion_allowed(v.root):
            return "You have not allowed me to read your letters; that is set in the vault."
        letters = v.letters_for_companion()
        if not letters:
            return "There are no plain-text letters in the vault for me to read."
        if low.startswith("my letters"):
            return "Your letters: " + "; ".join(name for name, _ in letters) + "."
        want = low.split("letter", 1)[1].strip(" :")
        for name, text in letters:
            if want and want in name.lower():
                return text
        return "No letter by that name. Say my letters to hear their names."

    def offer_update(self):
        """At start: say so if the Windows disk holds a newer Nemo (nemo/update.py)."""
        from .. import update
        found = update.available()
        if found is not None:
            self.tell(update.describe(found) + " Say update to use it.")
        elif update.running() is not None:
            self.tell(f"Running the update, commit {update.running().name[:7]}.")
        return found

    def update_nemo(self):
        from .. import update
        found = update.available()
        if found is None:
            self.say_back("No newer Nemo is on the Windows disk."); return
        try:
            dest = update.apply(found)
        except RuntimeError as exc:
            self.say_back(f"Not updated: {exc}."); return
        self.say_back("The new Nemo is ready. Starting it now.")
        self.app.after(1500, lambda: update.relaunch(dest))

    def say_back(self, text: str):
        self.tell(text)
        try:
            self.app.announce(text, cue="")   # talk: the voice, no chime
        except Exception:                                        # noqa: BLE001
            pass

    def calm(self, steps: list):
        """The breathing guide: each step said, the cog brightening as he
        breathes in and dimming as he breathes out."""
        if not steps:
            self.glow.set_voice(0.0)
            self._calm_job = None
            self.say_back("Done. Take your time.")
            return
        (word, secs), rest = steps[0], steps[1:]
        self.glow.set_voice(0.0 if word == "Breathe out" else 0.1)
        self.say_back(f"{word}... {secs}")
        self._calm_job = self.after(secs * 1000, lambda: self.calm(rest))

    def talk(self, request: str, key: str, words: list[str], router=None):
        """Nemo answers in the background (the talk model is slow here)."""
        import threading
        from .. import companion
        from ..staff import DEPARTMENTS
        names = {k: d.name for k, d in DEPARTMENTS.items()}
        offer = companion.suggestion(key, words, names)
        self.suggest_btn.pack_forget()
        self.glow.set_busy(True)
        self.tell("Nemo is listening...")
        box = {}

        def work():
            r = router
            if r is None:
                from ..router import Router
                r = Router(self.app.cfg)
            box["reply"] = companion.reply(r, request, self._history)
        t = threading.Thread(target=work, daemon=True); t.start()

        def wait():
            if t.is_alive():
                self._talk_job = self.after(300, wait); return
            self._talk_job = None
            self.glow.set_busy(False)
            said = box.get("reply", "I'm here.")
            self._history.append((request, said))
            offered = offer and not companion.crisis(request)
            mid, _, tall = self._panel_size
            self.glow.itemconfig(self._panel, height=tall)
            self.glow.coords(self._panel, mid, mid + (tall - self._panel_size[1]) // 2)
            self.tell(said + ("\n\n" + offer if offered else ""))
            if offered:
                self.suggest_btn.config(text=f"→ {names[key]}",
                                        command=lambda: self.show_department(request, key, words))
                self.suggest_btn.pack(pady=(4, 2))
            try:
                self.app.announce(said, cue="")
            except Exception:                                    # noqa: BLE001
                pass
        wait()

    def show_department(self, request: str, key: str, words: list[str]):
        from ..staff import DEPARTMENTS
        self.hide_department()
        side = self.glow.side
        width = side - 60
        frame = tk.Frame(self.glow, bg="#21170F", highlightthickness=2,
                         highlightbackground="#C49A52")
        self._card_img = None
        try:
            from PIL import Image, ImageTk
            im = Image.open(C.department_card(key)).convert("RGB")
            im = im.resize((width - 4, round((width - 4) * im.height / im.width)), Image.LANCZOS)
            self._card_img = ImageTk.PhotoImage(im)
            tk.Label(frame, image=self._card_img, bd=0).pack()
        except (ImportError, OSError, tk.TclError):
            tk.Label(frame, text=DEPARTMENTS[key].name, bg="#21170F", fg="#E8D6AE",
                     font=self.app.fonts["title"]).pack(pady=20)
        why = (f"for “{', '.join(dict.fromkeys(words))}”" if words
               else "as it is a thing to design and build" if key == "workshop" else "")
        tk.Label(frame, text=f"The {DEPARTMENTS[key].name} {why}".rstrip() + ".", bg="#21170F",
                 fg="#E8D6AE", font=self.app.fonts["body"], wraplength=width - 30).pack(pady=(6, 2))
        row = tk.Frame(frame, bg="#21170F"); row.pack(pady=(2, 8))
        ttk.Button(row, text="Go there", style="Primary.TButton",
                   command=lambda: self.go(request, key)).pack(side="left", padx=3)
        other = ttk.Combobox(row, state="readonly", width=18,
                             values=[d.name for d in DEPARTMENTS.values()])
        other.set("Somewhere else...")
        other.bind("<<ComboboxSelected>>", lambda e: self.show_department(
            request, list(DEPARTMENTS)[other.current()], []))
        other.pack(side="left", padx=3)
        ttk.Button(row, text="Back", command=self.hide_department).pack(side="left", padx=3)
        self.glow.itemconfig(self._panel, state="hidden")
        self._card = self.glow.create_window(side // 2, side // 2, window=frame, width=width)
        self._card_frame, self._card_key = frame, key

    def hide_department(self):
        if self._card is not None:
            self.glow.delete(self._card)
            self._card_frame.destroy()
            self._card = None
        self.glow.itemconfig(self._panel, state="normal")

    def go(self, request: str, key: str):
        """Carry the request on in its department."""
        if key == "library" and L.kind_of(request) == "story":
            self.start_story(request)
        elif key == "workshop":
            self.start_design(request)
        else:
            self.app.open_department(key)
            self.leave_home()

    def start_story(self, request: str):
        self.glow.set_busy(True)
        folder = L.file_story(self.app.cfg.path("paths.stories"), request)
        self.box.delete("1.0", "end")
        self.glow.set_busy(False)
        self.hide_department()
        self.tell(f"Kept as the story '{folder.name}'. The employees start writing it "
                  "now; it is in the Story list.")
        self.app.start_job(C.nemo_argv("story", "write", folder.name, "--json"), "story")
        self._leave_job = self.after(1500, self.leave_home)   # cancelled in destroy (D273)

    def start_design(self, request: str):
        self.glow.set_busy(True)
        name = L.name_for(request, set(C.list_projects(self.app.cfg)))
        try:
            proj = C.create_project(name, self.app.cfg)
        except ValueError as exc:
            self.glow.set_busy(False)
            self.tell(str(exc))
            return
        b = proj.load_brief(); b.function = request; proj.save_brief(b)
        self.app.refresh_projects(select=proj.root.name)
        self.app.tabs.select(self.app.tab_brief)
        self.leave_home()
        self.app.draft_brief()

    def leave_home(self):
        """Into the department: Nemo's window comes up, home goes."""
        self.app.deiconify(); self.app.lift()
        self.destroy()

    def quit_nemo(self):
        """Closing the home screen closes Nemo (it asks first if a job is running)."""
        self.app._close()
