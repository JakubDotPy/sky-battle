import pytest

from skybattle import geom
from skybattle.classes import load_classes
from skybattle.state import Action, PlaneDestroyed
from skybattle.world import World

CLASSES = load_classes()
ARENA = (2000.0, 2000.0)


def _world(squadrons=None):
    return World(ARENA, squadrons or [["fighter"], ["fighter"]], CLASSES, seed=7)


def test_two_squadrons_of_one_spawn_alive():
    w = _world()
    assert len(w.planes) == 2
    assert all(p.alive for p in w.planes.values())
    assert {p.squadron for p in w.planes.values()} == {0, 1}


def test_views_are_keyed_by_squadron_and_only_show_own_planes():
    w = _world()
    views = w.views()
    assert sorted(views) == [0, 1]
    assert len(views[0].planes) == 1
    assert views[0].planes[0].id in [p.id for p in w.planes.values() if p.squadron == 0]


def test_a_view_never_leaks_enemy_ammo():
    w = _world()
    for c in w.views()[0].planes[0].contacts:
        assert not hasattr(c, "ammo")


def test_firing_spends_ammo_and_starts_a_cooldown():
    w = _world()
    pid = min(w.planes)
    w.tick({0: {pid: Action(fire=frozenset({0}))}, 1: {max(w.planes): Action()}})
    p = w.planes[pid]
    assert p.ammo[0] == CLASSES["fighter"].guns[0].ammo - 1
    assert p.cooldown[0] == CLASSES["fighter"].guns[0].cooldown_ticks
    assert len(w.bullets) == 1


def test_firing_on_cooldown_is_ignored_and_spends_nothing():
    w = _world()
    pid, other = min(w.planes), max(w.planes)
    w.tick({0: {pid: Action(fire=frozenset({0}))}, 1: {other: Action()}})
    spent = w.planes[pid].ammo[0]
    w.tick({0: {pid: Action(fire=frozenset({0}))}, 1: {other: Action()}})
    assert w.planes[pid].ammo[0] == spent
    assert len(w.bullets) == 1


def test_firing_with_no_ammo_is_ignored():
    w = _world()
    pid = min(w.planes)
    w.planes[pid].ammo[0] = 0
    w.planes[pid].cooldown[0] = 0
    w.tick({0: {pid: Action(fire=frozenset({0}))}})
    assert w.bullets == []


def test_an_unknown_gun_index_is_rejected_without_raising():
    w = _world()
    pid = min(w.planes)
    w.tick({0: {pid: Action(fire=frozenset({9}))}})
    assert w.bullets == []


def test_a_bullet_damages_an_enemy_and_credits_the_shooter():
    w = _world()
    a, b = min(w.planes), max(w.planes)
    # place the target directly in front, one tick of bullet travel away
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    before = w.planes[b].hp
    w.tick({0: {a: Action(fire=frozenset({0}))}, 1: {b: Action()}})
    assert w.planes[b].hp < before
    assert w.damage_dealt[0] > 0.0


def test_own_bullets_never_damage_the_shooters_own_squadron():
    w = World(ARENA, [["fighter", "fighter"], ["fighter"]], CLASSES, seed=7)
    mates = sorted(p.id for p in w.planes.values() if p.squadron == 0)
    a, mate = mates
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[mate].x, w.planes[mate].y = 515.0, 500.0
    before = w.planes[mate].hp
    w.tick({0: {a: Action(fire=frozenset({0}))}})
    assert w.planes[mate].hp == before


def test_a_plane_at_zero_hp_dies_and_emits_an_event():
    w = _world()
    a, b = min(w.planes), max(w.planes)
    w.planes[b].hp = 1
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    w.tick({0: {a: Action(fire=frozenset({0}))}, 1: {b: Action()}})
    assert not w.planes[b].alive
    assert any(isinstance(e, PlaneDestroyed) and e.plane_id == b
               for e in w.views()[1].events)


def test_a_dead_plane_contributes_no_vision_and_is_no_contact():
    # "first evaluate, then send new state" -- the snapshot is built AFTER resolution
    w = _world()
    a, b = min(w.planes), max(w.planes)
    w.planes[b].hp = 1
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    w.tick({0: {a: Action(fire=frozenset({0}))}, 1: {b: Action()}})
    assert w.views()[0].planes[0].contacts == ()
    assert w.views()[1].planes == ()


