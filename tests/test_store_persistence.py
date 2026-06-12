"""
Phase 1 / PAIN 4 — prove that store.py persists state to disk across a process
restart (the whole point of moving off in-memory globals + the Render disk).

We don't just reuse the in-process connection: we write in one Python subprocess
and read in a *separate* subprocess sharing the same DATA_DIR, which is exactly
what a Render redeploy does (new process, same mounted volume).
"""
import os
import sys
import json
import subprocess
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_WRITER = """
import store
store.init()
store.set_kv("trade_counter", 7)
store.upsert_trade({"trade_id": "T-0007", "pair": "BTCUSDT",
                    "decision_action": "BUY", "resultado": None})
store.upsert_position({"trade_id": "T-0007", "pair": "BTCUSDT",
                       "entry": 65000, "sl": 64000, "qty": 0.01})
print("WROTE")
"""

_READER = """
import json, store
store.init()
print(json.dumps({
    "trade_counter": store.get_kv("trade_counter", 0),
    "trades": [t["trade_id"] for t in store.all_trades()],
    "positions": [p["trade_id"] for p in store.all_positions()],
}))
"""


def _run(code, data_dir):
    env = dict(os.environ, DATA_DIR=data_dir)
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_state_survives_process_restart():
    with tempfile.TemporaryDirectory() as data_dir:
        # Process 1 writes, then exits (connection torn down with the process).
        assert "WROTE" in _run(_WRITER, data_dir)
        # A brand-new process reads the same DATA_DIR — must see the persisted state.
        result = json.loads(_run(_READER, data_dir))
        assert result["trade_counter"] == 7
        assert "T-0007" in result["trades"]
        assert "T-0007" in result["positions"]


def test_position_delete_is_durable():
    with tempfile.TemporaryDirectory() as data_dir:
        _run(_WRITER, data_dir)
        _run("import store; store.init(); store.delete_position('T-0007'); print('DEL')", data_dir)
        result = json.loads(_run(_READER, data_dir))
        # Closed position is gone, but the trade record (audit trail) remains.
        assert "T-0007" not in result["positions"]
        assert "T-0007" in result["trades"]
