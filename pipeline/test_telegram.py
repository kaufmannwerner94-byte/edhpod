#!/usr/bin/env python3
"""
Tests the Telegram approval flow against a fake Telegram Bot API, locally.

    python3 test_telegram.py

Covers: previews are sent once and capped, taps approve / reject, an outdated
preview cannot approve edited content, taps from strangers are ignored, notes
after a rejection are stored, and a late approval of today's post asks for an
immediate publish.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN, CHAT = "123:fake", "4242"
CALLS, UPDATES = [], []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        assert self.path.startswith("/bot%s/" % TOKEN)
        method = self.path.rsplit("/", 1)[1]
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        ctype = self.headers.get("Content-Type", "")
        params = dict(urllib.parse.parse_qsl(raw.decode())) if "urlencoded" in ctype else {"multipart": True}
        CALLS.append((method, params))
        result = True
        if method == "getUpdates":
            offset = int(params.get("offset", 0))
            result = [u for u in UPDATES if u["update_id"] >= offset]
        elif method in ("sendMessage", "sendPhoto"):
            result = {"message_id": len(CALLS)}
        elif method == "sendMediaGroup":
            result = [{"message_id": len(CALLS)}]
        body = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TelegramTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        os.environ.update(TELEGRAM_API_BASE="http://127.0.0.1:%d" % cls.server.server_address[1],
                          TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID=CHAT)
        os.environ.pop("GITHUB_OUTPUT", None)
        sys.path.insert(0, str(HERE))
        import daily
        import queuekit
        import telegram_bot
        cls.qk, cls.bot = queuekit, telegram_bot
        daily.rebuild = lambda folder: None  # slides already exist in the copies

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        CALLS.clear()
        UPDATES.clear()
        self.tmp = Path(tempfile.mkdtemp())
        self.qk.QUEUE = self.tmp
        self.qk.today_utc = lambda: "2026-11-28"
        self.qk.utc_hour = lambda: 10
        import testkit
        for name in ("2026-11-28-budget-combo", "2026-11-29-card-of-the-day", "2026-11-26-welcome"):
            testkit.make_post(self.tmp, name)
        self.tg = self.bot.client()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def methods(self):
        return [m for m, _ in CALLS]

    def tap(self, data, chat=CHAT, update_id=1):
        UPDATES.append({"update_id": update_id, "callback_query": {
            "id": "q%d" % update_id, "data": data, "from": {"id": int(chat), "username": "me"},
            "message": {"message_id": 99, "chat": {"id": int(chat)}, "text": "preview text"}}})

    def say(self, text, update_id=1, chat=CHAT):
        UPDATES.append({"update_id": update_id, "message": {"chat": {"id": int(chat)}, "text": text}})

    def tag(self, name):
        folder = self.tmp / name
        return "%s:%s" % (self.qk.date_of(folder), self.qk.fingerprint(folder)[:16])

    # ------------------------------------------------------------------ previews

    def test_previews_sent_once_with_buttons(self):
        self.assertEqual(self.bot.send_previews(self.tg), 3)
        self.assertEqual(self.methods().count("sendMediaGroup"), 2)  # two carousels
        self.assertEqual(self.methods().count("sendPhoto"), 1)       # the welcome image
        texts = [p for m, p in CALLS if m == "sendMessage"]
        markup = json.loads(texts[0]["reply_markup"])
        self.assertEqual([b["callback_data"][0] for b in markup["inline_keyboard"][0]], ["a", "r"])
        self.assertIn("This date has passed", texts[0]["text"])      # welcome is dated 11-26
        CALLS.clear()
        self.assertEqual(self.bot.send_previews(self.tg), 0)
        self.assertEqual(CALLS, [])

    def test_open_previews_are_capped(self):
        self.bot.MAX_OPEN_PREVIEWS = 2
        try:
            self.assertEqual(self.bot.send_previews(self.tg), 2)
            self.assertEqual(self.bot.send_previews(self.tg), 0)
        finally:
            self.bot.MAX_OPEN_PREVIEWS = 5

    # ------------------------------------------------------------------ decisions

    def test_approve_tap(self):
        name = "2026-11-29-card-of-the-day"
        self.tap("a:" + self.tag(name))
        result = self.bot.poll(self.tg)
        self.assertEqual(self.qk.status(self.tmp / name), "approved")
        self.assertTrue(result["changed"])
        self.assertEqual(result["ack_offset"], 2)
        self.assertEqual(result["post_now"], "")
        edit = [p for m, p in CALLS if m == "editMessageText"][0]
        self.assertIn("Approved", edit["text"])
        self.assertIn("Reject instead", edit["reply_markup"])

    def test_reject_then_note_then_change_of_mind(self):
        name = "2026-11-29-card-of-the-day"
        self.tap("r:" + self.tag(name), update_id=1)
        self.say("The watch-out is too vague", update_id=2)
        self.bot.poll(self.tg)
        folder = self.tmp / name
        self.assertEqual(self.qk.status(folder), "rejected")
        self.assertEqual(self.qk.read_json(folder / "rejected.json")["note"], "The watch-out is too vague")
        UPDATES.clear()
        self.tap("a:" + self.tag(name), update_id=3)
        self.bot.poll(self.tg)
        self.assertEqual(self.qk.status(folder), "approved")
        self.assertFalse((folder / "rejected.json").exists())

    def test_outdated_preview_cannot_approve(self):
        name = "2026-11-29-card-of-the-day"
        stale = "a:" + self.tag(name)
        caption = self.tmp / name / "caption.txt"
        caption.write_text(caption.read_text() + "\nedited")
        self.tap(stale)
        self.bot.poll(self.tg)
        self.assertEqual(self.qk.status(self.tmp / name), "queued")

    def test_strangers_are_ignored(self):
        name = "2026-11-29-card-of-the-day"
        self.tap("a:" + self.tag(name), chat="999")
        self.say("/status", update_id=2, chat="999")
        self.bot.poll(self.tg)
        self.assertEqual(self.qk.status(self.tmp / name), "queued")
        self.assertNotIn("sendMessage", self.methods())

    def test_late_approval_of_today_publishes_now(self):
        self.qk.utc_hour = lambda: 18
        self.tap("a:" + self.tag("2026-11-28-budget-combo"))
        result = self.bot.poll(self.tg)
        self.assertEqual(result["post_now"], "2026-11-28")

    def test_status_and_preview_commands(self):
        self.say("/status", update_id=1)
        self.say("/preview 2026-11-29", update_id=2)
        self.bot.poll(self.tg)
        replies = [p["text"] for m, p in CALLS if m == "sendMessage"]
        self.assertIn("needs review", replies[0])
        self.assertIn("on its way", replies[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
