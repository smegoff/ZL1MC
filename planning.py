from __future__ import annotations
import math
from shapely.geometry import LineString
from models import CamError, Job, Move, Settings, number
from geometry import plan_operation
from tabs import tab_intervals
from work_control import Cancelled, checkpoint

MAX_MOVES = 500_000

def depth_passes(depth, stepdown):
    depth = number(depth, "Depth", 0, True)
    stepdown = number(stepdown, "Stepdown", 0, True)
    count = math.ceil(depth / stepdown - 1e-12)
    if count > 1000:
        raise CamError("More than 1,000 depth passes requested.")
    return [-min((i + 1) * stepdown, depth) for i in range(max(1, count))]

def tab_segments(path, op, z):
    """Yield segment ends and segment cutting heights; split exactly at tabs."""
    if not op.tabs or z >= -op.depth + op.tab_height:
        for pt in path[1:]:
            yield pt, z, False
        return
    line = LineString(path)
    total = line.length
    breaks = [0.0]
    distance = 0.0
    for a, b in zip(path, path[1:]):
        distance += math.dist(a, b)
        breaks.append(distance)
    intervals = []
    if op.tabs and z < -op.depth + op.tab_height:
        intervals = tab_intervals(path, op)
        for a, b in intervals:
            breaks.extend((a, b))
    cuts = sorted(set(breaks))
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 1e-9:
            continue
        is_tab = any(lo <= (a + b) / 2 <= hi for lo, hi in intervals)
        p = line.interpolate(b)
        yield (p.x, p.y), max(z, -op.depth + op.tab_height) if is_tab else z, is_tab

def build_job(drawing, operations, settings=None, cancel=None, progress=None):
    checkpoint(cancel, progress, "Validating job")
    settings = settings or Settings()
    settings.validate()
    if not operations:
        raise CamError("Add at least one operation.")
    for op in operations:
        op.validate()
    if any(abs(op.tool_diameter - operations[0].tool_diameter) > 1e-6 for op in operations):
        raise CamError("Use one cutter diameter per exported job. Export separate jobs for different physical tools; automatic tool changes are not supported.")
    plans = []
    for op in operations:
        try:
            plans.append(plan_operation(drawing, op, cancel, progress))
        except Cancelled:
            raise
        except CamError as exc:
            raise CamError(f"{op.name}: {exc}") from exc
    warnings = list(drawing.warnings)
    if not settings.check_setup:
        warnings.append("Stock, clearance and G54 travel checks are disabled. Verify the setup before machining.")
    else:
        validate_setup(plans, settings)
    moves = [Move("G0", z=settings.safe_z)]
    for i, plan in enumerate(plans):
        op = plan.operation
        warnings.extend(f"{op.name}: {w}" for w in plan.warnings)
        for z in depth_passes(op.depth, op.stepdown):
            checkpoint(cancel, progress, f"Planning {op.name}: Z {z:g} mm", i, len(plans))
            for path in plan.paths:
                segments = iter(tab_segments(path, op, z))
                first = next(segments)
                from itertools import chain
                current_z = first[1]
                moves.append(Move("G0", x=path[0][0], y=path[0][1], op=i, level=z))
                moves.append(Move("G1", z=current_z, feed=op.plunge, op=i, level=z))
                for (x, y), segment_z, is_tab in chain([first], segments):
                    if len(moves) % 1024 == 0:
                        checkpoint(cancel)
                    if segment_z != current_z:
                        moves.append(Move("G1", z=segment_z, feed=op.plunge, op=i, tab=is_tab, level=z))
                        current_z = segment_z
                    moves.append(Move("G1", x=x, y=y, feed=op.feed, op=i, tab=is_tab, level=z))
                    if len(moves) > MAX_MOVES:
                        raise CamError("Job exceeds 500,000 moves. Reduce complexity or split operations.")
                moves.append(Move("G0", z=settings.safe_z, op=i, level=z))
    return Job(drawing, settings, plans, moves, warnings)


def validate_setup(plans, settings):
    for plan in plans:
        op = plan.operation
        if op.depth > settings.stock_thickness + settings.spoilboard_allowance:
            raise CamError(f"{op.name}: depth exceeds stock thickness plus spoilboard allowance.")
        if op.depth + settings.fixture_height >= settings.tool_stickout:
            raise CamError(f"{op.name}: tool stick-out is insufficient for depth and fixture height.")
        if -op.depth < settings.z_min:
            raise CamError(f"{op.name}: cut is below the configured G54 Z minimum.")
        if op.tabs and settings.stock_thickness - op.depth + op.tab_height <= 0:
            raise CamError(f"{op.name}: tabs leave no material in the configured stock.")
        radius = op.tool_diameter / 2 + .0001
        for path in plan.paths:
            xs, ys = zip(*path)
            if (min(xs)-radius < settings.x_min or max(xs)+radius > settings.x_max
                    or min(ys)-radius < settings.y_min or max(ys)+radius > settings.y_max):
                raise CamError(f"{op.name}: cutter footprint exceeds the configured G54 XY envelope.")
