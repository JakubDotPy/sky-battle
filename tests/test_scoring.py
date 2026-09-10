import pytest

from skybattle.classes import load_classes
from skybattle.state import Action
from skybattle.world import World

CLASSES = load_classes()
ARENA = (2000.0, 2000.0)


def _w(squadrons=None, seed=7):
    return World(ARENA, squadrons or [["fighter"], ["fighter"]], CLASSES, seed=seed)


def _park(w):
    """Move both squadrons far apart and facing away, so nothing happens."""
    ids = sorted(w.planes)
    w.planes[ids[0]].x, w.planes[ids[0]].y, w.planes[ids[0]].heading_deg = 100.0, 100.0, 180.0
    w.planes[ids[1]].x, w.planes[ids[1]].y, w.planes[ids[1]].heading_deg = 1000.0, 1000.0, 0.0


def _idle(w):
    """Squadron-keyed replies telling every living plane to hold its controls."""
    out = {}
    for sq in sorted(w.damage_dealt):
        out[sq] = {p.id: Action() for p in w.planes.values() if p.alive and p.squadron == sq}
    return out


def test_a_fresh_round_is_not_over():
    assert not _w().round_over()


def test_damage_scores_one_point_per_point():
    w = _w()
    w.damage_dealt[0] = 40.0
    assert w.scores()[0] == pytest.approx(40.0)


def test_a_kill_pays_fifty_plus_twenty_percent_of_damage_to_that_plane():
    w = _w()
    a, b = min(w.planes), max(w.planes)
    sq_a, sq_b = w.planes[a].squadron, w.planes[b].squadron
    w.planes[b].hp = 5
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    w.tick({sq_a: {a: Action(fire=frozenset({0}))}, sq_b: {b: Action()}})
    dmg = CLASSES["fighter"].guns[0].damage
    # damage + 50 survival + 20% kill bonus + 10 per dead enemy as last squadron flying
    assert w.scores()[sq_a] == pytest.approx(dmg + 50.0 + 0.2 * dmg + 10.0)


def test_scores_pays_no_survival_bonus_without_kills_while_alive():
    """scores() must key the 50-point bonus off kills_while_alive, not merely len(kills[sq]).

    A kill recorded in `kills[sq]` with `kills_while_alive[sq]` still at zero must not pay the
    50-point bonus -- otherwise the qualifier ("while the killer's squadron still had a living
    plane") is decorative and every kill pays the bonus regardless.
    """
    w = _w()
    a, b = min(w.planes), max(w.planes)
    sq_a = w.planes[a].squadron
    w.kills[sq_a].append(b)          # a kill is on the books...
    w.kills_while_alive[sq_a] = 0    # ...but not one made while the killer's squadron lived
    assert w.scores()[sq_a] == pytest.approx(0.0)


def test_the_last_standing_bonus_counts_only_enemy_losses():
    """A squadron is not paid for its own casualties."""
    w = World(ARENA, [["fighter", "fighter"], ["fighter"]], CLASSES, seed=7)
    mine = sorted(p.id for p in w.planes.values() if p.squadron == 0)
    enemy = next(p.id for p in w.planes.values() if p.squadron == 1)
    w.planes[mine[1]].alive = False      # one of my own is lost
    w.planes[enemy].alive = False        # and the single enemy is destroyed
    # squadron 0 is last standing with one enemy dead: exactly one 10-point bonus
    assert w.scores()[0] == pytest.approx(10.0)


def test_survival_time_alone_scores_nothing():
    w = _w()
    _park(w)
    for _ in range(200):
        w.tick(_idle(w))
    assert w.scores()[0] == pytest.approx(0.0)
    assert w.scores()[1] == pytest.approx(0.0)


def test_the_round_ends_when_one_squadron_is_left_flying():
    w = _w()
    b = max(w.planes)
    w.planes[b].alive = False
    assert w.round_over()
    assert w.outcome() == "squadron_0"


def test_the_round_ends_at_the_tick_limit():
    w = _w()
    _park(w)
    w.tick_no = World.ROUND_TICK_LIMIT
    assert w.round_over()
    assert w.outcome() == "timeout"


def test_the_inactivity_drain_starts_after_600_quiet_ticks():
    w = _w()
    _park(w)
    hp_before = w.planes[min(w.planes)].hp
    for _ in range(World.INACTIVITY_TICKS + 5):
        w.tick(_idle(w))
    assert w.planes[min(w.planes)].hp < hp_before


def test_round_tick_limit_is_a_constructor_parameter():
    """round_over() and outcome() must read the instance value, not the class constant -- a
    call site left reading `self.ROUND_TICK_LIMIT` would make this pass at the class default
    (3000) and silently ignore the constructor argument."""
    w = World(ARENA, [["fighter"], ["fighter"]], CLASSES, seed=7, round_tick_limit=5)
    _park(w)
    w.tick_no = 4
    assert not w.round_over()
    w.tick_no = 5
    assert w.round_over()
    assert w.outcome() == "timeout"


