"""Fog of war.

Enforced BY CONSTRUCTION: each squadron's view is assembled from the union of its own cones.
Never build a full world state with a `visible` flag on it -- that is a one-line cheat.
"""

import itertools
from collections.abc import Mapping

from . import geom
from .state import Contact

QUANT_ANGLE = 2
"""Decimal places for bot-visible angles. Coarser than any cross-platform libm disagreement."""

QUANT_RANGE = 1
"""Decimal places for bot-visible ranges."""


def in_cone(ox: float, oy: float, heading_deg: float, cone_deg: float, cone_range: float,
            tx: float, ty: float, w: float, h: float) -> bool:
    """Whether (tx, ty) lies inside a cone of the given width and range.

    Both comparisons use QUANT-rounded values, for two reasons. `geom.distance` and
    `geom.bearing_to` bottom out in libm, which is not bit-identical across machines, so an
    unrounded boundary comparison could flip visibility between two people replaying the same
    match. And rounding here makes the decision agree exactly with the range and bearing a bot
    is told, so a contact reported at 899.9 in a 900-unit cone really is inside it.
    """
    if cone_deg <= 0.0 or cone_range <= 0.0:
        return False
    if round(geom.distance(ox, oy, tx, ty, w, h), QUANT_RANGE) > cone_range:
        return False
    bearing = round(geom.bearing_to(ox, oy, heading_deg, tx, ty, w, h), QUANT_ANGLE)
    return abs(bearing) <= cone_deg / 2.0


def sees(observer, target, arena: tuple[float, float]) -> bool:
    """Whether `observer` has `target` in either of its cones."""
    w, h = arena
    c = observer.cls
    if in_cone(observer.x, observer.y, observer.heading_deg, c.cone_deg, c.cone_range,
               target.x, target.y, w, h):
        return True
    # The rear cone is a separate frame rotated 180 degrees. Rotate the FRAME, never do
    # arithmetic on an already-wrapped bearing.
    return in_cone(observer.x, observer.y, observer.heading_deg + 180.0,
                   c.rear_cone_deg, c.rear_cone_range, target.x, target.y, w, h)


class ContactTracker:
    """Assigns contact ids that persist only while a target stays continuously visible.

    Re-acquisition mints a NEW id, so a scout that keeps eyes on a target is worth more than
    one that glances at it. Ids are per-squadron: two squadrons never share a contact id.
    """

    def __init__(self) -> None:
        self._assigned: dict[tuple[int, int], int] = {}
        self._counter = itertools.count(1)

    def update(self, squadron: int,
               visible_ids: tuple[int, ...]) -> tuple[dict[int, int], tuple[int, ...]]:
        """Returns (enemy plane id -> contact id, contact ids lost this tick)."""
        visible = set(visible_ids)
        lost = tuple(sorted(
            cid for (sq, pid), cid in self._assigned.items()
            if sq == squadron and pid not in visible
        ))
        for key in [k for k in self._assigned if k[0] == squadron and k[1] not in visible]:
            del self._assigned[key]
        mapping = {}
        for pid in sorted(visible):          # sorted: id allocation must not depend on set order
            key = (squadron, pid)
            if key not in self._assigned:
                self._assigned[key] = next(self._counter)
            mapping[pid] = self._assigned[key]
        return mapping, lost


def build_contacts(reader, seen: dict[int, tuple[int, ...]], enemies: Mapping[int, object],
                   ids: dict[int, int], arena: tuple[float, float]) -> tuple[Contact, ...]:
    """One reader plane's contact list.

    `seen` maps enemy plane id to the ids of MY planes that can see it -- the squadron union.
    Bearing and range are measured from THIS reader's nose, so the same enemy appears with
    different relative geometry to each of my planes, which is what makes the relative frame
    usable without any torus arithmetic in bot code.
    """
    w, h = arena
    out = []
    for pid in sorted(seen):                 # sorted: contact order must be deterministic
        e = enemies[pid]
        out.append(Contact(
            id=ids[pid],
            kind=e.kind,
            x=e.x,
            y=e.y,
            heading_deg=e.heading_deg,
            speed=e.speed,
            hp=e.hp,
            bearing_deg=round(geom.bearing_to(reader.x, reader.y, reader.heading_deg,
                                              e.x, e.y, w, h), QUANT_ANGLE),
            range=round(geom.distance(reader.x, reader.y, e.x, e.y, w, h), QUANT_RANGE),
            seen_by=seen[pid],
        ))
    return tuple(out)
