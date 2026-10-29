# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI check of the task panel (needs FreeCAD with GUI, e.g. under Xvfb): set values, OK creates a
Motion whose simulation follows the profile, reopening shows the stored values, Cancel on an
assembly without simulation leaves nothing behind.

Run inside FreeCAD (main()), e.g.:
    ./common/run-test.sh <freecad> /path/to/MotionProfiles/tests/fc_taskpanel_check.py
Prints "RESULT: PASS" or "RESULT: FAIL".
"""
import math
import os
import sys
import time

import FreeCAD as App

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from fc_simulation_check import build_assembly, joint_value  # noqa: E402
from motionprofiles import commands, motion_link  # noqa: E402
from motionprofiles.taskpanel import MotionProfileTaskPanel  # noqa: E402

TOL = 1e-6


def check(label, ok, detail=""):
    print(f"{label}: {detail} -> {'OK' if ok else 'FEHLER'}")
    return ok


def main():
    commands.register()
    ok = True

    # 1) Cancel without simulation: nothing created
    doc, asm, joint, mover = build_assembly("Revolute")
    panel = MotionProfileTaskPanel(asm, joint=joint)
    panel.reject()
    sims = [o for o in doc.Objects if "Simulation" in o.Name and o.TypeId == "App::FeaturePython"]
    ok &= check("Abbrechen", not sims, f"{len(sims)} Simulation(en) angelegt")

    # 2) New motion: velocity ramp, preview, OK
    panel = MotionProfileTaskPanel(asm, joint=joint)
    panel._set_combo(panel.quantity_combo, "velocity")
    panel._set_combo(panel.profile_combo, "ramp")
    panel.param_boxes["A"].setValue(30.0)
    panel.param_boxes["B"].setValue(20.0)
    panel.t_end.setValue(2.0)
    panel.t_step.setValue(0.05)
    pos = panel.update_preview()
    ok &= check("Vorschau", pos is not None and panel.canvas is not None,
                f"Kurve {'da' if pos else 'fehlt'}, Diagramm {'da' if panel.canvas else 'fehlt'}")
    ok &= check("OK", panel.accept() is True)
    motions = [o for o in doc.Objects if motion_link.has_profile(o)]
    ok &= check("Motion angelegt", len(motions) == 1, f"{len(motions)} Motion(s)")
    motion = motions[0]
    sim = motion_link.find_simulation(asm)
    ok &= check("in Simulation", sim is not None and motion in sim.Group)

    # 3) simulation follows the profile (degrees -> rad)
    rc = asm.generateSimulation(sim)
    frames = asm.numberOfFrames() if rc == 0 else 0
    asm.updateForFrame(0)
    start = App.Placement(mover.Placement)
    worst = 0.0
    for k in range(1, frames):
        asm.updateForFrame(k)
        t = (k - 1) * 0.05
        want = math.radians(30.0 * t + 10.0 * t * t)
        want = math.atan2(math.sin(want), math.cos(want))
        err = abs(joint_value("Revolute", start, mover.Placement) - want)
        worst = max(worst, min(err, 2 * math.pi - err))
    ok &= check("Simulation folgt dem Profil", frames > 3 and worst < TOL,
                f"rc={rc}, {frames} Bilder, max. Abweichung {worst:.2e} rad")

    # 4) reopen on the motion: values back
    panel = MotionProfileTaskPanel(asm, motion=motion)
    spec = panel.current_spec()
    ok &= check("Wieder geöffnet", spec["quantity"] == "velocity" and spec["profile"] == "ramp"
                and abs(spec["params"]["A"] - 30.0) < 1e-9 and abs(spec["params"]["B"] - 20.0) < 1e-9,
                f"{spec['quantity']}/{spec['profile']} A={spec['params'].get('A')} B={spec['params'].get('B')}")
    # switch to a table and save: formula changes, still one motion
    before = motion.Formula
    panel._set_combo(panel.profile_combo, "table")
    panel._set_combo(panel.quantity_combo, "position")
    panel.accept()
    ok &= check("Tabelle gespeichert", motion.ProfileType == "table" and motion.Formula != before
                and len([o for o in doc.Objects if motion_link.has_profile(o)]) == 1,
                f"ProfileType={motion.ProfileType}")

    # 5) open/close through the real task view: no "C++ object already deleted" from matplotlib
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

    errors = []
    previous_hook = sys.excepthook
    sys.excepthook = lambda kind, value, tb: errors.append(f"{kind.__name__}: {value}")
    try:
        for i in range(3):
            panel = MotionProfileTaskPanel(asm, motion=motion)
            Gui.Control.showDialog(panel)
            for _ in range(10):
                QtWidgets.QApplication.processEvents()
                QtCore.QThread.msleep(20)
            panel.param_boxes.get("A", panel.v0_box).setValue(1.0 + i) if panel.param_boxes else None
            panel.accept() if i == 1 else panel.reject()
            for _ in range(10):
                QtWidgets.QApplication.processEvents()
                QtCore.QThread.msleep(20)
    finally:
        sys.excepthook = previous_hook
    ok &= check("Aufgabenansicht öffnen/schließen", not errors, "; ".join(errors[:2]) or "keine Fehler")

    # mouse wheel over the plot goes on to the task view (scrolling), not swallowed by matplotlib
    panel = MotionProfileTaskPanel(asm, motion=motion)
    centre = QtCore.QPointF(10, 10)
    wheel = QtGui.QWheelEvent(centre, centre, QtCore.QPoint(), QtCore.QPoint(0, -120),
                              QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
    wheel.accept()
    panel.canvas.wheelEvent(wheel)
    ok &= check("Mausrad über Diagramm", not wheel.isAccepted(), "weitergereicht" if not wheel.isAccepted() else "verschluckt")
    panel.reject()

    # 6) joint chosen without motion: the existing motion is edited, no second one
    panel = MotionProfileTaskPanel(asm, joint=joint)
    ok &= check("Vorhandene Motion gewählt", panel.motion is motion and "vorhandene" in panel.target_label.text(),
                panel.target_label.text())
    panel.accept()
    count = len([o for o in doc.Objects if hasattr(o, "MotionType")])
    ok &= check("Keine zweite Motion", count == 1, f"{count} Motion(s)")
    App.closeDocument(doc.Name)

    # 7) plain motion from the simulation dialog (no profile): taken over, formula replaced
    import CommandCreateSimulation as CCS

    doc, asm, joint, mover = build_assembly("Revolute")
    sim = motion_link.get_or_create_simulation(asm)
    plain = asm.newObject("App::FeaturePython", "Motion")
    CCS.Motion(plain, "Angular", joint, "10*time")
    sim.Group = sim.Group + [plain]
    doc.recompute()
    panel = MotionProfileTaskPanel(asm, joint=joint)
    ok &= check("Fremde Motion übernommen", panel.motion is plain and "ersetzt" in panel.target_label.text(),
                panel.target_label.text())
    panel._set_combo(panel.quantity_combo, "velocity")
    panel._set_combo(panel.profile_combo, "constant")
    panel.param_boxes["A"].setValue(45.0)
    panel.t_end.setValue(1.0)
    panel.t_step.setValue(0.05)

    # 8) play button: saves, simulates, moves the part, restores on close
    start = App.Placement(mover.Placement)
    panel.play()
    seen = 0.0
    for _ in range(300):
        QtWidgets.QApplication.processEvents()
        QtCore.QThread.msleep(10)
        seen = max(seen, abs(joint_value("Revolute", start, mover.Placement)))
        if panel.timer is None or not panel.timer.isActive():
            break
    motions = [o for o in doc.Objects if hasattr(o, "MotionType")]
    ok &= check("Abspielen", panel.frames > 3 and seen > 0.1 and not panel.timer.isActive(),
                f"{panel.frames} Bilder, max. Winkel {math.degrees(seen):.1f}°, Meldung „{panel.message.text()}“")
    ok &= check("Abspielen speichert", len(motions) == 1 and plain.ProfileType == "constant"
                and plain.Formula != "10*time", f"{len(motions)} Motion(s), Formel {plain.Formula[:40]}")
    panel.reject()
    back = mover.Placement.isSame(start, 1e-9)
    ok &= check("Lage nach Schließen zurück", back, str(mover.Placement))

    # 9) list of existing motions: shown, selecting loads it, delete removes it
    panel = MotionProfileTaskPanel(asm)
    texts = [panel.motion_list.item(i).text() for i in range(panel.motion_list.count())]
    ok &= check("Liste", len(texts) == 1 and "Profil constant" in texts[0], "; ".join(texts))
    panel._set_combo(panel.profile_combo, "ramp")
    panel.motion_list.setCurrentRow(-1)
    panel.motion_list.setCurrentRow(0)
    ok &= check("Auswahl lädt", panel.motion is plain and panel.explicit
                and panel.profile_combo.currentData() == "constant"
                and abs(panel.param_boxes["A"].value() - 45.0) < 1e-9,
                f"Profil {panel.profile_combo.currentData()}")
    panel.delete_motion()
    left = [o for o in doc.Objects if hasattr(o, "MotionType")]
    ok &= check("Löschen", not left and panel.motion is None and panel.motion_list.count() == 0
                and not sim.Group and "neue" in panel.target_label.text(),
                f"{len(left)} Motion(s), Liste {panel.motion_list.count()}, „{panel.target_label.text()}“")
    doc.undo()
    ok &= check("Löschen rückgängig", len([o for o in doc.Objects if hasattr(o, "MotionType")]) == 1)
    panel.reject()
    App.closeDocument(doc.Name)

    # 10) limits: sandbox stops at the limit and says so, vanilla says limits are ignored
    respects = motion_link.simulation_respects_limits()
    doc, asm, joint, mover = build_assembly("Revolute")
    joint.EnableAngleMin = True
    joint.AngleMin = -90.0
    joint.EnableAngleMax = True
    joint.AngleMax = 20.0
    doc.recompute()
    panel = MotionProfileTaskPanel(asm, joint=joint)
    ok &= check("Hinweistext", ("hält die Simulation dort an" in panel.hint.text()) == respects,
                panel.hint.text()[:60])
    ok &= check("Knopf farbig", "background-color" in panel.play_button.styleSheet())
    panel._set_combo(panel.quantity_combo, "velocity")
    panel._set_combo(panel.profile_combo, "constant")
    panel.param_boxes["A"].setValue(45.0)
    panel.t_end.setValue(1.0)
    panel.t_step.setValue(0.05)
    panel.play()
    for _ in range(300):
        QtWidgets.QApplication.processEvents()
        QtCore.QThread.msleep(10)
        if panel.timer is None or not panel.timer.isActive():
            break
    stopped = "Gelenkgrenze" in panel.message.text()
    ok &= check("Anschlag gemeldet", stopped == respects and panel.progress.value() == panel.frames - 1,
                f"{panel.frames} Bilder, „{panel.message.text()}“, Balken {panel.progress.format()}")
    # replay: shows the computed frames again without recomputing
    frames_before = panel.frames
    calls = []
    original = asm.generateSimulation
    panel.replay()
    seen_frames = []
    for _ in range(300):
        QtWidgets.QApplication.processEvents()
        QtCore.QThread.msleep(10)
        seen_frames.append(panel.progress.value())
        if panel.timer is None or not panel.timer.isActive():
            break
    ok &= check("Abspielen ohne Neuberechnen", panel.frames == frames_before and max(seen_frames) == frames_before - 1
                and panel.replay_button.text().endswith("Abspielen"),
                f"{panel.frames} Bilder, bis Bild {max(seen_frames)}")
    panel.reject()
    App.closeDocument(doc.Name)

    # 11) long simulation: progress per frame mirrored from FreeCAD's sequencer (sandbox)
    doc, asm, joint, mover = build_assembly("Revolute")
    panel = MotionProfileTaskPanel(asm, joint=joint)
    panel._set_combo(panel.quantity_combo, "velocity")
    panel._set_combo(panel.profile_combo, "constant")
    panel.param_boxes["A"].setValue(10.0)
    panel.t_end.setValue(20.0)
    panel.t_step.setValue(0.002)
    t0 = time.time()
    panel.play()
    seconds = time.time() - t0
    panel._stop_playback()
    ok &= check("Fortschritt beim Rechnen", (getattr(panel, "seen_progress", 0) > 0) == respects,
                f"{panel.frames} Bilder in {seconds:.1f} s, höchster gespiegelter Wert {getattr(panel, 'seen_progress', 0)}")
    panel.reject()
    App.closeDocument(doc.Name)

    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1
