# Writing a bot

## The contract

A bot is **one `.py` file**. It defines a `Bot` class with an `act(self, state)` method, or —
equally valid, and simpler for a bot with no memory between ticks — a bare module-level
`act(state)` function:

```python
from skybattle.state import Action


class Bot:
    def act(self, state):
        return {p.id: Action(throttle=1.0, steer=0.5) for p in state.planes}
```

```python
from skybattle.state import Action


def act(state):
    return {p.id: Action(throttle=1.0) for p in state.planes}
```

`act` is called once per tick and returns a `dict` mapping each of your plane ids to the
`Action` you want that plane to take this tick. A plane you omit from the dict gets a **neutral**
action for that tick — throttle idle, wings level, guns silent — not a repeat of whatever it did
last tick. That is a different mechanism from the momentum-holding fallback the engine uses when
your *whole reply* times out or is rejected — see
[When a bot misbehaves](#when-a-bot-misbehaves) — which reuses your previous tick's accepted
reply verbatim, including whichever planes that reply happened to name.

If you write a class with an `__init__`, the engine constructs it with **no arguments** —
`Bot()` — so every constructor parameter needs a default:

```python
class Bot:
    def __init__(self, config=None):
        self.last_seen = {}
```

This is the right place to keep state across ticks: the engine holds one long-lived instance of
your `Bot` for the whole match, so instance attributes survive from tick to tick — a
`self.last_seen[plane_id] = ...` dict is the natural way to remember anything the engine itself
does not (see [contacts and memory](#contacts-and-memory) below).

### No I/O, and that is not a suggestion

Your file has **no I/O in it at all** — no `stdin`, no `stdout`, no sockets. The engine runs
your bot inside a subprocess it owns, and a small shim (`skybattle.runner`) claims the real
stdout for its own JSON protocol before your code ever runs, then points file descriptor 1 and
`sys.stdout` at stderr. The practical effect: **`print()` is entirely free to use for
debugging.** Even a `print` that happens to emit something that looks exactly like a protocol
message lands harmlessly on stderr and never reaches the engine. You cannot corrupt the match by
printing, and you do not need a `flush=True` discipline or an `fd=3` convention to get this —
it works out of the box.

## Squadron composition

Every bot declares its own squadron as a module-level literal, right alongside `Bot`:

```python
SQUADRON = ["scout", "fighter"]
```

This is as much a part of the contract as `act()` itself — a bot that skips it cannot join a
[hosted game](running-a-game.md#running-a-game-file) at all; `duel` is more forgiving and falls
back to a fixed `["scout", "fighter"]` only when the declaration is missing entirely.

The engine reads `SQUADRON` **statically, with `ast`** — it never imports your bot to find out
what it flies. That is not a style choice: your bot runs as an isolated subprocess, and never
importing player code into the engine's own process is what makes the per-tick deadline
enforceable at all. A useful side effect follows from the same fact: a host can inspect every
submission's chosen composition just by reading the file, without running anything.

Which also means the declaration has to be **a literal list of string kinds** — not a computed
list, a loop, or a call to a function that returns one:

```python
SQUADRON = ["bomber", "bomber"]      # fine -- a literal list of string constants
SQUADRON = ["scout"] * 2             # rejected: not a list of string literals
```

Every kind named has to exist in the class table — `bomber`, `fighter` or `scout` today, see
[Plane classes](classes.md) — and under `sky-battle play` its length has to match the host's
`planes_per_player` exactly. `duel` enforces only the kind check: two bots meeting head-on may
field squadrons of different sizes, since there is no shared `planes_per_player` to check them
against.

Composition is entirely yours to choose — any mix of classes, in any order. One honest caveat:
a group that optimises hard enough will tend to converge on whichever mix is simply strongest,
since balance has not been tuned for free choice yet.

None of the bots in `samples/` declare `SQUADRON` — they were all written back when `duel`'s
fallback was the only squadron there was, which is exactly why the sample ladder above never
needed one. Add a line before pointing a game file at any of them.

## Conventions that bite

| Convention | Rule |
|---|---|
| Angles | Degrees only. Radians never appear in the API. |
| Heading 0 | East (+x). Positive is **counter-clockwise**. |
| Absolute angles | `[0, 360)` — `heading_deg`, `direction_deg`. |
| Relative angles | `(-180, 180]` — `bearing_deg`. |
| Speeds | Units per tick. |
| Times | Ticks. There is exactly one clock. |

The one thing worth memorising above everything else: **`Action.steer` and `Contact.bearing_deg`
share a sign.** Positive `steer` turns left (counter-clockwise); positive `bearing_deg` means the
contact is to your left. That means turning toward a contact needs no negation at all:

```python
steer = max(min(target.bearing_deg / 30.0, 1.0), -1.0)
```

`samples/chaser.py` uses exactly this line. The division by a constant just scales a full
90-degree-or-more bearing down to a full-deflection `steer` of `1.0`; tune the constant, not the
sign.

The engine ships `skybattle.geom` for everything else angle- and distance-related on a
wrap-around arena: `delta`, `distance`, `bearing_to`, `direction_to`, `angle_diff`,
`normalize_deg`. **Use it rather than writing your own.** The arena wraps at its edges, so naive
`atan2`/Euclidean-distance maths is wrong roughly a quarter of the time — right until a target
crosses the seam, then silently wrong. `contact.bearing_deg` and `contact.range` arrive already
torus-correct — the engine computed them with `geom` before handing them to you — so a bot only
needs to import `geom` itself once it starts reasoning about *absolute* positions, such as a
remembered last-seen location or an intercept point; `samples/leader.py` and `samples/wingman.py`
do exactly that.

## What a bot receives

`act(state)` is handed a `View`:

```python
class View(NamedTuple):
    tick: int
    arena: tuple[float, float]
    planes: tuple[OwnPlane, ...]
    events: tuple[object, ...]
    rng: random.Random | None
```

`state.planes` is your squadron, `state.arena` is `(width, height)`, and `state.tick` is the
current tick number. `state.rng` is a `random.Random` instance seeded per squadron, so a bot
that wants to break symmetry (a scout choosing a random search heading, say) can do it
reproducibly rather than reaching for the global `random` module. In a real match this stream is
reseeded fresh every tick rather than continuing across ticks, so treat it as good for one draw
per tick, not as a generator you can rely on to keep advancing between calls to `act`.

### Your own planes

```python
class OwnPlane(NamedTuple):
    id: int
    kind: str                        # "scout" | "fighter" | "bomber"
    x: float
    y: float
    heading_deg: float                # absolute, 0 = east, CCW positive
    speed: float                      # units per tick
    hp: int
    hp_max: int
    stall_speed: float
    corner_speed: float
    max_speed: float
    guns: tuple[Gun, ...]
    contacts: tuple[Contact, ...]
    bubble_range: float               # this plane's own vision bubble radius
```

Own-plane state is never fogged — everything about a plane you control, you see exactly. That
includes `stall_speed`, `corner_speed` and `max_speed`, which are what let a bot fly one file
against any class without hard-coding numbers per kind (see [Plane classes](classes.md) for what
those numbers actually are).

Each gun:

```python
class Gun(NamedTuple):
    name: str
    bearing_deg: float          # fixed mount angle; 0 = forward, 180 = rear
    dispersion_deg: float       # precision, not a traverse -- you cannot aim this
    ammo: int
    cooldown_ticks_left: int
    muzzle_speed: float         # needed to compute a firing solution -- see leader.py
```

### Contacts

```python
class Contact(NamedTuple):
    id: int              # stable only while continuously visible
    kind: str
    x: float              # absolute -- for YOUR OWN memory
    y: float
    heading_deg: float    # absolute
    speed: float
    hp: int                # visible battle damage
    bearing_deg: float    # relative to the reading plane's nose
    range: float
    seen_by: tuple[int, ...]   # which of YOUR planes currently sees it
```

Contacts carry both an absolute position and a bearing/range relative to whichever of your
planes is reading them — the same enemy shows up with different `bearing_deg` and `range` on
each of your planes' `contacts` tuples, because each is measured from that plane's own nose. Use
the relative fields for steering and aiming; keep the absolute fields if you want to remember
where something was after it drops out of sight.

**What is deliberately not here:** a `Contact` has no `ammo` and no `cooldown` — you cannot tell
whether an enemy is dry, on purpose, because knowing that would make approaching a spent enemy
free. `hp` *is* exposed, because battle damage is honestly visible at range and prioritising a
wounded target is a real tactical decision.

### Contacts and memory

A contact's `id` is stable only for as long as it stays continuously visible. The moment it
drops out of every one of your planes' vision, the engine forgets it completely — no last-known
position, no age, nothing. Spot the same physical enemy again later and it arrives with a **new**
id. This rewards actually keeping a plane's eyes on a target rather than glancing at it, and it
means any memory of where something used to be is entirely your bot's responsibility:

```python
class Bot:
    def __init__(self, config=None):
        self.last_seen: dict[int, tuple[float, float, int]] = {}

    def act(self, state):
        for p in state.planes:
            for c in p.contacts:
                self.last_seen[c.id] = (c.x, c.y, state.tick)
        ...
```

`samples/wingman.py` does exactly this, and also expires stale entries after a fixed number of
ticks so a squadron does not chase a decades-old ghost.

### Events

`state.events` describes what happened on the *previous* tick — hits landed, hits taken, planes
destroyed, contacts lost, your own actions rejected. They arrive as the typed `NamedTuple`s from
`skybattle.state`, in a real match exactly as in a harness test:
`HitByBullet(plane_id, from_squadron, damage)`, `BulletHit(plane_id, gun, target_id, damage)`,
`PlaneDestroyed(plane_id, by)`, `ContactLost(contact_id)`, `ActionRejected(plane_id, reason)`.

Import them and match on the class:

```python
from skybattle.state import ActionRejected, BulletHit, ContactLost, HitByBullet, PlaneDestroyed

for e in state.events:
    match e:
        case HitByBullet(from_squadron=shooter, damage=damage):
            ...  # somebody from squadron `shooter` has guns on me
        case BulletHit(gun=gun, target_id=target):
            ...  # my gun `gun` connected with contact `target`
        case PlaneDestroyed(plane_id=pid, by=None):
            ...  # the inactivity drain got it; nobody shot it down
        case PlaneDestroyed(plane_id=pid, by=killer):
            ...
        case ContactLost(contact_id=cid):
            ...  # fell off the squadron's radar (see Contacts and memory, above)
        case ActionRejected(plane_id=pid, reason=reason):
            ...  # one of my own commands was refused, see below
```

Reading fields by name works just as well (`e.damage`, `e.contact_id`), and so does `isinstance`.
An event type your bot does not recognise — from an engine newer than the one you wrote against —
arrives as a plain positional tuple rather than raising, so it simply fails to match any `case`
you wrote and falls through to your default.

`ActionRejected` is also how you learn about your own bugs at runtime — a bad plane id, an
out-of-range gun index, a `NaN` you accidentally computed — so it is worth logging rather than
ignoring while you are developing a bot.

## Energy and turning

Turning is not free. Every tick, your commanded `steer` costs speed in proportion to how hard
you actually turned — a gentle correction bleeds almost nothing, a hard turn costs real speed.
`throttle` is a lever position, not a target speed: it sets a ceiling the plane accelerates
toward or decelerates toward, not a number you can just assert. Combined with [turn rate peaking
at corner speed rather than at the minimum](classes.md#turn-rate-peaks-at-corner-speed-not-at-the-minimum),
this is the whole tactical core of the flight model: hauling the nose around to get guns on
target costs you the speed to disengage afterwards, and sitting at corner speed all the time is
a genuine trade-off, not a free optimum.

## A complete bot

Everything above, in one file you can run. This is `samples/leader.py`, included verbatim from
the repository — it is a real player that ships with the engine, is exercised by the test suite,
and is the reference opponent the other samples are measured against.

```python title="samples/leader.py"
--8<-- "samples/leader.py"
```

Save it as `mybot.py` and fly it against the simplest sample:

```console
uv run sky-battle duel mybot.py samples/sitting_duck.py
```

The parts worth tracing, in the order they matter:

1. **`SQUADRON`** declares the two planes it wants. The engine reads this statically, without
   importing your file, and rejects it before the match if it disagrees with the host's game file.
1. **`if not p.contacts`** is the search branch. A bot with nothing in sight must *cover ground* —
   the gentle `steer=0.06` is deliberate, because a hard turn re-scans one patch of sky forever.
1. **The two-iteration loop** is the whole point. Bullet flight time depends on range, range
   depends on where the target will be, and that depends on flight time — so it converges on the
   intercept point instead of solving it in closed form. Two passes land well inside a plane's
   radius.
1. **`gun.muzzle_speed` and `gun.cooldown_ticks_left == 0 and gun.ammo > 0`** come from the live
   gun table, never from a constant the bot assumes. A balance change moves the aim automatically.
1. **`throttle=0.4 if abs(lead_bearing) > 30.0`** trades speed for turn rate, because
   [turn rate peaks at corner speed](classes.md#turn-rate-peaks-at-corner-speed-not-at-the-minimum).

What it deliberately does *not* do: read `state.events`, remember a lost contact, or divide roles
between its two planes. Those are the next rung up.

## Sample ladder

Work through `samples/` in order — each one is short and teaches exactly one idea, building on
the last.

- **0 — `sitting_duck.py`.** Returns `{}` every tick. Proves the harness works, and shows the
  neutral-action default in practice: with no entry for any plane, every plane gets throttle
  idle, wings level, no fire, tick after tick — it settles toward stall speed and flies straight,
  it does not freeze in place or hold a heading.
- **1 — `circler.py`.** The state shape, the id-keyed return dict, and gating a shot on cooldown
  *and* ammo. A plane cannot stand still — stall speed is above zero — so "sit and shoot" becomes
  tightest-possible-radius circling, which is itself the lesson.
- **2 — `chaser.py`.** The steer-sign trick above, using `contact.bearing_deg`, which the engine
  has already computed torus-correctly. Also teaches why it reliably **misses**: it aims where
  the target *is*, not where it will be.
- **3 — `leader.py`.** Aiming at the intercept point instead — two fixed-point iterations
  converge on where a target will be by the time a bullet arrives, using `geom` and the gun's
  real `muzzle_speed` rather than an assumed constant. This is the "aha" bot.
- **4 — `wingman.py`.** Everything squadron-shaped: the scout searches and never engages; the
  fighter engages only contacts the squadron can currently see, preferring a wounded target; both
  keep `self.last_seen` and sweep the freshest remembered position (via `geom.bearing_to`) once a
  contact is lost.

There is no rung beyond this in the current samples — a "dodger" bot that breaks away from an
enemy's firing solution was planned in the design notes but has not been written yet.

## Testing without an engine

Because `act` is a pure function of its input, a bot is directly unit-testable with no engine, no
subprocess, and no I/O. `skybattle.harness` ships builders with sane defaults for exactly this —
`make_state`, `plane`, `contact` — so a test names only what it cares about:

```python
from skybattle.harness import make_state, plane, contact
from mybot import Bot

def test_holds_fire_when_not_aligned():
    state = make_state(planes=[plane(id=0, contacts=(contact(bearing_deg=45.0),))])
    assert Bot().act(state)[0].fire == frozenset()
```

That is a real, passing test against `samples/chaser.py` — three lines, no engine started.
`plane()` pulls its stats from the real class table (`load_classes()`), so a test can never drift
from the balance file the engine actually reads. `skybattle.harness` also re-exports the
engine's own `validate()` function, so you can run your bot's replies through the exact check the
engine applies and never have a test pass that the real match would reject.

## When a bot misbehaves

The match **never aborts** because of a broken bot. Every failure degrades to a bounded, logged
consequence instead:

| What happens | Effect |
|---|---|
| Your `act` raises | The traceback prints to your own bot's stderr; the engine receives a clean `{"error": ...}` and treats the tick as a miss for that squadron — every plane in it coasts (holds its last accepted action) this tick. |
| Your `act` takes too long | Same as raising: on a 50 ms per-tick deadline (tick 1 gets ~2 seconds, since that is where module-level imports land), a late reply is dropped as a miss and the plane coasts. |
| You reply with something that is not a `dict`, has a non-integer or unknown-plane key, or a value that is not a legal `Action` | Only that plane coasts; the rest of your squadron is unaffected. You get an `ActionRejected` event next tick naming the reason (`not_a_dict`, `bad_key:...`, `unknown_plane`, `not_an_action`, `bad_fire`, `unknown_gun:N`). |
| A throttle or steer value outside its legal range | Clamped to range, logged as `ActionRejected(..., "clamped")`. Still applied — just clamped. |
| `NaN` or infinity anywhere in your reply | **Never clamped** — rejected outright, because `NaN` clamps to `NaN` and would poison the physics for both players. |
| Three misses in a row (or, past tick 50, misses on more than 2% of all ticks so far) | Your squadron **forfeits**: its planes keep existing and keep coasting for the rest of the round rather than vanishing, so the match's physics stay consistent for the other player, but you can no longer win the round. |

A bot that is *occasionally* a little slow degrades smoothly — it just coasts for a tick here
and there. A bot that is *consistently* over budget is a cliff, not a slope: every tick times
out, so every reply arrives "late" for a tick that has already moved on and is discarded, and the
bot ends up holding its very first action for the whole match while its miss count climbs toward
the forfeit threshold. This is exactly why the result line reports **accepted actions**, not a
timeout count — see [Running a game](running-a-game.md#reading-the-result-line).

None of this is theoretical — it is the engine's own regression suite. `tests/bots/` ships the
deliberately-broken family used to verify every row of the table above: a bot that raises
(`crasher.py`), one that loops forever (`hanger.py`), one that returns a plain string instead of
a dict (`garbage.py`), one that prints a protocol-shaped JSON line every tick just to see if it
fools the parser (`protocol_liar.py` — it doesn't; the fake line lands on stderr, same as any
other `print`), one that replies with 200,000 stale dict entries (`huge_reply.py` — rejected
before the JSON is even parsed, for being an oversized line), and one that is merely chatty
(`chatty.py`).
