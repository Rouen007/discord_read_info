# Discord Skill

Minimal Discord read CLI. See `SKILL.md` for the full reference and
`channels.example.yaml` for the config schema.

Default to this REST CLI for read-only Discord work. Browser/OpenCLI/DOM
scraping is fallback only when REST cannot cover the task.

## TL;DR

```bash
discord fetch    <channel>  [--days N | --hours N] [--author NAME] [--out PATH]
discord search   <guild>    "QUERY" [--channel CH] [--author-id ID] [--days N]
discord channels                       # show what aliases are configured
discord status                         # is CDP endpoint reachable?
discord setup                          # launch Chrome with CDP and open discord.com
```

`<channel>` / `<guild>` accept a numeric Discord ID or an alias from
`~/.config/discord-cli/channels.yaml` (case-insensitive). Use `discord channels`
to see what's currently configured.

## Output schema

```jsonc
{ "id", "channel_id", "timestamp", "author": { "id", "username", "global_name" },
  "content", "attachments"?, "embeds"?: [{ "title", "description" }], "referenced_message"? }
```

Bot channels that post as rich embeds (AlphaAgent, UW Live Options Flow, etc.) have
empty `content` — the actual message text is in `embeds[].description`. Always check
both fields when parsing bot output.

`timestamp` is UTC ISO 8601 — always convert to whatever local zone the user
expects before showing.

When reporting a read, include the output path, message count, UTC window,
local-time window, filters, and any partial coverage.

## Persistence

| Path | Purpose |
|---|---|
| `~/.config/discord-cli/channels.yaml` | private channel/guild/author aliases |
| `~/.local/state/discord-cli/token.json` | cached auth token (mode 600, fcntl-locked) |
| `~/.local/state/discord-cli/chrome-profile/` | Chrome user-data-dir created by `discord setup` |

None of these live inside the skill directory, so the skill itself can be
shared/uploaded freely.
