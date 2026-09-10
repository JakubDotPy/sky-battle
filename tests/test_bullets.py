import math
import random
import statistics

import pytest

from skybattle import bullets, geom
from skybattle.classes import load_classes

ARENA = (1000.0, 1000.0)
CLASSES = load_classes()


def _fwd(kind="fighter"):
    return CLASSES[kind].guns[0]


def test_bullet_inherits_shooter_velocity():
    # Zero out dispersion: this is about the velocity sum, not scatter.
    gun = _fwd()._replace(dispersion_deg=0.0)
    slow = bullets.spawn(gun, 0, 0, 0, 500.0, 500.0, 0.0, 0.0, random.Random(1))
    fast = bullets.spawn(gun, 0, 0, 0, 500.0, 500.0, 0.0, 8.0, random.Random(1))
    assert math.hypot(fast.vx, fast.vy) > math.hypot(slow.vx, slow.vy)
    assert math.hypot(fast.vx, fast.vy) == pytest.approx(gun.muzzle_speed + 8.0)


def test_a_rear_gun_throws_slower_as_the_plane_runs_away():
    """Inherited velocity is a VECTOR sum, so a bomber's own motion subtracts from its rear
    rounds. This was a real bug: a scalar add made them 1.73x too fast and made them speed UP
    as the bomber accelerated, when physically they should get SLOWER."""
    rear = CLASSES["bomber"].guns[1]._replace(dispersion_deg=0.0)
    rng = random.Random(1)
    slow = bullets.spawn(rear, 1, 0, 0, 500.0, 500.0, 0.0, 0.0, rng)
    fast = bullets.spawn(rear, 1, 0, 0, 500.0, 500.0, 0.0, 5.0, rng)
    assert math.hypot(fast.vx, fast.vy) < math.hypot(slow.vx, slow.vy)


def test_a_forward_gun_still_throws_faster_when_the_plane_is_fast():
    fwd = CLASSES["fighter"].guns[0]._replace(dispersion_deg=0.0)
    rng = random.Random(1)
    slow = bullets.spawn(fwd, 0, 0, 0, 500.0, 500.0, 0.0, 0.0, rng)
    fast = bullets.spawn(fwd, 0, 0, 0, 500.0, 500.0, 0.0, 8.0, rng)
    assert math.hypot(fast.vx, fast.vy) > math.hypot(slow.vx, slow.vy)


def test_rear_gun_fires_astern():
    # Zero out dispersion: this test is about the fixed mount's bearing, not its precision.
    rear = CLASSES["bomber"].guns[1]._replace(dispersion_deg=0.0)
    b = bullets.spawn(rear, 1, 0, 0, 500.0, 500.0, 0.0, 0.0, random.Random(1))
    assert b.vx < 0.0                       # heading east, rear gun shoots west
    assert b.vy == pytest.approx(0.0, abs=1e-9)


def test_bullet_carries_its_gun_damage_and_provenance():
    b = bullets.spawn(_fwd(), 0, 7, 1, 0.0, 0.0, 0.0, 0.0, random.Random(1))
    assert b.damage == _fwd().damage
    assert b.owner_id == 7
    assert b.squadron == 1
    assert b.gun == 0


def test_advance_moves_and_wraps():
    b = bullets.spawn(_fwd(), 0, 0, 0, 995.0, 500.0, 0.0, 0.0, random.Random(1))
    nxt = bullets.advance(b, ARENA)
    assert nxt is not None
    assert nxt.x < 100.0                    # wrapped past the seam


def test_bullet_expires():
    b = bullets.spawn(_fwd(), 0, 0, 0, 500.0, 500.0, 0.0, 0.0,
                      random.Random(1))._replace(ticks_left=1)
    assert bullets.advance(b, ARENA) is None


def test_dispersion_stays_inside_the_arc():
    """Every round leaves within the gun's dispersion of its fixed mount."""
    fwd = CLASSES["fighter"].guns[0]
    rng = random.Random(1)
    for _ in range(500):
        b = bullets.spawn(fwd, 0, 0, 0, 500.0, 500.0, 0.0, 0.0, rng)
        off = abs(geom.angle_diff(math.degrees(math.atan2(b.vy, b.vx)), 0.0))
        assert off <= fwd.dispersion_deg / 2.0 + 1e-9


