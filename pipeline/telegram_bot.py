#!/usr/bin/env python3
"""
Approve posts from your phone via a Telegram bot.

The bot sends each post that needs review as an album of its rendered slides,
followed by the caption with ✅ Approve / ❌ Reject buttons. Your taps are picked up
by the "Approvals" workflow, which runs every 15 minutes and commits the decision
to the repo as approved.json / rejected.json — exactly what approve.py writes.

    python3 telegram_bot.py whoami            # setup: show the bot and your chat id
    python3 telegram_bot.py poll              # apply button taps and commands
    python3 telegram_bot.py ack --offset N    # confirm processed updates to Telegram
    python3 telegram_bot.py pending           # how many posts need a preview
    python3 telegram_bot.py send              # render and send those previews
    python3 telegram_bot.py notify "text"     # send a message

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Only messages and taps from that
one chat are acted on; anything else that reaches the bot is ignored.

Commands you can send the bot:
    /status           what's queued, approved, published
    /preview <date>   send a post's preview again
    any other text    after a rejection: saved as the note on what to change

`poll` and `ack` are separate on purpose. Telegram forgets an update once it is
acknowledged, so the workflow acknowledges only after the decision has been
pushed to GitHub. If the push fails, the next run sees the same taps again, and
applying a decision twice is harmless.
"""

import argparse
import datetime
import getpass
import json
import os
import sys
from pathlib import Path

import requests

import queuekit

API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
MAX_OPEN_PREVIEWS = 5     # previews waiting for an answer at any one time
STATUS_MARK = "\n\n▶ "    # separates a preview's text from the decision line

LABELS = {
    "card-of-the-day": "Card of the Day",
    "budget-combo": "Budget Combo",
    "introduction": "Introduction",
    "welcome": "Welcome post (pin it after it goes live)",
}
HELP = (
    "EDHPod approvals.\n\n"
    "New posts arrive here as previews with Approve / Reject buttons. Your answer "
    "is picked up within about 15 minutes.\n\n"
    "/status: what's queued, approved, published\n"
    "/preview YYYY-MM-DD: send a preview again\n"
    "After rejecting, just type what should change and it is saved with the post."
)


class Telegram:
    def __init__(self, token: str, chat_id: str, session=None):
        if not token or not chat_id:
            raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        self.token, self.chat_id = token, str(chat_id)
        self.http = session or requests.Session()

    def call(self, method: str, files=None, **params):
        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                for k, v in params.items() if v is not None}
        try:
            response = self.http.post(
                "%s/bot%s/%s" % (API_BASE, self.token, method), data=data, files=files, timeout=120
            )
            body = response.json()
        except (requests.RequestException, ValueError) as error:
            # The URL contains the bot token.
            raise RuntimeError("Telegram %s failed: %s" % (method, str(error).replace(self.token, "***"))) from None
        if not body.get("ok"):
            raise RuntimeError("Telegram %s: %s" % (method, body.get("description")))
        return body["result"]

    def send(self, text: str, buttons=None, reply_to=None) -> dict:
        return self.call(
            "sendMessage", chat_id=self.chat_id, text=text[:4096],
            reply_markup={"inline_keyboard": buttons} if buttons else None,
            reply_to_message_id=reply_to, disable_web_page_preview=True,
        )

    def send_images(self, paths: list) -> None:
        if len(paths) == 1:
            with open(paths[0], "rb") as handle:
                self.call("sendPhoto", chat_id=self.chat_id, files={"photo": handle})
            return
        handles = {"s%d" % i: open(p, "rb") for i, p in enumerate(paths, start=1)}
        try:
            media = [{"type": "photo", "media": "attach://%s" % k} for k in handles]
            self.call("sendMediaGroup", chat_id=self.chat_id, media=media, files=handles)
        finally:
            for handle in handles.values():
                handle.close()


def client() -> Telegram:
    return Telegram(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""))


def output(**values) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    for key, value in values.items():
        print("  output %s=%s" % (key, value))
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write("%s=%s\n" % (key, value))


