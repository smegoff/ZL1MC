from __future__ import annotations
from collections import Counter
import math
import ezdxf
from ezdxf.path import make_path
from models import CamError, Drawing, number
from work_control import checkpoint

def load_dxf(filename, source_units="Auto", scale=1.0, tolerance=0.02,
             origin="Drawing origin", cancel=None, progress=None):
    scale = number(scale, "Scale", 0, True)
    tolerance = number(tolerance, "Curve tolerance", 0.001)
    if origin not in ("Drawing origin", "Lower left"):
        raise CamError("Unknown origin setting.")
    checkpoint(cancel, progress, "Reading DXF")
    doc = ezdxf.readfile(filename)
    checkpoint(cancel, progress, "Flattening drawing")
    if source_units == "Auto":
        code = doc.units
        if code == 0:
            raise CamError("This DXF has no units. Select mm or inch explicitly, then load again.")
        try:
            factor = ezdxf.units.conversion_factor(code, ezdxf.units.MM)
        except (ValueError, TypeError) as exc:
            raise CamError("Unsupported DXF units. Select the drawing's units explicitly.") from exc
    elif source_units in ("mm", "inch"):
        factor = 1.0 if source_units == "mm" else 25.4
    else:
        raise CamError("Source units must be Auto, mm, or inch.")
    factor *= scale
    layers = {}
    ignored = Counter()
    supported = {"LINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "LWPOLYLINE", "POLYLINE", "HATCH"}

    def expand(entities, inherited="0", depth=0):
        if depth > 24:
            raise CamError("Block nesting is too deep.")
        for entity in entities:
            checkpoint(cancel)
            layer = entity.dxf.get("layer", "0")
            if layer == "0":
                layer = inherited
            if entity.dxftype() == "INSERT":
                def skipped(e, reason):
                    raise CamError(f"Cannot expand block entity {e.dxftype()}: {reason}")
                if entity.attribs:
                    ignored["ATTRIB"] += len(entity.attribs)
                refs = entity.multi_insert() if entity.mcount > 1 else [entity]
                for ref in refs:
                    yield from expand(ref.virtual_entities(skipped_entity_callback=skipped), layer, depth + 1)
            else:
                yield entity, layer

    count = 0
    for entity, layer in expand(doc.modelspace()):
        checkpoint(cancel, progress, "Importing geometry", count, 100_000)
        kind = entity.dxftype()
        if kind not in supported:
            ignored[kind] += 1
            continue
        try:
            path = make_path(entity)
            subpaths = list(path.sub_paths()) if path.has_sub_paths else [path]
            for subpath in subpaths:
                verts = []
                for v in subpath.flattening(distance=tolerance / factor):
                    verts.append(v)
                    if len(verts) % 512 == 0:
                        checkpoint(cancel)
                    if count + len(verts) > 100_000:
                        raise CamError("Drawing exceeds 100,000 flattened vertices. Increase tolerance or simplify it.")
                if not verts:
                    raise CamError(f"Empty {kind} geometry on layer {layer}.")
                if any(not all(math.isfinite(c) for c in v) for v in verts):
                    raise CamError("The DXF contains non-finite coordinates.")
                # Elevation in a DXF is NOT interpreted as a machining depth.
                if any(abs(v.z * factor) > 1e-5 for v in verts):
                    raise CamError(f"{kind} on {layer} is not in the Z=0 plane. Flatten it in CAD first.")
                pts = []
                for v in verts:
                    pt = (v.x * factor, v.y * factor)
                    if not pts or math.dist(pts[-1], pt) > 1e-8:
                        pts.append(pt)
                if subpath.is_closed and len(pts) > 1:
                    if math.dist(pts[0], pts[-1]) <= 1e-5:
                        pts[-1] = pts[0]
                    else:
                        pts.append(pts[0])
                if len(pts) < 2:
                    raise CamError(f"Degenerate {kind} on layer {layer}.")
                count += len(pts)
                if count > 100_000:
                    raise CamError("Drawing exceeds 100,000 flattened vertices. Increase curve tolerance or simplify it.")
                layers.setdefault(layer, []).append(pts)
        except CamError:
            raise
        except Exception as exc:
            raise CamError(f"Cannot read {kind} on layer {layer}: {exc}") from exc
    if not layers:
        raise CamError("No supported drawing geometry found.")
    result = Drawing(layers, source=str(filename))
    if ignored:
        result.warnings.append("Ignored non-path entities: " + ", ".join(f"{k} ({v})" for k, v in sorted(ignored.items())))
    if origin == "Lower left":
        x0, y0, _, _ = result.bounds
        result.layers = {k: [[(x-x0, y-y0) for x, y in p] for p in paths] for k, paths in layers.items()}
    if max(abs(v) for v in result.bounds) > 1_000_000:
        raise CamError("Drawing coordinates exceed 1,000,000 mm. Check units, scale and origin.")
    return result
