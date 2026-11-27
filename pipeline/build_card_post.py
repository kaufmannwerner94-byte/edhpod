#!/usr/bin/env python3
"""
Assemble a Card of the Day post from live Scryfall data plus an editorial file.

    python3 build_card_post.py ../queue/2026-11-27-card-of-the-day/editorial.json

The split matters: everything verifiable (name, price, colors, image, oracle
text) is pulled fresh and written by this script, and everything editorial
(hook, reasons, watch-out, question) is hand-written in editorial.json. Nothing
factual is ever typed by hand into the slides, which is what the accuracy gate
in COMPLIANCE.md is there to enforce.

Alongside post.json it writes facts.json — the Scryfall record the copy was
checked against, so a later review can re-read the source rather than trusting
the slide.
"""

import json
import sys
from pathlib import Path

import postkit
import scryfall

HERE = Path(__file__).resolve().parent


def build(editorial_path: Path) -> Path:
    editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
    outdir = editorial_path.parent

    name = editorial["card"]
    printing, facts = postkit.buyable(
        name, universes_beyond=editorial.get("allow_universes_beyond", False)
    )

    image_path = scryfall.image(printing, outdir / "images")

    # Plays-well-with entries are verified to exist and to be Commander-legal,
    # so a hallucinated card name fails here rather than on the slide.
    partners = [
        {"name": postkit.must_be_legal(n)["name"]}
        for n in editorial["plays_well_with"]
    ]

    post = {
        "format": "card-of-the-day",
        "card": facts["name"],
        "source": facts["scryfall_uri"],
        "slides": [
            {
                "number": editorial["number"],
                "card_image": str(image_path),
                "card_name": facts["name"],
                "role": editorial["role"],
                "works_in": editorial["works_in"],
                "price": facts["price_both"],
                "hook": editorial["hook"],
            },
            {
                "card_name": facts["name"],
                "reasons": [{"text": r} for r in editorial["reasons"]],
                "plays_well_with": partners,
                "watch_out": editorial["watch_out"],
            },
            {"question": editorial["question"]},
        ],
    }

    (outdir / "post.json").write_text(json.dumps(post, indent=2), encoding="utf-8")
    (outdir / "facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")

    print("  card      %s (%s, %s)" % (facts["name"], facts["set_name"], facts["price_both"]))
    print("  oracle    %s" % facts["oracle_text"].replace("\n", " / "))
    print("  image     %s" % image_path.name)
    print("  wrote     post.json, facts.json")
    return outdir / "post.json"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_card_post.py <path to editorial.json>")
    build(Path(sys.argv[1]))
