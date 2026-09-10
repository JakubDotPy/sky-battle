from skybattle.state import Action

print("hello from module import time")


class Bot:
    def act(self, state):
        print("thinking about tick", state.tick)
        return {p.id: Action(throttle=0.5) for p in state.planes}
