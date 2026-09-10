# The game

Sky Battle is a bot-programming game. You do not fly a plane — you write a Python program that
flies one, or several. Two or more people's programs meet in an arena, and the engine runs the
fight unattended: the score at the end says whose bot flew best.

Two things are strictly separate. **The engine** owns the whole simulation: positions,
headings, speeds, bullets, collisions, damage, the tick loop, scoring, and the recording that
lets a human watch the fight afterwards. **The bot** is one `.py` file per player, with no game
loop of its own and no access to engine internals. Once per tick the engine hands it a snapshot
of what its planes can currently see, and it hands back one action per plane. That is the entire
interface — see [Writing a bot](writing-a-bot.md) for the contract in full.

## The tick loop

A match advances one tick at a time, always in the same order:

1. The engine builds each squadron a fogged view of the world — its own planes in full, plus
   whatever enemies are inside somebody's vision right now.
1. Every bot's `act(state)` runs and returns one action per plane: a throttle setting, a
   steering input, and which guns (if any) to fire.
1. The engine validates those actions, applies them, integrates every plane's position and
   heading, resolves gunfire and collisions, and kills anything that ran out of hit points.
1. Only *after* all of that does it build the next tick's views.

That last point matters more than it looks: a plane that died this tick contributes no vision
and shows up as no one's contact. Resolve first, then snapshot — one rule, and there is no
special case for "I could see it a moment ago."

## The arena

The arena is a **wrap-around torus** with no walls. Fly off the east edge and you reappear on
the west; there is no corner to camp in and no wall to be cornered against. It is the one
deliberate concession to un-realism in an otherwise physically-grounded game, kept because
walls make no sense for aircraft and because a bounded map gives a fleeing plane nowhere to run
out of, which would make the game boring in a different way (see [inactivity](#round-end-and-scoring)
below). The default arena is 2000 by 2000 units; a host can change it, but every class's cone and
bubble ranges are checked against whatever arena is chosen, because a cone longer than half the
shorter side would let a plane see the same enemy around both sides of the world at once.

## Vision

Sky Battle's central mechanic is fog of war. A plane sees an enemy one of two ways:

- **A vision cone** in front of the nose — some classes with a rear gun also have a second,
  narrower cone covering their tail.
- **A vision bubble** — a short-range, heading-independent radius. Whatever is this close is
  seen regardless of where the nose is pointed, modelling a pilot looking around rather than
  only down the barrel.

Whatever falls inside either one is visible. Vision is shared **instantly and perfectly** across
a whole squadron: the moment any one of your planes spots an enemy, every squadmate knows about
it too, as if the pilots were on the radio together. Each of your planes reads that contact from
its own nose, though, so the same enemy shows up with a different bearing and range to each
reader.

Losing sight of a contact and then re-spotting it gets a **brand-new id**. The engine keeps no
memory of a contact once it drops out of sight — no last-known position, no age — so a plane
that a bot wants to keep tracking has to actually be kept in view, and remembering where
something used to be is the bot author's job, not the engine's.

**Enemy bullets are never visible.** The only way to know you are under fire is to get hit, or
to reason about an enemy's bearing and infer that it has a shot. This is a deliberate design
choice, not an oversight: it is dramatically cheaper for the engine to compute, and it is the
better game — the interesting problem becomes reading an opponent's position rather than
reading tracer fire.

## Guns

Guns are **fixed mounts, not turrets**. A bot aims a gun by flying the aeroplane so the mount's
bearing lines up with the target — a forward gun at bearing 0 degrees, or a rear gun (on classes
that carry one) at bearing 180 degrees. There is no separate aiming action.

Every shot scatters by a random amount inside the mount's own dispersion arc, so a tighter gun
groups its rounds more reliably. Ammunition is finite and never replenishes, and a cooldown
gates how often a mount can fire again. A round's own speed is added to the shooter's velocity
as a **vector**, not simply along the firing line — which means a forward gun's rounds go
further the faster the shooter is moving, while a rear gun's rounds go *less* far the faster the
shooter runs away, because its own motion works against a bullet fired backwards. Every round
also expires after a fixed number of ticks, so range is a combination of muzzle speed, the
shooter's own speed, and how long the round survives — see [Plane classes](classes.md) for the
numbers per gun.

## Damage

Hit points are not a flat pool that flies the same right up to zero. A damaged plane's top speed
and turn rate both fall as it takes hits, bottoming out at a fraction of full capability at zero
HP. A wounded target is therefore genuinely easier prey, not just closer to dying — which is
also why an enemy's hit points are one of the few facts about it a bot is allowed to see (see
[Writing a bot](writing-a-bot.md#what-a-bot-receives)).

## Round end and scoring

A **round** ends when only one squadron still has a living plane, or after a fixed tick limit,
whichever comes first. If the timeout is hit with more than one squadron still flying, the
higher score wins; an exact tie is a draw.

Scoring, per round, per squadron:

- 1 point per point of damage dealt to any enemy plane.
- Plus 20% of the damage dealt to an enemy plane your squadron destroyed.
- Plus 50 points for every enemy plane destroyed while your squadron still had a plane alive.
- Plus 10 points per enemy plane dead, but *only* if your squadron is the last one flying at the
  end of the round.

Survival time by itself is never scored. Simply outlasting an opponent is worth nothing unless
you were also the one landing hits — which is also why an explicit anti-passivity clock exists:
if no plane anywhere has taken damage for 600 ticks, every living plane starts losing 1 hit
point per tick until someone dies. Any damage at all resets that counter, and a kill produced by
the drain pays no last-survivor bonus. On a torus, nothing else forces a resolution — a faster
plane could otherwise simply out-cruise a slower pursuer forever.

A **match** is a fixed number of rounds (11 by default — odd, so an overall draw is rare), each
with a fresh spawn and its own seed, with every round's score summed into a match total.
Planes pass through each other; only bullets collide with planes, since a top-down 2D arena is a
projection of pilots flying at different altitudes.

## Who this is for

Sky Battle is built to survive other people's *broken* bots — crashes, infinite loops, garbage
replies, all handled without ending the match (the full failure model is in
[Writing a bot](writing-a-bot.md#when-a-bot-misbehaves)). It is not built to survive a
*malicious* one: there is no sandboxing, no resource-isolation beyond a process boundary and a
per-tick deadline. Run it among people you trust — see
[Running a game](running-a-game.md#the-honest-limits) for what that means in practice.

Next: read what a squadron actually looks like in [Plane classes](classes.md), or skip straight
to [Writing a bot](writing-a-bot.md) if you already know the shape of the game.
