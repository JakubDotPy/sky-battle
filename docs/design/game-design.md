# Sky Battle — game design

**Status:** working draft. Brainstorm in progress; three of four research threads still open.
**Started:** 2026-09-09

## 1. What this is

A top-down 2D aerial dogfight simulator that nobody plays interactively. Players write a program; the program flies
the planes.

Two layers, strictly separated:

**The engine.** Owns the simulation: positions, headings, speeds, turn rates, bullets, collisions, damage, ammo, the
tick loop, match end conditions, and the recording/rendering that lets a human watch the fight. Runs headless by
default so a tournament can play thousands of matches without a window.

**The bot.** One `.py` file per player. It has no game loop of its own and no access to engine internals. Once per tick
the engine hands it a snapshot of what its planes can see; it returns one action per plane. The engine applies the
actions, steps the simulation, and repeats. An action is **composite** — it carries the throttle setting, the control
input, and which guns to fire, all at once, because a real pilot works all three simultaneously. The bot is a pure
client of a frozen API.

The interesting design work is the boundary, not the graphics: what a bot can see, what an action costs, how a broken
bot fails without taking the match down with it, and how two people's bots meet in a ranked match.

### Origin

A university assignment the author remembers: a professor supplied an engine, students submitted a single `.py` file
that steered a plane left/right, changed speed, and shot. The original is a starting point for the feel, not a
specification to reproduce — see [§3](#3-decisions-made).

## 2. Audience and success criteria

**Audience: a small group of friends and colleagues.** Several people each write a bot; matches get run; a ladder
says whose bot is best.

This choice sets two hard requirements and cancels a third:

1. **Must survive other people's broken bots.** Crashes, infinite loops, garbage output, actions for planes that are
   already dead. A bot that hangs must not hang the match, and its author must get a traceback good enough to fix it.
1. **Must rank bots without a human refereeing.** A tournament has to run unattended and produce a standing.
1. **Need not survive malicious bots.** No filesystem attacks, no exfiltration, no forkbombs. This removes
   containers, seccomp, and VM isolation from scope — kept only as a documented upgrade path if the project ever goes
   public.

Success: a Friday-afternoon tournament that runs without babysitting, and bots that are fun to write.

## 2a. Design principles

**When in doubt, prefer realism** — then consult on the gameplay balance before committing. Recorded as a standing
tie-break so small decisions don't each need a round-trip.

**With one guard rail: realism only earns its place if a bot can perceive it and act on it.** Air density, prop
wash and engine temperature change no decision a bot makes, so modelling them is invisible complexity. Realism that
changes a *choice* is the good kind. That test is what separates energy management (a real decision, every tick)
from a fuel-mixture model (a number nobody reads).

**One deliberate, permanent exception: the wrap-around arena.** A toroidal sky is not realistic under any reading.
It is kept because it abolishes corner-camping and because walls are absurd for aircraft. Recorded here so the
principle above is not later read as a reason to reopen it.

## 3. Decisions made

| Decision | Choice | Why |
|---|---|---|
| Fidelity to the original | Starting point only; free to redesign | The original's rules are half-remembered, and research shows several of them are the genre's minority conventions |
| Control unit | **One bot controls a squadron** of N planes; one action per plane per tick | Free-for-all is then just squadron size 1 — one API, both modes, no separate code paths |
| Action shape | **Composite** — one `Action` per plane per tick carrying `throttle`, `steer` and the set of guns to fire | In a real cockpit the throttle, the controls and the trigger are worked simultaneously. This drops the original's turn-*or*-shoot constraint deliberately; energy bleed replaces it as the central tension |
| Control inputs | **Continuous, not three-valued.** `steer` in [-1, +1], `throttle` in [0, 1] | A stick and a throttle lever have travel. It also gives energy management its dial: a gentle turn bleeds less speed than a hard one, which is the decision the whole flight model exists to create |
| Squadron size | **2 first**, generalise to n | Two is enough to make coordination real; the API is written for n from the start |
| Visibility | **Limited vision cone per plane** (fog of war) | Forced by the class design: a scout's wider cone is meaningless without it. Also the genre's main depth differentiator |
| Close-range awareness | **Circular vision bubble per class, unioned with the cones** ([§8](#8-starting-class-table)) | Measured: half of all enemy pairs within 50 units — formation-flying distance — went undetected under cone-only vision, because a forward cone cannot see a target off its own beam or astern. The bubble models a pilot looking around; the cone stays the long-range search instrument |
| Squadron vision | **Shared** between squadron-mates — "pilots giving each other shoutouts over radio" | Makes a scout an actual scout |
| Arena | **Wrap-around torus**, no walls | Walls are silly for planes; no corners to camp in |
| Class stats | **Data file, not code** | Balance is a permanent, ongoing problem; a balance pass must not be a code change |
| Class stats | **TOML, read by stdlib `tomllib`. No Python class per plane kind** | The kinds differ only in numbers and gun-mount bearings, which is data. Balance files are hand-edited and TOML has comments — a tuning number with no note explaining it is one nobody dares touch |
| Gun stats | **A separate gun table**, one row per mount | The bomber's two guns already differ in bearing, dispersion, cooldown, damage, ammo and lifetime; this is the TOML array-of-tables shape (`[[bomber.guns]]`) |
| Cost of a wide cone | **Paid in the stat line** — lower HP, and possibly other stats — not in update rate | Keeps vision a single readable number per class instead of adding a second clock the bot must model. RoboCup's alternative prices vision in *time*; that stays available if the stat-line price proves too weak |
| What a bot sees | **Planes only. Bullets are never visible** | 31x cheaper to compute *and* the better game — see below |
| Contact frame | **Both** — bearing and range from the receiving plane, plus absolute position | Relative spares every author the seam arithmetic; absolute is what a `last_seen` memory needs, since relative bearings go stale the moment the observer turns |
| Shared vision | **Instant, perfect union of the living squadron's cones.** No radio channel, no bandwidth budget, no delay | One file, one process, one memory — a bandwidth limit is a fiction the author routes around by reading their own instance variables. Every game that limits comms does so because its units are separate processes |
| Lost contacts | **The engine remembers nothing** — no last-known position, no age | Keeping that memory is the first genuinely worthwhile data-structure exercise the fog creates, and omitting it costs the engine zero lines |
| Contact identity | **A stable id while continuously visible; a new id after re-acquisition** | Tracking while visible is free, re-acquisition is a real inference problem — and it rewards using a scout to *keep* eyes on a target rather than glancing at it |
| Enemy hit points | **Visible.** Ammo and cooldown are not | Wounded-target prioritisation is a real strategic lever, and battle damage is honestly observable at range. Knowing an enemy is dry would make it free to approach |
| Turn rate curve | **Peaks at a corner speed** between stall and max, not at stall | Otherwise the dominant strategy is to fly at stall speed and pirouette |
| Tick order | **Resolve first, then snapshot.** Apply actions, integrate, resolve collisions and damage and deaths — *then* build each squadron's view | A plane that died this tick contributes no vision and appears as no contact. One rule, no edge cases |
| Energy | **Turning bleeds speed** (realism candidate A, adopted) | Real dogfighting is energy management; it is also the economic cure for stall-speed pirouetting |
| Damage | **Degrades performance** — max speed and turn rate fall with damage (candidate D, adopted) | A wounded plane is genuinely weaker prey, reinforcing the decision to expose `contact.hp` |
| Bullets | **Inherit shooter velocity** (candidate E, adopted) | One vector addition; fast planes' rounds arrive sooner, loiterers' are sluggish |
| Deadline miss | **No command is sent; the plane coasts** — holds throttle, zero steering, no fire | Momentum is the physically honest default for an aircraft, and a non-answer must be neither an advantage nor an instant death. Battlesnake does the same |
| Planes always move | **Spawn with an initial position and velocity**; stall speed is above zero | There is no "stop" action to fall back on, which is why coast is the right default |

### Plane classes

Classes differ along several axes, and more axes are expected. Current set:

- **Scout** — wider and longer vision cone.
- **Heavy / bomber** — slower, but carries a **rear-facing gun** as well as a forward one, simulating a rear gunner.
  The bot therefore picks *which* gun to fire from.
- **All classes** differ in: max speed, **stall speed** (a minimum speed — the plane does not fall below it, it simply
  cannot go slower), ammo capacity (finite, no regeneration), damage per round, and hit points.

### What a bot sees

A bot receives, once per tick, one view per squadron. The view holds:

- **Its own planes** in full — position, heading, speed, hit points, ammo per gun, and its own capabilities (max and
  stall speed, gun mounts, cone geometry) so a bot can be written class-agnostically.
- **Enemy contacts**, as **bearing and range relative to the plane reading them**, plus whatever else the sighting
  revealed. A contact is a structurally different type from an own-plane: no hit points, no ammo, no fuel. Leaking
  information a bot should not have then becomes a type error rather than an exploit somebody finds in week three.
- **Its own rounds in flight**, and hit notifications.

**Enemy bullets are never visible.** You infer incoming fire from being hit, from an enemy's bearing, and from the
knowledge that they had a firing solution. This was the author's call and the research independently endorsed it
twice: Robocode does exactly this and the resulting inference is among the richest parts of writing a bot, and
measured, it is **31x cheaper** — the fog-of-war filter drops from 12.5 s to 0.4 s of compute per match, which is
the difference between needing numpy and needing no dependencies at all.

**Contacts are expressed from the receiver's point of view.** If a scout spots an enemy and the sighting reaches its
wingman, the wingman reads a bearing and range measured from *the wingman's* own nose. The engine holds the absolute
truth and re-projects per plane per tick. This costs the engine a little and saves every bot author the one piece of
maths most likely to defeat them.

### Flight model

Semi-implicit Euler integration on a fixed `dt` of 1/30 s of *game* time — never a wall-clock delta. Planes are
kinematic agents whose heading is commanded, not force-driven, so no physics engine is involved.

**Turn rate is coupled to speed.** Robocode is the canonical precedent, using
`maxTurnRate = 10 - 0.75 * |velocity|` degrees per turn — full agility stationary, 40% of it at top speed. Here it
becomes a linear interpolation between two per-class numbers in the TOML table, which reads honestly in a balance
file. The bot-facing API should also expose **turn radius** (`v / omega`), because that is the quantity a bot
actually has to reason about.

> **The trap.** If turn rate strictly decreases with speed, the dominant strategy is to fly at stall speed and
> pirouette, and every match degenerates into loitering. A floor to sit on is a bad thing to hand a bot author.
> The fix is **corner speed** — make turn rate peak at an intermediate speed, as real aircraft do. That replaces a
> floor to sit on with an optimum to discover, which is a far better problem. See open question on this.

### Consequences already worked out

- **Firing takes a set of gun ids.** A rear gunner means the bomber picks *which* guns fire — possibly both, since
  two crew members act at once. The original's flat four-action set is gone, replaced by one composite action whose
  `fire` field is a set. An empty set means hold fire.
- **Damage needs hit points.** Per-class ammo damage only means something if a plane survives more than one hit.
- **Turn rate should couple to speed** (slow = tighter turn). Stall speeds create the natural place to hang this, and
  it pays for itself twice: throttle management becomes a real decision instead of "always full", and the bomber's
  slowness becomes a manoeuvrability *advantage* rather than pure downside — balance without a spreadsheet.
- **Finite ammo is the stalemate breaker.** A bot that cannot win eventually cannot shoot either.
- **Bots must be writable class-agnostically.** The API has to report a plane's own capabilities — max and stall
  speed, gun mounts, ammo remaining, cone geometry — so one bot file can fly whatever it is given.
- **Wrap-around must not leak into bot code.** Toroidal distance is a genuine nuisance to get right. The engine will
  hand bots pre-wrapped relative vectors (bearing and range), so a bot never does seam arithmetic. The engine still
  has to get it right internally, including bullets crossing the seam.

## 4. Prior art

Research finding, four independent enumerations, all clean: **a top-down 2D plane dogfight bot-programming game does
not exist** — not in Python, not open-source, not closed-source, not as a community. Checked
[awesome-games-of-coding](https://github.com/michelpereira/awesome-games-of-coding) (~35 entries, the canonical genre
list), GitHub's `programming-game` and `bot-arena` topics, [codeclash.ai](https://codeclash.ai/)'s arena set, and
CodinGame's full ~25-game multiplayer catalog. Zero aviation entries in any of them.

Everything plane-themed that exists is one of: a reinforcement-learning environment (the human's loop drives
`env.step()`; no ladder, no opponent submission), a human-played game, or DARPA's AlphaDogfight (a real F-16
simulator, not a programming game).

### Nearest neighbours

| System | How close | Misses on |
|---|---|---|
| [Coders Strike Back](https://www.codingame.com/multiplayer/bot-programming/coders-strike-back) (CodinGame) | Mechanically nearest: 2D continuous position + heading + inertia, per-turn output is steer-target plus thrust over stdin/stdout | No weapons, no plane theme, closed engine |
| [Space Battle Arena](https://github.com/Mikeware/SpaceBattleArena) | Nearest architecture *and* course precedent: top-down 2D, thrust/turn/fire, server in Python (pygame + pymunk) | Space theme; bots are written in Java |
| [Combat Turtles](https://github.com/adam-rumpf/combat-turtles) | Nearest single-file-Python classroom match: pure-stdlib, top-down arena, subclass and override `step()` | 2 bots only, in-process (a hung bot hangs the engine), turtles |
| [NetBots](https://github.com/dbakewel/netbots) | Python, top-down, move/scan/fire, built-in viewer, documented for classroom use | Robots; networked-by-design adds accidental complexity |
| [Robocode](https://robocode.sourceforge.io/) / [Tank Royale](https://github.com/robocode-dev/tank-royale) | The genre canon; radar-limited vision; Tank Royale ships an official **Python** bot API and a 30 ms turn timeout over WebSocket + JSON | Tanks |
| [CS188 Pacman Capture-the-Flag](https://www-inst.eecs.berkeley.edu/~cs188/pacman/contest.html) (Berkeley) | Structurally closest to the origin story: submit one `.py`, `chooseAction(state)` returns exactly one action, partial observability with noisy distances, unattended nightly tournaments | Grid movement, not flight |

So the design is not derivative of any one thing. It is **Robocode's control model, CodinGame's transport, and
CS188's submission unit, in a theme nobody has used.**

### Cross-cutting lessons

- **Composite actions are the genre norm.** Robocode, Combat Turtles, Screeps, Halite, CodinGame and Lux all let a
  bot issue several commands per tick; only Battlesnake, Core War, Robot Game and BotBowl are strictly one-action.
  The design considered the strict form — the original assignment's constraint — and dropped it on realism grounds.
  What survives is the *per-unit* discipline that is mainstream for squadron games: exactly one `Action` per plane
  per tick, no more (Halite: one move per ship; Screeps: one action per creep).
- **Full visibility is the genre norm.** Genuine partial observability exists only in Robocode (radar cone), RoboCup
  2D (a tunable cone with an explicit vision-versus-bandwidth trade), Lux AI (vision radius), Screeps World, ORTS and
  CS188 Pacman. It is the single feature that most raises strategic depth — and the one that most raises the
  difficulty of writing a bot.
- **In-process sandboxing of untrusted code is a dead end, in every language.** Java removed `SecurityManager` in
  Java 24 and Robocode's own maintainer says fixing its security model needs a large rewrite; Python never had a
  working equivalent (`rexec` and `Bastion` were removed, and `RestrictedPython` is explicitly not a security
  boundary). Do not attempt it.
- **There are exactly two answers to the infinite-loop problem,** and every system in the genre picks one:
  a **preemptive wall-clock deadline** (Pommerman: 100 ms then substitute a Stop action; Battlesnake: repeat the last
  move; Robocode: skip the turn, ban after too many; CodinGame/Halite/Lux: forfeit) or a **cooperative yield
  contract** (Bitburner — where it visibly fails: a busy loop freezes the whole game, a known open bug needing a
  reload to escape). There is no third option.
- **Control inversion is the real genre boundary.** RL environments put the human's loop in charge via `env.step()`.
  Bot arenas invert it: the engine owns the loop and calls into the bot. This project is the second kind, and should
  copy the second kind's conventions rather than Gym's.
- **The format has a deep university pedigree** — CS188 Pacman CTF (cloned into dozens of AI courses, with a
  cross-university hall of fame and published write-ups), MIT Battlecode (a credit-bearing course, 25+ years),
  Space Battle Arena, Combat Turtles, NetBots, RoboCup Simulation League, and the Google AI Challenge (run by the
  University of Waterloo CS Club). Worth mining for assignment structure if the project ever gets taught.

## 5. Open questions

**None outstanding.** Every design fork raised during the brainstorm is now recorded as a decision above. What
remains is not design but tuning: the numbers in the class and gun tables are placeholders awaiting a dedicated
balance pass, which is the one activity this document expects to repeat indefinitely.

## 6. Research

All four research threads reported. Findings are folded into this document, [bot-api.md](bot-api.md) and
[tech-decisions.md](tech-decisions.md) at the point they bear on a decision, rather than kept as a separate
literature section.

## 7. Match format and scoring

Recommended, following Robocode's formula — a quarter-century-tuned answer to "make hiding lose". Not yet confirmed.

### Scoring, per round, per squadron

```text
  1  x  damage dealt
+ 20%  of damage dealt to any enemy plane you destroyed
+ 50   x (enemy planes destroyed while you still had a plane alive)
+ 10   x (enemy planes dead)   -- only if you are the last squadron flying
```

Robocode is explicit that "a bot will not necessarily win, just by being the last bot left on the arena as the last
survivor", and that a win by inactivity timeout pays no survivor bonus. **Survival time is never scored on its own —
that is precisely the camping incentive.**

**Planes pass through each other.** A top-down 2D arena is a projection of a 3D sky, so two planes sharing an
`(x, y)` are simply flying under or over one another at different altitudes. Only bullets collide with planes.

**Terminology, used consistently across all three documents:** a **round** is one fight, ending when one squadron is
left flying or at a 3000-tick timeout, after which the higher score wins and an exact tie is a draw. A **match** is
**11 rounds** — odd, so draws are rare — with fresh spawns, fixed consecutive seeds, and scores summed.

### Anti-passivity is mandatory, not optional

The torus abolishes corner-camping — Robocode's shipped `Corners` bot would have nothing to say here — but it also
**removes the map's own answer to fleeing.** With no walls, a faster plane can outrun a pursuer in a straight line
forever, where on a bounded map the pursued eventually runs out of room. That makes an explicit clock load-bearing.

**Inactivity drain, Robocode's mechanic retuned:** if no plane has taken damage for 600 ticks, every living plane
loses 1 hp per tick until one dies; any damage resets the counter; a win by drain pays no last-survivor bonus. Four
lines, topology-independent, and it punishes *mutual* passivity without punishing a bot that is legitimately evading
while under fire.

**Ammo is finite, one magazine per gun.** At an 8-tick cooldown a 3000-tick round allows roughly 375 shots per gun,
so an 80-120 round loadout is a 25-30% duty cycle. A squadron out of ammo can draw but cannot win on points, which
bounds hoarding.

**A shrinking arena is rejected** as the primary mechanic: it is a second geometry every bot must model, and on a
torus a shrinking circle is not even well-defined. Battlesnake's own design agrees — the shrink is a variant, the
clock is the rule.

### Squadron composition

**Mandated and symmetric:** at squadron size 2, exactly one scout and one fighter; at size 3, add the bomber. Both
sides field the same composition.

This is the one place the research was emphatic, and the evidence is not flattering to free choice. Battlecode
offers asymmetric units and every documented year collapsed the same way: 2019's "nearly every top team used a
lattice, and the recommendation most people gave to beat lattices was to lattice harder"; 2023's destabilizers
"ended up not being used despite their potential strategic value" because nobody could afford them; 2025's SRPs
"very quickly nerfed after some horrific matches". The fix in every case was **iterative balance patches between
tournament stages**, which needs a large player base to discover the meta and a staged calendar to patch between.
A group of friends has neither.

The contrast is the argument: **Robocode has one chassis, no classes, and no balance patches in 25 years** — its
depth comes from physics coupling, not from a roster. Mandating the composition removes the "pick the best class"
decision that there is nothing to lose, and forces the *heterogeneous coordination* problem that is the entire
reason squadrons are worth building.

Corollary: **differentiate classes by capability, not by stat line.** A class defined by numbers gets dominated; a
class defined by a capability keeps a niche. The scout's value is information, the bomber's is that it can be chased
and still shoot, the fighter's is turn rate.

### Ladder

**For up to about 12 bots: double round-robin — every ordered pair, one match each — ranked by summed score. Nothing
else.** Ten bots is 90 ordered pairs, so 90 matches or **990 rounds**. (Single round-robin would be 45 pairs and 495
rounds; the earlier draft quoted the single-round-robin figure under the double-round-robin heading.) Exhaustive beats
estimated, and there is no rating theory to explain or defend. Halite and Battlesnake both use TrueSkill and it is ten
lines with the `trueskill` package, but it only earns its keep past roughly 16 bots or with continuous submissions.

**Report mean and standard error over the fixed seed set, not just the total.** Without it, "my bot got better" is
unfalsifiable — the single most common complaint across every competition postmortem surveyed.

## 8. Starting class table

Recommended shape, not confirmed numbers. The point is the shape; every value is a balance knob.

**Airframe:**

| Class | HP | Radius | Stall | Corner | Max | Turn at stall / corner / max |
|---|---|---|---|---|---|---|
| Scout | 70 | 9 u | 3 | 5 | 9 u/tick | 5 / 9 / 4.5 deg |
| Fighter | 100 | 12 u | 2 | 4.5 | 8 | 5.5 / 10 / 4 deg |
| Bomber | 160 | 18 u | 2 | 3 | 5 | 3.5 / 6 / 3 deg |

Radius sets the target a plane's bulk presents to an incoming bullet — a bomber's 160 hp is partly paid for by
being easier to hit.

**Guns** — one row per mount, which is exactly the TOML array-of-tables shape (`[[bomber.guns]]` twice), so a rear
gun is `bearing = 180.0` rather than a subclass:

| Class | Mount | Bearing | Dispersion | Cooldown | Damage | Ammo | Lifetime | Muzzle | Sustained DPS |
|---|---|---|---|---|---|---|---|---|---|
| Scout | forward | 0 deg | 2.5 deg | **6 ticks** | 8 | 80 | 20 ticks | 34 u/tick | 1.33 |
| Fighter | forward | 0 deg | 2.0 deg | **8 ticks** | 10 | 120 | 18 ticks | 30 u/tick | 1.25 |
| Bomber | forward | 0 deg | 3.0 deg | **14 ticks** | 14 | 90 | 15 ticks | 26 u/tick | 1.00 |
| Bomber | rear | 180 deg | 6.0 deg | **10 ticks** | 10 | 60 | 11 ticks | 28 u/tick | 1.00 |

**Muzzle speed is a per-gun property too**, and its shape is deliberate: heavier rounds leave the barrel slower,
which pairs with them already firing slower and hitting harder. The bomber's forward gun now hits hardest, fires
slowest, *and* flies slowest — heavy artillery, coherently, and also the hardest of the four guns to lead, since a
slow round gives a target longer to have moved by the time it arrives.

**Vision cones and bubble:**

| Class | Forward cone | Rear cone | Bubble |
|---|---|---|---|
| Scout | 120 deg / 900 u | — | 120 u |
| Fighter | 70 deg / 600 u | — | 150 u |
| Bomber | 50 deg / 450 u | 50 deg / 350 u | 220 u |

### Vision bubble: close-range awareness, unioned with the cones

**The evidence.** Three rounds of `leader.py` vs `chaser.py`, counting live enemy pairs by separation, against
cone-only vision:

```text
  within    pairs   had contact    BLIND
    50u       76      36 ( 47%)     52%
   100u      162      84 ( 51%)     48%
   150u      258     142 ( 55%)     44%
```

**Half the time an enemy is within 50 units — formation-flying distance — the squadron has no idea it is there**,
because vision is a forward cone only and a close enemy sits outside the arc. That is not fog of war, it is an
absurdity: a pilot with an enemy fifty metres off the wing knows about it.

**The fix is a per-class circular vision bubble, unioned with the existing cones**: whatever is this close is seen
regardless of heading. It splits vision into two jobs. The **cone** stays a long-range *search* instrument — the
scout's speciality, still the widest and longest of the three. The **bubble** is short-range *situational
awareness*, which makes the close-in turning fight about flying rather than about whose cone happened to sweep the
right way.

**The bomber has the largest bubble and the narrowest cone, deliberately.** Multiple crew and many windows around
the fuselage mean it is worst at spotting something coming and best at knowing what is already on top of it. A
later balance pass should read this paragraph before "fixing" that inversion — it is not an oversight.

**Bubble range sits at roughly 25% of each class's gun reach** (308–680 u — see the muzzle-speed reach figures
further down this section). That ceiling matters: if the bubble approached gun range, a plane could shoot
everything it could see and the cone would stop mattering. Bubble ranges are also far larger than any class's turn
circle (~26–32 u), so a plane cannot rotate out of its own bubble — awareness stays stable rather than flickering
as the nose swings.

> **These numbers are placeholders awaiting a dedicated balance pass.** Known already: the scout should be weaker
> than shown — lower HP — since its wide cone is its whole identity and it should not also be durable.

**Rate of fire is a per-gun property, not per-class**, because the bomber's two guns already differ in everything
else. And the realism tie-break supplies the balance lever for free: **heavier rounds fire slower** (8/6, 10/8,
14/14 damage per cooldown tick — monotone). That makes damage and cooldown a deliberate trade rather than two
independent knobs — the scout's light, fast-firing gun (1.33 damage/tick, the "Sustained DPS" column above) and the
bomber's slow, heavy one (1.00) land within a third of each other on sustained per-tick damage, with the fighter
(1.25) in between, so they differ in *how* they have to be used rather than in how strong they are. That parity
does not extend to the full magazine: total damage before a reload is 640 (scout), 1200 (fighter) and 1260 (bomber
forward), which is closer to double, not a third — a light gun keeps up tick to tick but runs dry first. Burst
damage, forgiveness of a near-miss, and ammo endurance all fall out of the same two numbers.

**Guns are fixed mounts. There is no aiming.** A round leaves along the mount's bearing — the bomber's rear gun
always fires straight astern — and a bot aims by flying the aeroplane, exactly as it does a forward gun. What
`dispersion_deg` expresses is *precision*: each round scatters by a random amount inside that arc, so a wider
mount groups worse. Note the bomber's **rear mount has much wider dispersion (6 deg) than any forward gun (2-3
deg)** — it is the least precise gun on any class. That is realistic, and it is the bomber's defensive identity:
its rear gun's value is that it can shoot at a pursuer at all, not that it tracks one.

**The shooter's velocity is added to the round as a vector, not as a scalar along the firing direction.** That
distinction is the rear gun's whole character: a bomber running away throws its rear rounds *slower*, because its
own motion subtracts from the muzzle velocity — a scalar add would instead make the rounds faster the harder the
bomber runs, which is backwards and was a real bug caught while building this. A forward gun still gets faster
with speed either way, since there the two vectors point the same way.

**Lifetime is a tick count, not a distance, and rounds inherit the shooter's velocity as a vector — so speed's
effect on reach depends on the mount.** A round expires after its gun's `lifetime_ticks`, travelling
`lifetime_ticks - 1` ticks at a constant velocity (it does not move on the tick its `ticks_left` reaches 1). At
rest every gun lands inside its own cone: scout 646 u vs. its 900 u cone, fighter 510 u vs. 600 u, bomber forward
364 u vs. 450 u, bomber rear 280 u vs. 350 u.

Speed changes that, and in opposite directions per mount. A **forward** gun's muzzle velocity and the plane's own
motion point the same way, so reach grows with speed: `(lifetime_ticks - 1) x (muzzle_speed + max_speed)`. A
**rear** gun fires against the plane's own motion, so reach *shrinks* with speed instead:
`(lifetime_ticks - 1) x (muzzle_speed - max_speed)`. At each class's own max speed: scout 817 vs. 900 (still
inside), bomber forward 434 vs. 450 (still inside, close enough that a small future change could flip it), bomber
rear 230 vs. 350 (shrinks, and lands further inside its cone than at rest) — and **the fighter's forward gun
reaches 646 units against its own 600-unit cone: the one gun, at today's placeholder numbers, that can already
throw a round beyond the sight of the plane that fired it.** So the affordance — long-range fire at a remembered
position, since a round can outlive its own firer's view of the target — is real today for exactly one gun, not a
general property of every gun at speed, and worth re-checking whenever any of these four numbers move.

**Three speed points, not two.** A two-point table can only express a turn rate that falls monotonically with speed,
which *is* the pirouette-at-stall-speed trap described in the flight-model section — the previous draft of this
table implemented the exact failure mode the document warns about. Corner speed is the third parameter: turn rate
rises from stall to corner, then falls to max. Piecewise-linear between the three points is enough.

**Constraint, not a preference: no cone range may exceed half the shorter map dimension.** On a torus a longer range
lets a plane see the same enemy through both sides at once and the fog stops meaning anything.

So the shorter dimension must be **at least twice the longest cone range**: with a 900-unit scout cone, no dimension
below 1800. The engine's default arena is **2000 x 2000**, and `load_classes(arena=...)` enforces the rule at load
time rather than trusting it.

> An earlier draft of this section recommended 1800 x 1400 with a 900-unit cone, which violates the constraint
> stated immediately above it — half of 1400 is 700. The engine rejected it on the first CLI invocation, which is
> the check working as intended. Worth noting for the balance pass: a 900-unit cone on a 2000-unit torus lets a
> scout see nearly half the map's width, so the cone is the more likely thing to shrink than the arena is to grow.

## 9. Realism candidates

Generated by applying the realism tie-break to the current spec. Each is cheap to implement; each changes gameplay,
so none is adopted until reviewed.

### A. Turning bleeds speed — energy management

**The big one.** Real dogfighting is the management of energy: a hard turn trades speed for angles, and the whole
boom-and-zoom versus turn-fighting dichotomy falls out of that single trade. The current spec couples turn *rate* to
speed but lets a plane turn for free, so speed only ever changes when the bot asks.

**Implementation:** steering costs speed proportional to turn rate, throttle restores it against a per-class
acceleration. Two numbers per class.

**Gameplay:** this is the deepest mechanic available at the lowest cost, and it is the natural counter-pressure to
the stall-speed pirouette — a plane that turns hard repeatedly ends up slow, and slow means it cannot disengage.
It also gives corner speed real teeth: sitting at corner speed becomes a genuine choice rather than a free optimum.

**Cost:** the single biggest jump in difficulty for a bot author, because throttle stops being set-and-forget.

### B. Stall has consequences — NOT ADOPTED

The spec currently says a plane at stall speed "does not fall, it simply cannot go slower" — a floor. Realistically,
below stall an aircraft loses lift and departs controlled flight.

**Implementation:** commanding a decelerate at stall speed, or turning hard enough at low speed, triggers a stall:
for N ticks the plane cannot steer and its heading drifts, then it recovers. A per-class `stall_recovery_ticks`.

**Gameplay:** makes the low-speed corner of the envelope genuinely dangerous instead of a safe place to loiter, which
is the same problem A solves from the other side. Adopting both may be one mechanic too many — worth deciding
together.

### C. The rear gunner is a different person — SUPERSEDED

Moot under the composite action model. `Action.fire` is a *set* of gun ids, so a bomber fires both guns in the same
tick as it flies — which is what two crew members actually do. No second action slot, no schema change.

### C (original proposal). The rear gunner is a different person

The bomber's rear gun is operated by a crew member, not the pilot. The current one-action-per-plane-per-tick rule
makes firing it compete with the pilot's flying.

**Implementation:** the rear gun gets its own action slot — the bomber returns a flying action *and* a rear-gun
action in the same tick.

**Gameplay:** this is what would make the bomber genuinely *different* rather than merely slow and tanky, and it is
realistic for exactly the right reason. It also complicates the action schema, which is currently one action per
plane, full stop.

### D. Damage degrades performance

Hit points are currently a flat pool: a plane at 10 HP flies exactly like a plane at 160.

**Implementation:** interpolate max speed and turn rate down with damage, e.g. to 70% of nominal at zero HP.

**Gameplay:** synergises with the decision to expose `contact.hp` — a wounded target becomes genuinely weaker prey
rather than merely closer to death, so prioritising it is doubly rewarded. Cheap: two multipliers.

**Cost:** a damaged plane may become unable to escape, which can make the endgame a foregone conclusion.

### E. Bullets inherit shooter velocity

Muzzle velocity adds to the aircraft's own. Currently rounds presumably leave the gun at a fixed speed.

**Implementation:** one vector addition at spawn.

**Gameplay:** a fast plane's rounds arrive sooner and hit harder to lead; a slow, pirouetting plane's rounds are
sluggish — another counter to loitering. It does make the intercept maths in `leader.py` slightly harder, which is
arguably the point of that sample.
