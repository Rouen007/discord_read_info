# discord — minimal Discord read CLI

Four-command CLI for pulling Discord messages via the official REST API:

```
discord fetch    <channel>  [--days N | --hours N] [--author NAME] [--out PATH]
discord search   <guild>    "QUERY" [--channel CH] [--author-id ID] [--days N] [--max N]
discord channels                     # list configured aliases
discord status                       # is the CDP endpoint reachable?
discord setup                        # launch Chrome with --remote-debugging-port
```

No DOM scraping, no opencli dependency, no Discord Desktop required. Token is
extracted once via Chrome DevTools Protocol from a logged-in discord.com tab,
then cached locally so subsequent calls are pure REST.

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
