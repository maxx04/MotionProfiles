# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD command: open the motion profile task panel for the selected Motion, the selected joint,
or a new Motion in the active assembly."""
import os

import FreeCAD as App
import FreeCADGui as Gui

from . import motion_link

ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "icons",
                    "MotionProfiles.svg")
COMMAND = "MotionProfiles_EditProfile"


def _active_assembly():
    import UtilsAssembly

    return UtilsAssembly.activeAssembly()


def _is_motion(obj):
    return hasattr(obj, "MotionType") and hasattr(obj, "Formula") and hasattr(obj, "Joint")


class CommandEditProfile:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Bewegungsprofil",
            "ToolTip": "Gelenk über ein Profil antreiben: Weg, Geschwindigkeit oder Beschleunigung "
                       "über der Zeit (konstant, Rampe, Cosinus, zykloidisch, SCCA, Tabelle ...). "
                       "Erzeugt bzw. bearbeitet eine Motion der Simulation.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None and _active_assembly() is not None

    def Activated(self):
        from .taskpanel import MotionProfileTaskPanel

        asm = _active_assembly()
        motion = joint = None
        for obj in Gui.Selection.getSelection():
            if _is_motion(obj):
                motion = obj
                break
            if getattr(obj, "JointType", None) in motion_link.SUPPORTED_JOINTS:
                joint = obj
        Gui.Control.showDialog(MotionProfileTaskPanel(asm, motion=motion, joint=joint))


class _AssemblyManipulator:
    """Put the command right after "Simulation" in the Assembly toolbar and menu."""

    def modifyToolBars(self):
        # "toolItem" (hinter Simulation) greift bei der Assembly-Toolbar nicht - an die Toolbar
        # "Assembly" anhaengen, die "Simulation" enthaelt.
        return [{"append": COMMAND, "toolBar": "Assembly"}]

    def modifyMenuBar(self):
        return [{"append": COMMAND, "menuItem": "Assembly_CreateSimulation"}]


class _TaskWatcher:
    """Eintrag in der Aufgabenansicht der Assembly-Werkbank (wie dort "Simulation"): sichtbar bei
    aktiver Baugruppe mit antreibbarem Gelenk."""

    def __init__(self):
        self.commands = [COMMAND]
        self.title = "Bewegungsprofil"

    def shouldShow(self):
        asm = _active_assembly()
        if asm is None or asm.Document != App.ActiveDocument:
            return False
        return bool(motion_link.joint_instances(asm))


def _on_workbench_activated(name):
    # Die Assembly-Werkbank setzt ihre Watcher in Activated() neu; danach kommt dieses Signal.
    if name == "AssemblyWorkbench":
        Gui.Control.addTaskWatcher([_TaskWatcher()])


def register():
    Gui.addCommand(COMMAND, CommandEditProfile())
    if hasattr(Gui, "addWorkbenchManipulator"):
        Gui.addWorkbenchManipulator(_AssemblyManipulator())
    main_window = Gui.getMainWindow()
    if main_window is not None and hasattr(main_window, "workbenchActivated"):
        main_window.workbenchActivated.connect(_on_workbench_activated)