def test_planes_pass_through_each_other():
    """A 2D arena is a projection of a 3D sky: two planes at one (x, y) are at different
    altitudes, so they do not collide. Only bullets collide with planes."""
    w = _world()
    a, b = min(w.planes), max(w.planes)
    w.planes[a].x, w.planes[a].y = 500.0, 500.0
    w.planes[b].x, w.planes[b].y = 500.0, 500.0
    w.tick({w.planes[a].squadron: {a: Action()}, w.planes[b].squadron: {b: Action()}})
    assert w.planes[a].alive and w.planes[b].alive


def test_the_same_seed_reproduces_the_same_match():
    """Firing every tick exercises World.rng's per-shot dispersion draw, not just spawn jitter --
    that consumer must not desync a replay either."""
    def run():
        w = World(ARENA, [["scout", "fighter"], ["scout", "fighter"]], CLASSES, seed=99)
        for _ in range(60):
            replies: dict[int, dict[int, Action]] = {}
            for pid, p in w.planes.items():
                fire = frozenset(range(len(p.cls.guns)))
                replies.setdefault(p.squadron, {})[pid] = Action(throttle=0.8, steer=0.4, fire=fire)
            w.tick(replies)
        planes = [(round(p.x, 9), round(p.y, 9), round(p.speed, 9)) for _, p in sorted(w.planes.items())]
        bullets = [(round(b.x, 9), round(b.y, 9), round(b.vx, 9), round(b.vy, 9)) for b in w.bullets]
        return planes, bullets

    assert run() == run()


def test_last_actions_exposes_the_validated_actions_for_the_replay():
    w = _world()
    pid = min(w.planes)
    w.tick({0: {pid: Action(throttle=1.0)}, 1: {}})
    assert w.last_actions[pid].throttle == 1.0


def test_each_plane_reads_bearings_from_its_own_nose():
    w = World(ARENA, [["fighter", "fighter"], ["fighter"]], CLASSES, seed=7)
    mates = sorted(p.id for p in w.planes.values() if p.squadron == 0)
    a, b = mates
    enemy = next(p.id for p in w.planes.values() if p.squadron == 1)
    # both mates face east; the enemy sits ahead of one and off to the side of the other
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y, w.planes[b].heading_deg = 500.0, 400.0, 0.0
    w.planes[enemy].x, w.planes[enemy].y = 700.0, 500.0

    planes = {p.id: p for p in w.views()[0].planes}
    ca = planes[a].contacts
    cb = planes[b].contacts
    assert len(ca) == 1 and len(cb) == 1
    assert ca[0].id == cb[0].id                      # same contact, one squadron union
    assert ca[0].bearing_deg == pytest.approx(0.0)   # dead ahead of a
    assert cb[0].bearing_deg > 5.0                   # off to the left of b
    assert ca[0].range != cb[0].range


def test_seen_by_names_every_squadron_mate_that_can_see_it():
    w = World(ARENA, [["fighter", "fighter"], ["fighter"]], CLASSES, seed=7)
    mates = sorted(p.id for p in w.planes.values() if p.squadron == 0)
    a, b = mates
    enemy = next(p.id for p in w.planes.values() if p.squadron == 1)
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y, w.planes[b].heading_deg = 500.0, 490.0, 0.0
    w.planes[enemy].x, w.planes[enemy].y = 700.0, 495.0
    contacts = w.views()[0].planes[0].contacts
    assert set(contacts[0].seen_by) == {a, b}


