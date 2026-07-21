# discord — minimal Discord read CLI

Five-command CLI for pulling Discord messages via the official REST API:

```
discord fetch    <channel>  [--days N | --hours N] [--author NAME] [--out PATH]
discord search   <guild>    "QUERY" [--channel CH] [--author-id ID] [--days N] [--max N]
discord images   <channel>  [--days N | --hours N] [--author NAME] [--out DIR]
                            [--all] [--from-json PATH]
discord channels                     # list configured aliases
discord status                       # is the CDP endpoint reachable?
discord setup                        # launch Chrome with --remote-debugging-port
```

No DOM scraping, no opencli dependency, no Discord Desktop required. Token is
extracted once via Chrome DevTools Protocol from a logged-in discord.com tab,
then cached locally so subsequent calls are pure REST.

## Agent read standard

For read-only Discord research, use this CLI first:

1. `discord channels` to confirm aliases, or pass raw Discord IDs.
2. `discord fetch <channel> --hours N --out /tmp/name.json` for channel history.
3. `discord search <guild> "QUERY" --days N --max N --out /tmp/name.json` for targeted pulls.
4. Report the output path, message count, UTC window, local-time window, filters, and any limitations.

Use browser/OpenCLI/DOM scraping only as a fallback when REST cannot cover the
task. If a wide `fetch` fails with an EOF/closed connection, retry with a smaller
time window or use targeted `search`.

Bot summaries can be embed-only: `content` may be empty while
`embeds[].description` contains the useful text.

## Install

```bash
# 1. Place the skill (or symlink it) under your Claude skills directory
ln -s /path/to/this/repo ~/.claude/skills/discord

# 2. Symlink the CLI into your PATH
ln -s ~/.claude/skills/discord/cli.py ~/.local/bin/discord
chmod +x ~/.claude/skills/discord/cli.py

# 3. Python deps (uses stdlib only — PyYAML optional, for YAML aliases)
python3 -m pip install --user pyyaml websockets

# 4. Sanity check
discord --help
```

## Configure

Friendly aliases live at `~/.config/discord-cli/channels.yaml` (mode 600).
Nothing in this repo should ever contain your real channel/guild/author IDs —
the registry is loaded at runtime.

```bash
mkdir -p ~/.config/discord-cli
cp channels.example.yaml ~/.config/discord-cli/channels.yaml
chmod 600 ~/.config/discord-cli/channels.yaml
$EDITOR ~/.config/discord-cli/channels.yaml
```

After editing, verify aliases load:

```bash
discord channels
```

## First-time login (token extraction)

The CLI needs an auth token from a logged-in Discord page. Run:

```bash
discord setup
```

This launches Chrome with `--remote-debugging-port=9222` against a **dedicated
profile** (`~/.local/state/discord-cli/chrome-profile/`) so your normal browser
isn't affected. Log into discord.com inside that window once — the cookie sticks
in the profile dir. Then trigger token extraction:

```bash
discord fetch <any-alias> --hours 1
```

Token is now cached at `~/.local/state/discord-cli/token.json` (mode 600,
fcntl-locked, multi-process safe). Chrome can be closed; future calls don't need it.

When the token expires (401 from the REST API), the cache auto-invalidates;
`discord setup` + one fetch refreshes it.

The CLI may attempt a stale cached token before CDP extraction. If it is truly
expired, REST 401 clears the cache.

## Output schema

Both `fetch` and `search` return normalized JSON messages:

```jsonc
{
  "id": "...",
  "channel_id": "...",
  "timestamp": "2026-06-23T19:45:12.345000+00:00",
  "author": { "id": "...", "username": "...", "global_name": "..." },
  "content": "...",
  "attachments": [
    {
      "filename": "screenshot.png",
      "url": "https://cdn.discordapp.com/...",
      "proxy_url": "https://media.discordapp.net/...",
      "content_type": "image/png",
      "size": 123456
    }
  ],
  "embeds": [{ "title": "...", "description": "..." }],
  "referenced_message": { "author": "...", "content": "first 200 chars..." }
}
```

## Downloading images

The `images` subcommand downloads image attachments from channel history to a
local directory:

```bash
# Download images from the past 2 days
discord images tradingroom --days 2 --out /tmp/trading_images

# Download only one author's images
discord images tradingroom --hours 12 --author frank --out /tmp/frank_charts

# Download ALL attachments (not just images)
discord images tradingroom --days 1 --all --out /tmp/all_files

# Download from a previously saved fetch JSON
discord fetch tradingroom --days 3 --out /tmp/msgs.json
discord images --from-json /tmp/msgs.json --out /tmp/images
```

Each download produces a `manifest.json` in the output directory:

```jsonc
[
  {
    "id": "1527316900328116314",
    "timestamp": "2026-07-17T14:30:00.000000+00:00",
    "content": "today's chart",
    "filename": "screenshot.png",
    "path": "/tmp/trading_images/1527316900328116314_0.png"
  }
]
```

## Multi-agent parallelism

The token cache lock makes concurrent calls safe — multiple Claude agents can
hit `discord fetch` / `discord search` at once. For *truly* parallel reads on
different Chrome windows, start each on its own port and point each agent at
its endpoint:

```bash
DISCORD_CDP_ENDPOINT=http://127.0.0.1:9223 discord fetch tradingroom --days 1
```

(Discord Desktop won't work for this — it's a single renderer process. Chrome
supports as many windows as you want.)

## What lives where

| Path | Tracked in repo? | Purpose |
|---|---|---|
| `cli.py` / `discord_api.py` | ✅ yes | the CLI |
| `SKILL.md` / `CLAUDE.md` / `AGENTS.md` / `README.md` | ✅ yes | docs |
| `channels.example.yaml` | ✅ yes | config schema |
| `config.json` | ✅ yes | skill metadata |
| `.gitignore` | ✅ yes | guards against accidental token/config commits |
| `~/.config/discord-cli/channels.yaml` | ❌ **no** | your private channel/guild aliases |
| `~/.local/state/discord-cli/token.json` | ❌ **no** | cached auth token |
| `~/.local/state/discord-cli/chrome-profile/` | ❌ **no** | Chrome user-data-dir for `setup` |

The skill ships with **zero** real IDs, tokens, or KOL names. Verify before
publishing:

```bash
grep -rE '1[0-9]{17,19}|MTQ[0-9A-Za-z._-]{20,}' . --include='*.{md,json,yaml,py}'
# only hits should be obvious placeholders like 1234567890123456789
```

## License

MIT (or whatever you prefer — adjust as needed).
