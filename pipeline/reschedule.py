#!/usr/bin/env python3
"""
Move every unpublished post onto consecutive days from a start date, keeping
their order. For launching later than planned, or closing a gap after a missed day.

    python3 reschedule.py 2026-12-01            # show what would move
    python3 reschedule.py 2026-12-01 --apply    # do it

The daily job only ever publishes the folder dated today, so a post whose date
has passed is silently skipped forever. This is the fix.

Approvals survive the move: they fingerprint the post's words, not its folder name.
"""

import argparse
import datetime
import sys

import queuekit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("start", help="first publication date, YYYY-MM-DD")
    parser.add_argument("--apply", action="store_true", help="actually rename the folders")
    args = parser.parse_args()

    start = datetime.date.fromisoformat(args.start)
    if args.start < queuekit.today_utc():
        raise SystemExit("%s is in the past" % args.start)

    posts = queuekit.all_posts()
    published = [f for f in posts if queuekit.status(f) == "published"]
    pending = [f for f in posts if queuekit.status(f) != "published"]
    clash = [f.name for f in published if queuekit.date_of(f) >= args.start]
    if clash:
        raise SystemExit("Already published on or after %s: %s" % (args.start, ", ".join(clash)))

    moves = []
    for offset, folder in enumerate(pending):
        date = (start + datetime.timedelta(days=offset)).isoformat()
        target = folder.with_name(date + folder.name[10:])
        if target != folder:
            moves.append((folder, target))
        print("  %s  ->  %s" % (folder.name, target.name))

    if not args.apply:
        print("\n%d folder(s) would move. Re-run with --apply." % len(moves))
        return 0

    # Two passes, so a post moving onto a date another post is vacating
    # cannot collide with it.
    staged = []
    for folder, target in moves:
        temp = folder.with_name(".moving-" + folder.name)
        folder.rename(temp)
        staged.append((temp, target))
    for temp, target in staged:
        temp.rename(target)
    print("\nMoved %d folder(s). Commit and push so the workflow sees the new dates." % len(moves))
    return 0


if __name__ == "__main__":
    sys.exit(main())
