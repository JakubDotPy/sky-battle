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
    g = Gun(name="forward", bearing_deg=0.0, dispersion_deg=8.0, ammo=80, cooldown_ticks_left=0)
    p = OwnPlane(id=0, kind="scout", x=0.0, y=0.0, heading_deg=0.0, speed=5.0, hp=70, hp_max=70,
                 stall_speed=3.0, corner_speed=5.0, max_speed=9.0, guns=(g,))
    assert p.guns[0].ammo == 80
    assert p.guns[0].cooldown_ticks_left == 0


def test_contact_is_immutable():
    c = Contact(id=1, kind="scout", x=0.0, y=0.0, heading_deg=0.0, speed=1.0, hp=70,
                bearing_deg=0.0, range=1.0, seen_by=())
    with pytest.raises(AttributeError):
        c.hp = 0


def test_steer_docstring_matches_the_flight_model_sign():
    """The docstring is part of the API contract, so assert it against real physics.

    Positive steer must increase heading (a left turn in a y-up, CCW-positive frame).
    """
    from skybattle.classes import load_classes
    from skybattle.flight import step

    fighter = load_classes()["fighter"]
    _, _, heading, _ = step(fighter, 500.0, 500.0, 0.0, 5.0, 100, 100, 0.0, 1.0, (2000.0, 2000.0))
    assert 0.0 < heading < 90.0