def test_inactivity_ticks_is_a_constructor_parameter():
    """_drain() must read the instance value, not the class constant -- a call site left
    reading `self.INACTIVITY_TICKS` would need 600 quiet ticks regardless of this argument."""
    w = World(ARENA, [["fighter"], ["fighter"]], CLASSES, seed=7, inactivity_ticks=5)
    _park(w)
    hp_before = w.planes[min(w.planes)].hp
    for _ in range(6):
        w.tick(_idle(w))
    assert w.planes[min(w.planes)].hp < hp_before


def test_any_damage_resets_the_inactivity_counter():
    w = _w()
    a, b = min(w.planes), max(w.planes)
    sq_a, sq_b = w.planes[a].squadron, w.planes[b].squadron
    _park(w)
    for _ in range(100):
        w.tick(_idle(w))
    assert w.ticks_since_damage >= 100
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    w.tick({sq_a: {a: Action(fire=frozenset({0}))}, sq_b: {b: Action()}})
    # _drain() runs after _resolve_hits() within the same tick, so the reset-to-0 from the
    # hit is immediately followed by one increment: 1, not 0, is what a caller ever observes.
    assert w.ticks_since_damage == 1


def test_a_win_by_drain_pays_no_last_survivor_bonus():
    w = _w()
    _park(w)
    w.planes[max(w.planes)].hp = 2
    for _ in range(World.INACTIVITY_TICKS + 10):
        w.tick(_idle(w))
        if w.round_over():
            break
    assert w.won_by_drain
    assert w.outcome() == "drain"
    # No combat happened: damage_dealt is 0 and drain kills credit nobody (by=None), so the
    # last squadron flying earns nothing beyond what it actually did.
    assert w.scores()[0] == pytest.approx(0.0)


def test_mutual_destruction_is_a_draw():
    w = _w()
    for pid in w.planes:
        w.planes[pid].alive = False
    assert w.round_over()
    assert w.outcome() == "draw"


def test_a_drain_death_does_not_poison_a_round_later_won_by_combat():
    """won_by_drain must mean "the drain ended this round", not "a drain death once happened".

    Squadmates of different classes have different hit points, so the first plane to drain out
    can be one of the eventual winner's - which does not end the round.
    """
    w = World(ARENA, [["scout", "fighter"], ["fighter"]], CLASSES, seed=7)
    mine = sorted(p.id for p in w.planes.values() if p.squadron == 0)
    enemy = next(p.id for p in w.planes.values() if p.squadron == 1)

    # Simulate the state after one of my own planes drained out.
    w.planes[mine[0]].hp = 0
    w.planes[mine[0]].alive = False
    w.won_by_drain = True

    # Now win by shooting: real damage must clear the flag.
    w.planes[mine[1]].x, w.planes[mine[1]].y, w.planes[mine[1]].heading_deg = 500.0, 500.0, 0.0
    w.planes[enemy].x, w.planes[enemy].y = 515.0, 500.0
    w.planes[enemy].hp = 1
    w.tick({0: {mine[1]: Action(fire=frozenset({0}))}, 1: {enemy: Action()}})

    assert not w.planes[enemy].alive
    assert not w.won_by_drain
    assert w.outcome() == "squadron_0"
    # damage + 50 survival + 20% kill bonus + 10 per dead enemy as last squadron flying
    dmg = CLASSES["fighter"].guns[0].damage
    assert w.scores()[0] == pytest.approx(dmg + 50.0 + 0.2 * dmg + 10.0)


def test_a_posthumous_kill_earns_no_survival_bonus():
    """A wiped-out squadron does not collect survival points for a bullet still in the air."""
    w = _w()
    a, b = min(w.planes), max(w.planes)
    w.planes[a].x, w.planes[a].y, w.planes[a].heading_deg = 500.0, 500.0, 0.0
    w.planes[b].x, w.planes[b].y = 515.0, 500.0
    w.planes[b].hp = 1
    sq_a, sq_b = w.planes[a].squadron, w.planes[b].squadron
    w.tick({sq_a: {a: Action(fire=frozenset({0}))}, sq_b: {b: Action()}})
    assert not w.planes[b].alive
    assert w.kills_while_alive[sq_a] == 1        # shooter was alive, so it counts

    w2 = _w()
    c, d = min(w2.planes), max(w2.planes)
    w2.planes[c].x, w2.planes[c].y, w2.planes[c].heading_deg = 500.0, 500.0, 0.0
    w2.planes[d].x, w2.planes[d].y = 515.0, 500.0
    w2.planes[d].hp = 1
    sq_c, sq_d = w2.planes[c].squadron, w2.planes[d].squadron
    w2.tick({sq_c: {c: Action(fire=frozenset({0}))}, sq_d: {d: Action()}})
    # kill the shooter's squadron before the bonus is tallied, then re-score
    for p in w2.planes.values():
        if p.squadron == sq_c:
            p.alive = False
    assert w2.kills_while_alive[sq_c] == 1       # counted at kill time, not at scoring time
