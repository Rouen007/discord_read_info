#!/usr/bin/env python3
"""
Discord REST API fetcher — extracts auth token from Discord webpack bundle via CDP,
then fetches historical messages directly from the REST API.

Reliable alternative to DOM/scroll/loadMore approaches.

Usage:
  python3 discord_api.py <channel_id> [--hours N] [--days N] [--output path]
"""

import json, sys, os, time, asyncio, urllib.request, urllib.error, fcntl, tempfile
import websockets
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Default endpoint targets Chrome (multi-window, multi-agent friendly), not Discord Desktop.
# Honor both DISCORD_CDP_ENDPOINT (new) and OPENCLI_CDP_ENDPOINT (legacy) — first wins.
CDP_ENDPOINT = (
    os.environ.get("DISCORD_CDP_ENDPOINT")
    or os.environ.get("OPENCLI_CDP_ENDPOINT")
    or "http://127.0.0.1:9222"
)

# Token cache lives under XDG state dir (NOT /tmp, NOT inside the skill dir):
#   - persistent across reboots (no need to re-extract token after macOS /tmp cleanup)
#   - outside any git checkout of the skill
#   - per-user, mode 600
_STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")) / "discord-cli"
TOKEN_CACHE_PATH = str(_STATE_DIR / "token.json")
TOKEN_LOCK_PATH = str(_STATE_DIR / "token.lock")
TOKEN_CACHE_TTL = 3600  # re-use token for 1 hour


def _ensure_state_dir():
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(_STATE_DIR, 0o700)
    except OSError:
        pass


class _TokenLock:
    """fcntl-based advisory lock — safe for multi-process / multi-agent access."""

    def __init__(self, exclusive: bool = True):
        self._exclusive = exclusive
        self._fh = None

    def __enter__(self):
        _ensure_state_dir()
        self._fh = open(TOKEN_LOCK_PATH, "a+")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX if self._exclusive else fcntl.LOCK_SH)
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


# ── Token extraction ──────────────────────────────────────────────────────────

def _read_token_cache_unlocked():
    """Read cache without taking the lock. Caller is responsible for locking."""
    try:
        if os.path.exists(TOKEN_CACHE_PATH):
            with open(TOKEN_CACHE_PATH) as fh:
                data = json.load(fh)
            if time.time() - data.get("ts", 0) < TOKEN_CACHE_TTL:
                return data.get("token")
    except Exception:
        pass
    return None


def _read_any_token_cache_unlocked():
    """Read a cached token regardless of age.

    Discord tokens often remain valid beyond the local refresh TTL. Prefer trying
    a stale cached token over forcing CDP extraction, then let REST 401 invalidate
    the cache if the token is actually expired.
    """
    try:
        if os.path.exists(TOKEN_CACHE_PATH):
            with open(TOKEN_CACHE_PATH) as fh:
                data = json.load(fh)
            return data.get("token")
    except Exception:
        pass
    return None


def _load_token_cache():
    with _TokenLock(exclusive=False):
        return _read_token_cache_unlocked()


def _write_token_cache_unlocked(token):
    """Atomic temp+rename. Caller MUST hold the exclusive lock."""
    _ensure_state_dir()
    fd, tmp_path = tempfile.mkstemp(prefix=".token.", dir=str(_STATE_DIR))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump({"token": token, "ts": time.time()}, fh)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, TOKEN_CACHE_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _save_token_cache(token):
    """Take the exclusive lock and write atomically. Don't call this from
    inside an already-held lock — fcntl.flock blocks on re-acquire."""
    try:
        with _TokenLock(exclusive=True):
            _write_token_cache_unlocked(token)
    except Exception:
        pass


