# Sky Battle — bot API

**Status:** working draft. Everything here is research-backed recommendation unless [game-design.md](game-design.md)
records it as decided.
**Companions:** [game-design.md](game-design.md) · [tech-decisions.md](tech-decisions.md)

The bot API is the only part of this project that is expensive to change, because other people write against it.
Everything else can be rewritten in an afternoon.

## 1. Shape of a bot

```python
API_VERSION = 1


class Bot:
    def __init__(self, config):        # once per match
        self.last_seen = {}

    def act(self, state):              # once per tick
        return {plane.id: Action(...) for plane in state.planes}
```

**The author writes no I/O at all.** The engine spawns its *own* runner shim, which imports the author's file and
owns the entire protocol. This is the single highest-value ergonomic decision in the project, because it makes
`print("debug")` harmless. Halite and CodinGame both put the protocol on the bot's stdout and both rely on authors
knowing to debug via stderr — convention that fails the first time somebody learning reaches for `print`.

```python
real_stdout = os.fdopen(os.dup(1), "wb")   # private protocol channel
os.dup2(2, 1)                              # anything printed goes to stderr
sys.stdout = sys.stderr
```

Verified against a bot that prints a *protocol-shaped JSON line* every tick — the worst case — which survived with
zero strikes, its fake line landing harmlessly on stderr. The shim also catches the author's exceptions, prints the
full traceback to stderr so the author debugs normally, and hands the engine a clean `{"error": ...}`, so the engine
never has to tell "crashed" from "sent nonsense" by parsing a traceback.

*(An fd-3 convention was tried first and is worse: it breaks on the `preexec_fn`/`pass_fds` interaction, requires
the author to know about fd 3, and does not work on Windows.)*

**A pure `act(state) -> dict[int, Action]`, not callbacks and not a loop the bot drives.** It is the only model
where a unit test is three lines and needs no engine. Robocode's own documentation warns against the model it
inherited: "it is considered bad practice to call Bot API methods from the event handlers, as calling methods like
`fire()` will block the event handler until the action completes, meaning other event handlers will be triggered at
a later turn and might get too old on the event queue and be removed."

**A class, so instance attributes are the state store.** Halite, Battlecode, Screeps and Robocode all let the bot be
a long-running object and every strong bot keys dictionaries on unit ids. Battlesnake is the counter-example —
genuinely stateless webhooks, where the community answer is "key your state by game id in a datastore", which its
own docs treat as a cost. **Plane ids are stable integers for a whole match and are never reused after a death,**
which is exactly what makes `self.last_seen[plane_id]` work.

**Actions are returned as a `dict` keyed by plane id, never a list of pairs.** One line of API design deletes an
entire class of problem: the language enforces uniqueness, so there is nothing to validate and nothing to document.
Halite III is the only surveyed game that accepted a *list* of per-unit commands, and it is the only one that needed
a rule for duplicates — that rule being "the game engine kills any bot that attempts to issue multiple commands to
one ship", a brutal trap for a mistake as ordinary as looping over a stale unit list.

**Squadron size 1 is free.** Free-for-all is the same call returning a one-entry dict. No second code path.

## 1a. What the bot returns

```python
@dataclass(frozen=True, kw_only=True)
class Action:
    throttle: float = 0.0          # [0, 1] lever position -> thrust
    steer: float = 0.0             # [-1, +1] control input; positive = left (CCW)
    fire: frozenset[int] = frozenset()   # gun ids to fire this tick; empty = hold fire
```

**Composite, because a real cockpit is.** The throttle is worked by one hand, the controls by the other hand and the
feet, and the trigger by a finger — simultaneously. One `Action` per plane per tick carries all three.

This deliberately drops the original assignment's turn-*or*-shoot constraint. **Energy bleed replaces it as the
central tension:** turning costs speed, so a bot that turns hard to get its guns on target arrives slow, and slow
means it cannot disengage. The trade-off moved from the action budget into the flight model, where it is both more
realistic and more interesting.

