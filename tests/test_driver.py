import time
from pathlib import Path

from skybattle.driver import BotProcess
from skybattle.state import Gun, OwnPlane, View

BOTS = Path(__file__).parent / "bots"


def _view(tick):
    g = Gun(name="forward", bearing_deg=0.0, dispersion_deg=8.0, ammo=80, cooldown_ticks_left=0)
    p = OwnPlane(id=0, kind="scout", x=0.0, y=0.0, heading_deg=0.0, speed=5.0, hp=70, hp_max=70,
                 stall_speed=3.0, corner_speed=5.0, max_speed=9.0, guns=(g,), contacts=())
    return View(tick=tick, arena=(2000.0, 2000.0), planes=(p,), events=())


def test_a_good_bot_is_accepted_every_tick():
    with BotProcess(BOTS / "good.py") as bot:
        for t in range(1, 6):
            _, status = bot.exchange(_view(t), rng_seed=1)
            assert status == "ok"
        assert bot.strikes == 0
        assert bot.accepted == 5


def test_a_hanging_bot_times_out_and_then_forfeits():
    with BotProcess(BOTS / "hanger.py", tick_deadline=0.05, first_tick_deadline=0.2) as bot:
        statuses = [bot.exchange(_view(t), rng_seed=1)[1] for t in range(1, 6)]
        assert "timeout" in statuses
        assert statuses[-1] == "forfeit"
        assert bot.forfeited


def test_a_timeout_re_applies_the_last_accepted_action():
    with BotProcess(BOTS / "hanger.py", tick_deadline=0.05, first_tick_deadline=0.2) as bot:
        raw, status = bot.exchange(_view(1), rng_seed=1)
        assert status == "timeout"
        # tick 0 has no previous action, so the fallback is a neutral Action
        assert raw == {}


def test_the_first_tick_gets_a_generous_budget_for_module_imports():
    with BotProcess(BOTS / "slow_first_tick.py",
                    tick_deadline=0.05, first_tick_deadline=3.0) as bot:
        _, status = bot.exchange(_view(1), rng_seed=1)
        assert status == "ok"
        assert bot.strikes == 0


def test_a_crashing_bot_is_an_error_not_a_timeout_and_the_traceback_is_captured():
    with BotProcess(BOTS / "crasher.py", strike_limit=99) as bot:
        _, status = bot.exchange(_view(1), rng_seed=1)
        assert status == "error"
        bot.exchange(_view(2), rng_seed=1)
    assert any("index out of range" in line for line in bot.stderr_tail)


def test_a_garbage_reply_is_an_error():
    with BotProcess(BOTS / "garbage.py", strike_limit=99) as bot:
        _, status = bot.exchange(_view(1), rng_seed=1)
        assert status == "error"


def test_a_stale_reply_never_becomes_the_next_ticks_answer():
    """The silent off-by-one this whole module exists to prevent.

    The bot stamps the tick it computed for into `throttle`, so a late tick-1 answer arriving in
    response to tick 2 is directly observable. Without the tick echo and the stale drain, the
    engine accepts it and every later tick is misaligned while the match still looks fine.
    """
    with BotProcess(BOTS / "tick_stamper_slow_first.py",
                    tick_deadline=0.05, first_tick_deadline=0.05, strike_limit=99) as bot:
        raw, status = bot.exchange(_view(1), rng_seed=1)
        assert status == "timeout"

        # Generous margin: 28 ticks at a 50 ms deadline is ~1.4 s of wall clock against the
        # fixture's 0.2 s sleep. The assertion below is what has teeth; the range only has to
        # outlast the sleep, and matching it exactly is how this test used to flake.
        for tick in range(2, 30):
            raw, status = bot.exchange(_view(tick), rng_seed=1)
            if status == "ok":
                stamp = round(raw[0].throttle * 1000.0)
                assert stamp == tick, (
                    f"accepted tick {stamp}'s action in answer to tick {tick} - stale reply "
                    f"was not drained"
                )
                return
        raise AssertionError("bot never produced an accepted reply")


