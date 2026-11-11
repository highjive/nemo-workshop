"""Safety parameters.

The architecture here is the one already proven in the pendant firmware: a
fixed, compiled-in floor that no configuration file can reach, and a
separate mutable layer an administrator may edit. The rule binding them is
one-directional.

    An administrator may make the assistant MORE cautious.
    An administrator may never make it less cautious than the floor.

That asymmetry is the whole design. A policy file is data on disk; on a
laptop that travels, data on disk is editable by anyone who can boot a USB
stick. So nothing safety-critical is allowed to live only in the policy
file. The floor below is a Python constant inside the installed package,
covered by the integrity manifest that nemodoc verifies at every boot: it
can be corrupted, but not silently.

Values are engineering limits, because this assistant designs hardware. The
failure mode being guarded against is not rude text, it is a LiPo cell in a
sealed enclosure with no protection circuit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ====================================================================
#  Three tiers of authority.
#
#    HARD_FLOOR   nobody. Not the local admin, not a signed document,
#                 not the author. Changing these means editing this file
#                 and rebuilding, which is visible in git and flagged by
#                 the integrity manifest.
#
#    FLOOR        the default. Replaceable in full by a document signed
#                 with the master key -- this is the "reset the safety
#                 protocols if something is wrong in the field" path.
#                 A signed floor may loosen as well as tighten, which is
#                 the point of master authority, but is still clamped by
#                 HARD_FLOOR afterwards.
#
#    Policy       the local administrator. May tighten only, never loosen.
#
# The hard tier exists so that a compromised or mistaken master key cannot
# turn the assistant into something that designs a weapon or removes the
# human gate before a battery is connected. An authority with no ceiling
# is a single point of failure, and the author is not exempt from that.
# ====================================================================

HARD_FLOOR: dict[str, Any] = {
    "human_signoff_before_print": True,
    "human_signoff_before_order": True,
    "human_signoff_before_battery_connect": True,
    "tier0_checks_mandatory": True,
    "skipped_check_is_not_a_pass": True,
    "mains_requires_human_signoff": True,
    "lipo_requires_protection_circuit": True,
    # A declared prop of a weapon, an airsoft device or a toy bow is let
    # through only to a human sign-off (D146, below). No document can
    # switch either sign-off off.
    "weapon_prop_requires_human_signoff": True,
    "launcher_requires_human_signoff": True,
    # An absolute ceiling. A signed floor may lower it; nothing raises it.
    "max_design_voltage_v": 48.0,
    # These may be added to by anyone and removed by no one.
    "forbidden_domains": [
        "weapon", "firearm", "munition", "explosive", "detonator",
        "projectile launcher", "gauss gun", "coil gun", "rail gun",
        "taser", "stun gun",
        "medical implant", "defibrillator", "infusion pump",
        "life support", "ventilator",
    ],
}



FLOOR: dict[str, Any] = {
    # --- electrical ---------------------------------------------------
    # Above this, a design is no longer a hobby project and wants a
    # qualified person, not a 4B model on a fourteen-year-old laptop.
    "max_design_voltage_v": 48.0,
    "mains_requires_human_signoff": True,
    "weapon_prop_requires_human_signoff": True,
    "launcher_requires_human_signoff": True,
    # Both False: a declared prop, an airsoft device and a toy bow may go
    # through to a sign-off. A policy or a signed floor may set either True
    # and close it again; being restrictions, anyone may switch them on.
    "forbid_weapon_props": False,
    "forbid_launchers": False,
    "max_continuous_current_a": 10.0,
    # Peak draw must not exceed the supply. Non-negotiable: a design that
    # only works when nothing is transmitting is not a design.
    "supply_headroom_fraction": 0.10,

    # --- battery ------------------------------------------------------
    # Every one of these is a documented cause of lithium fires.
    "lipo_requires_protection_circuit": True,
    "lipo_requires_swell_clearance_mm": 1.0,
    "lipo_forbids_sealed_enclosure": True,
    "battery_charging_requires_thermal_path": True,

    # --- thermal and mechanical ---------------------------------------
    "min_wall_mm_absolute": 0.8,
    "enclosure_vent_required_above_ma": 500,

    # --- process ------------------------------------------------------
    # The human gate. Nothing removes this.
    "human_signoff_before_print": True,
    "human_signoff_before_order": True,
    "human_signoff_before_battery_connect": True,
    # A check that did not run is not a check that passed.
    "skipped_check_is_not_a_pass": True,
    "tier0_checks_mandatory": True,

    # --- scope --------------------------------------------------------
    # Categories the assistant will not design toward, at any policy level.
    # Phrases, matched whole and on word boundaries. Single generic words
    # are deliberately absent: an earlier revision matched any word over
    # four characters, so "data transmission" and "test equipment" -- both
    # everyday phrases in an electronics brief -- were hard-blocked as
    # "high-voltage transmission" and "life-support equipment". A scope
    # guard that blocks ordinary work is one the operator routes around,
    # which leaves them with no guard at all.
    "forbidden_domains": [
        "weapon", "firearm", "munition", "explosive", "detonator",
        "projectile launcher", "gauss gun", "coil gun", "rail gun",
        "taser", "stun gun",
        "mains wiring", "consumer unit", "distribution board",
        "medical implant", "defibrillator", "infusion pump",
        "life support", "ventilator",
        "brake controller", "steering controller", "throttle controller",
        "flight controller", "avionics",
    ],
}

# ====================================================================
#  Props, airsoft and toy bows (D146)
#
# The scope guard is a word filter. "A toy sword with lights" passed it and
# "a replica weapon with lights" did not, though they are the same lights;
# and "airsoft" and "crossbow" were not on its list at all, so a brief for
# either passed with no condition unless it also said "weapon". It blocked
# by wording, not by what was being built: the kind of guard the note on
# forbidden_domains above warns an operator routes round.
#
# By the owner's decision, made in this file where the hard tier can only
# be changed (visible in git and to the integrity manifest):
#
#   * "weapon" and "firearm" no longer block a brief that declares itself a
#     prop, replica or toy, provided nothing in the brief or the parts says
#     it does anything but light up and make sound.
#   * An airsoft device is let through if the brief names no gas of any
#     kind and states an energy at or under AIRSOFT_MAX_JOULES.
#   * A bow or crossbow is let through only as a toy, with no gas, and
#     within the toy projectile limits below.
#   * Each goes to a human sign-off, never straight through.
#
# Everything here is a constant. None of it is read from a policy file or
# a signed document, so neither can widen it. Every other entry of
# forbidden_domains blocks whatever the brief calls itself: a "toy coil
# gun" is a coil gun.
#
# Limits, stated plainly. This judges the words and figures a brief
# states; it measures nothing, and a brief that understates its energy
# passes. It cannot see what a housing is shaped like or what a person does
# with the result. The sign-off puts those questions to a person. Nemo
# draws a rectangular tray, not the shape of a prop.
# ====================================================================

PROP_EXEMPT = frozenset({"weapon", "firearm"})
PROP_WORDS = ("prop", "replica", "toy", "cosplay", "costume")
# Words that say something is thrown or loaded. With any of them a brief
# is not a prop, whatever else it says.
PROP_DEFEATED_BY = ("projectile", "pellet", "dart", "bb", "ammunition", "ammo",
                    "cartridge", "live round")

AIRSOFT_WORDS = ("airsoft",)
# Not the bare word "bow": a boat has one, and so does a ribbon.
BOW_WORDS = ("crossbow", "archery", "bow and arrow", "toy bow")
# Nothing propelled by gas, whatever it is called.
GAS_WORDS = ("gas", "co2", "green gas", "hpa", "propane", "compressed air",
             "pneumatic", "air tank", "pre-charged")
# The limit for airsoft is national law, not EU toy law (the Toy Safety
# Directive does not treat such a device as a toy at all). The figure is
# the owner's, given 2026-10-07, and is set BELOW the 0.8 J he works to on
# purpose: if a printed part comes out stronger than designed, it should
# still be under that. Neither figure was looked up or checked against any
# statute here. Set to None, every airsoft brief is refused.
AIRSOFT_MAX_JOULES = 0.7
# Toy projectiles, as test houses summarise EN 71-1 (clause 4.17): above
# 0.08 J a projectile must not exceed 2500 J/m2. From those summaries, read
# 2026-10-07, NOT from the standard itself, which is not free to read.
# Check before relying on it.
TOY_PROJECTILE_MAX_J = 0.08
TOY_PROJECTILE_MAX_J_PER_M2 = 2500.0


def _has(words, text: str) -> str | None:
    for word in words:
        pattern = r"\b" + r"\W+".join(re.escape(w) for w in word.split()) + r"s?\b"
        if re.search(pattern, text):
            return word
    return None


def moving_parts(parts) -> list[str]:
    """Parts that can move or switch something: a motor driver, a servo, a
    relay. A prop that only lights up and makes sound has none."""
    out = []
    for x in parts:
        category = getattr(x, "category", "")
        interfaces = set(getattr(x, "interfaces", []) or [])
        if category == "driver" or (category == "actuator" and interfaces & {"pwm", "gpio"}):
            out.append(getattr(x, "ref", "?"))
    return out


def _joules(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:j|joules?)\b", text)
    return float(m.group(1)) if m else None


def _tip_mm(text: str) -> float | None:
    m = re.search(r"tip\D{0,30}?(\d+(?:\.\d+)?)\s*mm|(\d+(?:\.\d+)?)\s*mm\D{0,15}?tip", text)
    return float(m.group(1) or m.group(2)) if m else None


def launcher_refused(kind: str, text: str, forbid: bool) -> str | None:
    """Why an airsoft or toy-bow brief is refused, or None if it may go to
    a human sign-off. Judges only what the brief states; measures nothing."""
    if forbid:
        return "airsoft and toy bows are switched off by this machine's policy"
    gas = _has(GAS_WORDS, text)
    if gas:
        return f"it mentions '{gas}', and nothing propelled by gas is allowed"
    joules = _joules(text)
    if joules is None:
        return ("it does not state the energy of what it fires, in joules; "
                "write that in the brief")
    if kind == "airsoft":
        if AIRSOFT_MAX_JOULES is None:
            return ("no airsoft energy limit is set in safety.py (AIRSOFT_MAX_JOULES); "
                    "set it to the legal limit where it will be used")
        if joules > AIRSOFT_MAX_JOULES:
            return f"{joules:g} J is over the {AIRSOFT_MAX_JOULES:g} J set for airsoft"
        return None
    if not _has(("toy",), text):
        return "a bow or crossbow is allowed only as a toy, and the brief does not call it one"
    if joules <= TOY_PROJECTILE_MAX_J:
        return None
    tip = _tip_mm(text)
    if tip is None or tip <= 0:
        return (f"{joules:g} J is over {TOY_PROJECTILE_MAX_J:g} J, so the diameter of the "
                "projectile's tip in mm is needed, to work out its energy per unit area")
    density = joules / (math.pi * (tip / 2000.0) ** 2)
    if density > TOY_PROJECTILE_MAX_J_PER_M2:
        return (f"{joules:g} J on a {tip:g} mm tip is {density:,.0f} J/m2, over the "
                f"{TOY_PROJECTILE_MAX_J_PER_M2:,.0f} J/m2 allowed for a toy")
    return None


# Keys where a LOWER number is the more cautious setting, so "tightening"
# means decreasing rather than increasing.
_LOWER_IS_TIGHTER = {
    "max_design_voltage_v",
    "max_continuous_current_a",
    "enclosure_vent_required_above_ma",
}

# Booleans in the floor that are True are protections; policy may not
# switch them off. A policy may set an additional protection to True.
_PROTECTIONS = {k for k, v in FLOOR.items() if isinstance(v, bool) and v}


def clamp_to_hard(values: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply HARD_FLOOR over a candidate floor.

    Returns the clamped values and a list of what was overridden, so a
    signed document that oversteps is reported rather than silently
    trimmed. The author should know their document was partly ignored.
    """
    out = dict(values)
    overridden: list[str] = []
    for key, hard in HARD_FLOOR.items():
        have = out.get(key)
        if isinstance(hard, bool):
            if have is not True:
                out[key] = True
                overridden.append(f"{key}: forced to True (hard floor)")
        elif isinstance(hard, (int, float)):
            if have is None or float(have) > float(hard):
                out[key] = hard
                overridden.append(
                    f"{key}: capped at {hard} (hard floor)")
        elif isinstance(hard, list):
            missing = [x for x in hard if x not in (have or [])]
            if missing:
                out[key] = sorted(set(have or []) | set(hard))
                overridden.append(
                    f"{key}: {len(missing)} entry(ies) restored (hard floor)")
    return out, overridden


