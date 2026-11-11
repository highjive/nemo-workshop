"""Science: units, maths, physics, statistics and spreadsheets (owner,
2026-10-22: "units and conversions, general maths and physics", with the
spreadsheets put in this department at his word).

  Calculator     converts units with the working shown (pint); a conversion
                 that cannot be (metres to kilograms) is refused, not guessed
  Mathematician  solves, simplifies, factors, expands, differentiates and
                 integrates (sympy), exact first, then as a decimal
  Physicist      a formula from FORMULAS solved for whichever quantity is
                 missing, the units carried through, so a wrong unit is caught
  Statistician   a column of numbers: count, mean, median, spread, range, the
                 trend, values far from the rest, and a chart (numpy, scipy,
                 matplotlib)
  Bookkeeper     reads an Excel .xlsx (its sheets and cells, formulas as
                 written) and writes one, with working formulas (openpyxl)
  Writer         each answer as a worked sheet: the question, the steps, the
                 answer with its units (<storeroom>/science/)

Nothing asks the model: the answers come from the libraries. Typed maths is
checked before sympy reads it, as sympy's reader runs what it is given as
Python: only numbers, operators, single-letter names and known functions.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path


class ScienceError(ValueError):
    pass


@dataclass
class Answer:
    question: str
    steps: list[str] = field(default_factory=list)
    result: str = ""
    sheet: Path | None = None
    chart: Path | None = None


# ---------------------------------------------------------------- the Calculator
_UREG = None


def ureg():
    global _UREG
    if _UREG is None:
        import pint
        _UREG = pint.UnitRegistry()
        _UREG.formatter.default_format = "~C"
    return _UREG


# A lone F, C or K beside another of them is a temperature (2026-11-08:
# "100 F" to "C" was read as farads to coulombs and refused).
_DEGREES = {"F": "degF", "C": "degC", "K": "kelvin"}


def _degrees(quantity: str, to_unit: str) -> tuple[str, str, bool]:
    m = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*([FCK])\s*", quantity)
    if m and to_unit.strip() in _DEGREES:
        return f"{m.group(1)} {_DEGREES[m.group(2)]}", _DEGREES[to_unit.strip()], True
    return quantity, to_unit, False


def convert(quantity: str, to_unit: str) -> Answer:
    """'10 inch' to 'mm': the value, and how it was got."""
    import pint
    u = ureg()
    said = quantity
    quantity, to_unit, as_degrees = _degrees(quantity, to_unit)
    try:
        q = u.Quantity(quantity.replace("°C", "degC").replace("°F", "degF"))
        target = u.Unit(to_unit.replace("°C", "degC").replace("°F", "degF"))
        out = q.to(target)
    except pint.errors.DimensionalityError as exc:
        raise ScienceError(f"{quantity} cannot be given in {to_unit}: one is {exc.dim1}, "
                           f"the other {exc.dim2}") from None
    except (pint.errors.UndefinedUnitError, ValueError, AttributeError) as exc:
        raise ScienceError(f"not a quantity Nemo knows: {exc}") from None
    a = Answer(f"{said} in {to_unit}")
    if as_degrees:
        a.steps.append("F, C and K read as degrees Fahrenheit, Celsius and kelvin, not farads, "
                       "coulombs and kelvin")
    if q.units != q.to_base_units().units and target != out.to_base_units().units:
        a.steps.append(f"{q:~C} = {q.to_base_units():.6g~C} (in base units)")
    if not (q.units in (u.degC, u.degF) or target in (u.degC, u.degF)):
        factor = (1 * q.units).to(target).magnitude
        a.steps.append(f"1 {q.units:~C} = {factor:.6g} {target:~C}")
    else:
        a.steps.append("temperatures have an offset as well as a scale, so they are converted, "
                       "not multiplied")
    a.result = f"{out.magnitude:.6g} {out.units:~C}"
    return a


# ---------------------------------------------------------------- the Mathematician
_FUNCS = {"sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh", "sqrt", "exp",
          "log", "ln", "abs", "pi", "E", "oo", "factorial", "floor", "ceiling"}
_ALLOWED = re.compile(r"^[0-9A-Za-z_+\-*/^().,= ]*$")


def _checked(text: str) -> str:
    """Typed maths that sympy may read: numbers, operators, single letters
    (x, y, a...) and the functions above. Anything else is refused."""
    if not text.strip():
        raise ScienceError("type the maths first")
    if not _ALLOWED.match(text) or "__" in text:
        raise ScienceError("only numbers, letters, + - * / ^ ( ) , . and = can be used")
    for word in re.findall(r"[A-Za-z_]{2,}", text):
        if word not in _FUNCS:
            raise ScienceError(f"{word!r} is not a function Nemo knows; it knows "
                               f"{', '.join(sorted(_FUNCS))}")
    return text.replace("^", "**").replace("ln(", "log(")


def _parse(text: str):
    from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application,
                                            parse_expr, standard_transformations)
    tf = standard_transformations + (implicit_multiplication_application, convert_xor)
    try:
        return parse_expr(_checked(text), transformations=tf, evaluate=True)
    except ScienceError:
        raise
    except Exception as exc:                                     # noqa: BLE001
        raise ScienceError(f"Nemo could not read that maths ({exc.__class__.__name__})") from None


def _decimal(v) -> str:
    try:
        f = complex(v.evalf())
        return f"{f.real:.6g}" if abs(f.imag) < 1e-12 else f"{f.real:.6g} {f.imag:+.6g}i"
    except (TypeError, ValueError):
        return ""


def maths(text: str, action: str = "solve") -> Answer:
    """solve, simplify, factor, expand, differentiate, integrate or evaluate."""
    import sympy as sp
    a = Answer(f"{action}: {text}")
    if action == "solve":
        if text.count("=") > 1:
            raise ScienceError("one equation at a time")
        left, _, right = text.partition("=")
        lhs, rhs = _parse(left), (_parse(right) if right.strip() else sp.Integer(0))
        expr = sp.simplify(lhs - rhs)
        names = sorted(expr.free_symbols, key=lambda s: s.name)
        if not names:
            raise ScienceError("there is nothing to solve for")
        x = names[0]
        a.steps.append(f"{sp.sstr(lhs)} = {sp.sstr(rhs)}")
        a.steps.append(f"move everything to one side: {sp.sstr(expr)} = 0")
        fac = sp.factor(expr)
        if fac != expr:
            a.steps.append(f"factorise: {sp.sstr(fac)} = 0")
        sols = sp.solve(expr, x)
        a.result = (", ".join(f"{x} = {sp.sstr(s)}" + (f" (about {_decimal(s)})"
                                                         if _decimal(s) and not s.is_Integer else "")
                              for s in sols) or f"no value of {x} makes it true")
        if len(names) > 1:
            a.steps.append(f"solved for {x}; the others ({', '.join(n.name for n in names[1:])}) "
                           "are kept as they are")
        return a
    expr = _parse(text)
    if "=" in text:
        raise ScienceError(f"to {action}, give an expression, not an equation")
    names = sorted(expr.free_symbols, key=lambda s: s.name)
    if action in ("differentiate", "integrate") and not names:
        raise ScienceError(f"there is no letter to {action} by")
    if action == "simplify":
        out = sp.simplify(expr)
    elif action == "factor":
        out = sp.factor(expr)
    elif action == "expand":
        out = sp.expand(expr)
    elif action == "differentiate":
        out = sp.diff(expr, names[0])
        a.steps.append(f"d/d{names[0]} of {sp.sstr(expr)}")
    elif action == "integrate":
        out = sp.integrate(expr, names[0])
        a.steps.append(f"the integral of {sp.sstr(expr)} with respect to {names[0]}")
        a.steps.append("plus a constant, C")
    elif action == "evaluate":
        out = expr.evalf()
    else:
        raise ScienceError(f"Nemo can solve, simplify, factor, expand, differentiate, integrate "
                           f"or evaluate; not {action!r}")
    a.result = sp.sstr(out) + (f" (about {_decimal(out)})" if not names and _decimal(out)
                                and action != "evaluate" else "")
    return a


# ---------------------------------------------------------------- the Physicist
# Each formula: what it is, the equation, and the SI unit of each quantity.
# Standard forms, as in any textbook; g is standard gravity, a defined value.
FORMULAS = {
    "ohm": ("Ohm's law", "V = I*R", {"V": "volt", "I": "ampere", "R": "ohm"}),
    "power": ("electrical power", "P = V*I", {"P": "watt", "V": "volt", "I": "ampere"}),
    "energy": ("energy used", "E = P*t", {"E": "joule", "P": "watt", "t": "second"}),
    "rc": ("RC time constant", "tau = R*C", {"tau": "second", "R": "ohm", "C": "farad"}),
    "force": ("Newton's second law", "F = m*a", {"F": "newton", "m": "kilogram",
                                                 "a": "meter/second**2"}),
    "speed": ("speed", "v = d/t", {"v": "meter/second", "d": "meter", "t": "second"}),
    "kinetic": ("kinetic energy", "E = m*v**2/2", {"E": "joule", "m": "kilogram",
                                                   "v": "meter/second"}),
    "potential": ("potential energy near the Earth", "E = m*g*h",
                  {"E": "joule", "m": "kilogram", "g": "meter/second**2", "h": "meter"}),
    "pressure": ("pressure", "p = F/A", {"p": "pascal", "F": "newton", "A": "meter**2"}),
    "density": ("density", "rho = m/V", {"rho": "kilogram/meter**3", "m": "kilogram",
                                         "V": "meter**3"}),
    "heat": ("heat to warm something", "Q = m*c*dT",
             {"Q": "joule", "m": "kilogram", "c": "joule/(kilogram*kelvin)", "dT": "kelvin"}),
    "wave": ("wave speed", "v = f*lam", {"v": "meter/second", "f": "hertz", "lam": "meter"}),
}
DEFAULTS = {"g": "9.80665 m/s**2"}                      # standard gravity, by definition


def formula(name: str, given: dict[str, str]) -> Answer:
    """Solve a FORMULAS entry for the one quantity not given."""
    import pint
    import sympy as sp
    if name not in FORMULAS and "=" in name:
        # The first value given where the formula's name goes ("R=?" ...): the
        # one formula with every quantity named is meant (2026-11-08).
        k, _, v = name.partition("=")
        given = {k.strip(): v, **given}
        using = [n for n, (_, _, units) in FORMULAS.items() if set(given) <= set(units)]
        exact = [n for n in using if len(FORMULAS[n][2]) == len(given)]
        fits = exact if len(exact) == 1 else using
        if len(fits) != 1:
            raise ScienceError(
                f"which formula? {' and '.join(fits)} use {', '.join(sorted(given))}: name one "
                f"first (nemo science formula {fits[0]} ...)" if fits else
                f"no formula Nemo knows uses {', '.join(sorted(given))}; it knows: "
                f"{', '.join(FORMULAS)}")
        name = fits[0]
    if name not in FORMULAS:
        raise ScienceError(f"Nemo knows these formulas: {', '.join(FORMULAS)}")
    what, eq, units = FORMULAS[name]
    # "V=?" (as the help shows it) or an empty box asks for that one: it is not
    # given (2026-11-06: `formula ohm V=? I="20 mA" R="220 ohm"` was refused).
    asked = [k for k, v in given.items() if str(v).strip() in ("", "?")]
    given = {k: v for k, v in given.items() if str(v).strip() not in ("", "?")}
    given = {**{k: v for k, v in DEFAULTS.items() if k in units and k not in given}, **given}
    unknown = [k for k in units if k not in given]
    extra = [k for k in given if k not in units]
    if extra:
        raise ScienceError(f"{what} has {', '.join(units)}; not {', '.join(extra)}")
    if len(unknown) != 1:
        missing = [k for k in unknown if k not in asked]
        raise ScienceError(f"give all but one of {', '.join(units)}"
                           + (f"; {', '.join(asked)} is asked for" if asked else "")
                           + (f"; {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} "
                              "missing" if missing else ""))
    u = ureg()
    values = {}
    a = Answer(f"{what} ({eq}): find {unknown[0]}")
    for k, v in given.items():
        try:
            q = u.Quantity(v)
            if q.dimensionless and not u.Unit(units[k]).dimensionless:
                q = q * u.Unit(units[k])                   # a bare number is taken in SI
                a.steps.append(f"{k} = {v} taken as {q:~C}")
            values[k] = q.to(units[k]).magnitude
        except pint.errors.DimensionalityError:
            raise ScienceError(f"{k} must be in {u.Unit(units[k]):~C} or like it; "
                               f"{v} is not") from None
        except (pint.errors.UndefinedUnitError, ValueError) as exc:
            raise ScienceError(f"{k}: not a quantity Nemo knows ({exc})") from None
        a.steps.append(f"{k} = {values[k]:.6g} {u.Unit(units[k]):~C}")
    syms = {k: sp.Symbol(k) for k in units}
    left, right = eq.split("=")
    expr = sp.sympify(left, locals=syms) - sp.sympify(right, locals=syms)
    sol = sp.solve(expr, syms[unknown[0]])
    found = [(float(s.subs({syms[k]: v for k, v in values.items()})), s) for s in sol]
    # Of two roots (a speed from an energy), the one that is not negative.
    value, used = next(((f, s) for f, s in found if f >= 0), found[0])
    a.steps.append(f"{eq}, so {unknown[0]} = {sp.sstr(used)}")
    # Rounded first: 0.99999... s would be shown as 1000 ms.
    out = u.Quantity(float(f"{value:.12g}"), units[unknown[0]]).to_compact()
    a.result = f"{unknown[0]} = {out.magnitude:.6g} {out.units:~C}"
    return a


# ---------------------------------------------------------------- the Statistician
def stats(numbers: list[float], chart: Path | None = None) -> Answer:
    import numpy as np
    from scipy import stats as st
    xs = np.array(numbers, dtype=float)
    if len(xs) < 2:
        raise ScienceError("give at least two numbers")
    a = Answer(f"statistics of {len(xs)} numbers")
    sd = xs.std(ddof=1)
    a.steps += [f"count {len(xs)}", f"mean {xs.mean():.6g}", f"median {np.median(xs):.6g}",
                f"standard deviation {sd:.6g} (of a sample)",
                f"smallest {xs.min():.6g}, largest {xs.max():.6g}"]
    if len(xs) >= 3:
        fit = st.linregress(np.arange(len(xs)), xs)
        a.steps.append(f"trend {fit.slope:+.6g} a reading (r² {fit.rvalue ** 2:.3f}, "
                       + ("a clear trend)" if fit.pvalue < 0.05 else "no clear trend)"))
    far = [f"{v:g}" for v in xs if sd and abs(v - xs.mean()) > 3 * sd]
    a.steps.append("far from the rest: " + (", ".join(far) if far else "none (none beyond 3 standard deviations)"))
    a.result = f"mean {xs.mean():.6g}, spread {sd:.6g}"
    if chart is not None:
        try:
            import matplotlib
        except ImportError:
            a.steps.append("no chart: matplotlib is not installed")
            return a
        matplotlib.use("Agg")                    # a file, not a window
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6, 3.2), dpi=100)
        ax.plot(range(1, len(xs) + 1), xs, marker="o", color="#B07A2A")
        ax.axhline(xs.mean(), color="#666666", linestyle="--", linewidth=1, label="mean")
        ax.set_xlabel("reading"); ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        chart.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(chart); plt.close(fig)
        a.chart = chart
    return a


# ---------------------------------------------------------------- the Bookkeeper
def read_sheet(path: Path, rows: int = 20) -> dict[str, list[list]]:
    """Each sheet's first rows, formulas as written ("=SUM(A1:A4)")."""
    import zipfile

    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException
    try:
        wb = openpyxl.load_workbook(path, data_only=False, read_only=True)
    # An .xlsx is a zip: a file that is not one raised BadZipFile here (its test).
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, InvalidFileException) as exc:
        raise ScienceError(f"{Path(path).name} could not be read as an .xlsx ({exc})") from None
    out = {}
    for ws in wb.worksheets:
        out[ws.title] = [list(r) for r in ws.iter_rows(max_row=rows, values_only=True)]
    wb.close()
    return out


