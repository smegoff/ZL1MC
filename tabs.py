"""Stable contour identities and manually positioned, wraparound holding tabs."""
import hashlib
import json
from shapely.geometry import LineString
from models import CamError


def contour_key(path):
    return hashlib.sha256(json.dumps([[round(x,6),round(y,6)] for x,y in path]).encode()).hexdigest()[:20]


def tab_centres(path, op):
    return op.tab_positions.get(contour_key(path), [(i+.5)/op.tabs for i in range(op.tabs)]) if op.tabs else []


def tab_intervals(path, op):
    total = LineString(path).length
    centres = sorted(float(v) for v in tab_centres(path, op))
    width = (op.tab_width + op.tool_diameter) / total
    if centres and any((centres[(i+1) % len(centres)] - a) % 1 < width + 1e-6
                       for i,a in enumerate(centres) if len(centres)>1):
        raise CamError("Holding tabs overlap. Move them farther apart or reduce their width/count.")
    result = []
    for centre in centres:
        low, high = centre-width/2, centre+width/2
        for shift in (-1,0,1):
            a,b = max(0,low+shift),min(1,high+shift)
            if b>a:
                result.append((a*total,b*total))
    return sorted(result)
