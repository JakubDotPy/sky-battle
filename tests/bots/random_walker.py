"""Steers by the engine-supplied per-squadron RNG.

Determinism tests need a bot whose behaviour depends on the seed; a constant bot makes any
two runs match and the test vacuous.
"""

from skybattle.state import Action


class Bot:
    def act(self, state):
        return {
            p.id: Action(throttle=state.rng.random(), steer=state.rng.random() * 2.0 - 1.0)
            for p in state.planes
        }
