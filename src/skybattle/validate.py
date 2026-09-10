"""Action validation. Degrade per plane, never per squadron.

One malformed entry must not cost the other plane its tick: partial failure is debuggable
("plane 2 coasted 40 times this match"), whole-squadron failure is not. A bot keeping a dict
keyed by plane id will NATURALLY emit a stale id on the tick after a loss, so that path has to
be boring rather than fatal.

Exported so a bot author can call the engine's own checker in their tests. Reusing this exact
function means an author can never pass their own tests and then fail the engine's check.
"""

import math

from .state import Action


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def validate(raw: object,
             live_ids: tuple[int, ...]) -> tuple[dict[int, Action], tuple[tuple[int, str], ...]]:
    """Returns (accepted actions by plane id, rejections as (plane_id, reason))."""
    rejects: list[tuple[int, str]] = []
    if not isinstance(raw, dict):
        return {}, ((-1, "not_a_dict"),)
    if len(raw) > len(live_ids) + 8:
        # A plausible author bug (e.g. a stale dict grown to 200,000 keys) must be cheap to
        # reject -- bounded before the sort below, not after it.
        return {}, ((-1, "too_many_actions"),)

    live = set(live_ids)
    out: dict[int, Action] = {}
    for key in sorted(raw, key=repr):        # deterministic order for the reject log
        value = raw[key]
        if not isinstance(key, int) or isinstance(key, bool):
            rejects.append((-1, f"bad_key:{key!r}"))
            continue
        if key not in live:
            rejects.append((key, "unknown_plane"))
            continue
        if not isinstance(value, Action):
            rejects.append((key, "not_an_action"))
            continue
        if not isinstance(value.fire, (set, frozenset)) or \
                any(not isinstance(g, int) or isinstance(g, bool) for g in value.fire):
            rejects.append((key, "bad_fire"))
            continue
        if not _finite(value.throttle, value.steer):
            # Never clamp: NaN clamps to NaN and poisons the physics for both players.
            rejects.append((key, "nan_or_inf"))
            continue

        throttle = min(max(value.throttle, 0.0), 1.0)
        steer = min(max(value.steer, -1.0), 1.0)
        if (throttle, steer) != (value.throttle, value.steer):
            rejects.append((key, "clamped"))
        out[key] = Action(throttle=throttle, steer=steer, fire=frozenset(value.fire))

    return out, tuple(rejects)
