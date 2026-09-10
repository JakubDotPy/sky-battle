"""Rung 1: minimum-radius circles, firing when something crosses the nose.

Teaches the state shape, the id-keyed return dict, and cooldown AND ammo gating. A plane cannot
sit still -- stall speed is above zero -- so "sit and shoot" becomes tightest-circle loitering,
which is itself the lesson.
"""

# Anything works: every plane flies the same tight circle regardless of kind.
SQUADRON = ["scout", "fighter"]

from skybattle.state import Action

ON_TARGET_DEG = 8.0


class Bot:
    def act(self, state):
        out = {}
        for p in state.planes:
            gun = p.guns[0]
            ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
            aimed = any(abs(c.bearing_deg) <= ON_TARGET_DEG for c in p.contacts)
            out[p.id] = Action(
                throttle=0.0,                          # lever idle: settles at stall speed
                steer=1.0,
                fire=frozenset({0}) if ready and aimed else frozenset(),
            )
        return out