def active_floor(signed_values: dict[str, Any] | None = None
                 ) -> tuple[dict[str, Any], list[str]]:
    """The floor currently in force.

    With no signed document this is FLOOR. With one, the signed values
    replace FLOOR entirely -- then HARD_FLOOR is clamped over the result.
    """
    base = dict(signed_values) if signed_values else dict(FLOOR)
    return clamp_to_hard(base)


@dataclass
class Policy:
    """The administrator-editable layer."""

    values: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    version: int = 1
    _floor: dict[str, Any] | None = field(default=None, repr=False,
                                          compare=False)

    # ----------------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "Policy":
        if not Path(path).exists():
            return cls()
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(values=doc.get("values", {}) or {},
                   note=doc.get("note", ""),
                   version=int(doc.get("version", 1)))

    def save(self, path: Path) -> None:
        # Explicit fields only. asdict() would include the bound floor, and
        # an earlier revision wrote the entire active floor into policy.yaml
        # as a side effect -- harmless to load, but it made the policy file
        # look as though the local admin had set forty parameters.
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(yaml.safe_dump(
            {"values": self.values, "note": self.note,
             "version": self.version}, sort_keys=True), encoding="utf-8")

    # ----------------------------------------------------------------

    def against(self, floor: dict[str, Any] | None) -> "Policy":
        """Bind this policy to a particular active floor."""
        self._floor = dict(floor) if floor else None
        return self

    @property
    def floor(self) -> dict[str, Any]:
        return self._floor if self._floor else FLOOR

    def validate(self) -> list[str]:
        """Every way this policy tries to loosen the floor.

        Returns the problems rather than raising, so an administrator sees
        all of them at once instead of fixing them one per attempt.
        """
        problems: list[str] = []
        active = self.floor
        for key, value in self.values.items():
            if key not in active:
                # Unknown keys are allowed -- they are additional
                # restrictions the floor does not know about -- but they
                # can never relax anything, because nothing reads them
                # as permission.
                continue
            floor = active[key]

            if isinstance(floor, bool):
                if key in _PROTECTIONS and value is not True:
                    problems.append(
                        f"{key}: the floor requires this protection to stay "
                        f"on; a policy cannot set it to {value!r}")
            elif isinstance(floor, (int, float)):
                if key in _LOWER_IS_TIGHTER:
                    if float(value) > float(floor):
                        problems.append(
                            f"{key}: {value} is higher than the floor of "
                            f"{floor}; a policy may only lower this")
                else:
                    if float(value) < float(floor):
                        problems.append(
                            f"{key}: {value} is lower than the floor of "
                            f"{floor}; a policy may only raise this")
            elif isinstance(floor, list):
                missing = [x for x in floor if x not in (value or [])]
                if missing:
                    problems.append(
                        f"{key}: a policy may add entries but not remove "
                        f"them; missing {missing}")
        return problems

    def effective(self) -> dict[str, Any]:
        """The floor, tightened by whatever the policy legitimately adds.

        Any attempt to loosen is discarded rather than honoured. This is
        belt and braces: validate() should have rejected the file already,
        but a corrupted or hand-edited file must still fail safe.
        """
        out = dict(self.floor)
        for key, value in self.values.items():
            floor = out.get(key)

            if key not in out:
                out[key] = value
                continue
            if isinstance(floor, bool):
                out[key] = bool(floor or value)          # only ever adds
            elif isinstance(floor, (int, float)):
                if key in _LOWER_IS_TIGHTER:
                    out[key] = min(float(floor), float(value))
                else:
                    out[key] = max(float(floor), float(value))
            elif isinstance(floor, list):
                out[key] = sorted(set(floor) | set(value or []))
            else:
                out[key] = value
        return out


