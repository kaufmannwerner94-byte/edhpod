#!/usr/bin/env python3
"""
EDHPod slide renderer.

Takes a post JSON file and writes slide1.jpg / slide2.jpg / slide3.jpg next to it.

    python3 render.py ../queue/2026-12-01-card-of-the-day/post.json

Everything Instagram cares about is asserted rather than assumed: output is
exactly 1080x1350 (which is exactly 4:5, the edge of Instagram's permitted
range), JPEG, sRGB, under 8 MB, and all three slides are identical in size so
the carousel does not crop slides 2 and 3 to match slide 1.
"""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
FONTS = HERE / "fonts"

WIDTH, HEIGHT = 1080, 1350
JPEG_QUALITY = 90
MAX_BYTES = 8 * 1024 * 1024

# Which template each slide of each format uses. Slide 3 is shared.
SLIDES = {
    "card-of-the-day": ["card-of-the-day.1.html", "card-of-the-day.2.html", "cta.3.html"],
    "budget-combo": ["budget-combo.1.html", "budget-combo.2.html", "cta.3.html"],
    "introduction": ["introduction.1.html", "introduction.2.html", "cta.3.html"],
    "welcome": ["welcome.1.html"],
}


def find_browser():
    """
    Locate the Chromium headless shell, preferring an explicit override.

    Returns None when nothing is found in the known places, which lets
    Playwright use the browser it installed itself. That is the normal case on
    the GitHub Actions runner, where `playwright install` puts the browser in a
    directory layout that changes between Playwright releases.
    """
    env = os.environ.get("EDHPOD_CHROMIUM")
    if env and Path(env).exists():
        return env
    roots = [
        Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")),
        Path.home() / ".cache" / "ms-playwright",
    ]
    for root in roots:
        if not root or not root.exists():
            continue
        for pat in ("chromium_headless_shell-*/chrome-linux/chrome-headless-shell",
                    "chromium-*/chrome-linux/chrome",
                    "chromium-*/chrome-linux64/chrome"):
            hits = sorted(root.glob(pat))
            if hits:
                return str(hits[-1])
    return None


# --------------------------------------------------------------------------
# Templating: {{token}} substitution plus comment-delimited repeat blocks.
# --------------------------------------------------------------------------

REPEAT_RE = r"<!--REPEAT:%s-->(.*?)<!--/REPEAT-->"
SEP_RE = r"<!--SEP:%s-->(.*?)<!--/SEP-->"


def esc(value) -> str:
    """HTML-escape, but keep <br> usable from content."""
    s = "" if value is None else str(value)
    s = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return s.replace("&lt;br&gt;", "<br>")


def fill(markup: str, data: dict) -> str:
    for key, value in data.items():
        if isinstance(value, (list, dict)):
            continue
        markup = markup.replace("{{%s}}" % key, esc(value))
    return markup


def expand_repeats(markup: str, data: dict) -> str:
    """Replace each REPEAT block with one copy per list item."""
    for key, value in data.items():
        if not isinstance(value, list):
            continue

        sep_match = re.search(SEP_RE % re.escape(key), markup, re.S)
        separator = ""
        if sep_match:
            separator = sep_match.group(1)
            markup = markup.replace(sep_match.group(0), "")

        block = re.search(REPEAT_RE % re.escape(key), markup, re.S)
        if not block:
            continue

        pieces = []
        for index, item in enumerate(value, start=1):
            item = dict(item) if isinstance(item, dict) else {"text": item}
            item.setdefault("i", index)
            pieces.append(fill(block.group(1), item))
        markup = markup.replace(block.group(0), separator.join(pieces))
    return markup


def leftover_tokens(markup: str) -> list:
    return sorted(set(re.findall(r"\{\{([a-z_0-9]+)\}\}", markup)))


DOCUMENT = """<!doctype html>
<html><head><meta charset="utf-8"><style>
@font-face {{ font-family:'Space Grotesk'; src:url('{grotesk}') format('truetype'); font-weight:100 900; font-style:normal; }}
@font-face {{ font-family:'Inter'; src:url('{inter}') format('truetype'); font-weight:100 900; font-style:normal; }}
html,body {{ margin:0; padding:0; background:#11131C; }}
* {{ -webkit-font-smoothing:antialiased; }}
</style></head><body>{body}</body></html>
"""


def document(body: str) -> str:
    """Fonts are referenced as absolute file:// URIs so the scratch page can be
    written to the VM's temp dir rather than into the user's folder, which does
    not permit deleting files."""
    return DOCUMENT.format(
        body=body,
        grotesk=(FONTS / "SpaceGrotesk.ttf").as_uri(),
        inter=(FONTS / "Inter.ttf").as_uri(),
    )

