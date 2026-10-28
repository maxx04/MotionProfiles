# SPDX-License-Identifier: LGPL-2.1-or-later
"""Task panel: choose joint, driven quantity and profile; live preview of position, velocity and
acceleration; OK writes the Motion (new or existing)."""
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import motion_link, profiles

QUANTITY_LABELS = {"position": "Weg", "velocity": "Geschwindigkeit", "acceleration": "Beschleunigung"}
PREVIEW_POINTS = 400


def _make_canvas(figure):
    """Matplotlib-Zeichenflaeche, die ein von FreeCAD schon geloeschtes Widget vertraegt: schliesst
    die Aufgabenansicht, loescht Qt das Widget, waehrend Matplotlib noch ein verzoegertes
    Neuzeichnen bzw. den Anzeige-Handler offen hat ("Internal C++ object already deleted")."""
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

    class Canvas(FigureCanvasQTAgg):
        def showEvent(self, event):
            try:
                super().showEvent(event)
            except RuntimeError:
                pass

        def _draw_idle(self):
            try:
                super()._draw_idle()
            except RuntimeError:
                pass

    return Canvas(figure)


def _save_placements(assembly):
    import UtilsAssembly

    return UtilsAssembly.saveAssemblyPartsPlacements(assembly)


def _restore_placements(assembly, placements):
    import UtilsAssembly

    if placements:
        UtilsAssembly.restoreAssemblyPartsPlacements(assembly, placements)


def _spin(value, decimals=4, minimum=-1e9, maximum=1e9, suffix=""):
    box = QtWidgets.QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setValue(value)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)
    return box