# ---------------------------------------------------------------- previews

def nice_date(date: str) -> str:
    return datetime.date.fromisoformat(date).strftime("%a %d %b %Y")


def decision_buttons(folder: Path, offer=("approve", "reject")) -> list:
    tag = "%s:%s" % (queuekit.date_of(folder), queuekit.fingerprint(folder)[:16])
    labels = {"approve": ("✅ Approve", "a"), "reject": ("❌ Reject", "r")}
    if len(offer) == 1:
        labels = {"approve": ("↩️ Approve instead", "a"), "reject": ("↩️ Reject instead", "r")}
    return [[{"text": labels[o][0], "callback_data": "%s:%s" % (labels[o][1], tag)} for o in offer]]


def preview_text(folder: Path) -> str:
    caption = (folder / "caption.txt").read_text(encoding="utf-8").strip()
    date = queuekit.date_of(folder)
    when = ("Goes live %02d:00 UTC" % queuekit.POST_HOUR_UTC if date >= queuekit.today_utc()
            else "This date has passed. Approve now, reschedule later.")
    return "📅 %s · %s\n%s\n\n%s" % (
        nice_date(date), LABELS[queuekit.format_of(folder)], when, caption)


def open_previews() -> int:
    count = 0
    for folder in queuekit.all_posts():
        preview = queuekit.read_json(folder / "preview.json")
        if (preview and not preview.get("error") and queuekit.needs_review(folder)
                and preview.get("fingerprint") == queuekit.fingerprint(folder)):
            count += 1
    return count


def due_for_preview() -> list:
    """Posts awaiting review that have no current preview, oldest first, capped
    so the chat never holds more than MAX_OPEN_PREVIEWS open questions. Posts
    whose date has passed are included: an approval survives reschedule.py."""
    due = []
    for folder in queuekit.all_posts():
        if not queuekit.needs_review(folder):
            continue
        preview = queuekit.read_json(folder / "preview.json")
        if preview and preview.get("fingerprint") == queuekit.fingerprint(folder):
            continue  # already sent (or already reported as unbuildable)
        due.append(folder)
    return due[: max(0, MAX_OPEN_PREVIEWS - open_previews())]


def send_previews(tg: Telegram) -> int:
    import daily  # needs Playwright, so only imported when rendering

    sent = 0
    for folder in due_for_preview():
        print("preview   %s" % folder.name)
        fingerprint = queuekit.fingerprint(folder)
        try:
            daily.rebuild(folder)
        except BaseException as error:  # SystemExit is how the build gates fail
            if isinstance(error, KeyboardInterrupt):
                raise
            tg.send("⚠️ %s can't be built, so there is nothing to approve yet:\n\n%s\n\n"
                    "It needs fixing in the editorial files." % (folder.name, error))
            queuekit.write_json(folder / "preview.json", {
                "fingerprint": fingerprint, "sent_at": queuekit.now_utc(), "error": str(error)})
            continue
        slides = [folder / ("slide%d.jpg" % i) for i in range(1, queuekit.slide_count(folder) + 1)]
        tg.send_images(slides)
        message = tg.send(preview_text(folder), buttons=decision_buttons(folder))
        queuekit.write_json(folder / "preview.json", {
            "fingerprint": fingerprint, "sent_at": queuekit.now_utc(),
            "message_id": message["message_id"],
        })
        sent += 1
    return sent


# ---------------------------------------------------------------- decisions

def overview() -> str:
    today = queuekit.today_utc()
    marks = {"published": "✓", "approved": "●", "rejected": "✗",
             "changed-since-approval": "!", "queued": "○"}
    lines = []
    for folder in queuekit.all_posts():
        date = queuekit.date_of(folder)
        state = queuekit.status(folder)
        if date < today and state != "published":
            state_note = " (date passed, needs rescheduling)"
        else:
            state_note = ""
        if date >= today or state_note:
            lines.append("%s %s %s%s" % (marks[state], datetime.date.fromisoformat(date).strftime("%a %d %b"),
                                         LABELS[queuekit.format_of(folder)].split(" (")[0], state_note))
    yesterday = (datetime.date.fromisoformat(today) - datetime.timedelta(days=1)).isoformat()
    runway = queuekit.approved_runway(yesterday)
    return ("%s\n\n%d day(s) approved from today.\n● approved  ○ needs review  ✗ rejected  ✓ published"
            % ("\n".join(lines) or "The queue is empty.", runway))


