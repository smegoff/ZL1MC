from __future__ import annotations
from dataclasses import dataclass, field
import math

MODES = ("Engrave", "Inside profile", "Outside profile", "Pocket")

class CamError(ValueError):
    pass


def number(value, name, minimum=None, strict=False):
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise CamError(f"{name} must be a number.") from exc
    if not math.isfinite(v):
        raise CamError(f"{name} must be finite.")
    if minimum is not None and (v <= minimum if strict else v < minimum):
        raise CamError(f"{name} must be {'greater than' if strict else 'at least'} {minimum}.")
    return v


@dataclass
class Drawing:
    layers: dict[str, list[list[tuple[float, float]]]]
    warnings: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def paths(self):
        return [p for paths in self.layers.values() for p in paths]

    @property
    def bounds(self):
        pts = [p for path in self.paths for p in path]
        return (min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts))

@dataclass
class Operation:
    name: str = "Operation"
    layer: str = "*"
    mode: str = "Engrave"
    depth: float = 1.0
    stepdown: float = 0.25
    tool_diameter: float = 3.175
    stepover: float = 40.0
    feed: float = 300.0
    plunge: float = 80.0
    tabs: int = 0
    tab_width: float = 4.0
    tab_height: float = 0.5
    tab_positions: dict[str, list[float]] = field(default_factory=dict)

    def validate(self):
        if not isinstance(self.name, str) or not isinstance(self.layer, str):
            raise CamError("Operation name and layer must be text.")
        if self.mode not in MODES:
            raise CamError(f"Unknown operation: {self.mode}")
        for key in ("depth", "stepdown", "tool_diameter", "feed", "plunge"):
            setattr(self, key, number(getattr(self, key), key, 0.001))
        self.stepover = number(self.stepover, "Stepover", 0, True)
        if self.stepover > 50:
            raise CamError("Stepover must be greater than 0 and at most 50 percent.")
        tabs = number(self.tabs, "Tab count", 0)
        if tabs != int(tabs) or tabs > 100:
            raise CamError("Tab count must be an integer from 0 to 100.")
        self.tabs = int(tabs)
        if not isinstance(self.tab_positions, dict):
            raise CamError("Tab positions must be a mapping of contour IDs to positions.")
        for key, positions in self.tab_positions.items():
            if not isinstance(key, str) or not isinstance(positions, list) or len(positions) != self.tabs:
                raise CamError("Custom tab positions must match the tab count. Reset tabs after changing the count.")
            for value in positions:
                if not 0 <= number(value, "Tab position") < 1:
                    raise CamError("Tab positions must be between 0 (inclusive) and 1 (exclusive).")
            self.tab_positions[key] = [float(value) for value in positions]
        if self.tabs:
            if self.mode != "Outside profile":
                raise CamError("Holding tabs are available for Outside profile only.")
            self.tab_width = number(self.tab_width, "Tab width", 0.001)
            self.tab_height = number(self.tab_height, "Tab height", 0.001)
            if self.tab_height >= self.depth:
                raise CamError("Tab height must be less than the final cut depth.")
        if math.ceil(self.depth / self.stepdown) > 1000:
            raise CamError("More than 1,000 depth passes requested.")


@dataclass
class Settings:
    safe_z: float = 5.0
    spindle: int = 10000
    spindle_on: bool = True
    spindle_delay: float = 2.0
    check_setup: bool = False
    stock_thickness: float = 3.0
    spoilboard_allowance: float = 0.2
    fixture_height: float = 0.0
    tool_stickout: float = 15.0
    x_min: float = -5.0
    x_max: float = 300.0
    y_min: float = -5.0
    y_max: float = 180.0
    z_min: float = -45.0
    z_max: float = 10.0

    def validate(self):
        self.safe_z = number(self.safe_z, "Safe Z", 0.001)
        if not isinstance(self.spindle_on, bool):
            raise CamError("Spindle enabled must be true or false.")
        s = number(self.spindle, "Spindle S value", 0)
        if s != int(s) or (self.spindle_on and s == 0):
            raise CamError("Spindle S must be a positive integer when enabled.")
        self.spindle = int(s)
        self.spindle_delay = number(self.spindle_delay, "Spindle delay", 0)
        if not isinstance(self.check_setup, bool):
            raise CamError("Setup checks must be true or false.")
        for key in ("stock_thickness", "tool_stickout"):
            setattr(self, key, number(getattr(self, key), key, 0.001))
        for key in ("spoilboard_allowance", "fixture_height"):
            setattr(self, key, number(getattr(self, key), key, 0))
        for axis in "xyz":
            low, high = axis + "_min", axis + "_max"
            setattr(self, low, number(getattr(self, low), low))
            setattr(self, high, number(getattr(self, high), high))
            if getattr(self, low) >= getattr(self, high):
                raise CamError(f"{axis.upper()} minimum must be below its maximum.")
        if self.check_setup:
            if self.safe_z <= self.fixture_height:
                raise CamError("Safe Z must be above the highest fixture (relative to stock top).")
            if not self.z_min <= self.safe_z <= self.z_max:
                raise CamError("Safe Z is outside the configured G54 Z limits.")

@dataclass
class PlannedOperation:
    operation: Operation
    paths: list
    warnings: list[str] = field(default_factory=list)
    remaining_paths: list = field(default_factory=list)

@dataclass
class Move:
    code: str
    x: float | None = None
    y: float | None = None
    z: float | None = None
    feed: float | None = None
    op: int = -1
    tab: bool = False
    level: float | None = None


@dataclass
class Job:
    drawing: Drawing
    settings: Settings
    plans: list[PlannedOperation]
    moves: list[Move]
    warnings: list[str]
