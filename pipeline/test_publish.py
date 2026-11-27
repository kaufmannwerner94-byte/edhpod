#!/usr/bin/env python3
"""
End-to-end test of the publish path against a fake Instagram Graph API and a
fake GitHub Pages, both served locally. No network, no token, no real post.

    python3 test_publish.py

What it proves: approval is enforced, a dry run never publishes, the caption
goes on the carousel and the alt text on the children, a re-run never posts
twice — including when the publish call "fails" after Instagram actually
accepted it.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
USER = "17841400000000000"


class FakeMeta:
    def __init__(self):
        self.reset()

    def reset(self):
        self.mode = "instagram"
        self.containers = {}
        self.feed = []
        self.publish_calls = 0
        self.fail_publish_after_posting = False


META = FakeMeta()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        parts = url.path.strip("/").split("/")
        if parts[0] == "pages":
            return self._send(200, b"\xff\xd8fakejpeg", "image/jpeg")
        assert q.get("access_token") == "test-token", "token missing"
        if parts[1:] == ["me"]:
            if META.mode == "unified":  # a system user is not an Instagram account
                return self._send(200, {"id": "999", "name": "edhpod-publisher"})
            return self._send(200, {"user_id": USER, "username": "edhpod", "account_type": "MEDIA_CREATOR"})
        if parts[1:] == ["me", "assigned_instagram_accounts"]:
            return self._send(200, {"data": [{"id": USER}]})
        if parts[1:] == [USER] and q.get("fields") == "id,username":
            return self._send(200, {"id": USER, "username": "edhpod"})
        if parts[1:] == [USER, "media"]:
            return self._send(200, {"data": list(reversed(META.feed))})
        obj = parts[1]
        if obj in META.containers:
            return self._send(200, {"status_code": "FINISHED", "status": "Finished"})
        for media in META.feed:
            if media["id"] == obj:
                return self._send(200, {"permalink": media["permalink"]})
        return self._send(404, {"error": {"message": "unknown object", "code": 100}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
        assert form.pop("access_token") == "test-token"
        parts = self.path.strip("/").split("/")
        if parts[1:] == [USER, "media"]:
            cid = "c%d" % (len(META.containers) + 1)
            META.containers[cid] = form
            return self._send(200, {"id": cid})
        if parts[1:] == [USER, "media_publish"]:
            META.publish_calls += 1
            carousel = META.containers[form["creation_id"]]
            mid = "m%d" % (len(META.feed) + 1)
            META.feed.append({"id": mid, "caption": carousel["caption"],
                              "permalink": "https://www.instagram.com/p/%s/" % mid})
            if META.fail_publish_after_posting:
                return self._send(500, {"error": {"message": "internal", "code": 2}})
            return self._send(200, {"id": mid})
        return self._send(404, {"error": {"message": "no route", "code": 100}})


class PublishTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        cls.pages = base + "/pages"
        os.environ.update(IG_API_BASE=base, IG_API_VERSION="v26.0",
                          IG_ACCESS_TOKEN="test-token", IG_EXPECTED_USERNAME="edhpod")
        os.environ.pop("GITHUB_OUTPUT", None)
        sys.path.insert(0, str(HERE))
        import daily, instagram, queuekit
        cls.daily, cls.queuekit = daily, queuekit
        global testkit
        import testkit
        instagram.time.sleep = lambda s: None  # recovery waits are real-time otherwise
        daily.time.sleep = lambda s: None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    MODE = "instagram"

    def setUp(self):
        META.reset()
        META.mode = self.MODE
        os.environ["IG_LOGIN"] = self.MODE
        os.environ.pop("IG_USER_ID", None)
        self.tmp = Path(tempfile.mkdtemp())
        self.queuekit.QUEUE = self.tmp
        self.folder = testkit.make_post(self.tmp, "2026-11-28-card-of-the-day")
        (self.folder / "alt.json").write_text(json.dumps(["alt one", "alt two", "alt three"]))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_publish(self, *extra):
        sys.argv = ["daily.py", "publish", "--folder", self.folder.name,
                    "--base-url", self.pages, "--path", "x"] + list(extra)
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.daily.main()
        return code, out.getvalue()

    def approve(self):
        self.queuekit.write_json(self.folder / "approved.json",
                                 {"fingerprint": self.queuekit.fingerprint(self.folder)})

    def test_unapproved_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_publish()
        self.assertEqual(META.publish_calls, 0)

    def test_edit_after_approval_is_refused(self):
        self.approve()
        caption = self.folder / "caption.txt"
        caption.write_text(caption.read_text() + "\nedited")
        with self.assertRaises(SystemExit):
            self.run_publish()
        self.assertEqual(META.publish_calls, 0)

    def test_dry_run_never_publishes(self):
        code, out = self.run_publish("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertEqual(META.publish_calls, 0)
        self.assertFalse((self.folder / "published.json").exists())

    def test_publish_once_with_caption_and_alt_in_the_right_places(self):
        self.approve()
        code, out = self.run_publish()
        self.assertEqual(code, 0, out)
        children = [c for c in META.containers.values() if c.get("is_carousel_item")]
        carousel = [c for c in META.containers.values() if c.get("media_type") == "CAROUSEL"]
        self.assertEqual([c["alt_text"] for c in children], ["alt one", "alt two", "alt three"])
        self.assertTrue(all("caption" not in c for c in children))
        self.assertEqual(len(carousel), 1)
        self.assertIn("Lotus Cobra", carousel[0]["caption"])
        self.assertEqual(carousel[0]["children"].count(","), 2)
        self.assertTrue(children[0]["image_url"].endswith("/pages/x/slide1.jpg"))
        record = json.loads((self.folder / "published.json").read_text())
        self.assertEqual(record["media_id"], "m1")

        # Re-run: nothing happens.
        code, out = self.run_publish()
        self.assertIn("already published", out)
        self.assertEqual(META.publish_calls, 1)

    def test_lost_state_file_does_not_double_post(self):
        self.approve()
        self.run_publish()
        (self.folder / "published.json").unlink()
        code, out = self.run_publish()
        self.assertIn("already on the feed", out)
        self.assertEqual(META.publish_calls, 1)
        self.assertEqual(len(META.feed), 1)

    def test_ambiguous_publish_failure_is_resolved_from_the_feed(self):
        self.approve()
        META.fail_publish_after_posting = True
        code, out = self.run_publish()
        self.assertEqual(code, 0, out)
        self.assertIn("did go out", out)
        self.assertEqual(META.publish_calls, 1)
        self.assertTrue((self.folder / "published.json").exists())

    def test_welcome_is_a_single_image_post(self):
        self.folder = testkit.make_post(self.tmp, "2026-11-27-welcome")
        (self.folder / "alt.json").write_text(json.dumps(["welcome alt"]))
        self.approve()
        code, out = self.run_publish()
        self.assertEqual(code, 0, out)
        self.assertEqual(len(META.containers), 1)
        only = list(META.containers.values())[0]
        self.assertNotIn("is_carousel_item", only)
        self.assertNotIn("media_type", only)
        self.assertIn("Fan Content Policy", only["caption"])
        self.assertEqual(only["alt_text"], "welcome alt")
        self.assertEqual(META.publish_calls, 1)

    def test_token_never_printed(self):
        self.approve()
        _, out = self.run_publish()
        self.assertNotIn("test-token", out)


class UnifiedLoginPublishTest(PublishTest):
    """The same guarantees with a Unified-login system user token, which is
    what Meta gives every app created since late October 2026."""
    MODE = "unified"

    def test_account_comes_from_assigned_accounts(self):
        import instagram
        ig = instagram.Instagram("test-token")
        self.assertEqual(ig.user_id, USER)
        self.assertEqual(ig.me()["username"], "edhpod")


if __name__ == "__main__":
    unittest.main(verbosity=2)
