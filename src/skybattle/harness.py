"""Builders so a bot author can unit-test without the engine.

    def test_turns_toward_contact():
        state = make_state(planes=[plane(id=0, x=100, y=100, heading_deg=0.0,
                                         contacts=(contact(x=200, y=100, bearing_deg=0.0),))])
        assert act(state)[0].steer == 0.0

Every argument has a sane default, so a test names only what it cares about.
"""

import random

from .classes import load_classes
from .state import Contact, Gun, OwnPlane, View
from .validate import validate  # re-exported on purpose: one checker, engine and author alike

__all__ = ["contact", "gun", "make_state", "plane", "validate"]

_CLASSES = load_classes()


def gun(name: str = "forward", bearing_deg: float = 0.0, dispersion_deg: float = 2.0,
        ammo: int = 100, cooldown_ticks_left: int = 0, muzzle_speed: float = 30.0) -> Gun:
    return Gun(name=name, bearing_deg=bearing_deg, dispersion_deg=dispersion_deg, ammo=ammo,
               cooldown_ticks_left=cooldown_ticks_left, muzzle_speed=muzzle_speed)


def contact(id: int = 1, kind: str = "fighter", x: float = 200.0, y: float = 100.0,
            heading_deg: float = 0.0, speed: float = 4.0, hp: int = 100,
            bearing_deg: float = 0.0, range: float = 100.0,
            seen_by: tuple[int, ...] = (0,)) -> Contact:
    return Contact(id=id, kind=kind, x=x, y=y, heading_deg=heading_deg, speed=speed, hp=hp,
                   bearing_deg=bearing_deg, range=range, seen_by=seen_by)


def plane(id: int = 0, kind: str = "fighter", x: float = 100.0, y: float = 100.0,
          heading_deg: float = 0.0, speed: float | None = None, hp: int | None = None,
          contacts: tuple[Contact, ...] = ()) -> OwnPlane:
    """An own-plane with stats taken from the real class table, so tests cannot drift from it."""
    cls = _CLASSES[kind]
    return OwnPlane(
        id=id, kind=kind, x=x, y=y, heading_deg=heading_deg,
        speed=cls.corner_speed if speed is None else speed,
        hp=cls.hp if hp is None else hp, hp_max=cls.hp,
        stall_speed=cls.stall_speed, corner_speed=cls.corner_speed, max_speed=cls.max_speed,
        guns=tuple(gun(name=g.name, bearing_deg=g.bearing_deg,
                      dispersion_deg=g.dispersion_deg, ammo=g.ammo,
                      muzzle_speed=g.muzzle_speed)
                   for g in cls.guns),
        contacts=contacts,
        bubble_range=cls.bubble_range,
    )


def make_state(planes: list[OwnPlane] | None = None, tick: int = 1,
               arena: tuple[float, float] = (2000.0, 2000.0),
               events: tuple[object, ...] = (), seed: int = 1) -> View:
    return View(tick=tick, arena=arena,
                planes=tuple(planes if planes is not None else [plane()]),
                events=events, rng=random.Random(seed))
