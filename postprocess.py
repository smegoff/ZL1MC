from version import VERSION

def gcode(job):
    lines = [f"(DXF CAM {VERSION} - experimental - millimetres)",
             "(G54 zero: selected XY origin; Z zero: stock top)",
             "(Preview and air cut required; direct plunge entries)",
             "G90", "G21", "G17", "G94", "G54", "G40", "G49", "M5"]
    previous_op = -1
    for idx, move in enumerate(job.moves):
        if move.op != previous_op:
            op = job.plans[move.op].operation
            # User names remain in the UI; machine comments use only fixed ASCII.
            lines.append(f"(Operation {move.op + 1}: {op.mode}; depth {op.depth:.4f} mm)")
            previous_op = move.op
        parts = [move.code]
        for letter, value in (("X", move.x), ("Y", move.y), ("Z", move.z)):
            if value is not None:
                parts.append(f"{letter}{value:.4f}")
        if move.feed is not None:
            parts.append(f"F{move.feed:.3f}")
        lines.append(" ".join(parts))
        if idx == 0 and job.settings.spindle_on:
            lines.append(f"M3 S{job.settings.spindle}")
            lines.append(f"G4 P{job.settings.spindle_delay:.3f} (spindle start delay)")
    lines.extend(("M5", "M2"))
    return "\n".join(lines) + "\n"
