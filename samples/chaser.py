"""Rung 2: turn toward the nearest contact, throttle up, fire when aligned.

Teaches the steer sign and torus-correct bearing -- and teaches why it always MISSES, because
it aims where the target is rather than where it will be. That is rung 3's problem.
"""

# Anything works, but a scout's wider cone finds targets sooner for a bot this simple.
SQUADRON = ["scout", "fighter"]

from skybattle.state import Action

ON_TARGET_DEG = 6.0


class Bot:
    def act(self, state):
        out = {}
        for p in state.planes:
            if not p.contacts:
                # A search must COVER GROUND. A hard turn just re-scans the same patch of sky
                # forever, and squadrons can spawn over 1300 units apart against a 600-unit
                # cone - so a circling bot may never make contact at all.
                out[p.id] = Action(throttle=0.85, steer=0.06)
                continue
            target = min(p.contacts, key=lambda c: c.range)
            gun = p.guns[0]
            ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
            out[p.id] = Action(
                throttle=0.9,
                # bearing is already relative to my nose: positive is left, so steer positive
                steer=max(min(target.bearing_deg / 30.0, 1.0), -1.0),
                fire=(frozenset({0}) if ready and abs(target.bearing_deg) <= ON_TARGET_DEG
                      else frozenset()),
            )
        return out
