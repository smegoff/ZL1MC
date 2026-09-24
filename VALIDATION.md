# Validation — v0.3.0

Local validation: 25 September 2026, Windows, Python 3.13.0, Tk 8.6, ezdxf 1.4.4 and Shapely 2.1.2.

- 82 tests passed, including 13 real Tk GUI tests; no skips locally.
- The example produces 3,874 motion commands, an SVG and a report with a matching program checksum.
- `pip check` verifies dependency consistency.
- Windows CI is configured for Python 3.11/3.13, requires Tk tests, exports the example and builds the source ZIP. Results appear in the repository's Actions page.

## Coverage

Import/geometry: units, scale/origin, curves, blocks, HATCH islands, plane checks, closed contours, gaps/crossings/duplicates, cutter offsets, neighbouring parts and pocket coverage.

Motion/setup: final depths, stepdowns, clearance before XY rapids, tab heights/widths, custom seam-crossing tabs, overlap/stale-tab rejection, cutter envelope/Z limits, stock/spoilboard depth, fixture height and tool reach.

Persistence: legacy/versioned jobs, relative drawing references/fingerprints, schema rejection, program checksums, unchanged files after rendering failure, rollback after mid-commit failure/cancellation, and recovery after simulated process interruption.

GUI: load/build/export, operation editing/order/duplicate/undo/redo, pending-edit blocking and Apply/Discard/Cancel, contextual fields, depth/side preview, tab movement, invalid-job state preservation and default/smaller window bounds.

## Validation limits

No CNC/controller was connected. No physical cutting or independent controller/stock-removal simulation was performed. Representative fixtures do not prove arbitrary geometry or real workholding/cutting parameters.

Fresh Python installation with winget and standalone executable packaging were not tested. The existing-Python installer is rechecked for this release.

The example's estimated 2.205 mm² of remaining pocket material is expected, largely at sharp internal corners, and is reported explicitly.
