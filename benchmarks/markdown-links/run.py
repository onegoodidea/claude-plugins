#!/usr/bin/env python3
"""Run the markdown-links benchmark: cases x arms x trials of `claude -p`.

Arms:
  plugin  the plugin loaded with --plugin-dir
  plain   no plugin, no instructions
  rule    no plugin; rule.md appended to the system prompt

Every run starts from fixture.py's notes folder (a git repo), with user settings,
user CLAUDE.md, user skills and plugins, and MCP servers all left out
(--setting-sources project --strict-mcp-config), so arms differ only as listed.

Usage: run.py [--trials N] [--arms a,b] [--cases a,b] [--model M] [--jobs N] [--out DIR]
Writes <out>/runs.jsonl (one line per run) and <out>/<case>-<arm>-<n>/ (workspace,
transcript). Summarize with summarize.py <out>.
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fixture  # noqa: E402
import linkcheck  # noqa: E402

PLUGIN = os.path.normpath(os.path.join(HERE, "..", "..", "plugins", "markdown-links"))
RULE = open(os.path.join(HERE, "rule.md"), encoding="utf-8").read()
A = "’"
JANE, SAM = "People/Jane Doe.md", "People/Sam O" + A + "Neil.md"
CLINIC = "Places/St. Ann" + A + "s Clinic.md"
OVERVIEW, PRICING, OLD_PRICING = "Projects/Atlas/Overview.md", "Research/Pricing.md", "Archive/Pricing.md"
NEW_MEETING = "Meetings/2026/03/2026-03-05 - Atlas pricing review.md"
PRICING_HOLDERS = ["Tasks", "Jane Doe", "Overview", "Interview Notes", "Kickoff"]


def exists(ws, rel):
    return os.path.isfile(os.path.join(ws, rel))


def git_changed(ws):
    out = subprocess.run(["git", "-C", ws, "status", "--porcelain=v1", "-uall"],
                         capture_output=True, text=True).stdout
    return [line[3:] for line in out.splitlines()]


def check_write(ws, links, final):
    mine = [l for l in links if l.note == NEW_MEETING]
    body = {l.target for l in mine if l.kind == "md"}
    fm = {l.target for l in mine if l.kind == "wiki-frontmatter"}
    return {
        "note created": exists(ws, NEW_MEETING),
        "links all five notes": {JANE, SAM, CLINIC, OVERVIEW, PRICING} <= body,
        "attendees in frontmatter": {JANE, SAM} <= fm,
    }


def check_rename(ws, links, final):
    return {
        "renamed": exists(ws, "People/Jane Smith.md") and not exists(ws, JANE),
        "no link uses the old name": not any("Jane%20Doe" in l.raw or "[[Jane Doe" in l.raw for l in links),
    }


def check_folder(ws, links, final):
    return {
        "moved": exists(ws, "Archive/Research/Pricing.md") and not os.path.exists(os.path.join(ws, "Research")),
        "unrelated Archive/Pricing.md not repointed": sum(l.target == OLD_PRICING for l in links) == 1,
    }


def check_delete(ws, links, final):
    left = [l for l in links if l.target is None and l.kind == "md" and l.raw.rstrip(">").endswith("Pricing.md")]
    return {
        "deleted": not exists(ws, PRICING),
        "unrelated Archive/Pricing.md not repointed": sum(l.target == OLD_PRICING for l in links) == 1,
        "links left in place": len(left) == 5,
        "asked what to do": "?" in final and any(h in final for h in PRICING_HOLDERS),
    }


def check_shell_move(ws, links, final):
    return {
        "moved": exists(ws, "Archive/Meetings/2026-03-01 - Kickoff.md")
        and exists(ws, "Archive/Meetings/2026-03-03 - Pilot check-in.md")
        and not exists(ws, "Meetings/2026/03/2026-03-01 - Kickoff.md"),
    }


def check_finder_move(ws, links, final):
    return {
        "folder stays where the user put it": exists(ws, "Archive/Research/Pricing.md"),
        "unrelated Archive/Pricing.md not repointed": sum(l.target == OLD_PRICING for l in links) == 1,
    }


def premove_research(ws):
    os.makedirs(os.path.join(ws, "Archive"), exist_ok=True)
    os.rename(os.path.join(ws, "Research"), os.path.join(ws, "Archive", "Research"))


def check_typo(ws, links, final):
    text = open(os.path.join(ws, "Tasks.md"), encoding="utf-8").read()
    return {
        "typo fixed": "recieve" not in text and "receive" in text,
        "only Tasks.md changed": git_changed(ws) == ["Tasks.md"],
    }


CASES = {
    "write": (
        "Create `" + NEW_MEETING + "`: a short meeting note for a call with Jane Doe and Sam O" + A + "Neil at "
        "St. Ann" + A + "s Clinic about the Atlas pricing research. Link the two people, the clinic, the Atlas "
        "overview, and the pricing research note, and list the attendees in frontmatter the way the other "
        "meeting notes do.",
        check_write, True),
    "rename": ("Jane Doe changed her name to Jane Smith. Rename her note to match.", check_rename, True),
    "folder": ("Move the Research folder into Archive, so it becomes Archive/Research.", check_folder, True),
    "delete": ("Delete Research/Pricing.md; that research is obsolete.", check_delete, False),
    "shell-move": ("Move both March 2026 meeting notes from Meetings/2026/03 into Archive/Meetings, "
                   "using one shell command.", check_shell_move, True),
    "git-mv": ("Run `mkdir -p Archive/Meetings && git mv Meetings/2026/03/* Archive/Meetings/` to archive the March "
               "2026 meeting notes. Use git mv for the move itself, not any other tool.", check_shell_move, True),
    "finder-move": ("I moved the Research folder into Archive in Finder. Make sure everything still works.",
                    check_finder_move, True),
    "typo": ("Fix the spelling mistake in Tasks.md.", check_typo, True),
}
PREPARE = {"finder-move": premove_research}
ARMS = ("plugin", "plain", "rule")
TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill"]


def command(arm, prompt, model):
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--setting-sources", "project", "--strict-mcp-config",
           "--permission-mode", "acceptEdits", "--max-turns", "30",
           "--model", model, "--allowedTools", *TOOLS]
    if arm == "plugin":
        cmd += ["--plugin-dir", PLUGIN]
    elif arm == "rule":
        cmd += ["--append-system-prompt", RULE]
    return cmd


def parse_stream(lines):
    """The result event, tool names used, and how many Bash calls ran relink.

    claude -p does not put hook feedback in its stream, so a relink run is the
    visible sign that the hook's message reached Claude (or that it chose relink).
    """
    result, tools, relinks = {}, [], 0
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tools.append(block.get("name"))
                    cmd = (block.get("input") or {}).get("command", "")
                    if block.get("name") == "Bash" and " relink" in cmd:
                        relinks += 1
        elif ev.get("type") == "result":
            result = ev
    return result, tools, relinks


def run_one(case, arm, n, model, out, lock):
    tag = f"{case}-{arm}-{n}"
    base = os.path.join(out, tag)
    ws = os.path.join(base, "notes")
    os.makedirs(base)
    fixture.build(ws)
    if case in PREPARE:
        PREPARE[case](ws)
    prompt, check, clean_expected = CASES[case]
    started = datetime.datetime.now()
    try:
        proc = subprocess.run(command(arm, prompt, model), cwd=ws, capture_output=True, text=True, timeout=900)
        stdout, error = proc.stdout, (proc.stderr.strip()[-500:] if proc.returncode else "")
    except subprocess.TimeoutExpired as e:
        stdout, error = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
    with open(os.path.join(base, "transcript.jsonl"), "w", encoding="utf-8") as f:
        f.write(stdout)
    result, tools, relinks = parse_stream(stdout.splitlines())
    final = result.get("result", "") or ""
    links = linkcheck.scan(ws)
    probs = linkcheck.problems(links)
    checks = check(ws, links, final)
    if clean_expected:
        checks["no broken links"] = not probs
    usage = result.get("usage", {})
    row = {
        "case": case, "arm": arm, "trial": n, "model": model,
        "passed": all(checks.values()) and not error, "checks": checks,
        "link_problems": len(probs), "problems": probs[:20],
        "turns": result.get("num_turns"), "cost_usd": result.get("total_cost_usd"),
        "duration_s": round((datetime.datetime.now() - started).total_seconds(), 1),
        "output_tokens": usage.get("output_tokens"),
        "input_tokens": sum(usage.get(k, 0) or 0 for k in
                            ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
        "tool_calls": len(tools), "used_skill": "Skill" in tools, "relink_runs": relinks,
        "error": error, "final": final[-1500:],
    }
    with lock:
        with open(os.path.join(out, "runs.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{tag}: {'pass' if row['passed'] else 'FAIL'} "
              f"({row['link_problems']} link problems, {row['turns']} turns, ${row['cost_usd'] or 0:.3f})", flush=True)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--cases", default=",".join(CASES))
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(HERE, "results",
                                                   datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    lock = threading.Lock()
    jobs = [(c, arm, n) for n in range(1, a.trials + 1) for c in a.cases.split(",") for arm in a.arms.split(",")]
    with cf.ThreadPoolExecutor(a.jobs) as pool:
        list(pool.map(lambda j: run_one(*j, a.model, a.out, lock), jobs))
    print(f"results: {a.out}")


if __name__ == "__main__":
    main()
