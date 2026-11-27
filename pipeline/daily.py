#!/usr/bin/env python3
"""
The daily publish job. Runs on GitHub Actions; see .github/workflows/daily-post.yml.

    python3 daily.py prepare [--date 2026-11-27] --site _site
    python3 daily.py publish --folder 2026-11-27-card-of-the-day \\
                             --base-url https://<you>.github.io/<repo> --path <dir> [--dry-run]

It is split in two because Meta cannot accept image uploads: it fetches each
slide from a public URL. Between the two steps the workflow deploys `_site/`
to GitHub Pages, which is that public URL.

prepare
    Finds today's post (UTC), refuses unless it is approved and unchanged
    since approval, rebuilds it from live Scryfall data so prices are current,
    re-renders the slides, writes alt text, runs checks.py, and copies the
    slides into the site directory under an unguessable path.

publish
    Waits until every slide URL actually serves the image (Pages takes up to
    a minute after deploy), then creates the carousel and publishes it, and
    writes published.json. A post with published.json is never touched again,
    which is what makes re-running the workflow safe.

Outputs for later workflow steps go to $GITHUB_OUTPUT when it is set.
"""

import argparse
import os
import secrets
import shutil
import sys
import time
from pathlib import Path

import requests

import alttext
import checks
import queuekit

HERE = Path(__file__).resolve().parent


def output(**values) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    for key, value in values.items():
        print("  output %s=%s" % (key, value))
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write("%s=%s\n" % (key, value))


def rebuild(folder: Path) -> None:
    """Rebuild from live Scryfall data and re-render. Prices must come from today."""
    os.environ["EDHPOD_NO_CACHE"] = "1"
    # Imported here so `publish` does not need Playwright installed.
    import build_all
    import render

    post_path = build_all.BUILDERS[queuekit.format_of(folder)](folder / "editorial.json")
    render.render_post(post_path)


