# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pure-Python tests of the profile math and the formula text (no FreeCAD needed).

Run: python3 -m unittest discover -s tests
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from motionprofiles import formula, profiles  # noqa: E402
from motionprofiles.segments import Piecewise, Segment, Trig  # noqa: E402

TIMES = [i * 0.037 for i in range(0, 90)]  # 0 .. 3.3 s, not aligned with segment borders


def numeric_derivative(fn, t, h=1e-5):
    return (fn(t + h) - fn(t - h)) / (2 * h)


def eval_formula(text, t):
    """Evaluate a generated formula in Python with the solver's semantics."""
    def piecewise(_x, funcs, trans):
        for f, border in zip(funcs, trans):
            if t < border:
                return f
        return funcs[-1]

    code = text.replace("^", "**")
    env = {"time": t, "initialValue": 0.0, "sin": math.sin, "cos": math.cos,
           "functions": lambda *a: a, "transitions": lambda *a: a, "piecewise": piecewise}
    return eval(code, {"__builtins__": {}}, env)


class SegmentTests(unittest.TestCase):
    def test_derivatives_match_numeric(self):
        seg = Segment(0.5, [1.0, -2.0, 0.3, 0.7], [Trig("sin", 0.4, 3.0, 0.2), Trig("cos", -1.1, 1.5)])
        for t in TIMES:
            for order in (1, 2):
                self.assertAlmostEqual(seg.value(t, order), numeric_derivative(lambda x: seg.value(x, order - 1), t), 5)

    def test_integral_is_continuous_and_exact(self):
        pw = Piecewise([Segment(0.0, [1.0]), Segment(1.0, [0.0], [Trig("cos", 2.0, math.pi)]), Segment(2.0, [-1.0, 0.5])])
        integ = pw.integral(0.0)
        self.assertAlmostEqual(integ.value(0.0), 0.0)
        for border in (1.0, 2.0):
            self.assertAlmostEqual(integ.value(border - 1e-9), integ.value(border), 7)
        for t in TIMES:
            if min(abs(t - b) for b in (1.0, 2.0)) > 1e-4:
                self.assertAlmostEqual(numeric_derivative(integ.value, t), pw.value(t), 5)


class ProfileTests(unittest.TestCase):
    def check(self, quantity, curve, angular, v0=0.0):
        pos = profiles.position_curve(quantity, curve, angular, v0)
        k = profiles.unit_factor(angular)
        self.assertAlmostEqual(pos.value(0.0), 0.0, 9)
        for t in TIMES:
            if quantity == "position":
                want, got = k * (curve.value(t) - curve.value(0.0)), pos.value(t)
            elif quantity == "velocity":
                want, got = k * curve.value(t), pos.value(t, 1)
            else:
                want, got = k * curve.value(t), pos.value(t, 2)
            self.assertAlmostEqual(got, want, 7, f"{quantity} t={t}")
        if quantity == "acceleration":
            self.assertAlmostEqual(pos.value(0.0, 1), k * v0, 9)
        return pos

    def test_all_profiles_all_quantities(self):
        for key, definition in profiles.PROFILES.items():
            params = {p.key: p.default for p in definition.params}
            curve = definition.build(params)
            for quantity in profiles.QUANTITIES:
                for angular in (False, True):
                    with self.subTest(profile=key, quantity=quantity, angular=angular):
                        self.check(quantity, curve, angular, v0=0.3)

    def test_scca_rest_to_rest(self):
        curve = profiles.PROFILES["scca"].build({"A": 0.25, "H": 2.0, "T": 1.5})
        pos = profiles.position_curve("acceleration", curve)
        self.assertAlmostEqual(pos.value(1.5, 1), 0.0, 9)  # velocity back to zero after one period
        self.assertGreater(pos.value(1.5), 0.0)
        for border in (seg.start for seg in curve.segments[1:]):
            self.assertAlmostEqual(curve.value(border - 1e-9), curve.value(border), 6)  # acceleration continuous

    def test_cycloidal_rest_to_rest_position(self):
        pos = profiles.build("cycloidal", {"L": 90.0, "T": 2.0}, "position", angular=True)
        self.assertAlmostEqual(pos.value(2.0), math.radians(90.0), 9)
        self.assertAlmostEqual(pos.value(2.0, 1), 0.0, 9)
        self.assertAlmostEqual(pos.value(0.0, 1), 0.0, 9)

    def test_table_linear_and_cubic(self):
        pts = [(0.0, 0.0), (1.0, 5.0), (2.5, 2.0), (3.0, 4.0)]
        for degree in (1, 3):
            curve = profiles.table_profile(pts, degree)
            for t, v in pts:
                self.assertAlmostEqual(curve.value(t), v, 9)
        cubic = profiles.table_profile(pts, 3)
        for border in (1.0, 2.5):
            for order in (0, 1, 2):
                self.assertAlmostEqual(cubic.value(border - 1e-9, order), cubic.value(border, order), 5)
        self.assertAlmostEqual(cubic.value(0.0, 2), 0.0, 9)  # natural end
        self.assertAlmostEqual(cubic.value(3.0, 2), 0.0, 6)

    def test_table_errors(self):
        with self.assertRaises(ValueError):
            profiles.table_profile([(0.0, 1.0)])
        with self.assertRaises(ValueError):
            profiles.table_profile([(0.0, 1.0), (0.0, 2.0)])


class FormulaTests(unittest.TestCase):
    def test_formula_reproduces_curve(self):
        cases = [("table", "velocity", {}), ("scca", "acceleration", {}), ("cosine", "position", {"phi": 30.0}),
                 ("polynomial", "acceleration", {"d": -0.5})]
        for key, quantity, params in cases:
            table = [(0.0, 0.0), (0.7, 3.0), (1.9, -1.0), (2.4, 2.0)] if key == "table" else None
            pos = profiles.build(key, params, quantity, angular=True, initial_velocity=10.0, table=table)
            text = formula.motion_formula(pos)
            self.assertTrue(text.startswith("initialValue + "))
            for t in TIMES:
                with self.subTest(profile=key, t=t):
                    self.assertAlmostEqual(eval_formula(text, t), pos.value(t), 9)

    def test_negative_numbers_parenthesised(self):
        self.assertEqual(formula.num(-2.5), "(-2.5)")
        self.assertEqual(formula.num(0.0), "0")
        text = formula.expression(Piecewise([Segment(1.0, [-1.0, 2.0])]))
        self.assertEqual(text, "(-1.0) + 2.0*(time - 1.0)")


if __name__ == "__main__":
    unittest.main()