async def _extract_token_via_cdp():
    """Walk Discord's webpack module cache to find the auth token store.

    Looks for a CDP target whose URL contains `discord.com`. Works for both:
      • Chrome with a discord.com tab open (preferred — supports parallel agents)
      • Discord Desktop (single renderer, the URL is also discord.com)
    """
    data = urllib.request.urlopen(f"{CDP_ENDPOINT}/json/list").read()
    pages = json.loads(data)
    ws_url = None
    for p in pages:
        if p.get("type") != "page":
            continue
        if "discord.com" in (p.get("url") or ""):
            ws_url = p["webSocketDebuggerUrl"]
            break
    if not ws_url:
        raise RuntimeError(
            f"No discord.com tab found on CDP endpoint {CDP_ENDPOINT}. "
            "Open https://discord.com/app in Chrome (with --remote-debugging-port set), "
            "or run `discord setup`."
        )

    async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
        mid = [0]

        async def js(expr):
            mid[0] += 1
            await ws.send(json.dumps({
                "id": mid[0],
                "method": "Runtime.evaluate",
                "params": {"expression": expr, "returnByValue": True}
            }))
            return json.loads(await ws.recv()).get("result", {}).get("result", {}).get("value")

        token = await js("""
(function() {
  try {
    var moduleMap = {};
    webpackChunkdiscord_app.push([
      [Symbol("token-finder")], {},
      function(require) {
        for (var id in require.c) { moduleMap[id] = require.c[id].exports; }
      }
    ]);
    webpackChunkdiscord_app.pop();
    for (var id in moduleMap) {
      var m = moduleMap[id];
      if (!m) continue;
      var vals = [m, m.default, m.Z, m.ZP, m.q, m.t].filter(Boolean);
      for (var i = 0; i < vals.length; i++) {
        var v = vals[i];
        if (v && typeof v.getToken === "function") {
          try {
            var t = v.getToken();
            if (t && typeof t === "string" && t.length > 50) return t;
          } catch (e) {}
        }
      }
    }
  } catch (e) { return "err: " + e.message; }
  return null;
})()
""")
        return token


def get_token():
    """Return auth token from cache or live CDP extraction.

    Multi-process safe: if N agents miss the cache simultaneously, only one
    extracts via CDP — the rest block on the exclusive lock, re-read the cache,
    and reuse the freshly-written token.
    """
    cached = _load_token_cache()
    if cached:
        return cached

    with _TokenLock(exclusive=False):
        stale_cached = _read_any_token_cache_unlocked()
        if stale_cached:
            return stale_cached

    with _TokenLock(exclusive=True):
        cached = _read_token_cache_unlocked()  # double-check after lock acquired
        if cached:
            return cached
        token = asyncio.run(_extract_token_via_cdp())
        if token and isinstance(token, str) and len(token) > 50 and not token.startswith("err"):
            _write_token_cache_unlocked(token)  # still holding the lock — use unlocked variant
            return token
        raise RuntimeError(f"Could not extract Discord token: {token}")


def invalidate_token():
    """Clear cached token (call after 401). Safe under concurrent use."""
    with _TokenLock(exclusive=True):
        try:
            os.remove(TOKEN_CACHE_PATH)
        except FileNotFoundError:
            pass


# ── REST API ──────────────────────────────────────────────────────────────────

DISCORD_EPOCH_MS = 1420070400000  # Discord snowflake epoch


def snowflake_from_datetime(dt: datetime) -> int:
    """Convert a UTC datetime → Discord snowflake id (for min_id / max_id)."""
    ms = int(dt.timestamp() * 1000) - DISCORD_EPOCH_MS
    return max(0, ms) << 22


def _normalize(m: dict) -> dict:
    """Pluck the message fields we care about — same schema for fetch & search."""
    author = m.get("author") or {}
    out = {
        "id": m.get("id"),
        "channel_id": m.get("channel_id"),
        "timestamp": m.get("timestamp"),
        "author": {
            "id": author.get("id"),
            "username": author.get("username"),
            "global_name": author.get("global_name"),
        },
        "content": m.get("content", ""),
    }
    atts = m.get("attachments") or []
    if atts:
        out["attachments"] = [a.get("filename") for a in atts if isinstance(a, dict)]
    embeds = m.get("embeds") or []
    if embeds:
        out["embeds"] = [
            {"title": e.get("title"), "description": e.get("description")}
            for e in embeds if isinstance(e, dict)
        ]
    ref = m.get("referenced_message")
    if ref:
        ref_author = ref.get("author") or {}
        out["referenced_message"] = {
            "author": ref_author.get("username") or ref_author.get("global_name"),
            "content": (ref.get("content") or "")[:200],
        }
    return out


