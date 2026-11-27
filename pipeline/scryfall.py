#!/usr/bin/env python3
"""
Scryfall access for EDHPod.

Every rule in COMPLIANCE.md that can be enforced in code is enforced here:
identifying User-Agent and Accept headers on every request, 2 req/sec on the
card endpoints, 30-second backoff on 429, a 24-hour local cache, and images
pulled from the unmetered CDN rather than the API.

    python3 scryfall.py card "Cultivate"
    python3 scryfall.py newest-set
"""

import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
IMAGES = HERE / ".cache" / "images"
CACHE_SECONDS = 24 * 60 * 60

API = "https://api.scryfall.com"
USER_AGENT = "EDHPod/1.0 (Instagram @edhpod; daily Commander content)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

# Scryfall documents 2 req/sec for the card endpoints and 10 req/sec elsewhere.
# We use the strict figure everywhere; one post a day makes the cost irrelevant.
MIN_INTERVAL = 0.5
_last_call = [0.0]


def _throttle() -> None:
    wait = MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def _get(path: str, params: dict = None, attempt: int = 0):
    _throttle()
    response = requests.get(API + path, params=params, headers=HEADERS, timeout=30)
    if response.status_code == 429:
        if attempt >= 2:
            raise RuntimeError("Scryfall rate limited us repeatedly — stop and investigate")
        print("  rate limited by Scryfall, backing off 30s")
        time.sleep(30)
        return _get(path, params, attempt + 1)
    if response.status_code == 404:
        raise LookupError("Not found on Scryfall: %s %s" % (path, params))
    response.raise_for_status()
    return response.json()


def _cached(key: str, producer):
    CACHE.mkdir(parents=True, exist_ok=True)
    safe = urllib.parse.quote(key, safe="")
    path = CACHE / ("%s.json" % safe)
    # EDHPOD_NO_CACHE=1 forces a refetch. The cache lives in a folder that does
    # not always permit deleting files, so this is the way to clear it.
    fresh = os.environ.get("EDHPOD_NO_CACHE") == "1"
    if not fresh and path.exists() and (time.time() - path.stat().st_mtime) < CACHE_SECONDS:
        value = json.loads(path.read_text(encoding="utf-8"))
    else:
        value = producer()
        path.write_text(json.dumps(value), encoding="utf-8")
    # Stamp when Scryfall was actually contacted, not when this ran — a cached
    # read can be up to 24h old and prices go stale on exactly that timescale.
    fetched = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))
    if isinstance(value, dict):
        value["_fetched_at"] = fetched
    elif isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                entry["_fetched_at"] = fetched
    return value


def card(name: str, set_code: str = None) -> dict:
    """Exact card lookup. Oracle text here is authoritative — never paraphrase it."""
    params = {"exact": name}
    if set_code:
        params["set"] = set_code
    return _cached("card:%s:%s" % (name, set_code or ""), lambda: _get("/cards/named", params))


def search(query: str, order: str = "edhrec", limit: int = 20) -> list:
    """Search. Use Scryfall query syntax, e.g. 'set:fin is:commander'."""
    def fetch():
        data = _get("/cards/search", {"q": query, "order": order, "unique": "cards"})
        return data.get("data", [])[:limit]
    return _cached("search:%s:%s:%d" % (query, order, limit), fetch)


def printings(name: str, universes_beyond: bool = True) -> list:
    """Every printing of a card, newest first. `/cards/named` returns only one."""
    query = '!"%s"' % name
    if not universes_beyond:
        query += " -is:ub"
    def fetch():
        data = _get("/cards/search", {
            "q": query, "unique": "prints", "order": "released",
            "dir": "desc", "include_extras": "false",
        })
        return data.get("data", [])
    return _cached("prints:%s:%s" % (name, universes_beyond), fetch)


def cheapest_printing(name: str, universes_beyond: bool = False) -> dict:
    """
    The printing a reader would actually buy.

    Two corrections to the naive `/cards/named` lookup. First, that returns the
    *newest* printing, which in a new-set week is often the most expensive one —
    quoting it would overstate the cost of every evergreen staple we feature.
    Second, Universes Beyond printings are frequently the cheapest, but showing
    a Commander staple in crossover art teaches a new player to look for the
    wrong card, so they are excluded unless asked for. The price and the image
    always come from the same printing; never mix them.
    """
    wanted = name.strip().lower()

    def usable(printing_list):
        return [
            p for p in printing_list
            if price_value(p)
            and (p.get("legalities") or {}).get("commander") == "legal"
            # Scryfall's exact-name operator also matches a single *face* of a
            # double-faced card, so asking for "Reanimate" can return a modern
            # DFC whose back face happens to share the name. Different card,
            # different price, wrong image — compare the whole name.
            and (p.get("name") or "").strip().lower() == wanted
            # Cheapest-in-euros, left unguarded, lands on 1990s foreign-language
            # reprints like Chronicles Foreign Black Border: a real price for a
            # card the reader cannot read and will not find in a shop.
            and p.get("lang") == "en"
            and "paper" in (p.get("games") or [])
            and p.get("set_type") not in ("memorabilia", "token", "funny", "alchemy")
            and not p.get("oversized")
            and p.get("border_color") not in ("gold", "silver")
            and (p.get("image_uris") or p.get("card_faces"))
        ]

    candidates = usable(printings(name, universes_beyond=universes_beyond))
    if not candidates and not universes_beyond:
        candidates = usable(printings(name, universes_beyond=True))
    if not candidates:
        return card(name)
    return min(candidates, key=price_value)


