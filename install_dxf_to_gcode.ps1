# install_dxf_to_gcode.ps1
# Installs Python + ezdxf for the DXF->Gcode GUI tool.
# Run in PowerShell (preferably Admin).

$ErrorActionPreference = "Stop"

Write-Host "=== DXF -> G-code installer ==="

# Check winget
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: winget is not available on this system." -ForegroundColor Red
    Write-Host "Fix: Install 'App Installer' from Microsoft Store, then try again."
    exit 1
}

# Install Python (prefers 3.12)
Write-Host "`n[1/3] Installing Python..."
try {
    winget install --id Python.Python.3.12 --exact --silent --accept-source-agreements --accept-package-agreements
} catch {
    Write-Host "Python 3.12 install failed; trying Python 3.11..." -ForegroundColor Yellow
    winget install --id Python.Python.3.11 --exact --silent --accept-source-agreements --accept-package-agreements
}

# Refresh PATH in this session (best-effort)
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# Verify python works
Write-Host "`n[2/3] Checking Python..."
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Python command not found after install." -ForegroundColor Red
    Write-Host "Try rebooting, then run: python --version"
    exit 1
}

python --version

# Install ezdxf
Write-Host "`n[3/3] Installing Python packages..."
python -m pip install --upgrade pip
python -m pip install ezdxf

Write-Host "`n=== Done ===" -ForegroundColor Green
Write-Host "To run the GUI:"
Write-Host "  cd $PSScriptRoot"
Write-Host "  python .\dxf_to_gcode_gui.py"
