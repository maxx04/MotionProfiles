# SPDX-License-Identifier: LGPL-2.1-or-later
"""Motion profiles in the style of a servo motor: choose the driven quantity (position,
velocity or acceleration) and a profile shape; the result is always a position curve relative
to the joint's value at the start of the simulation (t = 0).

Units in the parameters: mm and s for linear joints, degrees and s for angular joints.
The returned position curve is in solver units (mm resp. rad).
"""
import math
from dataclasses import dataclass

from .segments import Piecewise, Segment, Trig

QUANTITIES = ("position", "velocity", "acceleration")


@dataclass(frozen=True)
class ParamDef:
    key: str
    label: str
    default: float
    kind: str = "value"  # value: scaled with the quantity unit; time; angle (degrees); ratio


@dataclass(frozen=True)
class ProfileDef:
    key: str
    label: str
    formula_text: str
    params: tuple
    build: object  # callable(params dict) -> Piecewise of the chosen quantity


def _const(p):
    return Piecewise([Segment(0.0, [p["A"]])])


def _ramp(p):
    return Piecewise([Segment(0.0, [p["A"], p["B"]])])


def _cosine(p):
    omega = 2.0 * math.pi / p["T"]
    return Piecewise([Segment(0.0, [p["B"]], [Trig("cos", p["A"], omega, math.radians(p["phi"]))])])


def _cycloidal(p):
    omega = 2.0 * math.pi / p["T"]
    return Piecewise([Segment(0.0, [0.0, p["L"] / p["T"]], [Trig("sin", -p["L"] / (2.0 * math.pi), omega)])])


def _parabolic(p):
    return Piecewise([Segment(0.0, [0.0, p["A"], 0.5 * p["B"]])])


def _polynomial(p):
    return Piecewise([Segment(0.0, [p["a"], p["b"], p["c"], p["d"]])])


def _scca(p):
    """Sine-constant-cosine acceleration over one period T: rest to rest when used as
    acceleration. Fractions: A for the sine/cosine flanks, B = 1/2 - A for the constant parts."""
    a, h, period = p["A"], p["H"], p["T"]
    if not 0.0 < a <= 0.5:
        raise ValueError("SCCA: A must be in (0, 0.5]")
    b = 0.5 - a
    w = math.pi / (a * period)  # half sine over a*T/2 ... full cosine half-wave over a*T
    t1 = 0.5 * a * period
    t2 = t1 + b * period
    t3 = t2 + a * period
    t4 = t3 + b * period
    segs = [
        Segment(0.0, [0.0], [Trig("sin", h, w)]),
        Segment(t1, [h]),
        Segment(t2, [0.0], [Trig("cos", h, w)]),
        Segment(t3, [-h]),
        Segment(t4, [0.0], [Trig("cos", -h, w)]),
    ]
    # drop empty constant parts (A = 0.5)
    unique = []
    for s in segs:
        if unique and s.start <= unique[-1].start:
            unique[-1] = s
        else:
            unique.append(s)
    return Piecewise(unique)


PROFILES = {
    d.key: d
    for d in (
        ProfileDef("constant", "Konstant", "A", (ParamDef("A", "A", 1.0),), _const),
        ProfileDef("ramp", "Rampe", "A + B·t", (ParamDef("A", "A", 0.0), ParamDef("B", "B", 1.0)), _ramp),
        ProfileDef(
            "cosine",
            "Cosinus",
            "A·cos(360°·t/T + φ) + B",
            (ParamDef("A", "A", 1.0), ParamDef("T", "T", 1.0, "time"), ParamDef("phi", "φ", 0.0, "angle"),
             ParamDef("B", "B", 0.0)),
            _cosine,
        ),
        ProfileDef(
            "cycloidal",
            "Zykloidisch",
            "L·(t/T − sin(360°·t/T)/2π)",
            (ParamDef("L", "L", 1.0), ParamDef("T", "T", 1.0, "time")),
            _cycloidal,
        ),
        ProfileDef("parabolic", "Parabolisch", "A·t + ½·B·t²", (ParamDef("A", "A", 0.0), ParamDef("B", "B", 1.0)),
                   _parabolic),
        ProfileDef(
            "polynomial",
            "Polynom",
            "a + b·t + c·t² + d·t³",
            (ParamDef("a", "a", 0.0), ParamDef("b", "b", 1.0), ParamDef("c", "c", 0.0), ParamDef("d", "d", 0.0)),
            _polynomial,
        ),
        ProfileDef(
            "scca",
            "SCCA",
            "Sinus-Konstant-Cosinus (Anteil A, Höhe H, Periode T)",
            (ParamDef("A", "A", 0.25, "ratio"), ParamDef("H", "H", 1.0), ParamDef("T", "T", 1.0, "time")),
            _scca,
        ),
    )
}