**Inputs are continuous, not three-valued**, because a stick and a throttle lever have travel — and because that is
what gives energy management a dial. A gentle turn bleeds less speed than a hard one, which is the decision the
whole flight model exists to create. Three-valued inputs would collapse it back to a binary.

**`throttle` is a lever position, not a target speed.** It sets thrust; speed is what results, once turning has bled
energy and drag has capped it. Stall speed is a floor on the resulting speed, not on the setting. This is the
mechanism that makes energy real rather than decorative: a bot cannot simply ask to be fast.

**`fire` is a set**, so the bomber fires both guns in the same tick it flies — two crew members do act at once.
An empty set holds fire, which is the default and costs nothing.

**Keyword-only and frozen**, so a later field addition cannot break positional construction in an existing bot
(see §6). Out-of-range values are clamped and logged; NaN is rejected outright, never clamped (see §5).

## 2. What the bot receives

- **`state.planes`** — its own planes in full: exact position, heading, speed, hit points, and per-gun `ammo`,
  `cooldown_ticks_left`, `dispersion_deg`, `bearing_deg`, `muzzle_speed`. Own state is never fogged. Guns are fixed
  mounts: a bot aims by flying the aeroplane, and `dispersion_deg` is the mount's precision, not a traverse it can
  steer. `muzzle_speed` is exposed because a bot needs it to compute a firing solution (see `samples/leader.py`,
  which reads `gun.muzzle_speed` rather than assuming one engine-wide constant).
- **`plane.contacts`** — enemies known to the squadron, carried on **each own-plane** with bearing and range
  measured from *that* plane's nose. The squadron shares knowledge instantly and perfectly, so every living plane
  receives the same contact ids; only the geometry differs per reader. Contacts belong to a plane rather than to the
  squadron precisely because the relative frame has to have a single, unambiguous origin — an earlier draft of this
  document put them on the view, which is incoherent for a squadron of more than one.

  ```python
  class Contact(NamedTuple):
      id: int                    # stable while continuously visible; a NEW id after re-acquisition
      kind: str                  # "scout" | "fighter" | "bomber"
      x: float                   # absolute, for the bot's own memory
      y: float
      heading_deg: float         # absolute, 0 = east, CCW positive
      speed: float               # units per tick
      hp: int                    # visible battle damage
      bearing_deg: float         # relative to the reading plane's nose, (-180, 180]
      range: float               # pre-wrapped shortest distance
      seen_by: tuple[int, ...]   # which of my planes can see it right now
  ```

  No `ammo`, no `cooldown`, no `age`, and nothing at all about a contact once it is lost.
- **`state.events`** — what happened on the *previous* tick (see §4).
- **`state.tick`**, and a per-squadron `random.Random` instance (see §5).

**Contacts carry both absolute and receiver-relative geometry.** Absolute position, heading and speed, *plus*
bearing and range measured from the nose of the plane reading them. The redundancy is deliberate and cheap:

- **Relative fields** are what the author asked for and what the sample bots use. On a torus there is no useful
  origin, and pre-wrapped bearing and range spare every bot author the one piece of maths most likely to defeat
  them.
- **Absolute fields** are what a `self.last_seen[id] = (pos, tick)` memory needs. Relative bearings go stale the
  instant the observing plane turns, so a memory built on them is wrong by construction.

**Report enemy heading and speed; do not force cross-tick velocity inference.** Robocode's `ScannedRobotEvent`
hands over heading and velocity, and RoboCup goes further and hands over the derivatives outright. The interesting
inference problem is *where will it be when my bullet arrives*, not *which way is it pointing*; numerically
differentiating a fogged, intermittent signal teaches noise amplification, not aviation.

**`contact.seen_by` is a tuple of the plane ids that can see it.** This is where the "shoutout over the radio"
metaphor actually pays off: a contact seen only by the scout at 880 units is not one the bomber can engage, and role
play emerges from a tuple instead of from a message protocol.

