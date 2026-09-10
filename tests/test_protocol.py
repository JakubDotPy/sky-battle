import json

import pytest

from skybattle import protocol
from skybattle.state import Action, Contact, Gun, OwnPlane, View


def _view():
    g = Gun(name="forward", bearing_deg=0.0, dispersion_deg=8.0, ammo=80, cooldown_ticks_left=2)
    c = Contact(id=4, kind="bomber", x=1.0, y=2.0, heading_deg=90.0, speed=4.0, hp=120,
                bearing_deg=-30.0, range=250.0, seen_by=(0, 1))
    p = OwnPlane(id=0, kind="scout", x=10.0, y=20.0, heading_deg=45.0, speed=5.0, hp=70,
                 hp_max=70, stall_speed=3.0, corner_speed=5.0, max_speed=9.0, guns=(g,),
                 contacts=(c,))
    return View(tick=12, arena=(2000.0, 2000.0), planes=(p,), events=())


def test_view_survives_a_json_round_trip_as_typed_objects():
    wire = json.loads(json.dumps(protocol.encode_view(_view(), rng_seed=5)))
    back = protocol.decode_view(wire)
    assert isinstance(back, View)
    assert back.tick == 12
    assert back.arena == (2000.0, 2000.0)
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


def test_the_encoder_pins_ownplane_layout():
    """The wire format is positional, so a layout change must fail loudly, not silently drop.

    state.py's contract is additive-only, which means the SUPPORTED change (appending a field)
    is exactly the one a hardcoded slice would drop without error.
    """
    assert protocol._SCALARS == OwnPlane._fields.index("guns")
    assert OwnPlane._fields[protocol._SCALARS:] == ("guns", "contacts")
