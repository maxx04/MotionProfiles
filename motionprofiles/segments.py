# SPDX-License-Identifier: LGPL-2.1-or-later
"""Piecewise closed-form functions of time: polynomial + sin/cos terms per segment.

This is the single representation used for preview, integration and formula output, so the
preview shows exactly what the solver gets. Every segment is written in its local time
tau = time - start; integration is exact (no sampling) and keeps the result continuous across
segment borders.
"""
import math
from dataclasses import dataclass, field


@dataclass
class Trig:
    """amp * sin(omega*tau + phase) or amp * cos(omega*tau + phase)."""

    kind: str  # "sin" | "cos"
    amp: float
    omega: float
    phase: float = 0.0

    def value(self, tau, order=0):
        """order-th derivative at tau."""
        angle = self.omega * tau + self.phase
        # d/dtau sin = omega cos, d/dtau cos = -omega sin
        shift = {"sin": 0, "cos": 1}[self.kind] + order
        base = (math.sin, math.cos, lambda a: -math.sin(a), lambda a: -math.cos(a))[shift % 4]
        return self.amp * self.omega**order * base(angle)

    def integral(self):
        if self.kind == "sin":
            return Trig("cos", -self.amp / self.omega, self.omega, self.phase)
        return Trig("sin", self.amp / self.omega, self.omega, self.phase)

    def scaled(self, factor):
        return Trig(self.kind, self.amp * factor, self.omega, self.phase)


@dataclass
class Segment:
    start: float
    poly: list = field(default_factory=lambda: [0.0])  # c0 + c1*tau + c2*tau^2 + ...
    trig: list = field(default_factory=list)

    def value(self, t, order=0):
        tau = t - self.start
        total = 0.0
        for k, c in enumerate(self.poly):
            if k >= order:
                total += c * math.prod(range(k - order + 1, k + 1)) * tau ** (k - order)
        return total + sum(term.value(tau, order) for term in self.trig)

    def integral(self, value_at_start):
        """Antiderivative of this segment that equals value_at_start at tau = 0."""
        poly = [0.0] + [c / (k + 1) for k, c in enumerate(self.poly)]
        trig = [term.integral() for term in self.trig]
        seg = Segment(self.start, poly, trig)
        seg.poly[0] += value_at_start - seg.value(self.start)
        return seg

    def scaled(self, factor):
        return Segment(self.start, [c * factor for c in self.poly], [t.scaled(factor) for t in self.trig])


class Piecewise:
    """Ordered segments; segment i is valid from its start up to the next start.
    Before the first start the first segment is used, after the last start the last one."""

    def __init__(self, segments):
        if not segments:
            raise ValueError("at least one segment required")
        starts = [s.start for s in segments]
        if any(b <= a for a, b in zip(starts, starts[1:])):
            raise ValueError("segment starts must be strictly increasing")
        self.segments = list(segments)

    def segment_at(self, t):
        current = self.segments[0]
        for seg in self.segments[1:]:
            if t < seg.start:
                break
            current = seg
        return current

    def value(self, t, order=0):
        return self.segment_at(t).value(t, order)

    def integral(self, value_at_start=0.0):
        """Continuous antiderivative, equal to value_at_start at the first segment start."""
        result = []
        current = value_at_start
        for i, seg in enumerate(self.segments):
            integ = seg.integral(current)
            result.append(integ)
            if i + 1 < len(self.segments):
                current = integ.value(self.segments[i + 1].start)
        return Piecewise(result)

    def shifted(self, offset):
        """Add a constant."""
        return Piecewise([Segment(s.start, [s.poly[0] + offset] + s.poly[1:], list(s.trig)) for s in self.segments])

    def scaled(self, factor):
        return Piecewise([s.scaled(factor) for s in self.segments])

    def plus_linear(self, slope, t0):
        """Add slope * (time - t0) (e.g. an initial velocity after integrating an acceleration)."""
        out = []
        for s in self.segments:
            poly = list(s.poly) + [0.0] * max(0, 2 - len(s.poly))
            poly[0] += slope * (s.start - t0)
            poly[1] += slope
            out.append(Segment(s.start, poly, list(s.trig)))
        return Piecewise(out)
