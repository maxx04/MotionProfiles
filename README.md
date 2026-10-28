# MotionProfiles

Servo-motor style motion profiles for FreeCAD Assembly simulations.

Choose what you drive — **position, velocity or acceleration** — and a profile shape
(constant, ramp, cosine, cycloidal, parabolic, polynomial, SCCA, or a table of points).
The addon turns it into a normal Assembly `Motion` formula, so files stay readable and
simulatable in FreeCAD without the addon.

Status: early development.
- Done: profile math and formula generation, verified in real simulations against FreeCAD weekly
  2026.10.21 and the assembly sandbox; task panel with live preview of position / velocity /
  acceleration (command "Bewegungsprofil" next to "Simulation" in the Assembly workbench).
- Next: Addon Manager metadata (package.xml), translations, result plots after a simulation.
- To discuss: a separate simulation addon with real actuators (force / torque, masses, friction) -
  dynamics instead of the kinematic, prescribed-motion simulation of Assembly.

## Usage

1. Activate an assembly, select a revolute, slider or cylindrical joint (or an existing Motion).
2. Assembly toolbar/menu: **Bewegungsprofil**.
3. Choose the driven quantity (Weg/Geschwindigkeit/Beschleunigung) and a profile, enter the
   values (degrees or mm, seconds) or a table; the preview shows all three curves.
4. OK creates or updates the Motion of the assembly's simulation. A joint that already has a Motion
   (also one made in the simulation dialog) gets that Motion edited - never a second one.
   "Übernehmen, simulieren und abspielen" saves, runs the simulation and plays it once in the 3D
   view; closing the panel puts the parts back where they were.

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
    # in FreeCAD (main()): tests/fc_simulation_check.py - real simulations
    #                      tests/fc_taskpanel_check.py  - task panel (GUI, e.g. under Xvfb)

## License

LGPL-2.1-or-later, like FreeCAD.
