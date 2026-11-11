"""Prompt loading.

Prompts live as files so you can edit them without touching code. This
matters more here than on fast hardware: a 4B model with a precise, worked
prompt beats a vague prompt to a much larger model, and prompt tuning is
free while tokens are slow.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_prompt(name: str, **fmt) -> str:
    path = HERE / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt named {name!r} in {HERE}")
    text = path.read_text(encoding="utf-8", errors="replace")
    cfg = fmt.pop("cfg", None)
    if cfg is not None:
        fmt.setdefault("printer", cfg.get("hardware.printer"))
    for key, value in fmt.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text
