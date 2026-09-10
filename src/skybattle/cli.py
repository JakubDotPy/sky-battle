"""The command line. `duel` is the whole of this plan's user interface."""

import argparse
from pathlib import Path

from .classes import DEFAULT_TABLE, load_classes
from .match import run_match

DEFAULT_SQUADRON = ["scout", "fighter"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sky-battle")
    subs = parser.add_subparsers(dest="command", required=True)

    duel = subs.add_parser("duel", help="run a match between two bots")
    duel.add_argument("bot_a", type=Path, nargs="?")
    duel.add_argument("bot_b", type=Path, nargs="?")
    duel.add_argument("--seed", type=int, default=1)
    duel.add_argument("--rounds", type=int, default=11)
    duel.add_argument("--arena", type=float, nargs=2, default=[2000.0, 2000.0])
    duel.add_argument("--deadline", type=float, default=0.05)
    duel.add_argument("--replay-dir", type=Path, default=None)
    duel.add_argument("--rules", action="store_true", help="print the class table and exit")

    args = parser.parse_args(argv)
    if args.command != "duel":
        parser.error(f"unknown command {args.command}")

    if args.rules:
        # The numbers ARE the game; nobody should have to read source for them.
        print(DEFAULT_TABLE.read_text())
        return 0

    if args.bot_a is None or args.bot_b is None:
        duel.error("two bot paths are required unless --rules is given")

    arena = (args.arena[0], args.arena[1])
    classes = load_classes(arena=arena)     # validates cone ranges against this arena
    squadrons = [list(DEFAULT_SQUADRON), list(DEFAULT_SQUADRON)]

    result = run_match([args.bot_a, args.bot_b], squadrons, seed=args.seed,
                       rounds=args.rounds, arena=arena, classes=classes,
                       deadline=args.deadline, replay_dir=args.replay_dir)

    names = {0: args.bot_a.name, 1: args.bot_b.name}
    for sq in sorted(result.totals):
        acc = sum(r.accepted[sq] for r in result.rounds)
        ticks = sum(r.ticks for r in result.rounds)
        strikes = sum(r.strikes[sq] for r in result.rounds)
        forfeits = sum(1 for r in result.rounds if r.forfeited[sq])
        print(f"squadron {sq} ({names[sq]}): {result.totals[sq]:8.1f} points  "
              f"accepted {acc}/{ticks}  strikes {strikes}  forfeits {forfeits}")
    print(f"winner: {'draw' if result.winner is None else f'squadron {result.winner}'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
