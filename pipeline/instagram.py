#!/usr/bin/env python3
"""
Instagram Graph API client for EDHPod (Instagram Login, Creator account).

    IG_ACCESS_TOKEN=... python3 instagram.py whoami
    IG_ACCESS_TOKEN=... python3 instagram.py limit
    IG_ACCESS_TOKEN=... python3 instagram.py refresh --out /path/to/new-token

Only the official publishing API is used — the one Meta permits for your own
account. Nothing here logs in as you or touches Instagram's private app API,
which is the kind of automation that gets accounts locked.

Three rules from PLAN.md that this file enforces:

* Caption on the carousel container, alt text on the children.
* Children are created one after another, not in parallel.
* `media_publish` is never blindly retried. If the call fails in a way that
  might have succeeded server-side, the recent feed is checked for the post
  before anything else happens, because a retry on a half-finished run
  double-posts.

The token never appears in output: it is sent in the request body or query
and stripped from every error message, so a failed request cannot leak it
into a CI log.
"""

import sys

if sys.version_info < (3, 8):
    raise SystemExit(
        "EDHPod needs Python 3.8 or newer; this is %d.%d. On this machine use:\n"
        "  /work/u19d26/miniforge3/envs/pygem3.9/bin/python3 <script>" % sys.version_info[:2]
    )

import argparse
import getpass
import os
import sys
import time

import requests

API_BASE = os.environ.get("IG_API_BASE", "https://graph.instagram.com")
# Graph API versions live roughly two years. v24.0 shipped October 2025.
API_VERSION = os.environ.get("IG_API_VERSION", "v24.0")

# Meta error codes that mean "try again shortly" rather than "you did it wrong".
TRANSIENT_CODES = {1, 2, 4, 17, 341, 368, 9004, 9007, 32, 613}


class InstagramError(RuntimeError):
    def __init__(self, message, code=None, subcode=None, status=None):
        super().__init__(message)
        self.code, self.subcode, self.status = code, subcode, status

    @property
    def transient(self) -> bool:
        return (self.status or 0) >= 500 or self.code in TRANSIENT_CODES


