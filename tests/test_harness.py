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