def table_profile(points, degree=3):
    """Piecewise curve through (t, value) points: degree 1 (linear) or 3 (natural cubic spline)."""
    pts = sorted((float(t), float(v)) for t, v in points)
    if len(pts) < 2:
        raise ValueError("table: at least two points")
    ts = [t for t, _ in pts]
    vs = [v for _, v in pts]
    if any(b <= a for a, b in zip(ts, ts[1:])):
        raise ValueError("table: times must be distinct")
    n = len(pts)
    if degree == 1 or n == 2:
        segs = [Segment(ts[i], [vs[i], (vs[i + 1] - vs[i]) / (ts[i + 1] - ts[i])]) for i in range(n - 1)]
        return Piecewise(segs)
    if degree != 3:
        raise ValueError("table: degree 1 or 3")
    h = [ts[i + 1] - ts[i] for i in range(n - 1)]
    # natural spline: second derivatives m (m0 = m_{n-1} = 0), tridiagonal system (Thomas)
    a = [0.0] * n
    b = [1.0] * n
    c = [0.0] * n
    d = [0.0] * n
    for i in range(1, n - 1):
        a[i] = h[i - 1]
        b[i] = 2.0 * (h[i - 1] + h[i])
        c[i] = h[i]
        d[i] = 6.0 * ((vs[i + 1] - vs[i]) / h[i] - (vs[i] - vs[i - 1]) / h[i - 1])
    for i in range(1, n):
        w = a[i] / b[i - 1]
        b[i] -= w * c[i - 1]
        d[i] -= w * d[i - 1]
    m = [0.0] * n
    m[-1] = d[-1] / b[-1]
    for i in range(n - 2, -1, -1):
        m[i] = (d[i] - c[i] * m[i + 1]) / b[i]
    segs = []
    for i in range(n - 1):
        slope = (vs[i + 1] - vs[i]) / h[i] - h[i] * (2.0 * m[i] + m[i + 1]) / 6.0
        segs.append(Segment(ts[i], [vs[i], slope, 0.5 * m[i], (m[i + 1] - m[i]) / (6.0 * h[i])]))
    return Piecewise(segs)


def unit_factor(angular):
    """Factor from user units (deg resp. mm) to solver units (rad resp. mm)."""
    return math.pi / 180.0 if angular else 1.0


def position_curve(quantity, curve: Piecewise, angular=False, initial_velocity=0.0):
    """Position relative to the start value (0 at t = 0) in solver units.

    curve is the chosen quantity in user units; initial_velocity only matters for acceleration.
    """
    if quantity not in QUANTITIES:
        raise ValueError(f"unknown quantity {quantity!r}")
    if quantity == "position":
        pos = curve.shifted(-curve.value(0.0))
    elif quantity == "velocity":
        pos = curve.integral(0.0)
    else:
        pos = curve.integral(initial_velocity).integral(0.0)
    return pos.scaled(unit_factor(angular))


def build(profile_key, params, quantity, angular=False, initial_velocity=0.0, table=None, degree=3):
    """Position curve (solver units, relative to start) for a profile or a table."""
    if profile_key == "table":
        curve = table_profile(table or [], degree)
    else:
        definition = PROFILES[profile_key]
        values = {p.key: float(params.get(p.key, p.default)) for p in definition.params}
        curve = definition.build(values)
    return position_curve(quantity, curve, angular, initial_velocity)