**A contact is a structurally different type from an own-plane**, and the fields it omits are chosen, not
incidental. Leaking anything else then becomes a *type* error rather than an exploit somebody finds in week three.

**`hp` is exposed on purpose:** it lets a bot prioritise a wounded target over a fresh one, which is a genuine
strategic lever and cheap to reason about. It is also the one property of an enemy aircraft that is honestly
observable at range — battle damage is visible.

**`ammo` and `cooldown` stay hidden**, and that asymmetry is the point. Knowing an enemy is out of ammunition would
make it free to approach, which collapses the most interesting late-round situation in the game into arithmetic.

**"I see nothing" is an empty tuple, never a sentinel.** Pommerman puts `Fog = 5` inside its board array, where 5
also looks like a legal cell value. That is a bug farm.

## 3. Conventions

Robocode is the cautionary tale here, and its mistakes are well documented: origin bottom-left, but heading 0 =
North with angles increasing *clockwise*, so "sin is used for X and cos for Y", inverted from every maths library.
It then ships two of every angle method — `getHeading()` and `getHeadingRadians()` — doubling the API surface for
one concept and creating a silent wrong answer if you mix them. Its most common beginner error is confusing relative
and absolute bearings.

| Convention | Choice |
|---|---|
| Angles | **Degrees only.** Radians are never exposed. `math.radians` is documented in the starter bot |
| Heading 0 | **+x (east)**, counter-clockwise positive, y-up, origin bottom-left, wrapping modulo (W, H) |
| Absolute angles | `[0, 360)` |
| Relative angles | `(-180, 180]` |
| Naming | Every angle field names its frame: `heading_deg` (absolute, mine), `bearing_deg` (relative to my nose), `direction_deg` (absolute, to something) |
| Speeds | units per tick |
| Times | ticks. One clock, no seconds anywhere |

With heading 0 = east and counter-clockwise positive, `math.degrees(math.atan2(dy, dx))` **is** a heading, with no
adjustment. Robocode got the origin right and the angle wrong; there is no reason to repeat half of it. The renderer
flips y — that is the renderer's job.

### The `geom` module is the pedagogical dial

Derived quantities live in an importable `skybattle.geom` — roughly thirty lines: `delta`, `distance`, `bearing_to`,
`angle_diff`, `normalize_deg`. Tank Royale eventually *added* `calcBearing` / `bearingTo` / `directionTo` /
`distanceTo` precisely because deriving them was the wall everyone hit in classic Robocode.

Two reasons this beats hiding the helpers on a base class: a module is **readable source**, so the helper is the
lecture; and forbidding the import is how a harder variant gets created for free.

**Torus geometry must be used from rung one.** `atan2(bx - ax, by - ay)` is correct about three quarters of the time
on a torus and points the long way round otherwise, and Euclidean distance over-estimates. That produces "my bot is
sometimes stupid", the worst bug class, because it never crashes. So `geom.delta` and `geom.distance` ship with the
engine and **every sample bot uses them**, so nobody writes the naive version by accident.

**`lead_point` is deliberately *not* in `geom`.** Leading a moving target is the punchline — sample rung 3. It ships
as pseudocode in the docs.

## 4. Events are data, not callbacks

`state.events` is a tuple describing the previous tick: `HitByBullet(plane_id, from_squadron, damage)`,
`BulletHit(plane_id, gun, target_id, damage)`, `PlaneDestroyed(plane_id, by)`, `ContactLost(contact_id)`,
`ActionRejected(plane_id, reason)`.

No priority queue, no ordering semantics to document, no reentrancy. And `ActionRejected` arriving in the same
stream is how a bot learns about its own bugs at runtime.

## 5. Failure is legible, and the match never aborts

