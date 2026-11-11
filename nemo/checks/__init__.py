"""Tier 0 check suite."""

from .deterministic import (  # noqa: F401
    FAIL, PASS, SKIP, Result,
    check_wire_gauges, current_sum, fits_envelope, printability,
    supply_rails, trace_width_mm, voltage_compatibility, wire_gauge,
    xref_cutouts, xref_nets,
)
from .runners import (  # noqa: F401
    compile_firmware, drc, erc, generate_enclosure, generate_schematic,
    netlist_groups, netlist_nets, solid,
    thickness, wireviz,
)


def summarise(results: list[Result]) -> tuple[str, int, int]:
    """Render a run of checks. Returns (text, failures, skips)."""
    lines = [r.render() for r in results]
    fails = sum(1 for r in results if r.status == FAIL)
    skips = sum(1 for r in results if r.status == SKIP)
    passes = len(results) - fails - skips
    lines.append("")
    lines.append(f"{passes} passed, {fails} failed, {skips} skipped")
    if skips:
        # D153: this said "install the missing tool", whatever the reason. A
        # check also skips when it has nothing it can compare.
        lines.append("A skipped check is not a passed check -- read why each "
                     "was skipped before trusting the output.")
    return "\n".join(lines), fails, skips
