"""A minimal PDF with a real text layer, for tests that need a datasheet.
Every name in it is invented (docs/design-rules.md: fixtures use invented names)."""
from __future__ import annotations

from pathlib import Path


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(path: Path, pages: list[list[str]]) -> Path:
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        text = "BT /F1 11 Tf 14 TL 60 760 Td " + " ".join(f"({_esc(l)}) '" for l in lines) + " ET"
        objs.append(f"<< /Length {len(text.encode('latin-1'))} >>\nstream\n{text}\nendstream")
        content = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for o in offsets:
        out += f"{o:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    Path(path).write_bytes(bytes(out))
    return Path(path)


# An invented part, and what its datasheet says (the truth a reading is judged by).
NT41 = [
    ["NT-41 Ambient Light Sensor Module", "Datasheet, revision 2",
     "Electrical characteristics", "Supply voltage: 3.3 V or 5 V",
     "Typical supply current: 0.8 mA", "Logic level: 3.3 V (I2C interface)"],
    ["Pin description", "VCC  power supply input", "GND  ground",
     "SDA  I2C data line", "SCL  I2C clock line", "INT  interrupt output, active low"],
]
NT41_TRUTH = {"supply_v": {3.3, 5.0}, "current_ma": 0.8, "logic_v": 3.3,
              "pins": {"VCC": "power", "GND": "gnd", "SDA": "bus", "SCL": "bus", "INT": "io"}}
