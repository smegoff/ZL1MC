# DXF → G-code Converter (3018 CNC / GRBL)

This tool converts **DXF drawing files** into **G-code** that can be run on a **3018 CNC machine** (or any GRBL-based CNC).

It is designed for:
- Engraving
- Outline tracing
- Laser/plasma-style art DXFs (animals, signs, silhouettes, etc.)

It is **not** a full CAM package (no pocketing, no tool diameter compensation).

---

## What this does (plain English)

1. You select a **DXF file** (a drawing).
2. The program converts it into **G-code** (machine instructions).
3. You load the `.gcode` file into your CNC controller software (UGS, Candle, etc.).

That’s it.

---

## What you need (Windows)

- Windows 10 or 11
- A 3018 CNC (or any GRBL-based CNC)
- CNC sender software (one of these):
  - Universal Gcode Sender (UGS)
  - Candle
  - bCNC
- **No Python knowledge required**

---

## Files in this project

| File | Purpose |
|-----|--------|
| `dxf_to_gcode_gui.py` | The DXF → G-code converter (GUI app) |
| `install_dxf_to_gcode.ps1` | Optional installer script (installs everything automatically) |

---

# OPTION A — Easy Automatic Install (Recommended)

This uses a PowerShell script to install everything for you.

### Step 1: Download the files
Create a folder, for example:

