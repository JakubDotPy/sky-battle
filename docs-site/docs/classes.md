---
render_macros: true
---

# Plane classes

Every number on this page is read live from `src/skybattle/classes.toml` — the engine's own
balance table — at build time, by the same `load_classes()` function the engine uses. When the
table changes, this page changes on the next build; nothing here is typed in by hand. The full
tables, gun-by-gun, live on the [reference](reference.md) page — this page is about the *shape*
of each class, not the exhaustive numbers.

A squadron is built from three classes, each with a distinct character rather than just a
different stat line.

## Scout

The scout sees furthest and widest, and dies fastest. Its whole identity is its vision cone —
the widest and longest of the three classes by a large margin — bought by carrying the least
hit points and the lightest airframe. A scout that gets seen first usually loses; its job is to
spot for the squadron, not to trade shots.

## Fighter

The fighter is the balanced knife-fighter: middling everything, and the best turn rate of the
three at every speed on the curve. It is the class built to win a turning fight, not to avoid
one.

## Bomber

The bomber is the flying fortress. It carries the most hit points by a wide margin, the heaviest
single gun, and — because it is worth calling out explicitly, since it looks like a bug the
first time you notice it — the **narrowest vision cone of the three classes, and simultaneously
the largest vision bubble**. A bomber crew is large enough to keep a proper lookout in every
direction close in (the bubble), but the plane itself is slow and its window arcs are cramped,
so it is genuinely bad at *searching* far ahead (the cone). It also carries a rear-facing gun —
the only class that does — which is short-ranged and imprecise but means a bomber is hard to
simply sneak up on and shoot at leisure.

## Comparing the three at a glance

{{ radar_chart() }}

Seven axes, each scaled independently to its own largest value among the three classes — the
point is each class's silhouette, not a shared unit. Note how the bomber's polygon bulges out on
*hit points* and *bubble range* while pinching in on *cone width* and *cone range*: that shape
is the class's whole design in one picture.

## Turn rate peaks at corner speed, not at the minimum

This is the other fact worth calling out before you assume it is a bug: turn rate does **not**
simply get better the slower a plane flies. Every class has an intermediate "corner speed" at
which it turns tightest — slower *or* faster than that, and turn rate falls off in both
directions.

{{ turn_curve_chart() }}

If turn rate instead fell off monotonically toward the minimum, the dominant strategy would be
to fly at stall speed and pirouette forever, and every fight would degenerate into loitering.
Corner speed replaces that floor-to-sit-on with an optimum to actually fly toward — sitting at
corner speed is a real choice with a real cost (see [turning bleeds
speed](writing-a-bot.md#energy-and-turning) in the bot-writing guide), not a free lunch.

## Cone versus bubble, side by side

{{ bubble_cone_chart() }}

The scout leads on cone width and cone range by a wide margin; the bomber trails on both but
leads decisively on bubble range. That is the trade the bomber's whole kit is built around.

## Where the exact numbers live

This page is about shape. For the full airframe table, the per-gun table (bearing, dispersion,
cooldown, damage, ammo, lifetime, muzzle speed), and the exact cone and bubble figures for every
class, see [Reference](reference.md) — or run `sky-battle duel --rules`, which prints the raw
balance table straight from the file the engine actually reads.