def test_a_wider_gun_groups_worse():
    """Dispersion is precision: the rear mount scatters more than a fixed forward gun."""
    def spread(gun):
        rng = random.Random(7)
        offs = []
        for _ in range(2000):
            b = bullets.spawn(gun, 0, 0, 0, 500.0, 500.0, 0.0, 0.0, rng)
            base = gun.bearing_deg
            offs.append(geom.angle_diff(math.degrees(math.atan2(b.vy, b.vx)), base))
        return statistics.pstdev(offs)
    assert spread(CLASSES["bomber"].guns[1]) > spread(CLASSES["bomber"].guns[0])


def test_the_rear_gun_fires_straight_astern_not_aimed():
    """No aiming: a rear mount points backwards, full stop."""
    rear = CLASSES["bomber"].guns[1]
    rng = random.Random(3)
    offs = []
    for _ in range(400):
        b = bullets.spawn(rear, 1, 0, 0, 500.0, 500.0, 0.0, 0.0, rng)
        fired = math.degrees(math.atan2(b.vy, b.vx))
        offs.append(geom.angle_diff(fired, 180.0))
    assert abs(sum(offs) / len(offs)) < 1.0        # centred on the mount, not on any target


def test_a_zero_dispersion_gun_fires_exactly_along_its_mount():
    perfect = CLASSES["fighter"].guns[0]._replace(dispersion_deg=0.0)
    b = bullets.spawn(perfect, 0, 0, 0, 500.0, 500.0, 90.0, 0.0, random.Random(5))
    assert math.degrees(math.atan2(b.vy, b.vx)) % 360.0 == pytest.approx(90.0, abs=1e-9)


def test_dispersion_is_reproducible_from_the_seed():
    fwd = CLASSES["fighter"].guns[0]

    def shots(seed):
        rng = random.Random(seed)
        return [bullets.spawn(fwd, 0, 0, 0, 500.0, 500.0, 0.0, 0.0, rng).vy for _ in range(20)]
    assert shots(11) == shots(11)
    assert shots(11) != shots(12)


def test_a_faster_plane_throws_its_rounds_further():
    """Lifetime is in ticks and rounds inherit the shooter's velocity, so speed extends reach
    as well as shortening flight time.

    The distance comparison alone does NOT prove `spawn` reads the gun's own `lifetime_ticks`:
    it would hold just as well for any hardcoded positive constant (e.g. the old, deleted
    BULLET_LIFETIME=40). Pinning the tick count travelled to `fwd.lifetime_ticks - 1` (the
    round expires once `ticks_left` hits 1, so it moves lifetime_ticks - 1 times) closes that
    gap: a hardcoded 40 would travel 39 ticks, not 17.
    """
    fwd = CLASSES["fighter"].guns[0]

    def distance(speed):
        rng = random.Random(1)
        b = bullets.spawn(fwd, 0, 0, 0, 0.0, 500.0, 0.0, speed, rng)
        total = 0.0
        ticks = 0
        while b is not None:
            step = math.hypot(b.vx, b.vy)
            b = bullets.advance(b, (100000.0, 100000.0))
            if b is not None:
                total += step
                ticks += 1
        return total, ticks

    slow_total, slow_ticks = distance(0.0)
    fast_total, fast_ticks = distance(8.0)
    assert fast_total > slow_total
    assert slow_ticks == fwd.lifetime_ticks - 1
    assert fast_ticks == fwd.lifetime_ticks - 1


def test_each_gun_has_its_own_reach():
    """Reach is per gun: the bomber's rear mount does not throw as far as a scout's gun."""
    assert CLASSES["scout"].guns[0].lifetime_ticks > CLASSES["bomber"].guns[1].lifetime_ticks


def test_spawn_reads_the_guns_own_lifetime_not_a_hardcoded_constant():
    """The test above only checks the table; this checks the wiring `bullets.spawn` actually
    uses `gun.lifetime_ticks` rather than some fixed value (the old BULLET_LIFETIME=40)."""
    rear = CLASSES["bomber"].guns[1]
    b = bullets.spawn(rear, 1, 0, 0, 500.0, 500.0, 0.0, 0.0, random.Random(1))
    assert b.ticks_left == rear.lifetime_ticks
