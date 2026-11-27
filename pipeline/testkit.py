"""
Self-contained post folders for the tests.

The tests must never depend on what happens to be in queue/: folders get
renamed by reschedule.py, published, and eventually run out, and the daily
workflow runs the tests before every publish.
"""

import json
from pathlib import Path

from PIL import Image

DISCLAIMER = "Unofficial Fan Content. Not approved/endorsed by Wizards of the Coast."
WELCOME_DISCLAIMER = (
    "EDHPod is unofficial Fan Content permitted under the Fan Content Policy. "
    "Not approved/endorsed by Wizards. Portions of the materials used are "
    "property of Wizards of the Coast. ©Wizards of the Coast LLC."
)


def make_post(queue: Path, name: str) -> Path:
    """A post folder named like the real ones, e.g. 2026-11-28-card-of-the-day."""
    folder = queue / name
    folder.mkdir(parents=True)
    welcome = name.endswith("-welcome")
    count = 1 if welcome else 3
    if welcome:
        caption = "Welcome to EDHPod\n\nPrices are daily estimates.\n\n%s\n\n#mtg #edh" % WELCOME_DISCLAIMER
    else:
        caption = ("Lotus Cobra turns every land into two mana. (%s)\n\nPrices are daily "
                   "estimates (Cardmarket via Scryfall).\n%s\n\n#mtg #edh" % (name, DISCLAIMER))
    (folder / "editorial.json").write_text(json.dumps({"card": "Lotus Cobra", "for": name}))
    (folder / "caption.txt").write_text(caption, encoding="utf-8")
    (folder / "facts.json").write_text(json.dumps({"cards": []}))
    (folder / "alt.json").write_text(json.dumps(["alt %d" % i for i in range(1, count + 1)]))
    for i in range(1, count + 1):
        Image.new("RGB", (1080, 1350), "#11131C").save(folder / ("slide%d.jpg" % i), "JPEG")
    return folder
