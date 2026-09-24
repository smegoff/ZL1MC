import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cam import CamError, Drawing, Operation, Settings, build_job, gcode, plan_operation, load_dxf
from persistence import export_job, export_paths, read_config, save_config, recover_export, transaction_dir
from preview_widget import prepare_preview
from tabs import contour_key, tab_centres
from work_control import Cancelled
from test_cam import drawing, rectangle, parse_moves


class SetupTests(unittest.TestCase):
    def job(self,op=None,**changes):
        return build_job(drawing(),[op or Operation()],Settings(check_setup=True,**changes))

    def test_valid_setup(self):self.assertTrue(self.job().settings.check_setup)

    def test_cutter_footprint_exceeds_x(self):
        with self.assertRaisesRegex(CamError,"footprint"):self.job(x_max=20)

    def test_depth_exceeds_stock(self):
        with self.assertRaisesRegex(CamError,"stock thickness"):self.job(Operation(depth=4))

    def test_spoilboard_allowance(self):self.job(Operation(depth=3.1))

    def test_safe_z_below_fixture(self):
        with self.assertRaisesRegex(CamError,"fixture"):self.job(fixture_height=6)

    def test_z_travel_limits(self):
        with self.assertRaisesRegex(CamError,"Z minimum"):self.job(z_min=-.5)
        with self.assertRaisesRegex(CamError,"Safe Z"):self.job(z_max=4)

    def test_stickout(self):
        with self.assertRaisesRegex(CamError,"stick-out"):self.job(tool_stickout=.8)

    def test_tabs_must_retain_stock(self):
        with self.assertRaisesRegex(CamError,"no material"):
            self.job(Operation(mode="Outside profile",depth=3.2,tabs=2,tab_height=.1))

    def test_checks_disabled_are_reported(self):
        job=build_job(drawing(),[Operation()])
        self.assertTrue(any("disabled" in w for w in job.warnings))

    def test_spindle_delay(self):
        self.assertIn("G4 P4.500",gcode(self.job(spindle_delay=4.5)))


class TabPreviewTests(unittest.TestCase):
    def test_custom_tab_crossing_seam_has_no_deep_entry(self):
        op=Operation(mode="Outside profile",tool_diameter=2,depth=2,stepdown=2,tabs=1,tab_height=.5)
        plan=plan_operation(drawing(),op)
        op.tab_positions={contour_key(plan.paths[0]):[0.0]}
        job=build_job(drawing(),[op])
        plunges=[after["Z"] for code,before,after,changed in parse_moves(gcode(job)) if code=="G1" and changed=={"Z","F"}]
        self.assertEqual(plunges[0],-1.5)
        self.assertIn(-2,plunges)
        self.assertEqual(plunges[-1],-1.5)

    def test_overlapping_tabs_rejected(self):
        op=Operation(mode="Outside profile",tabs=2)
        plan=plan_operation(drawing(),op)
        op.tab_positions={contour_key(plan.paths[0]):[.2,.21]}
        with self.assertRaisesRegex(CamError,"overlap"):build_job(drawing(),[op])

    def test_changed_geometry_rejects_old_tabs(self):
        op=Operation(mode="Outside profile",tabs=1)
        plan=plan_operation(drawing(),op)
        op.tab_positions={contour_key(plan.paths[0]):[.2]}
        with self.assertRaisesRegex(CamError,"changed contours"):
            build_job(drawing(rectangle(0,0,30,10)),[op])

    def test_preview_has_depth_and_vertical_motion(self):
        data=prepare_preview(build_job(drawing(),[Operation(depth=1,stepdown=.5)]))
        self.assertEqual(data.levels,[-.5,-1])
        self.assertTrue(any(s[0]==s[3] and s[1]==s[4] and s[2]!=s[5] for s in data.segments))

    def test_uncleared_boundaries_available(self):
        plan=plan_operation(drawing(),Operation(mode="Pocket"))
        self.assertTrue(plan.remaining_paths)