# Shrink text that would otherwise overflow. Runs twice: once per-element for
# things like a long card name on a single line, then globally if the slide as
# a whole is taller than 1350px. Generated content varies in length far more
# than a hand-made design does, so this is the difference between a template
# that works and one that works most days.
AUTOFIT_JS = """() => {
  const H = %d;
  const nodes = [...document.querySelectorAll('[data-autofit]')].map(el => ({
    el, min: parseFloat(el.dataset.autofit) || 20,
    size: parseFloat(getComputedStyle(el).fontSize)
  }));
  const overflowsX = el => el.scrollWidth > el.clientWidth + 1;
  for (const n of nodes) {
    let guard = 200;
    while (overflowsX(n.el) && n.size > n.min && guard-- > 0) {
      n.size -= 1; n.el.style.fontSize = n.size + 'px';
    }
  }
  const root = document.body.firstElementChild;
  const tooTall = () => root.scrollHeight > H + 1;
  let guard = 400;
  while (tooTall() && guard-- > 0) {
    const shrinkable = nodes.filter(n => n.size > n.min);
    if (!shrinkable.length) break;
    for (const n of shrinkable) { n.size -= 1; n.el.style.fontSize = n.size + 'px'; }
  }
  return { overflow: root.scrollHeight - H,
           shrunk: nodes.filter(n => n.size < parseFloat(n.el.dataset.initial || n.size) ).length };
}"""


def render_post(post_path: Path) -> list:
    post = json.loads(post_path.read_text(encoding="utf-8"))
    outdir = post_path.parent
    fmt = post["format"]
    if fmt not in SLIDES:
        raise SystemExit("Unknown format %r. Expected one of %s" % (fmt, list(SLIDES)))

    slides = post["slides"]
    if len(slides) != len(SLIDES[fmt]):
        raise SystemExit("Expected %d slides for %s, got %d" % (len(SLIDES[fmt]), fmt, len(slides)))

    # Card images must be local files; Chromium reads them over file://.
    for slide in slides:
        for key in ("card_image",):
            if key in slide:
                slide[key] = Path(slide[key]).resolve().as_uri()
        for item in [v for v in slide.values() if isinstance(v, list)]:
            for entry in item:
                if isinstance(entry, dict) and "image" in entry:
                    entry["image"] = Path(entry["image"]).resolve().as_uri()

    written, warnings = [], []
    browser_path = find_browser()
    scratch_dir = tempfile.mkdtemp(prefix="edhpod-render-")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=browser_path,  # None: Playwright's own install
            args=["--no-sandbox", "--disable-dev-shm-usage", "--force-color-profile=srgb"],
        )
        page = browser.new_page(
            viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1
        )

        for index, (template_name, slide) in enumerate(zip(SLIDES[fmt], slides), start=1):
            markup = (TEMPLATES / template_name).read_text(encoding="utf-8")
            markup = expand_repeats(markup, slide)
            markup = fill(markup, slide)

            missing = leftover_tokens(markup)
            if missing:
                warnings.append("slide%d has unfilled tokens: %s" % (index, ", ".join(missing)))

            scratch = Path(scratch_dir) / ("slide%d.html" % index)
            scratch.write_text(document(markup), encoding="utf-8")
            page.goto(scratch.as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            page.wait_for_function(
                "() => [...document.images].every(i => i.complete && i.naturalWidth > 0)"
            )
            info = page.evaluate(AUTOFIT_JS % HEIGHT)
            if info["overflow"] > 1:
                warnings.append(
                    "slide%d still overflows by %dpx after auto-fit" % (index, info["overflow"])
                )

            target = outdir / ("slide%d.jpg" % index)
            page.screenshot(path=str(target), type="jpeg", quality=JPEG_QUALITY, full_page=False)
            written.append(target)

        browser.close()
    shutil.rmtree(scratch_dir, ignore_errors=True)

    verify(written, warnings)
    return written


def verify(paths: list, warnings: list) -> None:
    """Fail loudly on anything Instagram would reject or silently crop."""
    sizes = set()
    for path in paths:
        with Image.open(path) as im:
            if im.format != "JPEG":
                raise SystemExit("%s is %s, must be JPEG" % (path.name, im.format))
            if im.size != (WIDTH, HEIGHT):
                raise SystemExit(
                    "%s is %dx%d, must be exactly %dx%d (4:5 is the edge of the "
                    "permitted range, so any drift is rejected)"
                    % (path.name, im.size[0], im.size[1], WIDTH, HEIGHT)
                )
            if im.mode != "RGB":
                raise SystemExit("%s is mode %s, must be RGB" % (path.name, im.mode))
            sizes.add(im.size)
        if path.stat().st_size > MAX_BYTES:
            raise SystemExit("%s exceeds Instagram's 8 MB limit" % path.name)

    if len(sizes) != 1:
        raise SystemExit("Slides differ in size %s — carousel would crop them" % sizes)

    for line in warnings:
        print("  warning: %s" % line)
    print("  verified: %d slides, %dx%d, JPEG, RGB, all identical size"
          % (len(paths), WIDTH, HEIGHT))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: render.py <path to post.json>")
    for out in render_post(Path(sys.argv[1])):
        print("  wrote %s (%.0f KB)" % (out.name, out.stat().st_size / 1024))
