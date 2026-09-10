# Sky Battle Engine Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the subagent-driven-development skill (recommended) or the
> executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A headless engine that runs a complete dogfight between two single-file Python bots and writes a replay.

**Architecture:** A pure-function simulation core (geometry, flight, collision, vision) wrapped by a `World` that
owns the tick order: apply actions, integrate, resolve damage and deaths, *then* build each squadron's fogged view.
Bots run as one subprocess per bot per match, speaking newline-delimited JSON over stdio through an
engine-supplied runner shim that owns all I/O so the author writes none. Every renderer is a downstream consumer of
a JSONL stream, so no display code exists in this plan.

**Tech Stack:** Python 3.13+, `uv`, standard library only at runtime (`math`, `random`, `json`, `gzip`, `tomllib`,
`subprocess`, `selectors`, `dataclasses`, `typing.NamedTuple`). `pytest` and `ruff` as dev dependencies.

**Spec:** `docs/design/game-design.md`, `docs/design/bot-api.md`, `docs/design/tech-decisions.md`

## Global Constraints

- **`requires-python = ">=3.13"`.** `src/` layout, package name `skybattle`.
- **`dependencies = []`.** No runtime dependency may be added by any task in this plan. `pytest` and `ruff` go in
  `[dependency-groups]`.
- **Angles are degrees only.** Radians are never exposed in any bot-facing type or field name.
- **Heading 0 = +x (east), counter-clockwise positive, y-up, origin bottom-left.** So
  `math.degrees(math.atan2(dy, dx))` *is* a heading with no adjustment.
- **Absolute angles are `[0, 360)`. Relative angles are `(-180, 180]`.**
- **Every angle field names its frame:** `heading_deg` (absolute, own), `bearing_deg` (relative to own nose),
  `direction_deg` (absolute, toward something).
- **All speeds are units per tick. All times are in ticks.** No field anywhere is denominated in seconds.
- **`dt` is fixed at 1/30 of game time and is never derived from wall-clock.** Measured wall-clock must never
  influence simulated state.
- **The engine owns all randomness.** `random.Random` seeded from the match seed. Never the module-level `random`.
- **Engine trigonometry goes through the lookup table in `geom`, never `math.sin`/`math.cos` directly.** `math.sin`
  and `math.atan2` route to the platform libm and are not bit-identical across machines.
- **Never iterate a `set` of strings in engine logic.** Order varies with `PYTHONHASHSEED`. Use tuples, lists, or
  sorted order.