class MotionProfileTaskPanel:
    """motion: existing Motion to edit, or None to create one (joint/prefix preselected if given)."""

    def __init__(self, assembly, motion=None, joint=None, prefix=""):
        self.assembly = assembly
        # explizit uebergebene Motion: nur diese bearbeiten. Sonst die Motion des gewaehlten
        # Gelenks (eine schon vorhandene - nie eine zweite am selben Gelenk anlegen).
        self.explicit = motion is not None
        self.instances = motion_link.joint_instances(assembly)
        if motion is None and joint is not None:
            motion = motion_link.find_motion(assembly, joint, prefix)
        self.motion = motion
        self.spec = (motion_link.read_spec(motion) if motion else None) or motion_link.default_spec()
        if motion is not None:
            joint, prefix = motion_link.motion_joint(motion)
        self.initial_placements = _save_placements(assembly)
        self.timer = None
        # erst bei OK anlegen - Abbrechen hinterlaesst keine leere Simulation
        self.sim = motion_link.find_simulation(assembly)
        self.param_boxes = {}
        self.closed = False
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Bewegungsprofil")
        self._build()
        self._select_joint(joint, prefix)
        if motion is not None:
            self._set_combo(self.type_combo, motion.MotionType)
        self._load_spec()
        self.update_preview()

    # ------------------------------------------------------------------ UI
    def _build(self):
        layout = QtWidgets.QVBoxLayout(self.form)
        top = QtWidgets.QFormLayout()
        self.joint_combo = QtWidgets.QComboBox()
        for joint, prefix in self.instances:
            self.joint_combo.addItem(motion_link.joint_label(joint, prefix), (joint, prefix))
        self.type_combo = QtWidgets.QComboBox()
        self.quantity_combo = QtWidgets.QComboBox()
        for key in profiles.QUANTITIES:
            self.quantity_combo.addItem(QUANTITY_LABELS[key], key)
        self.profile_combo = QtWidgets.QComboBox()
        for key, definition in profiles.PROFILES.items():
            self.profile_combo.addItem(definition.label, key)
        self.profile_combo.addItem("Tabelle", "table")
        self.formula_label = QtWidgets.QLabel()
        self.formula_label.setWordWrap(True)
        top.addRow("Gelenk", self.joint_combo)
        top.addRow("Bewegungsart", self.type_combo)
        top.addRow("Größe", self.quantity_combo)
        top.addRow("Profil", self.profile_combo)
        top.addRow("", self.formula_label)
        layout.addLayout(top)
        self.target_label = QtWidgets.QLabel()
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)

        self.params_box = QtWidgets.QGroupBox("Parameter")
        self.params_layout = QtWidgets.QFormLayout(self.params_box)
        layout.addWidget(self.params_box)

        self.table_box = QtWidgets.QGroupBox("Tabelle (Zeit, Wert)")
        table_layout = QtWidgets.QVBoxLayout(self.table_box)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["t [s]", "Wert"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(160)
        buttons = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Zeile +")
        remove = QtWidgets.QPushButton("Zeile −")
        self.degree_combo = QtWidgets.QComboBox()
        self.degree_combo.addItem("kubisch", 3)
        self.degree_combo.addItem("linear", 1)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addWidget(self.degree_combo)
        table_layout.addWidget(self.table)
        table_layout.addLayout(buttons)
        layout.addWidget(self.table_box)
        add.clicked.connect(self._add_row)
        remove.clicked.connect(self._remove_row)

        extra = QtWidgets.QFormLayout()
        self.v0_box = _spin(0.0)
        extra.addRow("Anfangsgeschwindigkeit", self.v0_box)
        start, end, step = ((self.sim.aTimeStart.Value, self.sim.bTimeEnd.Value, self.sim.cTimeStepOutput.Value)
                            if self.sim else (0.0, 1.0, 0.01))  # Vorgaben einer neuen Simulation
        self.t_start = _spin(start, 3, 0.0, 1e6, " s")
        self.t_end = _spin(end, 3, 0.0, 1e6, " s")
        self.t_step = _spin(step, 4, 1e-4, 1e3, " s")
        extra.addRow("Simulation Start", self.t_start)
        extra.addRow("Simulation Ende", self.t_end)
        extra.addRow("Simulation Schritt", self.t_step)
        layout.addLayout(extra)

        self.message = QtWidgets.QLabel()
        self.message.setStyleSheet("color: #c0392b")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        hint = QtWidgets.QLabel("Hinweis: Die Simulation beachtet Gelenkgrenzen nicht. Das Profil "
                                "wird zur Stellung beim Start addiert (initialValue).")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.play_button = QtWidgets.QPushButton("Übernehmen, simulieren und abspielen")
        self.play_button.clicked.connect(self.play)
        layout.addWidget(self.play_button)

        self.canvas = None
        try:
            from matplotlib.figure import Figure

            self.figure = Figure(figsize=(4, 5), tight_layout=True)
            self.axes = [self.figure.add_subplot(3, 1, i + 1) for i in range(3)]
            self.canvas = _make_canvas(self.figure)
            self.canvas.setMinimumHeight(360)
            layout.addWidget(self.canvas)
        except ImportError:
            layout.addWidget(QtWidgets.QLabel("Vorschau nicht verfügbar (matplotlib fehlt)."))

        self.joint_combo.currentIndexChanged.connect(self._joint_changed)
        for widget in (self.type_combo, self.quantity_combo, self.degree_combo):
            widget.currentIndexChanged.connect(self.update_preview)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.table.itemChanged.connect(self.update_preview)
        for box in (self.v0_box, self.t_start, self.t_end, self.t_step):
            box.valueChanged.connect(self.update_preview)

    def _set_combo(self, combo, data):
        index = combo.findData(data)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _select_joint(self, joint, prefix):
        for i in range(self.joint_combo.count()):
            j, p = self.joint_combo.itemData(i)
            if j == joint and (p == prefix or not prefix):
                self.joint_combo.setCurrentIndex(i)
                break
        self._joint_changed()

    def _joint_changed(self, *_):
        data = self.joint_combo.currentData()
        if data and not self.explicit and hasattr(self, "spec"):
            target = motion_link.find_motion(self.assembly, data[0], data[1])
            if target is not self.motion:
                self.motion = target
                stored = motion_link.read_spec(target) if target else None
                if stored and hasattr(self, "t_step"):
                    self.spec = stored
                    self._load_spec()
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        if data:
            for kind in motion_link.motion_types_for(data[0]):
                self.type_combo.addItem({"Angular": "Drehung", "Linear": "Verschiebung"}[kind], kind)
        if self.motion is not None and self.motion.MotionType in [self.type_combo.itemData(i) for i in range(self.type_combo.count())]:
            self._set_combo(self.type_combo, self.motion.MotionType)
        self.type_combo.blockSignals(False)
        self._update_target_label()
        self.update_preview()

    def _conflicting_motion(self):
        """Bei explizit bearbeiteter Motion: andere Motion am jetzt gewaehlten Gelenk."""
        data = self.joint_combo.currentData()
        if not data or not self.explicit:
            return None
        return motion_link.find_motion(self.assembly, data[0], data[1], exclude=self.motion)

    def _update_target_label(self):
        if not hasattr(self, "target_label"):
            return
        other = self._conflicting_motion()
        if other is not None:
            text = (f"Achtung: dieses Gelenk treibt schon die Motion „{other.Label}“ an - zwei "
                    "Antriebe am selben Gelenk widersprechen sich. Diese bearbeiten oder löschen.")
        elif self.motion is None:
            text = "Legt eine neue Motion an."
        elif motion_link.has_profile(self.motion):
            text = f"Bearbeitet die vorhandene Motion „{self.motion.Label}“."
        else:
            text = (f"Bearbeitet die vorhandene Motion „{self.motion.Label}“ - ihre Formel "
                    f"„{self.motion.Formula}“ wird durch das Profil ersetzt.")
        self.target_label.setText(text)

    def _load_spec(self):
        self._set_combo(self.quantity_combo, self.spec["quantity"])
        self._set_combo(self.profile_combo, self.spec["profile"])
        self._set_combo(self.degree_combo, self.spec.get("degree", 3))
        self.v0_box.setValue(self.spec.get("v0", 0.0))
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for t, v in self.spec.get("table", []):
            self._add_row(values=(t, v))
        self.table.blockSignals(False)
        self._profile_changed()

    def _profile_changed(self, *_):
        key = self.profile_combo.currentData()
        while self.params_layout.rowCount():
            self.params_layout.removeRow(0)
        self.param_boxes = {}
        if key != "table":
            definition = profiles.PROFILES[key]
            self.formula_label.setText(f"f(t) = {definition.formula_text}")
            for p in definition.params:
                value = self.spec.get("params", {}).get(p.key, p.default) if self.spec["profile"] == key else p.default
                suffix = {"time": " s", "angle": " °"}.get(p.kind, "")
                box = _spin(value, suffix=suffix)
                box.valueChanged.connect(self.update_preview)
                self.params_layout.addRow(p.label, box)
                self.param_boxes[p.key] = box
        else:
            self.formula_label.setText("Kurve durch die Tabellenpunkte")
        self.params_box.setVisible(key != "table")
        self.table_box.setVisible(key == "table")
        self.update_preview()

    def _add_row(self, *_, values=None):
        row = self.table.rowCount()
        if values is None:
            last = [float(self.table.item(row - 1, c).text()) for c in (0, 1)] if row else [0.0, 0.0]
            values = (last[0] + 1.0, last[1])
        self.table.insertRow(row)
        for col, value in enumerate(values):
            self.table.setItem(row, col, QtWidgets.QTableWidgetItem(f"{value:g}"))
        self.update_preview()

    def _remove_row(self):
        if self.table.rowCount() > 2:
            self.table.removeRow(self.table.rowCount() - 1)
            self.update_preview()

    # ------------------------------------------------------------------ data
    def current_spec(self):
        table = []
        for row in range(self.table.rowCount()):
            items = [self.table.item(row, c) for c in (0, 1)]
            table.append([float(i.text().replace(",", ".")) if i and i.text().strip() else 0.0 for i in items])
        return {
            "quantity": self.quantity_combo.currentData(),
            "profile": self.profile_combo.currentData(),
            "params": {k: box.value() for k, box in self.param_boxes.items()},
            "table": table,
            "degree": self.degree_combo.currentData(),
            "v0": self.v0_box.value(),
        }

    def angular(self):
        return self.type_combo.currentData() == "Angular"

    def update_preview(self, *_):
        if not hasattr(self, "t_step") or self.closed:
            return
        self.v0_box.setEnabled(self.quantity_combo.currentData() == "acceleration")
        base = "°" if self.angular() else "mm"
        unit = {"position": base, "velocity": base + "/s", "acceleration": base + "/s²"}[self.quantity_combo.currentData()]
        self.table.setHorizontalHeaderLabels(["t [s]", f"Wert [{unit}]"])
        self.v0_box.setSuffix(f" {base}/s")
        try:
            pos = motion_link.position_curve(self.current_spec(), self.angular())
            self.message.setText("")
        except (ValueError, KeyError) as exc:
            self.message.setText(str(exc))
            return None
        if self.canvas is None:
            return pos
        t0, t1 = self.t_start.value(), max(self.t_end.value(), self.t_start.value() + 1e-6)
        ts = [t0 + (t1 - t0) * i / PREVIEW_POINTS for i in range(PREVIEW_POINTS + 1)]
        back = 1.0 / profiles.unit_factor(self.angular())
        unit = "°" if self.angular() else "mm"
        labels = (f"Weg [{unit}]", f"Geschw. [{unit}/s]", f"Beschl. [{unit}/s²]")
        for order, ax in enumerate(self.axes):
            ax.clear()
            ax.plot(ts, [back * pos.value(t, order) for t in ts], linewidth=1.2)
            ax.set_ylabel(labels[order], fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.tick_params(labelsize=7)
        self.axes[-1].set_xlabel("t [s]", fontsize=8)
        self.canvas.draw_idle()
        return pos

    # ------------------------------------------------------------------ speichern, abspielen
    def save(self):
        """Motion (neu oder vorhanden) und Simulationszeiten schreiben. False bei Fehler."""
        if self.update_preview() is None and self.message.text():
            return False
        data = self.joint_combo.currentData()
        if not data:
            self.message.setText("Kein antreibbares Gelenk (Drehung, Schieben, Zylinder) gefunden.")
            return False
        other = self._conflicting_motion()
        if other is not None:
            self.message.setText(f"Das Gelenk treibt schon die Motion „{other.Label}“ an.")
            return False
        joint, prefix = data
        spec = self.current_spec()
        doc = self.assembly.Document
        doc.openTransaction("Bewegungsprofil")
        if self.sim is None:
            self.sim = motion_link.get_or_create_simulation(self.assembly)
        self.sim.aTimeStart = self.t_start.value()
        self.sim.bTimeEnd = self.t_end.value()
        self.sim.cTimeStepOutput = self.t_step.value()
        if self.motion is None:
            self.motion = motion_link.create_motion(self.assembly, self.sim, joint, prefix,
                                                    self.type_combo.currentData(), spec)
        else:
            self.motion.MotionType = self.type_combo.currentData()
            self.motion.Joint = (joint, [prefix]) if prefix else joint
            motion_link.write_spec(self.motion, spec)
        doc.commitTransaction()
        doc.recompute()
        self._update_target_label()
        return True

    def play(self):
        """Speichern, Simulation rechnen und einmal im 3D-Fenster abspielen (erneut: Stopp)."""
        if self.timer is not None and self.timer.isActive():
            self._stop_playback()
            return
        if not self.save():
            return
        rc = self.assembly.generateSimulation(self.sim)
        self.frames = self.assembly.numberOfFrames() if rc == 0 else 0
        if self.frames < 2:
            self.message.setText(f"Simulation fehlgeschlagen (rc={rc}) - siehe Ausgabefenster.")
            return
        self.message.setText("")
        fps = max(1, int(getattr(self.sim, "jFramesPerSecond", 30) or 30))
        self.play_start = time.time()
        self.play_fps = fps
        self.timer = QtCore.QTimer()
        self.timer.setInterval(int(1000 / fps))
        self.timer.timeout.connect(self._next_frame)
        self.play_button.setText("Stopp")
        self.timer.start()

    def _next_frame(self):
        frame = 1 + int((time.time() - self.play_start) * self.play_fps)
        if frame >= self.frames:
            self.assembly.updateForFrame(self.frames - 1)
            self._stop_playback()
            return
        self.assembly.updateForFrame(frame)

    def _stop_playback(self):
        if self.timer is not None:
            self.timer.stop()
        if hasattr(self, "play_button"):
            self.play_button.setText("Übernehmen, simulieren und abspielen")

    def _finish(self):
        """Abspielen beenden, Teile wie beim Oeffnen (wie der Simulationsdialog), schliessen."""
        self._stop_playback()
        _restore_placements(self.assembly, self.initial_placements)
        self.closed = True
        Gui.Control.closeDialog()

    # ------------------------------------------------------------------ task dialog
    def accept(self):
        if not self.save():
            return False
        self._finish()
        return True

    def reject(self):
        self._finish()
        return True
