from skybattle.state import Action


class Bot:
    def act(self, state):
        # A plausible author bug: a dict that grew to hundreds of thousands of stale entries.
        return {i: Action() for i in range(200_000)}
