"""Regenerate the demonstration drawing and JSON job (never sends to a machine)."""
from pathlib import Path
import json
import hashlib
import ezdxf

folder=Path(__file__).resolve().parent
doc=ezdxf.new("R2010")
doc.units=ezdxf.units.MM
for name in ("OUTLINE", "POCKET", "ENGRAVE"):
    doc.layers.new(name)
msp=doc.modelspace()
msp.add_lwpolyline([(0,0),(60,0),(60,40),(0,40)],close=True,dxfattribs={"layer":"OUTLINE"})
msp.add_lwpolyline([(8,8),(52,8),(52,32),(8,32)],close=True,dxfattribs={"layer":"POCKET"})
msp.add_lwpolyline([(24,14),(36,14),(36,26),(24,26)],close=True,dxfattribs={"layer":"POCKET"})
msp.add_lwpolyline([(27,18),(30,22),(33,18)],dxfattribs={"layer":"ENGRAVE"})
doc.saveas(folder/"stepped_sign.dxf")
config={
    "schema_version":1,
    "drawing":{"path":"stepped_sign.dxf","sha256":hashlib.sha256((folder/"stepped_sign.dxf").read_bytes()).hexdigest()},
    "import":{"source_units":"Auto","scale":1,"tolerance":0.02,"origin":"Drawing origin"},
    "settings":{"safe_z":5,"spindle":10000,"spindle_on":True,"check_setup":True,"stock_thickness":2},
    "operations":[
        {"name":"Mark island","layer":"ENGRAVE","mode":"Engrave","depth":0.2,"stepdown":0.2,"tool_diameter":3.175},
        {"name":"Pocket around island","layer":"POCKET","mode":"Pocket","depth":1,"stepdown":0.25,"tool_diameter":3.175,"stepover":40},
        {"name":"Outside with tabs","layer":"OUTLINE","mode":"Outside profile","depth":2,"stepdown":0.5,"tool_diameter":3.175,"tabs":4,"tab_width":4,"tab_height":0.6}
    ]
}
(folder/"stepped_sign.job.json").write_text(json.dumps(config,indent=2),encoding="utf-8")
print("Created example DXF and job settings.")
