"""Continuous collision between a moving round and a stationary disc.

Tunnelling is real here: a round covers ~30 units per tick against a 24-unit plane, so
sampling endpoints misses hits entirely. Verified against the naive approach in the tests.

THE RULE, and it is the whole fix: work in minimum-image relative coordinates and never wrap
the DISPLACEMENT vector -- only the start offset.
"""

import math

from . import geom


def swept_hit(px: float, py: float, radius: float,
              sx: float, sy: float, dx: float, dy: float,
              w: float, h: float) -> float | None:
    """Fraction of the step [0, 1] at which the segment first enters the disc, else None.

    (px, py) is the disc centre; (sx, sy) the segment start; (dx, dy) its displacement.

    PRECONDITION: travel plus radius must stay below half the arena, so the minimum image of
    the start offset is unambiguous. At 30 units per tick against a 1000-unit arena there is an
    order of magnitude of headroom. If speeds ever approach it, substep the step instead:
    n = ceil((step + radius) / (w / 2)).
    """
    # Start offset, reduced across the torus. The displacement is used raw.
    ox, oy = geom.delta(px, py, sx, sy, w, h)

    a = dx * dx + dy * dy
    if a == 0.0:                                  # not moving: plain overlap test
        return 0.0 if ox * ox + oy * oy <= radius * radius else None

    # |offset + t*displacement|^2 = radius^2
    b = 2.0 * (ox * dx + oy * dy)
    c = ox * ox + oy * oy - radius * radius
    if c <= 0.0:
        # Already overlapping at the start of the step. Return immediately rather than
        # solving: if the exit root exceeds 1.0 the quadratic branch below reports a miss
        # for a round that spent the whole tick inside the disc.
        return 0.0
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    for t in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)):
        if 0.0 <= t <= 1.0:
            return t
    return None
