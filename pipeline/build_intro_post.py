#!/usr/bin/env python3
"""
Assemble an Introduction post from live Scryfall data plus an editorial file.

    python3 build_intro_post.py ../queue/2026-11-30-introduction/editorial.json

Unlike the other two formats this one deliberately does *not* shop around for
the cheapest printing. The whole point of the post is "this card is new", so
the printing must be the one from the set being introduced — and the script
refuses to build if the named card is not actually in the newest set. That
check is the only thing standing between this format and a post that
confidently introduces a card from two years ago.
"""

import json
import sys
from pathlib import Path

import scryfall


def from_newest_set(name: str, set_code: str, set_name: str) -> dict:
    printing = scryfall.card(name, set_code=set_code)
    if (printing.get("set") or "").lower() != set_code.lower():
        raise SystemExit(
            "%s is not in %s — the Introduction format only covers the newest set"
            % (name, set_name)
        )
    if (printing.get("legalities") or {}).get("commander") != "legal":
        raise SystemExit("%s is not Commander-legal" % name)
    return printing


def build(editorial_path: Path) -> Path:
    editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
    outdir = editorial_path.parent
    images = outdir / "images"

    # Hard-coded set codes are how a post ends up introducing last year's set,
    # so the set is looked up rather than typed. editorial.json may name one
    # only as an assertion, and a mismatch is a build failure.
    newest = scryfall.newest_set()
    code, set_name = newest["code"], newest["name"]
    expected = editorial.get("set_code")
    if expected and expected.lower() != code.lower():
        raise SystemExit(
            "editorial.json says set %s but the newest set is %s (%s). Either "
            "the post is stale or a new set has landed." % (expected, code, set_name)
        )

    lead = from_newest_set(editorial["card"], code, set_name)
    facts = scryfall.summarise(lead)
    lead_image = scryfall.image(lead, images)

    more = []
    more_facts = []
    for entry in editorial["more"]:
        printing = from_newest_set(entry["card"], code, set_name)
        more_facts.append(scryfall.summarise(printing))
        more.append({
            "image": str(scryfall.image(printing, images)),
            "name": printing["name"],
            "take": entry["take"],
        })

    post = {
        "format": "introduction",
        "set": set_name,
        "card": facts["name"],
        "source": facts["scryfall_uri"],
        "slides": [
            {
                "number": editorial["number"],
                "set_name": set_name,
                "card_name": facts["name"],
                "card_image": str(lead_image),
                "what_it_does": editorial["what_it_does"],
                "best_home": editorial["best_home"],
                "take": editorial["take"],
            },
            {"set_name": set_name, "cards": more},
            {"question": editorial["question"]},
        ],
    }

    (outdir / "post.json").write_text(json.dumps(post, indent=2), encoding="utf-8")
    (outdir / "facts.json").write_text(
        json.dumps({"set": newest, "lead": facts, "more": more_facts}, indent=2),
        encoding="utf-8",
    )

    print("  set       %s (%s, released %s)" % (set_name, code, newest["released_at"]))
    print("  lead      %s — %s" % (facts["name"], facts["price_both"]))
    print("  oracle    %s" % facts["oracle_text"].replace("\n", " / "))
    for entry, extra in zip(more, more_facts):
        print("  also      %-36s %s" % (entry["name"], extra["price_both"]))
    print("  wrote     post.json, facts.json")
    return outdir / "post.json"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_intro_post.py <path to editorial.json>")
    build(Path(sys.argv[1]))
