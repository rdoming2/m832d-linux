"""Deterministic monochrome rendering for grayscale raster rows."""


_SCALE = 4096
_MIDPOINT = 128 * _SCALE
# Integer error diffusion keeps output deterministic across platforms.  Diffusion
# uses a fixed luminance midpoint; the configurable threshold applies only to the
# simple threshold renderer below.


def _round_division(value, divisor):
    """Round to nearest, with half values rounded away from zero."""
    if value >= 0:
        return (value + divisor // 2) // divisor
    return -((-value + divisor // 2) // divisor)


def _diffuse(rows, algorithm):
    """Diffuse error with serpentine traversal and mirrored horizontal weights."""
    width = len(rows[0]) if rows else 0
    current = [0] * width
    next_row = [0] * width
    next_next_row = [0] * width
    rendered = []
    for y, source in enumerate(rows):
        output = bytearray(width)
        reverse = y % 2 == 1
        positions = range(width - 1, -1, -1) if reverse else range(width)
        for x in positions:
            adjusted = source[x] * _SCALE + current[x]
            black = adjusted < _MIDPOINT
            output[x] = 1 if black else 0
            error = adjusted - (0 if black else 255 * _SCALE)
            # Floyd-Steinberg reaches the current/next rows.  Atkinson also
            # carries error two rows ahead; odd rows mirror horizontal offsets.
            if algorithm == "floyd-steinberg":
                neighbors = ((x + (-1 if reverse else 1), 7),
                             (x + (1 if reverse else -1), 3),
                             (x, 5),
                             (x + (-1 if reverse else 1), 1))
                targets = (current, next_row, next_row, next_row)
            else:
                direction = -1 if reverse else 1
                neighbors = ((x + direction, 2), (x + 2 * direction, 2),
                             (x - direction, 2), (x, 2),
                             (x + direction, 2), (x, 2))
                targets = (current, current, next_row, next_row, next_row,
                           next_next_row)
            for target, (neighbor, weight) in zip(targets, neighbors):
                if 0 <= neighbor < width:
                    target[neighbor] += _round_division(error * weight, 16)
        rendered.append(output)
        current, next_row = next_row, [0] * width
        if algorithm == "atkinson":
            next_row, next_next_row = next_next_row, [0] * width
    return rendered


def render(rows, mode, threshold=160):
    """Render 8-bit luminance rows as rows of black-pixel flags."""
    if mode == "threshold":
        return [bytearray(value < threshold for value in row) for row in rows]
    if mode not in ("atkinson", "floyd-steinberg"):
        raise ValueError("unsupported rendering mode")
    return _diffuse(rows, mode)
