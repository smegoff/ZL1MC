"""Build a small source ZIP; explicitly excludes environments and cached files."""
from pathlib import Path
import zipfile
from version import VERSION

root = Path(__file__).resolve().parent
target = root.parent / f"DXF-to-Gcode-2.5D-v{VERSION}.zip"
files = [root / name for name in (
    "README.md", "VALIDATION.md", "requirements.txt", ".gitignore", ".gitattributes", "cam.py",
    "dxf_to_gcode_gui.py", "tk_support.py", "install_dxf_to_gcode.ps1",
    "Setup.cmd", "Start_Converter.cmd", "build_release.py", "version.py",
    "CHANGELOG.md", "IMPROVEMENTS.md", "RELEASE_NOTES.md",
    "models.py", "dxf_import.py", "geometry.py", "planning.py", "postprocess.py",
    "persistence.py", "preview.py", "preview_widget.py", "tabs.py", "ui_app.py", "work_control.py",
)]
for directory in ("tests", "examples", ".github"):
    files.extend(p for p in (root / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, Path("DXF-to-Gcode-2.5D") / path.relative_to(root))
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert not any(".venv" in name or "__pycache__" in name for name in archive.namelist())
    print(f"Verified {len(archive.namelist())} files; {target.stat().st_size:,} bytes")
print(target)
