#!/usr/bin/env python3
"""
Assemble a Budget Combo post from live Scryfall data plus an editorial file.

    python3 build_combo_post.py ../queue/2026-11-28-budget-combo/editorial.json

Same split as build_card_post.py: the script owns everything checkable (card
names, images, every price, the total) and editorial.json owns everything
written (the combo name, the steps, the swap, the question).

The total is the part most worth automating. A budget post lives or dies on
that number, it is the easiest thing in the world to type out of date, and it
is the one claim a reader can disprove in ten seconds.
"""

import json
import sys
from pathlib import Path

import postkit
import scryfall


def build(editorial_path: Path) -> Path:
    editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
    outdir = editorial_path.parent
    images = outdir / "images"

    # The decklist is the shopping list, so it is the only source of prices.
    # Anything named on slide 1 has to appear on it, or slide 1 would show two
    # cards above a total that does not include them.
    rows, printings = [], []
    for entry in editorial["decklist"]:
        printing, facts = postkit.buyable(entry["card"])
        printings.append(printing)
        rows.append({
            "name": postkit.display_name(printing),
            "role": entry["role"],
            "price": facts["price_both"],
            "_full_name": facts["name"],
            "_printing": printing,
        })

    by_name = {row["_full_name"]: row for row in rows}
    combo_cards = []
    for name in editorial["combo_cards"]:
        resolved = scryfall.card(name)["name"]
        if resolved not in by_name:
            raise SystemExit(
                "%s is on slide 1 but not in the decklist, so the total would "
                "not include it" % resolved
            )
        combo_cards.append({
            # The name is not drawn on the slide; it is there for the alt text.
            "name": by_name[resolved]["name"],
            "image": str(scryfall.image(by_name[resolved]["_printing"], images)),
        })

    total = postkit.total(printings)
    total_usd, total_eur = postkit.total_parts(printings)

    post = {
        "format": "budget-combo",
        "combo": editorial["combo_name"],
        "sources": [p.get("scryfall_uri") for p in printings],
        "slides": [
            {
                "number": editorial["number"],
                "combo_name": editorial["combo_name"],
                "combo_cards": combo_cards,
                "steps": [{"text": s} for s in editorial["steps"]],
                "total_usd": total_usd,
                "total_eur": total_eur,
            },
            {
                "decklist": [
                    {k: v for k, v in row.items() if not k.startswith("_")}
                    for row in rows
                ],
                "total": total,
                "swap": editorial["swap"],
            },
            {"question": editorial["question"]},
        ],
    }

    facts = {
        "total": total,
        "cards": [
            {
                "name": scryfall.summarise(p)["name"],
                "price_both": scryfall.price_both(p),
                "set_name": p.get("set_name"),
                "oracle_text": scryfall.summarise(p)["oracle_text"],
                "retrieved_at": p.get("_fetched_at"),
                "scryfall_uri": p.get("scryfall_uri"),
            }
            for p in printings
        ],
    }

    (outdir / "post.json").write_text(json.dumps(post, indent=2), encoding="utf-8")
    (outdir / "facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")

    for row in rows:
        print("  %-34s %-10s %s" % (row["name"], row["price"], row["role"]))
    print("  TOTAL     %s" % total)
    print("  wrote     post.json, facts.json")
    return outdir / "post.json"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_combo_post.py <path to editorial.json>")
    build(Path(sys.argv[1]))
