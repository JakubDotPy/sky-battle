"""One bot, one long-lived subprocess, one match.

Spawning per tick costs 22-31 ms against a 44 microsecond round trip -- 500x -- and throws away
the bot's memory between ticks, which destroys any bot that tracks a target. So: long-lived.

The process boundary is what makes a deadline enforceable at all. A `while True: pass` in the
same interpreter cannot be interrupted: signals only run between bytecodes on the main thread
and a thread cannot be killed. Robustness, not security, is what forces the subprocess.
"""

import json
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Self

from . import protocol
from .state import View

MAX_REPLY_CHARS = 64 * 1024
"""A reply line longer than this is refused unread. A squadron of eight with contacts is well
under 10 KB, so this is generous -- it exists to catch a plausible author bug (e.g. a dict with
200,000 keys), not to squeeze a legitimate reply."""


class BotProcess:
    def __init__(self, bot_path: str | Path, tick_deadline: float = 0.05,
                 first_tick_deadline: float = 2.0, strike_limit: int = 3) -> None:
        self.bot_path = Path(bot_path)
        self.tick_deadline = tick_deadline
        self.first_tick_deadline = first_tick_deadline
        self.strike_limit = strike_limit

        self.strikes = 0
        self.consecutive = 0
        self.accepted = 0
        self.ticks = 0
        self.forfeited = False
        self.last_accepted: dict = {}
        self.stderr_tail: deque[str] = deque(maxlen=200)
        self._closed = False

        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "skybattle.runner", str(self.bot_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
            # Kill the whole group later: a bot that spawned helpers must leave no orphans.
            start_new_session=True,
        )
        self._sel = selectors.DefaultSelector()
        self._sel.register(self.proc.stdout, selectors.EVENT_READ)
        # Drain stderr on a thread so a chatty bot can never fill the pipe and block itself.
        self._err = threading.Thread(target=self._drain_stderr, daemon=True)
        self._err.start()

    def _drain_stderr(self) -> None:
        for line in self.proc.stderr:
            self.stderr_tail.append(line.rstrip("\n"))

    # ------------------------------------------------------------------ tick

    def exchange(self, view: View, rng_seed: int | str) -> tuple[object, str]:
        """Send one view, wait for the matching reply. Returns (raw reply, status)."""
        self.ticks += 1
        if self.forfeited or self.proc.poll() is not None:
            return self.last_accepted, "forfeit"

        deadline = self.first_tick_deadline if self.ticks == 1 else self.tick_deadline
        try:
            self.proc.stdin.write(json.dumps(protocol.encode_view(view, rng_seed)) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            return self._strike("dead_pipe")

        # Drain any stale replies until the one for THIS tick arrives, or the deadline expires.
        # One budget for the whole exchange -- a flood of wrong-tick lines must not each reset
        # the clock, or a bot could stretch a single tick to N x deadline.
        end = time.monotonic() + deadline
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0.0 or not self._sel.select(remaining):
                return self._strike("timeout")
            line = self.proc.stdout.readline(MAX_REPLY_CHARS)
            if not line:
                return self._strike("dead_pipe")
            if len(line) >= MAX_REPLY_CHARS and not line.endswith("\n"):
                # Bounded read, not unbounded readline(): a reply this large is refused before
                # json.loads ever sees it, so an oversized dict costs nothing to reject.
                return self._strike("reply_too_large")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                return self._strike("error")
            if payload.get("tick") != view.tick:
                continue                      # a late answer to an earlier tick: discard it
            if "error" in payload:
                return self._strike("error")
            try:
                actions = protocol.decode_actions(payload["actions"])
            except Exception:  # noqa: BLE001 -- a bot's reply payload can be malformed any way
                return self._strike("error")
            self.accepted += 1
            self.consecutive = 0
            self.last_accepted = actions
            return actions, "ok"

    def _strike(self, status: str) -> tuple[object, str]:
        """Count a failure and fall back to the last accepted action.

        Hold-last is Battlesnake's rule and it cannot be gamed: a bot gains nothing by timing
        out, because it simply keeps doing whatever it last chose. Never make the fallback
        something advantageous.
        """
        self.strikes += 1
        self.consecutive += 1
        if self.consecutive >= self.strike_limit or (
            self.ticks >= 50 and self.strikes > self.ticks * 0.02
        ):
            # A chronically slow bot never lands an action at all -- every tick times out and
            # its late reply is then dropped as stale -- so it would hold tick 0's action for
            # the whole match while looking as though it played. Forfeit it instead.
            self.forfeited = True
            self.close()
            return self.last_accepted, "forfeit"
        return self.last_accepted, status

    # ----------------------------------------------------------------- close

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._sel.close()
        except Exception:  # noqa: BLE001, S110 -- best-effort teardown, never blocks a match
            pass
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except Exception:  # noqa: BLE001, S110 -- a pipe may already be broken at shutdown
                pass
        if self.proc.poll() is None:
            try:
                # killpg, not kill: reap any helpers the bot spawned.
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                self.proc.kill()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
