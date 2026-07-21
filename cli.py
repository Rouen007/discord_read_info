#!/usr/bin/env python3
"""
discord — minimal Discord read CLI.

Five commands, all REST-based once token is cached. No DOM scraping, no opencli.

  discord fetch  <channel_id> [--days N | --hours N] [--author NAME] [--out PATH]
      Pull channel history via Discord REST API. --author filters client-side
      against author.username / author.global_name (case-insensitive substring).

  discord search <guild_id> "QUERY" [--channel CH] [--author-id ID] [--days N]
                                    [--max N] [--out PATH]
      Server-wide message search via Discord's REST search endpoint.

  discord images <channel_id> [--days N | --hours N] [--author NAME] [--out DIR]
                              [--all] [--from-json PATH]
      Download image attachments from channel history to a local directory.
      --all includes non-image files. --from-json skips fetching and reads
      from a previously saved JSON file.

  discord status
      Is the configured Chrome/CDP endpoint reachable?

  discord setup
      Launch Chrome with --remote-debugging-port and open discord.com.
      Only needed for first login or when the cached auth token expires.

Token cache:  ~/.local/state/discord-cli/token.json  (mode 600, fcntl-locked).
              Multi-process safe — multiple agents may call concurrently.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

CDP_ENDPOINT = (
    os.environ.get("DISCORD_CDP_ENDPOINT")
    or os.environ.get("OPENCLI_CDP_ENDPOINT")
    or "http://127.0.0.1:9222"
)
# Make the chosen endpoint visible to discord_api.py (which reads either env var).
os.environ["DISCORD_CDP_ENDPOINT"] = CDP_ENDPOINT
os.environ.setdefault("OPENCLI_CDP_ENDPOINT", CDP_ENDPOINT)

# Default Chrome user-data-dir for `discord setup`. Keeps the CLI's Chrome
# session isolated from the user's main browser profile.
DEFAULT_CHROME_PROFILE = str(Path.home() / ".local" / "state" / "discord-cli" / "chrome-profile")


# ── friendly-name registry ──────────────────────────────────────────────────
# Lives at ~/.config/discord-cli/channels.yaml (NOT shipped with the skill).
# Empty / missing config is fine — names just won't resolve.

CONFIG_PATH = Path(os.environ.get("DISCORD_CLI_CONFIG") or (Path.home() / ".config" / "discord-cli" / "channels.yaml"))

_SNOWFLAKE_RE = None


def _is_snowflake(s: str) -> bool:
    global _SNOWFLAKE_RE
    if _SNOWFLAKE_RE is None:
        import re
        _SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")
    return bool(_SNOWFLAKE_RE.match(s or ""))


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        import yaml  # PyYAML
    except ImportError:
        # Fall back to JSON if PyYAML isn't installed.
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            print(
                f"warning: PyYAML not installed and {CONFIG_PATH} isn't valid JSON; "
                "name resolution disabled (pip install pyyaml)",
                file=sys.stderr,
            )
            return {}
    try:
        return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception as e:
        print(f"warning: failed to parse {CONFIG_PATH}: {e}", file=sys.stderr)
        return {}


def _resolve_channel(name_or_id: str, cfg: dict) -> str:
    if _is_snowflake(name_or_id):
        return name_or_id
    entry = (cfg.get("channels") or {}).get(name_or_id.lower())
    if entry and entry.get("id"):
        return str(entry["id"])
    raise SystemExit(
        f"unknown channel '{name_or_id}'. Pass a numeric id or add it to {CONFIG_PATH}"
    )


def _resolve_guild(name_or_id: str, cfg: dict) -> str:
    if _is_snowflake(name_or_id):
        return name_or_id
    entry = (cfg.get("guilds") or {}).get(name_or_id.lower())
    if entry and entry.get("id"):
        return str(entry["id"])
    raise SystemExit(
        f"unknown guild '{name_or_id}'. Pass a numeric id or add it to {CONFIG_PATH}"
    )


def _resolve_author(alias: str, cfg: dict) -> list[str]:
    """Return list of substrings to match against author.username/global_name.
    Raw alias always included so users can also type the real name."""
    out = [alias]
    aliases = (cfg.get("author_aliases") or {}).get(alias.lower())
    if aliases:
        out.extend(aliases)
    # dedupe, preserve order
    seen, ordered = set(), []
    for s in out:
        if s and s.lower() not in seen:
            seen.add(s.lower())
            ordered.append(s)
    return ordered


def _cutoff_from(days, hours, default_hours=8) -> datetime:
    now = datetime.now(timezone.utc)
    if days is not None:
        return now - timedelta(days=days)
    if hours is not None:
        return now - timedelta(hours=hours)
    return now - timedelta(hours=default_hours)


def _emit(msgs: list, out_path: str | None) -> None:
    body = json.dumps(msgs, ensure_ascii=False, indent=2)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"saved {len(msgs)} messages → {out_path}", file=sys.stderr)
    else:
        print(body)


def _matches_author(msg: dict, needles: list[str]) -> bool:
    """Any-of substring match against author.username / author.global_name."""
    a = msg.get("author") or {}
    haystacks = [(a.get(f) or "").lower() for f in ("username", "global_name")]
    for n in needles:
        n = n.lower()
        if any(n in h for h in haystacks):
            return True
    return False


# ── subcommands ──────────────────────────────────────────────────────────────


def cmd_status(_a) -> int:
    import urllib.request
    try:
        body = urllib.request.urlopen(f"{CDP_ENDPOINT}/json/version", timeout=2).read()
        info = json.loads(body)
        print(json.dumps({"connected": True, "endpoint": CDP_ENDPOINT, "browser": info.get("Browser")}))
        return 0
    except Exception as e:
        print(json.dumps({"connected": False, "endpoint": CDP_ENDPOINT, "error": str(e)}))
        return 1


def cmd_setup(a) -> int:
    """Launch Chrome with --remote-debugging-port and open discord.com.

    Uses a dedicated user-data-dir so the user's main Chrome profile isn't affected.
    First time: the Chrome window opens on the Discord login page — the user logs in
    once, then closes the window when done. The auth cookie persists in the profile
    dir so future launches go straight to the app.
    """
    import time, urllib.request

    # If something is already listening on the endpoint, don't relaunch.
    try:
        urllib.request.urlopen(f"{CDP_ENDPOINT}/json/version", timeout=1).read()
        print(json.dumps({"step": "already_running", "endpoint": CDP_ENDPOINT}))
        return 0
    except Exception:
        pass

    # Pick a port from the endpoint URL.
    from urllib.parse import urlparse
    port = urlparse(CDP_ENDPOINT).port or 9222

    profile = Path(a.profile or DEFAULT_CHROME_PROFILE).expanduser()
    profile.mkdir(parents=True, exist_ok=True)

    chrome_bin = a.chrome or _detect_chrome()
    if not chrome_bin:
        print('{"error":"Chrome not found. Pass --chrome /path/to/Chrome."}', file=sys.stderr)
        return 1

    print(json.dumps({"step": "launching_chrome", "port": port, "profile": str(profile)}))
    subprocess.Popen(
        [
            chrome_bin,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://discord.com/app",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )

    for i in range(1, 31):  # up to 30s (Chrome cold start can be slow)
        try:
            urllib.request.urlopen(f"{CDP_ENDPOINT}/json/version", timeout=1).read()
            print(json.dumps({"step": "ready", "wait_seconds": i, "endpoint": CDP_ENDPOINT,
                              "note": "if first run, log into Discord in the Chrome window once."}))
            return 0
        except Exception:
            time.sleep(1)
    print('{"step":"waiting_cdp","status":"failed","error":"CDP not available after 30s"}')
    return 1


def _detect_chrome() -> str | None:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Arc.app/Contents/MacOS/Arc",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def cmd_fetch(a) -> int:
    import discord_api
    cfg = _load_config()
    channel_id = _resolve_channel(a.channel_id, cfg)
    cutoff = _cutoff_from(a.days, a.hours)
    try:
        token = discord_api.get_token()
    except Exception as e:
        print(f'{{"error":"get_token failed: {e}"}}', file=sys.stderr)
        return 1
    def checkpoint(partial_msgs: list) -> None:
        if not a.out:
            return
        tmp_path = f"{a.out}.partial"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(partial_msgs, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, a.out)

    try:
        msgs = discord_api.fetch_messages(channel_id, token, cutoff, on_page=checkpoint)
    except Exception as e:
        suffix = f'; partial data saved to {a.out}' if a.out and os.path.exists(a.out) else ''
        print(f'{{"error":"fetch failed: {e}{suffix}"}}', file=sys.stderr)
        return 1
    if a.author:
        needles = _resolve_author(a.author, cfg)
        msgs = [m for m in msgs if _matches_author(m, needles)]
    _emit(msgs, a.out)
    return 0


def cmd_search(a) -> int:
    import discord_api
    cfg = _load_config()
    guild_id = _resolve_guild(a.guild_id, cfg)
    channel_id = _resolve_channel(a.channel, cfg) if a.channel else None
    cutoff = _cutoff_from(a.days, None) if a.days is not None else None
    try:
        token = discord_api.get_token()
    except Exception as e:
        print(f'{{"error":"get_token failed: {e}"}}', file=sys.stderr)
        return 1
    try:
        msgs = discord_api.search_messages(
            guild_id=guild_id,
            token=token,
            query=a.query or "",
            channel_id=channel_id,
            author_id=a.author_id,
            cutoff=cutoff,
            max_results=a.max,
        )
    except Exception as e:
        print(f'{{"error":"search failed: {e}"}}', file=sys.stderr)
        return 1
    _emit(msgs, a.out)
    return 0


def cmd_channels(_a) -> int:
    """List configured channel/guild aliases."""
    cfg = _load_config()
    if not cfg:
        print(json.dumps({"config_path": str(CONFIG_PATH), "configured": False}, indent=2))
        return 0
    out = {
        "config_path": str(CONFIG_PATH),
        "guilds":   [{"alias": k, **v} for k, v in (cfg.get("guilds") or {}).items()],
        "channels": [{"alias": k, **v} for k, v in (cfg.get("channels") or {}).items()],
        "authors":  cfg.get("author_aliases") or {},
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_images(a) -> int:
    """Download image attachments from channel history."""
    import discord_api

    # Load messages: either from a previously saved JSON or by fetching live.
    if a.from_json:
        try:
            with open(a.from_json, "r", encoding="utf-8") as f:
                msgs = json.load(f)
            print(f"loaded {len(msgs)} messages from {a.from_json}", file=sys.stderr)
        except Exception as e:
            print(f'{{"error":"failed to read {a.from_json}: {e}"}}', file=sys.stderr)
            return 1
    else:
        if not a.channel_id:
            print('{"error":"channel_id is required unless --from-json is given"}', file=sys.stderr)
            return 1
        cfg = _load_config()
        channel_id = _resolve_channel(a.channel_id, cfg)
        cutoff = _cutoff_from(a.days, a.hours)
        try:
            token = discord_api.get_token()
        except Exception as e:
            print(f'{{"error":"get_token failed: {e}"}}', file=sys.stderr)
            return 1
        try:
            msgs = discord_api.fetch_messages(channel_id, token, cutoff)
        except Exception as e:
            print(f'{{"error":"fetch failed: {e}"}}', file=sys.stderr)
            return 1
        if a.author:
            cfg = _load_config()
            needles = _resolve_author(a.author, cfg)
            msgs = [m for m in msgs if _matches_author(m, needles)]

    out_dir = a.out or f"/tmp/discord_images_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    manifest = discord_api.download_attachments(msgs, out_dir, image_only=not a.all)
    print(json.dumps({
        "downloaded": len(manifest),
        "directory": out_dir,
        "manifest": f"{out_dir}/manifest.json",
    }, indent=2))
    return 0


# ── argparse wiring ──────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="discord", description="Minimal Discord read CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("fetch", help="pull channel history (REST)")
    sp.add_argument("channel_id")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--days", type=float)
    g.add_argument("--hours", type=float)
    sp.add_argument("--author", help="filter by author username/global_name (substring, case-insensitive)")
    sp.add_argument("--out", help="write JSON to PATH instead of stdout")
    sp.set_defaults(handler=cmd_fetch)

    sp = sub.add_parser("search", help="server-wide message search (REST)")
    sp.add_argument("guild_id")
    sp.add_argument("query", nargs="?", default="", help="content query (optional if --channel or --author-id given)")
    sp.add_argument("--channel", help="restrict to this channel id")
    sp.add_argument("--author-id", dest="author_id", help="restrict to this user id")
    sp.add_argument("--days", type=float, help="only messages newer than N days")
    sp.add_argument("--max", type=int, default=1000, help="max results (default 1000)")
    sp.add_argument("--out")
    sp.set_defaults(handler=cmd_search)

    sp = sub.add_parser("images", help="download image attachments from channel history")
    sp.add_argument("channel_id", nargs="?", default=None, help="channel alias or numeric id (not needed with --from-json)")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--days", type=float)
    g.add_argument("--hours", type=float)
    sp.add_argument("--author", help="filter by author (substring, case-insensitive)")
    sp.add_argument("--out", help="output directory for downloaded images")
    sp.add_argument("--all", action="store_true", help="download all attachments, not just images")
    sp.add_argument("--from-json", dest="from_json", help="read messages from a previously saved JSON file instead of fetching")
    sp.set_defaults(handler=cmd_images)

    sub.add_parser("channels", help="list configured channel/guild/author aliases").set_defaults(handler=cmd_channels)

    sub.add_parser("status", help="check CDP connectivity").set_defaults(handler=cmd_status)

    sp = sub.add_parser("setup", help="launch Chrome with --remote-debugging-port and open discord.com")
    sp.add_argument("--profile", help="Chrome user-data-dir (defaults to ~/.local/state/discord-cli/chrome-profile)")
    sp.add_argument("--chrome", help="path to Chrome/Chromium binary (auto-detected if omitted)")
    sp.set_defaults(handler=cmd_setup)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args) or 0


if __name__ == "__main__":
    sys.exit(main())