def prepare(args) -> int:
    date = args.date or queuekit.today_utc()
    folder = queuekit.find(args.folder or date)
    print("post      %s" % folder.name)

    if queuekit.status(folder) == "published":
        print("already published — nothing to do")
        output(skip="true", reason="published", folder=folder.name)
        return 0

    state = queuekit.status(folder)
    if args.allow_unapproved:
        print("::warning::approval check skipped (--allow-unapproved); use only for dry runs")
    elif state != "approved":
        # Not an error: the workflow tells you on Telegram, and approving later
        # in the day publishes it straight away.
        reason = "rejected" if state == "rejected" else "unapproved"
        print("not publishing: post is %s (%s)" % (reason, state))
        output(skip="true", reason=reason, folder=folder.name)
        return 0
    else:
        approval = queuekit.read_json(folder / "approved.json")
        print("approved  %s by %s" % (approval.get("approved_at"), approval.get("approved_by")))

    if not args.no_rebuild:
        rebuild(folder)
    texts = alttext.build(folder)
    print("alt text  %s chars" % ", ".join(str(len(t)) for t in texts))

    problems = checks.run(folder, publish_time=not args.no_rebuild)
    if problems:
        for problem in problems:
            print("::error::%s: %s" % (folder.name, problem))
        return 1
    print("checks    all passed")

    # An unguessable directory: the site is public, and a fresh path every day
    # means no CDN can serve yesterday's slide under today's name.
    path = "%s-%s" % (queuekit.date_of(folder), secrets.token_hex(12))
    site = Path(args.site)
    if site.exists():
        shutil.rmtree(site)
    (site / path).mkdir(parents=True)
    for i in range(1, queuekit.slide_count(folder) + 1):
        shutil.copy2(folder / ("slide%d.jpg" % i), site / path / ("slide%d.jpg" % i))
    (site / "index.html").write_text("<!doctype html><title>EDHPod</title>\n", encoding="utf-8")
    (site / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    output(skip="false", reason="", folder=folder.name, path=path)
    return 0


def wait_for_urls(urls: list, timeout: int = 600) -> None:
    """GitHub Pages serves a new deploy after seconds to a minute. Meta must
    not be asked to fetch a URL that still 404s."""
    deadline = time.time() + timeout
    pending = list(urls)
    while pending:
        url = pending[0]
        try:
            response = requests.head(url, timeout=30, allow_redirects=True)
            ok = response.status_code == 200 and response.headers.get(
                "content-type", "").startswith("image/jpeg")
        except requests.RequestException:
            ok = False
        if ok:
            print("  live    %s" % url)
            pending.pop(0)
            continue
        if time.time() > deadline:
            raise SystemExit("%s is still not being served after %ds" % (url, timeout))
        time.sleep(10)


def publish(args) -> int:
    from instagram import Instagram  # noqa: E402 — keeps `prepare` free of the token

    folder = queuekit.find(args.folder)
    if queuekit.status(folder) == "published":
        print("%s is already published" % folder.name)
        return 0
    if not args.dry_run:
        queuekit.require_approved(folder)

    caption = (folder / "caption.txt").read_text(encoding="utf-8").strip()
    alts = queuekit.read_json(folder / "alt.json")
    base = args.base_url.rstrip("/")
    urls = ["%s/%s/slide%d.jpg" % (base, args.path, i)
            for i in range(1, queuekit.slide_count(folder) + 1)]

    wait_for_urls(urls)

    ig = Instagram(os.environ.get("IG_ACCESS_TOKEN", ""))
    me = ig.me()
    print("account   @%s (%s)" % (me.get("username"), me.get("account_type")))
    expected = os.environ.get("IG_EXPECTED_USERNAME")
    if expected and me.get("username") != expected:
        raise SystemExit("token belongs to @%s, expected @%s" % (me.get("username"), expected))

    # Belt and braces for re-runs: if this exact caption is already in the
    # feed, the post went out on an earlier attempt that died before it could
    # write published.json.
    existing = ig.find_by_caption(caption)
    if existing:
        print("this caption is already on the feed: %s" % existing.get("permalink"))
        record(folder, existing["id"], existing.get("permalink", ""), None, urls, recovered=True)
        return 0

    if len(urls) == 1:
        carousel = ig.create_image(urls[0], caption, alts[0])
    else:
        children = []
        for url, alt in zip(urls, alts):
            child = ig.create_carousel_item(url, alt)
            ig.wait_until_ready(child)
            print("  child   %s" % child)
            children.append(child)
        carousel = ig.create_carousel(children, caption)
    ig.wait_until_ready(carousel)
    print("container %s ready" % carousel)

    if args.dry_run:
        print("DRY RUN — post built and accepted by Meta, not published. "
              "It expires unused in 24 hours.")
        return 0

    media_id = ig.publish(carousel, caption)
    link = ""
    try:
        link = ig.permalink(media_id)
    except Exception as error:  # the post is out; a missing link is cosmetic
        print("  could not fetch permalink: %s" % error)
    record(folder, media_id, link, carousel, urls)
    print("PUBLISHED %s" % (link or media_id))

    runway = queuekit.approved_runway(queuekit.date_of(folder))
    print("runway    %d more day(s) approved and queued" % runway)
    if runway < 3:
        print("::warning::Only %d approved post(s) queued after %s — approve more soon."
              % (runway, queuekit.date_of(folder)))
    output(permalink=link or media_id, runway=runway)
    return 0


def record(folder, media_id, permalink, container_id, urls, recovered=False) -> None:
    queuekit.write_json(folder / "published.json", {
        "published_at": queuekit.now_utc(),
        "media_id": media_id,
        "permalink": permalink,
        "container_id": container_id,
        "image_urls": urls,
        "recovered_from_feed": recovered,
        "workflow_run": os.environ.get("GITHUB_RUN_ID"),
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="EDHPod daily publish job")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare", help="rebuild, check and stage today's post")
    p.add_argument("--date", default="", help="YYYY-MM-DD, default today in UTC")
    p.add_argument("--folder", default="", help="post folder name, overrides --date")
    p.add_argument("--site", required=True, help="directory to stage the public slides in")
    p.add_argument("--allow-unapproved", action="store_true", help="for dry runs only")
    p.add_argument("--no-rebuild", action="store_true",
                   help="use the slides already on disk (local testing only)")

    q = sub.add_parser("publish", help="publish a prepared post")
    q.add_argument("--folder", required=True)
    q.add_argument("--base-url", required=True, help="the GitHub Pages URL")
    q.add_argument("--path", required=True, help="the directory prepare staged the slides in")
    q.add_argument("--dry-run", action="store_true", help="build the carousel but do not publish")

    args = parser.parse_args()
    return prepare(args) if args.command == "prepare" else publish(args)


if __name__ == "__main__":
    sys.exit(main())