The author's decision: **on a timeout no command is sent and the plane continues without change** — the engine
re-applies that plane's **last accepted `Action`**, so the throttle setting, the control input and the trigger state
all persist. Battlesnake does the same and describes it well: "momentum takes over and they will continue moving in
the same direction as the previous turn."

Under a composite action model this is the only coherent reading of "without change": a plane mid-turn keeps
turning, a plane accelerating keeps accelerating. Zeroing the controls instead would make a timeout an *event* the
physics could feel, which is exactly what a non-answer must not be. On tick 0, where there is no previous action,
the fallback is a neutral `Action()` — wings level, throttle idle, guns silent.

Recommended ladder, applied **per tick and per plane**, with everything recorded in the replay:

| Failure | Effect |
|---|---|
| Exception in `act` | Whole squadron coasts this tick; traceback stored on that tick; exception count incremented |
| 5 exceptions in a match | Squadron **disabled** — planes coast, cannot fire, remain targets. **Match continues** |
| Soft tick budget exceeded (~50 ms) | As exception |
| Hard tick budget exceeded (~500 ms) | As exception, counts triple |
| Illegal shape — not a dict, non-integer key, non-Action value, unknown gun index | That plane coasts; `ActionRejected`; **rest of the squadron unaffected** |
| Action for a dead or unknown plane id | Ignored, `ActionRejected(reason="unknown_plane")`, never raises |
| Missing action for a live plane | Coast, logged as `missing_action` |
| Numeric out of range | **Clamp and log** |
| NaN or infinity anywhere | **Reject, never clamp** — NaN clamps to NaN and poisons the physics for *both* players |
| Bot stdout/stderr | Captured per bot, attached to the tick, **never on the protocol channel** |

### The stale-reply desync — a bug naive implementations ship

**The tick number must travel in the request and be echoed in the reply, from day one.** If a bot misses tick 0's
deadline but replies during tick 1, its late answer is still sitting in the pipe, and a naive engine reads it as
tick 1's answer. Every subsequent tick is then off by one, **silently**. Measured, with a bot slow on tick 0 only —
entries are (tick sent, tick the action was actually computed for):

```text
naive:  [(0,'TIMEOUT'), (1,'TIMEOUT'), (2, 0), (3, 1)]        <-- permanently off by one
fixed:  [(0,'TIMEOUT'), (1,'TIMEOUT'), (2,'TIMEOUT'), (3, 3)] <-- 3 stale replies dropped
```

Requiring the echo and draining stale replies until either the current tick arrives or the deadline expires costs a
few lines, and it makes the recorded action stream self-describing for replay. Retrofitting it means re-auditing
every match result already produced.

### Coast is a cliff for a chronically slow bot, not a slope

A consequence of coast-on-timeout worth knowing, because it is counter-intuitive: a bot that is *occasionally* late
degrades smoothly, but a bot **consistently** over budget — say 60 ms against a 50 ms deadline — never lands a
single action. Every tick times out, and its late reply is then discarded as stale, so it holds tick 0's action for
the entire match while strikes accrue.

Two things follow:

1. **A strike budget is required on top of coasting** — forfeit at roughly 3 consecutive misses or 2% of ticks.
   "Holding tick 0's action forever" is not a meaningful ladder position, and without a budget such a bot sits on
   the ladder looking as though it played.
1. **Report the accepted-action count, not just the timeout count.** `timeouts: 900/3000` invites the author to
   assume the other 2100 ticks used their choices, which is false. `accepted: 1140/3000` is the honest number and
   the one that explains their ranking.

**Tick 0 gets a much larger budget — around 2 seconds.** This is where module-level imports land, and it is the
single biggest source of unfair misses: a cold `import numpy` costs 116 ms, more than twice a 50 ms tick.
Battlesnake models this as a separate `/start` request; same idea.

**The fallback must never be better than acting.** Hold the last *accepted* action, or coast straight on tick 0. A
bot must not be able to gain by timing out, which rules out anything clever like "evade".

