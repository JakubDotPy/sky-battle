"""The subprocess shim. It owns all I/O so the bot author owns none.

Duplicates the real stdout aside as a private protocol channel, then points fd 1 and
`sys.stdout` at stderr. An author's `print` -- even one emitting a protocol-shaped JSON line --
therefore lands harmlessly on stderr, where they can read it.

The author writes only `act(state) -> {plane_id: Action}`, as a `Bot` class or a bare function.
"""

import importlib.util
import json
import os
import sys
import traceback

from . import protocol


def _open_channel():
    """Take stdout for the protocol, then redirect all normal output to stderr."""
    channel = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return channel


def _load(path: str):
    """Import the author's file and return a callable act(state)."""
    spec = importlib.util.spec_from_file_location("author_bot", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import a bot from {path!r}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "Bot"):
        return module.Bot().act
    if hasattr(module, "act"):
        return module.act
    raise AttributeError(f"{path!r} defines neither a Bot class nor an act() function")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m skybattle.runner <bot.py>", file=sys.stderr)
        return 2

    channel = _open_channel()
    try:
        act = _load(argv[0])
    except Exception:  # noqa: BLE001 -- an author's file can raise anything at import time
        traceback.print_exc()
        return 1

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        tick = payload["tick"]
        try:
            view = protocol.decode_view(payload)
            # No falsy-view guard here: View is a NamedTuple and is always truthy. The actual
            # protection against a bot raising mid-computation is that encode_actions(act(view))
            # sits inside this try -- the except below catches it regardless of where it fails.
            reply = {"tick": tick, "actions": protocol.encode_actions(act(view))}
        except Exception:  # noqa: BLE001 -- isolating the author's bot from any exception is the point
            # The author's traceback goes to stderr so they debug normally; the engine gets a
            # clean error and never has to tell "crashed" from "sent nonsense" by parsing text.
            traceback.print_exc()
            reply = {"tick": tick, "error": "bot raised"}
        channel.write(json.dumps(reply) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
