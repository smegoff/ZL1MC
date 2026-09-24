# DXF → G-code 2.5D v0.3.0 — experimental

The original line-tracing converter now supports multiple depth passes, cutter-compensated profiles, pockets with islands and holding tabs. This release adds:

- Explicit pending-edit handling, contextual fields, duplication and operation undo/redo.
- Pan/zoom, operation/depth filtering, XZ side view, cutter-width overlay, uncleared-pocket outlines and draggable tabs.
- Stock, spoilboard, tool reach, fixture-height clearance and G54 envelope checks.
- Background import/planning/export with progress and cooperative cancellation.
- Versioned jobs with relative drawing paths and fingerprints.
- Recoverable export bundles, rollback tests and program checksums.
- Smaller modules and Windows GitHub Actions tests on Python 3.11 and 3.13.

Download `DXF-to-Gcode-2.5D-v0.3.0.zip`, extract all files, run `Setup.cmd`, then `Start_Converter.cmd`. Instructions and an example DXF/job are included.

82 automated tests pass locally, including real Tk interactions and injected export-failure recovery tests.

**Experimental prerelease: no physical CNC testing.** Entries remain vertical plunges. Clamp positions, stock removal, tool changes, ramp entry and 3D surfaces are not simulated or supported. Simulate, air cut and supervise scrap testing before relying on the program.