**A forfeited bot's planes keep existing and coast** — they do not vanish. Otherwise a forfeit mid-match changes the
physics for the surviving player and corrupts the ladder comparison.

**Validate and degrade per plane, never per squadron.** One malformed entry must not cost the other plane its tick.
Partial failure is debuggable — "plane 2 coasted 40 times this match"; whole-squadron failure is not. A bot keeping
dictionaries keyed by plane id will *naturally* emit a stale id on the tick after a loss, so that path has to be
boring rather than fatal.

**Never abort the match.** Halite kills a bot past 2000 ms and Robocode disables one after 30 skipped turns — correct
for a public ladder with thousands of entrants, wrong here. A match ending in a stack trace teaches nothing; a match
where you *watch* your plane go dumb at tick 812 teaches everything. **The viewer must show a per-tick badge for any
degraded tick.** Halite's design paper makes visual understandability its second principle exactly because
competitors improve by watching.

**Determinism: the engine owns the RNG.** A match is `(seed, class-table hash, bot files) -> replay`. Each bot gets
its *own* `random.Random` instance in the state, so replays reproduce and a bot cannot reseed the global `random`
module and perturb the engine's own rolls.

## 6. Versioning

Battlesnake's pattern, which worked: the bot declares its own version, old versions keep working alongside new, and
retirement happens on a published date.

- `API_VERSION = 1` as a module constant in every bot file. The engine refuses an unknown major with a one-line
  message naming the migration note.
- **Within a major version, additive only.** Append fields to `state`; never rename or remove one.
- **`Action` is a keyword-only dataclass**, so adding a field cannot break positional construction in an old bot.
  Any new field defaults to "no change".
- The replay header records API version, engine version, and the class-table hash.

## 7. Sample bots

Halite's design paper sets the bar as a tooling requirement, not a documentation one: "the game and its accompanying
environment need to be easy to understand and set up in **under ten minutes**, regardless of platform or user
background." It also shipped a dummy bot so you could submit before writing any code.

Each sample is 20-50 lines, teaches exactly one idea, and is squadron-shaped from rung one.

| # | File | Teaches |
|---|---|---|
| 0 | `sitting_duck.py` — returns `{}` | Proves the harness; doubles as the coast-path regression test |
| 1 | `circler.py` — throttle to stall speed, constant steer, fire when a contact is within a few degrees of the nose | The state shape, the id-keyed dict, `angle_diff`, cooldown and ammo gating. Planes cannot sit still, so "sits still and shoots" becomes minimum-radius circling — itself the lesson |
| 2 | `chaser.py` — `geom.delta` to the nearest contact, steer toward it, throttle up, fire when aligned | Torus-correct bearing, the steer-sign bug, and **why it always misses** |
| 3 | `leader.py` — aim at `contact.pos + contact.vel * t_flight`, two fixed-point iterations | Intercept geometry, bullet travel time, iterate-to-converge. **The "aha" bot** |
| 4 | `wingman.py` — the scout flies a search pattern and never engages; the fighter engages only contacts whose `seen_by` includes the scout; both keep `self.last_seen` and sweep a stale position when a contact drops | Everything the squadron design adds: shared vision, `seen_by`, per-plane roles, memory across ticks |
| 5 | `dodger.py` *(optional)* — break hard when an enemy's nose is pointed at you and you are inside its gun arc | Threat evaluation and the speed-versus-turn-rate coupling. Note it cannot dodge *bullets*, which are invisible; it dodges the **firing solution**, which is the better lesson anyway |

**Ship the samples as the engine's regression tests** — one artifact, two jobs.

### The author-side test harness falls out for free

Because the contract is a pure function, a bot is directly unit-testable with no engine, no subprocess and no I/O:

```python
def test_turns_toward_contact():
    state = make_state(squadron=[plane(id=0, x=100, y=100, heading_deg=0.0)],
                       contacts=[contact(x=200, y=100)])
    assert act(state)[0].steer == 0.0      # already pointing at it
```

