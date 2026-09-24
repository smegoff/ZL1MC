import math
from pathlib import Path
import tempfile
import unittest

import ezdxf
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from cam import (CamError, Drawing, Operation, Settings, build_job, closed_polygons,
                 compensated_radius, depth_passes, export_job, gcode, load_dxf,
                 plan_operation, pocket_region, svg_preview)


def rectangle(x0=0, y0=0, x1=20, y1=10):
    return [(x0,y0), (x1,y0), (x1,y1), (x0,y1), (x0,y0)]


def drawing(*paths):
    return Drawing({"0": list(paths) or [rectangle()]})


def parse_moves(text):
    """Independent parser for actual generated linear G-code (including rounding)."""
    state = {"X": None, "Y": None, "Z": None, "F": None}
    for line in text.splitlines():
        words = line.split()
        if not words or words[0] not in ("G0", "G1"):
            continue
        before = dict(state)
        changed = set()
        for word in words[1:]:
            state[word[0]] = float(word[1:])
            changed.add(word[0])
        yield words[0], before, dict(state), changed


class DepthAndValidationTests(unittest.TestCase):
    def test_uneven_final_pass(self):
        self.assertEqual(depth_passes(1, .3), [-.3, -.6, -.8999999999999999, -1])

    def test_single_shallow_pass(self):
        self.assertEqual(depth_passes(.1, .5), [-.1])

    def test_exact_division(self):
        self.assertEqual(len(depth_passes(.9, .3)), 3)
        self.assertAlmostEqual(depth_passes(.9, .3)[-1], -.9)

    def test_invalid_numbers(self):
        for field in ("depth", "stepdown", "tool_diameter", "feed", "plunge", "stepover"):
            for value in (0, -1, float("nan"), float("inf")):
                with self.subTest(field=field,value=value), self.assertRaises(CamError):
                    plan_operation(drawing(), Operation(**{field: value}))

    def test_excessive_stepover(self):
        with self.assertRaises(CamError):
            plan_operation(drawing(),Operation(stepover=51))

    def test_tab_validation(self):
        for kwargs in ({"tabs":1}, {"mode":"Outside profile","tabs":1.5},
                       {"mode":"Outside profile","tabs":2,"tab_height":2},
                       {"mode":"Outside profile","tabs":100,"tab_width":4}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CamError):
                plan_operation(drawing(),Operation(**kwargs))

    def test_no_operations(self):
        with self.assertRaises(CamError):
            build_job(drawing(),[])

    def test_missing_layer(self):
        with self.assertRaises(CamError):
            build_job(drawing(),[Operation(layer="absent")])

    def test_machine_settings(self):
        for settings in (Settings(safe_z=0), Settings(safe_z=float("nan")), Settings(spindle=0), Settings(spindle=-1)):
            with self.assertRaises(CamError):
                build_job(drawing(),[Operation()],settings)

    def test_tool_changes_rejected(self):
        with self.assertRaises(CamError):
            build_job(drawing(),[Operation(tool_diameter=2),Operation(tool_diameter=3)])


