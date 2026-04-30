"""
Export `optimized_params.json` to a sanitised, shareable artefact under reports/.

Why: the live `optimized_params.json` is gitignored (lessons-spirit: it is local
machine-state, not source-of-truth — README §Safety Rules #2). To share the
Gate1+Gate2 winners with another machine or reviewer, run this script. It
writes `reports/optimized_params_<UTC date>.json` with:

  - keys sorted (stable diffs)
  - timestamp stripped (machine-specific)
  - only Gate1+Gate2-marked entries by default (--all to include every entry)

Usage:
  python export_opt_params.py
  python export_opt_params.py --all
  python export_opt_params.py --output reports/custom_name.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent
OPT_PARAMS_PATH = _ROOT / "optimized_params.json"


def _sanitise(entry: dict) -> dict:
    out = {k: v for k, v in entry.items() if k != "timestamp"}
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true",
                    help="Include every entry, not only Gate2 passers (default off)")
    ap.add_argument("--input", type=Path, default=OPT_PARAMS_PATH,
                    help=f"Source file (default {OPT_PARAMS_PATH.name})")
    ap.add_argument("--output", type=Path, default=None,
                    help="Output path (default reports/optimized_params_<UTC date>.json)")
    args = ap.parse_args(argv[1:])

    if not args.input.exists():
        print(f"ERROR: {args.input} does not exist.")
        return 1

    raw = json.loads(args.input.read_text())
    if not isinstance(raw, dict):
        print(f"ERROR: {args.input} is not a JSON object.")
        return 1

    if args.all:
        entries = dict(raw)
    else:
        entries = {k: v for k, v in raw.items() if v.get("gate2_pass") is True}

    if not entries:
        print(f"No entries to export from {args.input} "
              f"({'all entries' if args.all else 'gate2_pass=true filter'}).")
        return 0

    sorted_entries = {k: _sanitise(entries[k]) for k in sorted(entries.keys())}

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(args.input),
        "filter": "all" if args.all else "gate2_pass=true",
        "count": len(sorted_entries),
        "entries": sorted_entries,
    }

    if args.output is None:
        reports_dir = _ROOT.parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
        out_path = reports_dir / f"optimized_params_{date_tag}.json"
    else:
        out_path = args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False))
    print(f"Exported {len(sorted_entries)} entries → {out_path}")
    for k in sorted_entries:
        print(f"  • {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