def test_a_plane_that_sees_nothing_itself_still_receives_the_squadron_contact():
    # the shared-vision payoff: the scout spots, the blind mate still knows
    w = World(ARENA, [["scout", "bomber"], ["fighter"]], CLASSES, seed=7)
    scout = next(p.id for p in w.planes.values() if p.kind == "scout")
    bomber = next(p.id for p in w.planes.values() if p.kind == "bomber")
    enemy = next(p.id for p in w.planes.values() if p.squadron == 1)
    w.planes[scout].x, w.planes[scout].y, w.planes[scout].heading_deg = 500.0, 500.0, 0.0
    w.planes[bomber].x, w.planes[bomber].y, w.planes[bomber].heading_deg = 500.0, 300.0, 180.0
    w.planes[enemy].x, w.planes[enemy].y = 900.0, 500.0

    planes = {p.id: p for p in w.views()[0].planes}
    assert len(planes[scout].contacts) == 1
    assert len(planes[bomber].contacts) == 1              # knows, though it cannot see
    assert planes[bomber].contacts[0].seen_by == (scout,)  # and knows who is looking


def test_views_is_idempotent_within_a_tick():
    """views() advances the contact tracker, so a second call must not under-report."""
    w = _world()
    first = w.views()
    second = w.views()
    assert first == second
    assert [e for e in first[0].events] == [e for e in second[0].events]


def test_different_seeds_produce_different_spawns():
    """The seed must actually vary the match, or a fixed seed set has zero variance."""
    def spawns(seed):
        w = World(ARENA, [["scout", "fighter"], ["scout", "fighter"]], CLASSES, seed=seed)
        return [(round(p.x, 6), round(p.y, 6), round(p.heading_deg, 6))
                for _, p in sorted(w.planes.items())]
    assert spawns(1) != spawns(999)
    assert spawns(1) == spawns(1)


def test_spawns_stay_symmetric_between_squadrons():
    """Jitter varies the match; it must not advantage a side.

    Both squadrons sit at the same distance from centre AND at the same angular separation,
    so a seed changes only the formation's orientation.
    """
    import math
    w = World(ARENA, [["fighter"], ["fighter"]], CLASSES, seed=17)
    cx, cy = ARENA[0] / 2.0, ARENA[1] / 2.0
    ps = [p for _, p in sorted(w.planes.items())]
    dists, angles = [], []
    for p in ps:
        dx, dy = geom.delta(cx, cy, p.x, p.y, *ARENA)
        dists.append(math.hypot(dx, dy))
        angles.append(geom.normalize_deg(math.degrees(math.atan2(dy, dx))))
    assert dists[0] == pytest.approx(dists[1], rel=1e-9)
    assert abs(geom.angle_diff(angles[0], angles[1])) == pytest.approx(180.0, abs=1e-6)


def test_spawns_stay_symmetric_for_squadrons_of_two():
    """The absolute slot offset used to break this: a 90-unit radius delta at seed 17."""
    import math
    w = World(ARENA, [["scout", "fighter"], ["scout", "fighter"]], CLASSES, seed=17)
    cx, cy = ARENA[0] / 2.0, ARENA[1] / 2.0
    per_sq = {}
    for _, p in sorted(w.planes.items()):
        dx, dy = geom.delta(cx, cy, p.x, p.y, *ARENA)
        per_sq.setdefault(p.squadron, []).append(math.hypot(dx, dy))
    assert per_sq[0] == pytest.approx(per_sq[1], rel=1e-9)


def test_the_squadron_rng_is_a_stream_not_a_constant():
    """A bot calling state.rng.random() must get different values on successive ticks."""
    w = _world()
    first = w.views()[0].rng.random()
    w.tick({0: {}, 1: {}})
    second = w.views()[0].rng.random()
    assert first != second


def test_squadron_streams_are_independent():
    w = _world()
    a = [w.views()[0].rng.random() for _ in range(3)]
    w2 = _world()
    _ = w2.views()[1].rng.random()          # squadron 1 draws first
    b = [w2.views()[0].rng.random() for _ in range(3)]
    assert a == b, "one squadron's draws perturbed another's stream"


def test_squadron_seeds_do_not_collide_across_matches():
    """`seed ^ (sq + 1)` collided: (1, 1) and (2, 0) both gave 3."""
    seen = {}
    for seed in range(1, 60):
        w = World(ARENA, [["fighter"], ["fighter"]], CLASSES, seed=seed)
        for sq in (0, 1):
            key = w.squadron_seed(sq)
            assert key not in seen, f"{(seed, sq)} collides with {seen[key]}"
            seen[key] = (seed, sq)
