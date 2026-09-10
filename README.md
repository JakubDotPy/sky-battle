# Sky Battle

A dogfight you don't play. You write a program, and it flies.

Sky Battle is a bot-programming arena: a headless engine simulates a top-down 2D sky, and each player submits a
single `.py` file that commands a squadron of aircraft. Once per tick the engine hands your bot everything its
planes can see, and your bot answers with one action per plane — throttle, control input, and which guns to fire.
Then the engine resolves the tick and does it again, a few thousand times, and someone wins.

Vision is limited to each plane's forward cone plus a short-range awareness bubble, and it is shared instantly
across your squadron. So the interesting part of writing a bot is rarely the shooting. It is knowing where the enemy
went.

```text
squadron 0 (leader):    824.4 points  accepted 2166/2166  strikes 0  forfeits 0
squadron 1 (chaser):    566.8 points  accepted 2166/2166  strikes 0  forfeits 0
winner: leader
```

## Quick start

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/). The engine itself has **no runtime dependencies**.

```bash
uv sync                                                    # set up
uv run sky-battle duel samples/leader.py samples/chaser.py --seed 7 --rounds 3
```

Then watch it happen in a browser:

```bash
uv run sky-battle duel samples/leader.py samples/chaser.py --replay-dir replays/
uv run sky-battle serve replays/                           # opens the viewer
```

Click a plane in the viewer and you see its vision cones, its awareness bubble, and every enemy it *cannot*
currently see dimmed to an outline. That is the fastest way to understand why a bot did something baffling.

## Writing a bot

One file. No I/O — the engine owns that, so `print()` is free for debugging and cannot corrupt anything.

```python
from skybattle.state import Action

SQUADRON = ["scout", "fighter"]      # your loadout, your choice


class Bot:
    def act(self, state):
        out = {}
        for plane in state.planes:
            if not plane.contacts:
                out[plane.id] = Action(throttle=0.85, steer=0.06)     # sweep and search
                continue
            target = min(plane.contacts, key=lambda c: c.range)
            out[plane.id] = Action(
                throttle=0.9,
                steer=max(min(target.bearing_deg / 25.0, 1.0), -1.0), # bearing and steer
                fire=frozenset({0}) if abs(target.bearing_deg) < 6 else frozenset(),
            )
        return out
```

`steer` and `bearing_deg` deliberately share a sign, so steering toward a contact needs no negation. That one fact
saves most new authors an afternoon.

Start from `samples/`, which is a ladder rather than a grab bag — each file teaches exactly one idea:

| Sample | Teaches |
|---|---|
| `sitting_duck.py` | The harness works. Returns nothing at all |
| `circler.py` | The state shape, cooldown and ammo gating |
| `chaser.py` | Steering toward a contact — and why it always misses |
| `leader.py` | Leading a moving target. The "aha" bot |
| `wingman.py` | Squadron roles: the scout spots, the fighter kills |

Testing needs no engine and no subprocess, because a bot is a pure function:

```python
from skybattle.harness import make_state, plane, contact


def test_turns_toward_a_contact():
    state = make_state(planes=[plane(id=0, contacts=(contact(bearing_deg=30.0),))])
    assert Bot().act(state)[0].steer > 0
```

## Hosting a game

Two players is `duel`. For anything else, declare the match in a file:

```toml
# game.toml
[game]
rounds            = 15
ticks_per_round   = 3000
planes_per_player = 2
arena             = [2000, 2000]
seed              = 7

[[players]]
name = "jakub"
bot  = "bots/jakub.py"

[[players]]
name = "anna"
bot  = "bots/anna.py"

[[players]]
name = "petr"
bot  = "bots/petr.py"
```

```bash
uv run sky-battle play game.toml --replay-dir replays/
```

The host sets the rules; each player picks their own loadout in their own bot file. The engine reads every
`SQUADRON` declaration **statically**, without importing anyone's code, so you can also just look at what everyone
chose before you run anything.

It survives bots that crash, hang, return garbage or run slow — a failing plane coasts and the match continues.
It is **not** hardened against malicious bots, so run it among people you trust.

## The three classes

| | Sees | Guns | Character |
|---|---|---|---|
| **Scout** | Widest, furthest | Light, fast-firing | Finds everyone, dies to anything |
| **Fighter** | Middling | Balanced | Best turn rate. Built to win a turning fight |
| **Bomber** | Narrowest cone, **largest bubble** | Heaviest, slowest, plus a rear gun | Cannot find anyone, very hard to sneak up on |

Two things that look like bugs and are not: **turn rate peaks at an intermediate "corner" speed**, not at the
minimum — so there is an optimum to find rather than a floor to sit on. And the bomber really does have the
narrowest cone and the biggest awareness bubble, because a bomber crew has many eyes and few of them are looking
far ahead.

## Commands

| Command | Does |
|---|---|
| `uv run sky-battle duel A.py B.py` | Two bots. `--seed`, `--rounds`, `--arena`, `--deadline`, `--replay-dir` |
| `uv run sky-battle play game.toml` | Any number of players, from a host's file |
| `uv run sky-battle serve replays/` | Browser replay viewer |
| `uv run sky-battle duel --rules` | Print the balance table and exit |
| `uv run pytest -q` | The test suite |
| `uv run ruff check src tests samples` | Lint |
| `cd docs-site && uv run zensical serve` | Player docs at <http://localhost:8000>, live-rebuilding |
| `cd docs-site && uv run zensical build` | Static docs into `docs-site/site/` |

Both `zensical` commands must run from `docs-site/` — it looks for `zensical.toml` in the working directory.

## Documentation

- **Players and hosts:** `docs-site/` — the game, the classes with comparative diagrams, writing a bot, hosting a
  game. Every stat on those pages is read live from the balance table at build time, so it cannot drift.
- **Design and rationale:** `docs/design/` — why the arena wraps, why turn rate peaks in the middle, what the bot
  API guarantees, and which technology choices were measured rather than assumed.
- **Balance:** every number lives in `src/skybattle/classes.toml`, and it is meant to be edited. The design docs
  record which values are placeholders and what is known to be untuned.

## How it fits together

```text
   your bot (one .py)                    the engine
   ┌────────────────┐              ┌──────────────────────┐
   │ SQUADRON = ... │   ① view     │ World                │
   │ class Bot:     │ ◄─────────── │  ├ flight  (physics) │
   │   def act(s):  │              │  ├ bullets, collide  │
   │     return {…} │ ───────────► │  ├ vision  (fog)     │
   └────────────────┘   ② actions  │  └ scoring           │
          ▲                        └──────────┬───────────┘
          │ owns all I/O                      │
   ┌──────┴───────┐                           ▼
   │  runner.py   │ ◄── JSONL/stdio ──►  replay ──► browser viewer
   └──────────────┘        driver.py
```

The engine owns the loop, so your bot is a pure function and needs no scaffolding. Bots run as separate processes,
which is what makes a per-tick deadline enforceable at all. And everything downstream reads a recorded stream rather
than the engine, which is why the viewer contains no game logic.