class GeometryTests(unittest.TestCase):
    def test_inside_outside_offsets(self):
        for mode, sign in (("Inside profile",1),("Outside profile",-1)):
            plan=plan_operation(drawing(),Operation(mode=mode,tool_diameter=2))
            bounds=LineString(plan.paths[0]).bounds
            radius=compensated_radius(2)
            self.assertAlmostEqual(bounds[0],sign*radius)
            self.assertAlmostEqual(bounds[2],20-sign*radius)

    def test_outside_profile_rejects_neighbour_gouging(self):
        with self.assertRaisesRegex(CamError, "too close"):
            plan_operation(drawing(rectangle(),rectangle(22,0,42,10)),
                           Operation(mode="Outside profile",tool_diameter=3))

    def test_outside_profiles_preserve_separated_parts(self):
        parts=[rectangle(),rectangle(26,0,46,10)]
        plan=plan_operation(drawing(*parts),Operation(mode="Outside profile",tool_diameter=3))
        self.assertEqual(len(plan.paths),2)
        for i,path in enumerate(plan.paths):
            footprint=LineString(path).buffer(1.5,quad_segs=64)
            self.assertLess(footprint.intersection(Polygon(parts[1-i])).area,1e-8)

    def test_open_path_only_engraves(self):
        d=drawing([(0,0),(10,0)])
        self.assertEqual(len(plan_operation(d,Operation()).paths),1)
        for mode in ("Inside profile","Outside profile","Pocket"):
            with self.assertRaises(CamError):
                plan_operation(d,Operation(mode=mode))

    def test_join_individual_lines(self):
        pts=rectangle()
        paths=[[a,b] for a,b in zip(pts,pts[1:])]
        self.assertEqual(len(closed_polygons(paths)),1)

    def test_gap_not_repaired(self):
        pts=rectangle()
        pts[-1]=(.01,0)
        with self.assertRaises(CamError):
            closed_polygons([pts])

    def test_self_intersection_rejected(self):
        with self.assertRaises(CamError):
            closed_polygons([[(0,0),(10,10),(0,10),(10,0),(0,0)]])

    def test_duplicate_rejected(self):
        with self.assertRaises(CamError):
            closed_polygons([rectangle(),rectangle()])

    def test_touching_and_crossing_rejected(self):
        for p in (rectangle(20,0,30,10),rectangle(10,5,30,15)):
            with self.assertRaises(CamError):
                closed_polygons([rectangle(),p])

    def test_small_pocket_rejected(self):
        with self.assertRaises(CamError):
            plan_operation(drawing(rectangle(0,0,2,2)),Operation(mode="Pocket",tool_diameter=3))

    def test_one_small_component_rejected(self):
        with self.assertRaises(CamError):
            plan_operation(drawing(rectangle(),rectangle(30,0,31,1)),Operation(mode="Pocket"))

    def test_nested_profiles_rejected(self):
        with self.assertRaises(CamError):
            plan_operation(drawing(rectangle(),rectangle(5,2,10,5)),Operation(mode="Outside profile"))

    def test_islands_parity(self):
        polys=closed_polygons([rectangle(0,0,40,40),rectangle(5,5,35,35),rectangle(10,10,30,30)])
        region=pocket_region(polys)
        self.assertAlmostEqual(region.area,1600-900+400)
        self.assertFalse(region.contains(Point(7,7)))
        self.assertTrue(region.contains(Point(20,20)))

    def test_pocket_swept_tool_avoids_island(self):
        shell=rectangle(0,0,40,30)
        island=rectangle(15,10,25,20)
        plan=plan_operation(drawing(shell,island),Operation(mode="Pocket",tool_diameter=3,stepover=40))
        region=Polygon(shell,[island])
        for path in plan.paths:
            sweep=LineString(path).buffer(1.5,quad_segs=64)
            self.assertLess(sweep.difference(region).area,1e-8)
        swept=unary_union([LineString(p).buffer(1.5,quad_segs=64) for p in plan.paths])
        self.assertGreater(swept.area/region.area,.99)

    def test_narrow_region_reported(self):
        plan=plan_operation(drawing(rectangle()),Operation(mode="Pocket",tool_diameter=3))
        self.assertTrue(any("uncleared" in w for w in plan.warnings))


class ExportTests(unittest.TestCase):
    def test_no_xy_rapid_below_clearance(self):
        job=build_job(drawing(),[Operation(mode="Pocket",depth=1.1,stepdown=.3)],Settings(safe_z=7))
        for code,before,after,changed in parse_moves(gcode(job)):
            if code=="G0" and ("X" in changed or "Y" in changed):
                self.assertEqual(before["Z"],7)
        self.assertEqual(job.moves[-1].z,7)

    def test_exact_exported_depth_no_overcut(self):
        job=build_job(drawing(),[Operation(depth=1,stepdown=.3)])
        zs=[after["Z"] for _,_,after,_ in parse_moves(gcode(job))]
        self.assertEqual(min(zs),-1)
        self.assertEqual(sorted(set(z for z in zs if z<0)),[-1,-.9,-.6,-.3])

    def test_tabs_hold_height_and_width(self):
        op=Operation(mode="Outside profile",tool_diameter=2,depth=2,stepdown=.5,tabs=2,tab_width=4,tab_height=.6)
        job=build_job(drawing(),[op])
        orange=[m for m in job.moves if m.tab and m.x is not None]
        self.assertTrue(orange)
        tab_lengths=[]
        current_length=0
        for code,before,after,changed in parse_moves(gcode(job)):
            if code=="G1" and "X" in changed and after["Z"] == -1.4:
                current_length+=math.dist((before["X"],before["Y"]),(after["X"],after["Y"]))
            elif current_length:
                tab_lengths.append(current_length)
                current_length=0
        self.assertEqual(len(tab_lengths),4)  # two tabs on last two passes
        for length in tab_lengths:
            self.assertAlmostEqual(length,6,places=3)  # 4 mm bridge + 2 mm cutter

    def test_exported_island_clearance_after_rounding(self):
        shell=rectangle(0,0,40,30)
        hole=rectangle(15,10,25,20)
        job=build_job(drawing(shell,hole),[Operation(mode="Pocket",tool_diameter=3,depth=.2)])
        region=Polygon(shell,[hole])
        for code,before,after,changed in parse_moves(gcode(job)):
            if code=="G1" and "X" in changed:
                sweep=LineString([(before["X"],before["Y"]),(after["X"],after["Y"])]).buffer(1.5,quad_segs=64)
                self.assertLess(sweep.difference(region).area,1e-8)

    def test_modal_setup_and_spindle_off(self):
        text=gcode(build_job(drawing(),[Operation()],Settings(spindle_on=False)))
        self.assertIn("G21\nG17\nG94\nG54\nG40\nG49",text)
        self.assertNotIn("M3",text)
        self.assertTrue(text.endswith("M5\nM2\n"))
        self.assertNotIn("G41",text)
        self.assertNotIn("G42",text)

    def test_layer_selection_and_order(self):
        d=Drawing({"a":[rectangle()],"b":[rectangle(30,0,50,10)]})
        job=build_job(d,[Operation(layer="b",depth=.3),Operation(layer="a",depth=.7)])
        xy=[m for m in job.moves if m.x is not None]
        self.assertEqual(xy[0].x,30)
        self.assertEqual(sorted(set(m.op for m in xy)),[0,1])
        self.assertEqual([p.operation.depth for p in job.plans],[.3,.7])

    def test_export_sidecars_and_no_dxf_overwrite(self):
        job=build_job(drawing(),[Operation()])
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/"part.gcode"
            export_job(job,target)
            self.assertTrue(target.with_suffix(".preview.svg").exists())
            self.assertTrue(target.with_suffix(".report.json").exists())
            with self.assertRaises(CamError):
                export_job(job,Path(temp)/"input.dxf")

    def test_untrusted_name_cannot_inject_gcode(self):
        job=build_job(drawing(),[Operation(name="bad)\nG0 Z-99\n(")])
        self.assertNotIn("Z-99",gcode(job))
        job.plans[0].operation.name="<script>test</script>"
        self.assertNotIn("<script>",svg_preview(job))


