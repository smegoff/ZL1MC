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

```
C:\CNC\DXFtoGcode
```

Put these two files in it:
- `dxf_to_gcode_gui.py`
- `install_dxf_to_gcode.ps1`

---

### Step 2: Run the installer
1. Open **PowerShell**
2. Go to the folder:

```powershell
cd C:\CNC\DXFtoGcode
```

3. Run the installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_dxf_to_gcode.ps1
```

What this does:
- Installs Python (3.11 or 3.12)
- Installs required libraries
- Sets everything up

---

### Step 3: Run the program

```powershell
python .\dxf_to_gcode_gui.py
```

A window will open.

You’re done.

---

# OPTION B — Manual Install (If you prefer step-by-step)

### Step 1: Install Python
1. Install **Python 3.11 or 3.12** from the Microsoft Store or python.org
2. Make sure **“Add Python to PATH”** is enabled

Check it works:

```powershell
python --version
```

---

### Step 2: Install required library
In PowerShell:

```powershell
python -m pip install ezdxf
```

---

### Step 3: Run the program

```powershell
python dxf_to_gcode_gui.py
```

---

# Using the Converter (Beginner Friendly)

### Step 1: Select your DXF
- Click **Browse…**
- Choose your `.dxf` file

The output `.gcode` file will auto-fill.

---

### Step 2: Recommended beginner settings

| Setting | Value |
|------|------|
| Units | `mm` |
| Scale | `1.0` |
| Curve segment length | `0.8` |
| Safe Z | `5.0` |
| Cut Z | `-0.2` (start shallow!) |
| Feed XY | `400–600` |
| Feed Z | `150–200` |
| Spindle | Enabled |

If curves look rough → reduce **Curve segment length**  
If file is huge → increase it (1.2–2.0)

---

### Step 3: Convert
Click **Convert**  
The program will tell you where the `.gcode` file was saved.

---

# Running on the CNC (IMPORTANT)

**Do not skip this section.**

1. Load the `.gcode` file into your CNC sender.
2. **Preview the toolpath**.
3. Do a **dry run**:
   - Spindle OFF, or
   - Z raised above the workpiece
4. Confirm:
   - The tool stays inside the work area
   - The size looks correct
5. Only then do a real cut.

---

# Common Problems & Fixes

### The drawing is tiny or massive
- Units mismatch
- Try:
  - Units = inch, Scale = 25.4  
  - or Units = mm, Scale = 0.03937  

---

### G-code file is huge
- Increase **Curve segment length** (1.2 – 2.0)

---

### Tool plunges too deep
- Reduce **Cut Z**
- Start at `-0.2` mm

---

### Nothing converts
- Enable **“Print DXF entity debug to console”**
- Convert again
- Check console output (DXF may be empty or malformed)

---

# Supported DXF Geometry

This tool supports **most art-style DXFs**, including:
- LINE
- POLYLINE / LWPOLYLINE
- ARC
- CIRCLE
- ELLIPSE
- SPLINE
- HATCH boundaries
- INSERT (block references)

Curves are automatically converted into small line segments that GRBL understands.

---

# What this tool does NOT do

This is **not** Fusion 360 or VCarve.

No:
- Tool diameter compensation
- Pocketing
- Multi-depth stepdowns
- Tabs
- Material removal strategies

It is intended for **simple engraving and tracing**.

---

# License / Use

Use it, modify it, share it, don’t crash your CNC.

If something breaks, run a dry pass first next time 😉

Happy cutting 👌
