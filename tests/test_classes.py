import pytest

from skybattle.classes import load_classes, table_hash


def test_loads_the_three_classes():
    cs = load_classes()
    assert sorted(cs) == ["bomber", "fighter", "scout"]


def test_gun_mounts_load_in_order_with_the_rear_gun_at_180():
    bomber = load_classes()["bomber"]
    assert [g.name for g in bomber.guns] == ["forward", "rear"]
    assert bomber.guns[0].bearing_deg == 0.0
    assert bomber.guns[1].bearing_deg == 180.0
    assert bomber.guns[1].dispersion_deg > bomber.guns[0].dispersion_deg


def test_turn_rate_peaks_at_corner_speed_for_every_class():
    for c in load_classes().values():
        assert c.turn_at_corner > c.turn_at_stall
        assert c.turn_at_corner > c.turn_at_max


def test_speeds_are_ordered_for_every_class():
    for c in load_classes().values():
        assert c.stall_speed < c.corner_speed < c.max_speed


def test_table_hash_is_stable_and_hex():
    h = table_hash()
    assert h == table_hash()
    assert len(h) == 64
    int(h, 16)


_MINIMAL_BAD_TABLE = """
[scout]
hp = 70
radius = 9.0
stall_speed = 3.0
corner_speed = 5.0
max_speed = 9.0
turn_at_stall = 5.0
turn_at_corner = 9.0
turn_at_max = 4.5
accel = 0.2
decel = 0.3
turn_bleed = 0.045
cone_deg = 120.0
cone_range = 900.0
rear_cone_deg = 0.0
rear_cone_range = 0.0
bubble_range = 120.0
[[scout.guns]]
name = "forward"
bearing_deg = 0.0
dispersion_deg = 2.5
cooldown_ticks = 6
damage = 8
ammo = 80
lifetime_ticks = 20
muzzle_speed = 34.0
"""


def test_rejects_a_cone_longer_than_half_the_arena(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text(_MINIMAL_BAD_TABLE)
    with pytest.raises(ValueError, match="cone_range"):
        load_classes(bad, arena=(1000.0, 1000.0))


def test_a_negative_bubble_range_is_rejected(tmp_path):
    bad = tmp_path / "bubble.toml"
    bad.write_text(_MINIMAL_BAD_TABLE.replace("bubble_range = 120.0", "bubble_range = -1.0"))
    with pytest.raises(ValueError, match="bubble_range"):
        load_classes(bad)


def test_a_zero_bubble_range_loads_fine(tmp_path):
    """Zero is legal: no bubble, not an error."""
    good = tmp_path / "nobubble.toml"
    good.write_text(_MINIMAL_BAD_TABLE.replace("bubble_range = 120.0", "bubble_range = 0.0"))
    cs = load_classes(good)
    assert cs["scout"].bubble_range == 0.0


def test_rejects_a_bubble_larger_than_half_the_arena(tmp_path):
    bad = tmp_path / "bigbubble.toml"
    bad.write_text(_MINIMAL_BAD_TABLE.replace("cone_range = 900.0", "cone_range = 100.0"))
    with pytest.raises(ValueError, match="bubble_range"):
        load_classes(bad, arena=(200.0, 200.0))  # limit 100; bubble_range 120 exceeds it


def test_a_missing_guns_block_names_the_class_and_the_header(tmp_path):
    bad = tmp_path / "nogun.toml"
    bad.write_text(_MINIMAL_BAD_TABLE.split("[[scout.guns]]")[0])
    with pytest.raises(ValueError, match=r"scout: needs at least one \[\[scout\.guns\]\] block"):
        load_classes(bad)


def test_an_unknown_field_names_the_class(tmp_path):
    bad = tmp_path / "typo.toml"
    bad.write_text(_MINIMAL_BAD_TABLE.replace("hp = 70", "hp = 70\nhitpoints = 70"))
    with pytest.raises(ValueError, match="scout:"):
        load_classes(bad)


def test_a_negative_dispersion_is_rejected(tmp_path):
    bad = tmp_path / "disp.toml"
    bad.write_text(_MINIMAL_BAD_TABLE.replace("dispersion_deg = 2.5", "dispersion_deg = -1.0"))
    with pytest.raises(ValueError, match="dispersion_deg"):
        load_classes(bad)


def test_a_zero_dispersion_gun_loads_fine(tmp_path):
    """Zero is legal: a perfect gun, not an error."""
    good = tmp_path / "perfect.toml"
    good.write_text(_MINIMAL_BAD_TABLE.replace("dispersion_deg = 2.5", "dispersion_deg = 0.0"))
    cs = load_classes(good)
    assert cs["scout"].guns[0].dispersion_deg == 0.0


def test_a_zero_lifetime_is_rejected(tmp_path):
    bad = tmp_path / "life.toml"
    bad.write_text(_MINIMAL_BAD_TABLE.replace("lifetime_ticks = 20", "lifetime_ticks = 0"))
    with pytest.raises(ValueError, match="lifetime_ticks"):
        load_classes(bad)


def test_a_zero_muzzle_speed_is_rejected(tmp_path):
    bad = tmp_path / "muzzle.toml"
    bad.write_text(_MINIMAL_BAD_TABLE.replace("muzzle_speed = 34.0", "muzzle_speed = 0.0"))
    with pytest.raises(ValueError, match="muzzle_speed"):
        load_classes(bad)
