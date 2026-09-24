# Changelog

## 0.3.0 — 2026-09-25

- Add Apply/Discard handling, contextual settings, duplication and operation undo/redo.
- Add pan/zoom, operation/pass filtering, side view, cutter width and uncleared-region preview overlays.
- Support dragging and saving tab positions, including tabs wrapping the contour seam without a deep initial plunge.
- Validate configured stock/spoilboard depth, tool stick-out, fixture-height clearance and G54 cutter/tip envelopes.
- Move import/planning/export to background tasks with progress and cooperative cancellation.
- Stage output bundles, restore old files on ordinary replacement failures, and provide recovery after interruption.
- Version job settings, save relative drawing references and fingerprints, and reject changed source files at export.
- Separate the code into import, models, geometry/tabs, planning, postprocessing, preview, persistence and UI modules.
- Add Windows CI on Python 3.11/3.13 and expand local coverage to 82 passing tests.

Remains experimental and has no physical CNC validation. Advanced entry strategies, stock-removal simulation and standalone executable packaging remain future work.

## 0.2.1 — 2026-09-24

- Reject outside profiles whose cutter footprint would enter another part in the same operation. Previously, two individually valid contours could produce a cut into a neighbouring part when their spacing was too small for the cutter.
- Add regression tests for rejected close contours and preserved separated parts.
- Share the application and release ZIP version through `version.py`.
- Add release notes and a prioritised GUI/code improvement plan.

This remains experimental and has not been validated on a physical CNC. The new check covers neighbouring contours in one outside-profile operation; it is not a stock, fixture or cross-operation collision simulator.

## 0.2.0 — 2026-09-24

First local 2.5D edition, extending the earlier single-depth line-tracing converter:

- Multi-pass engraving, inside/outside profiles, pocket clearing with islands, layer-based operation ordering and outside holding tabs.
- Toolpath preview, reusable job settings, and G-code with SVG preview/JSON report exports.
- Source-unit conversion to mm, flat-geometry validation and explicit import/geometry warnings.
- Windows setup and launcher, beginner README and example DXF/job.
- 43 automated CAM and real Tk GUI checks passed before the 0.2.1 follow-up.
