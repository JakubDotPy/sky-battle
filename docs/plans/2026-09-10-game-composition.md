# Game Composition Implementation Plan

**Goal:** A host declares a match in a file — how many rounds, how long, how many players, how many planes each —
and each player declares their own squadron composition in their bot file. The engine validates one against the
other before a shot is fired.

**Why a file:** the CLI was heading for `--players --planes-per-player --ticks --rounds --arena --deadline ...`.
A match declaration is configuration, not a command line.

**What already works:** the engine is already fully general. Verified by running the target case directly — three
players, two planes each, three *different* compositions, fifteen rounds — and it played, scored and picked a
winner. `World` takes `squadrons: list[list[str]]` of any length, `_spawn` distributes N squadrons around a ring,
every scoring dict is keyed by squadron index, and `run_match(..., rounds=15)` already honours its argument. **The
gap is entirely in the CLI**, plus one constant that needs to become a parameter.

**Spec:** `docs/design/game-design.md` (match format, classes), `docs/design/bot-api.md` (the bot contract).

## Global constraints

- **`dependencies = []` holds.** `tomllib` is stdlib; the game file is TOML for consistency with `classes.toml`.
- The engine must **never import player code**. Bots run as subprocesses behind the runner shim; that is what makes
  a per-tick deadline enforceable at all.
- Validation failures happen **before the match starts**, and name the offending file.
- Defaults exist for everything a host might omit.

## The host's declaration

```toml
[game]
rounds            = 15          # default 11
ticks_per_round   = 3000        # default 3000
planes_per_player = 2           # default 2
arena             = [2000, 2000]
seed              = 7
deadline          = 0.05

[[players]]
name = "jakub"
bot  = "bots/jakub.py"
```

Player count is the number of `[[players]]` blocks. Bot paths resolve relative to the game file, not the working
directory, so a game file and its bots move together.

## The player's declaration

```python
SQUADRON = ["scout", "fighter"]
API_VERSION = 1

class Bot:
    def act(self, state): ...
```

**Read statically with `ast`, never by importing.** Parse the file, find the module-level `SQUADRON` assignment,
require a list of string literals. No player code executes, the protocol is unchanged, and a host can inspect every
submission's choice without running anything — which matters when three files arrive by email. The declaration must
therefore be a literal; for a declaration that is a feature, not a limitation.

If a computed squadron is ever wanted, the upgrade is a startup handshake: the runner shim already imports the bot,
so it could report `SQUADRON` as its first protocol line. That costs a protocol change and flips `run_round`'s
ordering, so it is deliberately not done now.

## Tasks

### G1 — resolve hits in impact order

`World._resolve_hits` resolves bullets in **spawn order**, so when two rounds converge on a dying plane in one tick,
the older-spawned round can claim the kill even if the other struck first. With two squadrons both rounds belong to
the same squadron and it cancels; **with three players it stops cancelling** and a 50-point kill bonus lands on the
wrong player. The final review flagged this as harmless *only* for two squadrons, and three-player games are exactly
the trigger it named.

Collect candidate hits with their swept-collision fraction, then apply in ascending order.

### G2 — the game file, and ticks as a parameter

`World.ROUND_TICK_LIMIT` is a class constant; make it a constructor parameter defaulting to 3000, threaded through
`run_round` and `run_match`. Do the same for `INACTIVITY_TICKS` while the ground is open.

Add a module that loads and validates a game file, reads each bot's `SQUADRON` via `ast`, and checks: the file
parses; every player has a name and a readable bot path; every bot declares `SQUADRON`; every declared kind exists
in the class table; every declaration's length equals `planes_per_player`. Then `sky-battle play game.toml`,
printing a result line per player and honouring `--replay-dir`.

`duel a.py b.py` stays as the two-bot shortcut.

### G3 — update the documentation

The docs are written for players and hosts, and this changes both their stories. The host page becomes about writing
a game file rather than assembling flags; the bot page gains the `SQUADRON` declaration; the class page can now
honestly say a bomber is playable, which it currently is not. Every example must be run before it is committed.
