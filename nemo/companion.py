"""Nemo as Highjive's companion (owner, 2026-10-23: "nemo itself is my
companion and the departments are how it can help; unless I tell it which
department it won't change to it").

In the home scene he talks WITH Nemo. Nemo answers as itself, briefly, through
the talk model. It may suggest the department that could help, a suggestion
made by code from his words (prompt_logic.department_for), and it changes to
a department only when he names one or presses its card.

His rules for it, the same as for the whole project: a realist, never
optimistic and never pessimistic, saying plainly what it knows and what it
does not. It gives no medical advice. When his words suggest a crisis, Nemo
does not leave the answer to the model: it says plainly that it is not
enough and gives the helplines below, every time.
"""
from __future__ import annotations

import re

TASK = "story"               # routed to the local model, reasoning off (stories.py's)
CRISIS = re.compile(r"\b(suicid\w*|kill (?:my ?self|me)|end (?:my|it all)|end my life|"
                    r"self[- ]?harm\w*|hurt(?:ing)? my ?self|want to die|wish I was dead|"
                    r"no (?:reason|point) (?:to|in) (?:live|living|go(?:ing)? on)|overdose)\b", re.I)
HELP = ("I'm a program on your laptop, and this is more than I can help with on my own. "
        "Please talk to someone now: Samaritans, 116 123, free at any time in the UK and "
        "Ireland, or 999 or 112 if you are in danger. I'm still here while you call.")
# D271. Said without the words above, and the model was asked: "I feel like
# there's no point any more", "I don't want to be here anymore", "Everyone would
# be better off without me", "I can't go on like this" (qwen3-4b, 2026-11-11:
# four gentle questions, no helpline). Words like these may or may not mean it,
# so code asks plainly, as Samaritans advise (asking does not put the idea there),
# and gives the helplines either way. A yes is answered with HELP.
CONCERN = re.compile(r"\b(no (?:point|reason)(?: in anything| to anything| any ?more| left)?|"
                     r"(?:don'?t|do not) want to (?:be here|live|wake up|exist|go on)|"
                     r"better off without me|(?:can'?t|cannot) go on|(?:can'?t|cannot) cope|"
                     r"nothing (?:left )?to live for|give up on (?:life|everything)|"
                     r"disappear (?:for ?ever|for good)|tired of (?:living|life)|"
                     r"no way out|burden (?:to|on) (?:everyone|everybody|you all))\b", re.I)
ASK = ("That sounds very heavy, and I'd rather ask plainly: are you thinking about ending "
       "your life, or hurting yourself? If you are, please talk to someone now: Samaritans, "
       "116 123, free at any time, or 999 if you are in danger. Either way, I'm here.")
_YES = re.compile(r"^\s*(?:yes|yeah|yep|maybe|sometimes|i think so|i don'?t know|not sure|"
                  r"kind of|a bit|a little|i am|i do)\b", re.I)
SYSTEM = ("You are Nemo, a companion program on the user's own laptop. Write British English. "
          "Answer in two or three short sentences, warmly and plainly, with no exclamation "
          "marks and no praise of what they say or ask. Be a realist: never optimistic, never "
          "pessimistic; say plainly what you do not know. Listen first; ask one gentle "
          "question if it helps. You can only talk: never offer to do, find, fetch or arrange "
          "anything. You cannot see the time, the date, the weather or the news, you forget "
          "this conversation when it ends, and you cannot remind anyone: never claim "
          "otherwise or promise to. Give no medical, legal or money advice and name no "
          "medicine. Do not mention departments; Nemo's code does that.")
HISTORY = 3                  # exchanges kept: reading costs minutes on the AH531 (docs/design-rules.md 4f)

# D272. What the model cannot know or do, said by code (qwen3-4b, 2026-11-11:
# "It's 3:47 PM here", the same line for the weather, "I'll remind you", and
# ibuprofen named for a three-day headache).
_TIME = re.compile(r"\b(?:what(?:'s| is) the (?:time|date)|what time is it|what day is it|"
                   r"what(?:'s| is) today'?s date|what(?:'s| is) the day)\b", re.I)
_WEATHER = re.compile(r"\b(?:weather|forecast)\b", re.I)
_REMEMBER = re.compile(r"\b(?:remember (?:that|this|for me)|remind me|don'?t let me forget|"
                       r"will you remember)\b", re.I)
_MEDICINE = re.compile(r"\b(?:tablets?|pills?|medicines?|medications?|dose|dosage|painkillers?|"
                       r"ibuprofen|paracetamol|aspirin|antibiotics?|prescriptions?|"
                       r"what (?:should|can) i take)\b", re.I)
_PROMISE = re.compile(r"\bI(?:'ll|’ll| will) (?:remind|remember)|\bI (?:remember|have noted|"
                      r"have saved|'ve noted|’ve noted|'ve saved|’ve saved) (?:your|that|it)\b", re.I)
WEATHER = "I can't see the weather from here: Nemo has no weather feed, and I won't guess."
REMEMBER = ("I can't keep that or remind you: I forget what we say when this conversation "
            "ends. Say “journal” and then the words, and I'll keep them in your "
            "journal on this laptop.")
MEDICINE = ("I can't advise on medicines or symptoms. A pharmacist can advise today without "
            "an appointment; your GP for anything that keeps on, NHS 111 if you're unsure, and "
            "999 if it is sudden or severe.")


