"""Three fighters, all hunting the nearest contact with a lead solution.

No roles: every plane does the same thing, and the squadron's advantage is that three fighters
converge on one target faster than a target can turn away from all three.
"""

SQUADRON = ["fighter", "fighter", "fighter"]

from skybattle import geom
from skybattle.state import Action

ON_TARGET_DEG = 6.0


class Bot:
    def act(self, state):
        w, h = state.arena
        out = {}
        for p in state.planes:
            if not p.contacts:
                out[p.id] = Action(throttle=0.85, steer=0.06)  # sweep, covering ground
                continue

            target = min(p.contacts, key=lambda c: c.range)
            gun = p.guns[0]

            # Two fixed-point steps converge on where the target will be when the round
            # arrives -- see samples/leader.py for why this is the whole game.
            bullet_speed = gun.muzzle_speed + p.speed
            flight = target.range / bullet_speed
            aim_x, aim_y = target.x, target.y
            for _ in range(2):
                aim_x = target.x + geom.cos_deg(target.heading_deg) * target.speed * flight
                aim_y = target.y + geom.sin_deg(target.heading_deg) * target.speed * flight
                flight = geom.distance(p.x, p.y, aim_x, aim_y, w, h) / bullet_speed

            bearing = geom.bearing_to(p.x, p.y, p.heading_deg, aim_x, aim_y, w, h)
            ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
            out[p.id] = Action(
                throttle=0.4 if abs(bearing) > 30.0 else 0.9,  # corner speed turns best
                steer=max(min(bearing / 25.0, 1.0), -1.0),
                fire=frozenset({0}) if ready and abs(bearing) <= ON_TARGET_DEG else frozenset(),
            )
        return out
