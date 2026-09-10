import time

from skybattle.state import Action

time.sleep(0.4)          # stands in for a heavy module-level import


class Bot:
    def act(self, state):
        return {p.id: Action(throttle=1.0) for p in state.planes}
