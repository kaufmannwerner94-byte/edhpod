#!/usr/bin/env python3
"""
Assemble the welcome post — the single image that carries the Fan Content
disclaimer and gets pinned to the profile.

    python3 build_welcome_post.py ../queue/<date>-welcome/editorial.json

No card data is involved, so there is nothing to look up: the words come from
editorial.json and the disclaimer wording is fixed here, because Wizards
requires it verbatim and it should not be possible to paraphrase it by
editing a JSON file.
"""

import json
import sys
from pathlib import Path

# Fan Content Policy, exact wording. See COMPLIANCE.md.
DISCLAIMER = (
    "EDHPod is unofficial Fan Content permitted under the Fan Content Policy. "
    "Not approved/endorsed by Wizards. Portions of the materials used are "
    "property of Wizards of the Coast. ©Wizards of the Coast LLC."
)


def build(editorial_path: Path) -> Path:
    editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
    outdir = editorial_path.parent
    post = {
        "format": "welcome",
        "slides": [{
            "headline": editorial["headline"],
            "cotd": editorial["card_of_the_day"],
            "combo": editorial["budget_combo"],
            "intro": editorial["introduction"],
            "disclaimer": DISCLAIMER,
        }],
    }
    caption = (outdir / "caption.txt").read_text(encoding="utf-8")
    if DISCLAIMER not in caption:
        raise SystemExit("The welcome caption must contain the full Fan Content disclaimer verbatim")
    (outdir / "post.json").write_text(json.dumps(post, indent=2, ensure_ascii=False), encoding="utf-8")
    # No cards, so no facts — but checks.py reads the file, and an explicit
    # empty record says "nothing to verify" rather than "forgot to verify".
    (outdir / "facts.json").write_text(json.dumps({"cards": []}, indent=2), encoding="utf-8")
    print("  wrote     post.json, facts.json")
    return outdir / "post.json"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_welcome_post.py <path to editorial.json>")
    build(Path(sys.argv[1]))
