#!/usr/bin/env python3
"""
The parts of the COMPLIANCE.md checklist that a machine can check.

    python3 checks.py ../queue/2026-11-27-card-of-the-day

The rest — is the combo real, is the image unmodified, is the take honest — is
what approval is for. This file makes sure the human never has to spend
attention on the things a script catches.
"""

import calendar
import json
import re
import sys
import time
from pathlib import Path

from PIL import Image

import queuekit

WIDTH, HEIGHT = 1080, 1350
MAX_BYTES = 8 * 1024 * 1024
CAPTION_MAX = 2200
HASHTAGS_MAX = 30
MENTIONS_MAX = 20
ALT_MAX = 1000
# Half of Scryfall's "dangerously stale after 24 hours", as in postkit.
PRICE_MAX_AGE_HOURS = 12

DISCLAIMER = "Not approved/endorsed by Wizards"
PRICE_NOTE = "estimates"

# Universes Beyond set-name prefix -> words the caption must then contain.
# COMPLIANCE.md: a UB card image needs the third-party acknowledgement.
UB_ACKNOWLEDGEMENTS = {
    "Star Trek": "CBS Studios",
}


def _walk(value, key):
    """Every value stored under `key` anywhere in a nested structure."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v, key)


def caption_problems(caption: str) -> list:
    problems = []
    if not caption.strip():
        return ["caption is empty"]
    if len(caption) > CAPTION_MAX:
        problems.append("caption is %d characters, limit %d" % (len(caption), CAPTION_MAX))
    tags = re.findall(r"(?<!\w)#\w+", caption)
    if len(tags) > HASHTAGS_MAX:
        problems.append("caption has %d hashtags, limit %d" % (len(tags), HASHTAGS_MAX))
    mentions = re.findall(r"(?<!\w)@[\w.]+", caption)
    if len(mentions) > MENTIONS_MAX:
        problems.append("caption has %d @-mentions, limit %d" % (len(mentions), MENTIONS_MAX))
    if DISCLAIMER not in caption:
        problems.append("caption lacks the Wizards disclaimer line (%r)" % DISCLAIMER)
    if PRICE_NOTE not in caption:
        problems.append("caption does not call prices estimates")
    return problems


def ub_problems(caption: str, facts) -> list:
    problems = []
    sets = {s for s in _walk(facts, "set_name") if isinstance(s, str)}
    sets |= {s.get("name") for s in _walk(facts, "set") if isinstance(s, dict)}
    for prefix, words in UB_ACKNOWLEDGEMENTS.items():
        if any(s and s.startswith(prefix) for s in sets) and words not in caption:
            problems.append(
                "a card is from %s (Universes Beyond) but the caption lacks the "
                "acknowledgement mentioning %s" % (prefix, words)
            )
    return problems


def freshness_problems(facts) -> list:
    problems = []
    now = time.time()
    for stamp in set(_walk(facts, "retrieved_at")) | set(_walk(facts, "_fetched_at")):
        if not stamp:
            problems.append("a card in facts.json has no retrieval timestamp")
            continue
        age = (now - calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))) / 3600
        if age > PRICE_MAX_AGE_HOURS:
            problems.append("Scryfall data is %.1f hours old (limit %d)" % (age, PRICE_MAX_AGE_HOURS))
            break
    return problems


def slide_problems(folder: Path, count: int = 3) -> list:
    problems, sizes = [], set()
    for i in range(1, count + 1):
        path = folder / ("slide%d.jpg" % i)
        if not path.exists():
            problems.append("%s is missing" % path.name)
            continue
        with Image.open(path) as im:
            if im.format != "JPEG":
                problems.append("%s is %s, must be JPEG" % (path.name, im.format))
            if im.mode != "RGB":
                problems.append("%s is mode %s, must be RGB" % (path.name, im.mode))
            if im.size != (WIDTH, HEIGHT):
                problems.append("%s is %dx%d, must be %dx%d" % ((path.name,) + im.size + (WIDTH, HEIGHT)))
            sizes.add(im.size)
        if path.stat().st_size > MAX_BYTES:
            problems.append("%s is over 8 MB" % path.name)
    if len(sizes) > 1:
        problems.append("slides differ in size %s — the carousel would crop them" % sizes)
    return problems


def alt_problems(folder: Path, count: int = 3) -> list:
    path = folder / "alt.json"
    if not path.exists():
        return ["alt.json is missing — run alttext.py"]
    texts = json.loads(path.read_text(encoding="utf-8"))
    if len(texts) != count:
        return ["alt.json has %d entries, expected %d" % (len(texts), count)]
    return [
        "alt text %d is %s" % (i, "empty" if not t.strip() else "%d chars, limit %d" % (len(t), ALT_MAX))
        for i, t in enumerate(texts, start=1)
        if not t.strip() or len(t) > ALT_MAX
    ]


def run(folder: Path, publish_time: bool = True) -> list:
    """
    All problems with a post. `publish_time=False` skips the price-age and
    alt-text checks, which only make sense right before publishing, when the
    post has just been rebuilt.
    """
    caption = (folder / "caption.txt").read_text(encoding="utf-8")
    facts = json.loads((folder / "facts.json").read_text(encoding="utf-8"))
    count = queuekit.slide_count(folder)
    problems = caption_problems(caption) + ub_problems(caption, facts) + slide_problems(folder, count)
    if publish_time:
        problems += freshness_problems(facts) + alt_problems(folder, count)
    return problems


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: checks.py <post folder>")
    found = run(Path(sys.argv[1]))
    for p in found:
        print("  FAIL  %s" % p)
    print("  %d problem(s)" % len(found))
    sys.exit(1 if found else 0)
