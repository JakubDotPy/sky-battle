from skybattle.state import Action


class Bot:
    def act(self, state):
        # Legal shape, illegal magnitudes: the engine clamps both and logs a reject per plane.
        return {p.id: Action(throttle=5.0, steer=99.0) for p in state.planes}
