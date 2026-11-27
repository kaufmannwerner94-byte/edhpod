#!/usr/bin/env python3
"""
Review and approve queued posts. Nothing is published without approval.

    python3 approve.py                     # the queue at a glance
    python3 approve.py 2026-11-27          # show one post, then approve it
    python3 approve.py 2026-11-27 --yes    # approve without the prompt
    python3 approve.py 2026-11-27 --revoke # take an approval back

Approval writes approved.json into the post folder. Commit and push it — the
daily workflow only sees what is on GitHub:

    git add queue && git commit -m "Approve 2026-11-27" && git push

What you are approving is the words: editorial.json and caption.txt. The
slides are re-rendered on the morning of publication with that day's prices,
and the automated checks in checks.py run again then. Editing either file after
approving voids the approval.
"""

import argparse
import datetime
import getpass
import json
import sys

import checks
import queuekit

MARK = {
    "published": "✓ published",
    "approved": "● approved",
    "rejected": "✗ rejected",
    "changed-since-approval": "! edited since approval",
    "queued": "○ needs review",
}


def overview() -> int:
    today = queuekit.today_utc()
    print("today (UTC) %s\n" % today)
    for folder in queuekit.all_posts():
        date = queuekit.date_of(folder)
        state = queuekit.status(folder)
        late = date < today and state not in ("published",)
        print("  %s  %-16s %-24s%s" % (
            date, queuekit.format_of(folder), MARK[state], "  (date has passed)" if late else ""))
    yesterday = datetime.date.fromisoformat(today) - datetime.timedelta(days=1)
    runway = queuekit.approved_runway(yesterday.isoformat())
    print("\n%d consecutive day(s) from today are approved." % runway)
    return 0


def show(folder) -> list:
    print("=" * 72)
    print(folder.name)
    print("=" * 72)
    editorial = json.loads((folder / "editorial.json").read_text(encoding="utf-8"))
    print(json.dumps(editorial, indent=2, ensure_ascii=False))
    print("-" * 72 + "\ncaption.txt\n" + "-" * 72)
    print((folder / "caption.txt").read_text(encoding="utf-8"))
    print("-" * 72)
    for i in (1, 2, 3):
        print("slide%d     %s" % (i, folder / ("slide%d.jpg" % i)))
    print("-" * 72)
    # Prices and alt text are regenerated at publish time, so only check what
    # approval actually covers plus the rendered layout.
    problems = checks.run(folder, publish_time=False)
    for p in problems:
        print("  FAIL  %s" % p)
    print("checks    %s" % ("all passed" if not problems else "%d problem(s)" % len(problems)))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Review and approve EDHPod posts")
    parser.add_argument("post", nargs="?", help="date (YYYY-MM-DD) or folder name")
    parser.add_argument("--yes", action="store_true", help="approve without asking")
    parser.add_argument("--revoke", action="store_true", help="withdraw an approval")
    args = parser.parse_args()

    if not args.post:
        return overview()

    folder = queuekit.find(args.post)
    state = queuekit.status(folder)
    if state == "published":
        raise SystemExit("%s is already published" % folder.name)

    if args.revoke:
        path = folder / "approved.json"
        if path.exists():
            path.unlink()
            print("approval withdrawn for %s — commit and push to take effect" % folder.name)
        else:
            print("%s was not approved" % folder.name)
        return 0

    problems = show(folder)
    if problems:
        raise SystemExit("Fix the problems above before approving.")
    if state == "approved":
        print("already approved, unchanged since.")
        return 0

    if not args.yes:
        answer = input("\nApprove %s for publication? [y/N] " % folder.name)
        if answer.strip().lower() not in ("y", "yes"):
            print("not approved")
            return 1

    queuekit.approve(folder, getpass.getuser())
    print("approved. Now: git add queue && git commit -m \"Approve %s\" && git push"
          % queuekit.date_of(folder))
    return 0


if __name__ == "__main__":
    sys.exit(main())
