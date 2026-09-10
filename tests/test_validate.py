import math
import time

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
    actions, _rejects = validate({0: Action(throttle=math.nan), 1: Action(throttle=1.0)}, LIVE)
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


def test_a_reply_with_absurdly_many_entries_is_rejected_cheaply():
    """A plausible author bug - 200k keys - must not cost the round."""
    raw = {i: Action() for i in range(200_000)}
    start = time.monotonic()
    actions, rejects = validate(raw, (0, 1))
    assert time.monotonic() - start < 0.5
    assert actions == {}
    assert any("too_many_actions" in r for _, r in rejects)
