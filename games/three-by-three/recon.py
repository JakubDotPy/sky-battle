"""Two scouts and a fighter: find first, shoot second.

The scouts never fire -- their 120-degree, 900-unit cones are the contribution, and two of them
sweeping in opposite directions keep most of the arena lit. The fighter shoots only what the
squadron already sees, and prefers a wounded target.
"""

SQUADRON = ["scout", "scout", "fighter"]

from skybattle.state import Action

ON_TARGET_DEG = 5.0


class Bot:
    def act(self, state):
        out = {}
        sweep = 0.07
        for p in state.planes:
            if p.kind == "scout":
                out[p.id] = Action(throttle=0.8, steer=sweep)
                sweep = -sweep                      # the two scouts arc apart, not together
            elif p.contacts:
                target = min(p.contacts, key=lambda c: (c.hp, c.range))
                gun = p.guns[0]
                ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
                out[p.id] = Action(
                    throttle=0.9,
                    steer=max(min(target.bearing_deg / 25.0, 1.0), -1.0),
                    fire=(frozenset({0}) if ready and abs(target.bearing_deg) <= ON_TARGET_DEG
                          else frozenset()),
                )
            else:
                out[p.id] = Action(throttle=0.7, steer=0.05)    # loiter until the scouts call
        return out
