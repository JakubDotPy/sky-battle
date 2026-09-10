"""Round and match orchestration.

A ROUND is one fight, ending when one squadron is left flying or at the tick limit.
A MATCH is 11 rounds -- odd, so draws are rare -- with fresh spawns, consecutive seeds and
summed scores.
"""

from pathlib import Path
from typing import NamedTuple

from .classes import PlaneClass, load_classes
from .driver import BotProcess
from .replay import FatWriter, ThinWriter, make_header
from .world import World


class RoundResult(NamedTuple):
    scores: dict[int, float]
    outcome: str
    ticks: int
    accepted: dict[int, int]
    strikes: dict[int, int]
    forfeited: dict[int, bool]


class MatchResult(NamedTuple):
    rounds: list[RoundResult]
    totals: dict[int, float]
    winner: int | None


def run_round(bot_paths: list[str | Path], squadrons: list[list[str]], seed: int,
              arena: tuple[float, float], classes: dict[str, PlaneClass] | None = None,
              table_path: str | Path | None = None,
              replay_dir: str | Path | None = None, deadline: float = 0.05,
              round_index: int = 1,
              round_tick_limit: int = World.ROUND_TICK_LIMIT,
              inactivity_ticks: int = World.INACTIVITY_TICKS) -> RoundResult:
    table_path = Path(table_path) if table_path is not None else None
    classes = classes or load_classes(table_path)
    world = World(arena, squadrons, classes, seed=seed,
                  round_tick_limit=round_tick_limit, inactivity_ticks=inactivity_ticks)
    bots = [BotProcess(p, tick_deadline=deadline) for p in bot_paths]

    thin = fat = None
    if replay_dir is not None:
        d = Path(replay_dir)
        d.mkdir(parents=True, exist_ok=True)
        header = make_header(seed, arena, squadrons, table_path=table_path, bot_paths=bot_paths)
        thin = ThinWriter(d / f"round-{round_index:03d}.thin.jsonl.gz", header)
        fat = FatWriter(d / f"round-{round_index:03d}.fat.jsonl.gz", header)

    try:
        while not world.round_over():
            views = world.views()
            replies: dict[int, object] = {}
            statuses: dict[int, str] = {}
            for sq, bot in enumerate(bots):
                # Per-tick, not just per-squadron: see the note on rng_seed in protocol.py --
                # a subprocess bot rebuilds its Random from this seed every tick, so the seed
                # itself must vary by tick or state.rng would be a constant across the match.
                rng_seed = f"{world.squadron_seed(sq)}:{views[sq].tick}"
                raw, status = bot.exchange(views[sq], rng_seed=rng_seed)
                replies[sq] = raw
                statuses[sq] = status
            world.tick(replies)
            if thin is not None:
                thin.record(world.tick_no, world.last_actions, statuses)
                fat.record(world, statuses)
        return RoundResult(
            scores=world.scores(),
            outcome=world.outcome(),
            ticks=world.tick_no,
            accepted={sq: b.accepted for sq, b in enumerate(bots)},
            strikes={sq: b.strikes for sq, b in enumerate(bots)},
            forfeited={sq: b.forfeited for sq, b in enumerate(bots)},
        )
    finally:
        for b in bots:
            b.close()
        for w in (thin, fat):
            if w is not None:
                w.close()


def run_match(bot_paths: list[str | Path], squadrons: list[list[str]], seed: int,
              rounds: int = 11, **kw) -> MatchResult:
    results = [run_round(bot_paths, squadrons, seed=seed + i, round_index=i + 1, **kw)
               for i in range(rounds)]
    totals = {sq: sum(r.scores[sq] for r in results) for sq in results[0].scores}
    best = max(totals.values())
    leaders = [sq for sq, v in totals.items() if v == best]
    return MatchResult(rounds=results, totals=totals,
                       winner=leaders[0] if len(leaders) == 1 else None)
