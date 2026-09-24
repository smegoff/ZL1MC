"""Real Tk smoke checks; no CNC connection and no modal dialogs during tests."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
import os
from unittest.mock import patch

from cam import Operation
from dxf_to_gcode_gui import App

ROOT=Path(__file__).resolve().parents[1]


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            root=tk.Tk()
            root.destroy()
        except tk.TclError as exc:
            if os.environ.get("REQUIRE_TK_TESTS") == "1":
                raise
            raise unittest.SkipTest(f"Tk display unavailable: {exc}")

    def setUp(self):
        self.app=App()
        self.app.update()
        self.errors=[]
        self.app.report_callback_exception=lambda *args:self.errors.append(args)
        self.patches=[patch("dxf_to_gcode_gui.messagebox.showerror",side_effect=lambda *a: self.errors.append(a)),
                      patch("dxf_to_gcode_gui.messagebox.showwarning"),
                      patch("dxf_to_gcode_gui.messagebox.showinfo")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.app.destroy()
        self.assertEqual(self.errors,[])

    def load_and_build(self):
        self.app.dxf.set(str(ROOT/"examples"/"stepped_sign.dxf"))
        self.app.load()
        self.wait_task()
        config=json.loads((ROOT/"examples"/"stepped_sign.job.json").read_text())
        self.app.operations=[Operation(**op) for op in config["operations"]]
        self.app.refresh_tree()
        self.app.build()
        self.wait_task()
        self.assertIsNotNone(self.app.job)

    def wait_task(self):
        deadline=time.monotonic()+10
        while self.app.busy and time.monotonic()<deadline:
            self.app.update()
            time.sleep(.01)
        self.assertFalse(self.app.busy)
        self.assertEqual(self.errors,[])
        self.app.update()

    def test_example_build_preview_and_export(self):
        self.load_and_build()
        self.assertTrue(self.app.canvas.find_all())
        self.assertEqual(str(self.app.export_button["state"]),"normal")
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/"test.gcode"
            with patch("dxf_to_gcode_gui.filedialog.asksaveasfilename",return_value=str(output)), patch("dxf_to_gcode_gui.messagebox.askokcancel",return_value=True):
                self.app.export()
                self.wait_task()
            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".preview.svg").exists())

    def test_setting_change_invalidates_export(self):
        self.load_and_build()
        self.app.safe_z.set("8")
        self.assertIsNone(self.app.job)
        self.assertEqual(str(self.app.export_button["state"]),"disabled")

    def test_operation_add_edit_reorder(self):
        self.app.add()
        self.app.update()
        self.app.fields["depth"].set("2")
        self.app.update_selected()
        self.assertEqual(self.app.operations[0].depth,2)
        self.app.fields["name"].set("second")
        self.app.add()
        self.app.reorder(-1)
        self.assertEqual(self.app.operations[0].name,"second")
        self.app.remove()
        self.assertEqual(len(self.app.operations),1)

    def test_controls_fit_default_window(self):
        for widget in (self.app.preview_button,self.app.export_button,self.app.tree,self.app.canvas):
            self.assertGreater(widget.winfo_width(),40)
            self.assertGreater(widget.winfo_height(),10)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.app.winfo_rooty()+self.app.winfo_height())

    def test_dirty_editor_disables_export_and_discard_restores_it(self):
        self.load_and_build()
        self.app.set_editor(0)
        self.app.fields["depth"].set("0.4")
        self.assertTrue(self.app.editor_is_dirty())
        self.assertEqual(str(self.app.export_button["state"]),"disabled")
        self.app.discard_edits()
        self.assertFalse(self.app.editor_is_dirty())
        self.assertEqual(str(self.app.export_button["state"]),"normal")

    def test_pending_edits_apply_before_export(self):
        self.load_and_build();self.app.set_editor(0)
        self.app.fields["depth"].set("0.4")
        with patch("dxf_to_gcode_gui.messagebox.askyesnocancel",return_value=True),patch("dxf_to_gcode_gui.filedialog.asksaveasfilename") as save:
            self.app.export()
            save.assert_not_called()
        self.assertEqual(self.app.operations[0].depth,.4)
        self.assertIsNone(self.app.job)

    def test_cancel_selection_change_preserves_edits(self):
        self.app.add();self.app.add();self.app.tree.selection_set("0");self.app.update()
        self.app.fields["depth"].set("0.9")
        with patch("dxf_to_gcode_gui.messagebox.askyesnocancel",return_value=None):
            self.app.tree.selection_set("1");self.app.update()
        self.assertEqual(self.app.active_index,0)
        self.assertEqual(self.app.fields["depth"].get(),"0.9")

    def test_conditional_fields(self):
        self.app.fields["mode"].set("Pocket")
        self.assertEqual(str(self.app.field_widgets["stepover"]["state"]),"normal")
        self.assertEqual(str(self.app.field_widgets["tabs"]["state"]),"disabled")
        self.app.fields["mode"].set("Outside profile")
        self.assertEqual(str(self.app.field_widgets["stepover"]["state"]),"disabled")
        self.assertEqual(str(self.app.field_widgets["tabs"]["state"]),"normal")

    def test_duplicate_undo_redo(self):
        self.app.add();self.app.duplicate()
        self.assertEqual(len(self.app.operations),2)
        self.app.undo();self.assertEqual(len(self.app.operations),1)
        self.app.undo(True);self.assertEqual(len(self.app.operations),2)

    def test_preview_depth_filter_and_side_view(self):
        self.load_and_build()
        self.app.preview.pass_index.set(1)
        segments=self.app.preview.filtered_segments()
        self.assertTrue(all(s[9]==self.app.preview.data.levels[0] for s in segments))
        self.app.preview.view.set("Side XZ");self.app.preview.draw()
        self.assertTrue(self.app.canvas.find_all())

    def test_drag_tab_updates_saved_operation(self):
        self.load_and_build()
        from tabs import contour_key,tab_centres
        plan=self.app.job.plans[2];path=plan.paths[0]
        centre=tab_centres(path,plan.operation)[0]
        self.app.move_tab(2,0,0,centre+.01);self.wait_task()
        self.assertAlmostEqual(self.app.operations[2].tab_positions[contour_key(path)][0],centre+.01)

    def test_invalid_job_does_not_change_current_operations(self):
        self.app.add();before=asdict(self.app.operations[0])
        with tempfile.TemporaryDirectory() as tmp:
            filename=Path(tmp)/"bad.json"
            filename.write_text(json.dumps({"import":{"scale":-1},"operations":[{"depth":5}]}))
            with patch("dxf_to_gcode_gui.filedialog.askopenfilename",return_value=str(filename)):
                self.app.open_config()
        self.assertEqual(asdict(self.app.operations[0]),before)
        self.assertEqual(len(self.errors),1);self.errors.clear()

    def test_small_window_controls_remain_accessible(self):
        self.app.geometry("1000x700");self.app.update()
        self.assertLessEqual(self.app.export_button.winfo_rooty()+self.app.export_button.winfo_height(),self.app.winfo_rooty()+700)
        self.assertGreater(self.app.canvas.winfo_height(),150)


if __name__=="__main__":
    unittest.main()
