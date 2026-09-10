from skybattle.state import Action


def act(state):
    return {p.id: Action(throttle=1.0) for p in state.planes}