class Instagram:
    def __init__(self, token: str, session=None):
        if not token:
            raise SystemExit("IG_ACCESS_TOKEN is not set")
        self.token = token
        self.http = session or requests.Session()
        self._user_id = None

    # ------------------------------------------------------------------ plumbing

    def _scrub(self, text: str) -> str:
        return str(text).replace(self.token, "***")

    def _call(self, method: str, path: str, versioned: bool = True, **params) -> dict:
        url = "%s/%s%s" % (API_BASE, API_VERSION + "/" if versioned else "", path.lstrip("/"))
        params = {k: v for k, v in params.items() if v is not None}
        params["access_token"] = self.token
        try:
            if method == "GET":
                response = self.http.get(url, params=params, timeout=60)
            else:
                response = self.http.post(url, data=params, timeout=60)
        except requests.RequestException as error:
            # The exception text includes the URL, and a GET's URL holds the token.
            raise InstagramError("network error: %s" % self._scrub(error), status=599) from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or "error" in body:
            err = body.get("error") or {}
            raise InstagramError(
                self._scrub("%s (HTTP %s, code %s/%s, trace %s)" % (
                    err.get("error_user_msg") or err.get("message") or response.text[:300],
                    response.status_code, err.get("code"), err.get("error_subcode"),
                    err.get("fbtrace_id"),
                )),
                code=err.get("code"), subcode=err.get("error_subcode"),
                status=response.status_code,
            )
        return body

    def _retrying(self, method: str, path: str, attempts: int = 4, **params) -> dict:
        """Retry transient failures. Only for calls that are safe to repeat."""
        for attempt in range(attempts):
            try:
                return self._call(method, path, **params)
            except InstagramError as error:
                if not error.transient or attempt == attempts - 1:
                    raise
                wait = 15 * (attempt + 1)
                print("  transient error, retrying in %ds: %s" % (wait, error))
                time.sleep(wait)

    # ------------------------------------------------------------------ account

    def me(self) -> dict:
        return self._retrying("GET", "me", fields="user_id,username,account_type")

    @property
    def user_id(self) -> str:
        if not self._user_id:
            self._user_id = self.me()["user_id"]
        return self._user_id

    def publishing_limit(self) -> dict:
        data = self._retrying(
            "GET", "%s/content_publishing_limit" % self.user_id, fields="config,quota_usage"
        )
        return (data.get("data") or [{}])[0]

    def recent_media(self, limit: int = 10) -> list:
        data = self._retrying(
            "GET", "%s/media" % self.user_id,
            fields="id,caption,timestamp,permalink,media_type", limit=limit,
        )
        return data.get("data", [])

    def find_by_caption(self, caption: str, limit: int = 10):
        """The already-published post with this caption, if any."""
        wanted = " ".join(caption.split())
        for media in self.recent_media(limit):
            if " ".join((media.get("caption") or "").split()) == wanted:
                return media
        return None

    def permalink(self, media_id: str) -> str:
        return self._retrying("GET", media_id, fields="permalink").get("permalink", "")

    # ------------------------------------------------------------------ publishing

    def create_carousel_item(self, image_url: str, alt_text: str = None) -> str:
        try:
            data = self._retrying(
                "POST", "%s/media" % self.user_id,
                image_url=image_url, is_carousel_item="true", alt_text=alt_text,
            )
        except InstagramError as error:
            # Alt text on carousel children is documented but recent. If Meta
            # rejects the parameter itself, losing alt text beats losing the day.
            if alt_text and "alt_text" in str(error):
                print("::warning::Meta rejected alt_text, posting without it: %s" % error)
                return self.create_carousel_item(image_url, None)
            raise
        return data["id"]

    def create_image(self, image_url: str, caption: str, alt_text: str = None) -> str:
        """A single-image feed post (the welcome post)."""
        try:
            data = self._retrying(
                "POST", "%s/media" % self.user_id,
                image_url=image_url, caption=caption, alt_text=alt_text,
            )
        except InstagramError as error:
            if alt_text and "alt_text" in str(error):
                print("::warning::Meta rejected alt_text, posting without it: %s" % error)
                return self.create_image(image_url, caption, None)
            raise
        return data["id"]

    def create_carousel(self, children: list, caption: str) -> str:
        data = self._retrying(
            "POST", "%s/media" % self.user_id,
            media_type="CAROUSEL", children=",".join(children), caption=caption,
        )
        return data["id"]

    def wait_until_ready(self, container_id: str, timeout: int = 300) -> None:
        """There is no webhook; poll. FINISHED is the only state worth publishing."""
        deadline = time.time() + timeout
        while True:
            status = self._retrying("GET", container_id, fields="status_code,status")
            code = status.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError("container %s is %s: %s" % (container_id, code, status.get("status")))
            if code == "PUBLISHED":
                raise InstagramError("container %s is already published" % container_id)
            if time.time() > deadline:
                raise InstagramError("container %s still %s after %ds" % (container_id, code, timeout))
            time.sleep(5)

    def publish(self, container_id: str, caption: str) -> str:
        """
        Publish exactly once. On an ambiguous failure, look for the post in the
        feed instead of retrying; only an unambiguous refusal is re-raised.
        """
        try:
            return self._call("POST", "%s/media_publish" % self.user_id, creation_id=container_id)["id"]
        except InstagramError as error:
            if not error.transient:
                raise
            print("  publish call failed ambiguously (%s); checking the feed" % error)
        for _ in range(6):
            time.sleep(20)
            try:
                found = self.find_by_caption(caption)
            except InstagramError as error:
                print("  feed check failed: %s" % error)
                continue
            if found:
                print("  the post did go out")
                return found["id"]
        raise InstagramError(
            "media_publish failed and the post is not in the feed. NOT retrying "
            "automatically — check instagram.com/edhpod, then re-run the workflow "
            "if it is genuinely missing."
        )

    # ------------------------------------------------------------------ token

    def refresh(self) -> dict:
        """
        Exchange the long-lived token for a fresh 60-day one. Meta only allows
        this once the token is at least 24 hours old.
        """
        return self._call(
            "GET", "refresh_access_token", versioned=False, grant_type="ig_refresh_token"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("whoami", help="show the account the token belongs to")
    sub.add_parser("limit", help="show today's API publishing quota usage")
    refresh = sub.add_parser("refresh", help="refresh the token and write it to a file")
    refresh.add_argument("--out", required=True, help="file to write the new token to")
    args = parser.parse_args()

    token = os.environ.get("IG_ACCESS_TOKEN", "")
    if not token and args.command in ("whoami", "limit") and sys.stdin.isatty():
        token = getpass.getpass("Paste the Instagram access token (input is hidden), then Enter: ").strip()
    ig = Instagram(token)
    if args.command == "whoami":
        me = ig.me()
        print("@%s  user_id=%s  type=%s" % (me.get("username"), me.get("user_id"), me.get("account_type")))
    elif args.command == "limit":
        print(ig.publishing_limit())
    elif args.command == "refresh":
        data = ig.refresh()
        new = data.get("access_token")
        if not new:
            raise SystemExit("refresh returned no token")
        # Prove the new token works before anything replaces the old one.
        who = Instagram(new).me()
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(new)
        days = int(data.get("expires_in", 0)) // 86400
        print("refreshed token for @%s, valid for %d more days" % (who.get("username"), days),
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
