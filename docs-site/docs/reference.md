---
render_macros: true
---

# Reference

Exhaustive tables and exact type definitions. For the narrative version — what a plane class
*feels* like to fly, what a bot contract actually asks of you — see [Plane classes](classes.md)
and [Writing a bot](writing-a-bot.md). Every table below is generated at build time from
`src/skybattle/classes.toml`, the same file the engine reads, via the same `load_classes()`
function — nothing here is retyped by hand, so a balance pass regenerates this page rather than
silently contradicting it. Run `sky-battle duel --rules` to see the raw file directly.

## Airframe

{{ airframe_table() }}

Turn rate is piecewise-linear through three points — stall, corner and max speed — and **peaks at corner speed**, not at
the minimum; see [Plane classes](classes.md#turn-rate-peaks-at-corner-speed-not-at-the-minimum) for why. `radius` sets
the target a plane's own bulk presents to an incoming bullet, so a bomber's high hit-point pool is partly paid for by
being an easier target.

## Guns

{{ gun_table() }}

Guns are fixed mounts, never aimed — a round leaves along `bearing_deg`, and `dispersion_deg` is
the mount's *precision*, a random scatter applied per round, not a traverse a bot can steer.
`muzzle_speed` is the round's own speed before the shooter's velocity is added as a **vector**
(not simply summed along the firing line), which is why a rear mount's rounds go slower the
faster the shooter runs away. "Sustained DPS" is `damage / cooldown_ticks` for that mount alone —
how much damage per tick a gun does if it never misses and never runs dry; it says nothing about
total damage before the magazine empties, which scales with `ammo` instead.

## Vision

{{ cone_table() }}

Vision is the union of a plane's forward cone, its rear cone (if it has one), and its bubble —
a heading-independent short-range radius, so a pilot looking around is not blind to anything
close in just because it is not dead ahead. The bomber has both the narrowest cone and the
largest bubble of the three classes, on purpose — see
[Plane classes](classes.md#bomber) for why that is not a balance mistake.

## Types

The full bot-facing type surface, straight from `skybattle.state` and `skybattle.protocol`. See
[Writing a bot](writing-a-bot.md) for what each field means and how the pieces fit together in
practice.

### What a bot returns

```python
@dataclass(frozen=True, kw_only=True)
class Action:
    throttle: float = 0.0          # [0, 1] lever position -> thrust ceiling, not a target speed
    steer: float = 0.0             # [-1, +1]; positive = left (CCW); costs speed proportional
                                    # to how hard you actually turned
    fire: frozenset[int] = frozenset()   # gun indices to fire this tick; empty = hold fire
```

`Action` is keyword-only and frozen, so a bot returns exactly `dict[plane_id, Action]` — a
`dict`, never a list of pairs, so a duplicate plane id is a language-level impossibility rather
than a rule to enforce.

### What a bot receives

```python
class Gun(NamedTuple):
    name: str
    bearing_deg: float
    dispersion_deg: float
    ammo: int
    cooldown_ticks_left: int
    muzzle_speed: float = 30.0


class Contact(NamedTuple):
    id: int                    # stable only while continuously visible
    kind: str                  # "scout" | "fighter" | "bomber"
    x: float                   # absolute
    y: float
    heading_deg: float         # absolute
    speed: float
    hp: int                    # visible battle damage; no ammo, no cooldown
    bearing_deg: float         # relative to the reading plane's nose, (-180, 180]
    range: float
    seen_by: tuple[int, ...]   # which of YOUR planes currently sees it


class OwnPlane(NamedTuple):
    id: int
    kind: str
    x: float
    y: float
    heading_deg: float         # absolute, 0 = east, CCW positive
    speed: float                # units/tick
    hp: int
    hp_max: int
    stall_speed: float
    corner_speed: float
    max_speed: float
    guns: tuple[Gun, ...]
    contacts: tuple[Contact, ...] = ()
    bubble_range: float = 0.0


class View(NamedTuple):
    tick: int
    arena: tuple[float, float]
    planes: tuple[OwnPlane, ...]
    events: tuple[object, ...]
    rng: random.Random | None = None
```

### Events

Typed like this in `skybattle.state`, but see the
[warning in Writing a bot](writing-a-bot.md#events) — a real match delivers these over the wire
as plain positional tuples, with the type name stripped:

```python
class HitByBullet(NamedTuple):
    plane_id: int
    from_squadron: int
    damage: int

class BulletHit(NamedTuple):
    plane_id: int
    gun: int
    target_id: int
    damage: int

class PlaneDestroyed(NamedTuple):
    plane_id: int
    by: int | None          # None if killed by the inactivity drain

class ContactLost(NamedTuple):
    contact_id: int

class ActionRejected(NamedTuple):
    plane_id: int
    reason: str
```

`reason` on `ActionRejected` is one of: `not_a_dict`, `too_many_actions`, `bad_key:<repr>`,
`unknown_plane`, `not_an_action`, `bad_fire`, `nan_or_inf`, `clamped`, or `unknown_gun:<index>`
(the last one raised for a `fire` entry naming a gun index your plane does not have).

## Game files

A host's `[game]` table, with every field and its default. See [Running a game
file](running-a-game.md#running-a-game-file) for how the whole thing behaves.

| Field | Default | Meaning |
|---|---|---|
| `rounds` | `11` | Rounds in the match, each a fresh spawn with its own seed. |
| `ticks_per_round` | `3000` | Tick limit per round — `duel` has no flag for this and is always `3000`. |
| `planes_per_player` | `2` | The plane count every player's `SQUADRON` must declare. |
| `arena` | `[2000, 2000]` | `[width, height]`, checked against every class's cone and bubble ranges. |
| `seed` | `1` | Each round within the match uses `seed`, `seed + 1`, `seed + 2`, ... in order. |
| `deadline` | `0.05` | Per-tick wall-clock budget, in seconds, handed to each bot. |

`[[players]]`, one block per player — a file needs at least one:

| Field | Meaning |
|---|---|
| `name` | The player's display name — required, and what the result line reports. |
| `bot` | Path to the bot's `.py` file, resolved relative to the game file, not the working directory. |

A player's squadron is not declared in the game file at all — it comes from the bot's own
`SQUADRON` (see [Squadron composition](writing-a-bot.md#squadron-composition)), read statically
and checked against `planes_per_player` and the class table before the match starts.

## CLI

`sky-battle duel [bot_a] [bot_b] [--seed N] [--rounds N] [--arena W H] [--deadline SECONDS]
[--replay-dir DIR] [--rules]`, `sky-battle play GAME_FILE [--replay-dir DIR]`, and `sky-battle
serve REPLAY_DIR [--port N] [--no-open]` are the whole command surface today — see [Running a
game](running-a-game.md) for what each flag does and how to read the output.
