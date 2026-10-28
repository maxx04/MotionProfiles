# SPDX-License-Identifier: LGPL-2.1-or-later
"""Write a Piecewise as an OndselSolver motion formula.

Uses only what the solver's SymbolicParser understands and what was verified in a real
simulation (Sandbox and vanilla weekly 2026.10.21): + - * / ^, sin, cos and
piecewise(time, functions(...), transitions(...)). spline(...) is not used: generating a
simulation with it fails in both builds.
"""
from .segments import Piecewise

TIME = "time"


def num(x):
    """Number literal; negative values in parentheses so they are safe after any operator."""
    x = float(x)
    if x == 0.0:
        return "0"
    text = repr(x)
    return f"({text})" if x < 0 else text


def _segment_expression(seg):
    tau = TIME if seg.start == 0.0 else f"({TIME} - {num(seg.start)})"
    terms = []
    for k, c in enumerate(seg.poly):
        if c == 0.0:
            continue
        if k == 0:
            terms.append(num(c))
        elif k == 1:
            terms.append(f"{num(c)}*{tau}")
        else:
            terms.append(f"{num(c)}*{tau}^{k}")
    for t in seg.trig:
        if t.amp == 0.0:
            continue
        phase = f" + {num(t.phase)}" if t.phase else ""
        terms.append(f"{num(t.amp)}*{t.kind}({num(t.omega)}*{tau}{phase})")
    return " + ".join(terms) if terms else "0"


def expression(pw: Piecewise):
    if len(pw.segments) == 1:
        return _segment_expression(pw.segments[0])
    functions = ", ".join(_segment_expression(s) for s in pw.segments)
    transitions = ", ".join(num(s.start) for s in pw.segments[1:])
    return f"piecewise({TIME}, functions({functions}), transitions({transitions}))"


def motion_formula(position: Piecewise):
    """Formula for an Assembly Motion: the profile is added to the joint's current value."""
    return f"initialValue + {expression(position)}"
