"""Public compatibility facade and command-line entry point."""
import argparse
import json
from pathlib import Path
from version import VERSION
from models import CamError, Drawing, Operation, Settings, PlannedOperation, Move, Job, MODES
from dxf_import import load_dxf
from geometry import closed_polygons, compensated_radius, plan_operation, pocket_region
from planning import build_job, depth_passes, tab_segments
from postprocess import gcode
from preview import COLORS, preview_segments, svg_preview
from persistence import export_job, fingerprint, read_config, recover_export

def main():
    parser = argparse.ArgumentParser(description="Offline experimental DXF 2.5D CAM; settings/output in mm")
    parser.add_argument("dxf", nargs="?")
    parser.add_argument("job", nargs="?", help="JSON job configuration")
    parser.add_argument("output", nargs="?", help=".gcode output")
    parser.add_argument("--recover-export", metavar="GCODE", help="Restore an interrupted export's previous file set")
    args = parser.parse_args()
    if args.recover_export:
        if any((args.dxf,args.job,args.output)):
            parser.error("Recovery takes only --recover-export and its filename.")
        print("Recovered export." if recover_export(args.recover_export) else "No interrupted export found.")
        return
    if not all((args.dxf,args.job,args.output)):
        parser.error("Provide DXF, job JSON and output filename.")
    config = read_config(args.job)
    if config.drawing_sha256 and fingerprint(args.dxf) != config.drawing_sha256:
        raise CamError("Drawing differs from the saved job fingerprint. Review and resave it in the GUI.")
    drawing = load_dxf(args.dxf, **config.import_settings)
    job = build_job(drawing, config.operations, config.settings)
    export_job(job, args.output)
    print(f"Exported {len(job.moves)} moves to {args.output}")
    for warning in job.warnings:
        print("WARNING:", warning)


if __name__ == "__main__":
    main()
