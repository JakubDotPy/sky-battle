from skybattle.state import Action


class Bot:
    def act(self, state):
        return {p.id: Action(throttle=1.0, steer=0.5) for p in state.planes}
