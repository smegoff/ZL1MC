import html

COLORS = ("#087f8c", "#b45416", "#6247aa", "#a51b54", "#326d23")


def preview_segments(job):
    """Same XY movements as exported G-code; repeated depth passes are collapsed."""
    x = y = None
    seen = set()
    for m in job.moves:
        if m.x is None:
            continue
        if x is not None:
            segment = (x, y, m.x, m.y, m.code == "G0", m.op, m.tab)
            if segment not in seen:
                seen.add(segment)
                yield segment
        x, y = m.x, m.y


def svg_preview(job):
    segs = list(preview_segments(job))
    pts = [(x, y) for p in job.drawing.paths for x, y in p]
    pts += [(s[i], s[i+1]) for s in segs for i in (0, 2)]
    lo_x, lo_y = min(p[0] for p in pts), min(p[1] for p in pts)
    hi_x, hi_y = max(p[0] for p in pts), max(p[1] for p in pts)
    scale = min(920 / max(hi_x-lo_x, 1), 570 / max(hi_y-lo_y, 1))
    def xy(x, y):
        return 40 + (x-lo_x)*scale, 610 - (y-lo_y)*scale
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="760" viewBox="0 0 1000 760">',
             '<rect width="100%" height="100%" fill="#fafafa"/>',
             '<text x="30" y="25" font-family="sans-serif" font-size="18">DXF CAM — tool centreline preview (mm)</text>']
    for path in job.drawing.paths:
        points = " ".join(f"{xy(x,y)[0]:.3f},{xy(x,y)[1]:.3f}" for x, y in path)
        lines.append(f'<polyline points="{points}" fill="none" stroke="#b8bec5" stroke-width="1"/>')
    for x, y, u, v, rapid, op, tab in segs:
        a, b = xy(x, y)
        c, d = xy(u, v)
        color = "#ff9800" if tab else "#b1b9c3" if rapid else COLORS[op % len(COLORS)]
        dash = ' stroke-dasharray="4 5"' if rapid else ""
        lines.append(f'<line x1="{a:.3f}" y1="{b:.3f}" x2="{c:.3f}" y2="{d:.3f}" stroke="{color}" stroke-width="{3 if tab else 1.2}"{dash}/>')
    labels = ["Solid: cuts | Dashed: clearance travel | Orange: tabs on deeper passes",
              f"Preview extent: {hi_x-lo_x:.3f} × {hi_y-lo_y:.3f} mm. Z passes and tool width are not shown.",
              "No collision or stock-removal simulation. Inspect depths and setup separately."]
    labels += [f"{i+1}. {p.operation.name}: {p.operation.mode}, depth {p.operation.depth:g} mm" for i,p in enumerate(job.plans[:3])]
    for i, label in enumerate(labels):
        lines.append(f'<text x="30" y="{644+i*18}" font-family="sans-serif" font-size="13">{html.escape(label)}</text>')
    lines.append('</svg>')
    return "\n".join(lines)