Three things ship alongside the engine: a **snapshot builder** (`make_state`, `plane`, `contact`) with sane defaults
so a test names only what it cares about (~40 lines); **the engine's own `validate()`, exported** — reusing the same
function means an author can never pass their own tests and fail the engine's check; and a one-command local match
against a supplied dummy bot. Every competition that got adoption shipped that last one.

For the engine's side of the boundary, the deliberately-broken-bot family *is* the test suite: crash, hang, garbage,
illegal values, chatty, prints-protocol-JSON, slow-on-first-tick. Verified behaviour of all seven is recorded in
[tech-decisions.md](tech-decisions.md).

Onboarding is tooling: `python -m skybattle duel mybot.py samples/leader.py --seed 7` printing one result line, with
`--replay` and `--headless`. And `--rules` prints the class table, because the numbers *are* the game and nobody
should have to read source for them.

## 8. Anti-cheat, and the honest limits

The friends-tournament threat model means this section is about *accidents and mischief*, not attackers. Structural
answers are still preferred, because they cost nothing to enforce.

**Structural immunity beats policing.** Battlesnake (JSON over HTTP) and Tank Royale (separate processes over
WebSocket) make state mutation and opponent-peeking impossible by construction — you never receive an object graph.
Robocode's in-process model is the only surveyed design that needed a security manager, and it is the only one with
an exploit history: robots reaching engine internals through the AWT event queue, through static references, and
through reflection, each fixed by disabling the offending robot at runtime.

- **Frozen, tuple-based payload built fresh per squadron per tick, with no back-pointers.** The leak to grep for is
  a field path like `state.contacts[0].world`.
- **Enforce fog by construction.** Build each squadron's payload from the union of its own cones. Never hand over
  the full world with a `visible` flag — that is a one-line cheat.
- **Anonymise opponents:** no author names, no file names, no bot names in the payload. Opponents are `squadron 0`
  and `squadron 1`. This makes `if opponent == "alice": cooperate` unwritable.
- **Quantise every observable a bot controls.** Firepower is a per-gun constant, not a float the bot picks. This is
  a real incident, not a hypothetical: in Robocode melee, a player *"came up with a fantastic strategy based around
  the fact that shot strength was a float that could be modified. He used this to have his team fire extremely weak
  shots at each other, with the value of the float encoding different messages."* Any continuous, bot-chosen,
  globally observable value is a covert channel.
- **1v1 squadron duels for anything that counts.** Collusion needs three independent players; Halite I's top four
  adopted a mutual non-aggression pact, which its design paper lists among the competition's emergent phenomena.
- **The social fix, from Halite:** publish all replays and all sources after the tournament, which makes peeking
  worthless rather than impossible.

## 9. Where the research disagrees with a decision already made

**Enemy bullet visibility.** [game-design.md](game-design.md) records the decision that bullets are never visible,
and the technology research endorses it twice over: it is 31x cheaper to compute and it matches Robocode, where
inferring incoming fire is among the richest parts of bot-writing.

The design research recommended the opposite — bullets visible inside the cone — on one argument worth recording:
**dodging is the most satisfying beginner win**, and Robocode's alternative (infer the shot from the enemy's energy
drop, then wave-surf) is a world-class technique rather than a second-week one. It also flagged this as the fork it
was least confident about in either direction.

The decision stands. The cost is that the first satisfying win now has to come from somewhere else — which is what
sample rung 3, `leader.py`, is for.

**Note that Robocode's inference route is not available here even as a consolation.** That technique works because
in Robocode *firing costs energy*, so an enemy's energy drop is evidence of a shot. Here firing costs **ammo**, and
hit points only drop when a plane is hit — so `contact.hp` reveals damage *taken*, never shots *fired*.

`contact.hp` is exposed anyway, but for target prioritisation rather than shot inference — see §2.
