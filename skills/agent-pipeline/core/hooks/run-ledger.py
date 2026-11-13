#!/usr/bin/env python3
"""Stop hook for cloud routine sessions: every pipeline run ends with a ledger record.

A session that never ran `pipeline.py begin` is not a pipeline run, and the hook lets it stop. A run without an
outcome is blocked once, with the `finish` command as the reason. If it stops again without finishing, the hook
records it as failed. The hook never blocks on a storage error: a missing record shows up as a missed slot on the
scorecard instead. Local sessions are left alone.
"""

import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True

if os.getenv("CLAUDE_CODE_REMOTE") != "true":
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

import ledger  # noqa: E402
import pcfg  # noqa: E402
from ghrest import GitHub  # noqa: E402

FINISH = (
    "This pipeline run has no ledger record yet. Run `python3 .claude/routines/core/bin/pipeline.py finish "
    '--outcome <wrote|noop|gated|failed> --summary "<one line>"`, with one `--item kind:number:result` per item you '
    "handled, then stop."
)

try:
    payload = json.load(sys.stdin)
except ValueError:
    payload = {}
state = ledger.load_state()
if not state or state.get("flushed"):
    sys.exit(0)

try:
    profile = pcfg.load()
    gh = GitHub(pcfg.lookup(profile, "project.repo"))
    if not state.get("outcome"):
        if payload.get("stop_hook_active") and state.get("nudged"):
            state.update(
                outcome="failed", summary="the run ended without `pipeline.py finish`", ended_at=ledger.now_iso()
            )
            ledger.save_state(state)
            ledger.flush_state(profile, gh, state)
            sys.exit(0)
        state["nudged"] = True
        ledger.save_state(state)
        print(json.dumps({"decision": "block", "reason": FINISH}))
        sys.exit(0)
    ledger.flush_state(profile, gh, state)  # finished, but storing failed then: one more try
except SystemExit:
    raise
except Exception as err:
    print(f"run-ledger: could not store the run record ({err})", file=sys.stderr)
sys.exit(0)
