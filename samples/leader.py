"""Rung 3: aim where the target WILL be. The "aha" bot, and the reference opponent.

Bullet flight time depends on range, which depends on where the target will be, which depends
on flight time. Two fixed-point iterations converge well inside a plane's radius.

`lead_point` is deliberately absent from `skybattle.geom`: this is the punchline, so it is
written out here rather than handed over as a helper.
"""

from skybattle import geom
from skybattle.state import Action

ON_TARGET_DEG = 6.0
"""Deliberately identical to chaser.py's gate.

These two samples exist to isolate ONE variable - aiming at the target versus aiming at the
intercept point. A tighter gate here would confound that comparison, since leading requires
turning further before the nose is on the aim point, so a stricter gate costs the leading bot
shots for a reason unrelated to leading.
"""


class Bot:
    def act(self, state):
        w, h = state.arena
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

            # Step 1 - iterate to a firing solution. Bullet speed is the gun's own muzzle speed
            # plus this plane's speed added along its heading -- the gun points dead ahead, so
            # for a forward mount that is the same magnitude a scalar add would give.
            bullet_speed = gun.muzzle_speed + p.speed
            flight_ticks = target.range / bullet_speed
            aim_x, aim_y = target.x, target.y
            for _ in range(2):
                aim_x = target.x + geom.cos_deg(target.heading_deg) * target.speed * flight_ticks
                aim_y = target.y + geom.sin_deg(target.heading_deg) * target.speed * flight_ticks
                flight_ticks = geom.distance(p.x, p.y, aim_x, aim_y, w, h) / bullet_speed

            # Step 2 - steer at the intercept point, not at the target.
            lead_bearing = geom.bearing_to(p.x, p.y, p.heading_deg, aim_x, aim_y, w, h)
            ready = gun.cooldown_ticks_left == 0 and gun.ammo > 0
            out[p.id] = Action(
                # Corner speed turns best, so ease off when a hard turn is needed.
                throttle=0.4 if abs(lead_bearing) > 30.0 else 0.9,
                steer=max(min(lead_bearing / 25.0, 1.0), -1.0),
                fire=(frozenset({0}) if ready and abs(lead_bearing) <= ON_TARGET_DEG
                      else frozenset()),
            )
        return out
