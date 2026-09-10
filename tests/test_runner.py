import json
import subprocess
import sys
from pathlib import Path

from skybattle import protocol
from skybattle.state import Gun, OwnPlane, View

BOTS = Path(__file__).parent / "bots"


def _line(tick=1):
    g = Gun(name="forward", bearing_deg=0.0, dispersion_deg=8.0, ammo=80, cooldown_ticks_left=0)
    p = OwnPlane(id=0, kind="scout", x=0.0, y=0.0, heading_deg=0.0, speed=5.0, hp=70, hp_max=70,
                 stall_speed=3.0, corner_speed=5.0, max_speed=9.0, guns=(g,), contacts=())
    view = View(tick=tick, arena=(2000.0, 2000.0), planes=(p,), events=())
    return json.dumps(protocol.encode_view(view, rng_seed=1)) + "\n"


def _run(bot, ticks=2, timeout=20):
    proc = subprocess.run(
        [sys.executable, "-u", "-m", "skybattle.runner", str(BOTS / bot)],
        input="".join(_line(t) for t in range(1, ticks + 1)),
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    replies = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
    return replies, proc.stderr


def test_a_good_bot_replies_once_per_tick_with_the_tick_echoed():
    replies, _ = _run("good.py")
    assert [r["tick"] for r in replies] == [1, 2]
    assert replies[0]["actions"]["0"][0] == 1.0


def test_printing_does_not_corrupt_the_protocol():
    replies, err = _run("chatty.py")
    assert [r["tick"] for r in replies] == [1, 2]
    assert "hello from module import time" in err
    assert "thinking about tick" in err


def test_a_bot_printing_protocol_shaped_json_still_cannot_corrupt_the_stream():
    replies, err = _run("protocol_liar.py")
    assert [r["tick"] for r in replies] == [1, 2]
    # its fake reply is on stderr, and its REAL reply is the throttle it returned
    assert all(r["actions"]["0"][0] == 0.25 for r in replies)
    assert "actions" in err


def test_a_crash_becomes_a_clean_error_reply_with_the_traceback_on_stderr():
    replies, err = _run("crasher.py")
    assert [r["tick"] for r in replies] == [1, 2]
    assert all("error" in r for r in replies)
    assert "bot author's bug: index out of range" in err
    assert "Traceback" in err


def test_a_plain_act_function_works_as_well_as_a_bot_class():
    replies, _ = _run("function_style.py")
    assert replies[0]["actions"]["0"][0] == 1.0


def test_a_missing_bot_file_fails_loudly_rather_than_silently():
    proc = subprocess.run(
        [sys.executable, "-u", "-m", "skybattle.runner", str(BOTS / "nope.py")],
        input=_line(), capture_output=True, text=True, timeout=20, check=False,
    )
    assert proc.returncode != 0
    assert "nope.py" in proc.stderr
