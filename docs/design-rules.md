# Nemo's design rules

Lessons learned building Nemo, each from a real defect (the D-numbers are in the
technical report, docs/nemoiso-report.html). Code comments cite them as
"docs/design-rules.md 4d" and so on. Anyone changing Nemo should read them first.

## Mistakes that recurred: check for each on every change

1. **Inserting a test class with str_replace anchored on a `class` line
   deletes that line** and silently merges two classes. After every insertion
   run pyflakes and `grep -n "^class Test" <file>`.
2. **Tk `after()` timers outlive their widget.** Destroying a widget deletes
   its Tcl command but not the pending timer, so it fires later ("invalid
   command name"). A `winfo_exists()` guard inside the callback does nothing,
   because Tcl fails before Python runs. Track the id and `after_cancel` it in
   `destroy()`. In tests wrap with `wraps=`; mocking `after_cancel` disables
   the real cancel and leaks into later tests.
3. **Thresholds that disagree**: two parts of the system choosing from
   different facts (total RAM vs free RAM vs AVX vs which model is on disk)
   caused D98, D102 and D136. When adding a recommendation, check every path
   that makes the same decision. The memory figures live in `config.yaml`,
   `config.py` DEFAULTS, `NemoDoc.ps1` and `gui/controller.py`; a test ties them.
4. **Every text file read or write names `encoding="utf-8"`** (D122). The
   Windows default is cp1252: a write of model output containing an arrow
   crashed, and nothing showed on Linux. `tests/test_encoding.py` fails on a
   new call that names none.
4a. **`Config` is deep-copied** now.
4b. **An example in a prompt comes back as the answer.** The 1.7B model
   copied the wiring prompt's example connectors into a project that had
   none of them, and a whole example line of the plan prompt into an
   unrelated story. Show the shape with `<placeholders>`, never a worked
   example. Tests check the prompts carry none. Context does it too: shown the whole synopsis and the neighbouring chapters "to stay between them", the model planned those instead of its own chapter (D168). A FACT does it too: told
   "Its 3V3 pin gives 3.3 V; VIN and 5V give 5 V", it wired one part's
   supply pin to all three. Give it only what it must choose between.
4d. **Ask the model for a bounded choice, never for a file in a library's
   idiom.** The 1.7B model failed every time it was asked for SKiDL,
   CadQuery or Arduino C++, and succeeded when asked which pin goes to
   which or where a part sits, held to a JSON schema. Code writes the file
   and a deterministic check judges the choice. Where the library already
   knows the answer (which supply pin suits a part, a sensor away from the
   warm part) code decides it and says so; the model is not asked twice.
4g. **To have the small model judge, ask one thing at a time and give it a way
   out.** Asked which of three lines contradict a synopsis, it named every
   line of two sound plans (2 of 8 right). Asked line by line for agrees,
   new or contradicts, it was right on 9 of 10 (D169). Two answers force a
   guess; the third is where "neither" goes.
4f. **Every token the model writes is paid for in minutes here.** Asked for
   supply wires, colours, gauges and lengths that code then replaced, a
   five-part design timed out at 30 minutes and wasted 163 (D164). Ask only
   for what code cannot decide, and never let a later step ask the model
   in place of an answer an earlier step failed to get (D165). READING is
   paid for too: 1.15 tokens a second in Design mode, so a 500-token
   question is seven minutes before a word is written (D171, D172). The
   server's own figures are in `~/.nemo/<mode>.log`; read them, do not guess.
4e. **A gate that passes on one brief has been tested on one brief.** The
   second real brief passed every check and was wrong four ways (D137-D140),
   the third three more (D143-D145), the fourth, the first with a relay and a
   servo, three more with every check passing (D159-D161): read what was
   wired, not the PASS lines. The model runs at temperature 0.2 with
   no seed: one run is one sample, and the same brief can pass and then fail.
   Try a new kind of circuit against the real model before trusting a gate.
4c. **Prompt order is a cost.** llama-server re-reads only what differs
   after the longest shared beginning, and reading is as slow as writing
   here. Put what never changes first, what varies last. Do not reintroduce shallow copies of
   `DEFAULTS`.
5. A multi-word bible name containing a common English word makes the
   near-miss checker flag ordinary prose. Prefer the source's own bare term.
6. Security-critical code (signing, maintenance, authority, lockdown, safety): go
   slowly, add tests for tampering, and state limits honestly. In `safety.py`
   the prop, airsoft and toy-bow lists and limits are module constants on
   purpose: nothing in a policy or a signed floor may reach them (D146).
   `AIRSOFT_MAX_JOULES` is 0.7, the owner's own figure (2026-10-07), not checked against a statute; only he changes it. MASTER_PUBLIC_KEY is
   a literal compiled in by `tools/embed-key.py`.

## Conventions

- Every defect fix gets a regression test that fails on the old code. Prove the
  test discriminates by running it against the unfixed behaviour once.
- Estimates are labelled estimates. Never invent a datasheet figure, pin number,
  footprint or hash: say "not verified" instead. A part's `keep_apart` distance is
  such a figure: add one only where a source gives it.
- Test fixtures use invented names, never real people's or real projects'.
- Nemo never acts on another device unasked: casting to a television, for one, is
  always the owner's own press of a button.
- Every text file read or written names `encoding="utf-8"` (rule 4 above).
