"""The `serve` subcommand: page, round index, replay bytes, gzip header, 404s, path safety.

If the viewer page and script are not there, these tests fill in placeholders good enough to
serve -- and never overwrite files that already exist.
"""

import gzip
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from skybattle import replay
from skybattle.classes import load_classes
from skybattle.cli import make_server
from skybattle.match import run_round

BOTS = Path(__file__).parent / "bots"
VIEWER_DIR = Path(__file__).resolve().parent.parent / "src" / "skybattle" / "viewer"
ARENA = (2000.0, 2000.0)
SQ = [["scout", "fighter"], ["scout", "fighter"]]


def _ensure_placeholder_viewer_files() -> None:
    VIEWER_DIR.mkdir(parents=True, exist_ok=True)
    index = VIEWER_DIR / "index.html"
    if not index.is_file():
        index.write_text("<!doctype html><title>placeholder</title><canvas></canvas>\n")
    script = VIEWER_DIR / "viewer.js"
    if not script.is_file():
        script.write_text("// placeholder\n")


@pytest.fixture(scope="module")
def replay_dir(tmp_path_factory):
    _ensure_placeholder_viewer_files()
    d = tmp_path_factory.mktemp("replay")
    classes = load_classes(arena=ARENA)
    run_round([BOTS / "good.py", BOTS / "good.py"], SQ, seed=1, arena=ARENA,
              classes=classes, replay_dir=d)
    return d


@pytest.fixture(scope="module")
def server_url(replay_dir):
    server = make_server(replay_dir, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get(url: str):
    return urllib.request.urlopen(url)


def test_root_serves_the_viewer_page(server_url):
    resp = _get(f"{server_url}/")
    assert resp.status == 200
    body = resp.read()
    assert b"<canvas" in body.lower()


def test_viewer_js_is_served(server_url):
    resp = _get(f"{server_url}/viewer.js")
    assert resp.status == 200


def test_rounds_json_lists_the_generated_round(server_url):
    resp = _get(f"{server_url}/rounds.json")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/json")
    data = json.loads(resp.read())
    assert len(data) == 1
    entry = data[0]
    assert entry["name"] == "round-001.fat.jsonl.gz"
    assert entry["seed"] == 1
    assert entry["frames"] > 0
    assert len(entry["bots"]) == 2


def test_replay_route_serves_native_gzip(server_url, replay_dir):
    _, expected_ticks = replay.read(replay_dir / "round-001.fat.jsonl.gz")

    resp = _get(f"{server_url}/replay/round-001.fat.jsonl.gz")
    assert resp.status == 200
    assert resp.headers["Content-Encoding"] == "gzip"
    assert resp.headers["Content-Type"] == "application/json"

    raw = resp.read()
    # The server must not have gunzipped this itself: it should be valid gzip on the wire.
    text = gzip.decompress(raw).decode("utf-8")
    lines = [json.loads(x) for x in text.splitlines() if x.strip()]
    assert len(lines) - 1 == len(expected_ticks)  # header line + one per tick


@pytest.mark.parametrize("suffix", [
    "../../etc/passwd",
    "..%2f..%2fetc%2fpasswd",
    "/etc/passwd",
])
def test_replay_path_traversal_is_refused(server_url, suffix):
    """403 specifically: these must reach the containment check in `_serve_replay`, not just
    fail to match any route (which would 404 regardless of whether containment works)."""
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(f"{server_url}/replay/{suffix}")
    assert exc_info.value.code == 403


def test_unknown_path_is_404(server_url):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(f"{server_url}/nope")
    assert exc_info.value.code == 404


def test_unknown_replay_name_is_404(server_url):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(f"{server_url}/replay/round-999.fat.jsonl.gz")
    assert exc_info.value.code == 404