def handle_callback(tg: Telegram, cq: dict, result: dict) -> None:
    action, date, tag = cq.get("data", "::").split(":", 2)
    message = cq.get("message") or {}
    base_text = (message.get("text") or "").split(STATUS_MARK)[0]
    who = "telegram:%s" % ((cq.get("from") or {}).get("username") or (cq.get("from") or {}).get("id"))

    def answer(text):
        try:
            tg.call("answerCallbackQuery", callback_query_id=cq["id"], text=text)
        except RuntimeError:
            pass  # old queries cannot be answered; the edited message says it all

    def edit(status_line, buttons):
        try:
            tg.call("editMessageText", chat_id=tg.chat_id, message_id=message.get("message_id"),
                    text=(base_text + STATUS_MARK + status_line)[:4096],
                    reply_markup={"inline_keyboard": buttons or []})
        except RuntimeError as error:
            if "not modified" not in str(error):
                raise

    try:
        folder = queuekit.find(date)
    except SystemExit:
        answer("That post no longer exists.")
        edit("This post is no longer in the queue.", None)
        return

    state = queuekit.status(folder)
    if state == "published":
        answer("Already published.")
        edit("Already published.", None)
        return
    if queuekit.fingerprint(folder)[:16] != tag:
        answer("This post changed since the preview. A new preview is on its way.")
        edit("Outdated preview: the post was edited. See the new preview.", None)
        (folder / "preview.json").unlink(missing_ok=True)
        result["changed"] = True
        return

    if action == "a":
        if state != "approved":
            queuekit.approve(folder, who)
            result["changed"] = True
        today = queuekit.today_utc()
        if date == today and queuekit.utc_hour() >= queuekit.POST_HOUR_UTC:
            note = "✅ Approved, publishing now (it was due at %02d:00 UTC)." % queuekit.POST_HOUR_UTC
            result["post_now"] = date
        elif date < today:
            note = "✅ Approved, but its date has passed. Run reschedule.py to give it a new day."
        else:
            note = "✅ Approved, goes live %s at %02d:00 UTC." % (nice_date(date), queuekit.POST_HOUR_UTC)
        answer("Approved")
        edit(note, decision_buttons(folder, offer=("reject",)))
    elif action == "r":
        if state != "rejected":
            queuekit.reject(folder, who)
            result["changed"] = True
        answer("Rejected")
        edit("❌ Rejected, will not be posted. Type what should change and I'll save it with the post.",
             decision_buttons(folder, offer=("approve",)))


def handle_message(tg: Telegram, msg: dict, result: dict) -> None:
    text = (msg.get("text") or "").strip()
    if not text:
        return
    command = text.split()[0].split("@")[0].lower()
    if command in ("/start", "/help"):
        tg.send(HELP)
    elif command == "/status":
        tg.send(overview())
    elif command == "/preview":
        parts = text.split()
        try:
            folder = queuekit.find(parts[1]) if len(parts) > 1 else None
        except SystemExit as error:
            tg.send(str(error))
            return
        if not folder:
            tg.send("Usage: /preview YYYY-MM-DD")
        elif queuekit.status(folder) == "published":
            tg.send("%s is already published." % folder.name)
        else:
            (folder / "preview.json").unlink(missing_ok=True)
            # A post that was already decided goes back to review.
            (folder / "approved.json").unlink(missing_ok=True)
            (folder / "rejected.json").unlink(missing_ok=True)
            result["changed"] = True
            tg.send("A fresh preview of %s is on its way. Any earlier decision on it is cleared." % folder.name)
    elif text.startswith("/"):
        tg.send(HELP)
    else:
        # Free text is feedback on the most recent rejection without a note.
        rejected = [
            (queuekit.read_json(f / "rejected.json"), f) for f in queuekit.all_posts()
            if queuekit.status(f) == "rejected"
        ]
        rejected = [(r, f) for r, f in rejected if not r.get("note")]
        if not rejected:
            tg.send("Got it, but there's no rejected post waiting for a note.\n\n" + HELP)
            return
        record, folder = max(rejected, key=lambda pair: pair[0].get("rejected_at", ""))
        record["note"] = text
        queuekit.write_json(folder / "rejected.json", record)
        result["changed"] = True
        tg.send("📝 Saved with %s. Ask Claude to revise it, then it comes back here for review."
                % folder.name)


