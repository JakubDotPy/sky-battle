"""Slow on tick 1 only, and stamps the tick it computed for into `throttle`.

That makes a stale reply detectable: an action carrying tick 1's stamp arriving in answer to
tick 2 is precisely the desync the tick echo exists to prevent.
"""

import time

from skybattle.state import Action


class Bot:
    def act(self, state):
        if state.tick == 1:
            time.sleep(0.4)
        return {p.id: Action(throttle=state.tick / 1000.0) for p in state.planes}
