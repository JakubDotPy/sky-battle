"""The flight model.

Kinematic, not force-driven: heading is commanded. Two mechanics carry the whole game.

Speed-coupled turn rate peaking at CORNER SPEED, so there is an optimum to discover rather
than a floor to sit on. And ENERGY BLEED: turning costs speed, so a bot that hauls its nose
around to get guns on target arrives slow, and slow cannot disengage. That trade replaced the
original assignment's turn-or-shoot constraint.
"""

from . import geom
from .classes import PlaneClass

DAMAGE_FLOOR = 0.7
"""Performance multiplier at zero hit points. A shot-up aeroplane flies worse."""


def damage_factor(hp: int, hp_max: int) -> float:
    return DAMAGE_FLOOR + (1.0 - DAMAGE_FLOOR) * (max(hp, 0) / hp_max)


def turn_rate_deg(cls: PlaneClass, speed: float, damage_factor: float) -> float:
    """Degrees per tick available at this speed. Piecewise linear through three points."""
    if speed <= cls.corner_speed:
        lo, hi = cls.stall_speed, cls.corner_speed
        a, b = cls.turn_at_stall, cls.turn_at_corner
    else:
        lo, hi = cls.corner_speed, cls.max_speed
        a, b = cls.turn_at_corner, cls.turn_at_max
    span = hi - lo
    t = 0.0 if span <= 0.0 else min(max((speed - lo) / span, 0.0), 1.0)
    return (a + (b - a) * t) * damage_factor


def step(cls: PlaneClass, x: float, y: float, heading_deg: float, speed: float,
         hp: int, hp_max: int, throttle: float, steer: float,
         arena: tuple[float, float]) -> tuple[float, float, float, float]:
    """Advance one plane one tick. Returns (x, y, heading_deg, speed)."""
    w, h = arena
    df = damage_factor(hp, hp_max)

    # Step 1 - turn. Rate depends on the speed we came in with.
    rate = turn_rate_deg(cls, speed, df)
    turned = rate * max(min(steer, 1.0), -1.0)
    heading_deg = geom.normalize_deg(heading_deg + turned)

    # Step 2 - thrust toward the commanded setting. Throttle is a lever position, so the
    # target it implies is a ceiling the plane approaches, not a speed it is granted.
    ceiling = cls.stall_speed + max(min(throttle, 1.0), 0.0) * (cls.max_speed * df - cls.stall_speed)
    if speed < ceiling:
        speed = min(speed + cls.accel, ceiling)
    elif speed > ceiling:
        speed = max(speed - cls.decel, ceiling)

    # Step 3 - energy bleed. Proportional to how hard we actually turned, which is why a
    # gentle turn is cheaper than a hard one and why continuous steer matters.
    speed -= cls.turn_bleed * abs(turned)

    # Step 4 - stall floor. The plane does not fall; it simply cannot go slower.
    speed = max(speed, cls.stall_speed)

    # Step 5 - translate, wrapping the torus.
    x = (x + geom.cos_deg(heading_deg) * speed) % w
    y = (y + geom.sin_deg(heading_deg) * speed) % h
    return x, y, heading_deg, speed
