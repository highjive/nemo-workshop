"""Run the pipeline end to end with a stubbed model.

No llama.cpp, no network, no KiCad needed. Shows what the gates actually
print, including the checks that skip because a tool is missing.

    python3 docs/demo.py
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nemo.config import Config
from nemo.parts import PartsLibrary
from nemo.pipeline import Pipeline
from nemo.project import Brief, Project
from nemo.router import Reply

BRIEF = """```yaml
name: treasure-chest-player
function: >
  An RFID card player in a treasure-chest enclosure with a fixed open lid.
  Placing a card on the chest plays the audio bound to that card.
user: Home use, single user, cards handled loosely.
power: USB 5 V 1 A
supply_ma: 1000
rails: [5.0, 3.3]
envelope_mm: [140, 100, 70]
parts: [esp32_devkit_v1, rc522, dfplayer_mini, speaker_8ohm_20mm]
mcu: esp32
done_when: Three cards each play their own track within one second, ten times.
constraints:
  - Lid fixed open, no moving parts.
  - Speaker magnet at least 25 mm from the RFID antenna.
open_questions:
  - How many cards before storage becomes a problem?
```"""


class Stub:
    def __init__(self, text): self.text = text
    def ask(self, task, system, user, **kw): return Reply(self.text, "local", "stub")
    def local_up(self): return True


tmp = Path(tempfile.mkdtemp())
project = Project(tmp / "chest")
project.create(Brief(name="chest"))
cfg = Config.load(Path("/nonexistent"))
pipe = Pipeline(project, cfg, Stub(BRIEF), PartsLibrary.load())

print(pipe.stage_brief("rfid player in a treasure chest").render(), "\n")
print(pipe.stage_parts().render(), "\n")

# Undersized supply, to show a gate failing.
b = project.load_brief(); b.supply_ma = 400; project.save_brief(b)
print("--- same design on a 400 mA supply ---")
print(pipe.stage_parts().render(), "\n")

b.supply_ma = 1000; project.save_brief(b)
print(pipe.stage_pack([]).render())
print(f"\nproject at: {project.root}")
