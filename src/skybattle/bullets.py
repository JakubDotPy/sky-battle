"""Rounds in flight.

Enemy bullets are never visible to a bot: you infer incoming fire from being hit and from an
enemy's bearing. That is 31x cheaper to compute than exposing them and it is the better game.
"""

import random
from typing import NamedTuple

from . import geom
from .classes import GunSpec


class Bullet(NamedTuple):
    x: float
    y: float
    vx: float
    vy: float
    damage: int
    squadron: int
    owner_id: int
    gun: int
    ticks_left: int


def spawn(gun: GunSpec, gun_index: int, owner_id: int, squadron: int,
          x: float, y: float, heading_deg: float, speed: float,
          rng: random.Random) -> Bullet:
    """Fire one round.

    Guns are FIXED mounts: the round leaves along the mount's bearing, never aimed. What varies
    is precision -- each round deviates by a random amount inside the gun's dispersion arc, so a
    tighter gun groups better. The deviation comes from the ENGINE's RNG, never a bot's, so a
    match stays reproducible from its seed and a bot cannot predict its own scatter.

    The shooter's velocity is added as a VECTOR, not as a scalar along the firing direction.
    That distinction is the rear gun's whole character: a bomber running away throws its rear
    rounds SLOWER, because its own motion subtracts from the muzzle velocity -- a scalar add
    would instead make the rounds faster the harder the bomber runs, which is backwards. A
    forward gun still gets faster with speed either way, since there the two vectors point the
    same way.

    The round's lifetime is a tick count, not a distance, so a faster plane's rounds also fly
    further as well as arriving sooner (leading a target is harder): more ticks alive at a
    higher closing speed covers more ground.
    """
    spread = rng.uniform(-gun.dispersion_deg / 2.0, gun.dispersion_deg / 2.0)
    direction = geom.normalize_deg(heading_deg + gun.bearing_deg + spread)
    vx = geom.cos_deg(direction) * gun.muzzle_speed + geom.cos_deg(heading_deg) * speed
    vy = geom.sin_deg(direction) * gun.muzzle_speed + geom.sin_deg(heading_deg) * speed
    return Bullet(x=x, y=y, vx=vx, vy=vy,
                  damage=gun.damage, squadron=squadron, owner_id=owner_id, gun=gun_index,
                  ticks_left=gun.lifetime_ticks)


def advance(b: Bullet, arena: tuple[float, float]) -> Bullet | None:
    """Move one round one tick. None once it has expired."""
    if b.ticks_left <= 1:
        return None
    w, h = arena
    return b._replace(x=(b.x + b.vx) % w, y=(b.y + b.vy) % h, ticks_left=b.ticks_left - 1)
