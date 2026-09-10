from skybattle.classes import load_classes
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


def test_a_round_starting_inside_the_disc_is_a_hit_even_if_it_does_not_exit():
    # A slow round deep inside a large disc: both quadratic roots fall outside [0, 1], so
    # the solver alone would report a miss for a round that never left the plane.
    t = swept_hit(100.0, 100.0, 50.0, 100.0, 100.0, 1.0, 0.0, W, H)
    assert t == 0.0


def test_a_bigger_plane_is_an_easier_target():
    """Radius is per class: a bomber presents a larger target than a scout.

    Same shot geometry, offset just outside the scout's radius and inside the bomber's.
    """
    cs = load_classes()
    assert cs["scout"].radius < cs["fighter"].radius < cs["bomber"].radius
    offset = (cs["scout"].radius + cs["bomber"].radius) / 2.0
    for kind, expect_hit in (("scout", False), ("bomber", True)):
        r = cs[kind].radius
        t = swept_hit(500.0, 500.0 + offset, r, 400.0, 500.0, 200.0, 0.0, 2000.0, 2000.0)
        assert (t is not None) is expect_hit, f"{kind} radius {r} vs offset {offset}"