def _headers(token: str) -> dict:
    return {
        "Authorization": token,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko)"
        ),
        "Content-Type": "application/json",
    }


def _request_json(url: str, token: str):
    req = urllib.request.Request(url, headers=_headers(token))
    try:
        resp = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            invalidate_token()
        if e.code == 429:
            # Caller can catch + retry; surface the retry_after.
            try:
                ra = json.loads(body).get("retry_after", 1.0)
            except Exception:
                ra = 1.0
            raise _RateLimited(ra, body)
        raise RuntimeError(f"HTTP {e.code}: {body[:300]}")
    except Exception as e:
        raise RuntimeError(f"Request failed: {e}")
    return json.loads(resp.read())


class _RateLimited(Exception):
    def __init__(self, retry_after: float, body: str = ""):
        super().__init__(f"rate-limited; retry in {retry_after}s")
        self.retry_after = retry_after
        self.body = body


def fetch_messages(channel_id, token, cutoff: datetime, limit=100):
    """
    Fetch all messages in channel since `cutoff` (aware datetime, UTC).
    Returns list of normalized dicts, sorted chronologically.
    """
    all_msgs = []
    before = None

    while True:
        url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}"
        if before:
            url += f"&before={before}"

        try:
            msgs = _request_json(url, token)
        except _RateLimited as e:
            time.sleep(e.retry_after + 0.2)
            continue

        if not msgs:
            break

        reached_cutoff = False
        for m in msgs:
            raw_ts = m.get("timestamp", "")
            try:
                msg_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                continue

            if msg_dt < cutoff:
                reached_cutoff = True
                continue

            all_msgs.append(_normalize(m))

        if reached_cutoff or len(msgs) < limit:
            break

        before = msgs[-1]["id"]
        time.sleep(0.3)

    all_msgs.sort(key=lambda m: m["timestamp"] or "")
    return all_msgs


def search_messages(
    guild_id: str,
    token: str,
    query: str = "",
    channel_id: str | None = None,
    author_id: str | None = None,
    cutoff: datetime | None = None,
    max_results: int = 1000,
):
    """
    Hit Discord REST guild search.

    GET /api/v9/guilds/{guild_id}/messages/search
        ?content=...
        &channel_id=...
        &author_id=...
        &min_id=<snowflake-from-cutoff>
        &offset=N

    Returns flat list of normalized messages, newest first.
    """
    if not (query or channel_id or author_id):
        raise ValueError("search needs at least one of: query, channel_id, author_id")

    base = f"https://discord.com/api/v9/guilds/{guild_id}/messages/search"
    params = []
    if query:
        params.append(("content", query))
    if channel_id:
        params.append(("channel_id", channel_id))
    if author_id:
        params.append(("author_id", author_id))
    if cutoff:
        params.append(("min_id", str(snowflake_from_datetime(cutoff))))

    from urllib.parse import urlencode

    out: list = []
    offset = 0
    while len(out) < max_results:
        url = base + "?" + urlencode(params + [("offset", str(offset))])
        try:
            data = _request_json(url, token)
        except _RateLimited as e:
            time.sleep(e.retry_after + 0.2)
            continue

        msgs_groups = data.get("messages") or []
        if not msgs_groups:
            break

        for group in msgs_groups:
            # Each group is [primary_msg, ...context]. Take the primary (it has `hit: true`).
            primary = next((m for m in group if m.get("hit")), group[0] if group else None)
            if primary:
                out.append(_normalize(primary))

        if len(msgs_groups) < 25:  # Discord page size
            break
        offset += 25
        # Discord caps offset at 5000.
        if offset >= 5000:
            break
        time.sleep(0.3)

    return out[:max_results]


# No __main__ — call this module as a library from cli.py.
