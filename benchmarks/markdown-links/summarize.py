#!/usr/bin/env python3
"""Summarize a benchmark run: summarize.py <results dir>  (prints a Markdown table)."""
import collections
import json
import os
import statistics
import sys

rows = [json.loads(l) for l in open(os.path.join(sys.argv[1], "runs.jsonl"), encoding="utf-8")]
by = collections.defaultdict(list)
for r in rows:
    by[(r["case"], r["arm"])].append(r)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else 0


arms = [a for a in ("plugin", "plain", "rule") if any(k[1] == a for k in by)]
cases = list(dict.fromkeys(r["case"] for r in rows))
print("| Case | Arm | Passed | Link problems (mean) | Turns | Output tokens | Cost | Time (s) | Failed checks |")
print("|---|---|---|---|---|---|---|---|---|")
for c in cases:
    for a in arms:
        rs = by.get((c, a), [])
        if not rs:
            continue
        failed = collections.Counter(k for r in rs for k, v in r["checks"].items() if not v)
        if any(r["error"] for r in rs):
            failed["run error"] = sum(1 for r in rs if r["error"])
        print(f"| {c} | {a} | {sum(r['passed'] for r in rs)}/{len(rs)} | {mean([r['link_problems'] for r in rs]):.1f} "
              f"| {mean([r['turns'] for r in rs]):.1f} | {mean([r['output_tokens'] for r in rs]):.0f} "
              f"| ${mean([r['cost_usd'] for r in rs]):.3f} | {mean([r['duration_s'] for r in rs]):.0f} "
              f"| {', '.join(f'{k} ({v})' for k, v in failed.items()) or '—'} |")
print()
print("| Arm | Passed | Cost (total) | Turns (mean) | Time (mean s) |")
print("|---|---|---|---|---|")
for a in arms:
    rs = [r for r in rows if r["arm"] == a]
    print(f"| {a} | {sum(r['passed'] for r in rs)}/{len(rs)} | ${sum(r['cost_usd'] or 0 for r in rs):.2f} "
          f"| {mean([r['turns'] for r in rs]):.1f} | {mean([r['duration_s'] for r in rs]):.0f} |")
