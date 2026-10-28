# SPDX-License-Identifier: LGPL-2.1-or-later
"""Connect a profile to an Assembly Motion: store the profile definition in extra properties of the
Motion (group "MotionProfile") and write the generated formula into Motion.Formula.

Only additive properties - a file stays readable and simulatable without the addon, the formula is
plain Assembly syntax. Works with vanilla FreeCAD and the assembly sandbox (joint instances with a
nesting prefix there, plain joints in vanilla).
"""
import json

import FreeCAD as App

from . import formula, profiles

GROUP = "MotionProfile"
PROPS = (
    ("ProfileQuantity", "App::PropertyString", "position, velocity or acceleration"),
    ("ProfileType", "App::PropertyString", "profile key (constant, ramp, ..., table)"),
    ("ProfileParameters", "App::PropertyString", "profile parameters as JSON"),
    ("ProfileTable", "App::PropertyString", "table points [[t, value], ...] as JSON"),
    ("ProfileDegree", "App::PropertyInteger", "table interpolation: 1 linear, 3 cubic"),
    ("ProfileInitialVelocity", "App::PropertyFloat", "initial velocity for acceleration profiles"),
)
SUPPORTED_JOINTS = ("Revolute", "Slider", "Cylindrical")


def default_spec():
    return {"quantity": "velocity", "profile": "constant", "params": {}, "table": [[0.0, 0.0], [1.0, 1.0]],
            "degree": 3, "v0": 0.0}


def has_profile(motion):
    return hasattr(motion, "ProfileType") and bool(motion.ProfileType)


def read_spec(motion):
    """Profile stored on the Motion, or None."""
    if not has_profile(motion):
        return None
    spec = default_spec()
    spec.update({
        "quantity": motion.ProfileQuantity or spec["quantity"],
        "profile": motion.ProfileType,
        "params": json.loads(motion.ProfileParameters or "{}"),
        "table": json.loads(motion.ProfileTable or "[]") or spec["table"],
        "degree": motion.ProfileDegree or 3,
        "v0": motion.ProfileInitialVelocity,
    })
    return spec


def position_curve(spec, angular):
    return profiles.build(spec["profile"], spec.get("params", {}), spec["quantity"], angular=angular,
                          initial_velocity=spec.get("v0", 0.0), table=spec.get("table"),
                          degree=spec.get("degree", 3))


def write_spec(motion, spec):
    """Store the profile on the Motion and set its formula."""
    for name, kind, doc in PROPS:
        if not hasattr(motion, name):
            motion.addProperty(kind, name, GROUP, doc)
    motion.ProfileQuantity = spec["quantity"]
    motion.ProfileType = spec["profile"]
    motion.ProfileParameters = json.dumps(spec.get("params", {}))
    motion.ProfileTable = json.dumps(spec.get("table", []))
    motion.ProfileDegree = int(spec.get("degree", 3))
    motion.ProfileInitialVelocity = float(spec.get("v0", 0.0))
    angular = motion.MotionType == "Angular"
    motion.Formula = formula.motion_formula(position_curve(spec, angular))


def joint_instances(asm):
    """[(joint, prefix)] of the drivable joints. The sandbox knows joint instances of nested
    sub-assemblies; vanilla only the joints themselves."""
    import UtilsAssembly

    if hasattr(UtilsAssembly, "getJointInstancesOfType"):
        return list(UtilsAssembly.getJointInstancesOfType(asm, list(SUPPORTED_JOINTS)))
    return [(j, "") for j in UtilsAssembly.getJointsOfType(asm, list(SUPPORTED_JOINTS))]


def joint_label(joint, prefix):
    import UtilsAssembly

    if prefix and hasattr(UtilsAssembly, "jointInstanceDisplayName"):
        return UtilsAssembly.jointInstanceDisplayName(joint, prefix)
    return joint.Label


def motion_types_for(joint):
    return {"Revolute": ["Angular"], "Slider": ["Linear"]}.get(joint.JointType, ["Angular", "Linear"])


def motion_joint(motion):
    """(joint, prefix) a Motion drives."""
    value = motion.Joint
    if isinstance(value, tuple):
        joint, subs = value[0], value[1]
        return joint, (subs[0] if subs else "")
    return value, ""


def find_simulation(asm):
    """Erste Simulation der Baugruppe oder None (legt nichts an)."""
    import CommandCreateSimulation as CCS

    for obj in asm.OutListRecursive:
        if hasattr(obj, "Proxy") and isinstance(getattr(obj, "Proxy", None), CCS.Simulation):
            return obj
    return None


def all_motions(asm):
    """Alle Motions in den Simulationen der Baugruppe."""
    return [o for o in asm.OutListRecursive
            if hasattr(o, "MotionType") and hasattr(o, "Formula") and hasattr(o, "Joint")]


def find_motion(asm, joint, prefix, exclude=None):
    """Motion, die bereits diese Gelenk-Instanz antreibt (sonst None). Eine Motion ohne
    Instanzpfad (aeltere Datei, Vanilla) gilt fuer das Gelenk selbst."""
    for motion in all_motions(asm):
        if motion is exclude:
            continue
        mj, mp = motion_joint(motion)
        if mj == joint and (mp == prefix or not mp):
            return motion
    return None


def get_or_create_simulation(asm):
    import CommandCreateSimulation as CCS
    import UtilsAssembly

    existing = find_simulation(asm)
    if existing is not None:
        return existing
    group = UtilsAssembly.getSimulationGroup(asm)
    sim = group.newObject("App::FeaturePython", "Simulation")
    CCS.Simulation(sim)
    if App.GuiUp:
        CCS.ViewProviderSimulation(sim.ViewObject)
    return sim


def create_motion(asm, sim, joint, prefix, motion_type, spec):
    import CommandCreateSimulation as CCS

    motion = asm.newObject("App::FeaturePython", "Motion")
    CCS.Motion(motion, motion_type, (joint, [prefix]) if prefix else joint, "")
    if App.GuiUp:
        CCS.ViewProviderMotion(motion.ViewObject)
    write_spec(motion, spec)
    sim.Group = sim.Group + [motion]
    return motion
