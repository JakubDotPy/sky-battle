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


def test_trig_table_entries_are_platform_stable():
    # The table avoids libm, but is BUILT with libm, so entries are rounded to a fixed number
    # of decimal places: a 1-ULP disagreement between platforms collapses to the same double.
    for a in (0.0, 17.0, 45.0, 123.456, 271.0, 359.9):
        for value in (geom.sin_deg(a), geom.cos_deg(a)):
            assert value == round(value, geom._TABLE_DP)