def poll(tg: Telegram) -> dict:
    updates = tg.call("getUpdates", timeout=0, allowed_updates=["message", "callback_query"])
    result = {"changed": False, "post_now": "", "ack_offset": ""}
    for update in updates:
        result["ack_offset"] = update["update_id"] + 1
        try:
            if "callback_query" in update:
                cq = update["callback_query"]
                if str(((cq.get("message") or {}).get("chat") or {}).get("id")) == tg.chat_id:
                    handle_callback(tg, cq, result)
            elif "message" in update:
                msg = update["message"]
                if str((msg.get("chat") or {}).get("id")) == tg.chat_id:
                    handle_message(tg, msg, result)
        except Exception as error:  # one bad update must not block the rest
            print("::warning::update %s failed: %s" % (update.get("update_id"), error))
    print("processed %d update(s)" % len(updates))
    return result


# ---------------------------------------------------------------- CLI

def main() -> int:
    parser = argparse.ArgumentParser(description="EDHPod Telegram approvals")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("whoami")
    sub.add_parser("poll")
    ack = sub.add_parser("ack")
    ack.add_argument("--offset", required=True)
    sub.add_parser("pending")
    sub.add_parser("send")
    notify = sub.add_parser("notify")
    notify.add_argument("text")
    args = parser.parse_args()

    if args.command == "whoami":
        # Prompted rather than typed on the command line, so the token stays
        # out of shell history — and this works in tcsh as well as bash.
        token = os.environ.get("TELEGRAM_BOT_TOKEN") or getpass.getpass(
            "Paste the bot token from BotFather (input is hidden), then Enter: ").strip()
        tg = Telegram(token, "unknown")
        try:
            me = tg.call("getMe")
        except RuntimeError as error:
            if "Not Found" in str(error) or "Unauthorized" in str(error):
                raise SystemExit("Telegram rejected that token. Paste the whole line from "
                                 "BotFather, e.g. 7012345678:AAH... (digits, colon, letters).")
            raise
        print("bot: @%s" % me.get("username"))
        chats = {}
        for update in tg.call("getUpdates", timeout=0):
            msg = update.get("message") or {}
            chat = msg.get("chat") or {}
            if chat:
                chats[chat["id"]] = chat.get("username") or chat.get("first_name")
        if not chats:
            print("No messages yet. Open the bot in Telegram, press Start, then run this again.")
        for chat_id, name in chats.items():
            print("chat id: %s  (%s)  <- this is TELEGRAM_CHAT_ID" % (chat_id, name))
        return 0

    if args.command == "pending":
        due = due_for_preview()
        for folder in due:
            print("  due     %s" % folder.name)
        output(count=len(due))
        return 0

    tg = client()
    if args.command == "poll":
        result = poll(tg)
        output(changed=str(result["changed"]).lower(), post_now=result["post_now"],
               ack_offset=result["ack_offset"])
    elif args.command == "ack":
        if args.offset:
            tg.call("getUpdates", offset=int(args.offset), timeout=0, limit=1)
    elif args.command == "send":
        print("sent %d preview(s)" % send_previews(tg))
    elif args.command == "notify":
        tg.send(args.text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
