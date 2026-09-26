"""CUPS option values understood by the M832D filter."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Options:
    density: int = 2
    heat: int = 0x37
    threshold: int = 160
    feed: int = 2
    rotation: int = 0
    offset_x: int = 0
    offset_y: int = 0


def parse_options(raw):
    result = Options()
    values = dict(item.split("=", 1) for item in raw.split() if "=" in item)
    aliases = {"M832DDensity": "density", "M832DHeat": "heat",
               "M832DThreshold": "threshold", "M832DFeed": "feed",
               "M832DRotation": "rotation", "M832DOffsetX": "offset_x",
               "M832DOffsetY": "offset_y"}
    fields = result.__dict__.copy()
    for key, name in aliases.items():
        if key in values:
            named = {
                ("density", "Default"): 2, ("density", "Light"): 1,
                ("density", "Heavy"): 4, ("heat", "Default"): 0x37,
                ("heat", "Slow"): 0x20, ("heat", "Fast"): 0x50,
            }.get((name, values[key]))
            if named is not None:
                fields[name] = named
                continue
            try:
                fields[name] = int(values[key], 0)
            except ValueError as exc:
                raise ValueError(f"invalid {key}") from exc
    if not 0 <= fields["density"] <= 15 or not 0 <= fields["heat"] <= 255:
        raise ValueError("density or heat is outside its supported range")
    if not 0 <= fields["threshold"] <= 255 or not 0 <= fields["feed"] <= 255:
        raise ValueError("threshold or feed is outside its supported range")
    if fields["rotation"] not in (0, 90, 180, 270):
        raise ValueError("rotation must be 0, 90, 180, or 270")
    return Options(**fields)