def newest_set() -> dict:
    """The most recent released expansion — what the Introduction format covers."""
    def fetch():
        sets = _get("/sets")["data"]
        today = time.strftime("%Y-%m-%d")
        released = [
            s for s in sets
            if s.get("set_type") in ("expansion", "core")
            and not s.get("digital")
            and s.get("released_at", "9999") <= today
        ]
        released.sort(key=lambda s: s["released_at"], reverse=True)
        return released[0]
    return _cached("newest-set", fetch)


def image(card_data: dict, dest_dir: Path = None) -> Path:
    """
    Download the full card image at 744x1040 png: transparent, rounded corners,
    and the artist credit plus copyright line baked in, which is what keeps us
    compliant without having to print them ourselves.
    """
    dest_dir = Path(dest_dir) if dest_dir else IMAGES
    dest_dir.mkdir(parents=True, exist_ok=True)

    faces = card_data.get("card_faces")
    uris = card_data.get("image_uris") or (faces[0].get("image_uris") if faces else None)
    if not uris or "png" not in uris:
        raise LookupError("No png image for %s" % card_data.get("name"))

    target = dest_dir / ("%s.png" % card_data["id"])
    if target.exists() and target.stat().st_size > 0:
        return target

    # cards.scryfall.io is the unmetered origin — no throttle needed here.
    response = requests.get(uris["png"], headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    target.write_bytes(response.content)
    return target


def price_eur(card_data: dict) -> str:
    """Formatted EUR price, or a clear marker when Scryfall has none."""
    raw = (card_data.get("prices") or {}).get("eur")
    if not raw:
        usd = (card_data.get("prices") or {}).get("usd")
        return "$%.2f" % float(usd) if usd else "n/a"
    return "€%.2f" % float(raw)


def price_both(card_data: dict) -> str:
    """USD and EUR side by side. Both come from the same printing, so the two
    numbers are always describing the same physical card."""
    prices = card_data.get("prices") or {}
    usd, eur = prices.get("usd"), prices.get("eur")
    parts = []
    if usd:
        parts.append("$%.2f" % float(usd))
    if eur:
        parts.append("€%.2f" % float(eur))
    return " / ".join(parts) if parts else "n/a"


def price_value(card_data: dict) -> float:
    raw = (card_data.get("prices") or {}).get("eur")
    return float(raw) if raw else 0.0


def summarise(card_data: dict) -> dict:
    """The facts a post may state. Anything not in here must not be asserted."""
    faces = card_data.get("card_faces") or []
    oracle = card_data.get("oracle_text") or "\n//\n".join(
        f.get("oracle_text", "") for f in faces
    )
    return {
        # Stamped so the "prices recomputed at publish time" check in
        # COMPLIANCE.md can be evidenced rather than assumed. Scryfall calls
        # its prices dangerously stale after 24 hours.
        "retrieved_at": card_data.get("_fetched_at"),
        "name": card_data["name"],
        "mana_cost": card_data.get("mana_cost") or (faces[0].get("mana_cost") if faces else ""),
        "cmc": card_data.get("cmc"),
        "type_line": card_data.get("type_line"),
        "oracle_text": oracle,
        "color_identity": card_data.get("color_identity", []),
        "artist": card_data.get("artist"),
        "set_name": card_data.get("set_name"),
        "released_at": card_data.get("released_at"),
        "commander_legal": (card_data.get("legalities") or {}).get("commander"),
        "price_eur": price_eur(card_data),
        "price_both": price_both(card_data),
        "scryfall_uri": card_data.get("scryfall_uri"),
    }


COLOR_NAMES = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}


def color_identity_label(card_data: dict) -> str:
    identity = card_data.get("color_identity", [])
    if not identity:
        return "Colorless"
    return " / ".join(COLOR_NAMES.get(c, c) for c in identity)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    command = sys.argv[1]
    if command == "card":
        print(json.dumps(summarise(card(sys.argv[2])), indent=2))
    elif command == "newest-set":
        s = newest_set()
        print(json.dumps({k: s[k] for k in ("name", "code", "released_at", "card_count")}, indent=2))
    elif command == "search":
        for c in search(sys.argv[2]):
            print("%-34s %-28s %s" % (c["name"], c.get("type_line", "")[:28], price_eur(c)))
    else:
        raise SystemExit("unknown command %r" % command)
