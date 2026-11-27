#!/usr/bin/env python3
"""
Build and render every post in the queue.

    python3 build_all.py                 # everything
    python3 build_all.py 2026-12         # only folders matching a prefix

The format comes from the folder name — 2026-12-05-card-of-the-day — so the
date a post goes out and the template it uses are one decision, recorded in
one place, and a folder that is named wrong fails loudly instead of quietly
rendering the wrong thing.

Prices move daily, so this is meant to be re-run on the morning of a post
rather than once at build time. The staleness guard in postkit will stop any
post whose Scryfall data has gone cold.
"""

import sys
import traceback
from pathlib import Path

import build_card_post
import build_combo_post
import build_intro_post
import build_welcome_post
import render

HERE = Path(__file__).resolve().parent
QUEUE = HERE.parent / "queue"

BUILDERS = {
    "card-of-the-day": build_card_post.build,
    "budget-combo": build_combo_post.build,
    "introduction": build_intro_post.build,
    "welcome": build_welcome_post.build,
}


def format_of(folder: Path) -> str:
    for name in BUILDERS:
        if folder.name.endswith(name):
            return name
    raise SystemExit(
        "%s does not end in one of %s" % (folder.name, ", ".join(BUILDERS))
    )


def main(prefix: str = "") -> int:
    folders = sorted(
        f for f in QUEUE.iterdir()
        if f.is_dir() and f.name.startswith(prefix) and (f / "editorial.json").exists()
    )
    if not folders:
        raise SystemExit("No queue folders with an editorial.json match %r" % prefix)

    failures = []
    for folder in folders:
        print("\n%s" % folder.name)
        try:
            post = BUILDERS[format_of(folder)](folder / "editorial.json")
            render.render_post(post)
        except Exception as error:  # keep going; one bad post should not stop the batch
            failures.append((folder.name, error))
            print("  FAILED: %s" % error)
            if not isinstance(error, SystemExit):
                traceback.print_exc()

    print("\n%d/%d built" % (len(folders) - len(failures), len(folders)))
    for name, error in failures:
        print("  %s — %s" % (name, error))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
