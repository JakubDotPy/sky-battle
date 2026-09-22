"""Two bombers and a scout: soak damage, and make the chase expensive.

A bomber cannot win a turning fight, so it does not try. It flies straight, fires the forward
gun at anything ahead and the rear gun at anything astern -- which is the one thing only this
class can do. The scout supplies the contacts the bombers' 50-degree cones will never find.
"""

SQUADRON = ["bomber", "bomber", "scout"]

from skybattle.state import Action

FORWARD_DEG = 8.0
REAR_DEG = 172.0
"""Wider gates than a fighter would use: both bomber mounts are the least precise on any
class, so a tight gate would mostly hold fire on shots that scatter anyway."""


def _ready(gun):
    return gun.cooldown_ticks_left == 0 and gun.ammo > 0


class Bot:
    def act(self, state):
        out = {}
        for p in state.planes:
            if p.kind == "scout":
                out[p.id] = Action(throttle=0.85, steer=0.08)  # eyes only, never engages
                continue

            fire = set()
            steer = 0.02  # a slow drift, not a turn
            if p.contacts:
                target = min(p.contacts, key=lambda c: c.range)
                bearing = target.bearing_deg
                if abs(bearing) <= 90.0:
                    # Only turn toward what is already in front; turning a bomber around just
                    # hands a pursuer the shot.
                    steer = max(min(bearing / 40.0, 1.0), -1.0)
                    if abs(bearing) <= FORWARD_DEG and _ready(p.guns[0]):
                        fire.add(0)
                elif abs(bearing) >= REAR_DEG and _ready(p.guns[1]):
                    fire.add(1)
            out[p.id] = Action(throttle=0.8, steer=steer, fire=frozenset(fire))
        return out