# ====================================================================
#  Applying the parameters to an actual design
# ====================================================================

@dataclass
class Finding:
    severity: str      # "block" | "signoff" | "note"
    rule: str
    detail: str

    def render(self) -> str:
        tag = {"block": "BLOCK", "signoff": "SIGN", "note": "note"}[self.severity]
        return f"{tag}  {self.rule}: {self.detail}"


def review(brief, parts, policy: Policy | None = None) -> list[Finding]:
    """Check a design against the effective safety parameters.

    Runs as a Tier 0 gate: no model, no network, deterministic. A "block"
    stops the pipeline. A "signoff" does not stop it, but is recorded in
    BUILD.md as something requiring a human decision.
    """
    p = (policy or Policy()).effective()
    out: list[Finding] = []

    rails = list(getattr(brief, "rails", []) or [])
    highest = max(rails) if rails else 0.0

    if highest > float(p["max_design_voltage_v"]):
        out.append(Finding(
            "block", "max_design_voltage_v",
            f"design uses {highest} V; the limit is "
            f"{p['max_design_voltage_v']} V. Above this a design wants a "
            f"qualified person, not this assistant."))

    if highest >= 100 and p.get("mains_requires_human_signoff", True):
        out.append(Finding(
            "signoff", "mains_requires_human_signoff",
            "mains-adjacent voltage present; a qualified person must review "
            "isolation, creepage and clearance before anything is built."))

    # A battery or charger is a source, not a load. Summing a cell's
    # discharge rating as though it were draw double-counts the whole
    # design and blocks perfectly sound builds.
    loads = [x for x in parts if getattr(x, "category", "") != "power"]
    total_ma = sum(getattr(x, "draw_ma", 0.0) for x in loads)
    limit_a = float(p["max_continuous_current_a"])
    if total_ma / 1000.0 > limit_a:
        out.append(Finding(
            "block", "max_continuous_current_a",
            f"peak draw {total_ma:.0f} mA exceeds the {limit_a} A limit"))

    supply = float(getattr(brief, "supply_ma", 0) or 0)
    head = float(p["supply_headroom_fraction"])
    if supply and total_ma > supply * (1 - head):
        out.append(Finding(
            "block", "supply_headroom_fraction",
            f"peak draw {total_ma:.0f} mA leaves under {head:.0%} headroom "
            f"on a {supply:.0f} mA supply"))

    # --- battery ------------------------------------------------------
    cells = [x for x in parts
             if "lipo" in getattr(x, "ref", "").lower()
             or "lipo" in getattr(x, "name", "").lower()]
    if cells:
        refs = ", ".join(getattr(c, "ref", "?") for c in cells)
        if p.get("lipo_requires_protection_circuit", True):
            cell_refs = {getattr(c, "ref", "") for c in cells}
            protection = []
            for x in parts:
                if getattr(x, "ref", "") in cell_refs:
                    # A cell's own datasheet note saying it NEEDS protection
                    # is not evidence that protection is present. Excluding
                    # the cell from its own search is the difference between
                    # a real check and a tautology.
                    continue
                if getattr(x, "category", "") != "power":
                    continue
                blob = (getattr(x, "name", "") + " " +
                        getattr(x, "notes", "")).lower()
                if any(t in blob for t in ("protect", "dw01", "bms")):
                    protection.append(x)
            if not protection:
                out.append(Finding(
                    "block", "lipo_requires_protection_circuit",
                    f"{refs} present with no protection circuit in the BOM. "
                    "Add a protected charger module, or a cell with "
                    "integrated protection."))
        if p.get("lipo_forbids_sealed_enclosure", True):
            out.append(Finding(
                "signoff", "lipo_forbids_sealed_enclosure",
                f"{refs}: the enclosure must not be a sealed rigid pocket. "
                f"Leave at least "
                f"{p['lipo_requires_swell_clearance_mm']} mm clearance; "
                "cells swell with age."))
        if p.get("battery_charging_requires_thermal_path", True):
            out.append(Finding(
                "note", "battery_charging_requires_thermal_path",
                "charging generates heat; confirm the charger IC is not "
                "buried against an insulating wall."))

    # --- venting ------------------------------------------------------
    vent_above = float(p["enclosure_vent_required_above_ma"])
    if total_ma > vent_above:
        out.append(Finding(
            "note", "enclosure_vent_required_above_ma",
            f"{total_ma:.0f} mA exceeds {vent_above:.0f} mA; the enclosure "
            "needs a ventilation opening."))

    # --- scope --------------------------------------------------------
    # done_when is read too since D146: it says what the thing does, and a
    # brief could name its purpose there and nowhere else.
    text = " ".join(filter(None, [
        getattr(brief, "function", ""), getattr(brief, "name", ""),
        getattr(brief, "done_when", ""),
        " ".join(getattr(brief, "constraints", []) or []),
    ])).lower()
    # Whole-phrase, word-boundary matching. Substring matching would catch
    # "weapon" inside unrelated words and, worse, catch a generic word from
    # a multi-word phrase in briefs that have nothing to do with it.
    kind = "airsoft" if _has(AIRSOFT_WORDS, text) else "bow" if _has(BOW_WORDS, text) else ""
    launcher_ok = False
    if kind:
        refused = launcher_refused(kind, text, bool(p.get("forbid_launchers", False)))
        if refused:
            out.append(Finding(
                "block", "forbidden_domains",
                f"the brief is for {'an airsoft device' if kind == 'airsoft' else 'a bow or crossbow'}, "
                f"and is not let through: {refused}. The rule is not editable."))
            return out
        launcher_ok = True
        out.append(Finding(
            "signoff", "launcher_requires_human_signoff",
            "the brief is for something that launches a projectile. Nemo designs its "
            "electronics and wiring only, and has checked nothing but the figures the "
            "brief states. Before anything is built a person must measure the energy of "
            "what it fires, confirm it uses no gas, and check the law where it will be "
            "used and who may use it."))

    declared = _has(PROP_WORDS, text)
    prop_of: list[str] = []
    for domain in p.get("forbidden_domains", []):
        if not _has([domain], text):
            continue
        if launcher_ok and (domain in PROP_EXEMPT or domain == "projectile launcher"):
            continue                    # already allowed above, under its own conditions
        why_not = None
        if domain in PROP_EXEMPT and declared:
            thrown = _has(PROP_DEFEATED_BY, text)
            moving = moving_parts(parts)
            if p.get("forbid_weapon_props", False):
                why_not = "props of weapons are switched off by this machine's policy"
            elif thrown:
                why_not = (f"it calls itself a {declared} but also says '{thrown}'; a "
                           "prop lights up and makes sound and throws nothing")
            elif moving:
                why_not = (f"it calls itself a {declared} but its parts include "
                           f"{', '.join(moving)}, which can move or switch something; "
                           "a prop lights up and makes sound and nothing else")
            else:
                prop_of.append(domain)
                continue
        out.append(Finding(
            "block", "forbidden_domains",
            f"the brief matches '{domain}', which this assistant does "
            "not design toward at any policy level. "
            + (f"It is not let through as a prop: {why_not}. " if why_not else "")
            + "If this is a false match, rephrase the brief -- the rule is "
            "not editable."))
        break
    else:
        if prop_of:
            out.append(Finding(
                "signoff", "weapon_prop_requires_human_signoff",
                f"the brief describes a {declared} of a {prop_of[0]}. Nemo designs its "
                "lights, sound and wiring only. Before anything is built a person "
                "must confirm that it cannot launch, fire or shock anything, and "
                "must check the law on realistic imitations where it will be "
                "carried."))

    return out


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "block"]


def signoffs(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "signoff"]
