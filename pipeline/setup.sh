#!/usr/bin/env bash
# Rebuild the EDHPod render toolchain.
#
#     source pipeline/setup.sh
#
# The sandbox that renders the slides is wiped between sessions, so Chromium,
# one missing system library and three Python packages have to be put back each
# time. Everything lands outside the EDHPod folder on purpose: it is ~280 MB and
# does not belong in the user's Documents. Takes about three minutes cold, and
# is a no-op once everything is in place.
#
# Two things this works around, both discovered the hard way:
#   * `playwright install` downloads from a CDN that stalls in this sandbox and
#     background jobs do not survive between shell calls, so the browser zip is
#     fetched directly in one shot.
#   * There is no root here, so the one missing library is extracted from a .deb
#     into a private directory and reached via LD_LIBRARY_PATH rather than
#     installed with apt.

set -u

ROOT="${EDHPOD_TOOLCHAIN:-$HOME}"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.pw-browsers"
export LD_LIBRARY_PATH="$ROOT/extralibs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Pinned: the headless shell build must match the installed playwright, and
# `playwright --version` is the only honest source for which build that is.
CHROMIUM_BUILD="1255"
CHROMIUM_CDN="https://cdn.playwright.dev/builds/cft/159.0.8154.6/linux64/chrome-headless-shell-linux64.zip"
SHELL_DIR="$PLAYWRIGHT_BROWSERS_PATH/chromium_headless_shell-$CHROMIUM_BUILD/chrome-linux"

echo "==> Python packages"
python3 -c "import playwright, PIL, requests" 2>/dev/null \
  && echo "    already present" \
  || pip install --quiet --break-system-packages playwright pillow requests

echo "==> Chromium headless shell"
if [ -x "$SHELL_DIR/chrome-headless-shell" ]; then
  echo "    already present"
else
  mkdir -p "$SHELL_DIR"
  tmp="$(mktemp -d)"
  # -C resumes a partial download; this file is ~126 MB and the CDN is slow.
  curl -sL -C - -m 600 -o "$tmp/chs.zip" "$CHROMIUM_CDN" || {
    echo "    FAILED to download Chromium" >&2; return 1 2>/dev/null || exit 1; }
  unzip -q -o "$tmp/chs.zip" -d "$tmp"
  mv "$tmp"/chrome-headless-shell-linux64/* "$SHELL_DIR/"
  chmod +x "$SHELL_DIR/chrome-headless-shell"
  rm -rf "$tmp"
  echo "    installed"
fi

echo "==> Missing system library"
# Ubuntu 22.04's base image here lacks exactly one of Chromium's dependencies.
if [ -e "$ROOT/extralibs/libXdamage.so.1" ]; then
  echo "    already present"
else
  mkdir -p "$ROOT/extralibs"
  tmp="$(mktemp -d)"
  deb="pool/main/libx/libxdamage/libxdamage1_1.1.5-2build2_amd64.deb"
  curl -sL -m 120 -o "$tmp/x.deb" "http://archive.ubuntu.com/ubuntu/$deb" \
    && dpkg-deb -x "$tmp/x.deb" "$tmp/x" \
    && cp -a "$tmp/x"/usr/lib/x86_64-linux-gnu/libXdamage.so.1* "$ROOT/extralibs/" \
    && echo "    installed" || echo "    FAILED — check archive.ubuntu.com" >&2
  rm -rf "$tmp"
fi

echo "==> Verifying"
missing="$(ldd "$SHELL_DIR/chrome-headless-shell" 2>/dev/null | grep "not found" || true)"
if [ -n "$missing" ]; then
  echo "    unresolved libraries:" >&2
  echo "$missing" >&2
else
  echo "    all libraries resolved"
fi

echo
echo "Ready. Render with:"
echo "  cd pipeline && python3 render.py ../queue/<post>/post.json"