def crisis(text: str) -> bool:
    """Words that are, or may be, a crisis: no department is offered with them."""
    return bool(CRISIS.search(text) or CONCERN.search(text))


def by_code(text: str, history=None, now=None) -> str | None:
    """What Nemo says without the model, or None for the model to answer."""
    import datetime as dt
    if CRISIS.search(text):
        return HELP
    if history and history[-1][1] == ASK and (_YES.match(text) or CONCERN.search(text)):
        return HELP               # yes, or more of the same: not asked twice
    if CONCERN.search(text):
        return ASK
    if _MEDICINE.search(text):
        return MEDICINE
    if _REMEMBER.search(text):
        return REMEMBER
    if _TIME.search(text):
        t = now or dt.datetime.now()
        return (f"By this laptop's clock it's {t:%H:%M} on {t:%A} {t.day} {t:%B} {t.year}.")
    if _WEATHER.search(text):
        return WEATHER
    return None


def reply(router, text: str, history: list[tuple[str, str]] | None = None) -> str:
    """Nemo's answer in its own words, or what it can say without the model."""
    said = by_code(text, history)
    if said:
        return said
    past = "".join(f"They said: {u}\nYou said: {n}\n" for u, n in (history or [])[-HISTORY:])
    try:
        out = router.ask(TASK, SYSTEM, past + f"They say: {text}\nYou say:", temperature=0.5,
                         max_tokens=120).text.strip()
    except Exception as exc:                                    # noqa: BLE001
        return (f"I'm here, but I can't answer in my own words just now ({exc}). "
                "Is the talk model loaded?")
    if _PROMISE.search(out):
        return REMEMBER           # a promise it cannot keep is not passed on
    return out or "I'm listening."


def suggestion(key: str, words: list[str], names: dict[str, str]) -> str:
    """Code's line offering a department; nothing switches until he says."""
    if not words:
        return ""
    return (f"The {names[key]} could help with that. Say “{names[key]}”, or press "
            f"its card, to go there.")


# ---------------------------------------------------------------- his own tools
# (owner's yes, 2026-10-23: design A). Handled by code, never the model, and
# kept on this laptop in <storeroom>/companion: nothing is saved unless he
# says so.
_JOURNAL = re.compile(r"^\s*(?:journal|note this|write this down)[:,]?\s*(.*)$", re.I | re.S)
_CHECKIN = re.compile(r"^\s*(?:check[- ]?in|how am i doing)\b", re.I)
_SCORES = re.compile(r"\bmood\s*([1-5])\b.*?\bsleep\s*([1-5])\b", re.I | re.S)
_CALM = re.compile(r"^\s*(?:calm|breathe|breathing|help me (?:calm|relax))\b", re.I)


def command(text: str):
    """("journal", words) | ("ask-checkin", None) | ("checkin", (mood, sleep))
    | ("calm", None) | None: what code answers, before the model is asked."""
    m = _JOURNAL.match(text)
    if m:
        return "journal", m.group(1).strip()
    m = _SCORES.search(text)
    if m:
        return "checkin", (int(m.group(1)), int(m.group(2)))
    if _CHECKIN.match(text):
        return "ask-checkin", None
    if _CALM.match(text):
        return "calm", None
    return None


def _home(cfg) -> "Path":
    from pathlib import Path
    return Path(cfg.path("paths.storeroom")) / "companion"


def keep_journal(cfg, words: str, now=None) -> str:
    import datetime as dt
    if not words:
        return "Tell me what to keep, after the word journal: journal, today I finished the lamp."
    home = _home(cfg); home.mkdir(parents=True, exist_ok=True)
    stamp = (now or dt.datetime.now()).strftime("%Y-%m-%d %H:%M")
    with (home / "journal.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## {stamp}\n\n{words}\n")
    return "Kept in your journal, on this laptop only."


def check_in(cfg, mood: int, sleep: int, now=None) -> str:
    """Keep today's scores and read the last weeks plainly: no cheering, no alarm."""
    import datetime as dt
    import json
    home = _home(cfg); home.mkdir(parents=True, exist_ok=True)
    path = home / "checkins.jsonl"
    today = (now or dt.datetime.now())
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": today.strftime("%Y-%m-%d %H:%M"), "mood": mood, "sleep": sleep}) + "\n")
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    def week(back):
        lo, hi = today - dt.timedelta(days=7 * (back + 1)), today - dt.timedelta(days=7 * back)
        got = [r for r in rows if lo < dt.datetime.strptime(r["at"], "%Y-%m-%d %H:%M") <= hi]
        return (sum(r["mood"] for r in got) / len(got), sum(r["sleep"] for r in got) / len(got)) if got else None
    this, last = week(0), week(1)
    said = f"Kept: mood {mood}, sleep {sleep}."
    if this and last:
        def compare(a, b, what):
            return (f"{what} about the same as the week before" if abs(a - b) < 0.5 else
                    f"{what} lower than the week before ({a:.1f} against {b:.1f})" if a < b else
                    f"{what} higher than the week before ({a:.1f} against {b:.1f})")
        said += " This week: " + compare(this[0], last[0], "mood") + "; " + compare(this[1], last[1], "sleep") + "."
    else:
        said += " Too few check-ins yet to compare weeks."
    return said


CALM_STEPS = [("Breathe in", 4), ("Hold", 4), ("Breathe out", 6)] * 4
