# Improvement status — v0.3.0

The six requested workflow improvements are implemented:

1. **Editing:** Apply/Discard/Cancel, blocked export for pending edits, contextual fields, duplicate and operation undo/redo.
2. **Preview:** cached motion, pan/zoom, operation selector, pass slider, side view, plunge markers, cutter-width overlay, remaining-pocket boundaries and draggable tabs.
3. **Setup:** stock, spoilboard, fixture height, tool stick-out and G54 envelope checks. Defaults must be verified.
4. **Export:** staged bundles, backup journal, rollback on ordinary failures/cancellation, explicit interruption recovery and program checksum.
5. **Responsiveness:** background import/build/export, progress/cancellation, incremental import limits, cumulative pocket vertex accounting and debounced redraws.
6. **Maintenance:** smaller modules, versioned/validated job files, relative drawing references/fingerprints, expanded tests and Windows CI.

The 0.2.1 neighbouring outside-profile protection is retained.

## Limits and future extensions

- Setup checks use fixture height and a work-coordinate envelope, not clamp positions, holder geometry or stock removal. Cross-operation collision analysis needs a richer model.
- Tabs can be dragged, but corner positions need review; bridge-width calculations assume straight cuts. Changed contours require tab reset.
- Cancellation is cooperative. A DXF-reader/GEOS call may finish before it can stop. Large canvas redraws can still take time.
- Export replaces three files sequentially with backups/journal. Ordinary failures roll back; interruption needs recovery. This is not hardware-failure-proof multi-file atomicity.
- Static SVG remains a top view; depth controls are in the desktop app.
- Ramped/helical entry, finishing allowances, cutting-direction selection, travel optimisation, spatial indexing, fully streamed programs and a standalone Windows executable remain future extensions.
- Clean-machine winget installation and physical CNC cuts still need validation.

The later CAM/executable extensions were roadmap ideas beyond the six requested workflow improvements and need separate implementation and machine testing.