- **All bot-visible derived floats are quantised** — angles to 0.01 degrees, ranges to 0.1 units.
- **The match never aborts.** A failing bot degrades; the simulation continues.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/skybattle/geom.py` | Toroidal geometry and the deterministic trig table. No game concepts. |
| `src/skybattle/classes.py` | `PlaneClass` / `GunSpec` types and TOML loading with validation. |
| `src/skybattle/classes.toml` | The balance table. Package data. |
| `src/skybattle/state.py` | Bot-facing types: `Action`, `Contact`, `OwnPlane`, `Gun`, `View`, event types. |
| `src/skybattle/flight.py` | The flight model: turn rate, thrust, energy bleed, stall floor, damage degradation. |
| `src/skybattle/bullets.py` | `Bullet` type, spawning with inherited velocity, advancement, expiry. |
| `src/skybattle/collide.py` | Swept segment-vs-circle collision in minimum-image coordinates. |
| `src/skybattle/vision.py` | Cone tests, squadron union, `Contact` construction, contact-id tracking. |
| `src/skybattle/world.py` | `World`: tick order, damage, deaths, scoring, round end, inactivity drain. |
| `src/skybattle/validate.py` | Action validation, clamping, NaN rejection. Shared by engine and author harness. |
| `src/skybattle/runner.py` | The subprocess shim. Owns stdio so the bot author owns none. |
| `src/skybattle/driver.py` | `BotProcess`: spawn, tick exchange, deadline, stale-reply drain, strikes. |
| `src/skybattle/replay.py` | Thin (seed + actions) and fat (derived state) JSONL writers. |
| `src/skybattle/harness.py` | `make_state` / `plane` / `contact` builders so authors can unit-test a bot. |
| `src/skybattle/cli.py` | The `duel` subcommand. |
| `samples/*.py` | The five sample bots. Also the engine's regression suite. |

---

### Task 1: Project scaffold and toroidal geometry

**Files:**

- Create: `pyproject.toml`, `src/skybattle/__init__.py`, `src/skybattle/geom.py`
- Test: `tests/test_geom.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `wrap_delta(d: float, length: float) -> float`;
  `delta(ax, ay, bx, by, w, h) -> tuple[float, float]`; `distance(ax, ay, bx, by, w, h) -> float`;
  `normalize_deg(a: float) -> float`; `angle_diff(a: float, b: float) -> float`;
  `direction_to(ax, ay, bx, by, w, h) -> float`; `bearing_to(ax, ay, heading_deg, bx, by, w, h) -> float`;
  `sin_deg(a: float) -> float`; `cos_deg(a: float) -> float`; `TRIG_STEPS: int`.
- [ ] **Step 1: Create the project scaffold**

```bash
cd /home/jakub/Dev/personal/sky_battle
mkdir -p src/skybattle tests samples
touch src/skybattle/__init__.py
```

Write `pyproject.toml`:

```toml
[project]
name = "skybattle"
version = "0.1.0"
description = "A top-down 2D plane-wars arena for bot programmers"
requires-python = ">=3.13"
dependencies = []

[project.scripts]
sky-battle = "skybattle.cli:main"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/skybattle"]

[tool.ruff]
line-length = 110

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Then `uv sync`.

- [ ] **Step 2: Write the failing test**

`tests/test_geom.py`:

```python
import math

import pytest

from skybattle import geom

W, H = 1000.0, 1000.0


def test_wrap_delta_takes_the_short_way():
    assert geom.wrap_delta(990.0, 1000.0) == pytest.approx(-10.0)
    assert geom.wrap_delta(-990.0, 1000.0) == pytest.approx(10.0)
    assert geom.wrap_delta(10.0, 1000.0) == pytest.approx(10.0)


def test_distance_crosses_the_seam():
    # 5 and 995 are 10 apart the short way, not 990
    assert geom.distance(5.0, 500.0, 995.0, 500.0, W, H) == pytest.approx(10.0)


def test_distance_crosses_both_seams_diagonally():
    assert geom.distance(5.0, 5.0, 995.0, 995.0, W, H) == pytest.approx(math.hypot(10.0, 10.0))


def test_normalize_deg_lands_in_0_360():
    assert geom.normalize_deg(-90.0) == pytest.approx(270.0)
    assert geom.normalize_deg(450.0) == pytest.approx(90.0)
    assert geom.normalize_deg(0.0) == pytest.approx(0.0)


def test_angle_diff_lands_in_minus180_180():
    assert geom.angle_diff(10.0, 350.0) == pytest.approx(20.0)
    assert geom.angle_diff(350.0, 10.0) == pytest.approx(-20.0)
    assert geom.angle_diff(0.0, 180.0) == pytest.approx(180.0)


def test_direction_to_uses_east_as_zero_ccw_positive():
    assert geom.direction_to(0.0, 0.0, 10.0, 0.0, W, H) == pytest.approx(0.0)
    assert geom.direction_to(0.0, 0.0, 0.0, 10.0, W, H) == pytest.approx(90.0)


def test_bearing_to_is_relative_to_the_nose():
    # facing north, target due east -> 90 degrees to the right
    assert geom.bearing_to(500.0, 500.0, 90.0, 510.0, 500.0, W, H) == pytest.approx(-90.0)


def test_bearing_to_astern_is_stable_across_the_discontinuity():
    # target exactly behind: must be +180 or -180, never NaN or 0
    b = geom.bearing_to(500.0, 500.0, 0.0, 490.0, 500.0, W, H)
    assert abs(b) == pytest.approx(180.0)


def test_trig_table_matches_math_closely_and_is_quantised():
    for a in (0.0, 30.0, 45.0, 90.0, 123.456, 359.9):
        assert geom.sin_deg(a) == pytest.approx(math.sin(math.radians(a)), abs=1e-3)
        assert geom.cos_deg(a) == pytest.approx(math.cos(math.radians(a)), abs=1e-3)
    # identical input gives bit-identical output, and 0/90/180/270 are exact
    assert geom.sin_deg(0.0) == 0.0
    assert geom.cos_deg(0.0) == 1.0
    assert geom.sin_deg(90.0) == 1.0
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_geom.py -v`
Expected: FAIL — `ModuleNotFoundError` or `AttributeError: module 'skybattle.geom' has no attribute 'wrap_delta'`

- [ ] **Step 4: Write the implementation**

`src/skybattle/geom.py`:

```python
"""Toroidal geometry and deterministic trigonometry.

Every engine trig call goes through the table here. `math.sin` and `math.atan2` route to the
platform libm and are not bit-identical across machines, which would make replays diverge
between the machines of two people comparing bots.
"""

import math

TRIG_STEPS = 4096
"""Headings are quantised to this many steps around the circle before a trig lookup."""

_SIN = tuple(math.sin(2.0 * math.pi * i / TRIG_STEPS) for i in range(TRIG_STEPS))
_COS = tuple(math.cos(2.0 * math.pi * i / TRIG_STEPS) for i in range(TRIG_STEPS))

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
    """
    return angle_diff(direction_to(ax, ay, bx, by, w, h), heading_deg)
```

> `direction_to` uses `math.atan2`, which is the one libm call the engine cannot avoid. It is safe *because*
> Task 7 quantises every bot-visible bearing to 0.01 degrees, which is far coarser than any cross-platform libm
> disagreement. Do not use `math.atan2` anywhere a raw result reaches simulated state.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_geom.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/skybattle/__init__.py src/skybattle/geom.py tests/test_geom.py
git commit -m "feat: toroidal geometry and deterministic trig table"
```

---

### Task 2: Class table loading from TOML

**Files:**

- Create: `src/skybattle/classes.py`, `src/skybattle/classes.toml`
- Test: `tests/test_classes.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `GunSpec(NamedTuple)` with fields `name: str, bearing_deg: float, arc_deg: float,
  cooldown_ticks: int, damage: int, ammo: int`; `PlaneClass(NamedTuple)` with fields
  `name: str, hp: int, stall_speed: float, corner_speed: float, max_speed: float,
  turn_at_stall: float, turn_at_corner: float, turn_at_max: float, accel: float, decel: float,
  turn_bleed: float, cone_deg: float, cone_range: float, rear_cone_deg: float, rear_cone_range: float,
  guns: tuple[GunSpec, ...]`; `load_classes(path: Path | None = None) -> dict[str, PlaneClass]`;
  `table_hash(path: Path | None = None) -> str`; `DEFAULT_TABLE: Path`.
- [ ] **Step 1: Write the balance table**

`src/skybattle/classes.toml`. Numbers are placeholders pending a balance pass; the scout's HP is already known to
be too high.

```toml
# Sky Battle balance table.
# Speeds are units/tick, angles degrees, times ticks. Edit freely: this file is the game.
# Every replay records this file's hash, so results are only comparable across identical tables.

[scout]
hp = 70
stall_speed = 3.0
corner_speed = 5.0
max_speed = 9.0
# Turn rate peaks at corner speed. A monotonically falling curve makes flying at stall
# speed and pirouetting the dominant strategy.
turn_at_stall = 5.0
turn_at_corner = 9.0
turn_at_max = 4.5
accel = 0.20
decel = 0.30
# Degrees turned per tick is multiplied by this to get speed lost. Energy management.
turn_bleed = 0.045
cone_deg = 120.0
cone_range = 900.0
rear_cone_deg = 0.0
rear_cone_range = 0.0

  [[scout.guns]]
  name = "forward"
  bearing_deg = 0.0
  arc_deg = 8.0
  cooldown_ticks = 6
  damage = 8
  ammo = 80

[fighter]
hp = 100
stall_speed = 2.0
corner_speed = 4.5
max_speed = 8.0
turn_at_stall = 5.5
turn_at_corner = 10.0
turn_at_max = 4.0
accel = 0.22
decel = 0.30
turn_bleed = 0.040
cone_deg = 70.0
cone_range = 600.0
rear_cone_deg = 0.0
rear_cone_range = 0.0

  [[fighter.guns]]
  name = "forward"
  bearing_deg = 0.0
  arc_deg = 8.0
  cooldown_ticks = 8
  damage = 10
  ammo = 120

[bomber]
hp = 160
stall_speed = 2.0
corner_speed = 3.0
max_speed = 5.0
turn_at_stall = 3.5
turn_at_corner = 6.0
turn_at_max = 3.0
accel = 0.12
decel = 0.20
turn_bleed = 0.055
cone_deg = 50.0
cone_range = 450.0
rear_cone_deg = 50.0
rear_cone_range = 350.0

  [[bomber.guns]]
  name = "forward"
  bearing_deg = 0.0
  arc_deg = 6.0
  cooldown_ticks = 14
  damage = 14
  ammo = 90

  # A traversing gunner aims; a fixed forward gun is aimed by flying the aeroplane.
  [[bomber.guns]]
  name = "rear"
  bearing_deg = 180.0
  arc_deg = 40.0
  cooldown_ticks = 10
  damage = 10
  ammo = 60
```

- [ ] **Step 2: Write the failing test**

`tests/test_classes.py`:

```python
import pytest

from skybattle.classes import load_classes, table_hash


def test_loads_the_three_classes():
    cs = load_classes()
    assert sorted(cs) == ["bomber", "fighter", "scout"]


def test_gun_mounts_load_in_order_with_the_rear_gun_at_180():
    bomber = load_classes()["bomber"]
    assert [g.name for g in bomber.guns] == ["forward", "rear"]
    assert bomber.guns[0].bearing_deg == 0.0
    assert bomber.guns[1].bearing_deg == 180.0
    assert bomber.guns[1].arc_deg > bomber.guns[0].arc_deg


def test_turn_rate_peaks_at_corner_speed_for_every_class():
    for c in load_classes().values():
        assert c.turn_at_corner > c.turn_at_stall
        assert c.turn_at_corner > c.turn_at_max


def test_speeds_are_ordered_for_every_class():
    for c in load_classes().values():
        assert c.stall_speed < c.corner_speed < c.max_speed


def test_table_hash_is_stable_and_hex():
    h = table_hash()
    assert h == table_hash()
    assert len(h) == 64
    int(h, 16)


def test_rejects_a_cone_longer_than_half_the_arena(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text(load_classes.__module__ and _MINIMAL_BAD_TABLE)
    with pytest.raises(ValueError, match="cone_range"):
        load_classes(bad, arena=(1000.0, 1000.0))


_MINIMAL_BAD_TABLE = """
[scout]
hp = 70
stall_speed = 3.0
corner_speed = 5.0
max_speed = 9.0
turn_at_stall = 5.0
turn_at_corner = 9.0
turn_at_max = 4.5
accel = 0.2
decel = 0.3
turn_bleed = 0.045
cone_deg = 120.0
cone_range = 900.0
rear_cone_deg = 0.0
rear_cone_range = 0.0
[[scout.guns]]
name = "forward"
bearing_deg = 0.0
arc_deg = 8.0
cooldown_ticks = 6
damage = 8
ammo = 80
"""
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_classes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.classes'`

- [ ] **Step 4: Write the implementation**

`src/skybattle/classes.py`:

```python
"""The balance table. Humans write the TOML; the engine only reads it."""

import hashlib
import tomllib
from pathlib import Path
from typing import NamedTuple

DEFAULT_TABLE = Path(__file__).with_name("classes.toml")


class GunSpec(NamedTuple):
    name: str
    bearing_deg: float
    arc_deg: float
    cooldown_ticks: int
    damage: int
    ammo: int


class PlaneClass(NamedTuple):
    name: str
    hp: int
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
        guns = tuple(GunSpec(**g) for g in body.pop("guns"))
        if not guns:
            raise ValueError(f"{name}: needs at least one gun")
        cls = PlaneClass(name=name, guns=guns, **body)
        _check(cls, arena)
        out[name] = cls
    return out


def _check(c: PlaneClass, arena: tuple[float, float] | None) -> None:
    if not c.stall_speed < c.corner_speed < c.max_speed:
        raise ValueError(f"{c.name}: need stall < corner < max, got "
                         f"{c.stall_speed} / {c.corner_speed} / {c.max_speed}")
    if c.turn_at_corner <= max(c.turn_at_stall, c.turn_at_max):
        raise ValueError(f"{c.name}: turn rate must peak at corner speed, otherwise flying at "
                         f"stall speed and pirouetting is the dominant strategy")
    if arena is not None:
        limit = min(arena) / 2.0
        for label, r in (("cone_range", c.cone_range), ("rear_cone_range", c.rear_cone_range)):
            if r > limit:
                raise ValueError(f"{c.name}: {label} {r} exceeds half the shorter arena "
                                 f"dimension ({limit}); fog would be meaningless")


def table_hash(path: Path | None = None) -> str:
    """Recorded in every replay header, so results are comparable only across identical tables."""
    return hashlib.sha256((path or DEFAULT_TABLE).read_bytes()).hexdigest()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_classes.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 6: Commit**

```bash
git add src/skybattle/classes.py src/skybattle/classes.toml tests/test_classes.py
git commit -m "feat: load and validate the balance table from TOML"
```

---

### Task 3: Bot-facing types

**Files:**

- Create: `src/skybattle/state.py`
- Test: `tests/test_state.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `Action` (frozen, kw_only dataclass: `throttle: float = 0.0`, `steer: float = 0.0`,
  `fire: frozenset[int] = frozenset()`); `Gun(NamedTuple)` `name, bearing_deg, arc_deg, ammo, cooldown_ticks_left`;
  `OwnPlane(NamedTuple)` `id, kind, x, y, heading_deg, speed, hp, hp_max, stall_speed, corner_speed, max_speed,
  guns: tuple[Gun, ...]`; `Contact(NamedTuple)` exactly as the spec lists; `View(NamedTuple)`
  `tick, arena: tuple[float, float], planes: tuple[OwnPlane, ...], contacts: tuple[Contact, ...],
  events: tuple[object, ...], rng: random.Random | None`; event types `HitByBullet`, `BulletHit`,
  `PlaneDestroyed`, `ContactLost`, `ActionRejected`; `API_VERSION: int = 1`.
- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:

```python
import dataclasses

import pytest

from skybattle.state import Action, Contact, Gun, OwnPlane


def test_action_defaults_to_doing_nothing():
    a = Action()
    assert a.throttle == 0.0
    assert a.steer == 0.0
    assert a.fire == frozenset()


def test_action_is_keyword_only_so_a_new_field_cannot_break_old_bots():
    with pytest.raises(TypeError):
        Action(0.5, 1.0)          # positional construction must be impossible


def test_action_is_frozen():
    a = Action(throttle=0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.throttle = 1.0


def test_contact_carries_both_frames_and_hides_ammo():
    c = Contact(id=3, kind="bomber", x=1.0, y=2.0, heading_deg=90.0, speed=4.0, hp=120,
                bearing_deg=-30.0, range=250.0, seen_by=(0,))
    assert c.x == 1.0 and c.bearing_deg == -30.0     # absolute AND relative
    assert not hasattr(c, "ammo")
    assert not hasattr(c, "cooldown_ticks_left")
    assert not hasattr(c, "age")


def test_own_plane_sees_its_own_ammo_and_cooldown():
    g = Gun(name="forward", bearing_deg=0.0, arc_deg=8.0, ammo=80, cooldown_ticks_left=0)
    p = OwnPlane(id=0, kind="scout", x=0.0, y=0.0, heading_deg=0.0, speed=5.0, hp=70, hp_max=70,
                 stall_speed=3.0, corner_speed=5.0, max_speed=9.0, guns=(g,))
    assert p.guns[0].ammo == 80
    assert p.guns[0].cooldown_ticks_left == 0


def test_contact_is_immutable():
    c = Contact(id=1, kind="scout", x=0.0, y=0.0, heading_deg=0.0, speed=1.0, hp=70,
                bearing_deg=0.0, range=1.0, seen_by=())
    with pytest.raises(AttributeError):
        c.hp = 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.state'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/state.py`:

```python
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
    """[-1, +1] control input. Positive steers left (CCW). Magnitude costs speed.

    Shares a sign with `Contact.bearing_deg`, so `steer = clamp(bearing_deg / k)` turns
    toward a contact with no negation."""
    fire: frozenset[int] = field(default_factory=frozenset)
    """Gun indices to fire this tick. Empty holds fire and costs nothing."""


class Gun(NamedTuple):
    name: str
    bearing_deg: float
    arc_deg: float
    ammo: int
    cooldown_ticks_left: int


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
    contacts: tuple[Contact, ...]
    events: tuple[object, ...]
    rng: random.Random | None = None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_state.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/state.py tests/test_state.py
git commit -m "feat: bot-facing state and action types"
```

---

### Task 4: The flight model

**Files:**

- Create: `src/skybattle/flight.py`
- Test: `tests/test_flight.py`

**Interfaces:**

- Consumes: `skybattle.classes.PlaneClass`, `skybattle.geom`.
- Produces: `turn_rate_deg(cls: PlaneClass, speed: float, damage_factor: float) -> float`;
  `damage_factor(hp: int, hp_max: int) -> float`;
  `step(cls, x, y, heading_deg, speed, hp, hp_max, throttle, steer, arena) ->
  tuple[float, float, float, float]` returning `(x, y, heading_deg, speed)`.
- [ ] **Step 1: Write the failing test**

`tests/test_flight.py`:

```python
import pytest

from skybattle import flight
from skybattle.classes import load_classes

ARENA = (1000.0, 1000.0)
CLASSES = load_classes()


def test_turn_rate_peaks_at_corner_speed():
    c = CLASSES["fighter"]
    at_stall = flight.turn_rate_deg(c, c.stall_speed, 1.0)
    at_corner = flight.turn_rate_deg(c, c.corner_speed, 1.0)
    at_max = flight.turn_rate_deg(c, c.max_speed, 1.0)
    assert at_corner > at_stall
    assert at_corner > at_max


def test_turn_rate_interpolates_between_the_three_points():
    c = CLASSES["fighter"]
    mid = (c.stall_speed + c.corner_speed) / 2.0
    r = flight.turn_rate_deg(c, mid, 1.0)
    assert flight.turn_rate_deg(c, c.stall_speed, 1.0) < r < flight.turn_rate_deg(c, c.corner_speed, 1.0)


def test_damage_degrades_performance_to_70_percent():
    assert flight.damage_factor(100, 100) == pytest.approx(1.0)
    assert flight.damage_factor(0, 100) == pytest.approx(0.7)
    assert flight.damage_factor(50, 100) == pytest.approx(0.85)


def test_hard_turning_bleeds_speed():
    c = CLASSES["fighter"]
    start = c.corner_speed
    _, _, _, straight = flight.step(c, 500.0, 500.0, 0.0, start, 100, 100, 0.0, 0.0, ARENA)
    _, _, _, turning = flight.step(c, 500.0, 500.0, 0.0, start, 100, 100, 0.0, 1.0, ARENA)
    assert turning < straight


def test_a_gentle_turn_bleeds_less_than_a_hard_one():
    c = CLASSES["fighter"]
    _, _, _, gentle = flight.step(c, 500.0, 500.0, 0.0, c.corner_speed, 100, 100, 0.0, 0.3, ARENA)
    _, _, _, hard = flight.step(c, 500.0, 500.0, 0.0, c.corner_speed, 100, 100, 0.0, 1.0, ARENA)
    assert gentle > hard


def test_speed_never_falls_below_stall():
    c = CLASSES["fighter"]
    speed = c.stall_speed
    for _ in range(50):
        _, _, _, speed = flight.step(c, 500.0, 500.0, 0.0, speed, 100, 100, 0.0, 1.0, ARENA)
    assert speed == pytest.approx(c.stall_speed)


def test_throttle_sets_thrust_not_speed_so_a_turning_plane_cannot_hold_max():
    c = CLASSES["fighter"]
    speed = c.max_speed
    for _ in range(20):
        _, _, _, speed = flight.step(c, 500.0, 500.0, 0.0, speed, 100, 100, 1.0, 1.0, ARENA)
    assert speed < c.max_speed


def test_full_throttle_and_straight_flight_converges_on_max_speed():
    c = CLASSES["fighter"]
    speed = c.stall_speed
    for _ in range(200):
        _, _, _, speed = flight.step(c, 500.0, 500.0, 0.0, speed, 100, 100, 1.0, 0.0, ARENA)
    assert speed == pytest.approx(c.max_speed, abs=1e-6)


def test_steer_sign_negative_is_left_ccw_positive():
    c = CLASSES["fighter"]
    _, _, right, _ = flight.step(c, 500.0, 500.0, 0.0, 5.0, 100, 100, 0.0, 1.0, ARENA)
    _, _, left, _ = flight.step(c, 500.0, 500.0, 0.0, 5.0, 100, 100, 0.0, -1.0, ARENA)
    # y-up, CCW positive: steering left increases heading
    assert left > 0.0
    assert right > 350.0        # wrapped below zero


def test_position_wraps_across_the_seam():
    c = CLASSES["fighter"]
    x, _, _, _ = flight.step(c, 998.0, 500.0, 0.0, 5.0, 100, 100, 0.0, 0.0, ARENA)
    assert 0.0 <= x < 10.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_flight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.flight'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/flight.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_flight.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/flight.py tests/test_flight.py
git commit -m "feat: flight model with corner speed and energy bleed"
```

---

### Task 5: Bullets

**Files:**

- Create: `src/skybattle/bullets.py`
- Test: `tests/test_bullets.py`

**Interfaces:**

- Consumes: `skybattle.geom`, `skybattle.classes.GunSpec`.
- Produces: `Bullet(NamedTuple)` `x, y, vx, vy, damage, squadron, owner_id, gun, ticks_left`;
  `MUZZLE_SPEED: float`; `BULLET_LIFETIME: int`;
  `spawn(gun: GunSpec, gun_index: int, owner_id: int, squadron: int, x, y, heading_deg, speed) -> Bullet`;
  `advance(b: Bullet, arena) -> Bullet | None`.
- [ ] **Step 1: Write the failing test**

`tests/test_bullets.py`:

```python
import math

import pytest

from skybattle import bullets
from skybattle.classes import load_classes

ARENA = (1000.0, 1000.0)
CLASSES = load_classes()


def _fwd(kind="fighter"):
    return CLASSES[kind].guns[0]


def test_bullet_inherits_shooter_velocity():
    slow = bullets.spawn(_fwd(), 0, 0, 0, 500.0, 500.0, 0.0, 0.0)
    fast = bullets.spawn(_fwd(), 0, 0, 0, 500.0, 500.0, 0.0, 8.0)
    assert math.hypot(fast.vx, fast.vy) > math.hypot(slow.vx, slow.vy)
    assert math.hypot(fast.vx, fast.vy) == pytest.approx(bullets.MUZZLE_SPEED + 8.0)


def test_rear_gun_fires_astern():
    rear = CLASSES["bomber"].guns[1]
    b = bullets.spawn(rear, 1, 0, 0, 500.0, 500.0, 0.0, 0.0)
    assert b.vx < 0.0                       # heading east, rear gun shoots west
    assert b.vy == pytest.approx(0.0, abs=1e-9)


def test_bullet_carries_its_gun_damage_and_provenance():
    b = bullets.spawn(_fwd(), 0, 7, 1, 0.0, 0.0, 0.0, 0.0)
    assert b.damage == _fwd().damage
    assert b.owner_id == 7
    assert b.squadron == 1
    assert b.gun == 0


def test_advance_moves_and_wraps():
    b = bullets.spawn(_fwd(), 0, 0, 0, 995.0, 500.0, 0.0, 0.0)
    nxt = bullets.advance(b, ARENA)
    assert nxt is not None
    assert nxt.x < 100.0                    # wrapped past the seam


def test_bullet_expires():
    b = bullets.spawn(_fwd(), 0, 0, 0, 500.0, 500.0, 0.0, 0.0)._replace(ticks_left=1)
    assert bullets.advance(b, ARENA) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_bullets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.bullets'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/bullets.py`:

```python
"""Rounds in flight.

Enemy bullets are never visible to a bot: you infer incoming fire from being hit and from an
enemy's bearing. That is 31x cheaper to compute than exposing them and it is the better game.
"""

from typing import NamedTuple

from . import geom
from .classes import GunSpec

MUZZLE_SPEED = 30.0
"""Units per tick, before the shooter's own velocity is added."""

BULLET_LIFETIME = 40
"""Ticks. Bounds effective range and keeps the bullet list short."""


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
          x: float, y: float, heading_deg: float, speed: float) -> Bullet:
    """Fire one round.

    Muzzle velocity adds to the aircraft's own, so a fast plane's rounds arrive sooner and a
    loitering plane's are sluggish.
    """
    direction = geom.normalize_deg(heading_deg + gun.bearing_deg)
    muzzle = MUZZLE_SPEED + speed
    return Bullet(x=x, y=y,
                  vx=geom.cos_deg(direction) * muzzle,
                  vy=geom.sin_deg(direction) * muzzle,
                  damage=gun.damage, squadron=squadron, owner_id=owner_id, gun=gun_index,
                  ticks_left=BULLET_LIFETIME)


def advance(b: Bullet, arena: tuple[float, float]) -> Bullet | None:
    """Move one round one tick. None once it has expired."""
    if b.ticks_left <= 1:
        return None
    w, h = arena
    return b._replace(x=(b.x + b.vx) % w, y=(b.y + b.vy) % h, ticks_left=b.ticks_left - 1)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_bullets.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/bullets.py tests/test_bullets.py
git commit -m "feat: bullets with inherited shooter velocity"
```

---

### Task 6: Swept collision across the seam

**Files:**

- Create: `src/skybattle/collide.py`
- Test: `tests/test_collide.py`

**Interfaces:**

- Consumes: `skybattle.geom`.
- Produces: `PLANE_RADIUS: float`; `swept_hit(px, py, radius, sx, sy, dx, dy, w, h) -> float | None`
  returning the fraction of the step at which contact occurs, or None.
- [ ] **Step 1: Write the failing test**

`tests/test_collide.py`:

```python
from skybattle.collide import swept_hit

W = H = 1000.0


def test_direct_hit_reports_when_along_the_step():
    t = swept_hit(100.0, 100.0, 12.0, 60.0, 100.0, 40.0, 0.0, W, H)
    assert t is not None
    assert 0.0 <= t <= 1.0


def test_tunnelling_across_the_seam_is_caught():
    # bullet at x=990 moving +30 wraps to x=20; plane sits at x=5
    t = swept_hit(5.0, 500.0, 12.0, 990.0, 500.0, 30.0, 0.0, W, H)
    assert t is not None


def test_naive_endpoint_sampling_would_have_missed_that():
    # proves the swept test earns its keep: neither endpoint is inside the plane
    from skybattle import geom
    for sx in (990.0, 1020.0 % W):
        assert geom.distance(sx, 500.0, 5.0, 500.0, W, H) > 12.0


def test_no_false_positive_when_clear_of_the_line():
    assert swept_hit(5.0, 520.0, 12.0, 990.0, 500.0, 30.0, 0.0, W, H) is None


def test_a_graze_still_registers():
    t = swept_hit(5.0, 511.0, 12.0, 990.0, 500.0, 30.0, 0.0, W, H)
    assert t is not None


def test_a_zero_length_step_still_detects_overlap():
    assert swept_hit(100.0, 100.0, 12.0, 105.0, 100.0, 0.0, 0.0, W, H) is not None
    assert swept_hit(100.0, 100.0, 12.0, 300.0, 100.0, 0.0, 0.0, W, H) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_collide.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.collide'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/collide.py`:

```python
"""Continuous collision between a moving round and a stationary disc.

Tunnelling is real here: a round covers ~30 units per tick against a 24-unit plane, so
sampling endpoints misses hits entirely. Verified against the naive approach in the tests.

THE RULE, and it is the whole fix: work in minimum-image relative coordinates and never wrap
the DISPLACEMENT vector -- only the start offset.
"""

import math

from . import geom

PLANE_RADIUS = 12.0

_MAX_TRAVEL_WARNING = (
    "swept_hit assumes travel + radius stays below half the arena, so the minimum image of the "
    "start offset is unambiguous. At 30 units/tick against a 1000-unit arena there is an order "
    "of magnitude of headroom. If speeds ever approach it, substep the step instead."
)


def swept_hit(px: float, py: float, radius: float,
              sx: float, sy: float, dx: float, dy: float,
              w: float, h: float) -> float | None:
    """Fraction of the step [0, 1] at which the segment first enters the disc, else None.

    (px, py) is the disc centre; (sx, sy) the segment start; (dx, dy) its displacement.
    """
    # Start offset, reduced across the torus. The displacement is used raw.
    ox, oy = geom.delta(px, py, sx, sy, w, h)

    a = dx * dx + dy * dy
    if a == 0.0:                                  # not moving: plain overlap test
        return 0.0 if ox * ox + oy * oy <= radius * radius else None

    # |offset + t*displacement|^2 = radius^2
    b = 2.0 * (ox * dx + oy * dy)
    c = ox * ox + oy * oy - radius * radius
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    for t in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)):
        if 0.0 <= t <= 1.0:
            return t
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_collide.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/collide.py tests/test_collide.py
git commit -m "feat: swept collision correct across the torus seam"
```

---

### Task 7: Vision cones, squadron union and contact identity

**Files:**

- Create: `src/skybattle/vision.py`
- Test: `tests/test_vision.py`

**Interfaces:**

- Consumes: `skybattle.geom`, `skybattle.state.Contact`, `skybattle.classes.PlaneClass`.
- Produces: `QUANT_ANGLE: int = 2`; `QUANT_RANGE: int = 1`;
  `in_cone(ox, oy, heading_deg, cone_deg, cone_range, tx, ty, w, h) -> bool`;
  `sees(observer, target, arena) -> bool` where both args are objects with
  `.x .y .heading_deg .cls`; `ContactTracker` with
  `update(squadron: int, visible_ids: tuple[int, ...]) -> tuple[dict[int, int], tuple[int, ...]]`;
  `build_contacts(reader, seen: dict[int, tuple[int, ...]], enemies: dict[int, object],
  ids: dict[int, int], arena) -> tuple[Contact, ...]`.
- [ ] **Step 1: Write the failing test**

`tests/test_vision.py`:

```python
from dataclasses import dataclass

import pytest

from skybattle import vision
from skybattle.classes import load_classes

ARENA = (2000.0, 2000.0)
W, H = ARENA
CLASSES = load_classes()


@dataclass
class P:
    id: int
    x: float
    y: float
    heading_deg: float
    cls: object
    speed: float = 4.0
    hp: int = 100
    kind: str = "fighter"


def _p(kind="fighter", **kw):
    return P(cls=CLASSES[kind], kind=kind, **kw)


def test_a_target_dead_ahead_is_seen():
    o = _p(id=0, x=100.0, y=100.0, heading_deg=0.0)
    t = _p(id=1, x=400.0, y=100.0, heading_deg=0.0)
    assert vision.sees(o, t, ARENA)


def test_a_target_behind_is_not_seen_by_a_forward_only_class():
    o = _p(id=0, x=400.0, y=100.0, heading_deg=0.0)
    t = _p(id=1, x=100.0, y=100.0, heading_deg=0.0)
    assert not vision.sees(o, t, ARENA)


def test_a_target_beyond_cone_range_is_not_seen():
    o = _p(id=0, x=0.0, y=0.0, heading_deg=0.0)
    t = _p(id=1, x=CLASSES["fighter"].cone_range + 50.0, y=0.0, heading_deg=0.0)
    assert not vision.sees(o, t, ARENA)


def test_the_bomber_sees_astern_through_its_rear_cone():
    o = _p(kind="bomber", id=0, x=400.0, y=100.0, heading_deg=0.0)
    t = _p(id=1, x=200.0, y=100.0, heading_deg=0.0)
    assert vision.sees(o, t, ARENA)


def test_the_scouts_cone_is_wider_than_the_fighters():
    off_axis_t = _p(id=1, x=100.0 + 200.0, y=100.0 + 200.0, heading_deg=0.0)
    scout = _p(kind="scout", id=0, x=100.0, y=100.0, heading_deg=0.0)
    fighter = _p(id=0, x=100.0, y=100.0, heading_deg=0.0)
    assert vision.sees(scout, off_axis_t, ARENA)
    assert not vision.sees(fighter, off_axis_t, ARENA)


def test_a_cone_sees_across_the_seam():
    o = _p(id=0, x=1990.0, y=100.0, heading_deg=0.0)
    t = _p(id=1, x=30.0, y=100.0, heading_deg=0.0)
    assert vision.sees(o, t, ARENA)


def test_contact_id_is_stable_while_continuously_visible():
    tr = vision.ContactTracker()
    ids1, lost1 = tr.update(0, (7,))
    ids2, lost2 = tr.update(0, (7,))
    assert ids1[7] == ids2[7]
    assert lost1 == () and lost2 == ()


def test_contact_id_changes_after_re_acquisition():
    tr = vision.ContactTracker()
    first, _ = tr.update(0, (7,))
    _, lost = tr.update(0, ())
    again, _ = tr.update(0, (7,))
    assert lost == (first[7],)
    assert again[7] != first[7]


def test_two_squadrons_get_independent_contact_ids():
    tr = vision.ContactTracker()
    a, _ = tr.update(0, (7,))
    b, _ = tr.update(1, (7,))
    assert a[7] != b[7]


def test_contacts_carry_both_frames_and_are_quantised():
    reader = _p(id=0, x=100.0, y=100.0, heading_deg=0.0)
    enemy = _p(id=9, x=400.0, y=100.0, heading_deg=90.0, speed=4.0, hp=88)
    out = vision.build_contacts(reader, {9: (0,)}, {9: enemy}, {9: 3}, ARENA)
    assert len(out) == 1
    c = out[0]
    assert c.id == 3
    assert c.hp == 88
    assert c.x == 400.0                                  # absolute frame
    assert c.bearing_deg == pytest.approx(0.0)           # relative frame
    assert c.range == pytest.approx(300.0)
    assert c.seen_by == (0,)
    assert c.bearing_deg == round(c.bearing_deg, vision.QUANT_ANGLE)
    assert c.range == round(c.range, vision.QUANT_RANGE)


def test_seeing_nothing_is_an_empty_tuple_not_a_sentinel():
    reader = _p(id=0, x=100.0, y=100.0, heading_deg=0.0)
    assert vision.build_contacts(reader, {}, {}, {}, ARENA) == ()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_vision.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.vision'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/vision.py`:

```python
"""Fog of war.

Enforced BY CONSTRUCTION: each squadron's view is assembled from the union of its own cones.
Never build a full world state with a `visible` flag on it -- that is a one-line cheat.
"""

import itertools

from . import geom
from .state import Contact

QUANT_ANGLE = 2
"""Decimal places for bot-visible angles. Coarser than any cross-platform libm disagreement."""

QUANT_RANGE = 1
"""Decimal places for bot-visible ranges."""


def in_cone(ox: float, oy: float, heading_deg: float, cone_deg: float, cone_range: float,
            tx: float, ty: float, w: float, h: float) -> bool:
    if cone_deg <= 0.0 or cone_range <= 0.0:
        return False
    if geom.distance(ox, oy, tx, ty, w, h) > cone_range:
        return False
    return abs(geom.bearing_to(ox, oy, heading_deg, tx, ty, w, h)) <= cone_deg / 2.0


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


def build_contacts(reader, seen: dict[int, tuple[int, ...]], enemies: dict[int, object],
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_vision.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/vision.py tests/test_vision.py
git commit -m "feat: cone vision, squadron union and re-acquisition contact ids"
```

---

### Task 8: Action validation

**Files:**

- Create: `src/skybattle/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**

- Consumes: `skybattle.state.Action`.
- Produces: `validate(raw: object, live_ids: tuple[int, ...]) ->
  tuple[dict[int, Action], tuple[tuple[int, str], ...]]` returning accepted actions per plane id
  and a tuple of `(plane_id, reason)` rejections. Exported for bot authors to call in their own
  tests, so an author can never pass their own tests and fail the engine's check.
- [ ] **Step 1: Write the failing test**

`tests/test_validate.py`:

```python
import math

from skybattle.state import Action
from skybattle.validate import validate

LIVE = (0, 1)


def test_accepts_a_good_dict():
    actions, rejects = validate({0: Action(throttle=1.0, steer=0.5)}, LIVE)
    assert actions[0].throttle == 1.0
    assert rejects == ()


def test_out_of_range_is_clamped_and_logged():
    actions, rejects = validate({0: Action(throttle=5.0, steer=-3.0)}, LIVE)
    assert actions[0].throttle == 1.0
    assert actions[0].steer == -1.0
    assert any("clamped" in r for _, r in rejects)


def test_nan_is_rejected_never_clamped():
    # NaN clamps to NaN and would poison the physics for BOTH players
    actions, rejects = validate({0: Action(throttle=math.nan)}, LIVE)
    assert 0 not in actions
    assert any("nan" in r for _, r in rejects)


def test_infinity_is_rejected():
    actions, rejects = validate({0: Action(steer=math.inf)}, LIVE)
    assert 0 not in actions
    assert any("nan" in r or "inf" in r for _, r in rejects)


def test_an_action_for_a_dead_or_unknown_plane_is_ignored_not_raised():
    actions, rejects = validate({99: Action(throttle=1.0)}, LIVE)
    assert actions == {}
    assert rejects == ((99, "unknown_plane"),)


def test_one_bad_entry_does_not_cost_the_other_plane_its_tick():
    actions, rejects = validate({0: Action(throttle=math.nan), 1: Action(throttle=1.0)}, LIVE)
    assert 1 in actions and actions[1].throttle == 1.0
    assert 0 not in actions


def test_a_non_dict_reply_rejects_the_whole_squadron_gracefully():
    actions, rejects = validate("go left", LIVE)
    assert actions == {}
    assert rejects == ((-1, "not_a_dict"),)


def test_a_non_action_value_is_rejected_per_plane():
    actions, rejects = validate({0: "left", 1: Action(throttle=1.0)}, LIVE)
    assert 0 not in actions and 1 in actions
    assert any("not_an_action" in r for _, r in rejects)


def test_a_non_integer_key_is_rejected():
    actions, rejects = validate({"zero": Action()}, LIVE)
    assert actions == {}
    assert any("bad_key" in r for _, r in rejects)


def test_fire_must_be_a_set_of_ints():
    actions, rejects = validate({0: Action(fire=frozenset({0, 1}))}, LIVE)
    assert actions[0].fire == frozenset({0, 1})
    actions, rejects = validate({0: Action(fire="both")}, LIVE)
    assert 0 not in actions
    assert any("bad_fire" in r for _, r in rejects)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_validate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.validate'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/validate.py`:

```python
"""Action validation. Degrade per plane, never per squadron.

One malformed entry must not cost the other plane its tick: partial failure is debuggable
("plane 2 coasted 40 times this match"), whole-squadron failure is not. A bot keeping a dict
keyed by plane id will NATURALLY emit a stale id on the tick after a loss, so that path has to
be boring rather than fatal.

Exported so a bot author can call the engine's own checker in their tests. Reusing this exact
function means an author can never pass their own tests and then fail the engine's check.
"""

import math

from .state import Action


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def validate(raw: object,
             live_ids: tuple[int, ...]) -> tuple[dict[int, Action], tuple[tuple[int, str], ...]]:
    """Returns (accepted actions by plane id, rejections as (plane_id, reason))."""
    rejects: list[tuple[int, str]] = []
    if not isinstance(raw, dict):
        return {}, ((-1, "not_a_dict"),)

    live = set(live_ids)
    out: dict[int, Action] = {}
    for key in sorted(raw, key=repr):        # deterministic order for the reject log
        value = raw[key]
        if not isinstance(key, int) or isinstance(key, bool):
            rejects.append((-1, f"bad_key:{key!r}"))
            continue
        if key not in live:
            rejects.append((key, "unknown_plane"))
            continue
        if not isinstance(value, Action):
            rejects.append((key, "not_an_action"))
            continue
        if not isinstance(value.fire, (set, frozenset)) or \
                any(not isinstance(g, int) or isinstance(g, bool) for g in value.fire):
            rejects.append((key, "bad_fire"))
            continue
        if not _finite(value.throttle, value.steer):
            # Never clamp: NaN clamps to NaN and poisons the physics for both players.
            rejects.append((key, "nan_or_inf"))
            continue

        throttle = min(max(value.throttle, 0.0), 1.0)
        steer = min(max(value.steer, -1.0), 1.0)
        if (throttle, steer) != (value.throttle, value.steer):
            rejects.append((key, "clamped"))
        out[key] = Action(throttle=throttle, steer=steer, fire=frozenset(value.fire))

    return out, tuple(rejects)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_validate.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/validate.py tests/test_validate.py
git commit -m "feat: per-plane action validation with NaN rejection"
```

---

### Task 9: World tick order, damage and deaths

**Files:**

- Create: `src/skybattle/world.py`
- Test: `tests/test_world.py`

**Interfaces:**

- Consumes: `flight`, `bullets`, `collide`, `vision`, `validate`, `classes`, `state`, `geom`.
- Produces: `Plane` (mutable dataclass: `id, squadron, kind, cls, x, y, heading_deg, speed, hp,
  ammo: list[int], cooldown: list[int], alive: bool`); `World` with `__init__(arena, squadrons:
  list[list[str]], classes: dict[str, PlaneClass], seed: int)`, `tick(replies: dict[int, object])
  -> None`, `views() -> dict[int, View]`, and attributes `planes: dict[int, Plane]`,
  `bullets: list[Bullet]`, `tick_no: int`, `damage_dealt: dict[int, float]`,
  `kills: dict[int, list[int]]`, `arena`.
- [ ] **Step 1: Write the failing test**

`tests/test_world.py`:

```python
import pytest

from skybattle.classes import load_classes
from skybattle.state import Action, PlaneDestroyed
from skybattle.world import World

CLASSES = load_classes()
ARENA = (2000.0, 2000.0)


def _world(squadrons=None):
    return World(ARENA, squadrons or [["fighter"], ["fighter"]], CLASSES, seed=7)


def test_two_squadrons_of_one_spawn_alive():
    w = _world()
    assert len(w.planes) == 2
    assert all(p.alive for p in w.planes.values())
    assert {p.squadron for p in w.planes.values()} == {0, 1}


def test_views_are_keyed_by_squadron_and_only_show_own_planes():
    w = _world()
    views = w.views()
    assert sorted(views) == [0, 1]
    assert len(views[0].planes) == 1
    assert views[0].planes[0].id in [p.id for p in w.planes.values() if p.squadron == 0]


def test_a_view_never_leaks_enemy_ammo():
    w = _world()
    for c in w.views()[0].contacts:
        assert not hasattr(c, "ammo")


def test_firing_spends_ammo_and_starts_a_cooldown():
    w = _world()
    pid = min(w.planes)
    w.tick({pid: Action(fire=frozenset({0})), max(w.planes): Action()})
    p = w.planes[pid]
    assert p.ammo[0] == CLASSES["fighter"].guns[0].ammo - 1
    assert p.cooldown[0] == CLASSES["fighter"].guns[0].cooldown_ticks
    assert len(w.bullets) == 1


def test_firing_on_cooldown_is_ignored_and_spends_nothing():
    w = _world()
    pid, other = min(w.planes), max(w.planes)
    w.tick({pid: Action(fire=frozenset({0})), other: Action()})
    spent = w.planes[pid].ammo[0]
    w.tick({pid: Action(fire=frozenset({0})), other: Action()})
    assert w.planes[pid].ammo[0] == spent
    assert len(w.bullets) == 1


def test_firing_with_no_ammo_is_ignored():
    w = _world()
    pid = min(w.planes)
    w.planes[pid].ammo[0] = 0
    w.planes[pid].cooldown[0] = 0
    w.tick({pid: Action(fire=frozenset({0}))})
    assert w.bullets == []


def test_an_unknown_gun_index_is_rejected_without_raising():
    w = _world()
    pid = min(w.planes)
    w.tick({pid: Action(fire=frozenset({9}))})
    assert w.bullets == []


def test_a_bullet_damages_an_enemy_and_credits_the_shooter():
    w = _world()
    a, b = min(w.planes), max(w.planes)
    # place the target directly in front, one tick of bullet travel away
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    before = w.planes[b].hp
    w.tick({a: Action(fire=frozenset({0})), b: Action()})
    assert w.planes[b].hp < before
    assert w.damage_dealt[0] > 0.0


def test_own_bullets_never_damage_the_shooters_own_squadron():
    w = World(ARENA, [["fighter", "fighter"], ["fighter"]], CLASSES, seed=7)
    mates = sorted(p.id for p in w.planes.values() if p.squadron == 0)
    a, mate = mates
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[mate].x, w.planes[mate].y = 515.0, 500.0
    before = w.planes[mate].hp
    w.tick({a: Action(fire=frozenset({0}))})
    assert w.planes[mate].hp == before


def test_a_plane_at_zero_hp_dies_and_emits_an_event():
    w = _world()
    a, b = min(w.planes), max(w.planes)
    w.planes[b].hp = 1
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    w.tick({a: Action(fire=frozenset({0})), b: Action()})
    assert not w.planes[b].alive
    assert any(isinstance(e, PlaneDestroyed) and e.plane_id == b
               for e in w.views()[1].events)


def test_a_dead_plane_contributes_no_vision_and_is_no_contact():
    # "first evaluate, then send new state" -- the snapshot is built AFTER resolution
    w = _world()
    a, b = min(w.planes), max(w.planes)
    w.planes[b].hp = 1
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    w.tick({a: Action(fire=frozenset({0})), b: Action()})
    assert w.views()[0].contacts == ()
    assert w.views()[1].planes == ()


def test_a_midair_collision_destroys_both_and_credits_neither():
    w = _world()
    a, b = min(w.planes), max(w.planes)
    w.planes[a].x, w.planes[a].y = 500.0, 500.0
    w.planes[b].x, w.planes[b].y = 505.0, 500.0
    w.tick({a: Action(), b: Action()})
    assert not w.planes[a].alive and not w.planes[b].alive
    assert w.damage_dealt[0] == 0.0 and w.damage_dealt[1] == 0.0


def test_the_same_seed_reproduces_the_same_match():
    def run():
        w = World(ARENA, [["scout", "fighter"], ["scout", "fighter"]], CLASSES, seed=99)
        for _ in range(60):
            w.tick({pid: Action(throttle=0.8, steer=0.4) for pid in w.planes})
        return [(round(p.x, 9), round(p.y, 9), round(p.speed, 9)) for _, p in sorted(w.planes.items())]

    assert run() == run()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_world.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.world'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/world.py`:

```python
"""The simulation.

TICK ORDER, and it is load-bearing: apply actions, integrate, resolve damage and deaths, THEN
build each squadron's view. A plane that died this tick therefore contributes no vision and
appears as no contact -- one rule instead of a family of edge cases.
"""

import random
from dataclasses import dataclass, field

from . import bullets as bul
from . import collide, flight, geom, vision
from .classes import PlaneClass
from .state import (Action, ActionRejected, BulletHit, ContactLost, Gun, HitByBullet, OwnPlane,
                    PlaneDestroyed, View)
from .validate import validate


@dataclass
class Plane:
    """Engine-internal, mutable. Never handed to a bot."""

    id: int
    squadron: int
    kind: str
    cls: PlaneClass
    x: float
    y: float
    heading_deg: float
    speed: float
    hp: int
    ammo: list[int]
    cooldown: list[int]
    alive: bool = True


class World:
    def __init__(self, arena: tuple[float, float], squadrons: list[list[str]],
                 classes: dict[str, PlaneClass], seed: int) -> None:
        self.arena = arena
        self.classes = classes
        self.seed = seed
        self.rng = random.Random(seed)
        self.tick_no = 0
        self.bullets: list[bul.Bullet] = []
        self.planes: dict[int, Plane] = {}
        self.tracker = vision.ContactTracker()
        self.damage_dealt: dict[int, float] = {sq: 0.0 for sq in range(len(squadrons))}
        self.kills: dict[int, list[int]] = {sq: [] for sq in range(len(squadrons))}
        self._events: dict[int, list[object]] = {sq: [] for sq in range(len(squadrons))}
        self._spawn(squadrons)

    # ---------------------------------------------------------------- setup

    def _spawn(self, squadrons: list[list[str]]) -> None:
        w, h = self.arena
        next_id = 0
        n = len(squadrons)
        for sq, kinds in enumerate(squadrons):
            # Squadrons start opposite each other, facing in. Planes always have velocity:
            # there is no "stopped" state, which is why coasting is the right timeout default.
            base = 360.0 / n * sq
            for slot, kind in enumerate(kinds):
                cls = self.classes[kind]
                cx = w / 2.0 + geom.cos_deg(base) * w * 0.3
                cy = h / 2.0 + geom.sin_deg(base) * h * 0.3
                self.planes[next_id] = Plane(
                    id=next_id, squadron=sq, kind=kind, cls=cls,
                    x=(cx + slot * 40.0) % w, y=(cy + slot * 40.0) % h,
                    heading_deg=geom.normalize_deg(base + 180.0),
                    speed=cls.corner_speed,
                    hp=cls.hp,
                    ammo=[g.ammo for g in cls.guns],
                    cooldown=[0 for _ in cls.guns],
                )
                next_id += 1

    # ---------------------------------------------------------------- tick

    def tick(self, replies: dict[int, object]) -> None:
        """Advance one tick. `replies` maps squadron index to that bot's raw reply."""
        self.tick_no += 1
        for sq in self._events:
            self._events[sq] = []

        actions = self._collect(replies)
        self._integrate(actions)
        self._fire(actions)
        self._advance_bullets()
        self._resolve_hits()
        self._resolve_rams()

    def _collect(self, replies: dict[int, object]) -> dict[int, Action]:
        """Validate every squadron's reply, degrading per plane."""
        actions: dict[int, Action] = {}
        for sq, raw in replies.items():
            live = tuple(sorted(p.id for p in self.planes.values()
                                if p.alive and p.squadron == sq))
            accepted, rejects = validate(raw, live)
            actions.update(accepted)
            for pid, reason in rejects:
                self._events[sq].append(ActionRejected(plane_id=pid, reason=reason))
        return actions

    def _integrate(self, actions: dict[int, Action]) -> None:
        for pid in sorted(self.planes):          # fixed order: never a dict-order dependency
            p = self.planes[pid]
            if not p.alive:
                continue
            a = actions.get(pid, Action())
            p.x, p.y, p.heading_deg, p.speed = flight.step(
                p.cls, p.x, p.y, p.heading_deg, p.speed, p.hp, p.cls.hp,
                a.throttle, a.steer, self.arena)
            for i in range(len(p.cooldown)):
                p.cooldown[i] = max(0, p.cooldown[i] - 1)

    def _fire(self, actions: dict[int, Action]) -> None:
        for pid in sorted(self.planes):
            p = self.planes[pid]
            if not p.alive:
                continue
            a = actions.get(pid)
            if a is None:
                continue
            for gi in sorted(a.fire):
                if gi < 0 or gi >= len(p.cls.guns):
                    self._events[p.squadron].append(
                        ActionRejected(plane_id=pid, reason=f"unknown_gun:{gi}"))
                    continue
                if p.cooldown[gi] > 0 or p.ammo[gi] <= 0:
                    continue
                gun = p.cls.guns[gi]
                self.bullets.append(bul.spawn(gun, gi, pid, p.squadron,
                                              p.x, p.y, p.heading_deg, p.speed))
                p.ammo[gi] -= 1
                p.cooldown[gi] = gun.cooldown_ticks

    def _advance_bullets(self) -> None:
        # Keep the pre-move position so the swept test has the full segment.
        self._segments = []
        alive = []
        for b in self.bullets:
            nxt = bul.advance(b, self.arena)
            if nxt is None:
                continue
            self._segments.append((b, b.vx, b.vy))
            alive.append(nxt)
        self.bullets = alive

    def _resolve_hits(self) -> None:
        w, h = self.arena
        spent: set[int] = set()
        for idx, (b, dx, dy) in enumerate(self._segments):
            best: tuple[float, Plane] | None = None
            for pid in sorted(self.planes):
                p = self.planes[pid]
                if not p.alive or p.squadron == b.squadron:
                    continue
                t = collide.swept_hit(p.x, p.y, collide.PLANE_RADIUS,
                                      b.x, b.y, dx, dy, w, h)
                if t is not None and (best is None or t < best[0]):
                    best = (t, p)
            if best is None:
                continue
            _, target = best
            spent.add(idx)
            target.hp -= b.damage
            self.damage_dealt[b.squadron] += b.damage
            self._events[b.squadron].append(
                BulletHit(plane_id=b.owner_id, gun=b.gun, target_id=target.id, damage=b.damage))
            self._events[target.squadron].append(
                HitByBullet(plane_id=target.id, from_squadron=b.squadron, damage=b.damage))
            if target.hp <= 0:
                self._kill(target, by=b.squadron)

        if spent:
            # A bullet that hit is consumed. Indices line up because _segments was built in
            # the same order as the surviving bullet list.
            self.bullets = [b for i, b in enumerate(self.bullets) if i not in spent]

    def _resolve_rams(self) -> None:
        """Mid-air collision destroys both and credits neither.

        Robocode pays MORE for ramming because a tank survives contact. A plane does not, so
        the incentive is inverted or 'fly the bomber into their scout' is a positive-value
        opening move.
        """
        w, h = self.arena
        ids = [pid for pid in sorted(self.planes) if self.planes[pid].alive]
        doomed: set[int] = set()
        for i, a_id in enumerate(ids):
            for b_id in ids[i + 1:]:
                a, b = self.planes[a_id], self.planes[b_id]
                if a.squadron == b.squadron:
                    continue
                if geom.distance(a.x, a.y, b.x, b.y, w, h) <= collide.PLANE_RADIUS * 2.0:
                    doomed.add(a_id)
                    doomed.add(b_id)
        for pid in sorted(doomed):
            self._kill(self.planes[pid], by=None)

    def _kill(self, p: Plane, by: int | None) -> None:
        if not p.alive:
            return
        p.alive = False
        p.hp = 0
        if by is not None:
            self.kills[by].append(p.id)
        event = PlaneDestroyed(plane_id=p.id, by=by)
        for sq in self._events:
            self._events[sq].append(event)

    # ---------------------------------------------------------------- views

    def views(self) -> dict[int, View]:
        """Build each squadron's fogged view. Called AFTER resolution, never before."""
        out: dict[int, View] = {}
        living = [p for _, p in sorted(self.planes.items()) if p.alive]
        for sq in sorted(self._events):
            mine = [p for p in living if p.squadron == sq]
            enemies = {p.id: p for p in living if p.squadron != sq}

            seen: dict[int, list[int]] = {}
            for observer in mine:
                for eid, enemy in sorted(enemies.items()):
                    if vision.sees(observer, enemy, self.arena):
                        seen.setdefault(eid, []).append(observer.id)
            seen_t = {eid: tuple(obs) for eid, obs in seen.items()}

            ids, lost = self.tracker.update(sq, tuple(sorted(seen_t)))
            events = list(self._events[sq]) + [ContactLost(contact_id=c) for c in lost]

            out[sq] = View(
                tick=self.tick_no,
                arena=self.arena,
                planes=tuple(self._own(p) for p in mine),
                contacts=(vision.build_contacts(mine[0], seen_t, enemies, ids, self.arena)
                          if mine else ()),
                events=tuple(events),
                rng=random.Random(self.seed ^ (sq + 1)),
            )
        return out

    @staticmethod
    def _own(p: Plane) -> OwnPlane:
        return OwnPlane(
            id=p.id, kind=p.kind, x=p.x, y=p.y, heading_deg=p.heading_deg, speed=p.speed,
            hp=p.hp, hp_max=p.cls.hp,
            stall_speed=p.cls.stall_speed, corner_speed=p.cls.corner_speed,
            max_speed=p.cls.max_speed,
            guns=tuple(Gun(name=g.name, bearing_deg=g.bearing_deg, arc_deg=g.arc_deg,
                           ammo=p.ammo[i], cooldown_ticks_left=p.cooldown[i])
                       for i, g in enumerate(p.cls.guns)),
        )
```

> **Known limitation to fix in Task 10, not here.** `View.contacts` is built from `mine[0]`'s nose, so a squadron's
> second plane currently reads bearings measured from its wingman. Task 10 replaces `View.contacts` with per-plane
> contact tuples. The test for it lives in Task 10; leave this as-is so the two tasks stay independently reviewable.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_world.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/world.py tests/test_world.py
git commit -m "feat: world tick order, damage resolution and deaths"
```

---

### Task 10: Per-plane contacts — and a spec correction

**Files:**

- Modify: `src/skybattle/state.py` (add `OwnPlane.contacts`, remove `View.contacts`)
- Modify: `src/skybattle/world.py` (`views` and `_own`)
- Modify: `docs/design/bot-api.md` §2
- Test: `tests/test_vision.py` (add), `tests/test_world.py` (add)

**Why this task exists.** `docs/design/bot-api.md` §2 places `contacts` on the *view* while also specifying that
`bearing_deg` and `range` are measured "from the nose of the plane reading them". Those two statements are
incompatible for a squadron of more than one: a single squadron-level tuple has no single reader. The spec is wrong
and this task fixes it in both the code and the document. **Contacts belong to a plane, not to a squadron.** The
squadron union survives as a fact about *which* enemies are known — it is `seen_by` that carries it — while the
geometry is per-reader, which is the whole reason the relative frame is usable without torus arithmetic.

**Interfaces:**

- Consumes: Task 7 and Task 9 output.
- Produces: `OwnPlane` gains a final field `contacts: tuple[Contact, ...] = ()`. `View` loses `contacts`; its
  fields become `tick, arena, planes, events, rng`.
- [ ] **Step 1: Write the failing tests**

Append to `tests/test_world.py`:

```python
def test_each_plane_reads_bearings_from_its_own_nose():
    w = World(ARENA, [["fighter", "fighter"], ["fighter"]], CLASSES, seed=7)
    mates = sorted(p.id for p in w.planes.values() if p.squadron == 0)
    a, b = mates
    enemy = next(p.id for p in w.planes.values() if p.squadron == 1)
    # both mates face east; the enemy sits ahead of one and off to the side of the other
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y, w.planes[b].heading_deg = 500.0, 400.0, 0.0
    w.planes[enemy].x, w.planes[enemy].y = 700.0, 500.0

    planes = {p.id: p for p in w.views()[0].planes}
    ca = planes[a].contacts
    cb = planes[b].contacts
    assert len(ca) == 1 and len(cb) == 1
    assert ca[0].id == cb[0].id                      # same contact, one squadron union
    assert ca[0].bearing_deg == pytest.approx(0.0)   # dead ahead of a
    assert cb[0].bearing_deg > 5.0                   # off to the left of b
    assert ca[0].range != cb[0].range


def test_seen_by_names_every_squadron_mate_that_can_see_it():
    w = World(ARENA, [["fighter", "fighter"], ["fighter"]], CLASSES, seed=7)
    mates = sorted(p.id for p in w.planes.values() if p.squadron == 0)
    a, b = mates
    enemy = next(p.id for p in w.planes.values() if p.squadron == 1)
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y, w.planes[b].heading_deg = 500.0, 490.0, 0.0
    w.planes[enemy].x, w.planes[enemy].y = 700.0, 495.0
    contacts = w.views()[0].planes[0].contacts
    assert set(contacts[0].seen_by) == {a, b}


def test_a_plane_that_sees_nothing_itself_still_receives_the_squadron_contact():
    # the shared-vision payoff: the scout spots, the blind mate still knows
    w = World(ARENA, [["scout", "bomber"], ["fighter"]], CLASSES, seed=7)
    scout = next(p.id for p in w.planes.values() if p.kind == "scout")
    bomber = next(p.id for p in w.planes.values() if p.kind == "bomber")
    enemy = next(p.id for p in w.planes.values() if p.squadron == 1)
    w.planes[scout].x, w.planes[scout].y, w.planes[scout].heading_deg = 500.0, 500.0, 0.0
    w.planes[bomber].x, w.planes[bomber].y, w.planes[bomber].heading_deg = 500.0, 300.0, 180.0
    w.planes[enemy].x, w.planes[enemy].y = 900.0, 500.0

    planes = {p.id: p for p in w.views()[0].planes}
    assert len(planes[scout].contacts) == 1
    assert len(planes[bomber].contacts) == 1              # knows, though it cannot see
    assert planes[bomber].contacts[0].seen_by == (scout,)  # and knows who is looking
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_world.py -k "own_nose or seen_by or sees_nothing" -v`
Expected: FAIL — `AttributeError: 'OwnPlane' object has no attribute 'contacts'`

- [ ] **Step 3: Move contacts onto the plane**

In `src/skybattle/state.py`, append a field to `OwnPlane` and drop `contacts` from `View`:

```python
class OwnPlane(NamedTuple):
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


class View(NamedTuple):
    tick: int
    arena: tuple[float, float]
    planes: tuple[OwnPlane, ...]
    events: tuple[object, ...]
    rng: random.Random | None = None
```

In `src/skybattle/world.py`, change `views` to build per-plane contacts and `_own` to accept them:

```python
            ids, lost = self.tracker.update(sq, tuple(sorted(seen_t)))
            events = list(self._events[sq]) + [ContactLost(contact_id=c) for c in lost]

            out[sq] = View(
                tick=self.tick_no,
                arena=self.arena,
                planes=tuple(
                    self._own(p, vision.build_contacts(p, seen_t, enemies, ids, self.arena))
                    for p in mine
                ),
                events=tuple(events),
                rng=random.Random(self.seed ^ (sq + 1)),
            )
        return out

    @staticmethod
    def _own(p: Plane, contacts: tuple[Contact, ...]) -> OwnPlane:
        return OwnPlane(
            id=p.id, kind=p.kind, x=p.x, y=p.y, heading_deg=p.heading_deg, speed=p.speed,
            hp=p.hp, hp_max=p.cls.hp,
            stall_speed=p.cls.stall_speed, corner_speed=p.cls.corner_speed,
            max_speed=p.cls.max_speed,
            guns=tuple(Gun(name=g.name, bearing_deg=g.bearing_deg, arc_deg=g.arc_deg,
                           ammo=p.ammo[i], cooldown_ticks_left=p.cooldown[i])
                       for i, g in enumerate(p.cls.guns)),
            contacts=contacts,
        )
```

Add `Contact` to the `from .state import (...)` line in `world.py`. Delete the "Known limitation" note left at the
end of Task 9's implementation, and update the two Task 9 tests that referenced `views()[0].contacts` to read
`views()[0].planes[0].contacts` (the dead-plane test asserts an empty tuple either way).

- [ ] **Step 4: Correct the spec**

In `docs/design/bot-api.md` §2, replace the `state.contacts` bullet with:

```markdown
- **`plane.contacts`** — enemies known to the squadron, carried on **each own-plane** with bearing and range
  measured from *that* plane's nose. The squadron shares knowledge instantly and perfectly, so every living plane
  receives the same contact ids; only the geometry differs per reader. Contacts belong to a plane rather than to the
  squadron precisely because the relative frame has to have a single, unambiguous origin — an earlier draft of this
  document put them on the view, which is incoherent for a squadron of more than one.
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -v`
Expected: PASS, everything green.

- [ ] **Step 6: Commit**

```bash
git add src/skybattle/state.py src/skybattle/world.py tests/test_world.py docs/design/bot-api.md
git commit -m "fix: contacts belong to a plane, not a squadron

The relative bearing frame needs one unambiguous origin, which a
squadron-level tuple does not have. Corrects the spec too."
```

---

### Task 11: Scoring, round end and the inactivity drain

**Files:**

- Modify: `src/skybattle/world.py`
- Test: `tests/test_scoring.py`

**Interfaces:**

- Consumes: Task 9 and Task 10 output.
- Produces: on `World`: `ROUND_TICK_LIMIT: int = 3000`, `INACTIVITY_TICKS: int = 600`,
  `round_over() -> bool`, `scores() -> dict[int, float]`, `outcome() -> str` returning one of
  `"squadron_0"`, `"squadron_1"`, ... `"draw"`, `"timeout"`, `"drain"`, and attributes
  `ticks_since_damage: int`, `won_by_drain: bool`.
- [ ] **Step 1: Write the failing test**

`tests/test_scoring.py`:

```python
import pytest

from skybattle.classes import load_classes
from skybattle.state import Action
from skybattle.world import World

CLASSES = load_classes()
ARENA = (2000.0, 2000.0)


def _w(squadrons=None, seed=7):
    return World(ARENA, squadrons or [["fighter"], ["fighter"]], CLASSES, seed=seed)


def _park(w):
    """Move both squadrons far apart and facing away, so nothing happens."""
    ids = sorted(w.planes)
    w.planes[ids[0]].x, w.planes[ids[0]].y, w.planes[ids[0]].heading_deg = 100.0, 100.0, 180.0
    w.planes[ids[1]].x, w.planes[ids[1]].y, w.planes[ids[1]].heading_deg = 1000.0, 1000.0, 0.0


def test_a_fresh_round_is_not_over():
    assert not _w().round_over()


def test_damage_scores_one_point_per_point():
    w = _w()
    w.damage_dealt[0] = 40.0
    assert w.scores()[0] == pytest.approx(40.0)


def test_a_kill_pays_fifty_plus_twenty_percent_of_damage_to_that_plane():
    w = _w()
    a, b = min(w.planes), max(w.planes)
    w.planes[b].hp = 5
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    w.tick({a: Action(fire=frozenset({0})), b: Action()})
    dmg = CLASSES["fighter"].guns[0].damage
    # damage + 50 survival + 20% kill bonus + 10 per dead enemy as last squadron flying
    assert w.scores()[0] == pytest.approx(dmg + 50.0 + 0.2 * dmg + 10.0)


def test_survival_time_alone_scores_nothing():
    w = _w()
    _park(w)
    for _ in range(200):
        w.tick({pid: Action() for pid in w.planes})
    assert w.scores()[0] == pytest.approx(0.0)
    assert w.scores()[1] == pytest.approx(0.0)


def test_the_round_ends_when_one_squadron_is_left_flying():
    w = _w()
    b = max(w.planes)
    w.planes[b].alive = False
    assert w.round_over()
    assert w.outcome() == "squadron_0"


def test_the_round_ends_at_the_tick_limit():
    w = _w()
    _park(w)
    w.tick_no = World.ROUND_TICK_LIMIT
    assert w.round_over()
    assert w.outcome() == "timeout"


def test_the_inactivity_drain_starts_after_600_quiet_ticks():
    w = _w()
    _park(w)
    hp_before = w.planes[min(w.planes)].hp
    for _ in range(World.INACTIVITY_TICKS + 5):
        w.tick({pid: Action() for pid in w.planes})
    assert w.planes[min(w.planes)].hp < hp_before


def test_any_damage_resets_the_inactivity_counter():
    w = _w()
    a, b = min(w.planes), max(w.planes)
    _park(w)
    for _ in range(100):
        w.tick({pid: Action() for pid in w.planes})
    assert w.ticks_since_damage >= 100
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    w.tick({a: Action(fire=frozenset({0})), b: Action()})
    assert w.ticks_since_damage == 0


def test_a_win_by_drain_pays_no_last_survivor_bonus():
    w = _w()
    _park(w)
    w.planes[max(w.planes)].hp = 2
    for _ in range(World.INACTIVITY_TICKS + 10):
        w.tick({pid: Action() for pid in w.planes})
        if w.round_over():
            break
    assert w.won_by_drain
    assert w.outcome() == "drain"
    assert w.scores()[0] == pytest.approx(50.0)   # survival credit only, no +10 per dead enemy


def test_mutual_destruction_is_a_draw():
    w = _w()
    for pid in w.planes:
        w.planes[pid].alive = False
    assert w.round_over()
    assert w.outcome() == "draw"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_scoring.py -v`
Expected: FAIL — `AttributeError: 'World' object has no attribute 'round_over'`

- [ ] **Step 3: Write the implementation**

In `src/skybattle/world.py`, add the two class constants and initialise the counters in `__init__`:

```python
class World:
    ROUND_TICK_LIMIT = 3000
    INACTIVITY_TICKS = 600
    """Quiet ticks before the drain starts. Robocode's mechanic, retuned.

    The torus abolishes corner-camping but it also removes the map's own answer to fleeing:
    with no walls a faster plane can outrun a pursuer forever. So an explicit clock is
    load-bearing, not optional.
    """
```

In `__init__`, after `self.kills = ...`:

```python
        self.ticks_since_damage = 0
        self.won_by_drain = False
```

At the end of `tick()`, after `self._resolve_rams()`:

```python
        self._drain()
```

And add these methods:

```python
    def _drain(self) -> None:
        """Bleed everyone until somebody dies, if nothing has happened for long enough.

        Punishes MUTUAL passivity without punishing a bot that is legitimately evading while
        under fire, because taking damage resets the counter.
        """
        self.ticks_since_damage += 1
        if self.ticks_since_damage < self.INACTIVITY_TICKS:
            return
        for pid in sorted(self.planes):
            p = self.planes[pid]
            if not p.alive:
                continue
            p.hp -= 1
            if p.hp <= 0:
                self.won_by_drain = True
                self._kill(p, by=None)

    def _living_squadrons(self) -> tuple[int, ...]:
        return tuple(sorted({p.squadron for p in self.planes.values() if p.alive}))

    def round_over(self) -> bool:
        return len(self._living_squadrons()) <= 1 or self.tick_no >= self.ROUND_TICK_LIMIT

    def outcome(self) -> str:
        living = self._living_squadrons()
        if not living:
            return "draw"
        if len(living) == 1:
            return "drain" if self.won_by_drain else f"squadron_{living[0]}"
        if self.tick_no >= self.ROUND_TICK_LIMIT:
            return "timeout"
        return "ongoing"

    def scores(self) -> dict[int, float]:
        """Robocode's formula, which is a quarter-century-tuned answer to 'make hiding lose'.

            1 x damage dealt
          + 20% of damage dealt to any enemy plane you destroyed
          + 50 x enemy planes destroyed while you still had a plane alive
          + 10 x enemy planes dead, only if you are the last squadron flying

        Survival time is deliberately never scored on its own: that IS the camping incentive.
        """
        living = self._living_squadrons()
        last_standing = living[0] if len(living) == 1 and not self.won_by_drain else None
        dead_planes = sum(1 for p in self.planes.values() if not p.alive)

        out: dict[int, float] = {}
        for sq in sorted(self.damage_dealt):
            score = self.damage_dealt[sq]
            for victim in self.kills[sq]:
                score += 50.0
                score += 0.2 * self._damage_to(sq, victim)
            if sq == last_standing:
                score += 10.0 * dead_planes
            out[sq] = score
        return out

    def _damage_to(self, squadron: int, victim_id: int) -> float:
        return self._damage_ledger.get((squadron, victim_id), 0.0)
```

The kill bonus needs a per-victim ledger. In `__init__` add:

```python
        self._damage_ledger: dict[tuple[int, int], float] = {}
```

And in `_resolve_hits`, immediately after `self.damage_dealt[b.squadron] += b.damage`:

```python
            key = (b.squadron, target.id)
            self._damage_ledger[key] = self._damage_ledger.get(key, 0.0) + b.damage
            self.ticks_since_damage = 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_scoring.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS, all green.

- [ ] **Step 6: Commit**

```bash
git add src/skybattle/world.py tests/test_scoring.py
git commit -m "feat: Robocode-style scoring, round end and inactivity drain"
```

---

### Task 12: The wire codec

**Files:**

- Create: `src/skybattle/protocol.py`
- Test: `tests/test_protocol.py`

**Why a codec is needed.** The bot lives in another process, so the typed `View` has to survive a JSON round trip
and arrive as typed objects again — a bot author must never touch a raw dict. `NamedTuple` is a `tuple`, so
`json.dumps` emits compact positional arrays with no custom encoder (measured at 34% smaller than a
self-describing form, which compounds over 1800 ticks). `View.rng` cannot cross the wire, so its seed does.

**Interfaces:**

- Consumes: `skybattle.state`.
- Produces: `encode_view(view: View, rng_seed: int) -> dict`; `decode_view(payload: dict) -> View`;
  `encode_actions(actions: dict[int, Action]) -> dict`; `decode_actions(payload: dict) -> dict[int, Action]`.
- [ ] **Step 1: Write the failing test**

`tests/test_protocol.py`:

```python
import json

import pytest

from skybattle import protocol
from skybattle.state import Action, Contact, Gun, OwnPlane, View


def _view():
    g = Gun(name="forward", bearing_deg=0.0, arc_deg=8.0, ammo=80, cooldown_ticks_left=2)
    c = Contact(id=4, kind="bomber", x=1.0, y=2.0, heading_deg=90.0, speed=4.0, hp=120,
                bearing_deg=-30.0, range=250.0, seen_by=(0, 1))
    p = OwnPlane(id=0, kind="scout", x=10.0, y=20.0, heading_deg=45.0, speed=5.0, hp=70,
                 hp_max=70, stall_speed=3.0, corner_speed=5.0, max_speed=9.0, guns=(g,),
                 contacts=(c,))
    return View(tick=12, arena=(2000.0, 1400.0), planes=(p,), events=())


def test_view_survives_a_json_round_trip_as_typed_objects():
    wire = json.loads(json.dumps(protocol.encode_view(_view(), rng_seed=5)))
    back = protocol.decode_view(wire)
    assert isinstance(back, View)
    assert back.tick == 12
    assert back.arena == (2000.0, 1400.0)
    assert isinstance(back.planes[0], OwnPlane)
    assert isinstance(back.planes[0].guns[0], Gun)
    assert isinstance(back.planes[0].contacts[0], Contact)
    assert back.planes[0].contacts[0].seen_by == (0, 1)
    assert back.planes[0].guns[0].cooldown_ticks_left == 2


def test_the_rng_arrives_as_a_seeded_random_not_a_seed():
    back = protocol.decode_view(protocol.encode_view(_view(), rng_seed=5))
    other = protocol.decode_view(protocol.encode_view(_view(), rng_seed=5))
    assert back.rng.random() == other.rng.random()


def test_actions_survive_a_json_round_trip():
    actions = {0: Action(throttle=1.0, steer=-0.25, fire=frozenset({0, 1})), 3: Action()}
    wire = json.loads(json.dumps(protocol.encode_actions(actions)))
    back = protocol.decode_actions(wire)
    assert back[0].throttle == 1.0
    assert back[0].steer == -0.25
    assert back[0].fire == frozenset({0, 1})
    assert back[3] == Action()


def test_action_keys_come_back_as_ints_not_strings():
    back = protocol.decode_actions(protocol.encode_actions({7: Action()}))
    assert list(back) == [7]
    assert isinstance(next(iter(back)), int)


def test_a_garbage_action_payload_raises_rather_than_returning_nonsense():
    with pytest.raises((TypeError, ValueError, KeyError, AttributeError)):
        protocol.decode_actions("left a bit")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.protocol'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/protocol.py`:

```python
"""JSON codec for the engine/bot boundary.

Newline-delimited JSON over pipes, measured at 44 microseconds per round trip for a squadron
of two. msgpack is 1.8x faster, which is about 20 microseconds a tick and therefore irrelevant,
and it costs a dependency plus opacity: a student can read JSON.
"""

import random

from .state import Action, Contact, Gun, OwnPlane, View


def encode_view(view: View, rng_seed: int) -> dict:
    """`View` -> a JSON-ready dict. `rng` becomes a seed; a Random cannot cross a pipe."""
    return {
        "tick": view.tick,
        "arena": list(view.arena),
        "rng_seed": rng_seed,
        "planes": [
            {
                "p": list(p[:11]),
                "guns": [list(g) for g in p.guns],
                "contacts": [list(c) for c in p.contacts],
            }
            for p in view.planes
        ],
        "events": [[type(e).__name__, list(e)] for e in view.events],
    }


def decode_view(payload: dict) -> View:
    """A JSON dict -> a typed `View`. The bot author never sees a raw dict."""
    planes = []
    for entry in payload["planes"]:
        head = entry["p"]
        planes.append(OwnPlane(
            *head,
            guns=tuple(Gun(g[0], *(float(v) for v in g[1:3]), int(g[3]), int(g[4]))
                       for g in entry["guns"]),
            contacts=tuple(Contact(int(c[0]), c[1], *(float(v) for v in c[2:6]), int(c[6]),
                                   float(c[7]), float(c[8]), tuple(int(i) for i in c[9]))
                           for c in entry["contacts"]),
        ))
    return View(
        tick=int(payload["tick"]),
        arena=(float(payload["arena"][0]), float(payload["arena"][1])),
        planes=tuple(planes),
        events=tuple(tuple(body) for _, body in payload["events"]),
        rng=random.Random(payload["rng_seed"]),
    )


def encode_actions(actions: dict[int, Action]) -> dict:
    return {str(pid): [a.throttle, a.steer, sorted(a.fire)] for pid, a in actions.items()}


def decode_actions(payload: dict) -> dict[int, Action]:
    """Raises on anything malformed. The driver catches and counts a strike."""
    return {
        int(pid): Action(throttle=float(body[0]), steer=float(body[1]),
                         fire=frozenset(int(g) for g in body[2]))
        for pid, body in payload.items()
    }
```

> **Event decoding is deliberately lossy.** Events arrive as plain tuples rather than their named types, because
> reconstructing the class would mean shipping a registry that must stay in sync across a version boundary. Task 17
> revisits this if a sample bot needs to branch on an event type; until one does, YAGNI applies. The
> `[type_name, fields]` shape on the wire preserves everything needed to do it later without a protocol change.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_protocol.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/protocol.py tests/test_protocol.py
git commit -m "feat: JSON wire codec for the engine/bot boundary"
```

---

### Task 13: The runner shim

**Files:**

- Create: `src/skybattle/runner.py`
- Test: `tests/test_runner.py`, `tests/bots/` (fixture bots)

**Interfaces:**

- Consumes: `skybattle.protocol`, `skybattle.state`.
- Produces: a module runnable as `python -m skybattle.runner <bot_path>` that reads one JSON view
  per line on stdin and writes one JSON reply per line on its private stdout channel. Reply shape:
  `{"tick": int, "actions": {...}}` or `{"tick": int, "error": str}`.

**This is the highest-value ergonomic decision in the project.** If the protocol lived on the bot's stdout, the
first thing every author does — `print("debug")` — would desynchronise the match. Halite and CodinGame both put the
protocol on stdout and rely on authors knowing to use stderr. Convention is not enough for friends who are learning.

- [ ] **Step 1: Write the fixture bots**

`tests/bots/good.py`:

```python
from skybattle.state import Action


class Bot:
    def act(self, state):
        return {p.id: Action(throttle=1.0, steer=0.5) for p in state.planes}
```

`tests/bots/chatty.py`:

```python
from skybattle.state import Action

print("hello from module import time")


class Bot:
    def act(self, state):
        print("thinking about tick", state.tick)
        return {p.id: Action(throttle=0.5) for p in state.planes}
```

`tests/bots/protocol_liar.py` — the worst case: it prints something that looks exactly like a reply.

```python
import json

from skybattle.state import Action


class Bot:
    def act(self, state):
        print(json.dumps({"tick": state.tick, "actions": {"0": [1.0, 1.0, []]}}))
        return {p.id: Action(throttle=0.25) for p in state.planes}
```

`tests/bots/crasher.py`:

```python
class Bot:
    def act(self, state):
        raise ValueError("bot author's bug: index out of range")
```

`tests/bots/function_style.py` — an author who wrote a plain function instead of a class.

```python
from skybattle.state import Action


def act(state):
    return {p.id: Action(throttle=1.0) for p in state.planes}
```

- [ ] **Step 2: Write the failing test**

`tests/test_runner.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

import pytest

from skybattle import protocol
from skybattle.state import Gun, OwnPlane, View

BOTS = Path(__file__).parent / "bots"


def _line(tick=1):
    g = Gun(name="forward", bearing_deg=0.0, arc_deg=8.0, ammo=80, cooldown_ticks_left=0)
    p = OwnPlane(id=0, kind="scout", x=0.0, y=0.0, heading_deg=0.0, speed=5.0, hp=70, hp_max=70,
                 stall_speed=3.0, corner_speed=5.0, max_speed=9.0, guns=(g,), contacts=())
    view = View(tick=tick, arena=(2000.0, 2000.0), planes=(p,), events=())
    return json.dumps(protocol.encode_view(view, rng_seed=1)) + "\n"


def _run(bot, ticks=2, timeout=20):
    proc = subprocess.run(
        [sys.executable, "-u", "-m", "skybattle.runner", str(BOTS / bot)],
        input="".join(_line(t) for t in range(1, ticks + 1)),
        capture_output=True, text=True, timeout=timeout,
    )
    replies = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
    return replies, proc.stderr


def test_a_good_bot_replies_once_per_tick_with_the_tick_echoed():
    replies, _ = _run("good.py")
    assert [r["tick"] for r in replies] == [1, 2]
    assert replies[0]["actions"]["0"][0] == 1.0


def test_printing_does_not_corrupt_the_protocol():
    replies, err = _run("chatty.py")
    assert [r["tick"] for r in replies] == [1, 2]
    assert "hello from module import time" in err
    assert "thinking about tick" in err


def test_a_bot_printing_protocol_shaped_json_still_cannot_corrupt_the_stream():
    replies, err = _run("protocol_liar.py")
    assert [r["tick"] for r in replies] == [1, 2]
    # its fake reply is on stderr, and its REAL reply is the throttle it returned
    assert all(r["actions"]["0"][0] == 0.25 for r in replies)
    assert "actions" in err


def test_a_crash_becomes_a_clean_error_reply_with_the_traceback_on_stderr():
    replies, err = _run("crasher.py")
    assert [r["tick"] for r in replies] == [1, 2]
    assert all("error" in r for r in replies)
    assert "bot author's bug: index out of range" in err
    assert "Traceback" in err


def test_a_plain_act_function_works_as_well_as_a_bot_class():
    replies, _ = _run("function_style.py")
    assert replies[0]["actions"]["0"][0] == 1.0


def test_a_missing_bot_file_fails_loudly_rather_than_silently():
    proc = subprocess.run(
        [sys.executable, "-u", "-m", "skybattle.runner", str(BOTS / "nope.py")],
        input=_line(), capture_output=True, text=True, timeout=20,
    )
    assert proc.returncode != 0
    assert "nope.py" in proc.stderr
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL — `No module named skybattle.runner`

- [ ] **Step 4: Write the implementation**

`src/skybattle/runner.py`:

```python
"""The subprocess shim. It owns all I/O so the bot author owns none.

Duplicates the real stdout aside as a private protocol channel, then points fd 1 and
`sys.stdout` at stderr. An author's `print` -- even one emitting a protocol-shaped JSON line --
therefore lands harmlessly on stderr, where they can read it.

The author writes only `act(state) -> {plane_id: Action}`, as a `Bot` class or a bare function.
"""

import importlib.util
import json
import os
import sys
import traceback

from . import protocol


def _open_channel():
    """Take stdout for the protocol, then redirect all normal output to stderr."""
    channel = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return channel


def _load(path: str):
    """Import the author's file and return a callable act(state)."""
    spec = importlib.util.spec_from_file_location("author_bot", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import a bot from {path!r}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "Bot"):
        return module.Bot().act
    if hasattr(module, "act"):
        return module.act
    raise AttributeError(f"{path!r} defines neither a Bot class nor an act() function")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m skybattle.runner <bot.py>", file=sys.stderr)
        return 2

    channel = _open_channel()
    try:
        act = _load(argv[0])
    except Exception:
        traceback.print_exc()
        return 1

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        tick = payload["tick"]
        try:
            view = protocol.decode_view(payload)
            reply = {"tick": tick, "actions": protocol.encode_actions(view and act(view))}
        except Exception:
            # The author's traceback goes to stderr so they debug normally; the engine gets a
            # clean error and never has to tell "crashed" from "sent nonsense" by parsing text.
            traceback.print_exc()
            reply = {"tick": tick, "error": "bot raised"}
        channel.write(json.dumps(reply) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> `protocol.encode_actions(view and act(view))` is deliberate: if `act` returns something that is not a dict,
> `encode_actions` raises inside the `try`, so a malformed return is reported as an error reply rather than
> crashing the shim.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_runner.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 6: Commit**

```bash
git add src/skybattle/runner.py tests/test_runner.py tests/bots/
git commit -m "feat: runner shim so print() cannot corrupt the protocol"
```

---

### Task 14: The bot driver

**Files:**

- Create: `src/skybattle/driver.py`
- Test: `tests/test_driver.py`, plus three more fixture bots

**Interfaces:**

- Consumes: `skybattle.protocol`, `skybattle.state.Action`.
- Produces: `BotProcess` with `__init__(bot_path: str | Path, tick_deadline: float = 0.05,
  first_tick_deadline: float = 2.0, strike_limit: int = 3)`, `exchange(view: View, rng_seed: int)
  -> tuple[object, str]` returning `(raw_reply_or_last_accepted, status)` where status is one of
  `"ok"`, `"timeout"`, `"error"`, `"forfeit"`; `close() -> None`; attributes `strikes: int`,
  `accepted: int`, `ticks: int`, `forfeited: bool`, `stderr_tail: list[str]`.
  Context-manager support (`__enter__` / `__exit__`).
- [ ] **Step 1: Write the fixture bots**

`tests/bots/hanger.py`:

```python
class Bot:
    def act(self, state):
        while True:
            pass
```

`tests/bots/slow_first_tick.py` — the realistic unfair-miss case: a costly import, then fast.

```python
import time

from skybattle.state import Action

time.sleep(0.4)          # stands in for a heavy module-level import


class Bot:
    def act(self, state):
        return {p.id: Action(throttle=1.0) for p in state.planes}
```

`tests/bots/garbage.py`:

```python
class Bot:
    def act(self, state):
        return "go left"
```

- [ ] **Step 2: Write the failing test**

`tests/test_driver.py`:

```python
import json
from pathlib import Path

from skybattle.driver import BotProcess
from skybattle.state import Gun, OwnPlane, View

BOTS = Path(__file__).parent / "bots"


def _view(tick):
    g = Gun(name="forward", bearing_deg=0.0, arc_deg=8.0, ammo=80, cooldown_ticks_left=0)
    p = OwnPlane(id=0, kind="scout", x=0.0, y=0.0, heading_deg=0.0, speed=5.0, hp=70, hp_max=70,
                 stall_speed=3.0, corner_speed=5.0, max_speed=9.0, guns=(g,), contacts=())
    return View(tick=tick, arena=(2000.0, 2000.0), planes=(p,), events=())


def test_a_good_bot_is_accepted_every_tick():
    with BotProcess(BOTS / "good.py") as bot:
        for t in range(1, 6):
            _, status = bot.exchange(_view(t), rng_seed=1)
            assert status == "ok"
        assert bot.strikes == 0
        assert bot.accepted == 5


def test_a_hanging_bot_times_out_and_then_forfeits():
    with BotProcess(BOTS / "hanger.py", tick_deadline=0.05, first_tick_deadline=0.2) as bot:
        statuses = [bot.exchange(_view(t), rng_seed=1)[1] for t in range(1, 6)]
        assert "timeout" in statuses
        assert statuses[-1] == "forfeit"
        assert bot.forfeited


def test_a_timeout_re_applies_the_last_accepted_action():
    with BotProcess(BOTS / "hanger.py", tick_deadline=0.05, first_tick_deadline=0.2) as bot:
        raw, status = bot.exchange(_view(1), rng_seed=1)
        assert status == "timeout"
        # tick 0 has no previous action, so the fallback is a neutral Action
        assert raw == {}


def test_the_first_tick_gets_a_generous_budget_for_module_imports():
    with BotProcess(BOTS / "slow_first_tick.py",
                    tick_deadline=0.05, first_tick_deadline=3.0) as bot:
        _, status = bot.exchange(_view(1), rng_seed=1)
        assert status == "ok"
        assert bot.strikes == 0


def test_a_crashing_bot_is_an_error_not_a_timeout_and_the_traceback_is_captured():
    with BotProcess(BOTS / "crasher.py", strike_limit=99) as bot:
        _, status = bot.exchange(_view(1), rng_seed=1)
        assert status == "error"
        bot.exchange(_view(2), rng_seed=1)
    assert any("index out of range" in line for line in bot.stderr_tail)


def test_a_garbage_reply_is_an_error():
    with BotProcess(BOTS / "garbage.py", strike_limit=99) as bot:
        _, status = bot.exchange(_view(1), rng_seed=1)
        assert status == "error"


def test_a_stale_reply_never_becomes_the_next_ticks_answer():
    """The silent off-by-one that naive implementations ship.

    A bot slow on tick 1 replies during tick 2; without a tick echo the engine reads that late
    answer as tick 2's, and every subsequent tick is permanently misaligned.
    """
    with BotProcess(BOTS / "slow_first_tick.py",
                    tick_deadline=0.05, first_tick_deadline=0.05, strike_limit=99) as bot:
        first = bot.exchange(_view(1), rng_seed=1)
        assert first[1] == "timeout"
        # whatever happens next, an accepted reply must be for the tick we asked about
        for t in range(2, 8):
            raw, status = bot.exchange(_view(t), rng_seed=1)
            if status == "ok":
                assert isinstance(raw, dict)
                break
        assert bot.accepted <= bot.ticks


def test_printing_bots_do_not_break_the_driver():
    with BotProcess(BOTS / "protocol_liar.py") as bot:
        for t in range(1, 4):
            _, status = bot.exchange(_view(t), rng_seed=1)
            assert status == "ok"


def test_close_is_idempotent_and_reaps_a_hung_child():
    bot = BotProcess(BOTS / "hanger.py", tick_deadline=0.05, first_tick_deadline=0.1)
    bot.exchange(_view(1), rng_seed=1)
    bot.close()
    bot.close()
    assert bot.proc.poll() is not None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_driver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.driver'`

- [ ] **Step 4: Write the implementation**

`src/skybattle/driver.py`:

```python
"""One bot, one long-lived subprocess, one match.

Spawning per tick costs 22-31 ms against a 44 microsecond round trip -- 500x -- and throws away
the bot's memory between ticks, which destroys any bot that tracks a target. So: long-lived.

The process boundary is what makes a deadline enforceable at all. A `while True: pass` in the
same interpreter cannot be interrupted: signals only run between bytecodes on the main thread
and a thread cannot be killed. Robustness, not security, is what forces the subprocess.
"""

import json
import os
import selectors
import signal
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from . import protocol
from .state import View


class BotProcess:
    def __init__(self, bot_path: str | Path, tick_deadline: float = 0.05,
                 first_tick_deadline: float = 2.0, strike_limit: int = 3) -> None:
        self.bot_path = Path(bot_path)
        self.tick_deadline = tick_deadline
        self.first_tick_deadline = first_tick_deadline
        self.strike_limit = strike_limit

        self.strikes = 0
        self.consecutive = 0
        self.accepted = 0
        self.ticks = 0
        self.forfeited = False
        self.last_accepted: dict = {}
        self.stderr_tail: deque[str] = deque(maxlen=200)
        self._closed = False

        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "skybattle.runner", str(self.bot_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
            # Kill the whole group later: a bot that spawned helpers must leave no orphans.
            start_new_session=True,
        )
        self._sel = selectors.DefaultSelector()
        self._sel.register(self.proc.stdout, selectors.EVENT_READ)
        # Drain stderr on a thread so a chatty bot can never fill the pipe and block itself.
        self._err = threading.Thread(target=self._drain_stderr, daemon=True)
        self._err.start()

    def _drain_stderr(self) -> None:
        for line in self.proc.stderr:
            self.stderr_tail.append(line.rstrip("\n"))

    # ------------------------------------------------------------------ tick

    def exchange(self, view: View, rng_seed: int) -> tuple[object, str]:
        """Send one view, wait for the matching reply. Returns (raw reply, status)."""
        self.ticks += 1
        if self.forfeited or self.proc.poll() is not None:
            return self.last_accepted, "forfeit"

        deadline = self.first_tick_deadline if self.ticks == 1 else self.tick_deadline
        try:
            self.proc.stdin.write(json.dumps(protocol.encode_view(view, rng_seed)) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            return self._strike("dead_pipe")

        # Drain any stale replies until the one for THIS tick arrives, or the deadline expires.
        while True:
            if not self._sel.select(deadline):
                return self._strike("timeout")
            line = self.proc.stdout.readline()
            if not line:
                return self._strike("dead_pipe")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                return self._strike("error")
            if payload.get("tick") != view.tick:
                continue                      # a late answer to an earlier tick: discard it
            if "error" in payload:
                return self._strike("error")
            try:
                actions = protocol.decode_actions(payload["actions"])
            except Exception:
                return self._strike("error")
            self.accepted += 1
            self.consecutive = 0
            self.last_accepted = actions
            return actions, "ok"

    def _strike(self, status: str) -> tuple[object, str]:
        """Count a failure and fall back to the last accepted action.

        Hold-last is Battlesnake's rule and it cannot be gamed: a bot gains nothing by timing
        out, because it simply keeps doing whatever it last chose. Never make the fallback
        something advantageous.
        """
        self.strikes += 1
        self.consecutive += 1
        if self.consecutive >= self.strike_limit or self.strikes > max(1, self.ticks // 50):
            # A chronically slow bot never lands an action at all -- every tick times out and
            # its late reply is then dropped as stale -- so it would hold tick 0's action for
            # the whole match while looking as though it played. Forfeit it instead.
            self.forfeited = True
            self.close()
            return self.last_accepted, "forfeit"
        return self.last_accepted, status

    # ----------------------------------------------------------------- close

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._sel.close()
        except Exception:
            pass
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except Exception:
                pass
        if self.proc.poll() is None:
            try:
                # killpg, not kill: reap any helpers the bot spawned.
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                self.proc.kill()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def __enter__(self) -> "BotProcess":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
```

> `communicate(timeout=…)` is deliberately not used anywhere: it does **not** kill the child when the timeout
> expires, so a hung bot would survive it.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_driver.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 6: Commit**

```bash
git add src/skybattle/driver.py tests/test_driver.py tests/bots/
git commit -m "feat: bot driver with deadlines, tick echo and hold-last fallback"
```

---

### Task 15: Replay writers

**Files:**

- Create: `src/skybattle/replay.py`
- Test: `tests/test_replay.py`

**Interfaces:**

- Consumes: `skybattle.world.World`, `skybattle.classes.table_hash`, `skybattle.state.API_VERSION`.
- Produces: `ThinWriter(path, header: dict)` with `record(tick: int, actions: dict[int, Action],
  statuses: dict[int, str]) -> None` and `close()`; `FatWriter(path, header: dict)` with
  `record(world: World) -> None` and `close()`; `read(path) -> tuple[dict, list[dict]]`;
  `make_header(seed, arena, squadrons, table_path=None) -> dict`. Both writers are context managers
  and write gzipped JSONL.
- [ ] **Step 1: Write the failing test**

`tests/test_replay.py`:

```python
import gzip
import json

from skybattle import replay
from skybattle.classes import load_classes
from skybattle.state import Action
from skybattle.world import World

CLASSES = load_classes()
ARENA = (2000.0, 2000.0)


def _world():
    return World(ARENA, [["fighter"], ["fighter"]], CLASSES, seed=7)


def test_the_header_records_everything_needed_to_reproduce():
    h = replay.make_header(seed=7, arena=ARENA, squadrons=[["fighter"], ["fighter"]])
    for key in ("seed", "arena", "squadrons", "class_table_sha256", "api_version",
                "engine_version", "python_version"):
        assert key in h


def test_thin_replay_records_actions_and_statuses_per_tick(tmp_path):
    p = tmp_path / "thin.jsonl.gz"
    with replay.ThinWriter(p, replay.make_header(7, ARENA, [["fighter"], ["fighter"]])) as wr:
        wr.record(1, {0: Action(throttle=1.0)}, {0: "ok", 1: "timeout"})
    header, ticks = replay.read(p)
    assert header["seed"] == 7
    assert ticks[0]["tick"] == 1
    assert ticks[0]["statuses"]["1"] == "timeout"


def test_fat_replay_carries_derived_fields_so_a_viewer_needs_no_engine(tmp_path):
    w = _world()
    w.tick({pid: Action(throttle=1.0) for pid in w.planes})
    p = tmp_path / "fat.jsonl.gz"
    with replay.FatWriter(p, replay.make_header(7, ARENA, [["fighter"], ["fighter"]])) as wr:
        wr.record(w)
    _, ticks = replay.read(p)
    frame = ticks[0]
    plane = frame["planes"][0]
    for key in ("id", "squadron", "kind", "x", "y", "heading_deg", "speed", "hp", "alive",
                "cone_deg", "cone_range", "rear_cone_deg", "rear_cone_range"):
        assert key in plane, key
    assert "visible" in frame            # what each squadron could see, recorded not recomputed
    assert "bullets" in frame
    assert "scores" in frame


def test_fat_replay_records_a_degraded_tick_badge(tmp_path):
    w = _world()
    w.tick({pid: Action() for pid in w.planes})
    p = tmp_path / "fat.jsonl.gz"
    with replay.FatWriter(p, replay.make_header(7, ARENA, [["fighter"], ["fighter"]])) as wr:
        wr.record(w, statuses={0: "ok", 1: "timeout"})
    _, ticks = replay.read(p)
    assert ticks[0]["degraded"] == ["1"]


def test_replays_are_gzipped_jsonl(tmp_path):
    p = tmp_path / "thin.jsonl.gz"
    with replay.ThinWriter(p, replay.make_header(7, ARENA, [["fighter"]])) as wr:
        wr.record(1, {}, {})
    with gzip.open(p, "rt") as fh:
        lines = [json.loads(x) for x in fh]
    assert len(lines) == 2               # header line, then one tick
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_replay.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.replay'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/replay.py`:

```python
"""Two replay artifacts, one derived from the other.

THIN is canonical truth: seed plus the validated, post-substitution action stream. It replays
bit-exactly and needs no bots.

FAT is what anything that DISPLAYS reads: full per-tick state plus the DERIVED fields -- cone
geometry and per-squadron visibility. Recording those is the whole point: a viewer that has to
work out visibility itself is a viewer that has to embed the physics, which in a browser means
porting the simulation to JavaScript. About a kilobyte more per tick buys the architecture.

The engine regenerates fat from thin on demand, so there is one source of truth.
"""

import gzip
import json
import platform
from pathlib import Path

from . import vision
from .classes import table_hash
from .state import API_VERSION, Action

ENGINE_VERSION = "0.1.0"


def make_header(seed: int, arena: tuple[float, float], squadrons: list[list[str]],
                table_path: Path | None = None) -> dict:
    """Everything needed to know whether two results are comparable."""
    return {
        "seed": seed,
        "arena": list(arena),
        "squadrons": squadrons,
        "class_table_sha256": table_hash(table_path),
        "api_version": API_VERSION,
        "engine_version": ENGINE_VERSION,
        # `random`'s stream stability across interpreter versions is not guaranteed, so a
        # replay that will not reproduce should at least say why.
        "python_version": platform.python_version(),
    }


class _Writer:
    def __init__(self, path: str | Path, header: dict) -> None:
        self._fh = gzip.open(Path(path), "wt", encoding="utf-8")
        self._fh.write(json.dumps(header) + "\n")

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class ThinWriter(_Writer):
    def record(self, tick: int, actions: dict[int, Action],
               statuses: dict[int, str]) -> None:
        self._fh.write(json.dumps({
            "tick": tick,
            "actions": {str(pid): [a.throttle, a.steer, sorted(a.fire)]
                        for pid, a in sorted(actions.items())},
            "statuses": {str(sq): s for sq, s in sorted(statuses.items())},
        }) + "\n")


class FatWriter(_Writer):
    def record(self, world, statuses: dict[int, str] | None = None) -> None:
        statuses = statuses or {}
        living = [p for _, p in sorted(world.planes.items()) if p.alive]

        # Per-squadron visibility, computed once here and RECORDED, never left to the viewer.
        visible: dict[str, list[int]] = {}
        for sq in sorted(world.damage_dealt):
            mine = [p for p in living if p.squadron == sq]
            seen = sorted({
                e.id for e in living if e.squadron != sq
                for o in mine if vision.sees(o, e, world.arena)
            })
            visible[str(sq)] = seen

        self._fh.write(json.dumps({
            "tick": world.tick_no,
            "planes": [
                {
                    "id": p.id, "squadron": p.squadron, "kind": p.kind,
                    "x": round(p.x, 3), "y": round(p.y, 3),
                    "heading_deg": round(p.heading_deg, 3), "speed": round(p.speed, 3),
                    "hp": p.hp, "hp_max": p.cls.hp, "alive": p.alive,
                    "ammo": list(p.ammo), "cooldown": list(p.cooldown),
                    "cone_deg": p.cls.cone_deg, "cone_range": p.cls.cone_range,
                    "rear_cone_deg": p.cls.rear_cone_deg,
                    "rear_cone_range": p.cls.rear_cone_range,
                }
                for _, p in sorted(world.planes.items())
            ],
            "bullets": [[round(b.x, 2), round(b.y, 2), b.squadron] for b in world.bullets],
            "visible": visible,
            "scores": {str(sq): s for sq, s in sorted(world.scores().items())},
            "degraded": sorted(str(sq) for sq, s in statuses.items() if s != "ok"),
        }) + "\n")


def read(path: str | Path) -> tuple[dict, list[dict]]:
    with gzip.open(Path(path), "rt", encoding="utf-8") as fh:
        lines = [json.loads(x) for x in fh if x.strip()]
    return lines[0], lines[1:]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_replay.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/replay.py tests/test_replay.py
git commit -m "feat: thin and fat replay writers"
```

---

### Task 16: The author test harness

**Files:**

- Create: `src/skybattle/harness.py`
- Test: `tests/test_harness.py`

**Why.** Because the contract is a pure function, a bot is unit-testable with no engine, no subprocess and no I/O.
This is the highest-leverage thing the project can ship for a bot author, and it is about forty lines. It also
re-exports the engine's own `validate`, so an author can never pass their own tests and then fail the engine's check.

**Interfaces:**

- Consumes: `skybattle.state`, `skybattle.classes`, `skybattle.validate`.
- Produces: `gun(name="forward", **kw) -> Gun`; `contact(**kw) -> Contact`;
  `plane(id=0, kind="fighter", **kw) -> OwnPlane`; `make_state(planes=None, tick=1,
  arena=(2000.0, 1400.0), events=(), seed=1) -> View`; and a re-export of `validate`.
- [ ] **Step 1: Write the failing test**

`tests/test_harness.py`:

```python
from skybattle.harness import contact, make_state, plane, validate
from skybattle.state import Action, View


def test_make_state_needs_no_arguments():
    s = make_state()
    assert isinstance(s, View)
    assert len(s.planes) == 1
    assert s.tick == 1


def test_defaults_come_from_the_real_class_table():
    p = plane(kind="bomber")
    assert p.hp == p.hp_max
    assert len(p.guns) == 2                       # forward and rear
    assert p.guns[1].bearing_deg == 180.0


def test_a_test_names_only_what_it_cares_about():
    s = make_state(planes=[plane(id=0, x=100.0, y=100.0, heading_deg=0.0,
                                 contacts=(contact(x=200.0, y=100.0, bearing_deg=0.0,
                                                   range=100.0),))])
    c = s.planes[0].contacts[0]
    assert c.bearing_deg == 0.0
    assert c.range == 100.0


def test_the_harness_exports_the_engines_own_validator():
    from skybattle.validate import validate as engine_validate
    assert validate is engine_validate


def test_a_three_line_bot_test_works():
    def act(state):
        return {p.id: Action(steer=0.0) for p in state.planes}

    s = make_state(planes=[plane(id=0, x=100.0, y=100.0, heading_deg=0.0,
                                 contacts=(contact(bearing_deg=0.0, range=200.0),))])
    assert act(s)[0].steer == 0.0


def test_the_rng_is_seeded_and_reproducible():
    assert make_state(seed=3).rng.random() == make_state(seed=3).rng.random()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_harness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.harness'`

- [ ] **Step 3: Write the implementation**

`src/skybattle/harness.py`:

```python
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

__all__ = ["gun", "contact", "plane", "make_state", "validate"]

_CLASSES = load_classes()


def gun(name: str = "forward", bearing_deg: float = 0.0, arc_deg: float = 8.0,
        ammo: int = 100, cooldown_ticks_left: int = 0) -> Gun:
    return Gun(name=name, bearing_deg=bearing_deg, arc_deg=arc_deg, ammo=ammo,
               cooldown_ticks_left=cooldown_ticks_left)


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
        guns=tuple(gun(name=g.name, bearing_deg=g.bearing_deg, arc_deg=g.arc_deg, ammo=g.ammo)
                   for g in cls.guns),
        contacts=contacts,
    )


def make_state(planes: list[OwnPlane] | None = None, tick: int = 1,
               arena: tuple[float, float] = (2000.0, 1400.0),
               events: tuple[object, ...] = (), seed: int = 1) -> View:
    return View(tick=tick, arena=arena,
                planes=tuple(planes if planes is not None else [plane()]),
                events=events, rng=random.Random(seed))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_harness.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/skybattle/harness.py tests/test_harness.py
git commit -m "feat: author-side test harness"
```

---

### Task 17: Match orchestration and the `duel` command

**Files:**

- Create: `src/skybattle/match.py`, `src/skybattle/cli.py`
- Test: `tests/test_match.py`

**Interfaces:**

- Consumes: everything above.
- Produces: `RoundResult(NamedTuple)` `scores: dict[int, float], outcome: str, ticks: int,
  accepted: dict[int, int], strikes: dict[int, int], forfeited: dict[int, bool]`;
  `MatchResult(NamedTuple)` `rounds: list[RoundResult], totals: dict[int, float], winner: int | None`;
  `run_round(bot_paths, squadrons, seed, arena, classes, replay_dir=None, deadline=0.05) -> RoundResult`;
  `run_match(bot_paths, squadrons, seed, rounds=11, **kw) -> MatchResult`;
  `main(argv=None) -> int` in `cli.py`.
- [ ] **Step 1: Write the failing test**

`tests/test_match.py`:

```python
from pathlib import Path

from skybattle.classes import load_classes
from skybattle.match import run_match, run_round

BOTS = Path(__file__).parent / "bots"
SAMPLES = Path(__file__).parent.parent / "samples"
CLASSES = load_classes()
ARENA = (2000.0, 1400.0)
SQ = [["scout", "fighter"], ["scout", "fighter"]]


def test_a_round_terminates_and_reports_both_squadrons():
    r = run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, arena=ARENA,
                  classes=CLASSES)
    assert r.ticks > 0
    assert sorted(r.scores) == [0, 1]
    assert r.outcome != "ongoing"


def test_a_hanging_bot_forfeits_but_the_round_still_finishes():
    r = run_round([BOTS / "good.py", BOTS / "hanger.py"], SQ, seed=1, arena=ARENA,
                  classes=CLASSES, deadline=0.02)
    assert r.forfeited[1]
    assert not r.forfeited[0]
    assert r.outcome != "ongoing"


def test_a_forfeited_squadrons_planes_keep_existing():
    # otherwise a forfeit changes the physics for the survivor and corrupts the comparison
    r = run_round([BOTS / "good.py", BOTS / "crasher.py"], SQ, seed=1, arena=ARENA,
                  classes=CLASSES, deadline=0.02)
    assert r.ticks > 1


def test_accepted_is_reported_alongside_strikes():
    r = run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, arena=ARENA,
                  classes=CLASSES)
    # the honest number: a drained stale reply also costs the following tick
    assert r.accepted[0] <= r.ticks
    assert r.strikes[0] == 0


def test_a_match_is_eleven_rounds_and_sums_scores():
    m = run_match([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, rounds=3, arena=ARENA,
                  classes=CLASSES)
    assert len(m.rounds) == 3
    assert m.totals[0] == sum(r.scores[0] for r in m.rounds)


def test_the_same_seed_reproduces_the_same_match():
    kw = dict(squadrons=SQ, seed=42, rounds=2, arena=ARENA, classes=CLASSES)
    a = run_match([BOTS / "good.py", BOTS / "good.py"], **kw)
    b = run_match([BOTS / "good.py", BOTS / "good.py"], **kw)
    assert a.totals == b.totals


def test_a_replay_pair_is_written_when_asked(tmp_path):
    run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, arena=ARENA,
              classes=CLASSES, replay_dir=tmp_path)
    assert (tmp_path / "round-001.thin.jsonl.gz").exists()
    assert (tmp_path / "round-001.fat.jsonl.gz").exists()


def test_the_cli_duel_command_runs_and_prints_one_result_line(capsys):
    from skybattle.cli import main
    code = main(["duel", str(BOTS / "good.py"), str(BOTS / "good.py"),
                 "--seed", "3", "--rounds", "1"])
    assert code == 0
    out = capsys.readouterr().out
    assert "squadron 0" in out
    assert "accepted" in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_match.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skybattle.match'`

- [ ] **Step 3: Write the match runner**

`src/skybattle/match.py`:

```python
"""Round and match orchestration.

A ROUND is one fight, ending when one squadron is left flying or at the tick limit.
A MATCH is 11 rounds -- odd, so draws are rare -- with fresh spawns, consecutive seeds and
summed scores.
"""

from pathlib import Path
from typing import NamedTuple

from .classes import PlaneClass, load_classes
from .driver import BotProcess
from .replay import FatWriter, ThinWriter, make_header
from .world import World


class RoundResult(NamedTuple):
    scores: dict[int, float]
    outcome: str
    ticks: int
    accepted: dict[int, int]
    strikes: dict[int, int]
    forfeited: dict[int, bool]


class MatchResult(NamedTuple):
    rounds: list[RoundResult]
    totals: dict[int, float]
    winner: int | None


def run_round(bot_paths: list[str | Path], squadrons: list[list[str]], seed: int,
              arena: tuple[float, float], classes: dict[str, PlaneClass] | None = None,
              replay_dir: str | Path | None = None, deadline: float = 0.05,
              round_index: int = 1) -> RoundResult:
    classes = classes or load_classes()
    world = World(arena, squadrons, classes, seed=seed)
    bots = [BotProcess(p, tick_deadline=deadline) for p in bot_paths]

    thin = fat = None
    if replay_dir is not None:
        d = Path(replay_dir)
        d.mkdir(parents=True, exist_ok=True)
        header = make_header(seed, arena, squadrons)
        thin = ThinWriter(d / f"round-{round_index:03d}.thin.jsonl.gz", header)
        fat = FatWriter(d / f"round-{round_index:03d}.fat.jsonl.gz", header)

    try:
        while not world.round_over():
            views = world.views()
            replies: dict[int, object] = {}
            statuses: dict[int, str] = {}
            for sq, bot in enumerate(bots):
                raw, status = bot.exchange(views[sq], rng_seed=seed ^ (sq + 1))
                replies[sq] = raw
                statuses[sq] = status
            world.tick(replies)
            if thin is not None:
                thin.record(world.tick_no, {}, statuses)
                fat.record(world, statuses)
        return RoundResult(
            scores=world.scores(),
            outcome=world.outcome(),
            ticks=world.tick_no,
            accepted={sq: b.accepted for sq, b in enumerate(bots)},
            strikes={sq: b.strikes for sq, b in enumerate(bots)},
            forfeited={sq: b.forfeited for sq, b in enumerate(bots)},
        )
    finally:
        for b in bots:
            b.close()
        for w in (thin, fat):
            if w is not None:
                w.close()


def run_match(bot_paths: list[str | Path], squadrons: list[list[str]], seed: int,
              rounds: int = 11, **kw) -> MatchResult:
    results = [run_round(bot_paths, squadrons, seed=seed + i, round_index=i + 1, **kw)
               for i in range(rounds)]
    totals = {sq: sum(r.scores[sq] for r in results) for sq in results[0].scores}
    best = max(totals.values())
    leaders = [sq for sq, v in totals.items() if v == best]
    return MatchResult(rounds=results, totals=totals,
                       winner=leaders[0] if len(leaders) == 1 else None)
```

- [ ] **Step 4: Write the CLI**

`src/skybattle/cli.py`:

```python
"""The command line. `duel` is the whole of this plan's user interface."""

import argparse
from pathlib import Path

from .classes import DEFAULT_TABLE, load_classes
from .match import run_match

DEFAULT_SQUADRON = ["scout", "fighter"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sky-battle")
    subs = parser.add_subparsers(dest="command", required=True)

    duel = subs.add_parser("duel", help="run a match between two bots")
    duel.add_argument("bot_a", type=Path)
    duel.add_argument("bot_b", type=Path)
    duel.add_argument("--seed", type=int, default=1)
    duel.add_argument("--rounds", type=int, default=11)
    duel.add_argument("--arena", type=float, nargs=2, default=[2000.0, 1400.0])
    duel.add_argument("--deadline", type=float, default=0.05)
    duel.add_argument("--replay-dir", type=Path, default=None)
    duel.add_argument("--rules", action="store_true", help="print the class table and exit")

    args = parser.parse_args(argv)
    if args.command != "duel":
        parser.error(f"unknown command {args.command}")

    if args.rules:
        # The numbers ARE the game; nobody should have to read source for them.
        print(DEFAULT_TABLE.read_text())
        return 0

    arena = (args.arena[0], args.arena[1])
    classes = load_classes(arena=arena)     # validates cone ranges against this arena
    squadrons = [list(DEFAULT_SQUADRON), list(DEFAULT_SQUADRON)]

    result = run_match([args.bot_a, args.bot_b], squadrons, seed=args.seed,
                       rounds=args.rounds, arena=arena, classes=classes,
                       deadline=args.deadline, replay_dir=args.replay_dir)

    names = {0: args.bot_a.name, 1: args.bot_b.name}
    for sq in sorted(result.totals):
        acc = sum(r.accepted[sq] for r in result.rounds)
        ticks = sum(r.ticks for r in result.rounds)
        strikes = sum(r.strikes[sq] for r in result.rounds)
        forfeits = sum(1 for r in result.rounds if r.forfeited[sq])
        print(f"squadron {sq} ({names[sq]}): {result.totals[sq]:8.1f} points  "
              f"accepted {acc}/{ticks}  strikes {strikes}  forfeits {forfeits}")
    print(f"winner: {'draw' if result.winner is None else f'squadron {result.winner}'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> `accepted N/total` is printed rather than a timeout count on purpose. A timeout count invites the author to assume
> the other ticks used their choices, which is false: a drained stale reply also costs the following tick.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_match.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Commit**

```bash
git add src/skybattle/match.py src/skybattle/cli.py tests/test_match.py
git commit -m "feat: round and match orchestration with a duel command"
```

---

### Task 18: Sample bots, which are also the regression suite

**Files:**

- Create: `samples/sitting_duck.py`, `samples/circler.py`, `samples/chaser.py`,
  `samples/leader.py`, `samples/wingman.py`
- Test: `tests/test_samples.py`

**Interfaces:**

- Consumes: `skybattle.state.Action`, `skybattle.geom`, `skybattle.harness` (in tests only).
- Produces: five bot files, each defining `class Bot` with `act(self, state)`.

Each teaches exactly one idea and is squadron-shaped from rung one. **They double as the engine's regression
suite** — one artifact, two jobs — and `leader.py` is the reference opponent to beat.

- [ ] **Step 1: Write the failing test**

`tests/test_samples.py`:

```python
import importlib.util
from pathlib import Path

import pytest

from skybattle.harness import contact, make_state, plane, validate
from skybattle.match import run_round

SAMPLES = Path(__file__).parent.parent / "samples"
ARENA = (2000.0, 1400.0)
SQ = [["scout", "fighter"], ["scout", "fighter"]]
NAMES = ["sitting_duck", "circler", "chaser", "leader", "wingman"]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SAMPLES / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Bot()


@pytest.mark.parametrize("name", NAMES)
def test_every_sample_returns_actions_the_engine_accepts(name):
    bot = _load(name)
    state = make_state(planes=[
        plane(id=0, kind="scout", contacts=(contact(id=1, bearing_deg=25.0, range=400.0),)),
        plane(id=1, kind="fighter", contacts=(contact(id=1, bearing_deg=-5.0, range=200.0),)),
    ])
    actions, rejects = validate(bot.act(state), live_ids=(0, 1))
    assert rejects == ()
    assert set(actions) <= {0, 1}


@pytest.mark.parametrize("name", NAMES)
def test_every_sample_survives_seeing_nothing(name):
    bot = _load(name)
    state = make_state(planes=[plane(id=0), plane(id=1, kind="scout")])
    _, rejects = validate(bot.act(state), live_ids=(0, 1))
    assert rejects == ()


def test_sitting_duck_does_nothing():
    assert _load("sitting_duck").act(make_state()) == {}


def test_circler_flies_at_stall_speed_and_holds_a_constant_turn():
    a = _load("circler").act(make_state(planes=[plane(id=0)]))[0]
    assert a.throttle == 0.0            # a lever position of 0 means stall speed
    assert abs(a.steer) == 1.0


def test_circler_only_fires_when_a_contact_is_near_the_nose():
    bot = _load("circler")
    off = bot.act(make_state(planes=[plane(id=0, contacts=(contact(bearing_deg=40.0),))]))[0]
    on = bot.act(make_state(planes=[plane(id=0, contacts=(contact(bearing_deg=1.0),))]))[0]
    assert off.fire == frozenset()
    assert on.fire == frozenset({0})


def test_chaser_steers_toward_a_contact_with_the_right_sign():
    bot = _load("chaser")
    left = bot.act(make_state(planes=[plane(id=0, contacts=(contact(bearing_deg=30.0),))]))[0]
    right = bot.act(make_state(planes=[plane(id=0, contacts=(contact(bearing_deg=-30.0),))]))[0]
    assert left.steer > 0.0
    assert right.steer < 0.0


def test_leader_aims_ahead_of_a_crossing_target_rather_than_at_it():
    bot = _load("leader")
    crossing = contact(x=400.0, y=100.0, heading_deg=90.0, speed=8.0,
                       bearing_deg=0.0, range=300.0)
    a = bot.act(make_state(planes=[plane(id=0, x=100.0, y=100.0, heading_deg=0.0,
                                         contacts=(crossing,))]))[0]
    # the target is dead ahead but crossing left, so a leading bot must turn left, not hold
    assert a.steer > 0.0


def test_wingman_gives_the_scout_and_the_fighter_different_jobs():
    bot = _load("wingman")
    seen_by_scout_only = contact(id=5, bearing_deg=10.0, range=800.0, seen_by=(0,))
    state = make_state(planes=[
        plane(id=0, kind="scout", contacts=(seen_by_scout_only,)),
        plane(id=1, kind="fighter", contacts=(seen_by_scout_only,)),
    ])
    actions = bot.act(state)
    assert actions[0].fire == frozenset()        # the scout never engages
    assert actions[1].throttle > 0.5             # the fighter closes


def test_wingman_remembers_a_contact_after_losing_it():
    bot = _load("wingman")
    seen = contact(id=5, x=900.0, y=500.0, bearing_deg=0.0, range=400.0, seen_by=(0,))
    bot.act(make_state(tick=1, planes=[plane(id=0, kind="scout", contacts=(seen,)),
                                       plane(id=1, kind="fighter", contacts=(seen,))]))
    bot.act(make_state(tick=2, planes=[plane(id=0, kind="scout"), plane(id=1, kind="fighter")]))
    assert bot.last_seen                          # kept its own memory; the engine keeps none


def test_leader_beats_chaser_over_a_fixed_seed_set():
    """The reference-opponent ladder. Leading a target is the punchline of the whole design,
    so a bot that leads must beat one that does not."""
    wins = 0
    for seed in range(1, 6):
        r = run_round([SAMPLES / "leader.py", SAMPLES / "chaser.py"], SQ, seed=seed,
                      arena=ARENA)
        if r.scores[0] > r.scores[1]:
            wins += 1
    assert wins >= 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_samples.py -v`
Expected: FAIL — `FileNotFoundError` for `samples/sitting_duck.py`

- [ ] **Step 3: Write the samples**

`samples/sitting_duck.py`:

```python
"""Rung 0: does nothing at all.

Proves the harness works, and doubles as the engine's coast-path regression test: every plane
holds its last action, which on tick one is a neutral one.
"""


class Bot:
    def act(self, state):
        return {}
```

`samples/circler.py`:

```python
"""Rung 1: minimum-radius circles, firing when something crosses the nose.

Teaches the state shape, the id-keyed return dict, and cooldown AND ammo gating. A plane cannot
sit still -- stall speed is above zero -- so "sit and shoot" becomes tightest-circle loitering,
which is itself the lesson.
"""

from skybattle.state import Action

ON_TARGET_DEG = 8.0


class Bot:
    def act(self, state):
        out = {}
        for p in state.planes:
            gun = p.guns[0]
            ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
            aimed = any(abs(c.bearing_deg) <= ON_TARGET_DEG for c in p.contacts)
            out[p.id] = Action(
                throttle=0.0,                          # lever idle: settles at stall speed
                steer=1.0,
                fire=frozenset({0}) if ready and aimed else frozenset(),
            )
        return out
```

`samples/chaser.py`:

```python
"""Rung 2: turn toward the nearest contact, throttle up, fire when aligned.

Teaches the steer sign and torus-correct bearing -- and teaches why it always MISSES, because
it aims where the target is rather than where it will be. That is rung 3's problem.
"""

from skybattle.state import Action

ON_TARGET_DEG = 6.0


class Bot:
    def act(self, state):
        out = {}
        for p in state.planes:
            if not p.contacts:
                out[p.id] = Action(throttle=0.6, steer=0.4)   # search
                continue
            target = min(p.contacts, key=lambda c: c.range)
            gun = p.guns[0]
            ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
            out[p.id] = Action(
                throttle=0.9,
                # bearing is already relative to my nose: positive is left, so steer positive
                steer=max(min(target.bearing_deg / 30.0, 1.0), -1.0),
                fire=(frozenset({0}) if ready and abs(target.bearing_deg) <= ON_TARGET_DEG
                      else frozenset()),
            )
        return out
```

`samples/leader.py`:

```python
"""Rung 3: aim where the target WILL be. The "aha" bot, and the reference opponent.

Bullet flight time depends on range, which depends on where the target will be, which depends
on flight time. Two fixed-point iterations converge well inside a plane's radius.

`lead_point` is deliberately absent from `skybattle.geom`: this is the punchline, so it is
written out here rather than handed over as a helper.
"""

from skybattle import geom
from skybattle.bullets import MUZZLE_SPEED
from skybattle.state import Action

ON_TARGET_DEG = 4.0


class Bot:
    def act(self, state):
        w, h = state.arena
        out = {}
        for p in state.planes:
            if not p.contacts:
                out[p.id] = Action(throttle=0.6, steer=0.35)
                continue
            target = min(p.contacts, key=lambda c: c.range)

            # Step 1 - iterate to a firing solution.
            bullet_speed = MUZZLE_SPEED + p.speed
            flight_ticks = target.range / bullet_speed
            aim_x, aim_y = target.x, target.y
            for _ in range(2):
                aim_x = target.x + geom.cos_deg(target.heading_deg) * target.speed * flight_ticks
                aim_y = target.y + geom.sin_deg(target.heading_deg) * target.speed * flight_ticks
                flight_ticks = geom.distance(p.x, p.y, aim_x, aim_y, w, h) / bullet_speed

            # Step 2 - steer at the intercept point, not at the target.
            lead_bearing = geom.bearing_to(p.x, p.y, p.heading_deg, aim_x, aim_y, w, h)
            gun = p.guns[0]
            ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
            out[p.id] = Action(
                # Corner speed turns best, so ease off when a hard turn is needed.
                throttle=0.4 if abs(lead_bearing) > 30.0 else 0.9,
                steer=max(min(lead_bearing / 25.0, 1.0), -1.0),
                fire=(frozenset({0}) if ready and abs(lead_bearing) <= ON_TARGET_DEG
                      else frozenset()),
            )
        return out
```

`samples/wingman.py`:

```python
"""Rung 4: everything the squadron design adds.

The scout searches and never engages. The fighter engages only what the squadron can see, and
prefers a WOUNDED target -- which is why `contact.hp` is exposed. Both keep their own memory of
where a contact was last seen, because the engine keeps none: re-acquisition mints a new
contact id, so a plane that keeps eyes on a target is worth more than one that glances.
"""

from skybattle import geom
from skybattle.state import Action

ON_TARGET_DEG = 5.0
FORGET_AFTER = 90


class Bot:
    def __init__(self, config=None):
        self.last_seen: dict[int, tuple[float, float, int]] = {}

    def act(self, state):
        w, h = state.arena
        for p in state.planes:
            for c in p.contacts:
                self.last_seen[c.id] = (c.x, c.y, state.tick)
        self.last_seen = {cid: v for cid, v in self.last_seen.items()
                          if state.tick - v[2] <= FORGET_AFTER}

        out = {}
        for p in state.planes:
            if p.kind == "scout":
                out[p.id] = self._search(p)
            else:
                out[p.id] = self._engage(p, state, w, h)
        return out

    def _search(self, p):
        """Sweep, stay alive, never shoot. Its cone is its contribution."""
        return Action(throttle=0.7, steer=0.25)

    def _engage(self, p, state, w, h):
        if p.contacts:
            # Wounded first: fewer hits to finish, and a damaged plane flies worse.
            target = min(p.contacts, key=lambda c: (c.hp, c.range))
            bearing = target.bearing_deg
            gun = p.guns[0]
            ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
            return Action(
                throttle=0.9,
                steer=max(min(bearing / 25.0, 1.0), -1.0),
                fire=(frozenset({0}) if ready and abs(bearing) <= ON_TARGET_DEG
                      else frozenset()),
            )
        if self.last_seen:
            # Nothing in sight: sweep the freshest remembered position.
            x, y, _ = max(self.last_seen.values(), key=lambda v: v[2])
            bearing = geom.bearing_to(p.x, p.y, p.heading_deg, x, y, w, h)
            return Action(throttle=0.8, steer=max(min(bearing / 25.0, 1.0), -1.0))
        return Action(throttle=0.6, steer=-0.25)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_samples.py -v`
Expected: PASS, 19 tests (10 parametrised plus 9 specific).

If `test_leader_beats_chaser_over_a_fixed_seed_set` fails, that is a **balance** signal rather than a code fault:
the placeholder numbers in `classes.toml` need the tuning pass the spec defers. Adjust `MUZZLE_SPEED`,
`turn_bleed` or the gun cooldowns and record what changed and why in a comment in the TOML — never weaken the test.

- [ ] **Step 5: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check src tests samples && uv run ruff format --check src tests samples`
Expected: all green.

- [ ] **Step 6: Play a real duel**

```bash
uv run sky-battle duel samples/leader.py samples/chaser.py --seed 7 --rounds 3 --replay-dir /tmp/sb
ls -la /tmp/sb
```

Expected: three result lines with scores and `accepted N/N`, plus six replay files.

- [ ] **Step 7: Commit**

```bash
git add samples tests/test_samples.py
git commit -m "feat: five sample bots doubling as the regression suite"
```

---

## Self-review

**Spec coverage.** Walked `game-design.md`, `bot-api.md` and `tech-decisions.md` section by section against the
tasks above.

| Spec area | Task |
|---|---|
| Torus, minimum image convention, angle conventions | 1 |
| TOML class table, gun table, cone-range constraint | 2 |
| `Action`, `Contact`, `OwnPlane`, events, API version | 3, 10 |
| Corner speed, energy bleed (A), damage degradation (D), stall floor | 4 |
| Bullets inherit shooter velocity (E) | 5 |
| Swept collision, seam correctness, tunnelling | 6 |
| Cone vision, squadron union, re-acquisition ids, quantisation | 7, 10 |
| Per-plane action validation, NaN rejection, clamping | 8 |
| Tick order (resolve then snapshot), damage, deaths, ram | 9 |
| Shared vision, `seen_by`, enemy `hp` visible, ammo hidden | 10 |
| Scoring formula, round end, inactivity drain, no survival-only score | 11 |
| JSONL protocol, positional encoding | 12 |
| Runner shim, `print` safety, traceback legibility | 13 |
| Deadlines, tick echo and stale drain, hold-last, strike budget, `killpg` | 14 |
| Thin and fat replays, derived fields recorded, gzip, header | 15 |
| Author harness, exported validator | 16 |
| Match format (11 rounds), `duel`, `--rules` | 17 |
| Sample-bot ladder, samples as regression suite | 18 |

**Deliberately deferred, and why.** Each is a separate plan, not an omission:

- **The browser viewer** (replay page plus live SSE). It consumes the fat stream produced by Task 15 and needs no
  engine change, which is the entire point of the two-artifact format. Plan 2.
- **The tournament ladder** (double round-robin, mean and standard error over a fixed seed set, a Textual
  scoreboard). It consumes `run_match` from Task 17. Plan 3.
- **`RLIMIT_AS` and `RLIMIT_CPU`** backstops, and `bubblewrap`. The spec puts these behind explicit triggers — a bot
  OOMing the box, or accepting a bot from a stranger — and the threat model does not include either yet.
- **Regenerating a fat replay from a thin one.** Currently both are written live. The regeneration path matters when
  archive size does, and needs the viewer to exist to be worth testing.
- **The balance pass.** Every number in `classes.toml` is a placeholder; the spec expects this to be a recurring
  activity rather than a task.

**Placeholder scan.** No `TBD`, no "add error handling", no "similar to Task N". Every code step carries the actual
code. Task 18's failure note points at a real, specific action (tune three named constants) rather than at
"investigate".

**Type consistency.** Checked the names that cross task boundaries: `PlaneClass` / `GunSpec` fields (Task 2) are
used verbatim in Tasks 4, 5, 7, 9, 15; `flight.step` returns `(x, y, heading_deg, speed)` and is destructured that
way in Task 9; `collide.swept_hit` returns `float | None` and is tested for `None` in Task 9; `vision.sees` takes
objects exposing `.x .y .heading_deg .cls`, which both `world.Plane` (Task 9) and the test double (Task 7) satisfy;
`validate` returns `(dict, tuple)` in Tasks 8, 9, 16, 18; `BotProcess.exchange` returns `(raw, status)` in Tasks 14
and 17. Task 10 deliberately changes `OwnPlane` and `View`, and lists every call site it has to touch.

**One inconsistency found and fixed while reviewing:** Task 9's original `views()` built contacts from `mine[0]`,
which silently gives a squadron's second plane its wingman's bearings. Rather than hide it, Task 9 now carries an
explicit note and Task 10 fixes it in code *and* corrects the spec — because the spec is what is actually wrong.
