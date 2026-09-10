"""Rung 0: does nothing at all.

Proves the harness works, and doubles as the engine's coast-path regression test: every plane
holds its last action, which on tick one is a neutral one.
"""

# Anything works: this bot returns {} and never looks at what it is flying.
SQUADRON = ["scout", "fighter"]


class Bot:
    def act(self, state):
        return {}
