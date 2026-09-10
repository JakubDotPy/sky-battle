"""The simulation.

TICK ORDER, and it is load-bearing: apply actions, integrate, resolve damage and deaths, THEN
build each squadron's view. A plane that died this tick therefore contributes no vision and
appears as no contact -- one rule instead of a family of edge cases.
"""

import random
from dataclasses import dataclass

from . import bullets as bul
from . import collide, flight, geom, vision
from .classes import PlaneClass
from .state import (
    Action,
    ActionRejected,
    BulletHit,
    Contact,
    ContactLost,
    Gun,
    HitByBullet,
    OwnPlane,
    PlaneDestroyed,
    View,
)
from .validate import validate


@dataclass
class Plane:
    """Engine-internal, mutable. Never handed to a bot."""

    id: int
    squadron: int
    kind: str
    cls: PlaneClass
    x: float
    y: float
    heading_deg: float
    speed: float
    hp: int
    ammo: list[int]
    cooldown: list[int]
    alive: bool = True


class World:
    ROUND_TICK_LIMIT = 3000
    INACTIVITY_TICKS = 600
    """Quiet ticks before the drain starts. Robocode's mechanic, retuned.

    The torus abolishes corner-camping but it also removes the map's own answer to fleeing:
    with no walls a faster plane can outrun a pursuer forever. So an explicit clock is
    load-bearing, not optional.
    """

    def __init__(self, arena: tuple[float, float], squadrons: list[list[str]],
                 classes: dict[str, PlaneClass], seed: int,
                 round_tick_limit: int = ROUND_TICK_LIMIT,
                 inactivity_ticks: int = INACTIVITY_TICKS) -> None:
        self.arena = arena
        self.classes = classes
        self.seed = seed
        self.round_tick_limit = round_tick_limit
        self.inactivity_ticks = inactivity_ticks
        self.rng = random.Random(seed)
        """The engine's own stream: spawn jitter (drawn once, below) and, every tick, each
        round's dispersion (drawn in `_fire`). Never handed to a bot -- a bot drawing from this
        would let it predict or manipulate its own scatter. Any new draw added anywhere in a
        tick reshuffles every dispersion value downstream of it, so keep draws in a fixed,
        documented order."""
        self.tick_no = 0
        self.bullets: list[bul.Bullet] = []
        self.planes: dict[int, Plane] = {}
        self.tracker = vision.ContactTracker()
        self.damage_dealt: dict[int, float] = {sq: 0.0 for sq in range(len(squadrons))}
        self.kills: dict[int, list[int]] = {sq: [] for sq in range(len(squadrons))}
        self._damage_ledger: dict[tuple[int, int], float] = {}
        self.ticks_since_damage = 0
        self.won_by_drain = False
        """True once a drain death has occurred and no combat has happened since.

        Combat clears it (same as `ticks_since_damage`), so at round end it distinguishes "the
        drain ended this round" from "a drain death merely happened at some point".
        """
        self.kills_while_alive: dict[int, int] = {sq: 0 for sq in range(len(squadrons))}
        self._events: dict[int, list[object]] = {sq: [] for sq in range(len(squadrons))}
        self._squadron_rng = {sq: random.Random(self.squadron_seed(sq))
                              for sq in range(len(squadrons))}
        """Each squadron's bot RNG, created ONCE and handed out by reference every tick.

        The stream then advances only as far as a bot actually draws from it, so two bots that
        draw a different number of values on a tick stay independent of each other -- that's the
        property that matters, and it's why these are per-squadron streams rather than one
        shared `Random`.
        """
        self.last_actions: dict[int, Action] = {}
        """The validated, post-substitution actions applied on the most recent tick.

        This is what the thin replay records: seed + this stream reproduces the match.
        """
        self._views_tick: int | None = None
        self._views_cache: dict[int, View] = {}
        self._spawn(squadrons)

    # ---------------------------------------------------------------- setup

    def _spawn(self, squadrons: list[list[str]]) -> None:
        w, h = self.arena
        next_id = 0
        n = len(squadrons)
        # One rotation and one radius for the whole formation, so a seed varies the match
        # without favouring a side: every squadron stays at the same radius, separated by the
        # same angle, with only the formation's orientation changing.
        rot = self.rng.uniform(0.0, 360.0)
        ring = self.rng.uniform(0.25, 0.35)
        for sq, kinds in enumerate(squadrons):
            # Squadrons start opposite each other, facing in. Planes always have velocity:
            # there is no "stopped" state, which is why coasting is the right timeout default.
            base = 360.0 / n * sq + rot
            for slot, kind in enumerate(kinds):
                cls = self.classes[kind]
                cx = w / 2.0 + geom.cos_deg(base) * w * ring
                cy = h / 2.0 + geom.sin_deg(base) * h * ring
                # Offset squadmates along the formation's own tangent, so a squadron's internal
                # geometry is identical to every other squadron's up to the shared rotation.
                tangent = base + 90.0
                ox = geom.cos_deg(tangent) * slot * 40.0
                oy = geom.sin_deg(tangent) * slot * 40.0
                self.planes[next_id] = Plane(
                    id=next_id, squadron=sq, kind=kind, cls=cls,
                    x=(cx + ox) % w, y=(cy + oy) % h,
                    heading_deg=geom.normalize_deg(base + 180.0),
                    speed=cls.corner_speed,
                    hp=cls.hp,
                    ammo=[g.ammo for g in cls.guns],
                    cooldown=[0 for _ in cls.guns],
                )
                next_id += 1

    def squadron_seed(self, squadron: int) -> str:
        """The seed for one squadron's bot RNG, derived from the match seed.

        String seeding is documented and stable, and unlike XOR it is injective over
        (seed, squadron) - `seed ^ (sq + 1)` collides, e.g. (1, 1) and (2, 0) both give 3.
        """
        return f"{self.seed}:{squadron}"

    # ---------------------------------------------------------------- tick

    def tick(self, replies: dict[int, object]) -> None:
        """Advance one tick. `replies` maps squadron index to that bot's raw reply."""
        self.tick_no += 1
        for sq in self._events:
            self._events[sq] = []

        actions = self._collect(replies)
        self._integrate(actions)
        self._fire(actions)
        self._advance_bullets()
        self._resolve_hits()
        self._drain()

    def _collect(self, replies: dict[int, object]) -> dict[int, Action]:
        """Validate every squadron's reply, degrading per plane."""
        actions: dict[int, Action] = {}
        for sq, raw in replies.items():
            live = tuple(sorted(p.id for p in self.planes.values()
                                if p.alive and p.squadron == sq))
            accepted, rejects = validate(raw, live)
            actions.update(accepted)
            for pid, reason in rejects:
                self._events[sq].append(ActionRejected(plane_id=pid, reason=reason))
        self.last_actions = actions
        return actions

    def _integrate(self, actions: dict[int, Action]) -> None:
        for pid in sorted(self.planes):          # fixed order: never a dict-order dependency
            p = self.planes[pid]
            if not p.alive:
                continue
            a = actions.get(pid, Action())
            p.x, p.y, p.heading_deg, p.speed = flight.step(
                p.cls, p.x, p.y, p.heading_deg, p.speed, p.hp, p.cls.hp,
                a.throttle, a.steer, self.arena)
            for i in range(len(p.cooldown)):
                p.cooldown[i] = max(0, p.cooldown[i] - 1)

    def _fire(self, actions: dict[int, Action]) -> None:
        for pid in sorted(self.planes):
            p = self.planes[pid]
            if not p.alive:
                continue
            a = actions.get(pid)
            if a is None:
                continue
            for gi in sorted(a.fire):
                if gi < 0 or gi >= len(p.cls.guns):
                    self._events[p.squadron].append(
                        ActionRejected(plane_id=pid, reason=f"unknown_gun:{gi}"))
                    continue
                if p.cooldown[gi] > 0 or p.ammo[gi] <= 0:
                    continue
                gun = p.cls.guns[gi]
                self.bullets.append(bul.spawn(gun, gi, pid, p.squadron,
                                              p.x, p.y, p.heading_deg, p.speed, self.rng))
                p.ammo[gi] -= 1
                p.cooldown[gi] = gun.cooldown_ticks

    def _advance_bullets(self) -> None:
        # Keep the pre-move position so the swept test has the full segment.
        self._segments = []
        alive = []
        for b in self.bullets:
            nxt = bul.advance(b, self.arena)
            if nxt is None:
                continue
            self._segments.append((b, b.vx, b.vy))
            alive.append(nxt)
        self.bullets = alive

    def _resolve_hits(self) -> None:
        """Apply hits in the order they actually occurred within the tick, not spawn order.

        Two rounds converging on a dying plane must credit whichever one struck FIRST
        (smallest `swept_hit` fraction `t`), not whichever bullet happens to be processed
        first. So: gather one candidate per bullet (its earliest hit, same selection as
        before), then apply candidates in ascending `t`. A target already killed by an
        earlier-applied candidate is not hit again, and its bullet survives unconsumed --
        exactly as if that bullet's target had never been there to hit.
        """
        w, h = self.arena
        candidates: list[tuple[float, int, Plane]] = []
        for idx, (b, dx, dy) in enumerate(self._segments):
            best: tuple[float, Plane] | None = None
            for pid in sorted(self.planes):
                p = self.planes[pid]
                if not p.alive or p.squadron == b.squadron:
                    continue
                t = collide.swept_hit(p.x, p.y, p.cls.radius,
                                      b.x, b.y, dx, dy, w, h)
                if t is not None and (best is None or t < best[0]):
                    best = (t, p)
            if best is not None:
                t, target = best
                candidates.append((t, idx, target))
        candidates.sort(key=lambda c: (c[0], c[1]))

        spent: set[int] = set()
        for _, idx, target in candidates:
            if not target.alive:
                continue
            b, _, _ = self._segments[idx]
            spent.add(idx)
            target.hp -= b.damage
            self.damage_dealt[b.squadron] += b.damage
            key = (b.squadron, target.id)
            self._damage_ledger[key] = self._damage_ledger.get(key, 0.0) + b.damage
            self.ticks_since_damage = 0
            self.won_by_drain = False
            self._events[b.squadron].append(
                BulletHit(plane_id=b.owner_id, gun=b.gun, target_id=target.id, damage=b.damage))
            self._events[target.squadron].append(
                HitByBullet(plane_id=target.id, from_squadron=b.squadron, damage=b.damage))
            if target.hp <= 0:
                self._kill(target, by=b.squadron)

        if spent:
            # A bullet that hit is consumed. Indices line up because _segments was built in
            # the same order as the surviving bullet list.
            self.bullets = [b for i, b in enumerate(self.bullets) if i not in spent]

    def _kill(self, p: Plane, by: int | None) -> None:
        if not p.alive:
            return
        p.alive = False
        p.hp = 0
        if by is not None:
            self.kills[by].append(p.id)
            if any(q.alive for q in self.planes.values() if q.squadron == by):
                self.kills_while_alive[by] += 1
        event = PlaneDestroyed(plane_id=p.id, by=by)
        for sq in self._events:
            self._events[sq].append(event)

    def _drain(self) -> None:
        """Bleed everyone until somebody dies, if nothing has happened for long enough.

        Punishes MUTUAL passivity without punishing a bot that is legitimately evading while
        under fire, because taking damage resets the counter.
        """
        self.ticks_since_damage += 1
        if self.ticks_since_damage < self.inactivity_ticks:
            return
        for pid in sorted(self.planes):
            p = self.planes[pid]
            if not p.alive:
                continue
            p.hp -= 1
            if p.hp <= 0:
                self.won_by_drain = True
                self._kill(p, by=None)

    def _living_squadrons(self) -> tuple[int, ...]:
        return tuple(sorted({p.squadron for p in self.planes.values() if p.alive}))

    def round_over(self) -> bool:
        return len(self._living_squadrons()) <= 1 or self.tick_no >= self.round_tick_limit

    def outcome(self) -> str:
        living = self._living_squadrons()
        if not living:
            return "draw"
        if len(living) == 1:
            return "drain" if self.won_by_drain else f"squadron_{living[0]}"
        if self.tick_no >= self.round_tick_limit:
            return "timeout"
        return "ongoing"

    def scores(self) -> dict[int, float]:
        """Robocode's formula, which is a quarter-century-tuned answer to 'make hiding lose'.

            1 x damage dealt
          + 20% of damage dealt to any enemy plane you destroyed
          + 50 x enemy planes destroyed while you still had a plane alive
          + 10 x enemy planes dead, only if you are the last squadron flying

        Survival time is deliberately never scored on its own: that IS the camping incentive.
        """
        living = self._living_squadrons()
        last_standing = living[0] if len(living) == 1 and not self.won_by_drain else None

        out: dict[int, float] = {}
        for sq in sorted(self.damage_dealt):
            score = self.damage_dealt[sq]
            score += 50.0 * self.kills_while_alive[sq]
            for victim in self.kills[sq]:
                score += 0.2 * self._damage_to(sq, victim)
            if sq == last_standing:
                enemy_dead = sum(1 for p in self.planes.values()
                                  if not p.alive and p.squadron != sq)
                score += 10.0 * enemy_dead
            out[sq] = score
        return out

    def _damage_to(self, squadron: int, victim_id: int) -> float:
        return self._damage_ledger.get((squadron, victim_id), 0.0)

    # ---------------------------------------------------------------- views

    def views(self) -> dict[int, View]:
        """Build each squadron's fogged view. Called AFTER resolution, never before.

        views() advances the contact tracker, so a second call in the same tick would
        under-report ContactLost; the cache also avoids repeating the cone checks, which
        are the dominant per-tick cost.
        """
        if self._views_tick == self.tick_no:
            return self._views_cache
        out: dict[int, View] = {}
        living = [p for _, p in sorted(self.planes.items()) if p.alive]
        for sq in sorted(self._events):
            mine = [p for p in living if p.squadron == sq]
            enemies = {p.id: p for p in living if p.squadron != sq}

            seen: dict[int, list[int]] = {}
            for observer in mine:
                for eid, enemy in sorted(enemies.items()):
                    if vision.sees(observer, enemy, self.arena):
                        seen.setdefault(eid, []).append(observer.id)
            seen_t = {eid: tuple(obs) for eid, obs in seen.items()}

            ids, lost = self.tracker.update(sq, tuple(sorted(seen_t)))
            events = list(self._events[sq]) + [ContactLost(contact_id=c) for c in lost]

            out[sq] = View(
                tick=self.tick_no,
                arena=self.arena,
                planes=tuple(
                    self._own(p, vision.build_contacts(p, seen_t, enemies, ids, self.arena))
                    for p in mine
                ),
                events=tuple(events),
                rng=self._squadron_rng[sq],
            )
        self._views_cache = out
        self._views_tick = self.tick_no
        return out

    @staticmethod
    def _own(p: Plane, contacts: tuple[Contact, ...]) -> OwnPlane:
        return OwnPlane(
            id=p.id, kind=p.kind, x=p.x, y=p.y, heading_deg=p.heading_deg, speed=p.speed,
            hp=p.hp, hp_max=p.cls.hp,
            stall_speed=p.cls.stall_speed, corner_speed=p.cls.corner_speed,
            max_speed=p.cls.max_speed,
            guns=tuple(Gun(name=g.name, bearing_deg=g.bearing_deg,
                           dispersion_deg=g.dispersion_deg,
                           ammo=p.ammo[i], cooldown_ticks_left=p.cooldown[i],
                           muzzle_speed=g.muzzle_speed)
                       for i, g in enumerate(p.cls.guns)),
            contacts=contacts,
            bubble_range=p.cls.bubble_range,
        )
