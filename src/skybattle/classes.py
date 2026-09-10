"""The balance table. Humans write the TOML; the engine only reads it."""

import hashlib
import tomllib
from pathlib import Path
from typing import NamedTuple

DEFAULT_TABLE = Path(__file__).with_name("classes.toml")


class GunSpec(NamedTuple):
    name: str
    bearing_deg: float
    dispersion_deg: float
    cooldown_ticks: int
    damage: int
    ammo: int
    lifetime_ticks: int
    muzzle_speed: float


class PlaneClass(NamedTuple):
    name: str
    hp: int
    radius: float
    stall_speed: float
    corner_speed: float
    max_speed: float
    turn_at_stall: float
    turn_at_corner: float
    turn_at_max: float
    accel: float
    decel: float
    turn_bleed: float
    cone_deg: float
    cone_range: float
    rear_cone_deg: float
    rear_cone_range: float
    guns: tuple[GunSpec, ...]


def load_classes(path: Path | None = None,
                 arena: tuple[float, float] | None = None) -> dict[str, PlaneClass]:
    """Parse and validate the balance table.

    `arena` enables the cone-range check: on a torus a cone longer than half the shorter
    dimension lets a plane see the same enemy through both sides at once, and the fog stops
    meaning anything.
    """
    raw = tomllib.loads((path or DEFAULT_TABLE).read_text())
    out: dict[str, PlaneClass] = {}
    for name in sorted(raw):  # sorted: never rely on dict order from a parsed file
        body = raw[name]
        if "guns" not in body:
            raise ValueError(f"{name}: needs at least one [[{name}.guns]] block")
        guns = tuple(GunSpec(**g) for g in body.pop("guns"))
        if not guns:
            raise ValueError(f"{name}: needs at least one gun")
        try:
            cls = PlaneClass(name=name, guns=guns, **body)
        except TypeError as exc:
            raise ValueError(f"{name}: {exc}") from exc
        _check(cls, arena)
        out[name] = cls
    return out


def _check(c: PlaneClass, arena: tuple[float, float] | None) -> None:
    if c.radius <= 0:
        raise ValueError(f"{c.name}: radius must be > 0, got {c.radius}")
    if not c.stall_speed < c.corner_speed < c.max_speed:
        raise ValueError(f"{c.name}: need stall < corner < max, got "
                         f"{c.stall_speed} / {c.corner_speed} / {c.max_speed}")
    if c.turn_at_corner <= max(c.turn_at_stall, c.turn_at_max):
        raise ValueError(f"{c.name}: turn rate must peak at corner speed, got "
                         f"{c.turn_at_stall} / {c.turn_at_corner} / {c.turn_at_max} at "
                         f"stall / corner / max; otherwise flying at stall speed and "
                         f"pirouetting is the dominant strategy")
    if arena is not None:
        limit = min(arena) / 2.0
        for label, r in (("cone_range", c.cone_range), ("rear_cone_range", c.rear_cone_range)):
            if r > limit:
                raise ValueError(f"{c.name}: {label} {r} exceeds half the shorter arena "
                                 f"dimension ({limit}); fog would be meaningless")
    for g in c.guns:
        if g.dispersion_deg < 0:
            raise ValueError(f"{c.name}: gun {g.name!r} dispersion_deg must be >= 0, "
                             f"got {g.dispersion_deg}")
        if g.lifetime_ticks <= 0:
            raise ValueError(f"{c.name}: gun {g.name!r} lifetime_ticks must be > 0, "
                             f"got {g.lifetime_ticks}")
        if g.muzzle_speed <= 0:
            raise ValueError(f"{c.name}: gun {g.name!r} muzzle_speed must be > 0, "
                             f"got {g.muzzle_speed}")


def table_hash(path: Path | None = None) -> str:
    """Recorded in every replay header, so results are comparable only across identical tables."""
    return hashlib.sha256((path or DEFAULT_TABLE).read_bytes()).hexdigest()
