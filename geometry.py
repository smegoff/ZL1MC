from __future__ import annotations
import math
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import linemerge, unary_union
from shapely.validation import explain_validity
from models import CamError, PlannedOperation
from work_control import checkpoint
from tabs import contour_key, tab_intervals

QUADS = 64

def closed_polygons(paths, cancel=None):
    """Join exact DXF line endpoints; reject gaps, crossings and duplicate contours.

    Endpoint rounding is only 0.000001 mm, not a general geometry repair.
    """
    lines = []
    for path in paths:
        checkpoint(cancel)
        pts = list(path)
        pts[0] = tuple(round(v, 6) for v in pts[0])
        pts[-1] = tuple(round(v, 6) for v in pts[-1])
        line = LineString(pts)
        if line.length <= 1e-6:
            raise CamError("Zero-length contour.")
        lines.append(line)
    merged = linemerge(MultiLineString(lines))
    rings = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
    polygons = []
    for ring in rings:
        if not ring.is_ring:
            raise CamError("Profiles and pockets need closed, non-crossing contours. Join gaps or remove duplicate lines in CAD; use Engrave for open paths.")
        poly = Polygon(ring)
        if not poly.is_valid or poly.area <= 1e-8:
            raise CamError("Invalid contour: " + explain_validity(poly))
        polygons.append(poly)
    for i, a in enumerate(polygons):
        checkpoint(cancel)
        for b in polygons[i + 1:]:
            if a.boundary.intersects(b.boundary):
                raise CamError("Contours touch, cross or duplicate one another. Separate or clean them in CAD.")
    return sorted(polygons, key=lambda p: p.area, reverse=True)


def pocket_region(polygons):
    # Even nesting depths are pocket floors; odd depths are protected islands.
    parents = []
    levels = []
    for i, poly in enumerate(polygons):
        containers = [j for j in range(i) if polygons[j].contains(poly)]
        parent = min(containers, key=lambda j: polygons[j].area) if containers else None
        parents.append(parent)
        levels.append(0 if parent is None else levels[parent] + 1)
    floors = []
    for i, poly in enumerate(polygons):
        if levels[i] % 2 == 0:
            holes = [polygons[j].exterior.coords for j in range(len(polygons)) if parents[j] == i]
            floors.append(Polygon(poly.exterior.coords, holes))
    return unary_union(floors)


def polygons_in(geom):
    if geom.is_empty:
        return []
    return [geom] if geom.geom_type == "Polygon" else list(geom.geoms)


def boundaries(geom):
    paths = []
    for polygon in polygons_in(geom):
        paths.append(list(polygon.exterior.coords))
        paths.extend(list(r.coords) for r in polygon.interiors)
    return paths


def compensated_radius(diameter):
    # Round buffers use chords. A tiny conservative margin prevents those chords
    # encroaching on protected islands by the buffer tessellation error.
    return (diameter / 2) / math.cos(math.pi / (4 * QUADS)) + 0.0001

def plan_operation(drawing, op, cancel=None, progress=None):
    op.validate()
    paths = drawing.paths if op.layer == "*" else drawing.layers.get(op.layer, [])
    if not paths:
        raise CamError(f"No geometry on layer {op.layer!r}.")
    if op.mode == "Engrave":
        return PlannedOperation(op, paths)
    checkpoint(cancel, progress, "Checking contours")
    polys = closed_polygons(paths, cancel)
    radius = compensated_radius(op.tool_diameter)
    warnings = []
    result = []
    remaining_paths = []
    if op.mode in ("Inside profile", "Outside profile"):
        for i, poly in enumerate(polys):
            checkpoint(cancel, progress, "Offsetting profiles", i, len(polys))
            if any(other.contains(poly) for other in polys[:i]):
                raise CamError("Nested profile contours need separate layers/operations for holes and the outside outline.")
            offset = poly.buffer(radius if op.mode == "Outside profile" else -radius, quad_segs=QUADS)
            if offset.is_empty:
                raise CamError("Tool is too large for an inside contour. Choose a smaller cutter.")
            if len(polygons_in(offset)) != 1:
                raise CamError("Tool offset splits a profile into multiple pieces. Simplify the shape or use a smaller tool.")
            if op.mode == "Outside profile":
                # Each contour is a separate part to preserve. An offset can be
                # valid on its own while its cutter footprint gouges a neighbour.
                # Include a small margin for the rounded output coordinates.
                footprint = offset.boundary.buffer(radius, quad_segs=QUADS)
                if any(footprint.intersection(other).area > 1e-8
                       for j, other in enumerate(polys) if j != i):
                    raise CamError("Outside profiles are too close for this cutter: cutting one would enter another part. Increase spacing or use a smaller cutter.")
            result.extend(boundaries(offset))
    else:
        region = pocket_region(polys)
        components = polygons_in(region)
        for component in components:
            if component.buffer(-radius, quad_segs=QUADS).is_empty:
                raise CamError("Tool is too large for at least one pocket. Use a smaller cutter or a separate operation.")
        step = op.tool_diameter * op.stepover / 100
        distance = radius
        vertex_count = 0
        for iteration in range(10000):
            checkpoint(cancel, progress, "Clearing pocket", iteration, 0)
            inset = region.buffer(-distance, quad_segs=QUADS)
            if inset.is_empty:
                break
            loops = boundaries(inset)
            vertex_count += sum(map(len, loops))
            result.extend(loops)
            if vertex_count > 100_000:
                raise CamError("Pocket toolpath is too large. Increase stepover or simplify the drawing.")
            distance += step
        else:
            raise CamError("Pocket needs too many offset loops. Increase stepover.")
        footprints = []
        for path in result:
            checkpoint(cancel)
            footprints.append(LineString(path).buffer(op.tool_diameter / 2, quad_segs=QUADS))
        checkpoint(cancel, progress, "Checking pocket coverage")
        swept = unary_union(footprints)
        remaining = region.difference(swept)
        remaining_paths = boundaries(remaining)
        # This includes unreachable sharp corners and narrow areas, and any small
        # centre remnants from the simple offset-loop strategy. Never claim a
        # pocket is fully cleared just because the offset loops terminated.
        if remaining.area > 0.01:
            warnings.append(f"Estimated uncleared pocket area: {remaining.area:.3f} mm² (corners, narrow regions or centre remnants). Inspect the preview; a smaller cutter may be needed.")
    if op.tabs:
        if set(op.tab_positions) - {contour_key(p) for p in result}:
            raise CamError("Custom tabs belong to changed contours. Reset tab positions and place them again.")
        for path in result:
            if (op.tab_width + op.tool_diameter) * op.tabs >= LineString(path).length * 0.8:
                raise CamError("Tabs occupy too much of the contour. Reduce tab count/width.")
            tab_intervals(path, op)
        warnings.append("Check tab positions and corner clearance in preview; tab height is measured up from the final cut bottom.")
    return PlannedOperation(op, result, warnings, remaining_paths)
