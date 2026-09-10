from dataclasses import dataclass

import pytest

from skybattle import geom, vision
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
    """300u astern: outside the bomber's 220u bubble, inside its 350u rear cone -- so this
    can only be the rear cone catching it, not the bubble."""
    o = _p(kind="bomber", id=0, x=400.0, y=100.0, heading_deg=0.0)
    t = _p(id=1, x=100.0, y=100.0, heading_deg=0.0)
    assert vision.sees(o, t, ARENA)


def test_the_scouts_cone_is_wider_than_the_fighters():
    off_axis_t = _p(id=1, x=100.0 + 200.0, y=100.0 + 200.0, heading_deg=0.0)
    scout = _p(kind="scout", id=0, x=100.0, y=100.0, heading_deg=0.0)
    fighter = _p(id=0, x=100.0, y=100.0, heading_deg=0.0)
    assert vision.sees(scout, off_axis_t, ARENA)
    assert not vision.sees(fighter, off_axis_t, ARENA)


def test_a_cone_sees_across_the_seam():
    """310u wrapped: outside the fighter's 150u bubble, inside its 600u forward cone -- so
    this can only be the cone catching it, not the bubble."""
    o = _p(id=0, x=1990.0, y=100.0, heading_deg=0.0)
    t = _p(id=1, x=300.0, y=100.0, heading_deg=0.0)
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


def test_an_enemy_astern_and_close_is_seen_by_the_bubble_not_the_cone():
    """Fighter has no rear cone, so a target dead astern can only be caught by the bubble."""
    cls = CLASSES["fighter"]
    o = _p(kind="fighter", id=0, x=1000.0, y=1000.0, heading_deg=0.0)
    close = _p(id=1, x=1000.0 - 30.0, y=1000.0, heading_deg=0.0)      # 30u astern, inside bubble
    far = _p(id=1, x=1000.0 - (cls.bubble_range + 20.0), y=1000.0, heading_deg=0.0)  # just outside

    assert vision.sees(o, close, ARENA)
    assert not vision.sees(o, far, ARENA)


def test_the_bubble_sees_across_the_torus_seam():
    """Target sits 20u away across the seam, off-axis so the forward cone cannot be the cause."""
    o = _p(kind="fighter", id=0, x=10.0, y=1000.0, heading_deg=90.0)   # facing north
    t = _p(id=1, x=1990.0, y=1000.0, heading_deg=0.0)                  # 20u west, wrapped

    naive = ((t.x - o.x) ** 2 + (t.y - o.y) ** 2) ** 0.5
    assert naive > 1000.0            # the un-wrapped straight-line distance is nowhere close
    assert geom.distance(o.x, o.y, t.x, t.y, W, H) == pytest.approx(20.0)  # wrapped, it is 20u
    assert vision.sees(o, t, ARENA)


def test_the_bomber_has_the_biggest_bubble_and_the_smallest_cone():
    """The deliberate inversion: many crew and windows means worst at searching, best at
    already knowing what is on top of it."""
    assert CLASSES["bomber"].bubble_range > CLASSES["scout"].bubble_range
    assert CLASSES["bomber"].bubble_range > CLASSES["fighter"].bubble_range
    assert CLASSES["scout"].cone_range > CLASSES["bomber"].cone_range


def test_the_bubble_decision_is_quantised_like_in_cones():
    """Same reasoning as the cone-range quantisation test: the decision and the reported range
    must use the identical rounding, or a replay can diverge across machines."""
    cls = CLASSES["fighter"]
    o = _p(kind="fighter", id=0, x=1000.0, y=1000.0, heading_deg=0.0)
    # 0.04 past the bubble, astern so the (rear-cone-less) fighter's cone cannot catch it either.
    t = _p(id=1, x=1000.0 - (cls.bubble_range + 0.04), y=1000.0, heading_deg=0.0)

    raw = geom.distance(o.x, o.y, t.x, t.y, W, H)
    assert raw > cls.bubble_range                                     # genuinely outside, unrounded
    assert round(raw, vision.QUANT_RANGE) <= cls.bubble_range          # but rounds back inside

    assert vision.sees(o, t, ARENA)                                    # the rounded decision wins


def test_the_range_round_admits_a_target_the_raw_distance_would_exclude():
    """`in_cone` must decide on the ROUNDED range, not the raw one, or a replay can diverge
    across machines whose libm disagrees in the last bit.

    This is not merely "on the boundary": it is a case where the two decisions genuinely
    differ. 600.04 units is 0.04 past the fighter's 600.0-unit cone -- a raw comparison must
    exclude it -- but QUANT_RANGE rounds distance to one decimal place, so the reported range
    rounds DOWN to 600.0 and the target is admitted. If `in_cone` ever compared the raw
    `geom.distance` instead, this target would flip to invisible.
    """
    cls = CLASSES["fighter"]
    o = _p(id=0, x=100.0, y=100.0, heading_deg=0.0)
    t = _p(id=1, x=100.0 + cls.cone_range + 0.04, y=100.0, heading_deg=0.0)

    raw = geom.distance(o.x, o.y, t.x, t.y, W, H)
    assert raw > cls.cone_range                                    # genuinely outside, unrounded
    assert round(raw, vision.QUANT_RANGE) <= cls.cone_range         # but rounds back inside

    assert vision.sees(o, t, ARENA)                                 # the rounded decision wins


def test_visibility_decision_uses_the_same_rounding_as_the_reported_values():
    """The decision and the report must agree, and both must be platform-stable.

    geom.distance and geom.bearing_to bottom out in libm, so an unrounded boundary comparison
    could flip visibility between machines and diverge a replay.
    """
    cls = CLASSES["fighter"]
    o = _p(id=0, x=100.0, y=100.0, heading_deg=0.0)
    # Exactly at maximum cone range, dead ahead.
    t = _p(id=1, x=100.0 + cls.cone_range, y=100.0, heading_deg=0.0)
    assert vision.sees(o, t, ARENA)

    out = vision.build_contacts(o, {1: (0,)}, {1: t}, {1: 1}, ARENA)
    assert out[0].range == round(out[0].range, vision.QUANT_RANGE)
    assert out[0].range <= cls.cone_range
