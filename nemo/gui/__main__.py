import sys

from .app import main

# `python -m nemo.gui --prompt` opens at the home screen, as the desktop
# shortcut does (owner, 2026-10-25), and as NemoIso does at boot.
raise SystemExit(main(prompt="--prompt" in sys.argv[1:]))
