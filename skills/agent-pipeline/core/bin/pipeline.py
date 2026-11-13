#!/usr/bin/env python3
"""The agent pipeline's control plane. Code selects the work, gates the writes and records each run; the model judges.

    python3 .claude/routines/core/bin/pipeline.py begin <routine key> [--dry-run]
    python3 .claude/routines/core/bin/pipeline.py select <role>
    python3 .claude/routines/core/bin/pipeline.py overlap --files <path> [<path> ...]
    python3 .claude/routines/core/bin/pipeline.py post --kind comment|pr|hub-body|release-pr [options] [--body-file F]
    python3 .claude/routines/core/bin/pipeline.py finish --outcome wrote|noop|gated|failed --summary "<one line>"
    python3 .claude/routines/core/bin/pipeline.py ledger init-db | metrics <file> --week <YYYY-Www>

The run protocol (`core/shared.md`) is begin → select → judge → post → finish. Every GitHub call is REST through
`gh api`, because cloud sessions refuse GraphQL and search.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # a __pycache__ next to the vendored core would show up as untracked files

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import gates  # noqa: E402
import ledger  # noqa: E402
import pcfg  # noqa: E402
import writes  # noqa: E402
from ghrest import GhError, GitHub  # noqa: E402

ROLES = sorted([*gates.SELECTORS, "release-manager"])


def emit(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="pipeline.yml (default: the one next to the vendored core)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    begin = sub.add_parser("begin", help="open this run's ledger record")
    begin.add_argument("routine", help="the routine's key in pipeline.yml")
    begin.add_argument("--dry-run", action="store_true", help="the run message says DRY RUN: write nothing")

    select = sub.add_parser("select", help="print this role's eligible work as JSON")
    select.add_argument("role", choices=ROLES)

    overlap = sub.add_parser("overlap", help="the open PRs that touch any of these files (gate G4)")
    overlap.add_argument("--files", nargs="+", required=True)

    post = sub.add_parser("post", help="make one GitHub write through the gateway")
    post.add_argument("--kind", required=True, choices=writes.KINDS)
    post.add_argument("--to", choices=writes.TARGETS, help="where a comment goes (default: from the role)")
    post.add_argument("--issue", type=int, help="the issue or PR number a comment goes on")
    post.add_argument("--marker", help="the role marker, without <!-- -->, e.g. 'PR-EVALUATION sha=<sha> verdict=PASS'")
    post.add_argument("--body-file", help="the body, as Markdown; the gateway adds the marker, header and footer")
    post.add_argument("--title", help="a new PR's title")
    post.add_argument("--head", help="a new PR's head branch")
    post.add_argument("--base", help="a new PR's base branch (default: the integration branch)")
    post.add_argument("--tldr", help="release-pr only: the main themes, 15 words or fewer")

    finish = sub.add_parser("finish", help="close and store this run's ledger record")
    finish.add_argument("--outcome", required=True, choices=ledger.OUTCOMES)
    finish.add_argument("--summary", required=True, help="one line: what the run did")
    finish.add_argument("--item", action="append", default=[], help="kind:number:result, e.g. pr:12:PASS (repeat)")

    store = sub.add_parser("ledger", help="ledger housekeeping")
    store.add_argument("action", choices=["init-db", "metrics"])
    store.add_argument("path", nargs="?", help="metrics: the JSON file scorecard.py wrote")
    store.add_argument("--week", help="metrics: the ISO week, YYYY-Www")
    return ap


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.profile:
        os.environ["PIPELINE_PROFILE"] = args.profile  # every module, local prompts included, reads this one
    profile = pcfg.load()
    gh = GitHub(pcfg.lookup(profile, "project.repo"))
    try:
        if args.cmd == "begin":
            state = ledger.begin(profile, args.routine, args.dry_run)
            emit({k: state[k] for k in ("routine", "role", "session", "dry_run", "core", "started_at")})
        elif args.cmd == "select":
            if args.role == "release-manager":
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                emit(gates.select_release(gh, profile, pcfg.git, today))
            else:
                emit(gates.SELECTORS[args.role](gh, profile))
        elif args.cmd == "overlap":
            emit({"conflicts": gates.overlap(gh, args.files)})
        elif args.cmd == "post":
            result = writes.post(
                profile,
                gh,
                args.kind,
                body=writes.read_body(args.body_file),
                to=args.to,
                number=args.issue,
                marker=args.marker,
                title=args.title,
                head=args.head,
                base=args.base,
                tldr=args.tldr,
            )
            emit(result)
        elif args.cmd == "finish":
            record, sink = ledger.finish(profile, gh, args.outcome, args.summary, args.item)
            emit({"stored": sink, "record": record})
        elif args.cmd == "ledger":
            if args.action == "init-db":
                ledger.init_db(profile)
                emit({"turso": "pipeline_runs is ready"})
            else:
                if not (args.path and args.week):
                    raise ledger.LedgerError("metrics needs the JSON file and --week YYYY-Www")
                state = ledger.load_state() or {}
                if state.get("dry_run"):
                    emit({"dry_run": True, "would_write": f"metrics/{args.week}.json"})
                else:
                    data = json.loads(open(args.path).read())
                    emit({"stored": ledger.put_metrics(profile, gh, args.week, data)})
    except (GhError, writes.WriteRefused, ledger.LedgerError, RuntimeError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
