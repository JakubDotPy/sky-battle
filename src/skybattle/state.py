"""The types a bot sees and returns. This module is the API contract.

Within a major API version these types are ADDITIVE ONLY: append fields, never rename or
remove one, and give every new field a default meaning "no change".
"""

import random
from dataclasses import dataclass, field
from typing import NamedTuple

API_VERSION = 1


@dataclass(frozen=True, kw_only=True)
class Action:
    """One plane's controls for one tick.

    Composite because a real cockpit is: throttle in one hand, controls in the other hand and
    the feet, trigger under a finger, all at once.
    """

    throttle: float = 0.0
    """[0, 1] lever position. Sets thrust, NOT a target speed."""
    steer: float = 0.0
    """[-1, +1] control input. Positive steers left (counter-clockwise). Magnitude costs speed.

    Shares a sign with `Contact.bearing_deg`, so `steer = clamp(bearing_deg / k)` turns toward
    a contact with no negation.
    """
    fire: frozenset[int] = field(default_factory=frozenset)
    """Gun indices to fire this tick. Empty holds fire and costs nothing."""


class Gun(NamedTuple):
    name: str
    bearing_deg: float
    dispersion_deg: float
    """Precision, not a traverse: guns are fixed mounts, and each round scatters by a random
    amount inside this arc. Wider means less precise."""
    ammo: int
    cooldown_ticks_left: int
    muzzle_speed: float = 30.0
    """Appended, not inserted: the wire format is positional (see protocol.py), so a new field
    goes at the end. A bot needs this to compute a firing solution -- see samples/leader.py."""


class Contact(NamedTuple):
    """An enemy plane currently inside some squadron-mate's vision cone.

    Structurally distinct from OwnPlane, and the omissions are chosen. `hp` is exposed so a bot
    can prioritise a wounded target. `ammo` and `cooldown` are hidden: knowing an enemy is dry
    would make it free to approach.
    """

    id: int
    """Stable while continuously visible. A NEW id after re-acquisition, so keeping eyes on a
    target is worth more than glancing at it."""
    kind: str
    x: float
    y: float
    heading_deg: float
    speed: float
    hp: int
    bearing_deg: float
    range: float
    seen_by: tuple[int, ...]


class OwnPlane(NamedTuple):
    """A plane the bot commands. Never fogged."""

    id: int
    kind: str
    x: float
    y: float
    heading_deg: float
    speed: float
    hp: int
    hp_max: int
    stall_speed: float
    corner_speed: float
    max_speed: float
    guns: tuple[Gun, ...]
    contacts: tuple[Contact, ...] = ()
    """Enemies known to the squadron, with bearing and range measured from THIS plane's nose.

    The squadron shares knowledge instantly and perfectly, so every living plane gets the same
    contact ids; only the geometry differs per reader. `Contact.seen_by` says which of my
    planes actually has eyes on it, which is what makes a scout a scout.
    """


class HitByBullet(NamedTuple):
    plane_id: int
    from_squadron: int
    damage: int


class BulletHit(NamedTuple):
    plane_id: int
    gun: int
    target_id: int
    damage: int


class PlaneDestroyed(NamedTuple):
    plane_id: int
    by: int | None


class ContactLost(NamedTuple):
    contact_id: int


class ActionRejected(NamedTuple):
    plane_id: int
    reason: str


class View(NamedTuple):
    """Everything one squadron knows at the start of one tick."""

    tick: int
    arena: tuple[float, float]
    planes: tuple[OwnPlane, ...]
    events: tuple[object, ...]
    rng: random.Random | None = None
