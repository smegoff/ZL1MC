param([switch]$Launch)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location -LiteralPath $PSScriptRoot

function Find-CompatiblePython {
    $candidates = @()
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $found = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0) { $candidates += $found }
        } catch { }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*\WindowsApps\*') { $candidates += $command.Source }
    $pythonRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $pythonRoot) {
        $candidates += Get-ChildItem -LiteralPath $pythonRoot -Directory |
            Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'python.exe' }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate) {
            try {
                & $candidate -c 'import sys, venv; from tk_support import check_tk; check_tk(); sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) else 1)' 2>$null
                if ($LASTEXITCODE -eq 0) { return $candidate }
            } catch { }
        }
    }
    return $null
}

try {
    Write-Host 'DXF 2.5D CAM setup - installs dependencies into this folder only.'
    $pythonExe = Find-CompatiblePython
    if (-not $pythonExe) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw 'Install Python 3.13 from https://www.python.org/downloads/windows/ with Tcl/Tk and pip enabled, then run Setup.cmd again. No admin shell is required.'
        }
        Write-Host 'Installing Python 3.13 for your Windows user with winget...'
        & $winget.Source install --id Python.Python.3.13 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw 'Python installation failed. See the manual instructions in README.md.' }
        $pythonExe = Find-CompatiblePython
        if (-not $pythonExe) { throw 'Python was installed but could not be located. Reopen this folder and run Setup.cmd again.' }
    }
    Write-Host "Using $pythonExe"
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $pythonExe -m venv (Join-Path $PSScriptRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the private Python environment.' }
    }
    & $venvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your internet connection and rerun Setup.cmd.' }
    & $venvPython -c 'import ezdxf, shapely, cam; from tk_support import check_tk; check_tk(); print(ezdxf.__version__, shapely.__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'Setup validation failed. See the error above.' }
    Write-Host 'Ready. Double-click Start_Converter.cmd to open the converter.'
    if ($Launch) {
        & $venvPython (Join-Path $PSScriptRoot 'dxf_to_gcode_gui.py')
        if ($LASTEXITCODE -ne 0) { throw 'The converter exited with an error.' }
    }
} catch {
    Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
