#!/usr/bin/env python3
"""Build the made-up notes folder every benchmark run starts from.

Usage: fixture.py <dest>   (dest must not exist; becomes a git repo with one commit)
"""
import os
import subprocess
import sys

APOS = "’"  # curly apostrophe, as in real note titles

FILES = {
    ".markdown-links.json": '{"exclude": []}\n',
    "README.md": (
        "# Notes\n\n"
        "Start with [Tasks](Tasks.md) and the [Atlas overview](Projects/Atlas/Overview.md).\n"
        "People: [Jane Doe](People/Jane%20Doe.md), [Sam O" + APOS + "Neil](People/Sam%20O%E2%80%99Neil.md).\n"
        "The [old pricing note](Archive/Pricing.md) is kept for history.\n"
    ),
    "Tasks.md": (
        "# Tasks\n\n"
        "- Send Jane the draft ([Jane Doe](People/Jane%20Doe.md)); she should recieve it Friday.\n"
        "- Review [Atlas tasks](Projects/Atlas/Tasks.md).\n"
        "- Read the [pricing research](Research/Pricing.md).\n"
    ),
    "People/Jane Doe.md": (
        "---\naliases:\n  - Jane\n---\n\n# Jane Doe\n\n"
        "Leads research on [Atlas](../Projects/Atlas/Overview.md). Wrote [Pricing](../Research/Pricing.md).\n"
    ),
    "People/Sam O" + APOS + "Neil.md": "# Sam O" + APOS + "Neil\n\nWorks with [Jane Doe](Jane%20Doe.md).\n",
    "Places/St. Ann" + APOS + "s Clinic.md": "# St. Ann" + APOS + "s Clinic\n\nWhere the Atlas pilot runs.\n",
    "Projects/Atlas/Overview.md": (
        "# Atlas\n\n"
        "Owner: [Jane Doe](../../People/Jane%20Doe.md). See [Tasks](Tasks.md) and the\n"
        "[pricing research](../../Research/Pricing.md) and [interview notes](../../Research/Interview%20Notes%20%28beta%29.md).\n"
    ),
    "Projects/Atlas/Tasks.md": "# Atlas tasks\n\n- Ask [Sam](../../People/Sam%20O%E2%80%99Neil.md) about the pilot.\n",
    "Research/Pricing.md": (
        "# Pricing\n\n"
        "By [Jane Doe](../People/Jane%20Doe.md). Raw notes: [interviews](Interview%20Notes%20%28beta%29.md).\n"
    ),
    "Research/Interview Notes (beta).md": "# Interview notes (beta)\n\nThree calls. Summary in [Pricing](Pricing.md).\n",
    "Archive/Pricing.md": "# Pricing (2024)\n\nSuperseded.\n",
    "Meetings/2026/03/2026-03-01 - Kickoff.md": (
        "---\ndate: 2026-03-01\nwith:\n  - \"[[Jane Doe]]\"\n  - \"[[Sam O" + APOS + "Neil]]\"\n---\n\n"
        "# Kickoff\n\n"
        "With [Jane](../../../People/Jane%20Doe.md) and [Sam](../../../People/Sam%20O%E2%80%99Neil.md).\n"
        "We agreed to start from the [pricing research](../../../Research/Pricing.md).\n"
    ),
    "Meetings/2026/03/2026-03-03 - Pilot check-in.md": (
        "---\ndate: 2026-03-03\nwith:\n  - \"[[Jane Doe]]\"\n---\n\n"
        "# Pilot check-in\n\n"
        "At [St. Ann" + APOS + "s](../../../Places/St.%20Ann%E2%80%99s%20Clinic.md). Next: [Atlas tasks](../../../Projects/Atlas/Tasks.md).\n"
    ),
}


def build(dest: str) -> None:
    os.makedirs(dest)
    for rel, text in FILES.items():
        path = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    git = ["git", "-C", dest, "-c", "user.name=bench", "-c", "user.email=bench@example.invalid"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "notes"], check=True)


if __name__ == "__main__":
    build(sys.argv[1])
