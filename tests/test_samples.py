import importlib.util
from pathlib import Path

import pytest

from skybattle.harness import contact, make_state, plane, validate
from skybattle.match import run_round

SAMPLES = Path(__file__).parent.parent / "samples"
ARENA = (2000.0, 2000.0)  # cone_range 900 needs half the shorter dimension >= 900
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
    if name == "sitting_duck":
        assert actions == {}          # rung 0: legitimately does nothing at all
    else:
        assert set(actions) == {0, 1}  # every plane actually gets an action, not just a subset


@pytest.mark.parametrize("name", NAMES)
def test_every_sample_survives_seeing_nothing(name):
    bot = _load(name)
    state = make_state(planes=[plane(id=0), plane(id=1, kind="scout")])
    actions, rejects = validate(bot.act(state), live_ids=(0, 1))
    assert rejects == ()
    if name == "sitting_duck":
        assert actions == {}          # rung 0: legitimately does nothing at all
    else:
        assert set(actions) == {0, 1}  # every plane actually gets an action, not just a subset


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
