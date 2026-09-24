"""Versioned job files and recoverable multi-file export transactions."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from models import CamError, Operation, Settings, number
from version import VERSION
from preview import svg_preview
from postprocess import gcode
from work_control import checkpoint

SCHEMA_VERSION = 1


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_import(data):
    defaults = dict(source_units="Auto", scale=1.0, tolerance=.02, origin="Drawing origin")
    if not isinstance(data, dict) or set(data) - set(defaults):
        raise CamError("Invalid drawing import settings.")
    defaults.update(data)
    if defaults["source_units"] not in ("Auto", "mm", "inch"):
        raise CamError("Source units must be Auto, mm or inch.")
    if defaults["origin"] not in ("Drawing origin", "Lower left"):
        raise CamError("Unknown drawing origin.")
    defaults["scale"] = number(defaults["scale"], "Scale", 0, True)
    defaults["tolerance"] = number(defaults["tolerance"], "Curve tolerance", .001)
    return defaults


@dataclass
class JobConfig:
    import_settings: dict
    settings: Settings
    operations: list[Operation]
    drawing: str = ""
    drawing_sha256: str = ""
    selected_operation: int | None = None


def read_config(filename):
    path = Path(filename)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version", 0) not in (0, SCHEMA_VERSION):
        raise CamError("Unsupported job-file version.")
    try:
        imports = validate_import(data.get("import", {}))
        settings = Settings(**data.get("settings", {}))
        settings.validate()
        if not isinstance(data["operations"], list) or len(data["operations"]) > 1000:
            raise CamError("Operations must be a list of at most 1,000 entries.")
        operations = [Operation(**op) for op in data["operations"]]
        for op in operations:
            op.validate()
        drawing = data.get("drawing", {})
        if not isinstance(drawing, dict):
            raise CamError("Invalid drawing reference.")
        relative, checksum = drawing.get("path", ""), drawing.get("sha256", "")
        if not isinstance(relative, str) or not isinstance(checksum, str):
            raise CamError("Invalid drawing path or fingerprint.")
        if checksum and (len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum)):
            raise CamError("Invalid drawing fingerprint.")
        selected = data.get("selected_operation")
        if selected is not None and (type(selected) is not int or not 0 <= selected < len(operations)):
            raise CamError("Invalid selected operation.")
    except (TypeError, KeyError) as exc:
        raise CamError(f"Invalid job file: {exc}") from exc
    return JobConfig(imports, settings, operations,
                     str((path.parent / relative).resolve()) if relative else "", checksum, selected)


def atomic_text(path, text):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_config(filename, imports, settings, operations, drawing="", selected=None):
    imports = validate_import(imports)
    settings.validate()
    for op in operations:
        op.validate()
    target = Path(filename).resolve()
    data = {"schema_version": SCHEMA_VERSION, "app_version": VERSION,
            "import": imports, "settings": asdict(settings),
            "operations": [asdict(op) for op in operations], "selected_operation": selected}
    if drawing:
        source = Path(drawing).resolve()
        try:
            ref = os.path.relpath(source, target.parent)
        except ValueError:
            ref = str(source)
        data["drawing"] = {"path": ref, "sha256": fingerprint(source)}
    atomic_text(target, json.dumps(data, indent=2))


def export_paths(filename):
    target = Path(filename).resolve()
    if target.suffix.lower() not in (".gcode", ".nc", ".tap"):
        raise CamError("Output must end in .gcode, .nc or .tap.")
    return [target, target.with_suffix(".preview.svg"), target.with_suffix(".report.json")]


def transaction_dir(target):
    return target.parent / ("." + target.stem + ".export-transaction")


def recover_export(filename):
    """Restore a previous bundle after interruption; retain backups until done."""
    paths = export_paths(filename)
    txn = transaction_dir(paths[0])
    if not txn.exists():
        return False
    if txn.is_symlink() or txn.resolve().parent != paths[0].parent:
        raise CamError("Unexpected export recovery directory.")
    journal = txn / "journal.json"
    if journal.exists() and not (txn / "committed").exists():
        data = json.loads(journal.read_text(encoding="utf-8"))
        if data.get("files") != [p.name for p in paths] or len(data.get("existed", [])) != 3:
            raise CamError("Export recovery journal does not match this output.")
        for i, target in enumerate(paths):
            if data["existed"][i]:
                restored = txn / f"restore{i}"
                shutil.copyfile(txn / f"backup{i}", restored)
                os.replace(restored, target)
            else:
                target.unlink(missing_ok=True)
    shutil.rmtree(txn)
    return True


def export_job(job, filename, cancel=None, progress=None):
    paths = export_paths(filename)
    if job.drawing.source and paths[0] == Path(job.drawing.source).resolve():
        raise CamError("The output cannot overwrite the input drawing.")
    checkpoint(cancel, progress, "Preparing G-code")
    program = gcode(job)
    checkpoint(cancel, progress, "Preparing preview")
    svg = svg_preview(job)
    report = {"version": VERSION, "input": job.drawing.source, "units": "mm",
              "settings": asdict(job.settings), "operations": [asdict(p.operation) for p in job.plans],
              "warnings": job.warnings, "moves": len(job.moves),
              "program_sha256": hashlib.sha256(program.encode("ascii")).hexdigest(),
              "status": "Experimental; software tested, not machine validated"}
    payloads = [program.encode("ascii"), svg.encode("utf-8"), json.dumps(report, indent=2).encode("utf-8")]
    checkpoint(cancel, progress, "Staging export")
    txn = transaction_dir(paths[0])
    if txn.exists():
        raise CamError(f"An interrupted export needs recovery. Recover {paths[0].name} before retrying; this restores the previous bundle.")
    txn.mkdir()  # Exclusive target lock.
    try:
        existed = [p.exists() for p in paths]
        for i, (target, payload) in enumerate(zip(paths, payloads)):
            checkpoint(cancel)
            with (txn / f"stage{i}").open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if existed[i]:
                shutil.copyfile(target, txn / f"backup{i}")
        atomic_text(txn / "journal.json", json.dumps({"files": [p.name for p in paths], "existed": existed}))
        for i,target in enumerate(paths):
            checkpoint(cancel, progress, "Installing export files", i, 3)
            os.replace(txn / f"stage{i}", target)
        atomic_text(txn / "committed", "complete")
    except Exception:
        recover_export(paths[0])
        raise
    shutil.rmtree(txn)
