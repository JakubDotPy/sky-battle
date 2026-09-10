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


def test_steer_sign_positive_is_left_ccw_positive():
    """Positive steer turns left.

    The frame is heading 0 = east, CCW positive, y-up, so increasing heading is a left turn.
    This sign is chosen so that steer and bearing share a convention: a bot can write
    `steer = clamp(contact.bearing_deg / k)` and turn toward the target with no negation.
    """
    c = CLASSES["fighter"]
    _, _, left, _ = flight.step(c, 500.0, 500.0, 0.0, 5.0, 100, 100, 0.0, 1.0, ARENA)
    _, _, right, _ = flight.step(c, 500.0, 500.0, 0.0, 5.0, 100, 100, 0.0, -1.0, ARENA)
    assert 0.0 < left < 90.0          # heading increased
    assert right > 270.0              # heading decreased and wrapped below zero


def test_position_wraps_across_the_seam():
    c = CLASSES["fighter"]
    x, _, _, _ = flight.step(c, 998.0, 500.0, 0.0, 5.0, 100, 100, 0.0, 0.0, ARENA)
    assert 0.0 <= x < 10.0
