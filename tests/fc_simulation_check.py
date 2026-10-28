# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check in a real FreeCAD simulation that the generated formulas move the joint exactly as the
profile says (vanilla and patched builds).

Builds a tiny assembly at runtime (grounded box, moving box, revolute or slider joint), puts the
formula into a Motion, runs generateSimulation() and compares the joint value of every frame
with the profile. Frame 0 is the start state, frame k is time start + (k - 1) * step.

Run inside FreeCAD (GUI or a script runner that calls main()), e.g. from the assembly sandbox:
    ./common/run-test.sh <freecad> /path/to/MotionProfiles/tests/fc_simulation_check.py
Prints "RESULT: PASS" or "RESULT: FAIL".
"""
import math
import os
import sys

import FreeCAD as App

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from motionprofiles import formula, profiles  # noqa: E402

TOL = 1e-6
STEP = 0.05
END = 3.0

CASES = [
    # (joint, profile, quantity, params, table, initial velocity)
    ("Revolute", "ramp", "velocity", {"A": 30.0, "B": 20.0}, None, 0.0),
    ("Revolute", "scca", "acceleration", {"A": 0.25, "H": 200.0, "T": 2.0}, None, 0.0),
    ("Revolute", "cycloidal", "position", {"L": 120.0, "T": 2.5}, None, 0.0),
    ("Revolute", "table", "position", {}, [(0.0, 0.0), (1.0, 40.0), (2.0, 10.0), (3.0, 60.0)], 0.0),
    ("Slider", "cosine", "velocity", {"A": 4.0, "T": 1.5, "phi": 0.0, "B": 1.0}, None, 0.0),
    ("Slider", "polynomial", "acceleration", {"a": 2.0, "b": 0.0, "c": -0.5, "d": 0.0}, None, 1.0),
]


def build_assembly(joint_type):
    import JointObject
    import UtilsAssembly

    doc = App.newDocument("MotionProfilesCheck")
    asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
    base = doc.addObject("Part::Box", "Base")
    mover = doc.addObject("Part::Box", "Mover")
    mover.Placement.Base = App.Vector(0, 0, 10)
    asm.addObject(base)
    asm.addObject(mover)
    doc.recompute()

    grounded = UtilsAssembly.getJointGroup(asm).newObject("App::FeaturePython", "GroundedJoint")
    JointObject.GroundedJoint(grounded, base)

    joint = UtilsAssembly.getJointGroup(asm).newObject("App::FeaturePython", "Joint")
    JointObject.Joint(joint, JointObject.JointTypes.index(joint_type))
    if App.GuiUp:
        JointObject.ViewProviderJoint(joint.ViewObject)
    # top face of the base and bottom face of the mover, JCS at the face centres, z up
    joint.Reference1 = (base, ["Face6", "Face6"])
    joint.Reference2 = (mover, ["Face5", "Face5"])
    joint.Detach1 = True
    joint.Detach2 = True
    joint.Placement1 = App.Placement(App.Vector(5, 5, 10), App.Rotation())
    joint.Placement2 = App.Placement(App.Vector(5, 5, 0), App.Rotation())
    doc.recompute()
    asm.solve()
    return doc, asm, joint, mover


def joint_value(joint_type, start, now):
    if joint_type == "Revolute":
        delta = now.Rotation.multiply(start.Rotation.inverted())
        angle = delta.Angle * (1.0 if delta.Axis.z >= 0 else -1.0)
        return math.atan2(math.sin(angle), math.cos(angle))
    return now.Base.z - start.Base.z


def run_case(case):
    import CommandCreateSimulation as CCS
    import UtilsAssembly

    joint_type, key, quantity, params, table, v0 = case
    angular = joint_type == "Revolute"
    pos = profiles.build(key, params, quantity, angular=angular, initial_velocity=v0, table=table)
    text = formula.motion_formula(pos)

    doc, asm, joint, mover = build_assembly(joint_type)
    sim = UtilsAssembly.getSimulationGroup(asm).newObject("App::FeaturePython", "Simulation")
    CCS.Simulation(sim)
    sim.aTimeStart = 0.0
    sim.bTimeEnd = END
    sim.cTimeStepOutput = STEP
    motion = asm.newObject("App::FeaturePython", "Motion")
    CCS.Motion(motion, "Angular" if angular else "Linear", joint, text)
    sim.Group = [motion]

    rc = asm.generateSimulation(sim)
    frames = asm.numberOfFrames() if rc == 0 else 0
    label = f"{joint_type}/{key}/{quantity}"
    if frames < 3:
        App.closeDocument(doc.Name)
        return False, f"{label}: generateSimulation rc={rc}, Bilder={frames}"
    asm.updateForFrame(0)
    start = App.Placement(mover.Placement)
    worst, worst_t = 0.0, 0.0
    for k in range(1, frames):
        asm.updateForFrame(k)
        t = (k - 1) * STEP
        want = pos.value(t)
        if angular:
            want = math.atan2(math.sin(want), math.cos(want))
        err = abs(joint_value(joint_type, start, mover.Placement) - want)
        if angular:
            err = min(err, 2 * math.pi - err)
        if err > worst:
            worst, worst_t = err, t
    App.closeDocument(doc.Name)
    ok = worst <= TOL
    unit = "rad" if angular else "mm"
    return ok, f"{label}: {frames} Bilder, max. Abweichung {worst:.2e} {unit} bei t={worst_t:.2f} -> {'OK' if ok else 'FEHLER'}"


def main():
    results = [run_case(case) for case in CASES]
    for _, text in results:
        print(text)
    ok = all(good for good, _ in results)
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1