class ImportTests(unittest.TestCase):
    def load(self,doc,**kwargs):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"input.dxf"
            doc.saveas(path)
            return load_dxf(path,**kwargs)

    def doc(self):
        doc=ezdxf.new()
        doc.units=ezdxf.units.MM
        return doc

    def test_inch_conversion(self):
        doc=self.doc()
        doc.units=ezdxf.units.IN
        doc.modelspace().add_line((0,0),(1,0))
        self.assertAlmostEqual(self.load(doc).bounds[2],25.4)

    def test_unitless_requires_choice(self):
        doc=self.doc()
        doc.units=0
        doc.modelspace().add_line((0,0),(1,0))
        with self.assertRaises(CamError):
            self.load(doc)
        self.assertEqual(self.load(doc,source_units="mm").bounds[2],1)

    def test_scale_and_origin(self):
        doc=self.doc()
        doc.modelspace().add_lwpolyline(rectangle(10,20,30,40),close=True)
        self.assertEqual(self.load(doc,scale=2,origin="Lower left").bounds,(0,0,40,40))

    def test_nonplanar_rejected(self):
        doc=self.doc()
        doc.modelspace().add_line((0,0,0),(1,2,3))
        with self.assertRaises(CamError):
            self.load(doc)

    def test_nested_blocks_inherit_layer(self):
        doc=self.doc()
        inner=doc.blocks.new("inner")
        inner.add_lwpolyline(rectangle(),close=True)
        outer=doc.blocks.new("outer")
        outer.add_blockref("inner",(2,3))
        doc.modelspace().add_blockref("outer",(10,20),dxfattribs={"layer":"CUT"})
        result=self.load(doc)
        self.assertIn("CUT",result.layers)
        self.assertEqual(result.bounds,(12,23,32,33))

    def test_hatch_islands(self):
        doc=self.doc()
        hatch=doc.modelspace().add_hatch()
        hatch.paths.add_polyline_path(rectangle(0,0,40,40),is_closed=True,flags=1)
        hatch.paths.add_polyline_path(rectangle(10,10,20,20),is_closed=True,flags=0)
        result=self.load(doc)
        self.assertEqual(len(result.paths),2)
        region=pocket_region(closed_polygons(result.paths))
        self.assertAlmostEqual(region.area,1500)

    def test_curves_and_ignored_entities_reported(self):
        doc=self.doc()
        msp=doc.modelspace()
        msp.add_circle((0,0),5)
        msp.add_ellipse((20,0),major_axis=(5,0),ratio=.5)
        msp.add_spline(fit_points=[(0,10),(10,15),(20,10)])
        msp.add_text("not converted")
        result=self.load(doc)
        self.assertEqual(len(result.paths),3)
        self.assertTrue(any("TEXT (1)" in w for w in result.warnings))

    def test_arc_and_bulge(self):
        doc=self.doc()
        msp=doc.modelspace()
        msp.add_arc((0,0),5,0,90)
        msp.add_lwpolyline([(0,10,1),(10,10,0)],format="xyb")
        result=self.load(doc)
        self.assertEqual(len(result.paths),2)
        self.assertGreater(len(result.paths[1]),4)


if __name__ == "__main__":
    unittest.main()