def write_sheet(path: Path, title: str, header: list[str], rows: list[list],
                totals: bool = True) -> Path:
    """A new .xlsx: the header in bold, the rows, and (if asked) a row of
    SUM and AVERAGE formulas under each column of numbers. The formulas are
    worked out by Excel or LibreOffice when the file is opened."""
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31] or "Sheet"
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    if totals and rows:
        last = len(rows) + 1
        sums, means = ["Total"], ["Average"]
        for col in range(2, len(header) + 1):
            letter = get_column_letter(col)
            numeric = all(isinstance(r[col - 1], (int, float)) for r in rows if len(r) >= col)
            sums.append(f"=SUM({letter}2:{letter}{last})" if numeric else "")
            means.append(f"=AVERAGE({letter}2:{letter}{last})" if numeric else "")
        if len(header) == 1:
            sums, means = [f"=SUM(A2:A{last})"], [f"=AVERAGE(A2:A{last})"]
        ws.append(sums); ws.append(means)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ---------------------------------------------------------------- the Writer
def keep(cfg, a: Answer) -> Path:
    """The worked sheet: the question, the steps, the answer."""
    folder = cfg.path("paths.storeroom") / "science"
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", a.question)[:50].strip() or "answer"
    path = folder / f"{time.strftime('%Y-%m-%d %H%M%S')} {stem}.md"
    lines = [f"# {a.question}", "", "## Working", ""] + [f"{n}. {s}" for n, s in enumerate(a.steps, 1)]
    lines += ["", "## Answer", "", a.result]
    if a.chart:
        lines += ["", f"![chart]({a.chart.name})"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    a.sheet = path
    return path

