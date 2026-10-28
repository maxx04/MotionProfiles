# MotionProfiles

Servo-motor style motion profiles for FreeCAD Assembly simulations.

Choose what you drive — **position, velocity or acceleration** — and a profile shape
(constant, ramp, cosine, cycloidal, parabolic, polynomial, SCCA, or a table of points).
The addon turns it into a normal Assembly `Motion` formula, so files stay readable and
simulatable in FreeCAD without the addon.

Status: early development. Done: profile math and formula generation (phase 1), verified in
real simulations against FreeCAD weekly 2026.10.21 (phase 2). Next: task panel with live
preview of position / velocity / acceleration.

## How it works

The solver (OndselSolver) parses motion formulas with `+ - * / ^`, `sin`, `cos` and
`piecewise(time, functions(...), transitions(...))`. Every profile is kept as piecewise
polynomials plus sin/cos terms; velocity and acceleration profiles are integrated exactly
per segment. The preview and the solver therefore see the same curve.

Notes:
- The profile is added to the joint's value at the start (`initialValue + ...`).
- Units in the dialog: degrees or mm, seconds. Formulas use rad or mm.
- `spline(...)` in formulas is not used: generating a simulation with it fails.
- Assembly simulations currently do not respect joint limits.

## Tests

    python3 -m unittest discover -s tests          # math and formula text, no FreeCAD needed
    # in FreeCAD: tests/fc_simulation_check.py (main()) - runs real simulations

## License

LGPL-2.1-or-later, like FreeCAD.
