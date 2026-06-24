---
name: discord
description: Minimal Discord read CLI — fetch channel history and server-wide search via REST API. Four subcommands, no DOM scraping.
version: 3.1.0
tags: [discord, chat, search, read]
---

# Discord Skill

Tiny CLI that pulls Discord messages via the official REST API. Token is extracted
once from a logged-in Discord page on Chrome (via CDP) and cached at
`~/.local/state/discord-cli/token.json` (mode 600, fcntl-locked, multi-process safe).

Friendly channel/guild/author aliases live in
`~/.config/discord-cli/channels.yaml` (private, not shipped — see
`channels.example.yaml` for the schema).

## Commands

```
discord fetch    <channel>  [--days N | --hours N] [--author NAME] [--out PATH]
discord search   <guild>    "QUERY" [--channel CH] [--author-id ID] [--days N] [--max N] [--out PATH]
discord channels                              # show what aliases are configured
discord status                                # is the CDP endpoint reachable?
discord setup    [--profile DIR] [--chrome PATH]   # launch Chrome with CDP enabled
```

`<channel>` / `<guild>` accept either a numeric Discord ID **or** an alias defined
in `channels.yaml`. `--author NAME` matches client-side (substring, case-insensitive)
against `author.username` / `author.global_name`, optionally expanded via your
`author_aliases:` section.

## Setup

```bash
# 1. Copy the sample config and fill in YOUR channel/guild IDs
cp ~/.claude/skills/discord/channels.example.yaml ~/.config/discord-cli/channels.yaml
chmod 600 ~/.config/discord-cli/channels.yaml
$EDITOR ~/.config/discord-cli/channels.yaml

# 2. Launch Chrome with CDP and log into Discord once
discord setup
#    → opens a fresh Chrome window with a dedicated user-data-dir
#    → log into discord.com once; the cookie persists in the profile dir

# 3. Trigger first token extraction (any small fetch works)
discord fetch <your-channel-alias> --hours 1
#    → token gets cached; subsequent calls are instant REST hits
```

After the token is cached, Chrome can be closed. The token survives until you log
out or Discord rotates it. On 401, the cache is auto-invalidated; rerun
`discord setup` and one `fetch` to refresh.

## Examples

```bash
# Past 2 days from a configured channel
discord fetch tradingroom --days 2 --out /tmp/dc.json

# Filter by an author alias
discord fetch tradingroom --hours 8 --author frank

# Server-wide search inside one guild
discord search myguild "QCOM" --days 7

# Pass raw IDs if you don't want to configure aliases
discord fetch 1234567890123456789 --hours 6
```

## Output schema

Both `fetch` and `search` emit a JSON array of normalized messages:

```jsonc
[
  {
    "id": "...",
    "channel_id": "...",
    "timestamp": "2026-06-23T19:45:12.345000+00:00",   // UTC ISO 8601
    "author": { "id": "...", "username": "...", "global_name": "..." },
    "content": "...",
    "attachments": ["screenshot.png"],            // optional
    "referenced_message": {                       // optional, for replies
      "author": "...", "content": "first 200 chars..."
    }
  }
]
```

`fetch` is sorted oldest→newest; `search` is newest→oldest (Discord's native order).

## Time zone

Timestamps are UTC. Convert before showing the user:

```python
from datetime import datetime, timezone, timedelta
ET = timezone(timedelta(hours=-4))   # EDT; use -5 for EST
et = datetime.fromisoformat(m["timestamp"]).astimezone(ET).strftime("%m-%d %H:%M ET")
```

## Multi-process safety

Multiple agents can call `discord fetch` / `discord search` concurrently.

- Token cache uses `fcntl.flock` + atomic temp+rename.
- Cold cache miss: one process extracts via CDP, the rest block on the lock, then
  read the freshly-written token (double-checked locking — no duplicate work).
- For true parallel reads, start Chrome on multiple ports and pass each agent its
  own `DISCORD_CDP_ENDPOINT=http://127.0.0.1:<port>` — Chrome supports many
  independent windows; the Discord desktop client does not.

## Files

```
cli.py                  # CLI entry (symlinked from ~/.local/bin/discord)
discord_api.py          # token cache + REST helpers
channels.example.yaml   # sample config — copy to ~/.config/discord-cli/channels.yaml
README.md               # install / upload notes
```

User-private (NOT inside this skill, not in git):

```
~/.config/discord-cli/channels.yaml          # your channel/guild/author aliases
~/.local/state/discord-cli/token.json        # cached auth token (mode 600)
~/.local/state/discord-cli/chrome-profile/   # Chrome user-data-dir for setup
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `discord status` → `connected:false` | `discord setup` launches Chrome with the debug port |
| `get_token failed` / `no discord.com tab found` | Open discord.com in the CDP-enabled Chrome window |
| HTTP 401 | Token expired — rerun `discord setup` + one `fetch` to refresh |
| HTTP 429 | CLI honors `retry_after` automatically |
| `unknown channel 'foo'` | Add `foo` to `channels.yaml` or pass a numeric ID |
