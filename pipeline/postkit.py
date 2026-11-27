#!/usr/bin/env python3
"""
Shared gates for the build scripts.

Every format pulls cards the same way and has to pass the same checks before
anything reaches a slide, so those checks live here rather than being copied
into each build_*.py and drifting apart.

Two rules this file exists to enforce:

1. A card named in a post must exist, be Commander-legal, and have a price —
   a hallucinated or banned card fails the build instead of the audience.
2. A price must never be older than half of Scryfall's own "dangerously stale
   after 24 hours" window, because a post that quotes a number nobody
   re-checked is worse than a post with no number.
"""

import calendar
import time

import scryfall

# Scryfall calls its prices "dangerously stale after 24 hours". Half of that is
# the widest window where a price is still worth printing on a slide.
MAX_AGE_HOURS = 12


def _check_age(facts: dict) -> None:
    stamped = facts.get("retrieved_at")
    if not stamped:
        raise SystemExit("%s has no retrieval timestamp" % facts.get("name"))
    age = (
        time.time() - calendar.timegm(time.strptime(stamped, "%Y-%m-%dT%H:%M:%SZ"))
    ) / 3600
    if age > MAX_AGE_HOURS:
        raise SystemExit(
            "Scryfall data for %s is %.1f hours old. Rebuild with "
            "EDHPOD_NO_CACHE=1 so the price is current." % (facts["name"], age)
        )


def buyable(name: str, universes_beyond: bool = False) -> tuple:
    """
    The printing a reader would actually buy, plus its verified facts.

    Returns (printing, facts). Raises if the card is not Commander-legal or if
    the data behind it has gone stale.
    """
    printing = scryfall.cheapest_printing(name, universes_beyond=universes_beyond)
    facts = scryfall.summarise(printing)
    if facts["commander_legal"] != "legal":
        raise SystemExit(
            "%s is %s in Commander — do not post it" % (name, facts["commander_legal"])
        )
    _check_age(facts)
    return printing, facts


def must_be_legal(name: str) -> dict:
    """
    Confirm a card that is only *mentioned* (no price, no image) is real and
    legal. Cheaper than buyable() because it needs one lookup, not a print run.
    """
    data = scryfall.card(name)
    legal = (data.get("legalities") or {}).get("commander")
    if legal != "legal":
        raise SystemExit("%s is %s in Commander" % (name, legal))
    return data


def total_parts(printings: list) -> tuple:
    """
    Sum a shopping list in both currencies, returned separately so a template
    can stack them instead of wrapping "$13.58 / €11.33" mid-slash.

    A currency is only reported when every card has a price in it — a total
    that silently skips two of eight cards reads as a bargain and is a lie.
    """
    usd = [(p.get("prices") or {}).get("usd") for p in printings]
    eur = [(p.get("prices") or {}).get("eur") for p in printings]
    out = (
        "$%.2f" % sum(float(v) for v in usd) if all(usd) else "",
        "€%.2f" % sum(float(v) for v in eur) if all(eur) else "",
    )
    if not any(out):
        raise SystemExit("Cannot total this list — prices are missing")
    return out


def total(printings: list) -> str:
    return " / ".join(p for p in total_parts(printings) if p)


def display_name(printing: dict) -> str:
    """
    What to print on a slide. For a transforming card Scryfall's name is
    "Front // Back", which is correct and also 42 characters of decklist row
    for a card everyone calls by its front face.
    """
    name = printing.get("name", "")
    if printing.get("layout") in ("transform", "modal_dfc", "meld", "reversible_card"):
        return name.split(" // ")[0]
    return name
