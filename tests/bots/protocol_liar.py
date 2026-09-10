import json

from skybattle.state import Action


class Bot:
    def act(self, state):
        print(json.dumps({"tick": state.tick, "actions": {"0": [1.0, 1.0, []]}}))
        return {p.id: Action(throttle=0.25) for p in state.planes}
