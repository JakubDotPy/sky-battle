"""JSON codec for the engine/bot boundary.

Newline-delimited JSON over pipes, measured at 44 microseconds per round trip for a squadron
of two. msgpack is 1.8x faster, which is about 20 microseconds a tick and therefore irrelevant,
and it costs a dependency plus opacity: a student can read JSON.
"""

import random

from .state import (
    Action,
    ActionRejected,
    BulletHit,
    Contact,
    ContactLost,
    Gun,
    HitByBullet,
    OwnPlane,
    PlaneDestroyed,
    View,
)

# ponytail: the wire format is positional, so OwnPlane's field LAYOUT is load-bearing here.
# Deriving the scalar count keeps an appended scalar BEFORE the tuple fields working, and
# checking the tail means a new field fails at import instead of silently vanishing from every
# bot's view. `bubble_range` is a scalar appended AFTER the tuple fields (state.py appends
# fields at the end, always), so it cannot join the `p[:_SCALARS]` prefix -- it gets its own
# wire key instead, same as `guns` and `contacts` do.
_SCALARS = OwnPlane._fields.index("guns")
if OwnPlane._fields[_SCALARS:] != ("guns", "contacts", "bubble_range"):
    raise RuntimeError(
        f"OwnPlane layout changed to {OwnPlane._fields!r}; update encode_view/decode_view"
    )

# The wire already carries `[type_name, fields]`, so handing a bot the named type costs one
# lookup. It has to: the in-process path (`World.views()`) delivers real event types, so an
# untyped wire path would be a divergence that passes a harness test and misreads a live match.
_EVENT_TYPES = {
    cls.__name__: cls
    for cls in (HitByBullet, BulletHit, PlaneDestroyed, ContactLost, ActionRejected)
}


def _decode_event(name: str, body: list) -> object:
    """A name the engine no longer sends degrades to a plain tuple rather than raising.

    `API_VERSION` already refuses a genuine engine/bot mismatch, so this only covers the case
    of an event type that outlived its name -- and a tuple is what a bot used to get anyway.
    """
    cls = _EVENT_TYPES.get(name)
    return cls(*body) if cls is not None else tuple(body)


def encode_view(view: View, rng_seed: int | str) -> dict:
    """`View` -> a JSON-ready dict. `rng` becomes a seed; a Random cannot cross a pipe.

    KNOWN ASYMMETRY: an in-process bot (`World.views()`) is handed the SAME `Random` object
    every tick, so `state.rng` is a genuine stream -- draws on tick 2 continue where tick 1 left
    off. A subprocess bot instead rebuilds a fresh `Random(rng_seed)` every tick (see
    `decode_view`), because a `Random` object cannot cross a pipe and the protocol has no way to
    resume one across a tick boundary. `match.run_round` works around the worst of it by
    deriving a PER-TICK seed (`f"{squadron_seed}:{tick}"`), so at least every tick differs and a
    subprocess bot is not handed a constant -- but its stream still restarts each tick rather
    than continuing, so it is not bit-for-bit the same object as the in-process stream. Fixing
    that fully would need a protocol change (e.g. sending the seed plus the draw count already
    consumed) and was judged not worth it for this fix.
    """
    return {
        "tick": view.tick,
        "arena": list(view.arena),
        "rng_seed": rng_seed,
        "planes": [
            {
                "p": list(p[:_SCALARS]),
                "guns": [list(g) for g in p.guns],
                "contacts": [list(c) for c in p.contacts],
                "bubble_range": p.bubble_range,
            }
            for p in view.planes
        ],
        "events": [[type(e).__name__, list(e)] for e in view.events],
    }


def decode_view(payload: dict) -> View:
    """A JSON dict -> a typed `View`. The bot author never sees a raw dict."""
    planes = []
    for entry in payload["planes"]:
        head = entry["p"]
        planes.append(OwnPlane(
            *head,
            guns=tuple(Gun(g[0], *(float(v) for v in g[1:3]), int(g[3]), int(g[4]), float(g[5]))
                       for g in entry["guns"]),
            contacts=tuple(Contact(int(c[0]), c[1], *(float(v) for v in c[2:6]), int(c[6]),
                                   float(c[7]), float(c[8]), tuple(int(i) for i in c[9]))
                           for c in entry["contacts"]),
            bubble_range=float(entry["bubble_range"]),
        ))
    return View(
        tick=int(payload["tick"]),
        arena=(float(payload["arena"][0]), float(payload["arena"][1])),
        planes=tuple(planes),
        events=tuple(_decode_event(name, body) for name, body in payload["events"]),
        rng=random.Random(payload["rng_seed"]),
    )


def encode_actions(actions: dict[int, Action]) -> dict:
    return {str(pid): [a.throttle, a.steer, sorted(a.fire)] for pid, a in actions.items()}


def decode_actions(payload: dict) -> dict[int, Action]:
    """Raises on anything malformed. The driver catches and counts a strike."""
    return {
        int(pid): Action(throttle=float(body[0]), steer=float(body[1]),
                         fire=frozenset(int(g) for g in body[2]))
        for pid, body in payload.items()
    }
