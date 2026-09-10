"""Toroidal geometry and deterministic trigonometry.

Every engine trig call goes through the table here. `math.sin` and `math.atan2` route to the
platform libm and are not bit-identical across machines, which would make replays diverge
between the machines of two people comparing bots.
"""

import math

TRIG_STEPS = 4096
"""Headings are quantised to this many steps around the circle before a trig lookup."""

_TABLE_DP = 12
"""Table entries are rounded to this many decimal places.

The table exists to avoid libm, but it is built with libm, so its own entries would differ by
~1 ULP across platforms and that difference would reach simulated positions. Rounding to a
decimal string and back collapses any such disagreement to an identical double everywhere,
while leaving ~1e-12 of accuracy -- far more than this game needs.
"""

_SIN = tuple(round(math.sin(2.0 * math.pi * i / TRIG_STEPS), _TABLE_DP) for i in range(TRIG_STEPS))
_COS = tuple(round(math.cos(2.0 * math.pi * i / TRIG_STEPS), _TABLE_DP) for i in range(TRIG_STEPS))

# Exact values at the quarter turns; the table is off by ~1e-17 there and those four
# headings appear constantly (spawn orientations, rear guns), so pin them.
for _i, _s, _c in ((0, 0.0, 1.0), (TRIG_STEPS // 4, 1.0, 0.0),
                   (TRIG_STEPS // 2, 0.0, -1.0), (3 * TRIG_STEPS // 4, -1.0, 0.0)):
    _SIN = _SIN[:_i] + (_s,) + _SIN[_i + 1:]
    _COS = _COS[:_i] + (_c,) + _COS[_i + 1:]


def _index(deg: float) -> int:
    return round(normalize_deg(deg) * TRIG_STEPS / 360.0) % TRIG_STEPS


def sin_deg(deg: float) -> float:
    return _SIN[_index(deg)]


def cos_deg(deg: float) -> float:
    return _COS[_index(deg)]


def normalize_deg(deg: float) -> float:
    """An absolute angle in [0, 360)."""
    return deg % 360.0


def wrap_delta(d: float, length: float) -> float:
    """The shortest signed offset along one wrapped axis.

    The minimum image convention from periodic boundary conditions. Reduce to the shortest
    offset *first* and every downstream geometry routine works unmodified.
    """
    return (d + length / 2.0) % length - length / 2.0


def angle_diff(a: float, b: float) -> float:
    """Signed difference a - b in (-180, 180]. `wrap_delta` does double duty here."""
    d = wrap_delta(a - b, 360.0)
    return 180.0 if d == -180.0 else d


def delta(ax: float, ay: float, bx: float, by: float, w: float, h: float) -> tuple[float, float]:
    """The shortest vector from a to b across the torus."""
    return wrap_delta(bx - ax, w), wrap_delta(by - ay, h)


def distance(ax: float, ay: float, bx: float, by: float, w: float, h: float) -> float:
    dx, dy = delta(ax, ay, bx, by, w, h)
    return math.hypot(dx, dy)


def direction_to(ax: float, ay: float, bx: float, by: float, w: float, h: float) -> float:
    """Absolute heading from a toward b, in [0, 360). 0 = east, CCW positive."""
    dx, dy = delta(ax, ay, bx, by, w, h)
    return normalize_deg(math.degrees(math.atan2(dy, dx)))


def bearing_to(ax: float, ay: float, heading_deg: float,
               bx: float, by: float, w: float, h: float) -> float:
    """Bearing from a's nose toward b, in (-180, 180]. Negative is to the right.

    Rotate the *frame* and then wrap. Never wrap a bearing and then add to it: `angle_diff`
    maps onto (-180, 180], so an exactly-astern contact sits on the discontinuity and
    arithmetic on the wrapped value lands on the wrong side of it.

    This sign pairs with `Action.steer`, where positive steers left, so a bot can write
    `steer = clamp(contact.bearing_deg / k)` and turn toward a contact with no negation.
    """
    return angle_diff(direction_to(ax, ay, bx, by, w, h), heading_deg)
