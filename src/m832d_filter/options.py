"""CUPS option values understood by the M832D filter."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Options:
    density: int = 2
    threshold: int = 160
    rendering: str = "atkinson"
    rotation: int = 0
    offset_x: int = 0
    offset_y: int = 0
    page_pause: int = 0


def parse_options(raw):
    result = Options()
    values = dict(item.split("=", 1) for item in raw.split() if "=" in item)
    aliases = {"M832DDarkness": "density", "M832DDensity": "density",
               "M832DThreshold": "threshold",
               "M832DRendering": "rendering",
               "M832DRotation": "rotation", "M832DOffsetX": "offset_x",
               "M832DOffsetY": "offset_y", "M832DPagePause": "page_pause"}
    fields = result.__dict__.copy()
    for key, name in aliases.items():
        if key in values:
            named = {
                ("density", "Default"): 2, ("density", "Fine"): 1,
                ("density", "Medium"): 2, ("density", "Thick"): 4,
                # Preserve values accepted by queues using the old project UI.
                ("density", "Light"): 1, ("density", "Heavy"): 4,
                ("rendering", "Atkinson"): "atkinson",
                ("rendering", "FloydSteinberg"): "floyd-steinberg",
                ("rendering", "Threshold"): "threshold",
            }.get((name, values[key]))
            if named is not None:
                fields[name] = named
                continue
            try:
                fields[name] = int(values[key], 0)
            except ValueError as exc:
                raise ValueError(f"invalid {key}") from exc
    if not 0 <= fields["density"] <= 15:
        raise ValueError("darkness is outside its supported range")
    if not 0 <= fields["threshold"] <= 255:
        raise ValueError("threshold is outside its supported range")
    if fields["rendering"] not in ("atkinson", "floyd-steinberg", "threshold"):
        raise ValueError("rendering must be Atkinson, FloydSteinberg, or Threshold")
    if fields["rotation"] not in (0, 90, 180, 270):
        raise ValueError("rotation must be 0, 90, 180, or 270")
    if fields["page_pause"] not in (0, 5, 10, 20, 30):
        raise ValueError("page pause must be 0, 5, 10, 20, or 30 seconds")
    return Options(**fields)
