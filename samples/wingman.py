"""Rung 4: everything the squadron design adds.

The scout searches and never engages. The fighter engages only what the squadron can see, and
prefers a WOUNDED target -- which is why `contact.hp` is exposed. Both keep their own memory of
where a contact was last seen, because the engine keeps none: re-acquisition mints a new
contact id, so a plane that keeps eyes on a target is worth more than one that glances.
"""

from skybattle import geom
from skybattle.state import Action

ON_TARGET_DEG = 5.0
FORGET_AFTER = 90


class Bot:
    def __init__(self, config=None):
        self.last_seen: dict[int, tuple[float, float, int]] = {}

    def act(self, state):
        w, h = state.arena
        for p in state.planes:
            for c in p.contacts:
                self.last_seen[c.id] = (c.x, c.y, state.tick)
        self.last_seen = {cid: v for cid, v in self.last_seen.items()
                          if state.tick - v[2] <= FORGET_AFTER}

        out = {}
        for p in state.planes:
            if p.kind == "scout":
                out[p.id] = self._search(p)
            else:
                out[p.id] = self._engage(p, state, w, h)
        return out

    def _search(self, p):
        """Sweep wide, stay alive, never shoot. Its cone is its contribution.

        A wide arc traverses the arena; a tight circle would re-scan one patch forever and
        the squadron would never find anything to spot.
        """
        return Action(throttle=0.8, steer=0.08)

    def _engage(self, p, state, w, h):
        if p.contacts:
            # Wounded first: fewer hits to finish, and a damaged plane flies worse.
            target = min(p.contacts, key=lambda c: (c.hp, c.range))
            bearing = target.bearing_deg
            gun = p.guns[0]
            ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
            return Action(
                throttle=0.9,
                steer=max(min(bearing / 25.0, 1.0), -1.0),
                fire=(frozenset({0}) if ready and abs(bearing) <= ON_TARGET_DEG
                      else frozenset()),
            )
        if self.last_seen:
            # Nothing in sight: sweep the freshest remembered position.
            x, y, _ = max(self.last_seen.values(), key=lambda v: v[2])
            bearing = geom.bearing_to(p.x, p.y, p.heading_deg, x, y, w, h)
            return Action(throttle=0.8, steer=max(min(bearing / 25.0, 1.0), -1.0))
        return Action(throttle=0.6, steer=-0.25)
