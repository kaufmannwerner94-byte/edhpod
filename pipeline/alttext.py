#!/usr/bin/env python3
"""
Alt text for each slide, generated from the same post.json and facts.json the
slides are rendered from, so it can never disagree with what is on the image.

    python3 alttext.py ../queue/2026-11-27-card-of-the-day

Instagram accepts up to 1000 characters per carousel item. The slides are
mostly text, so the alt text is mostly that text, plus the card's own name,
type and oracle text for the card image — a screen-reader user cannot read
the card in the picture, and the oracle text is what is printed on it.
"""

import json
import re
import sys
from pathlib import Path

MAX_CHARS = 1000

CTA = (
    "Closing slide. One card. One combo. Every day. Follow @edhpod for daily "
    "Commander picks, save this for your next deck build, and send it to your "
    "playgroup. Your turn: %s"
)


def _mana(cost: str) -> str:
    """{2}{W}{U} -> 2WU. Braces read aloud as noise."""
    return re.sub(r"[{}]", "", cost or "").replace("/", "")


def _card(facts: dict) -> str:
    parts = [facts.get("name", "")]
    if facts.get("mana_cost"):
        parts.append("mana cost %s" % _mana(facts["mana_cost"]))
    if facts.get("type_line"):
        parts.append(facts["type_line"])
    text = ", ".join(p for p in parts if p) + "."
    if facts.get("oracle_text"):
        text += " Card text: %s" % " ".join(facts["oracle_text"].split())
    return text


def _clip(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_CHARS:
        return text
    return text[: MAX_CHARS - 1].rsplit(" ", 1)[0] + "…"


def _numbered(items: list) -> str:
    return " ".join("%d. %s" % (i, t) for i, t in enumerate(items, start=1))


def card_of_the_day(post: dict, facts: dict) -> list:
    s1, s2, s3 = post["slides"]
    first = (
        "Card of the Day: %s. %s Role: %s. Works in: %s. Price: %s. Card image: %s"
        % (s1["card_name"], s1["hook"], s1["role"], s1["works_in"], s1["price"], _card(facts))
    )
    second = "Why %s works: %s Plays well with: %s. Watch out: %s" % (
        s2["card_name"],
        _numbered([r["text"] for r in s2["reasons"]]),
        ", ".join(p["name"] for p in s2["plays_well_with"]),
        s2["watch_out"],
    )
    return [first, second, CTA % s3["question"]]


def budget_combo(post: dict, facts: dict) -> list:
    s1, s2, s3 = post["slides"]
    pictured = [c.get("name") for c in s1["combo_cards"]]
    if not all(pictured):
        raise SystemExit(
            "post.json predates combo card names — rebuild it with build_combo_post.py"
        )
    oracle = {c["name"]: c for c in facts.get("cards", [])}
    card_text = " ".join(
        "%s: %s" % (n, " ".join((oracle.get(n) or {}).get("oracle_text", "").split()))
        for n in pictured
    )
    total = " / ".join(t for t in (s1.get("total_usd"), s1.get("total_eur")) if t)
    first = "Budget Combo: %s. Card images: %s. How it works: %s Total: %s. %s" % (
        s1["combo_name"], " and ".join(pictured), _numbered([x["text"] for x in s1["steps"]]),
        total, card_text,
    )
    second = "Decklist. %s. Total: %s. Swap: %s" % (
        "; ".join("%s, %s, %s" % (r["name"], r["role"], r["price"]) for r in s2["decklist"]),
        s2["total"], s2["swap"],
    )
    return [first, second, CTA % s3["question"]]


def introduction(post: dict, facts: dict) -> list:
    s1, s2, s3 = post["slides"]
    first = (
        "New set introduction, %s: %s. What it does: %s Best home: %s Our take: %s Card image: %s"
        % (s1["set_name"], s1["card_name"], s1["what_it_does"], s1["best_home"],
           s1["take"], _card(facts.get("lead") or {}))
    )
    second = "More from %s, with card images: %s" % (
        s2["set_name"], " ".join("%s: %s" % (c["name"], c["take"]) for c in s2["cards"]),
    )
    return [first, second, CTA % s3["question"]]


def welcome(post: dict, facts: dict) -> list:
    s1 = post["slides"][0]
    return [
        "EDHPod welcome post. %s Three formats on rotation: Card of the Day, %s; "
        "Budget Combo, %s; Introduction, %s. %s"
        % (s1["headline"].replace("<br>", " "), s1["cotd"], s1["combo"], s1["intro"], s1["disclaimer"])
    ]


BUILDERS = {
    "welcome": welcome,
    "card-of-the-day": card_of_the_day,
    "budget-combo": budget_combo,
    "introduction": introduction,
}


def build(folder: Path) -> list:
    post = json.loads((folder / "post.json").read_text(encoding="utf-8"))
    facts = json.loads((folder / "facts.json").read_text(encoding="utf-8"))
    texts = [_clip(t) for t in BUILDERS[post["format"]](post, facts)]
    (folder / "alt.json").write_text(
        json.dumps(texts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return texts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: alttext.py <post folder>")
    for i, text in enumerate(build(Path(sys.argv[1])), start=1):
        print("slide%d (%d chars)\n  %s\n" % (i, len(text), text))