def test_an_absurdly_large_reply_is_rejected_without_parsing():
    """A plausible author bug - 200k keys - must be refused cheaply, not JSON-parsed."""
    with BotProcess(BOTS / "huge_reply.py", strike_limit=99) as bot:
        start = time.monotonic()
        _, status = bot.exchange(_view(1), rng_seed=1)
        assert time.monotonic() - start < 1.0
        assert status == "reply_too_large"


def test_printing_bots_do_not_break_the_driver():
    with BotProcess(BOTS / "protocol_liar.py") as bot:
        for t in range(1, 4):
            _, status = bot.exchange(_view(t), rng_seed=1)
            assert status == "ok"


def test_close_is_idempotent_and_reaps_a_hung_child():
    bot = BotProcess(BOTS / "hanger.py", tick_deadline=0.05, first_tick_deadline=0.1)
    bot.exchange(_view(1), rng_seed=1)
    bot.close()
    bot.close()
    assert bot.proc.poll() is not None


def test_two_early_misses_do_not_forfeit():
    """Spurious misses are guaranteed, so a ladder must not be decided by them.

    A cold import costs over 100 ms and a GC pause adds tens of ms unpredictably. The
    2%-of-ticks rule must not fire before there are enough ticks for 2% to mean anything:
    the earlier `strikes > max(1, ticks // 50)` form forfeits on the SECOND strike of a match,
    because `ticks // 50` is 0 until tick 50.
    """
    with BotProcess(BOTS / "good.py", strike_limit=3) as bot:
        bot.exchange(_view(1), rng_seed=1)
        bot._strike("timeout")
        bot._strike("timeout")            # two unlucky ticks, not consecutive in play
        assert not bot.forfeited, "forfeited on the second strike of the match"
        for tick in range(2, 12):
            _, status = bot.exchange(_view(tick), rng_seed=1)
            assert status == "ok", f"forfeited at tick {tick} after two early misses"
        assert not bot.forfeited


def test_a_flood_of_stale_replies_cannot_stretch_one_tick():
    """One exchange gets one budget, however many wrong-tick lines arrive.

    A bot fixture cannot reach this path through a real subprocess: skybattle.runner's shim
    (_open_channel) redirects fd 1 to stderr and keeps the real protocol fd private to `main()`
    before it ever imports the bot module, so a bot loaded through `-m skybattle.runner <path>`
    cannot forge extra lines onto the pipe the driver reads - confirmed empirically (a fixture
    that tried had its flood land in stderr_tail, not on stdout, and exchange() saw zero bytes).
    So this drives the real BotProcess.exchange() against a pipe fed on a separate thread
    instead, which exercises the identical drain loop without needing to defeat the shim.
    """
    import json as _json
    import os as _os
    import selectors as _selectors
    import threading as _threading
    from unittest.mock import MagicMock

    bot = BotProcess.__new__(BotProcess)
    bot.tick_deadline = 0.05
    bot.first_tick_deadline = 0.05
    bot.strike_limit = 99
    bot.strikes = 0
    bot.consecutive = 0
    bot.accepted = 0
    bot.ticks = 0
    bot.forfeited = False
    bot.last_accepted = {}

    read_fd, write_fd = _os.pipe()
    bot.proc = MagicMock()
    bot.proc.stdout = _os.fdopen(read_fd, "r")
    bot.proc.poll.return_value = None
    bot._sel = _selectors.DefaultSelector()
    bot._sel.register(bot.proc.stdout, _selectors.EVENT_READ)
    writer = _os.fdopen(write_fd, "w", buffering=1)

    def flood():
        for _ in range(20):
            time.sleep(0.02)
            try:
                writer.write(_json.dumps({"tick": -1, "actions": {}}) + "\n")
            except (BrokenPipeError, ValueError):
                return

    thread = _threading.Thread(target=flood, daemon=True)
    thread.start()
    start = time.monotonic()
    _, status = bot.exchange(_view(1), rng_seed=1)
    elapsed = time.monotonic() - start
    thread.join(timeout=1.0)
    bot.proc.stdout.close()
    writer.close()
    bot._sel.close()

    assert status == "timeout"
    assert elapsed < 0.3, f"one tick took {elapsed:.2f}s despite a 0.05s deadline"
