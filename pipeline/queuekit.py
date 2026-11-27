#!/usr/bin/env python3
"""
The queue as a state machine, shared by approve.py and daily.py.

A post folder moves through three states, each recorded by one file in it:

    queued     editorial.json + caption.txt exist
    approved   approved.json exists and its fingerprint still matches
    rejected   rejected.json exists and its fingerprint still matches
    published  published.json exists — never touched again

Approved and rejected are mutually exclusive: recording one removes the other.

Approval fingerprints the *editorial* files, not the rendered slides. The slides
are rebuilt on the morning of publication so prices are current, which changes
their bytes every day; what a human approved is the words. Edit the hook or the
caption after approving and the approval is void until you approve again.
"""

import sys

if sys.version_info < (3, 8):
    raise SystemExit(
        "EDHPod needs Python 3.8 or newer; this is %d.%d. On this machine use:\n"
        "  /work/u19d26/miniforge3/envs/pygem3.9/bin/python3 <script>" % sys.version_info[:2]
    )

import datetime
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUEUE = HERE.parent / "queue"

# Format -> number of slides. Content posts are 3-slide carousels; the
# welcome post that carries the Fan Content disclaimer is a single image.
SLIDE_COUNT = {
    "card-of-the-day": 3,
    "budget-combo": 3,
    "introduction": 3,
    "welcome": 1,
}
FORMATS = tuple(SLIDE_COUNT)
FINGERPRINTED = ("editorial.json", "caption.txt")

# Must match the cron line in .github/workflows/daily-post.yml.
POST_HOUR_UTC = 17


def today_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def utc_hour() -> int:
    return datetime.datetime.now(datetime.timezone.utc).hour


def now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_of(folder: Path) -> str:
    for name in FORMATS:
        if folder.name.endswith(name):
            return name
    raise SystemExit("%s does not end in one of %s" % (folder.name, ", ".join(FORMATS)))


def slide_count(folder: Path) -> int:
    return SLIDE_COUNT[format_of(folder)]


def date_of(folder: Path) -> str:
    return folder.name[:10]


def all_posts() -> list:
    return sorted(
        f for f in QUEUE.iterdir()
        if f.is_dir() and (f / "editorial.json").exists()
    )


def find(selector: str) -> Path:
    """
    Resolve a date (2026-11-27), a folder name, or a path to exactly one post.
    Two posts on one date is a scheduling mistake and fails rather than guessing.
    """
    candidate = Path(selector)
    if candidate.is_dir() and (candidate / "editorial.json").exists():
        return candidate.resolve()
    matches = [f for f in all_posts() if f.name == selector or date_of(f) == selector]
    if not matches:
        raise SystemExit("No queued post for %s" % selector)
    if len(matches) > 1:
        raise SystemExit(
            "%d posts are queued for %s (%s) — one per day"
            % (len(matches), selector, ", ".join(m.name for m in matches))
        )
    return matches[0]


def fingerprint(folder: Path) -> str:
    digest = hashlib.sha256()
    for name in FINGERPRINTED:
        path = folder / name
        if not path.exists():
            raise SystemExit("%s is missing %s" % (folder.name, name))
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def status(folder: Path) -> str:
    """One of: published, approved, rejected, changed-since-approval, queued."""
    if (folder / "published.json").exists():
        return "published"
    current = fingerprint(folder)
    approval = read_json(folder / "approved.json")
    if approval:
        return "approved" if approval.get("fingerprint") == current else "changed-since-approval"
    rejection = read_json(folder / "rejected.json")
    if rejection and rejection.get("fingerprint") == current:
        return "rejected"
    # A rejected post that has since been edited is simply up for review again.
    return "queued"


def needs_review(folder: Path) -> bool:
    return status(folder) in ("queued", "changed-since-approval")


def approve(folder: Path, by: str) -> dict:
    record = {
        "approved_at": now_utc(),
        "approved_by": by,
        "fingerprint": fingerprint(folder),
        "fingerprinted_files": list(FINGERPRINTED),
    }
    write_json(folder / "approved.json", record)
    (folder / "rejected.json").unlink(missing_ok=True)
    return record


def reject(folder: Path, by: str, note: str = "") -> dict:
    record = {
        "rejected_at": now_utc(),
        "rejected_by": by,
        "fingerprint": fingerprint(folder),
        "note": note,
    }
    write_json(folder / "rejected.json", record)
    (folder / "approved.json").unlink(missing_ok=True)
    return record


def require_approved(folder: Path) -> dict:
    state = status(folder)
    if state == "approved":
        return read_json(folder / "approved.json")
    if state == "changed-since-approval":
        raise SystemExit(
            "%s was edited after it was approved. Review it again and re-run "
            "approve.py." % folder.name
        )
    if state == "published":
        raise SystemExit("%s is already published" % folder.name)
    if state == "rejected":
        raise SystemExit("%s was rejected" % folder.name)
    raise SystemExit("%s has not been approved — run approve.py %s" % (folder.name, date_of(folder)))


def approved_runway(after: str) -> int:
    """
    How many consecutive days after `after` already have an approved post.
    The number that says how long the channel survives if you stop working.
    """
    by_date = {date_of(f): f for f in all_posts()}
    day = datetime.date.fromisoformat(after)
    count = 0
    while True:
        day += datetime.timedelta(days=1)
        folder = by_date.get(day.isoformat())
        if not folder or status(folder) != "approved":
            return count
        count += 1
