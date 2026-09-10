# Balance pass — open questions

**Status:** the balance pass has been deliberately deferred throughout development. Every number in
`src/skybattle/classes.toml` is a placeholder that has never been tuned as a set.

This file holds the questions worth starting from, each with the measurement that raised it, so the pass begins
from evidence rather than from feel. Measurements were taken during the build; re-measure before acting, since the
table has moved since some of them.

## 1. Leading a target does not clearly pay

`test_leader_beats_chaser_over_a_fixed_seed_set` is marked `xfail`. Its threshold — leading beats not-leading in at
least 3 of 5 seeds — states the sample ladder's central pedagogical claim, and was deliberately **not** lowered.

Measured over three rounds, `leader.py` against `chaser.py`:

| | Shots | Hits | Accuracy | Median engagement range |
|---|---|---|---|---|
| `leader.py` (aims at the intercept point) | 98 | 77 | **78.6%** | 482 u |
| `chaser.py` (aims at the target) | 156 | 81 | **51.9%** | 451 u |

Leading buys 27 points of accuracy and costs **37% of the shots taken**, because a moving intercept point is harder
to keep the nose on than the target itself. Net hits tie, so the round turns on other things.

Two later findings complicate it further. The claim was **never** demonstrated: the 5/5 the test once reported was
one deterministic trial replayed five times, before spawns derived from the seed. And the vision bubble gave both
bots free close-range awareness — which is exactly where leading matters least.

**The likely lever is not the guns.** If engagements happened at range, a 13-degree lead would be required and the
bubble would be irrelevant. That points at cone ranges, gun reach, or closing speeds.

Counter-evidence worth keeping: in a three-player game, `leader`-based `ada` beat `chaser`-based `cleo` by roughly
3:1. Leading may pay in a crowd and not in a duel.

## 2. A scout that never engages costs half a squadron's guns

`wingman.py` lost to `circler.py` **90 to 527**. Its scout searches and never fires, by design, so the squadron
fights with one gun and must be repaid in information. Shared vision does not currently pay that much.

Either the information has to be worth more, or the scout has to contribute something besides sight.

## 3. The scout's cone covers nearly half the map

A 900-unit cone on a 2000-unit torus. The engine refuses a cone longer than half the shorter arena dimension, so
this is legal but close to the ceiling. Worth asking whether "sees almost everything" is the intended identity, or
whether the cone should shrink now that the bubble handles close-range awareness.

## 4. Free composition, accepted knowingly

Symmetric squadrons were originally mandated, on the evidence that free choice plus asymmetric classes collapses
into a monoculture — Battlecode's documented experience every year. That constraint was **lifted deliberately**: the
host sets planes-per-player, each player picks their own kinds, and the players in question are trusted not to
min-max.

The risk is therefore accepted rather than unconsidered. Evidence so far is genuinely mixed — twin scouts won one
measured game, bomber + fighter won another, scout + fighter won a third. There may be no dominant mix, which would
be the happiest outcome.

## 5. Sustained DPS currently holds its principle

The design intends "heavier rounds fire slower", so the classes land within about a third of each other:

| Class | Gun | Damage / cooldown | DPS |
|---|---|---|---|
| Scout | forward | 8 / 6 | 1.33 |
| Fighter | forward | 10 / 8 | 1.25 |
| Bomber | forward | 14 / 14 | 1.00 |
| Bomber | rear | 10 / 10 | 1.00 |

Spread is **1.33x**, so the principle holds. It did not always: an earlier pass cut the scout's cooldown to 2 ticks
to escape a ramming meta, reaching 4.00 DPS and a 4x spread. Removing plane-to-plane collision removed the reason,
and the values were reverted. **If a future pass touches cooldowns, check this ratio afterwards.**

## Vision, for reference

| Class | Bubble | Cone | Hull radius |
|---|---|---|---|
| Scout | 120 u | 120 deg / 900 u | 9 |
| Fighter | 150 u | 70 deg / 600 u | 12 |
| Bomber | **220 u** | **50 deg / 450 u** (+ rear 50 / 350) | 18 |

The bomber inversion — narrowest cone, largest bubble — is deliberate: many crew, few of them looking far ahead.

The bubble was added because half of all encounters inside 50 units were mutually blind, which a pilot would not
be. It closed that: **53% blind at 50 units became 0%**. The cost is that close-range awareness is now free, which
is what question 1 runs into.