class CancellationTests(unittest.TestCase):
    def test_import_cancelled(self):
        with self.assertRaises(Cancelled):load_dxf("not-opened.dxf",cancel=lambda:True)

    def test_build_cancelled(self):
        with self.assertRaises(Cancelled):build_job(drawing(),[Operation()],cancel=lambda:True)

    def test_cancel_inside_pocket_loop(self):
        event=threading.Event()
        def progress(message,*_):
            if message=="Clearing pocket":event.set()
        with self.assertRaises(Cancelled):
            build_job(drawing(),[Operation(mode="Pocket")],cancel=event.is_set,progress=progress)

    def test_cancel_before_export_preserves_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"part.gcode";path.write_text("old")
            with self.assertRaises(Cancelled):export_job(build_job(drawing(),[Operation()]),path,cancel=lambda:True)
            self.assertEqual(path.read_text(),"old")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/"part.gcode"
        self.job=build_job(drawing(),[Operation()])

    def tearDown(self):self.temp.cleanup()

    def original_files(self):
        for i,path in enumerate(export_paths(self.path)):path.write_text(f"original-{i}")

    def assert_originals(self):
        for i,path in enumerate(export_paths(self.path)):self.assertEqual(path.read_text(),f"original-{i}")

    def test_render_failure_changes_no_files(self):
        self.original_files()
        with patch("persistence.svg_preview",side_effect=RuntimeError("render failed")),self.assertRaises(RuntimeError):
            export_job(self.job,self.path)
        self.assert_originals()

    def test_mid_commit_failure_restores_all_files(self):
        self.original_files();real=os.replace
        def fail(source,target):
            if Path(source).name=="stage1":raise OSError("disk failure")
            return real(source,target)
        with patch("persistence.os.replace",side_effect=fail),self.assertRaises(OSError):export_job(self.job,self.path)
        self.assert_originals();self.assertFalse(transaction_dir(self.path).exists())

    def test_new_targets_removed_after_failure(self):
        real=os.replace
        def fail(source,target):
            if Path(source).name=="stage1":raise OSError("disk failure")
            return real(source,target)
        with patch("persistence.os.replace",side_effect=fail),self.assertRaises(OSError):export_job(self.job,self.path)
        self.assertTrue(all(not p.exists() for p in export_paths(self.path)))

    def test_interrupted_export_can_be_recovered(self):
        self.original_files();real=os.replace
        def interrupt(source,target):
            if Path(source).name=="stage1":raise KeyboardInterrupt()
            return real(source,target)
        with patch("persistence.os.replace",side_effect=interrupt),self.assertRaises(KeyboardInterrupt):export_job(self.job,self.path)
        self.assertTrue(transaction_dir(self.path).exists())
        self.assertTrue(recover_export(self.path));self.assert_originals()
        self.assertFalse(recover_export(self.path))

    def test_cancel_during_commit_rolls_back(self):
        self.original_files();event=threading.Event()
        def progress(message,current,total):
            if message=="Installing export files" and current==0:event.set()
        with self.assertRaises(Cancelled):export_job(self.job,self.path,event.is_set,progress)
        self.assert_originals()

    def test_report_checksum_matches_program(self):
        export_job(self.job,self.path)
        report=json.loads(self.path.with_suffix(".report.json").read_text())
        self.assertEqual(report["program_sha256"],hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_versioned_job_relative_drawing_and_fingerprint(self):
        source=self.root/"drawing.dxf";source.write_text("example")
        filename=self.root/"job.json"
        save_config(filename,{},Settings(),[Operation()],source,0)
        data=json.loads(filename.read_text());self.assertEqual(data["schema_version"],1)
        self.assertEqual(data["drawing"]["path"],"drawing.dxf")
        loaded=read_config(filename)
        self.assertEqual(loaded.drawing,str(source.resolve()))
        self.assertEqual(loaded.selected_operation,0)

    def test_legacy_job_loads(self):
        filename=self.root/"job.json";filename.write_text(json.dumps({"operations":[{}]}))
        self.assertEqual(len(read_config(filename).operations),1)

    def test_schema_and_import_rejected(self):
        filename=self.root/"job.json"
        for data in ({"schema_version":99},{"import":{"scale":float("nan")},"operations":[{}]}, {"settings":{"safe_z":-1},"operations":[{}]}):
            filename.write_text(json.dumps(data))
            with self.assertRaises(CamError):read_config(filename)


if __name__=="__main__":unittest.main()
