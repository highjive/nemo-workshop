"""Find and replace for any text box in Nemo, as Notepad 11 has it (owner,
2026-10-28; the search itself is nemo/textfind.py, with what was seen in
Notepad's files). Ctrl+F opens it with Find, Ctrl+H with Replace; F3 finds
the next, Shift+F3 the previous; Esc closes it.

Its settings are Notepad's: Match case, Wrap around (on unless turned off),
and Search up or down. Selected text, when there is some, goes into the
Find box, as Notepad's SelectFindText suggests. Replace all is one undo step
where the text box keeps an undo history.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import textfind
from . import theme as T


def _offset(text: tk.Text, index: str) -> int:
    return int(text.count("1.0", index, "chars")[0] if text.compare(index, ">", "1.0") else 0)


def _index(n: int) -> str:
    return f"1.0+{n}c"


class FindBar(tk.Toplevel):
    """One small window per text box, kept above its window."""

    def __init__(self, text: tk.Text, replace: bool = False):
        super().__init__(text.winfo_toplevel())
        self.text = text
        self.title("Find and replace" if replace else "Find")
        self.transient(text.winfo_toplevel())
        self.resizable(False, False)
        self.configure(bg=T.PANEL, padx=12, pady=10)
        app = text.winfo_toplevel()
        while getattr(app, "master", None) is not None:
            app = app.master
        if hasattr(app, "brand"):
            app.brand(self)
        self.find_var, self.replace_var = tk.StringVar(), tk.StringVar()
        self.case_var, self.wrap_var = tk.BooleanVar(value=False), tk.BooleanVar(value=True)
        self.up_var = tk.BooleanVar(value=False)
        ttk.Label(self, text="Find", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.find_box = ttk.Entry(self, textvariable=self.find_var, width=34)
        self.find_box.grid(row=0, column=1, columnspan=2, sticky="we", padx=6, pady=2)
        ttk.Button(self, text="Find next", command=self.find_next).grid(row=0, column=3, sticky="we")
        ttk.Button(self, text="Find previous", command=self.find_previous).grid(row=0, column=4, sticky="we", padx=(4, 0))
        self.replace_row = [
            ttk.Label(self, text="Replace", style="Panel.TLabel"),
            ttk.Entry(self, textvariable=self.replace_var, width=34),
            ttk.Button(self, text="Replace", command=self.replace),
            ttk.Button(self, text="Replace all", command=self.replace_all)]
        opts = ttk.Frame(self, style="Panel.TFrame"); opts.grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Checkbutton(opts, text="Match case", variable=self.case_var).pack(side="left")
        ttk.Checkbutton(opts, text="Wrap around", variable=self.wrap_var).pack(side="left", padx=10)
        ttk.Radiobutton(opts, text="Search down", value=False, variable=self.up_var).pack(side="left")
        ttk.Radiobutton(opts, text="Search up", value=True, variable=self.up_var).pack(side="left", padx=6)
        self.status = ttk.Label(self, text="", style="PanelMuted.TLabel")
        self.status.grid(row=3, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self.show_replace(replace)
        for key, fn in (("<Return>", lambda e: self.find_next()), ("<Escape>", lambda e: self.destroy()),
                        ("<F3>", lambda e: self.find_next()), ("<Shift-F3>", lambda e: self.find_previous())):
            self.bind(key, fn)
        text._findbar = self
        # The found text stays lit while the typing is in this window.
        try:
            text.configure(inactiveselectbackground=text.cget("selectbackground"))
        except tk.TclError:
            pass
        self.find_box.focus_set()

    # ------------------------------------------------------------ opening
    @classmethod
    def open_for(cls, text: tk.Text, replace: bool = False) -> "FindBar":
        """The text box's bar, made once; selected text goes into Find."""
        bar = getattr(text, "_findbar", None)
        if bar is None or not bar.winfo_exists():
            bar = cls(text, replace)
        else:
            bar.show_replace(replace or bar.replacing)
            bar.deiconify(); bar.lift(); bar.find_box.focus_set()
        try:
            chosen = text.get("sel.first", "sel.last")
            if chosen and "\n" not in chosen:
                bar.find_var.set(chosen)
        except tk.TclError:
            pass                                               # nothing selected
        bar.find_box.select_range(0, "end")
        return bar

    def show_replace(self, on: bool):
        self.replacing = on
        for i, w in enumerate(self.replace_row):
            if on:
                w.grid(row=1, column=i if i < 2 else i + 1, columnspan=2 if i == 1 else 1,
                       sticky="we" if i else "w", padx=(6 if i == 1 else 0, 0 if i != 3 else 0), pady=2)
            else:
                w.grid_remove()
        self.title("Find and replace" if on else "Find")

    # ------------------------------------------------------------ actions
    def _search(self, reverse: bool) -> bool:
        query = self.find_var.get()
        if not query:
            self.status.config(text="Type what to find."); return False
        body = self.text.get("1.0", "end-1c")
        try:
            start = _offset(self.text, "sel.first" if reverse else "sel.last")
        except tk.TclError:
            start = _offset(self.text, "insert")
        hit = textfind.find(body, query, start, match_case=self.case_var.get(), reverse=reverse,
                            wrap=self.wrap_var.get())
        if hit is None:
            self.status.config(text=textfind.cannot_find(query))
            self.bell()
            return False
        a, b = _index(hit[0]), _index(hit[1])
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", a, b)
        self.text.mark_set("insert", a if reverse else b)
        self.text.see(a)
        self.status.config(text="")
        return True

    def find_next(self) -> bool:
        return self._search(self.up_var.get())

    def find_previous(self) -> bool:
        return self._search(not self.up_var.get())

    def replace(self) -> bool:
        """The selected text, when it is a match, becomes the replacement;
        then the next match is found."""
        query = self.find_var.get()
        try:
            chosen = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            chosen = None
        same = chosen is not None and (chosen == query if self.case_var.get()
                                       else chosen.lower() == query.lower())
        if query and same and str(self.text.cget("state")) != "disabled":
            a = self.text.index("sel.first")
            self.text.delete("sel.first", "sel.last")
            self.text.insert(a, self.replace_var.get())
            self.text.mark_set("insert", f"{a}+{len(self.replace_var.get())}c")
        return self.find_next()

    def replace_all(self) -> int:
        query = self.find_var.get()
        if not query or str(self.text.cget("state")) == "disabled":
            return 0
        body = self.text.get("1.0", "end-1c")
        new, n = textfind.replace_all(body, query, self.replace_var.get(),
                                      match_case=self.case_var.get())
        if n:
            undo = bool(self.text.cget("undo"))
            if undo:
                self.text.edit_separator()
                self.text.configure(autoseparators=False)
            self.text.delete("1.0", "end-1c")
            self.text.insert("1.0", new)
            if undo:
                self.text.edit_separator()
                self.text.configure(autoseparators=True)
        self.status.config(text=f"Replaced {n}." if n else textfind.cannot_find(query))
        return n

    def destroy(self):
        if getattr(self.text, "_findbar", None) is self:
            try:
                self.text._findbar = None
            except tk.TclError:
                pass
        super().destroy()


def install(root: tk.Misc):
    """Ctrl+F, Ctrl+H, F3 and Shift+F3 in every text box of the app."""
    def opener(replace):
        def go(event):
            FindBar.open_for(event.widget, replace)
            return "break"
        return go

    def again(previous):
        def go(event):
            bar = getattr(event.widget, "_findbar", None)
            if bar is None or not bar.winfo_exists():
                FindBar.open_for(event.widget)
            else:
                (bar.find_previous if previous else bar.find_next)()
            return "break"
        return go
    root.bind_class("Text", "<Control-f>", opener(False))
    root.bind_class("Text", "<Control-h>", opener(True))
    root.bind_class("Text", "<F3>", again(False))
    root.bind_class("Text", "<Shift-F3>", again(True))
